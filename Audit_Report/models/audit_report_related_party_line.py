from odoo import fields, models


class AuditReportRelatedPartyLine(models.TransientModel):
    _name = 'audit.report.related.party.line'
    _description = 'Audit Report Related Party Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'audit.report',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    party_name = fields.Char(string='Related party')
    relationship = fields.Char(string='Nature of relationship')
    transaction = fields.Char(string='Nature of transaction')
    amount = fields.Float(string='Amount (current)')
    amount_prior = fields.Float(string='Amount (prior)')
