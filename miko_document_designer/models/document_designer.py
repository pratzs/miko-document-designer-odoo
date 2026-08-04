# -*- coding: utf-8 -*-
"""The one screen.

It is core's own ``base.document.layout`` extended by prototype inheritance, so
every field Odoo already owns - logo, colours, font, paper format, layout,
header, footer, company details, background - is present and writes straight
back to ``res.company``. The merchant does the whole job in one place, and
nothing is shadowed: uninstalling this module leaves their branding exactly as
they set it rather than reverting to a blank Odoo default.
"""
from odoo import api, fields, models

from .design import build_css, build_watermark_html
from .ir_actions_report import _data_uri

# Core's own dependency list for the preview. An override's @api.depends
# replaces the original rather than adding to it, so these have to be repeated
# alongside ours or editing the logo would stop refreshing the preview.
CORE_PREVIEW_DEPENDS = (
    'report_layout_id', 'logo', 'font', 'primary_color', 'secondary_color',
    'report_header', 'report_footer', 'layout_background',
    'layout_background_image', 'company_details',
)

MIKO_PREVIEW_DEPENDS = (
    'miko_design_active', 'miko_base_font_size', 'miko_table_font_size',
    'miko_line_height', 'miko_density', 'miko_zebra', 'miko_zebra_color',
    'miko_row_numbers', 'miko_grid', 'miko_head_bg', 'miko_head_color',
    'miko_watermark_type', 'miko_watermark_text', 'miko_watermark_image',
    'miko_watermark_opacity', 'miko_watermark_angle', 'miko_watermark_size',
)


class MikoDocumentDesigner(models.TransientModel):
    _name = 'miko.document.designer'
    _inherit = 'base.document.layout'
    _description = 'Document Designer'

    miko_design_active = fields.Boolean(
        related='company_id.miko_design_active', readonly=False)

    miko_base_font_size = fields.Integer(
        related='company_id.miko_base_font_size', readonly=False)
    miko_table_font_size = fields.Integer(
        related='company_id.miko_table_font_size', readonly=False)
    miko_line_height = fields.Integer(
        related='company_id.miko_line_height', readonly=False)

    miko_density = fields.Selection(
        related='company_id.miko_density', readonly=False)
    miko_zebra = fields.Boolean(related='company_id.miko_zebra', readonly=False)
    miko_zebra_color = fields.Char(
        related='company_id.miko_zebra_color', readonly=False)
    miko_row_numbers = fields.Boolean(
        related='company_id.miko_row_numbers', readonly=False)
    miko_grid = fields.Selection(related='company_id.miko_grid', readonly=False)
    miko_head_bg = fields.Char(related='company_id.miko_head_bg', readonly=False)
    miko_head_color = fields.Char(
        related='company_id.miko_head_color', readonly=False)
    miko_line_images = fields.Boolean(
        related='company_id.miko_line_images', readonly=False)
    miko_line_image_size = fields.Integer(
        related='company_id.miko_line_image_size', readonly=False)

    miko_watermark_type = fields.Selection(
        related='company_id.miko_watermark_type', readonly=False)
    miko_watermark_text = fields.Char(
        related='company_id.miko_watermark_text', readonly=False)
    miko_watermark_image = fields.Binary(
        related='company_id.miko_watermark_image', readonly=False)
    miko_watermark_opacity = fields.Integer(
        related='company_id.miko_watermark_opacity', readonly=False)
    miko_watermark_angle = fields.Integer(
        related='company_id.miko_watermark_angle', readonly=False)
    miko_watermark_size = fields.Integer(
        related='company_id.miko_watermark_size', readonly=False)

    miko_letterhead_pdf = fields.Binary(
        related='company_id.miko_letterhead_pdf', readonly=False)
    miko_letterhead_pdf_name = fields.Char(
        related='company_id.miko_letterhead_pdf_name', readonly=False)
    miko_append_pdf = fields.Binary(
        related='company_id.miko_append_pdf', readonly=False)
    miko_append_pdf_name = fields.Char(
        related='company_id.miko_append_pdf_name', readonly=False)

    miko_amount_words = fields.Boolean(
        related='company_id.miko_amount_words', readonly=False)
    miko_bank_block = fields.Boolean(
        related='company_id.miko_bank_block', readonly=False)
    miko_bank_title = fields.Char(
        related='company_id.miko_bank_title', readonly=False)

    @api.depends(*(CORE_PREVIEW_DEPENDS + MIKO_PREVIEW_DEPENDS))
    def _compute_preview(self):
        """Core's preview, with our design painted onto it.

        Core renders the preview against the WIZARD as the company, so the
        layout class in the markup carries the wizard's id. The stylesheet is
        scoped to that same id rather than to the company's, or the preview
        would show the design of whichever company shares that number.
        """
        super()._compute_preview()
        for wizard in self:
            if not wizard.preview:
                continue
            design = wizard.company_id.sudo()._miko_design_values()
            css = build_css(design, 'o_company_%s_layout' % wizard.id)
            watermark = build_watermark_html(
                design, image_data_uri=_data_uri(design.get('watermark_image')))
            if not css and not watermark:
                continue
            style = '<style type="text/css">\n%s\n</style>' % css if css else ''
            wizard.preview = self.env['ir.actions.report']._miko_decorate(
                wizard.preview, style, watermark)

    def action_miko_print_sample(self):
        """Print the real thing rather than the preview.

        The preview is HTML in an iframe; the watermark, the letterhead and the
        appended pages only exist once wkhtmltopdf has run. Anyone judging those
        three from the preview would be judging the wrong artefact.
        """
        self.ensure_one()
        return self.env.ref('web.action_report_externalpreview').report_action(
            self.company_id)
