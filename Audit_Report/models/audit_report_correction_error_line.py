from odoo import fields, models


class AuditReportCorrectionErrorLine(models.TransientModel):
    _name = 'audit.report.correction.error.line'
    _description = 'Audit Report Correction of Error Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'audit.report',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    row_type = fields.Selection(
        [
            ('section', 'Section'),
            ('subheading', 'Subheading'),
            ('text', 'Text'),
            ('line', 'Line'),
        ],
        required=True,
        default='line',
    )
    description = fields.Char(string='Description')
    amount_as_reported = fields.Float(string='As reported')
    amount_as_restated = fields.Float(string='As re-stated')
    amount_restatement = fields.Float(string='Re-statement')
