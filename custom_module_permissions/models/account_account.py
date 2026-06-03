from odoo import _, api, models
from odoo.exceptions import AccessError


class AccountAccount(models.Model):
    _inherit = 'account.account'

    def _check_custom_module_manage_coa_permission(self, operation_label):
        if self.env.context.get('skip_custom_module_manage_coa_check'):
            return
        if self.env.is_superuser() or self.env.user.has_group(
            'custom_module_permissions.group_custom_module_manage_chart_of_accounts'
        ):
            return
        raise AccessError(_(
            "You are not allowed to %(operation)s the Chart of Accounts. "
            "Please contact your administrator."
        ) % {'operation': operation_label})

    @api.model_create_multi
    def create(self, vals_list):
        self._check_custom_module_manage_coa_permission(_('create'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_custom_module_manage_coa_permission(_('modify'))
        return super().write(vals)

    def unlink(self):
        self._check_custom_module_manage_coa_permission(_('delete'))
        return super().unlink()
