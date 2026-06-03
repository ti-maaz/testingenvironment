from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    vat_category = fields.Selection(
        [
            ('standard', 'Standard Rated Sales'),
            ('zero_rated', 'Zero Rated Sales'),
            ('exempt', 'Exempt Sales'),
            ('out_of_scope', 'Out of Scope'),
        ],
        string='VAT Category',
        default='zero_rated',
        tracking=True,
    )
