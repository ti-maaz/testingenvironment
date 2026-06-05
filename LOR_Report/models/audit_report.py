from odoo import api, fields, models


class AuditReport(models.TransientModel):
    _inherit = 'audit.report'

    lor_manager_name_display = fields.Char(
        string='Manager Names',
        compute='_compute_lor_manager_name_display',
    )

    @api.depends(
        'shareholder_1',
        'shareholder_2',
        'shareholder_3',
        'shareholder_4',
        'shareholder_5',
        'shareholder_6',
        'shareholder_7',
        'shareholder_8',
        'shareholder_9',
        'shareholder_10',
        'signature_include_1',
        'signature_include_2',
        'signature_include_3',
        'signature_include_4',
        'signature_include_5',
        'signature_include_6',
        'signature_include_7',
        'signature_include_8',
        'signature_include_9',
        'signature_include_10',
    )
    def _compute_lor_manager_name_display(self):
        for wizard in self:
            wizard.lor_manager_name_display = wizard._get_lor_manager_names()

    @staticmethod
    def _join_lor_names(names):
        normalized_names = [str(name or '').strip() for name in names if str(name or '').strip()]
        if not normalized_names:
            return ''
        if len(normalized_names) == 1:
            return normalized_names[0]
        if len(normalized_names) == 2:
            return f'{normalized_names[0]} and {normalized_names[1]}'
        return f"{', '.join(normalized_names[:-1])} and {normalized_names[-1]}"

    def _get_lor_manager_names(self):
        self.ensure_one()
        manager_names = []
        for index in range(1, 11):
            if not getattr(self, f'signature_include_{index}', False):
                continue
            manager_name = (getattr(self, f'shareholder_{index}', '') or '').strip()
            if manager_name:
                manager_names.append(manager_name)
        if manager_names:
            return self._join_lor_names(manager_names)
        return ''

    def action_open_lor_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'lor.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_audit_report_id': self.id,
                'default_company_id': self.company_id.id,
                'form_view_initial_mode': 'edit',
                'dialog_size': 'extra-large',
            },
        }
