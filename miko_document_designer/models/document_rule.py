# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

TRISTATE = [
    ('inherit', "Company default"),
    ('on', "On"),
    ('off', "Off"),
]


def _tri(value, key, out):
    # 'inherit' writes nothing at all, which is what lets the company value
    # fall through. 'off' writes False and must be kept: a rule that turns a
    # watermark off for one customer is the whole point of having rules.
    if value == 'on':
        out[key] = True
    elif value == 'off':
        out[key] = False
    return out


class MikoDocumentRule(models.Model):
    """One customer, or one document type, printing differently from the rest.

    A rule carries only what it overrides. Everything it leaves on "Company
    default" falls through, so a rule that turns on a watermark for one customer
    does not quietly reset that customer's fonts to the module defaults.
    """
    _name = 'miko.document.rule'
    _description = 'Document Design Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    report_ids = fields.Many2many(
        'ir.actions.report', 'miko_document_rule_report_rel', 'rule_id', 'report_id',
        string="Documents",
        help="Leave empty to apply to every printed document.")
    partner_ids = fields.Many2many(
        'res.partner', 'miko_document_rule_partner_rel', 'rule_id', 'partner_id',
        string="Customers",
        help="Leave empty to apply to every customer. A rule on a company also "
             "covers that company's own contacts.")

    # -- overrides -------------------------------------------------------
    external_report_layout_id = fields.Many2one(
        'ir.ui.view', string="Layout", domain=[('type', '=', 'qweb')],
        help="Leave empty to keep the company's layout.")

    base_font_size = fields.Integer(string="Document text size (px)")
    table_font_size = fields.Integer(string="Line table text size (px)")
    line_height = fields.Integer(string="Line spacing (%)")

    density = fields.Selection(
        [('inherit', "Company default"), ('default', "Odoo default"),
         ('compact', "Compact"), ('roomy', "Roomy")],
        string="Row height", default='inherit', required=True)
    zebra = fields.Selection(TRISTATE, string="Striped rows",
                             default='inherit', required=True)
    zebra_color = fields.Char(string="Stripe colour")
    row_numbers = fields.Selection(TRISTATE, string="Number the lines",
                                   default='inherit', required=True)
    grid = fields.Selection(
        [('inherit', "Company default"), ('default', "Odoo default"),
         ('rows', "Horizontal rules"), ('grid', "Full grid"), ('none', "No rules")],
        string="Table rules", default='inherit', required=True)
    head_bg = fields.Char(string="Header row background")
    head_color = fields.Char(string="Header row text")
    line_images = fields.Selection(TRISTATE, string="Product picture on lines",
                                   default='inherit', required=True)
    line_image_size = fields.Integer(string="Picture size (px)")

    watermark_type = fields.Selection(
        [('inherit', "Company default"), ('none', "None"),
         ('text', "Text"), ('image', "Image")],
        string="Watermark", default='inherit', required=True)
    watermark_text = fields.Char(string="Watermark text")
    watermark_image = fields.Binary(string="Watermark image", attachment=True)
    watermark_opacity = fields.Integer(string="Watermark opacity (%)")
    watermark_angle = fields.Integer(string="Watermark angle")
    watermark_size = fields.Integer(string="Watermark size (px)")

    letterhead_pdf = fields.Binary(string="Letterhead PDF", attachment=True)
    letterhead_pdf_name = fields.Char(string="Letterhead file name")
    no_letterhead = fields.Boolean(
        string="No letterhead",
        help="Print these documents on plain paper even though the company has "
             "a letterhead. Useful for the copies that go on pre-printed stock.")
    append_pdf = fields.Binary(string="Append PDF (terms)", attachment=True)
    append_pdf_name = fields.Char(string="Appended file name")
    no_append = fields.Boolean(
        string="No appended pages",
        help="Skip the company's appended terms for these documents.")

    amount_words = fields.Selection(TRISTATE, string="Total in words",
                                    default='inherit', required=True)
    bank_block = fields.Selection(TRISTATE, string="Bank details",
                                  default='inherit', required=True)
    bank_title = fields.Char(string="Bank block title")

    @api.constrains('watermark_opacity', 'base_font_size', 'table_font_size',
                    'line_height', 'line_image_size', 'watermark_size')
    def _check_ranges(self):
        for rule in self:
            if not 0 <= rule.watermark_opacity <= 100:
                raise ValidationError(
                    "Watermark opacity is a percentage: keep it between 0 and 100.")
            for value, label in (
                (rule.base_font_size, "Document text size"),
                (rule.table_font_size, "Line table text size"),
                (rule.line_image_size, "Picture size"),
                (rule.watermark_size, "Watermark size"),
            ):
                if value and not 4 <= value <= 400:
                    raise ValidationError(
                        "%s has to be between 4 and 400 pixels, or 0 to inherit."
                        % label)
            if rule.line_height and not 50 <= rule.line_height <= 400:
                raise ValidationError(
                    "Line spacing has to be between 50%% and 400%%, or 0 to inherit.")

    def _miko_design_values(self):
        """Only the keys this rule actually overrides."""
        self.ensure_one()
        out = {}
        for key, value in (
            ('base_font_size', self.base_font_size),
            ('table_font_size', self.table_font_size),
            ('line_height', self.line_height),
            ('zebra_color', self.zebra_color),
            ('head_bg', self.head_bg),
            ('head_color', self.head_color),
            ('line_image_size', self.line_image_size),
            ('watermark_text', self.watermark_text),
            ('watermark_image', self.watermark_image),
            ('watermark_opacity', self.watermark_opacity),
            ('watermark_angle', self.watermark_angle),
            ('watermark_size', self.watermark_size),
            ('letterhead_pdf', self.letterhead_pdf),
            ('append_pdf', self.append_pdf),
            ('bank_title', self.bank_title),
        ):
            if value:
                out[key] = value
        if self.density != 'inherit':
            out['density'] = self.density
        if self.grid != 'inherit':
            out['grid'] = self.grid
        if self.watermark_type != 'inherit':
            out['watermark_type'] = self.watermark_type
        if self.no_letterhead:
            out['letterhead_pdf'] = False
        if self.no_append:
            out['append_pdf'] = False
        _tri(self.zebra, 'zebra', out)
        _tri(self.row_numbers, 'row_numbers', out)
        _tri(self.line_images, 'line_images', out)
        _tri(self.amount_words, 'amount_words', out)
        _tri(self.bank_block, 'bank_block', out)
        return out

    @api.model
    def _miko_partner_of(self, record):
        """The partner a document is addressed to, whatever the model calls it."""
        if not record:
            return self.env['res.partner']
        for fname in ('partner_id', 'commercial_partner_id', 'partner_shipping_id'):
            if fname in record._fields:
                partner = record[fname]
                if partner:
                    return partner
        return self.env['res.partner']

    @api.model
    def _miko_match(self, company, record=None, report=None):
        """The first rule that applies, or an empty recordset."""
        rules = self.search([('company_id', '=', company.id)])
        if not rules:
            return self.browse()
        partner = self._miko_partner_of(record)
        commercial = partner.commercial_partner_id if partner else partner
        for rule in rules:
            if rule.report_ids and (not report or report.id not in rule.report_ids.ids):
                continue
            if rule.partner_ids:
                candidates = set(rule.partner_ids.ids)
                if not (partner and (partner.id in candidates
                                     or (commercial and commercial.id in candidates))):
                    continue
            return rule
        return self.browse()
