import csv

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests.common import tagged
from odoo.tools import file_open


@tagged('post_install', '-at_install')
class TestAECustomTemplate(AccountTestInvoicingCommon):
    country_code = 'AE'
    chart_template = 'ae_custom'

    @classmethod
    def _get_source_accounts(cls):
        source_accounts = {}
        with file_open('l10n_ae_custom_coa/data/template/account.account-ae_custom.csv', 'r') as csv_file:
            for row in csv.DictReader(csv_file):
                source_accounts[row['code']] = row
        return source_accounts

    def test_template_registered(self):
        template_mapping = self.env['account.chart.template']._get_chart_template_mapping(get_all=True)
        self.assertIn('ae_custom', template_mapping)
        self.assertEqual(template_mapping['ae_custom']['parent'], 'ae')

    def test_new_company_load(self):
        company = self._create_company(name='AE Custom CoA Company')

        source_accounts = self._get_source_accounts()
        Account = self.env['account.account'].with_company(company).with_context(active_test=False)
        account_domain = [*self.env['account.account']._check_company_domain(company)]
        company_codes = set(Account.search(account_domain).mapped('code'))

        self.assertTrue(set(source_accounts).issubset(company_codes))
        self.assertEqual(company.income_account_id.code, '41010103')
        self.assertEqual(company.expense_account_id.code, '51190101')
        self.assertEqual(company.account_default_pos_receivable_account_id.code, '12020101')
        self.assertEqual(company.account_journal_suspense_account_id.code, '12040209')
        self.assertEqual(company.default_cash_difference_income_account_id.code, '41030504')
        self.assertEqual(company.default_cash_difference_expense_account_id.code, '51220106')
        self.assertEqual(company.transfer_account_id.code, '12060101')
        self.assertEqual(company.expense_accrual_account_id.code, '12030201')
        self.assertEqual(company.revenue_accrual_account_id.code, '22030110')
        bank_journal = self.env.ref(f'account.{company.id}_bank', raise_if_not_found=False)
        self.assertTrue(bank_journal)
        self.assertEqual(bank_journal.default_account_id.code, '12040201')
        cash_journal = self.env.ref(f'account.{company.id}_cash', raise_if_not_found=False)
        self.assertTrue(cash_journal)
        self.assertEqual(cash_journal.type, 'cash')
        self.assertEqual(cash_journal.name, 'Owner Current Account')
        self.assertEqual(cash_journal.code, 'OCA')
        self.assertEqual(cash_journal.default_account_id.code, '12040101')

        receivable = company.partner_id.with_company(company).property_account_receivable_id
        payable = company.partner_id.with_company(company).property_account_payable_id
        self.assertEqual(receivable.code, '12020101')
        self.assertEqual(payable.code, '22020101')

        sale_tax = self.env.ref(f'account.{company.id}_uae_sale_tax_5_dubai', raise_if_not_found=False)
        purchase_tax = self.env.ref(f'account.{company.id}_uae_purchase_tax_5', raise_if_not_found=False)
        export_tax = self.env.ref(f'account.{company.id}_uae_export_tax', raise_if_not_found=False)
        self.assertTrue(sale_tax)
        self.assertTrue(purchase_tax)
        self.assertTrue(export_tax)

        sale_tax_accounts = set((sale_tax.invoice_repartition_line_ids + sale_tax.refund_repartition_line_ids).mapped('account_id.code'))
        purchase_tax_accounts = set((purchase_tax.invoice_repartition_line_ids + purchase_tax.refund_repartition_line_ids).mapped('account_id.code'))
        self.assertIn('22030204', sale_tax_accounts)
        self.assertIn('12030403', purchase_tax_accounts)
        self.assertNotIn('201017', sale_tax_accounts)

        international_revenue = Account.search([*account_domain, ('code', '=', '41010102')], limit=1)
        self.assertSetEqual(set(international_revenue.tax_ids.ids), {export_tax.id})

        legacy_uae_code = Account.search([*account_domain, ('code', '=', '201017')], limit=1)
        self.assertFalse(legacy_uae_code)
        self.assertFalse(Account.search([*account_domain, ('code', '=', '999997')], limit=1))
        self.assertFalse(Account.search([*account_domain, ('code', '=', '999998')], limit=1))

    def test_no_tax_override(self):
        company = self._create_company(name='AE Custom Tax Integrity Co')

        tax_xmlids = self.env['ir.model.data'].search([
            ('model', '=', 'account.tax'),
            ('module', '=', 'account'),
            ('name', 'like', f'{company.id}_%'),
        ]).mapped('name')

        self.assertTrue(any(name.endswith('_uae_sale_tax_5_dubai') for name in tax_xmlids))
        self.assertFalse(any('_ae_custom_' in name for name in tax_xmlids))

    def test_encoding_normalization(self):
        source_accounts = self._get_source_accounts()
        self.assertIn('51140107', source_accounts)
        self.assertEqual(source_accounts['51140107']['name'], 'Depreciation - IT Equipments')
        self.assertIn('52010101', source_accounts)
        self.assertEqual(source_accounts['52010101']['name'], 'Realized Gain')
        self.assertIn('52010104', source_accounts)
        self.assertEqual(source_accounts['52010104']['name'], 'Unrealized Loss')

    def test_source_account_xmlids_are_unique(self):
        xmlids = []
        with file_open('l10n_ae_custom_coa/data/template/account.account-ae_custom.csv', 'r') as csv_file:
            for row in csv.DictReader(csv_file):
                xmlids.append(row['id'])
        self.assertEqual(len(xmlids), len(set(xmlids)))
