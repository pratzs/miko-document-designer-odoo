# -*- coding: utf-8 -*-
from odoo import fields, models

from . import design as design_lib


class ResCompany(models.Model):
    """The company owns the design.

    Only what core has no home for lives here. Logo, colours, font, paper
    format, header, footer, company details and the layout choice are all
    core's own fields on this same model, and the designer screen writes
    straight back to them rather than shadowing them - so other modules reading
    `primary_color` get the truth and uninstalling this module leaves the
    company's branding exactly as it was set.
    """
    _inherit = 'res.company'

    miko_design_active = fields.Boolean(
        string="Apply Miko design", default=True,
        help="Turn off to print exactly as stock Odoo would, without losing "
             "any of the settings below.")

    # -- typography ------------------------------------------------------
    miko_base_font_size = fields.Integer(
        string="Document text size (px)",
        help="0 keeps Odoo's own size.")
    miko_table_font_size = fields.Integer(
        string="Line table text size (px)",
        help="0 keeps Odoo's own size.")
    miko_line_height = fields.Integer(
        string="Line spacing (%)",
        help="0 keeps Odoo's own spacing.")

    # -- line table ------------------------------------------------------
    miko_density = fields.Selection(
        [('default', "Odoo default"), ('compact', "Compact"), ('roomy', "Roomy")],
        string="Row height", default='default', required=True)
    miko_zebra = fields.Boolean(string="Striped rows")
    miko_zebra_color = fields.Char(string="Stripe colour", default='#F2F4F7')
    miko_row_numbers = fields.Boolean(string="Number the lines")
    miko_grid = fields.Selection(
        [('default', "Odoo default"), ('rows', "Horizontal rules"),
         ('grid', "Full grid"), ('none', "No rules")],
        string="Table rules", default='default', required=True)
    miko_head_bg = fields.Char(string="Header row background")
    miko_head_color = fields.Char(string="Header row text")
    miko_line_images = fields.Boolean(string="Product picture on lines")
    miko_line_image_size = fields.Integer(string="Picture size (px)", default=48)

    # -- stamp -----------------------------------------------------------
    miko_watermark_type = fields.Selection(
        [('none', "None"), ('text', "Text"), ('image', "Image")],
        string="Watermark", default='none', required=True)
    miko_watermark_text = fields.Char(string="Watermark text")
    miko_watermark_image = fields.Binary(string="Watermark image", attachment=True)
    miko_watermark_opacity = fields.Integer(string="Watermark opacity (%)", default=12)
    miko_watermark_angle = fields.Integer(string="Watermark angle", default=-30)
    miko_watermark_size = fields.Integer(string="Watermark size (px)", default=90)

    # -- paper -----------------------------------------------------------
    miko_letterhead_pdf = fields.Binary(
        string="Letterhead PDF", attachment=True,
        help="Printed behind every page of every document. Page 1 of this file "
             "is used; the document itself is drawn on top of it, so text stays "
             "selectable.")
    miko_letterhead_pdf_name = fields.Char(string="Letterhead file name")
    miko_append_pdf = fields.Binary(
        string="Append PDF (terms)", attachment=True,
        help="Added after the last page of every document, for terms and "
             "conditions.")
    miko_append_pdf_name = fields.Char(string="Appended file name")

    # -- invoice blocks --------------------------------------------------
    miko_amount_words = fields.Boolean(string="Total in words")
    miko_bank_block = fields.Boolean(string="Bank details block")
    miko_bank_title = fields.Char(string="Bank block title", default="Payment details")

    # -- resolution ------------------------------------------------------
    def _miko_design_values(self):
        """The company's own design, as a plain dict."""
        self.ensure_one()
        return {
            'active': self.miko_design_active,
            'base_font_size': self.miko_base_font_size,
            'table_font_size': self.miko_table_font_size,
            'line_height': self.miko_line_height,
            'density': self.miko_density,
            'zebra': self.miko_zebra,
            'zebra_color': self.miko_zebra_color,
            'row_numbers': self.miko_row_numbers,
            'grid': self.miko_grid,
            'head_bg': self.miko_head_bg,
            'head_color': self.miko_head_color,
            'line_images': self.miko_line_images,
            'line_image_size': self.miko_line_image_size,
            'watermark_type': self.miko_watermark_type,
            'watermark_text': self.miko_watermark_text,
            'watermark_image': self.miko_watermark_image,
            'watermark_opacity': self.miko_watermark_opacity,
            'watermark_angle': self.miko_watermark_angle,
            'watermark_size': self.miko_watermark_size,
            'letterhead_pdf': self.miko_letterhead_pdf,
            'append_pdf': self.miko_append_pdf,
            'amount_words': self.miko_amount_words,
            'bank_block': self.miko_bank_block,
            'bank_title': self.miko_bank_title,
        }

    def _miko_design_for(self, record=None, report=None):
        """The design that applies to one document.

        Company first, then the first matching rule on top. Returns a plain
        dict so QWeb can read it with .get() and a test can compare it without
        a database round trip.
        """
        self.ensure_one()
        values = self._miko_design_values()
        if not values['active']:
            return dict(design_lib.DEFAULTS, active=False)
        rule = self.env['miko.document.rule'].sudo()._miko_match(
            self, record=record, report=report)
        if rule:
            values = design_lib.merged(values, rule._miko_design_values())
        else:
            values = design_lib.merged(values)
        return values
