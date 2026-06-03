from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    has_trn = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='TRN Number',
        tracking=True,
    )
    has_company_name = fields.Selection(
        [('yes', 'Yes'), ('no', 'No'), ('simplify', 'Simplify')],
        string='Company Name',
        tracking=True,
    )
