from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditReportPdfGenerationWarnings(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.AuditReportModel = type(cls.env['audit.report'])

    def _wizard_values(self, **overrides):
        values = {
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'signature_date_mode': 'today',
            'use_previous_settings': False,
            'signature_include_1': True,
            'company_free_zone': 'Meydan Free Zone',
            'company_street': 'Meydan Grandstand, 6th Floor, Meydan Road, Nad Al Sheba',
            'company_city': 'Dubai',
            'company_license_number': 'LIC-001',
            'trade_license_activities': 'Consulting services',
            'incorporation_date': fields.Date.to_date('2020-01-01'),
            'corporate_tax_registration_number': 'CT-001',
            'vat_registration_number': 'VAT-001',
            'corporate_tax_start_date': fields.Date.to_date('2024-01-01'),
            'corporate_tax_end_date': fields.Date.to_date('2024-12-31'),
            'implementing_regulations_freezone': 'Meydan Free Zone Companies and licensing Regulations 2022',
        }
        for index in range(1, 11):
            values[f'shareholder_{index}'] = False
            values[f'number_of_shares_{index}'] = 0
            values[f'share_value_{index}'] = 0.0
        values.update(overrides)
        return values

    def _create_wizard(self, **overrides):
        return self.env['audit.report'].create(self._wizard_values(**overrides))

    @staticmethod
    def _tb_row(code, initial_balance=0.0, end_balance=0.0, name=''):
        return {
            'id': abs(hash((code, name or code))) % 100000 + 1,
            'code': code,
            'code_raw': code,
            'name': name or code,
            'type': 'equity',
            'initial_balance': initial_balance,
            'debit': 0.0,
            'credit': 0.0,
            'end_balance': end_balance,
            'balance_role': 'closing',
        }

    def _mock_tb_fetcher(self, rows_by_range):
        normalized = {}
        for key, rows in rows_by_range.items():
            start_date, end_date = key
            normalized[(
                fields.Date.to_date(start_date) if start_date else False,
                fields.Date.to_date(end_date) if end_date else False,
            )] = [dict(row) for row in rows]

        def _fetch(_wizard, date_start, date_end):
            return [
                dict(row)
                for row in normalized.get((date_start or False, date_end or False), [])
            ]

        return _fetch

    def test_one_year_unpaid_with_invested_capital_opens_warning_modal(self):
        wizard = self._create_wizard(
            share_capital_paid_status='unpaid',
            number_of_shares_1=1,
            share_value_1=100.0,
        )
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [
                self._tb_row('31010101', initial_balance=-100.0, end_balance=-100.0),
            ],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        confirmation = self.env['audit.report.soce.pdf.confirmation'].browse(action['res_id'])
        self.assertFalse(confirmation.show_soce_review)
        self.assertIn('Share capital status is set to Unpaid', confirmation.confirmation_message)

    def test_one_year_paid_with_zero_invested_capital_opens_warning_modal(self):
        wizard = self._create_wizard(share_capital_paid_status='paid')
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        confirmation = self.env['audit.report.soce.pdf.confirmation'].browse(action['res_id'])
        self.assertIn('Share capital status is set to Paid', confirmation.confirmation_message)

    def test_unpaid_status_warns_when_dividend_exists_in_displayed_periods(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            soce_prior_opening_label_date=fields.Date.to_date('2023-01-01'),
            share_capital_paid_status='unpaid',
        )
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [],
            ('2023-01-01', '2023-12-31'): [
                self._tb_row('31010202', initial_balance=0.0, end_balance=-15.0, name='Dividend paid'),
            ],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        confirmation = self.env['audit.report.soce.pdf.confirmation'].browse(action['res_id'])
        self.assertTrue(confirmation.show_soce_review)
        self.assertIn('Dividend paid is not zero', confirmation.confirmation_message)
        self.assertIn('prior: 15.00', confirmation.confirmation_message)

    def test_warning_when_owner_capital_differs_from_shareholder_total(self):
        wizard = self._create_wizard(
            share_capital_paid_status='paid',
            number_of_shares_1=1,
            share_value_1=100.0,
        )
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [
                self._tb_row('31010101', initial_balance=-80.0, end_balance=-80.0),
            ],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        confirmation = self.env['audit.report.soce.pdf.confirmation'].browse(action['res_id'])
        self.assertIn(
            'does not equal the sum of shareholders total share capital',
            confirmation.confirmation_message,
        )

    def test_one_year_matching_share_capital_data_opens_pdf_directly(self):
        wizard = self._create_wizard(
            share_capital_paid_status='paid',
            number_of_shares_1=1,
            share_value_1=100.0,
        )
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [
                self._tb_row('31010101', initial_balance=-100.0, end_balance=-100.0),
            ],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()

        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], f'/audit_report/pdf/{wizard.id}')

    def test_two_year_matching_share_capital_data_still_opens_confirmation_modal(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            soce_prior_opening_label_date=fields.Date.to_date('2023-01-01'),
            share_capital_paid_status='paid',
            number_of_shares_1=1,
            share_value_1=100.0,
        )
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [
                self._tb_row('31010101', initial_balance=-100.0, end_balance=-100.0),
            ],
            ('2023-01-01', '2023-12-31'): [
                self._tb_row('31010101', initial_balance=-100.0, end_balance=-100.0),
            ],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        confirmation = self.env['audit.report.soce.pdf.confirmation'].browse(action['res_id'])
        self.assertTrue(confirmation.show_soce_review)
        self.assertIn('SOCE first balance date review', confirmation.confirmation_message)

    def test_confirmation_modal_confirm_action_still_returns_pdf_url(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            soce_prior_opening_label_date=fields.Date.to_date('2023-01-01'),
            share_capital_paid_status='paid',
            number_of_shares_1=1,
            share_value_1=100.0,
        )
        fetcher = self._mock_tb_fetcher({
            ('2024-01-01', '2024-12-31'): [
                self._tb_row('31010101', initial_balance=-100.0, end_balance=-100.0),
            ],
            ('2023-01-01', '2023-12-31'): [
                self._tb_row('31010101', initial_balance=-100.0, end_balance=-100.0),
            ],
        })

        with patch.object(self.AuditReportModel, '_fetch_grouped_account_rows_from_odoo_trial_balance', fetcher):
            action = wizard.action_print_account_report_pdf()
            confirmation = self.env['audit.report.soce.pdf.confirmation'].browse(action['res_id'])
            confirm_action = confirmation.action_confirm_print_pdf()

        self.assertEqual(confirm_action['type'], 'ir.actions.act_url')
        self.assertEqual(confirm_action['url'], f'/audit_report/pdf/{wizard.id}')
