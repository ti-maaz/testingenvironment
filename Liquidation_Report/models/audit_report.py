from odoo import models


class AuditReport(models.TransientModel):
    _inherit = 'audit.report'

    def action_open_liquidation_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'liquidation.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_audit_report_id': self.id,
                'default_company_id': self.company_id.id,
                'form_view_initial_mode': 'edit',
                'dialog_size': 'extra-large',
            },
        }
