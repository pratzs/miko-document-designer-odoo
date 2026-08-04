# Miko Document Designer for Odoo

One screen for the whole look of every printed document, and **no dependencies**:
the manifest declares `web` and nothing else, so installing it does not pull
Invoicing, Sales or Purchase onto a database that did not ask for them.

| | |
|---|---|
| Technical name | `miko_document_designer` |
| Series | 16.0, 17.0, 18.0, 19.0 |
| Licence | OPL-1 (paid) |
| Price | per series: 99 / 149 / 179 / 199 USD (set in `_dev/build_versions.py`) |
| Category | Accounting |
| Colour | Rosewood `#C0897C` / `#8E4A3A` |
| Tests | 86, certified 4/4 |

## What it does

Odoo's own `base.document.layout` gives a merchant a logo, two colours, a font
and a layout. This adds everything after that:

- **Line table** - striped rows in a chosen colour, numbered lines, compact or
  roomy rows, horizontal rules / full grid / none, a coloured header row.
- **Product pictures** on the printed lines.
- **Watermark** - text or image, with angle, size and opacity, on every page.
- **Letterhead PDF** printed *behind* every page, merged rather than
  rasterised so the document's own text stays selectable.
- **Appended PDF** - terms and conditions after the last page.
- **Total in words** and a **bank details block**.
- **Rules** - one customer, or one document type, printing differently.

## The two decisions everything else follows from

**1. Write through, never shadow.** Every field core already owns - `logo`,
`primary_color`, `font`, `paperformat_id`, `external_report_layout_id`,
`report_header`, `report_footer`, `company_details`, `layout_background` - is
surfaced on our screen as a `related` field and written straight back to
`res.company`. The designer model is core's own `base.document.layout` extended
by prototype inheritance, so the merchant does the whole job in one place, other
modules reading `primary_color` get the truth, and uninstalling leaves their
branding exactly as they set it.

**2. Do the work after the report is rendered, not inside it.** Every feature
above used to mean inheriting `account.report_invoice_document`,
`sale.report_saleorder_document` and `purchase.report_purchaseorder_document` -
three apps installed for a buyer who wanted a nicer invoice. Instead:

- `ir.actions.report._prepare_html` injects a scoped stylesheet into the
  `<head>` of the body, header and footer documents core has just built, and the
  watermark into the body. Core keeps only the `.article`, `.header` and
  `.footer` nodes and throws the rest of the page away, so a stylesheet
  anywhere else never reaches the PDF.
- The same hook does the DOM work (pictures, total in words, bank block) with
  lxml, anchored on `table.o_main_table`, `div#total` and the
  `o_line_section` / `o_line_subsection` / `o_line_note` / `is-subtotal` row
  classes - all of which are core's own and identical on 16 to 19.
- `_render_qweb_pdf` merges the letterhead under every page and appends the
  terms.

The result reaches every document any module prints, including ones that did not
exist when this was written.

## Things learned here the hard way

1. **`res.groups.category_id` does not exist on Odoo 19.** It became
   `privilege_id` pointing at a new `res.groups.privilege` model. Naming either
   one fails to load on half the series; the field is cosmetic, so the group
   carries neither.
2. **A percentage `top` cannot position anything in an Odoo PDF.** Core's
   `minimal_layout` opens with `<html style="height: 0;">`, so every percentage
   height resolves against nothing. `top: 42%` became `top: 0` and printed
   "DRAFT" as "DRAF" with its tail lying across the address block. Only a real
   PDF showed it - the HTML was perfect. Watermark offsets are pixels.
3. **wkhtmltopdf is QtWebKit: it ignores unprefixed `transform`.**
   `-webkit-transform` is required, not belt and braces.
4. **Bootstrap 5 stripes tables with an inset `box-shadow`, not a background**,
   so a `background-color` alone is painted over. Zebra rows set both.
5. **A trailing space inside `<strong>` is collapsed**, and a `&#160;` measures
   a few pixels at report sizes. The gap after a label has to be a margin.
6. **On Odoo 16 `account.move.create` needs an explicit `journal_id`**; the
   default comes from a context an ordinary `create()` does not carry, and the
   failure surfaces as a `CacheMiss` inside account's own create.
7. **The class name appears in the stylesheet before the element appears in the
   body.** Three tests asserted on `'miko-watermark'` and passed on the CSS
   rule. Assert on the element (`<div class="miko-watermark">`).
8. **Core does not put `o_main_table` on every line table.** Stock's delivery
   slip identifies its tables with `name="stock_move_table"` and
   `name="stock_move_line_table"` instead, and the attribute survives into the
   rendered HTML. A design that only knew the class left packing slips
   completely undesigned.
9. **Core does not stamp every report with a company either.**
   `stock.report_picking` renders its article as `article
   o_report_layout_standard` with no `o_company_N_layout`, so a stylesheet
   scoped by company reaches every document except that one. There is a
   deliberate unscoped fallback for exactly those.
10. **A bank block belongs only on a document that shows totals.** An earlier
    version fell back to appending the block at the end of the article when
    there was no `div#total`, which printed "How to pay us" and an account
    number on a real packing slip. No totals block, no payment block.
11. **Odoo caches a posted invoice's PDF as an attachment and re-serves it.**
    Re-rendering after a design change returns the byte-identical old file. That
    is core behaviour and correct - a printed invoice is a record - but it means
    a design change does not retro-fit invoices already generated.

## Build, certify, verify

```bash
python3 _dev/build_versions.py                       # writes build/16.0 .. 19.0
cd ../_odoo-portfolio
./certify.sh miko-document-designer-odoo miko_document_designer 85
```

`build/` is generated - never edit it. The build script also writes the
per-series **price** into each manifest, which is how one module carries four
prices on the store.

### Verifying the PDF by hand (required before any release)

The automated suite deliberately does not drive wkhtmltopdf: core falls back to
HTML rendering inside a test run, and forcing the binary from a test cursor
risks the suite hanging on an HTTP round trip to its own server. So the PDF is
verified by hand, and this is the procedure:

```bash
docker run -d --name ddtest --network dev_default -p 8169:8069 \
  -v "$PWD/build/19.0":/mnt/app:ro odoo:19 \
  odoo --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/app \
  --db_host=dev-db-1 --db_user=odoo --db_password=odoo \
  -d dd19live -i miko_document_designer,sale_management --without-demo=False
# then pipe _dev/render/render_check.py through `odoo shell` and read the PDFs
```

`_dev/render/render_check.py` sets a full design, renders a real quotation three
ways (designed / with letterhead and appended terms / with the design switched
off) and prints the page counts. Open the PDFs and look at them.

Checked on a real render, 2026-08-04, Odoo 19: product pictures paired to the
right lines, numbered lines, striped rows, coloured header row, compact rows,
the watermark whole and centred, the total in words, the bank block, the
letterhead behind page 1 with the text still selectable, and the terms as
page 2.

Checked again on 2026-08-04 across the whole document set on Odoo 19 -
invoice, quotation, sales order, purchase order, delivery note and picking
operations - with `_dev/render/render_documents.py`. All six carry the design.
That run is what found the stock-table, unscoped-report and packing-slip-bank
defects listed above.

**Still on the by-hand list**, because no model in a database without Invoicing
has the field: a document that carries its own `partner_bank_id` must print
*that* account rather than the company's first one.

## Still to do before it is live

Only one step, and it cannot be done from here: register the repository at
https://apps.odoo.com/apps/dashboard/repos, one URI per series, and press Scan
on every row. Odoo does not poll - nothing appears on the store until each row
is scanned.

    ssh://git@github.com/pratzs/miko-document-designer-odoo.git#16.0
    ssh://git@github.com/pratzs/miko-document-designer-odoo.git#17.0
    ssh://git@github.com/pratzs/miko-document-designer-odoo.git#18.0
    ssh://git@github.com/pratzs/miko-document-designer-odoo.git#19.0

## Listing assets

| Asset | Where | Built by |
|---|---|---|
| Animated cover | `miko_document_designer/images/banner.gif` | `_dev/render/make_banner_gif.py` |
| Still cover | `miko_document_designer/images/banner.png` | same script, last frame |
| Icon | `static/description/icon.png` | `Miko App Icons/Miko Mark/make-icon.cjs`, Rosewood |
| Layout thumbnails | `static/img/layout_*.png` | headless Chrome from a mock sheet |
| Description body | `static/description/index.html` | inline styles only, absolute image URLs |
| Screenshots | `static/description/screenshot_*.png` | `_dev/render/shoot.py` against a real Odoo 19 |
| Document gallery | `static/description/screenshot_documents.png` | `_dev/render/render_documents.py` + `make_gallery.py` |

The description body's images are absolute jsDelivr URLs on the `assets-1.0.0`
tag. **Never force-move that tag** - GitHub raw and jsDelivr serve tags as
immutable and keep serving the old content. Mint a new tag instead.

Screenshots are taken with `_dev/render/seed.py` piped through `odoo shell`
first, so the rules in them are real records rather than an empty state.
