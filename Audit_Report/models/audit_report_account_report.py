from odoo import _, models
from odoo.exceptions import ValidationError


class AccountReport(models.Model):
    _inherit = 'account.report'

    def _is_audit_tb_override_trial_balance_context(self):
        self.ensure_one()
        wizard_id = self.env.context.get('audit_tb_override_wizard_id')
        if not wizard_id:
            return False
        trial_balance_report = self.env.ref(
            'account_reports.trial_balance_report',
            raise_if_not_found=False,
        )
        return bool(trial_balance_report and self.id == trial_balance_report.id)

    def _get_audit_tb_override_wizard(self):
        self.ensure_one()
        wizard_id = self.env.context.get('audit_tb_override_wizard_id')
        if not wizard_id:
            raise ValidationError("No audit TB override wizard is linked to this Trial Balance.")
        wizard = self.env['audit.report'].browse(int(wizard_id))
        if not wizard.exists():
            raise ValidationError("The linked audit TB override wizard no longer exists.")
        return wizard.with_company(wizard.company_id).with_context(
            allowed_company_ids=[wizard.company_id.id]
        )

    def _init_options_buttons(self, options, previous_options):
        super()._init_options_buttons(options, previous_options)
        if not self._is_audit_tb_override_trial_balance_context():
            return

        period_key = self.env.context.get('audit_tb_override_period_key') or 'current'
        is_embedded = bool(self.env.context.get('audit_tb_embedded'))
        if is_embedded:
            return

        period_label = _('Current') if period_key == 'current' else _('Prior')
        extra_buttons = [{
            'name': _('Import %s Overrides') % period_label,
            'sequence': 5,
            'action': 'action_import_audit_tb_overrides',
            'always_show': True,
            'branch_allowed': True,
        }]
        extra_buttons.append({
            'name': _('Back to Audit TB Overrides'),
            'sequence': 6,
            'action': 'action_back_to_audit_tb_override',
            'always_show': True,
            'branch_allowed': True,
        })
        options['buttons'] = [*extra_buttons, *options['buttons']]

    def action_import_audit_tb_overrides(self, options):
        self.ensure_one()
        wizard = self._get_audit_tb_override_wizard()
        period_key = self.env.context.get('audit_tb_override_period_key') or 'current'
        return wizard.action_import_tb_overrides_from_odoo_trial_balance_options(
            options,
            period_key=period_key,
        )

    def action_back_to_audit_tb_override(self, options):
        self.ensure_one()
        wizard = self._get_audit_tb_override_wizard()
        return wizard._reopen_wizard_form()
