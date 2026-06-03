# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, models
from odoo.addons.account.models.chart_template import template
from odoo.exceptions import UserError


AE_TO_CUSTOM_ACCOUNT_XMLID_MAP = {
    'uae_account_102011': 'ae_custom_account_12020101',  # AR
    'uae_account_102012': 'ae_custom_account_12020101',  # PoS AR
    'uae_account_104041': 'ae_custom_account_12030403',  # VAT Input
    'uae_account_104042': 'ae_custom_account_12030404',  # Recoverable VAT Input - Postponed
    'uae_account_104043': 'ae_custom_account_12030405',  # Recoverable VAT Input - Reverse
    'uae_account_131100': 'ae_custom_account_12010101',  # Inventory valuation
    'uae_account_201002': 'ae_custom_account_22020101',  # AP
    'uae_account_201017': 'ae_custom_account_22030204',  # VAT Output
    'uae_account_201020': 'ae_custom_account_22030205',  # VAT Output - Postponed
    'uae_account_400001': 'ae_custom_account_51190101',  # Generic expense fallback
    'uae_account_400053': 'ae_custom_account_51220102',  # FX loss
    'uae_account_400071': 'ae_custom_account_51220104',  # Cash discount loss
    'uae_account_400072': 'ae_custom_account_51220105',  # Customs/import charges
    'uae_account_500001': 'ae_custom_account_41010103',  # Generic income fallback
    'uae_account_500011': 'ae_custom_account_41030502',  # FX gain
    'uae_account_500014': 'ae_custom_account_41030503',  # Cash discount gain
}

AE_CUSTOM_UTILITY_CODES = {
    'account_journal_suspense_account_id': '12040209',          # Bank Suspense Account
    'default_cash_difference_income_account_id': '41030504',    # Cash Difference Gain
    'default_cash_difference_expense_account_id': '51220106',   # Cash Difference Loss
    'transfer_account_id': '12060101',                          # Liquidity Transfer
    'outstanding_inbound': '12040210',                          # Outstanding Receipts
    'outstanding_outbound': '12040211',                         # Outstanding Payments
}


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _filter_existing_template_fields(self, model_name, values):
        model_fields = self.env[model_name]._fields
        return {field_name: value for field_name, value in values.items() if field_name in model_fields}

    def _setup_utility_bank_accounts(self, template_code, company, template_data):
        if template_code != 'ae_custom':
            return super()._setup_utility_bank_accounts(template_code, company, template_data)

        company = company.sudo()
        if company.parent_id:
            for field_name in (
                'account_journal_suspense_account_id',
                'default_cash_difference_income_account_id',
                'default_cash_difference_expense_account_id',
                'transfer_account_id',
            ):
                company[field_name] = company.parent_ids[0][field_name]
            return

        Account = self.env['account.account'].sudo().with_company(company).with_context(active_test=False)
        account_domain = [*Account._check_company_domain(company)]
        accounts_by_code = {
            code: Account.search([*account_domain, ('code', '=', code)], limit=1)
            for code in AE_CUSTOM_UTILITY_CODES.values()
        }
        missing_codes = [code for code, account in accounts_by_code.items() if not account]
        if missing_codes:
            raise UserError(_(
                "Missing utility account codes in custom CoA: %(codes)s",
                codes=', '.join(sorted(missing_codes)),
            ))

        company.account_journal_suspense_account_id = accounts_by_code[AE_CUSTOM_UTILITY_CODES['account_journal_suspense_account_id']]
        company.default_cash_difference_income_account_id = accounts_by_code[AE_CUSTOM_UTILITY_CODES['default_cash_difference_income_account_id']]
        company.default_cash_difference_expense_account_id = accounts_by_code[AE_CUSTOM_UTILITY_CODES['default_cash_difference_expense_account_id']]
        company.transfer_account_id = accounts_by_code[AE_CUSTOM_UTILITY_CODES['transfer_account_id']]

        inbound_outstanding = accounts_by_code[AE_CUSTOM_UTILITY_CODES['outstanding_inbound']]
        outbound_outstanding = accounts_by_code[AE_CUSTOM_UTILITY_CODES['outstanding_outbound']]

        journals = self.env['account.journal'].sudo().with_company(company).search([
            ('company_id', '=', company.id),
            ('type', 'in', ('bank', 'cash', 'credit')),
        ])
        for journal in journals:
            if journal.inbound_payment_method_line_ids:
                journal.inbound_payment_method_line_ids.write({'payment_account_id': inbound_outstanding.id})
            if journal.outbound_payment_method_line_ids:
                journal.outbound_payment_method_line_ids.write({'payment_account_id': outbound_outstanding.id})

    @template('ae_custom')
    def _get_ae_custom_template_data(self):
        return {
            'name': _('United Arab Emirates - Custom Chart of Accounts'),
            'parent': 'ae',
            'code_digits': '8',
            'sequence': 100,
            'property_account_receivable_id': 'ae_custom_account_12020101',
            'property_account_payable_id': 'ae_custom_account_22020101',
        }

    @template('ae_custom', 'res.company')
    def _get_ae_custom_res_company(self):
        values = self._filter_existing_template_fields('res.company', {
            'account_default_pos_receivable_account_id': 'ae_custom_account_12020101',
            'income_account_id': 'ae_custom_account_41010103',
            'expense_account_id': 'ae_custom_account_51190101',
            'income_currency_exchange_account_id': 'ae_custom_account_41030502',
            'expense_currency_exchange_account_id': 'ae_custom_account_51220102',
            'account_journal_early_pay_discount_loss_account_id': 'ae_custom_account_51220104',
            'account_journal_early_pay_discount_gain_account_id': 'ae_custom_account_41030503',
            'account_stock_valuation_id': 'ae_custom_account_12010101',
            'expense_accrual_account_id': 'ae_custom_account_12030201',
            'revenue_accrual_account_id': 'ae_custom_account_22030110',
        })
        return {
            self.env.company.id: values,
        }

    @template('ae_custom', 'account.journal')
    def _get_ae_custom_account_journal(self):
        return {
            'cash': {
                'name': _('Owner Current Account'),
                'type': 'cash',
                'code': 'OCA',
                'default_account_id': 'ae_custom_account_12040101',
                'show_on_dashboard': True,
            },
        }

    @template('ae')
    def _zz_get_ae_template_data_for_ae_custom(self):
        # Parent `ae` template is loaded after `ae_custom` and would otherwise overwrite
        # template_data with `uae_account_*` XMLIDs not present in the custom chart.
        if self.env.company.chart_template != 'ae_custom':
            return {}
        return {
            'code_digits': '8',
            'property_account_receivable_id': 'ae_custom_account_12020101',
            'property_account_payable_id': 'ae_custom_account_22020101',
        }

    @template('ae', 'res.company')
    def _zz_get_ae_res_company_for_ae_custom(self):
        # Keep UAE tax defaults from parent logic, but force account refs to custom XMLIDs.
        if self.env.company.chart_template != 'ae_custom':
            return {}
        values = self._filter_existing_template_fields('res.company', {
            'account_default_pos_receivable_account_id': 'ae_custom_account_12020101',
            'income_currency_exchange_account_id': 'ae_custom_account_41030502',
            'expense_currency_exchange_account_id': 'ae_custom_account_51220102',
            'account_journal_early_pay_discount_loss_account_id': 'ae_custom_account_51220104',
            'account_journal_early_pay_discount_gain_account_id': 'ae_custom_account_41030503',
            'expense_account_id': 'ae_custom_account_51190101',
            'income_account_id': 'ae_custom_account_41010103',
            'account_stock_valuation_id': 'ae_custom_account_12010101',
            'expense_accrual_account_id': 'ae_custom_account_12030201',
            'revenue_accrual_account_id': 'ae_custom_account_22030110',
        })
        return {
            self.env.company.id: values,
        }

    @template('ae_custom', 'account.account')
    def _get_ae_custom_account_account(self):
        values = self._filter_existing_template_fields('account.account', {
            'account_stock_variation_id': 'ae_custom_account_51010101',
        })
        if not values:
            return {}
        return {
            'ae_custom_account_12010101': {
                **values,
            },
        }

    @template('ae_custom', 'account.tax.group')
    def _get_ae_custom_account_tax_group(self):
        return self._parse_csv('ae', 'account.tax.group', module='l10n_ae')

    @template('ae_custom', 'account.tax')
    def _get_ae_custom_account_tax(self):
        tax_data = self._parse_csv('ae', 'account.tax', module='l10n_ae')
        self._remap_ae_account_refs(tax_data)
        self._deref_account_tags('ae_custom', tax_data)
        return tax_data

    @template('ae_custom', 'account.fiscal.position')
    def _get_ae_custom_account_fiscal_position(self):
        return self._parse_csv('ae', 'account.fiscal.position', module='l10n_ae')

    @template('ae', 'account.account')
    def _get_ae_account_account(self):
        # In ae_custom mode we fully own account definitions, so skip UAE account-level tweaks
        # that target XMLIDs not present in the custom chart.
        if self.env.company.chart_template == 'ae_custom':
            return {}
        values = self._filter_existing_template_fields('account.account', {
            'account_stock_variation_id': 'uae_account_400001',
        })
        if not values:
            return {}
        return {
            'uae_account_131100': values,
        }

    def _remap_ae_account_refs(self, tax_data):
        repartition_fields = ('repartition_line_ids', 'invoice_repartition_line_ids', 'refund_repartition_line_ids')
        for values in tax_data.values():
            for field_name in repartition_fields:
                for command in values.get(field_name, []):
                    if not isinstance(command, (list, tuple)) or len(command) < 3:
                        continue
                    command_values = command[2]
                    if not isinstance(command_values, dict):
                        continue
                    account_xmlid = command_values.get('account_id')
                    if not isinstance(account_xmlid, str):
                        continue
                    command_values['account_id'] = AE_TO_CUSTOM_ACCOUNT_XMLID_MAP.get(account_xmlid, account_xmlid)
