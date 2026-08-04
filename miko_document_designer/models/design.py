# -*- coding: utf-8 -*-
"""The design vocabulary, and the pure functions that turn it into CSS/HTML.

Kept free of the ORM on purpose: the CSS builder is the part most likely to be
wrong in a way tests can catch cheaply, and a pure function can be exercised
without a database. The ORM side (res.company, miko.document.rule) only decides
WHICH values apply; this module decides what they mean.

Nothing here emits anything for a value left at its default. A freshly installed
module must not change a single printed document until somebody designs one, so
`build_css` on the default design returns an empty string.
"""

# Every key here is a design knob. The value is the neutral default: the state
# in which we emit nothing at all and Odoo prints exactly as it did before.
DEFAULTS = {
    'active': True,
    # typography
    'base_font_size': 0,        # px, 0 = leave Odoo's
    'table_font_size': 0,       # px, 0 = leave Odoo's
    'line_height': 0,           # %, 0 = leave Odoo's
    # line table
    'density': 'default',       # default | compact | roomy
    'zebra': False,
    'zebra_color': '#F2F4F7',
    'row_numbers': False,
    'grid': 'default',          # default | rows | grid | none
    'head_bg': '',
    'head_color': '',
    'line_images': False,
    'line_image_size': 48,      # px
    # stamp
    'watermark_type': 'none',   # none | text | image
    'watermark_text': '',
    'watermark_image': False,   # base64 bytes
    'watermark_opacity': 12,    # %
    'watermark_angle': -30,     # degrees
    'watermark_size': 90,       # px
    # paper
    'letterhead_pdf': False,    # base64 bytes, printed behind every page
    'append_pdf': False,        # base64 bytes, appended after the last page
    # invoice blocks
    'amount_words': False,
    'bank_block': False,
    'bank_title': '',
}

DENSITY_PADDING = {
    'compact': '1px 4px',
    'roomy': '10px 8px',
}

GRID_RULES = {
    'rows': 'border: 0 !important; border-bottom: 1px solid #dee2e6 !important;',
    'grid': 'border: 1px solid #dee2e6 !important;',
    'none': 'border: 0 !important;',
}

# Rows that are not product lines. A section header, a note or a running
# subtotal must never take a line number, and the class names below are the ones
# core actually writes on 16, 17, 18 and 19 - checked against each image rather
# than assumed.
NON_PRODUCT_ROW_CLASSES = (
    'o_line_section',
    'o_line_subsection',
    'o_line_note',
    'is-subtotal',
)

WATERMARK_CLASS = 'miko-watermark'
LINE_IMAGE_CLASS = 'miko-line-img'

# Roughly the middle of an A4 or Letter sheet at the 96dpi wkhtmltopdf renders
# at, measured on a real page rather than calculated: percentages cannot be used
# here at all (see build_css), so this is a length and has to be one.
WATERMARK_TOP_PX = 400


def merged(*designs):
    """Layer designs left to right; every key a layer carries wins.

    A layer carries only the keys it means. The company always supplies a full
    set; a rule supplies just its overrides. Nothing is dropped for being falsy,
    because "off" is a value a rule is entitled to set - dropping it is how a
    rule that turns a watermark OFF for one customer silently keeps printing it.
    """
    out = dict(DEFAULTS)
    for design in designs:
        for key, value in (design or {}).items():
            if key in DEFAULTS and value is not None:
                out[key] = value
    return out


def _px(value):
    return '%dpx' % int(value)


def build_css(design, scope):
    """Return the CSS for one design, scoped to one company's layout class.

    `scope` is the class core puts on the header, article and footer of every
    externally-laid-out report (``o_company_<id>_layout``), so the rules cannot
    leak into another company's document when several are printed in one batch.
    """
    design = merged(design)
    if not design.get('active'):
        return ''
    sel = '.%s' % scope
    table = '%s .o_main_table' % sel
    out = []

    if design['base_font_size']:
        out.append('%s { font-size: %s; }' % (sel, _px(design['base_font_size'])))
    if design['line_height']:
        out.append('%s { line-height: %d%%; }' % (sel, int(design['line_height'])))
    if design['table_font_size']:
        out.append('%s { font-size: %s; }' % (table, _px(design['table_font_size'])))

    padding = DENSITY_PADDING.get(design['density'])
    if padding:
        out.append('%s > thead > tr > th, %s > tbody > tr > td { padding: %s; }'
                   % (table, table, padding))

    grid = GRID_RULES.get(design['grid'])
    if grid:
        out.append('%s > thead > tr > th, %s > tbody > tr > td { %s }'
                   % (table, table, grid))

    if design['zebra']:
        # Bootstrap 5 paints its own striping with an inset box-shadow rather
        # than a background, so a background-color alone is painted over.
        out.append(
            '%s > tbody > tr:nth-child(even) > td '
            '{ background-color: %s !important; box-shadow: none !important; '
            '-webkit-print-color-adjust: exact; }'
            % (table, design['zebra_color']))

    if design['row_numbers']:
        skip = ''.join(':not(.%s)' % klass for klass in NON_PRODUCT_ROW_CLASSES)
        out.append('%s > tbody { counter-reset: miko-line; }' % table)
        out.append(
            '%s > tbody > tr%s > td:first-child:before '
            '{ counter-increment: miko-line; content: counter(miko-line) ". "; '
            'color: #6c757d; }' % (table, skip))

    if design['head_bg'] or design['head_color']:
        decl = []
        if design['head_bg']:
            decl.append('background-color: %s !important;' % design['head_bg'])
            decl.append('-webkit-print-color-adjust: exact;')
        if design['head_color']:
            decl.append('color: %s !important;' % design['head_color'])
        out.append('%s > thead > tr > th { %s }' % (table, ' '.join(decl)))

    if design['line_images']:
        size = _px(design['line_image_size'] or DEFAULTS['line_image_size'])
        out.append(
            '.%s { float: left; margin: 0 8px 2px 0; max-height: %s; '
            'max-width: %s; }' % (LINE_IMAGE_CLASS, size, size))

    if design['watermark_type'] in ('text', 'image'):
        opacity = max(0.0, min(1.0, (design['watermark_opacity'] or 0) / 100.0))
        angle = int(design['watermark_angle'])
        # Four things here are the way they are because of what wkhtmltopdf
        # 0.12.6 actually did on a real page, not because of what the spec says:
        #   - `position: fixed` is what repeats the stamp on every page.
        #   - the offset is in PIXELS, never a percentage. Odoo's own
        #     `minimal_layout` opens with <html style="height: 0;">, so every
        #     percentage height resolves against nothing: `top: 42%` puts the
        #     stamp at the very top of the sheet, where rotating it runs it off
        #     the edge. That is the whole of the "DRAFT prints as DRAF" bug.
        #   - `white-space: nowrap` stops a long stamp wrapping before it is
        #     rotated and leaving its tail somewhere else on the page.
        #   - `-webkit-transform` is not belt and braces. This engine is
        #     QtWebKit and ignores the unprefixed property outright.
        out.append(
            '.%s { position: fixed; top: %dpx; left: 0; width: 100%%; '
            'text-align: center; z-index: 3000; }'
            % (WATERMARK_CLASS, WATERMARK_TOP_PX))
        out.append(
            '.%s > .miko-watermark-inner { display: inline-block; '
            'white-space: nowrap; opacity: %s; '
            'transform: rotate(%ddeg); -webkit-transform: rotate(%ddeg); '
            'font-family: Helvetica, Arial, sans-serif; font-size: %s; '
            'font-weight: 700; letter-spacing: 2px; color: #000000; '
            'line-height: 1; }'
            % (WATERMARK_CLASS, ('%.2f' % opacity), angle, angle,
               _px(design['watermark_size'])))
        out.append('.%s img { max-width: 400px; max-height: 400px; }'
                   % WATERMARK_CLASS)

    return '\n'.join(out)


def build_watermark_html(design, image_data_uri=None):
    """Return the watermark markup, or '' when there is nothing to stamp.

    It is a separate node rather than a ::before on the body because
    wkhtmltopdf repeats position:fixed elements on every page, which is the only
    reliable way to get a stamp on page four of a four page invoice.
    """
    design = merged(design)
    if not design.get('active'):
        return ''
    kind = design['watermark_type']
    if kind == 'text' and design['watermark_text']:
        text = (design['watermark_text']
                .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        inner = text
    elif kind == 'image' and image_data_uri:
        inner = '<img src="%s"/>' % image_data_uri
    else:
        return ''
    return ('<div class="%s"><div class="miko-watermark-inner">%s</div></div>'
            % (WATERMARK_CLASS, inner))
