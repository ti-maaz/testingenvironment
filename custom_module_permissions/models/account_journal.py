from odoo import api, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _with_coa_bypass(self):
        return self.with_context(skip_custom_module_manage_coa_check=True)

    @api.model_create_multi
    def create(self, vals_list):
        return super(AccountJournal, self._with_coa_bypass()).create(vals_list)

    def write(self, vals):
        return super(AccountJournal, self._with_coa_bypass()).write(vals)
