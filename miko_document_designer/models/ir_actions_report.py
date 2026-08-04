# -*- coding: utf-8 -*-
"""Where the design reaches the paper.

Two hooks, both chosen because they behave identically on 16, 17, 18 and 19:

* ``_prepare_html`` is the last place the report is still HTML and is already
  split into the body, header and footer documents wkhtmltopdf is handed. Core
  keeps only the ``.article``, ``.header`` and ``.footer`` nodes and throws the
  rest of the page away, so a stylesheet appended anywhere else in the template
  never reaches the PDF. Injecting into the ``<head>`` of the documents core
  itself just built avoids that entirely, and covers every report and every
  layout - including layouts we did not write.
* ``_render_qweb_pdf`` is the last place it is still a PDF we can add pages to.

Neither hook is allowed to break a print. A corrupt letterhead uploaded by a
merchant must cost them a warning in the log, not the ability to invoice.
"""
import base64
import io
import logging
import re

from odoo import _, models
from odoo.tools.pdf import merge_pdf

from . import document_html
from .design import UNSCOPED_ARTICLE, build_css, build_watermark_html

_logger = logging.getLogger(__name__)

try:  # PyPDF2 1.26 on 16 and 17, 2.12 on 18 and 19
    from odoo.tools.pdf import PdfFileReader, PdfFileWriter
except ImportError:  # pragma: no cover - depends on the series' bundled lib
    from PyPDF2 import PdfFileReader, PdfFileWriter

BODY_TAG = re.compile(r'(<body[^>]*>)', re.IGNORECASE)

# The one2many a document keeps its printed lines in, whatever the module that
# owns it calls them. Probed in order; the first one that exists and carries
# products is used. Anything not on this list simply gets no pictures.
LINE_FIELDS = (
    'invoice_line_ids',        # account.move
    'order_line',              # sale.order, purchase.order
    'move_ids_without_package',  # stock.picking on 16, 17 and 18
    'move_ids',                # stock.picking on 19: the field was renamed
    'move_lines',              # stock.picking on the oldest series
    'move_line_ids',
    'line_ids',
)

# display_type values that still mean "a product line". False is what core
# writes on 16, 17 and 18; 'product' is what 19 writes.
PRODUCT_DISPLAY_TYPES = (False, '', 'product')

# Magic prefixes of a base64 payload, so an uploaded JPEG is not announced as a
# PNG. Sniffed from the base64 itself to avoid decoding the whole image.
_B64_MIME = (
    ('iVBORw0KGgo', 'image/png'),
    ('/9j/', 'image/jpeg'),
    ('R0lGOD', 'image/gif'),
    ('UklGR', 'image/webp'),
    ('PHN2Zw', 'image/svg+xml'),
)


def _data_uri(value):
    if not value:
        return None
    raw = value.decode() if isinstance(value, bytes) else value
    mime = 'image/png'
    for prefix, candidate in _B64_MIME:
        if raw.startswith(prefix):
            mime = candidate
            break
    return 'data:%s;base64,%s' % (mime, raw)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    # -- resolution ------------------------------------------------------
    def _miko_resolve(self, report_ref, res_ids):
        """The design and company that apply to this particular print."""
        report = self._get_report(report_ref)
        company = self.env.company
        record = None
        if res_ids and report.model and report.model in self.env:
            records = self.env[report.model].sudo().browse(res_ids).exists()
            if records:
                record = records[0]
                if 'company_id' in record._fields and record.company_id:
                    company = record.company_id
        return company.sudo()._miko_design_for(record=record, report=report), company

    # -- HTML ------------------------------------------------------------
    def _miko_style_block(self):
        """The <style> tag injected into every document of this print.

        Every company gets its own scoped block, because one wkhtmltopdf call
        can carry documents from several companies. The company this print
        actually resolved to gets the design WITH its rule applied, and gets it
        instead of - not after - its plain company block: a cascade can override
        a value but cannot un-set one, so a rule that turns striped rows off
        would otherwise still print stripes.
        """
        design = self.env.context.get('miko_design')
        design_company_id = self.env.context.get('miko_design_company')
        blocks = []
        for company in self.env['res.company'].sudo().search([]):
            if design and company.id == design_company_id:
                continue
            blocks.append(build_css(company._miko_design_values(),
                                    'o_company_%s_layout' % company.id))
        if design and design_company_id:
            blocks.append(build_css(design,
                                    'o_company_%s_layout' % design_company_id))
            # And the reports core never stamps with a company at all - the
            # picking operations slip is one - which would otherwise be the only
            # document in the database that ignores the design.
            blocks.append(build_css(design, selector=UNSCOPED_ARTICLE))
        css = '\n'.join(block for block in blocks if block)
        return '<style type="text/css">\n%s\n</style>' % css if css else ''

    def _miko_watermark_block(self):
        design = self.env.context.get('miko_design')
        if not design:
            return ''
        return build_watermark_html(
            design, image_data_uri=_data_uri(design.get('watermark_image')))

    def _miko_decorate(self, document, style, watermark):
        """Put the stylesheet in the head and the watermark at the top of body."""
        if not document:
            return document
        markup_type = type(document)
        text = str(document)
        if style and '</head>' in text:
            text = text.replace('</head>', style + '</head>', 1)
        elif style:
            text = style + text
        if watermark:
            new_text, count = BODY_TAG.subn(
                lambda match: match.group(1) + watermark, text, count=1)
            text = new_text if count else watermark + text
        # Keep whatever string type core handed us (Markup on every series that
        # has it) so the caller's own concatenation does not escape our markup.
        return markup_type(text)

    # -- document content ------------------------------------------------
    def _miko_record_of(self, article):
        """The record an article node was rendered for, if we can name it."""
        model = article.get('data-oe-model')
        res_id = article.get('data-oe-id')
        if not model or not res_id or model not in self.env:
            return None
        try:
            record = self.env[model].sudo().browse(int(res_id)).exists()
        except (TypeError, ValueError):
            return None
        return record or None

    def _miko_line_items(self, record):
        """(label, image data URI) per printed product line, in document order.

        The label is what the document actually prints for that line, so the
        pairing check downstream compares like with like.
        """
        for fname in LINE_FIELDS:
            if fname not in record._fields:
                continue
            lines = record[fname]
            if not lines or 'product_id' not in lines._fields:
                continue
            if 'display_type' in lines._fields:
                lines = lines.filtered(
                    lambda line: line.display_type in PRODUCT_DISPLAY_TYPES)
            if not lines:
                continue
            items = []
            for line in lines:
                product = line.product_id
                label = ''
                if 'name' in line._fields and line.name:
                    label = line.name
                elif product:
                    label = product.display_name
                image = product.image_128 if product and 'image_128' in product._fields else False
                items.append((label, _data_uri(image)))
            return items
        return []

    def _miko_amount_in_words(self, record):
        """The document's total, written out, or '' if it has no total."""
        if 'currency_id' not in record._fields or 'amount_total' not in record._fields:
            return ''
        currency = record.currency_id
        if not currency:
            return ''
        try:
            return currency.amount_to_text(record.amount_total) or ''
        except Exception:  # noqa: BLE001 - not every currency can be spelled
            _logger.warning("Miko Document Designer: %s cannot be written out "
                            "in words; the block was skipped.", currency.name)
            return ''

    def _miko_bank_rows(self, record):
        """(bank name, account number) for the accounts to print."""
        if 'partner_bank_id' in record._fields and record.partner_bank_id:
            # The account the document itself tells the customer to pay into.
            # Printing any other one would send money to the wrong place, so it
            # wins over the company's list.
            banks = record.partner_bank_id
        else:
            company = (record.company_id
                       if 'company_id' in record._fields and record.company_id
                       else self.env.company)
            banks = company.sudo().partner_id.bank_ids[:2]
        return [(bank.bank_id.name, bank.acc_number) for bank in banks]

    def _miko_totals_html(self, record, design):
        """The blocks that belong under the totals, as one HTML fragment.

        Whether the document HAS totals is decided by the document itself, in
        `inject_after_totals`: a delivery note never shows a totals block, so it
        never receives one of these either.
        """
        words = ''
        if design.get('amount_words'):
            words = self._miko_amount_in_words(record)
        rows = []
        if design.get('bank_block'):
            rows = self._miko_bank_rows(record)
        return document_html.build_totals_block(
            document_html.build_words_block(_("Total in words:"), words),
            document_html.build_bank_block(
                design.get('bank_title') or _("Payment details"), rows),
        )

    def _miko_anyone_wants_content(self):
        companies = self.env['res.company'].sudo().search([
            ('miko_design_active', '=', True),
            '|', '|',
            ('miko_line_images', '=', True),
            ('miko_amount_words', '=', True),
            ('miko_bank_block', '=', True),
        ], limit=1)
        if companies:
            return True
        return bool(self.env['miko.document.rule'].sudo().search([
            '|', '|',
            ('line_images', '=', 'on'),
            ('amount_words', '=', 'on'),
            ('bank_block', '=', 'on'),
        ], limit=1))

    def _miko_transform(self, html):
        """Add what the report engine had no way to know we wanted.

        Done before core splits the document, so the header/footer/article
        split still happens exactly as core intends, and done per article so a
        batch of fifty invoices resolves its rules per customer rather than
        once for the whole run.
        """
        design_default = self.env.context.get('miko_design')
        wants = ('line_images', 'amount_words', 'bank_block')
        if design_default is not None:
            if not design_default.get('active'):
                return html
            if not any(design_default.get(key) for key in wants):
                return html
        elif not self._miko_anyone_wants_content():
            # No context to go on: this is a direct call rather than a print.
            # Two cheap queries beat parsing every rendered report for nothing.
            return html
        try:
            root = document_html.parse(html)
        except Exception:  # noqa: BLE001 - never lose a document to a parse
            _logger.warning("Miko Document Designer: could not read the "
                            "rendered document; it was left untouched.",
                            exc_info=True)
            return html
        touched = False
        for article in document_html.find_article_nodes(root):
            record = self._miko_record_of(article)
            if record is None:
                continue
            design = record.company_id.sudo()._miko_design_for(record=record, report=self) \
                if 'company_id' in record._fields and record.company_id \
                else (design_default or self.env.company.sudo()._miko_design_for(record=record, report=self))
            if not design.get('active'):
                continue
            if design.get('line_images'):
                items = self._miko_line_items(record)
                if items and document_html.inject_line_images(
                        article, items, size=design.get('line_image_size') or 48):
                    touched = True
            fragment = self._miko_totals_html(record, design)
            if fragment and document_html.inject_after_totals(article, fragment):
                touched = True
        if not touched:
            return html
        return document_html.serialise(root)

    def _prepare_html(self, html, report_model=False):
        html = self._miko_transform(html)
        result = super()._prepare_html(html, report_model=report_model)
        if not isinstance(result, tuple) or len(result) != 5:
            return result
        style = self._miko_style_block()
        watermark = self._miko_watermark_block()
        if not style and not watermark:
            return result
        bodies, res_ids, header, footer, paperformat_args = result
        bodies = [self._miko_decorate(body, style, watermark) for body in bodies]
        header = self._miko_decorate(header, style, '')
        footer = self._miko_decorate(footer, style, '')
        return bodies, res_ids, header, footer, paperformat_args

    # -- PDF -------------------------------------------------------------
    def _miko_underlay(self, pdf_content, letterhead):
        """Draw every page of the document on top of the letterhead's page 1.

        Merging rather than rasterising keeps the document's own text
        selectable and searchable, which a background image would not.
        """
        source = PdfFileReader(io.BytesIO(pdf_content), strict=False)
        writer = PdfFileWriter()
        add_page = getattr(writer, 'add_page', None) or writer.addPage
        for index in range(len(source.pages)):
            # Re-read the letterhead for each page: a merged page object is
            # mutated in place, so one shared copy would stack every page of
            # the document onto the same sheet.
            stamp = PdfFileReader(io.BytesIO(letterhead), strict=False).pages[0]
            merge = getattr(stamp, 'merge_page', None) or stamp.mergePage
            merge(source.pages[index])
            add_page(stamp)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    def _miko_apply_pdf(self, pdf_content, design):
        if not pdf_content:
            return pdf_content
        letterhead = design.get('letterhead_pdf')
        if letterhead:
            try:
                pdf_content = self._miko_underlay(
                    pdf_content, base64.b64decode(letterhead))
            except Exception:  # noqa: BLE001 - a bad upload must not stop a print
                _logger.warning(
                    "Miko Document Designer: the letterhead PDF could not be "
                    "applied and was skipped for this document.", exc_info=True)
        append = design.get('append_pdf')
        if append:
            try:
                pdf_content = merge_pdf([pdf_content, base64.b64decode(append)])
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "Miko Document Designer: the appended PDF could not be "
                    "added and was skipped for this document.", exc_info=True)
        return pdf_content

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        design, company = self._miko_resolve(report_ref, res_ids)
        this = self.with_context(miko_design=design, miko_design_company=company.id)
        result = super(IrActionsReport, this)._render_qweb_pdf(
            report_ref, res_ids=res_ids, data=data)
        if not (isinstance(result, tuple) and len(result) == 2):
            return result
        content, report_type = result
        if report_type != 'pdf' or not design.get('active'):
            return result
        return this._miko_apply_pdf(content, design), report_type
