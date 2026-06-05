from odoo import _, models
from odoo.exceptions import AccessError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _check_bulk_move_action_access(self):
        # Keep the original accounting-manager gate and add the custom feature permission.
        if self.env.is_superuser():
            return

        super()._check_bulk_move_action_access()

        if self.env.user.has_group(
            'custom_module_permissions.group_custom_module_account_move_bulk_reset_to_draft'
        ):
            return

        raise AccessError(_(
            "Only Accounting Managers with the Bulk Reset to Draft permission can use these bulk reset actions."
        ))
