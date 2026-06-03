from odoo import fields, models


class AuditReportLorExtraLine(models.TransientModel):
    _name = 'audit.report.lor.extra.line'
    _description = 'Audit Report LOR Extra Main Item'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'audit.report',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    item_text = fields.Text(required=True, string='Main List Item')
