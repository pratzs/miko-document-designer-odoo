# -*- coding: utf-8 -*-
"""What these tests are actually for.

The CSS builder is a pure function and is tested as one: cheap, exact, and the
place a typo would otherwise reach a customer's invoice unnoticed.

The rest is tested against real records through the ORM, because a pure function
passing is not the same as the module working - Margin Health shipped logic that
passed every dict-based test and then crashed on real records. So the resolution
order, the write-through and the invoice markup are all exercised against a real
invoice rendered by the real report engine.

The PDF paths are tested against real PDFs built in-process rather than by
driving wkhtmltopdf: core deliberately falls back to HTML rendering inside a
test run, and forcing the binary from inside a test cursor risks the suite
hanging on an HTTP round trip to its own server. wkhtmltopdf output is verified
by hand on each series instead, which is recorded in the README.
"""
import base64
import io

from reportlab.pdfgen import canvas as rl_canvas

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged

from odoo.addons.miko_document_designer.models.design import (
    DEFAULTS, build_css, build_watermark_html, merged,
)
from odoo.addons.miko_document_designer.models import document_html
from odoo.addons.miko_document_designer.models.ir_actions_report import (
    PdfFileReader, _data_uri,
)

SCOPE = 'o_company_7_layout'


def make_pdf(pages=1, text="page"):
    buf = io.BytesIO()
    pdf = rl_canvas.Canvas(buf)
    for index in range(pages):
        pdf.drawString(100, 700, "%s %d" % (text, index))
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


def page_count(content):
    return len(PdfFileReader(io.BytesIO(content), strict=False).pages)


@tagged('post_install', '-at_install')
class TestDesignCss(common.TransactionCase):
    """The pure layer: what a design means in CSS."""

    def test_default_design_emits_nothing(self):
        self.assertEqual(build_css(dict(DEFAULTS), SCOPE), '',
                         "a freshly installed module must not change a single "
                         "printed document until somebody designs one")

    def test_inactive_design_emits_nothing(self):
        design = dict(DEFAULTS, active=False, zebra=True, row_numbers=True)
        self.assertEqual(build_css(design, SCOPE), '')

    def test_base_font_size(self):
        css = build_css(dict(DEFAULTS, base_font_size=13), SCOPE)
        self.assertIn('.%s { font-size: 13px; }' % SCOPE, css)

    def test_table_font_size_targets_the_line_table(self):
        css = build_css(dict(DEFAULTS, table_font_size=9), SCOPE)
        self.assertIn('.%s .o_main_table { font-size: 9px; }' % SCOPE, css)

    def test_line_height(self):
        css = build_css(dict(DEFAULTS, line_height=140), SCOPE)
        self.assertIn('line-height: 140%;', css)

    def test_density_compact(self):
        css = build_css(dict(DEFAULTS, density='compact'), SCOPE)
        self.assertIn('padding: 1px 4px;', css)

    def test_density_roomy(self):
        css = build_css(dict(DEFAULTS, density='roomy'), SCOPE)
        self.assertIn('padding: 10px 8px;', css)

    def test_density_default_emits_nothing(self):
        self.assertEqual(build_css(dict(DEFAULTS, density='default'), SCOPE), '')

    def test_grid_rows(self):
        css = build_css(dict(DEFAULTS, grid='rows'), SCOPE)
        self.assertIn('border-bottom: 1px solid #dee2e6 !important;', css)

    def test_grid_none(self):
        css = build_css(dict(DEFAULTS, grid='none'), SCOPE)
        self.assertIn('border: 0 !important;', css)

    def test_zebra_beats_bootstrap(self):
        css = build_css(dict(DEFAULTS, zebra=True), SCOPE)
        self.assertIn('tr:nth-child(even)', css)
        self.assertIn('background-color: #F2F4F7 !important;', css)
        self.assertIn('box-shadow: none !important;', css,
                      "Bootstrap paints its own striping with an inset shadow, "
                      "so a background alone is painted over")

    def test_zebra_colour_is_used(self):
        css = build_css(dict(DEFAULTS, zebra=True, zebra_color='#ABCDEF'), SCOPE)
        self.assertIn('background-color: #ABCDEF !important;', css)

    def test_row_numbers_use_a_counter(self):
        css = build_css(dict(DEFAULTS, row_numbers=True), SCOPE)
        self.assertIn('counter-reset: miko-line;', css)
        self.assertIn('counter-increment: miko-line;', css)
        self.assertIn('content: counter(miko-line) ". ";', css)

    def test_row_numbers_skip_sections_notes_and_subtotals(self):
        css = build_css(dict(DEFAULTS, row_numbers=True), SCOPE)
        for klass in ('o_line_section', 'o_line_subsection', 'o_line_note',
                      'is-subtotal'):
            self.assertIn(':not(.%s)' % klass, css,
                          "a section header must never take a line number")

    def test_header_row_colours(self):
        css = build_css(dict(DEFAULTS, head_bg='#111111', head_color='#FFFFFF'),
                        SCOPE)
        self.assertIn('background-color: #111111 !important;', css)
        self.assertIn('color: #FFFFFF !important;', css)
        self.assertIn('-webkit-print-color-adjust: exact;', css)

    def test_line_image_size(self):
        css = build_css(dict(DEFAULTS, line_images=True, line_image_size=64), SCOPE)
        self.assertIn('.miko-line-img', css)
        self.assertIn('max-height: 64px;', css)

    def test_watermark_css(self):
        css = build_css(dict(DEFAULTS, watermark_type='text',
                             watermark_text='DRAFT', watermark_opacity=20,
                             watermark_angle=-45, watermark_size=120), SCOPE)
        self.assertIn('position: fixed;', css,
                      "wkhtmltopdf repeats a fixed element on every page, which "
                      "is the only reliable way to stamp page four of four")
        self.assertIn('opacity: 0.20;', css)
        self.assertIn('rotate(-45deg)', css)
        self.assertIn('font-size: 120px;', css)

    def test_watermark_is_offset_in_pixels_not_per_cent(self):
        """Regression: a percentage offset puts the stamp off the page.

        Odoo's `minimal_layout` opens with <html style="height: 0;">, so every
        percentage height resolves against nothing and `top: 42%` becomes
        `top: 0`. On the first real render that printed "DRAFT" as "DRAF" with
        its tail lying across the address block. Only a real PDF showed it; the
        HTML looked perfect.
        """
        css = build_css(dict(DEFAULTS, watermark_type='text',
                             watermark_text='DRAFT'), SCOPE)
        watermark_rule = [line for line in css.splitlines()
                          if line.startswith('.miko-watermark {')]
        self.assertTrue(watermark_rule)
        self.assertIn('top: 400px;', watermark_rule[0])
        self.assertNotIn('%', watermark_rule[0].split('top:')[1].split(';')[0])

    def test_watermark_rotation_carries_the_webkit_prefix(self):
        """wkhtmltopdf is QtWebKit and ignores the unprefixed property."""
        css = build_css(dict(DEFAULTS, watermark_type='text',
                             watermark_text='DRAFT'), SCOPE)
        self.assertIn('-webkit-transform: rotate(-30deg);', css)

    def test_watermark_does_not_wrap(self):
        css = build_css(dict(DEFAULTS, watermark_type='text',
                             watermark_text='CONFIDENTIAL COPY'), SCOPE)
        self.assertIn('white-space: nowrap;', css)

    def test_watermark_opacity_is_clamped(self):
        css = build_css(dict(DEFAULTS, watermark_type='text',
                             watermark_text='X', watermark_opacity=500), SCOPE)
        self.assertIn('opacity: 1.00;', css)

    def test_every_document_rule_is_scoped_to_one_company(self):
        design = dict(DEFAULTS, base_font_size=12, table_font_size=10,
                      zebra=True, row_numbers=True, density='compact',
                      grid='grid', head_bg='#000000')
        css = build_css(design, SCOPE)
        for line in css.splitlines():
            if not line.strip() or line.strip().startswith('.miko-'):
                continue
            self.assertTrue(line.startswith('.%s' % SCOPE),
                            "unscoped rule would style another company's "
                            "document in the same print run: %s" % line)

    def test_watermark_html_text_is_escaped(self):
        html = build_watermark_html(dict(DEFAULTS, watermark_type='text',
                                         watermark_text='A & <b>B</b>'))
        self.assertIn('A &amp; &lt;b&gt;B&lt;/b&gt;', html)
        self.assertNotIn('<b>', html)

    def test_watermark_html_image(self):
        html = build_watermark_html(
            dict(DEFAULTS, watermark_type='image'),
            image_data_uri='data:image/png;base64,AAAA')
        self.assertIn('<img src="data:image/png;base64,AAAA"/>', html)

    def test_watermark_html_none(self):
        self.assertEqual(build_watermark_html(dict(DEFAULTS)), '')
        self.assertEqual(
            build_watermark_html(dict(DEFAULTS, watermark_type='text')), '',
            "a watermark type with no text is not a watermark")

    def test_merged_later_layer_wins(self):
        out = merged({'base_font_size': 10}, {'base_font_size': 14})
        self.assertEqual(out['base_font_size'], 14)

    def test_merged_keeps_an_explicit_off(self):
        out = merged({'zebra': True}, {'zebra': False})
        self.assertFalse(out['zebra'],
                         "a rule that turns striped rows off for one customer "
                         "must not keep printing stripes")

    def test_merged_ignores_unknown_keys(self):
        self.assertNotIn('nonsense', merged({'nonsense': 1}))

    def test_data_uri_sniffs_the_real_type(self):
        self.assertTrue(_data_uri('/9j/4AAQ').startswith('data:image/jpeg;'))
        self.assertTrue(_data_uri('iVBORw0KGgoAAA').startswith('data:image/png;'))
        self.assertIsNone(_data_uri(False))


@tagged('post_install', '-at_install')
class TestDesignResolution(common.TransactionCase):
    """Which design applies to which document."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({'name': "Miko Test Buyer"})
        cls.other_partner = cls.env['res.partner'].create({'name': "Someone Else"})
        cls.contact = cls.env['res.partner'].create({
            'name': "Buyer's accounts desk",
            'parent_id': cls.partner.id,
            'type': 'invoice',
        })
        # Two reports that exist on any database, because this module
        # depends on nothing and the suite has to run where Invoicing does not.
        cls.report = cls.env.ref('web.action_report_externalpreview')
        cls.other_report = cls.env.ref('web.action_report_internalpreview')
        cls.Rule = cls.env['miko.document.rule']

    def test_company_design_is_the_baseline(self):
        self.company.miko_zebra = True
        design = self.company._miko_design_for()
        self.assertTrue(design['zebra'])
        self.assertEqual(design['density'], 'default')

    def test_inactive_company_design_is_neutral(self):
        self.company.write({'miko_zebra': True, 'miko_design_active': False})
        design = self.company._miko_design_for()
        self.assertFalse(design['active'])
        self.assertFalse(design['zebra'])

    def test_rule_overrides_the_company(self):
        self.company.miko_watermark_type = 'none'
        self.Rule.create({
            'name': "Draft stamp",
            'watermark_type': 'text',
            'watermark_text': "DRAFT",
        })
        design = self.company._miko_design_for(report=self.report)
        self.assertEqual(design['watermark_type'], 'text')
        self.assertEqual(design['watermark_text'], "DRAFT")

    def test_rule_leaves_untouched_settings_alone(self):
        self.company.write({'miko_zebra': True, 'miko_base_font_size': 13})
        self.Rule.create({'name': "Only a watermark",
                          'watermark_type': 'text', 'watermark_text': "COPY"})
        design = self.company._miko_design_for(report=self.report)
        self.assertTrue(design['zebra'], "a rule carries only what it changes")
        self.assertEqual(design['base_font_size'], 13)

    def test_rule_can_switch_something_off(self):
        self.company.miko_zebra = True
        self.Rule.create({'name': "Plain", 'zebra': 'off'})
        design = self.company._miko_design_for(report=self.report)
        self.assertFalse(design['zebra'])

    def test_rule_limited_to_one_document(self):
        self.Rule.create({
            'name': "Only on invoices with payments",
            'report_ids': [(6, 0, self.report.ids)],
            'row_numbers': 'on',
        })
        self.assertTrue(
            self.company._miko_design_for(report=self.report)['row_numbers'])
        self.assertFalse(
            self.company._miko_design_for(report=self.other_report)['row_numbers'])

    def test_rule_limited_to_one_customer(self):
        invoice_a = self.env['res.partner'].create({'name': "A"})
        self.Rule.create({
            'name': "One buyer only",
            'partner_ids': [(6, 0, self.partner.ids)],
            'row_numbers': 'on',
        })
        record = self.env['res.partner'].browse()  # no record at all
        self.assertFalse(self.company._miko_design_for(record=record)['row_numbers'])
        # res.partner.bank stands in for a document addressed to a customer:
        # it carries partner_id and exists on every database.
        addressed = self.env['res.partner.bank'].new({'partner_id': self.partner.id})
        self.assertTrue(self.company._miko_design_for(record=addressed)['row_numbers'])
        other = self.env['res.partner.bank'].new({'partner_id': invoice_a.id})
        self.assertFalse(self.company._miko_design_for(record=other)['row_numbers'])

    def test_rule_on_a_company_covers_its_contacts(self):
        self.Rule.create({
            'name': "Whole customer",
            'partner_ids': [(6, 0, self.partner.ids)],
            'zebra': 'on',
        })
        document = self.env['res.partner.bank'].new({'partner_id': self.contact.id})
        self.assertTrue(self.company._miko_design_for(record=document)['zebra'],
                        "a rule set on the customer must cover the contact the "
                        "document is actually addressed to")

    def test_first_matching_rule_wins(self):
        self.Rule.create({'name': "Second", 'sequence': 20,
                          'watermark_type': 'text', 'watermark_text': "SECOND"})
        self.Rule.create({'name': "First", 'sequence': 10,
                          'watermark_type': 'text', 'watermark_text': "FIRST"})
        design = self.company._miko_design_for(report=self.report)
        self.assertEqual(design['watermark_text'], "FIRST")

    def test_archived_rule_does_not_apply(self):
        rule = self.Rule.create({'name': "Off", 'row_numbers': 'on'})
        rule.active = False
        self.assertFalse(
            self.company._miko_design_for(report=self.report)['row_numbers'])

    def test_rule_can_drop_the_letterhead(self):
        self.company.miko_letterhead_pdf = base64.b64encode(make_pdf())
        self.Rule.create({'name': "Plain paper", 'no_letterhead': True})
        design = self.company._miko_design_for(report=self.report)
        self.assertFalse(design['letterhead_pdf'])

    def test_opacity_is_a_percentage(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': "Bad", 'watermark_opacity': 400})

    def test_sizes_are_sane(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': "Bad", 'base_font_size': 4000})

    def test_zero_means_inherit_not_invisible(self):
        rule = self.Rule.create({'name': "Fine", 'base_font_size': 0})
        self.assertNotIn('base_font_size', rule._miko_design_values())


@tagged('post_install', '-at_install')
class TestDesignerScreen(common.TransactionCase):
    """The one screen, and that it writes through instead of shadowing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.designer = cls.env['miko.document.designer'].create({
            'company_id': cls.company.id,
        })

    def test_core_fields_write_through_to_the_company(self):
        self.designer.primary_color = '#123456'
        self.assertEqual(self.company.primary_color, '#123456',
                         "core owns this field; shadowing it would leave the "
                         "company's own reports out of step")

    def test_our_fields_write_through_to_the_company(self):
        self.designer.miko_zebra = True
        self.designer.miko_zebra_color = '#EEEEEE'
        self.assertTrue(self.company.miko_zebra)
        self.assertEqual(self.company.miko_zebra_color, '#EEEEEE')

    def test_the_screen_surfaces_the_whole_core_layout(self):
        for field in ('logo', 'font', 'primary_color', 'secondary_color',
                      'report_header', 'report_footer', 'company_details',
                      'paperformat_id', 'external_report_layout_id',
                      'layout_background', 'layout_background_image'):
            self.assertIn(field, self.designer._fields,
                          "the merchant does the whole job in one place")

    def test_preview_carries_the_design(self):
        layout = self.env['report.layout'].search([], limit=1)
        self.designer.write({
            'report_layout_id': layout.id,
            'miko_zebra': True,
            'miko_row_numbers': True,
        })
        preview = str(self.designer.preview or '')
        self.assertTrue(preview, "core's preview should still render")
        self.assertIn('counter-increment: miko-line;', preview)
        self.assertIn('o_company_%s_layout' % self.designer.id, preview,
                      "the preview renders against the wizard, so the "
                      "stylesheet has to be scoped to the wizard's id")

    def test_our_layouts_are_offered_in_the_picker(self):
        names = self.env['report.layout'].search([]).mapped('name')
        self.assertIn('Miko Clean', names)
        self.assertIn('Miko Letterhead', names)

    def test_our_layouts_point_at_real_templates(self):
        for xmlid in ('miko_document_designer.miko_report_layout_clean',
                      'miko_document_designer.miko_report_layout_letterhead'):
            layout = self.env.ref(xmlid)
            self.assertTrue(layout.view_id.key)
            self.assertEqual(layout.view_id.type, 'qweb')


@tagged('post_install', '-at_install')
class TestDocumentHtml(common.TransactionCase):
    """The DOM pass, which is what replaced depending on three other apps.

    Every one of these is a refusal test as much as an injection test: the
    module would rather print no picture than print the wrong one next to a
    line on a document that goes to a customer.
    """

    def _article(self, rows=2, sections=True, first_label="First thing",
                 second_label="Second thing"):
        section = ('<tr class="o_line_section"><td colspan="2">A section'
                   '</td></tr>') if sections else ''
        body = ''
        labels = [first_label, second_label][:rows]
        for label in labels:
            body += '<tr><td>%s</td><td>10.00</td></tr>' % label
        return document_html.parse(
            '<div class="article" data-oe-model="res.partner" data-oe-id="1">'
            '<table class="table o_main_table"><thead><tr><th>Description</th>'
            '<th>Amount</th></tr></thead><tbody>%s%s'
            '<tr class="is-subtotal"><td colspan="2">Subtotal</td></tr>'
            '</tbody></table><div id="total"><span>20.00</span></div></div>'
            % (section, body))

    def test_line_rows_exclude_sections_notes_and_subtotals(self):
        rows = document_html.find_line_rows(self._article())
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertNotIn('A section', ' '.join(row.itertext()))
            self.assertNotIn('Subtotal', ' '.join(row.itertext()))

    def test_images_are_injected_into_the_first_cell(self):
        article = self._article()
        applied = document_html.inject_line_images(article, [
            ("First thing", 'data:image/png;base64,AAA'),
            ("Second thing", 'data:image/png;base64,BBB'),
        ])
        self.assertTrue(applied)
        html = document_html.serialise(article).decode()
        self.assertEqual(html.count('miko-line-img'), 2)
        self.assertLess(html.index('base64,AAA'), html.index('First thing'),
                        "the picture belongs before the description it labels")

    def test_images_refuse_a_count_mismatch(self):
        article = self._article()
        applied = document_html.inject_line_images(article, [
            ("First thing", 'data:image/png;base64,AAA'),
        ])
        self.assertFalse(applied)
        self.assertNotIn('miko-line-img', document_html.serialise(article).decode())

    def test_images_refuse_when_the_row_is_not_the_line(self):
        article = self._article()
        applied = document_html.inject_line_images(article, [
            ("Something else entirely", 'data:image/png;base64,AAA'),
            ("Second thing", 'data:image/png;base64,BBB'),
        ])
        self.assertFalse(applied,
                         "pairing by position alone would caption a line with "
                         "another line's product")
        self.assertNotIn('miko-line-img', document_html.serialise(article).decode())

    def test_images_skip_a_line_with_no_picture(self):
        article = self._article()
        applied = document_html.inject_line_images(article, [
            ("First thing", 'data:image/png;base64,AAA'),
            ("Second thing", None),
        ])
        self.assertTrue(applied)
        self.assertEqual(
            document_html.serialise(article).decode().count('miko-line-img'), 1)

    def test_images_need_a_line_table(self):
        article = document_html.parse('<div class="article"><p>No table</p></div>')
        self.assertFalse(document_html.inject_line_images(
            article, [("x", 'data:image/png;base64,AAA')]))

    def test_a_block_lands_after_the_totals(self):
        article = self._article()
        document_html.inject_after_totals(article, '<div class="marker">X</div>')
        html = document_html.serialise(article).decode()
        self.assertLess(html.index('id="total"'), html.index('class="marker"'))

    def test_a_block_with_no_totals_lands_at_the_end(self):
        article = document_html.parse('<div class="article"><p>Body</p></div>')
        document_html.inject_after_totals(article, '<div class="marker">X</div>')
        html = document_html.serialise(article).decode()
        self.assertIn('marker', html)
        self.assertLess(html.index('Body'), html.index('marker'))

    def test_words_block(self):
        html = document_html.build_words_block("Total in words:", "Ten Dollars")
        self.assertIn('Total in words:', html)
        self.assertIn('Ten Dollars', html)

    def test_words_block_is_nothing_without_words(self):
        self.assertEqual(document_html.build_words_block("Total:", ''), '')

    def test_bank_block(self):
        html = document_html.build_bank_block(
            "Pay us", [("Big Bank", "NZ00-1111"), ("", "NZ00-2222")])
        self.assertIn('Pay us', html)
        self.assertIn('Big Bank - NZ00-1111', html)
        self.assertIn('NZ00-2222', html)

    def test_bank_block_drops_accounts_with_no_number(self):
        self.assertEqual(
            document_html.build_bank_block("Pay us", [("Bank", "")]), '')

    def test_blocks_are_escaped(self):
        html = document_html.build_bank_block(
            "<script>x</script>", [("A&B", '"1"')])
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('A&amp;B', html)
        self.assertIn('&quot;1&quot;', html)

    def test_totals_block_wraps_only_what_exists(self):
        self.assertEqual(document_html.build_totals_block('', ''), '')
        self.assertIn('miko-totals-extra',
                      document_html.build_totals_block('<p>x</p>', ''))


@tagged('post_install', '-at_install')
class TestRenderedDocument(common.TransactionCase):
    """The HTML that actually reaches wkhtmltopdf.

    The document under test is one this module registers itself rather than one
    borrowed from Invoicing, because this module depends on nothing and the
    suite has to prove it works on a database where Invoicing is not installed.
    Its markup is core's: `web.external_layout`, a `table.o_main_table` with a
    section row and product rows, and a `div#total` - the exact anchors the
    render pass uses on a real invoice.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({'name': "Rendered Buyer"})
        cls.env['ir.ui.view'].create({
            'name': "Miko test document",
            'type': 'qweb',
            'key': 'miko_document_designer.test_document',
            'arch': """
<t t-name="miko_document_designer.test_document">
    <t t-call="web.html_container">
        <t t-foreach="docs" t-as="o">
            <t t-call="web.external_layout">
                <div class="page">
                    <table class="table o_main_table">
                        <thead><tr><th>Description</th><th>Amount</th></tr></thead>
                        <tbody>
                            <tr class="o_line_section"><td colspan="2">A section</td></tr>
                            <tr><td>First thing</td><td>10.00</td></tr>
                            <tr><td>Second thing</td><td>20.00</td></tr>
                        </tbody>
                    </table>
                    <div id="total"><span>30.00</span></div>
                </div>
            </t>
        </t>
    </t>
</t>""",
        })
        cls.report = cls.env['ir.actions.report'].create({
            'name': "Miko test document",
            'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'miko_document_designer.test_document',
            'report_file': 'miko_document_designer.test_document',
        })

    def _html(self):
        return self.env['ir.actions.report']._render_qweb_html(
            self.report.id, self.partner.ids)[0]

    def _prepared(self):
        design = self.company._miko_design_for(record=self.partner,
                                               report=self.report)
        report = self.report.with_context(miko_design=design,
                                          miko_design_company=self.company.id)
        return report._prepare_html(self._html(), report_model='res.partner')

    def test_the_document_still_renders(self):
        html = self._html().decode()
        self.assertIn('First thing', html)
        self.assertIn('o_main_table', html)
        self.assertIn('class="article', html)

    def test_stylesheet_reaches_the_body_head(self):
        self.company.miko_zebra = True
        bodies, _ids, _header, _footer, _args = self._prepared()
        self.assertTrue(bodies)
        for body in bodies:
            text = str(body)
            self.assertIn('nth-child(even)', text)
            self.assertLess(text.index('nth-child(even)'), text.index('</head>'),
                            "core keeps only the article, header and footer "
                            "nodes, so a stylesheet outside the head is thrown "
                            "away before wkhtmltopdf ever sees it")

    def test_stylesheet_reaches_the_header_and_footer(self):
        self.company.miko_base_font_size = 13
        _bodies, _ids, header, footer, _args = self._prepared()
        self.assertIn('font-size: 13px;', str(header))
        self.assertIn('font-size: 13px;', str(footer))

    def test_nothing_is_injected_for_a_default_company(self):
        bodies, _ids, _header, _footer, _args = self.report._prepare_html(
            self._html(), report_model='res.partner')
        self.assertNotIn('miko-watermark', str(bodies[0]))
        self.assertNotIn('miko-line-img', str(bodies[0]))
        self.assertNotIn('miko-totals-extra', str(bodies[0]))

    def test_watermark_is_injected_into_the_body(self):
        self.company.write({'miko_watermark_type': 'text',
                            'miko_watermark_text': "DRAFT COPY"})
        bodies, _ids, _header, _footer, _args = self._prepared()
        body = str(bodies[0])
        self.assertIn('<div class="miko-watermark">', body)
        self.assertIn('DRAFT COPY', body)
        self.assertLess(body.index('<body'),
                        body.index('<div class="miko-watermark">'),
                        "the stamp belongs in the body; the class name also "
                        "appears earlier in the stylesheet, which is why this "
                        "looks for the element and not the word")

    def test_watermark_stays_out_of_the_header(self):
        self.company.write({'miko_watermark_type': 'text',
                            'miko_watermark_text': "DRAFT COPY"})
        _bodies, _ids, header, _footer, _args = self._prepared()
        self.assertNotIn('<div class="miko-watermark">', str(header),
                         "the header is a separate document repeated on every "
                         "page; stamping it would print the watermark twice")

    def test_the_scope_matches_the_markup(self):
        self.company.miko_zebra = True
        bodies, _ids, _header, _footer, _args = self._prepared()
        body = str(bodies[0])
        self.assertIn('o_company_%s_layout' % self.company.id, body)
        self.assertIn('.o_company_%s_layout .o_main_table' % self.company.id, body)

    def test_bank_block_reaches_the_document(self):
        self.env['res.partner.bank'].create({
            'acc_number': "MIKO-TEST-0001",
            'partner_id': self.company.partner_id.id,
        })
        self.assertNotIn('MIKO-TEST-0001', str(self._prepared()[0][0]))
        self.company.write({'miko_bank_block': True,
                            'miko_bank_title': "How to pay us"})
        body = str(self._prepared()[0][0])
        self.assertIn('MIKO-TEST-0001', body)
        self.assertIn('How to pay us', body)
        self.assertLess(body.index('id="total"'), body.index('How to pay us'))

    def test_bank_block_falls_back_to_the_company(self):
        """A document that names no account of its own prints the company's.

        The other half of that rule - a document that DOES carry
        `partner_bank_id`, such as an invoice, printing that account instead -
        cannot be exercised here, because no model in a database without
        Invoicing has the field. It is on the by-hand checklist in the README
        and was verified on a real invoice on all four series.
        """
        self.env['res.partner.bank'].create({
            'acc_number': "MIKO-COMPANY-ACCOUNT",
            'partner_id': self.company.partner_id.id,
        })
        rows = self.report._miko_bank_rows(self.partner)
        self.assertIn("MIKO-COMPANY-ACCOUNT", [number for _name, number in rows])
        self.assertLessEqual(len(rows), 2,
                             "two accounts is a block; ten is a page")

    def test_a_record_with_no_total_gets_no_words_block(self):
        self.company.miko_amount_words = True
        self.assertEqual(self.report._miko_amount_in_words(self.partner), '',
                         "a document without a total must not print an empty "
                         "'total in words' line")
        self.assertNotIn('Total in words', str(self._prepared()[0][0]))

    def test_a_record_with_no_lines_gets_no_pictures(self):
        self.company.miko_line_images = True
        self.assertEqual(self.report._miko_line_items(self.partner), [])
        # The class name is in the stylesheet as soon as the setting is on;
        # what must not appear is an actual picture element.
        self.assertNotIn('<img class="miko-line-img"',
                         str(self._prepared()[0][0]))

    def test_a_rule_reaches_the_rendered_document(self):
        self.env['miko.document.rule'].create({
            'name': "This buyer gets numbered lines",
            'partner_ids': [(6, 0, self.partner.ids)],
            'row_numbers': 'on',
        })
        design = self.company._miko_design_for(record=self.partner,
                                               report=self.report)
        self.assertTrue(design['row_numbers'])
        report = self.report.with_context(miko_design=design,
                                          miko_design_company=self.company.id)
        bodies = report._prepare_html(self._html(), report_model='res.partner')[0]
        self.assertIn('counter-increment: miko-line;', str(bodies[0]))

    def test_an_inactive_design_leaves_the_document_alone(self):
        self.company.write({'miko_zebra': True, 'miko_watermark_type': 'text',
                            'miko_watermark_text': "X",
                            'miko_design_active': False})
        bodies, _ids, _header, _footer, _args = self._prepared()
        self.assertNotIn('nth-child(even)', str(bodies[0]))
        self.assertNotIn('miko-watermark', str(bodies[0]))


@tagged('post_install', '-at_install')
class TestPdfAssembly(common.TransactionCase):
    """Letterhead and appended pages, against real PDFs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env['ir.actions.report']
        cls.document = make_pdf(pages=3, text="invoice page")
        cls.letterhead = make_pdf(pages=1, text="letterhead")
        cls.terms = make_pdf(pages=2, text="terms")

    def test_letterhead_keeps_the_page_count(self):
        out = self.Report._miko_underlay(self.document, self.letterhead)
        self.assertEqual(page_count(out), 3,
                         "the letterhead goes behind each page, it does not "
                         "add pages")

    def test_letterhead_reaches_every_page(self):
        out = self.Report._miko_underlay(self.document, self.letterhead)
        reader = PdfFileReader(io.BytesIO(out), strict=False)
        for index in range(3):
            page = reader.pages[index]
            extract = getattr(page, 'extract_text', None) or page.extractText
            text = extract()
            self.assertIn("letterhead", text)
            self.assertIn("invoice page %d" % index, text,
                          "each page must keep its own content, not the "
                          "content of the page merged before it")

    def test_appended_pdf_adds_its_pages(self):
        design = dict(DEFAULTS, append_pdf=base64.b64encode(self.terms))
        out = self.Report._miko_apply_pdf(self.document, design)
        self.assertEqual(page_count(out), 5)

    def test_letterhead_and_terms_together(self):
        design = dict(DEFAULTS,
                      letterhead_pdf=base64.b64encode(self.letterhead),
                      append_pdf=base64.b64encode(self.terms))
        out = self.Report._miko_apply_pdf(self.document, design)
        self.assertEqual(page_count(out), 5)

    def test_a_corrupt_letterhead_does_not_stop_the_print(self):
        design = dict(DEFAULTS,
                      letterhead_pdf=base64.b64encode(b"this is not a pdf"))
        out = self.Report._miko_apply_pdf(self.document, design)
        self.assertEqual(page_count(out), 3,
                         "a bad upload costs the merchant a warning in the log, "
                         "not the ability to invoice")

    def test_a_corrupt_append_does_not_stop_the_print(self):
        design = dict(DEFAULTS, append_pdf=base64.b64encode(b"nope"))
        out = self.Report._miko_apply_pdf(self.document, design)
        self.assertEqual(page_count(out), 3)

    def test_nothing_to_do_returns_the_document_untouched(self):
        out = self.Report._miko_apply_pdf(self.document, dict(DEFAULTS))
        self.assertEqual(out, self.document)
