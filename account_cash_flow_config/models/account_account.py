from odoo import models, fields

class AccountAccount(models.Model):
    _inherit = 'account.account'

    cash_flow_type = fields.Selection(
        selection=[
            ('operating', 'Operating Activities'),
            ('investing', 'Investing Activities'),
            ('financing', 'Financing Activities'),
        ],
        string='Cash Flow Activity Type',
        help='Specify the cash flow type for this account.',
    )
