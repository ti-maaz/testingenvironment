import json
import re
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.Audit_Report.controllers.main import AuditReportController


@tagged('post_install', '-at_install')
class TestAuditReportNoteRendering(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.AuditReportModel = type(cls.env['audit.report'])
        cls.controller = AuditReportController()

    def _wizard_values(self, **overrides):
        values = {
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'balance_sheet_date_mode': 'end_only',
            'prior_year_mode': 'auto',
            'prior_balance_sheet_date_mode': 'end_only',
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'signature_date_mode': 'today',
            'use_previous_settings': False,
        }
        values.update(overrides)
        return values

    def _create_wizard(self, **overrides):
        return self.env['audit.report'].create(self._wizard_values(**overrides))

    def _create_document_with_revision(self, snapshot_json):
        document = self.env['audit.report.document'].create({
            'name': 'Note Render Test Report',
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'source_wizard_json': snapshot_json,
        })
        revision = document.create_revision_from_html('<html><body><p>Base</p></body></html>')
        return revision

    def _render_notes_only_template(
        self,
        template_name,
        *,
        show_prior_year=False,
        ignore_notes_last_page_margins=False,
        note_sections=None,
        note_numbers=None,
        ppe_note_number=False,
        ppe_note_columns=None,
        ppe_note_schedules=None,
        intangible_note_number=False,
        intangible_note_columns=None,
        intangible_note_schedules=None,
        correction_error_note_number=False,
        share_note_number=False,
        share_rows=None,
        authorized_share_capital=0.0,
        total_shares_count=0.0,
        share_value_default=0.0,
        share_capital_paid_status='paid',
        show_prior_year_marker=False,
        prior_year_marker_label=False,
        show_related_parties_note=False,
        related_party_rows=None,
        show_investment_note_schedule=True,
    ):
        wizard = self._create_wizard(
            audit_period_category='normal_2y' if show_prior_year else 'normal_1y',
            ignore_notes_last_page_margins=ignore_notes_last_page_margins,
        )
        lines = [
            {
                'code': f'5102010{idx}',
                'name': f'Line {idx}',
                'current': float(idx * 10),
                'prev': float(idx * 5),
            }
            for idx in range(1, 8)
        ]
        note = {
            'number': 5,
            'label': 'Operating expenses',
            'lines': lines,
            'line_segments': wizard._build_generic_note_render_segments(lines),
            'total_current': sum(line['current'] for line in lines),
            'total_prev': sum(line['prev'] for line in lines),
            'preserve_sign': False,
        }
        rendered_note_sections = note_sections if note_sections is not None else [note]
        rendered_note_numbers = note_numbers if note_numbers is not None else {'pl_opex': 5}
        env = self.controller._get_template_env(self.controller._templates_path())
        template = env.get_template(template_name)
        return template.render(
            sections_to_render=['notes_to_financial_statements'],
            note_numbers=rendered_note_numbers,
            note_sections=rendered_note_sections,
            ppe_note_number=ppe_note_number,
            ppe_note_columns=ppe_note_columns or [],
            ppe_note_schedules=ppe_note_schedules or [],
            intangible_note_number=intangible_note_number,
            intangible_note_columns=intangible_note_columns or [],
            intangible_note_schedules=intangible_note_schedules or [],
            correction_error_note_number=correction_error_note_number,
            share_note_number=share_note_number,
            show_prior_year=show_prior_year,
            show_prior_year_marker=show_prior_year_marker,
            prior_year_marker_label=prior_year_marker_label,
            gap_notes_to_financial_statements=True,
            ignore_notes_last_page_margins=ignore_notes_last_page_margins,
            show_investment_note_schedule=show_investment_note_schedule,
            show_related_parties_note=show_related_parties_note,
            current_group_totals={},
            prev_group_totals={},
            fa_other_receivables_current=0.0,
            fa_note_vat_receivable_current=0.0,
            fa_note_vat_receivable_prev=0.0,
            fa_note_vat_payable_current=0.0,
            fa_note_vat_payable_prev=0.0,
            show_shareholder_note=True,
            show_share_capital_conversion_note=False,
            show_share_capital_transfer_note=False,
            signature_break_lines_notes=2,
            signature_names=['Director One'],
            company_name='Demo Co',
            company=SimpleNamespace(
                street='Demo Street',
                city='Dubai',
                incorporation_date=fields.Date.to_date('2020-01-01'),
            ),
            freezone='IFZA',
            license='53589',
            incorporation_date=fields.Date.to_date('2020-01-01'),
            generated_date_display='01 January 2025',
            report_period_word='period',
            comparative_period_word='period',
            business_activity='consulting',
            business_activity_providing_prefix='',
            business_activity_services_suffix='',
            shareholder_display_text='Director One',
            management_director_text='Director One',
            management_director_title='Director',
            emphasis_note_lines=[],
            share_capital_paid_status=share_capital_paid_status,
            share_rows=share_rows or [],
            authorized_share_capital=authorized_share_capital,
            total_shares_count=total_shares_count,
            share_value_default=share_value_default,
            related_party_rows=related_party_rows or [],
            is_dmcc_company_freezone=False,
            date_end=fields.Date.to_date('2024-12-31'),
        )

    def _render_balance_sheet_only_template(
        self,
        template_name,
        *,
        show_prior_year_marker=False,
        prior_year_marker_label=False,
    ):
        env = self.controller._get_template_env(self.controller._templates_path())
        template = env.get_template(template_name)
        return template.render(
            sections_to_render=['balance_sheet_page'],
            company_name='Demo Co',
            date_end=fields.Date.to_date('2024-12-31'),
            current_group_totals={},
            prev_group_totals={},
            main_head_labels={},
            note_numbers={},
            total_assets=0.0,
            total_liabilities=0.0,
            total_equity=0.0,
            total_of_equity_and_liabilities=0.0,
            prev_total_assets=0.0,
            prev_total_liabilities=0.0,
            prev_total_equity=0.0,
            prev_total_of_equity_and_liabilities=0.0,
            tb_diff_current=0.0,
            tb_diff_prior=0.0,
            tb_warning_current=False,
            tb_warning_prior=False,
            show_prior_year=True,
            show_prior_year_marker=show_prior_year_marker,
            prior_year_marker_label=prior_year_marker_label,
            is_dormant_period=False,
            is_cessation_period=False,
        )

    def _render_auditor_report_template(
        self,
        template_name,
        *,
        note_ref=5,
        show_other_matter=False,
        other_matter_paragraph='',
        other_matter_company_name='Demo Co',
        other_matter_period_word='period',
        other_matter_date_display='30 June 2023',
        show_emphasis_of_matter=True,
    ):
        env = self.controller._get_template_env(self.controller._templates_path())
        template = env.get_template(template_name)
        return template.render(
            sections_to_render=['independent_auditor_report'],
            gap_independent_auditor_report=True,
            report_ended_label='Period Ended',
            date_end=fields.Date.to_date('2024-12-31'),
            company_name='Demo Co',
            report_period_word='period',
            generated_date_display='01 January 2025',
            freezone_selection='default',
            show_other_matter=show_other_matter,
            other_matter_paragraph=other_matter_paragraph,
            other_matter_company_name=other_matter_company_name,
            other_matter_period_word=other_matter_period_word,
            other_matter_date_display=other_matter_date_display,
            show_emphasis_of_matter=show_emphasis_of_matter,
            emphasis_note_items=[{
                'note_ref': note_ref,
                'matter_text': 'the correction of a prior period error',
            }],
            is_default=True,
            is_ifza=False,
        )

    def _render_entity_information_template(self, template_name, owner_display_names):
        env = self.controller._get_template_env(self.controller._templates_path())
        template = env.get_template(template_name)
        return template.render(
            sections_to_render=['entity_information'],
            freezone_selection='default',
            freezone='IFZA',
            signature_names=[],
            report_ended_label='Period Ended',
            report_period_end='31 December 2025',
            owner='',
            owner_display_names=owner_display_names,
            company=SimpleNamespace(street='DSO-IFZA, IFZA Properties', city='Dubai'),
            license='53589',
        )

    @staticmethod
    def _normalize_html_text(html):
        return ' '.join((html or '').split())

    def _render_report_of_directors_html(self, wizard, *, report_data=None):
        return self.controller._render_report_html(
            wizard,
            sections_to_render=['report_of_directors'],
            toc_entries=[],
            report_data=report_data,
            css_content='',
        )

    def _render_report_sections_html(self, wizard, sections_to_render, *, report_data=None):
        return self.controller._render_report_html(
            wizard,
            sections_to_render=sections_to_render,
            toc_entries=[],
            report_data=report_data,
            css_content='',
        )

    def _financial_review_report_data(
        self,
        wizard,
        *,
        revenue_total,
        net_profit_after_tax,
        net_profit_margin,
        show_prior_year=False,
        prev_revenue_total=0.0,
        prev_net_profit_after_tax=0.0,
        prev_net_profit_margin=0.0,
    ):
        display_data = wizard._get_financial_review_net_display_data(
            revenue_total,
            net_profit_after_tax,
            net_profit_margin,
            prev_revenue_total,
            prev_net_profit_after_tax,
            prev_net_profit_margin,
            show_prior_year,
        )
        return {
            'show_prior_year': show_prior_year,
            'gap_report_of_directors': True,
            'signature_names': ['Director One'],
            'signature_break_lines_report_of_directors': 0,
            'generated_date_display': '01 January 2025',
            'replace_going_concern_paragraph': False,
            'liquidation_going_concern_paragraphs': [],
            'cost_of_revenue_total': 0.0,
            'prev_cost_of_revenue_total': 0.0,
            'revenue_total': revenue_total,
            'prev_revenue_total': prev_revenue_total,
            'gross_profit_margin': 0.0,
            'prev_gross_profit_margin': 0.0,
            'gross_profit_margin_label': 'Gross profit margin',
            'net_profit_after_tax': net_profit_after_tax,
            'prev_net_profit_after_tax': prev_net_profit_after_tax,
            'net_profit_margin': net_profit_margin,
            'prev_net_profit_margin': prev_net_profit_margin,
            **display_data,
        }

    def test_collect_note_lines_merges_vat_receivable_and_payable_prefixes(self):
        wizard = self._create_wizard()
        current_map = {
            '1203': {
                '12030101': {'name': 'Advance', 'balance': 15.0},
                '12030401': {'name': 'Input VAT - Main', 'balance': 10.0},
                '12030402': {'name': 'Input VAT - Reverse Charge', 'balance': 5.0},
            },
            '2202': {
                '22020101': {'name': 'Trade Payable', 'balance': 22.0},
            },
            '2203': {
                '22030101': {'name': 'Other Payable', 'balance': 12.0},
                '22030201': {'name': 'Output VAT - Standard Rated', 'balance': 7.0},
                '22030202': {'name': 'Output VAT - Reverse Charge', 'balance': 3.0},
                '22030301': {'name': 'Audit Fee Accrual', 'balance': 5.0},
            },
        }

        receivable_lines = wizard._collect_note_lines(['1203'], current_map, {})
        payable_lines = wizard._collect_note_lines(['2201', '2202', '2203', '2204'], current_map, {})

        vat_receivable = next(line for line in receivable_lines if line['name'] == 'VAT recoverable')
        vat_payable = next(line for line in payable_lines if line['name'] == 'VAT payable')
        audit_fee_accrual = next(
            line for line in payable_lines
            if line['name'] == 'Audit and Accounting fee accrual'
        )

        self.assertEqual(vat_receivable['current'], 15.0)
        self.assertEqual(vat_payable['current'], 10.0)
        self.assertEqual(audit_fee_accrual['current'], 5.0)
        self.assertFalse(any('Input VAT' in line['name'] for line in receivable_lines))
        self.assertFalse(any('Output VAT' in line['name'] for line in payable_lines))
        self.assertFalse(any(line['name'] == 'Audit Fee Accrual' for line in payable_lines))

    def test_collect_note_lines_includes_monies_in_transit_for_cash_and_bank_note(self):
        wizard = self._create_wizard()
        current_map = {
            '1204': {
                '12040101': {'name': 'Owner current account', 'balance': 50.0},
                '12040102': {'name': 'Petty cash', 'balance': 10.0},
                '12040201': {'name': 'Main bank account', 'balance': 20.0},
                '12040301': {'name': 'Monies in transit', 'balance': 30.0},
            },
        }
        prev_map = {
            '1204': {
                '12040102': {'name': 'Petty cash', 'balance': 1.0},
                '12040201': {'name': 'Main bank account', 'balance': 2.0},
                '12040301': {'name': 'Monies in transit', 'balance': 3.0},
            },
        }

        lines = wizard._collect_note_lines(['1204'], current_map, prev_map)
        names = {line['name']: line for line in lines}

        self.assertEqual(names['Cash in hand']['current'], 10.0)
        self.assertEqual(names['Cash at bank']['current'], 20.0)
        self.assertEqual(names['Monies in transit']['current'], 30.0)
        self.assertEqual(names['Monies in transit']['prev'], 3.0)
        self.assertNotIn('Owner current account', names)

    def test_depreciation_expense_filter_keeps_each_account_line_separate(self):
        wizard = self._create_wizard()
        current_map = {
            '5114': {
                '51140101': {'name': 'Depreciation - Buildings & Structures', 'balance': 10.0},
                '51140102': {'name': 'Depreciation - Furniture & Fixtures', 'balance': 20.0},
                '51140201': {'name': 'Amortization - Intangible Assets', 'balance': 30.0},
            },
        }

        filtered_map = wizard._filter_account_head_map_by_prefixes(current_map, ('511401',))
        lines = wizard._collect_note_lines(['5114'], filtered_map, {})

        self.assertEqual(
            [line['name'] for line in lines],
            [
                'Depreciation - Buildings & Structures',
                'Depreciation - Furniture & Fixtures',
            ],
        )
        self.assertEqual([line['current'] for line in lines], [10.0, 20.0])
        self.assertFalse(any(line['code'] == '51140201' for line in lines))

    def test_operating_expense_normalization_merges_requested_labels(self):
        wizard = self._create_wizard()
        normalized = wizard._normalize_operating_expense_note_lines([
            {'code': '51020101', 'name': 'Subcontractor Services', 'current': 10.0, 'prev': 1.0},
            {'code': '51020102', 'name': 'Entertainment Expense', 'current': 8.0, 'prev': 2.0},
            {'code': '51090101', 'name': 'Audit and Accounting Fee', 'current': 11.0, 'prev': 5.0},
            {'code': '51090102', 'name': 'Other Accountant Fee', 'current': 9.0, 'prev': 4.0},
            {'code': '51090103', 'name': 'Audit Fee Accrual', 'current': 6.0, 'prev': 3.0},
            {'code': '51130101', 'name': 'Business Travel', 'current': 7.0, 'prev': 3.0},
            {'code': '51130201', 'name': 'Business Accommodation', 'current': 5.0, 'prev': 4.0},
            {'code': '51250101', 'name': 'Business Insurance Expense', 'current': 6.0, 'prev': 1.0},
            {'code': '51030101', 'name': 'IT Expenses', 'current': 3.0, 'prev': 2.0},
            {'code': '51030102', 'name': 'Software Subscriptions', 'current': 4.0, 'prev': 1.0},
        ])
        names = {line['name']: line for line in normalized}

        self.assertIn('Subcontractor', names)
        self.assertIn('Entertainment', names)
        self.assertIn('Audit and accounting fee', names)
        self.assertIn('Audit and Accounting fee accrual', names)
        self.assertIn('Travelling and accommodation', names)
        self.assertIn('Insurance expense', names)
        self.assertIn('IT expenses', names)
        self.assertEqual(names['Audit and accounting fee']['current'], 20.0)
        self.assertEqual(names['Audit and accounting fee']['prev'], 9.0)
        self.assertEqual(names['Audit and Accounting fee accrual']['current'], 6.0)
        self.assertEqual(names['Travelling and accommodation']['current'], 12.0)
        self.assertEqual(names['IT expenses']['current'], 7.0)
        self.assertNotIn('Software Subscriptions', names)
        self.assertNotIn('Other Accountant Fee', names)
        self.assertNotIn('Audit Fee Accrual', names)

    def test_cost_of_revenue_normalization_renames_requested_labels(self):
        wizard = self._create_wizard()

        normalized = wizard._normalize_cost_of_revenue_note_lines([
            {'code': '51010101', 'name': 'Stock Purchase', 'current': 40.0, 'prev': 10.0},
            {'code': '51010102', 'name': 'Subcontractor Services', 'current': 4.0, 'prev': 1.0},
        ])

        self.assertEqual(normalized[0]['name'], 'Purchases')
        self.assertEqual(normalized[1]['name'], 'Subcontractor')

    def test_prepare_direct_cost_note_adds_work_in_progress_rows_and_adjusts_total(self):
        wizard = self._create_wizard()

        prepared = wizard._prepare_direct_cost_note(
            wizard._normalize_cost_of_revenue_note_lines([
                {'code': '51010101', 'name': 'Stock Purchase', 'current': 214183.0, 'prev': 100.0},
                {
                    'code': '51010102',
                    'name': 'Subcontractor Services',
                    'current': 274405.0,
                    'prev': 50.0,
                },
                {
                    'code': '51010501',
                    'name': 'Closing work in progress',
                    'current': 70326.0,
                    'prev': 10.0,
                },
            ])
        )

        self.assertTrue(prepared['force_single_segment'])
        self.assertEqual(prepared['total_current'], 418262.0)
        self.assertEqual(prepared['total_prev'], 140.0)
        self.assertEqual(
            [line['name'] for line in prepared['lines']],
            [
                'Opening work in progress',
                'Purchases',
                'Subcontractor',
                '',
                'Less: Closing work in progress',
            ],
        )
        self.assertEqual(prepared['lines'][0]['current_display'], '-')
        self.assertEqual(
            prepared['lines'][3]['current_wrap_class'],
            'amount-line amount-line-top-single',
        )
        self.assertEqual(prepared['lines'][4]['current_display'], '(70,326)')

    def test_notes_template_renders_custom_direct_cost_note_rows(self):
        wizard = self._create_wizard()
        prepared = wizard._prepare_direct_cost_note([
            {'code': '51010101', 'name': 'Purchases', 'current': 214183.0, 'prev': 0.0},
            {'code': '51010102', 'name': 'Subcontractor', 'current': 274405.0, 'prev': 0.0},
            {
                'code': '51010501',
                'name': 'Closing work in progress',
                'current': 70326.0,
                'prev': 0.0,
            },
        ])
        note = {
            'number': 8,
            'label': 'Direct cost',
            'lines': prepared['lines'],
            'line_segments': [{
                'show_title': True,
                'show_total': True,
                'lines': prepared['lines'],
            }],
            'total_current': prepared['total_current'],
            'total_prev': prepared['total_prev'],
            'preserve_sign': False,
        }

        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[note],
            note_numbers={'pl_cost': 8},
        )
        normalized_html = self._normalize_html_text(html)

        self.assertIn('Opening work in progress', normalized_html)
        self.assertIn('Less: Closing work in progress', normalized_html)
        self.assertIn('class="total-row note-direct-cost-subtotal"', html)
        self.assertIn('amount-line amount-line-top-single', html)
        self.assertIn('(70,326)', html)
        self.assertIn('418,262', html)

    def test_prepare_direct_cost_note_handles_credit_balanced_closing_wip(self):
        wizard = self._create_wizard()

        prepared = wizard._prepare_direct_cost_note([
            {'code': '51010101', 'name': 'Purchases', 'current': 214183.0, 'prev': 0.0},
            {'code': '51010102', 'name': 'Subcontractor', 'current': 274405.0, 'prev': 0.0},
            {
                'code': '51010501',
                'name': 'Closing work in progress',
                'current': -70326.0,
                'prev': 0.0,
            },
        ])

        self.assertEqual(prepared['total_current'], 418262.0)
        self.assertEqual(prepared['lines'][4]['current_display'], '(70,326)')

    def test_canonical_note_name_renames_staff_salary_variants(self):
        wizard = self._create_wizard()

        self.assertEqual(
            wizard._canonical_note_line_display_name('Staff Salary'),
            'Salaries and wages',
        )
        self.assertEqual(
            wizard._canonical_note_line_display_name('Coaching Staff Salaries'),
            'Salaries and wages',
        )

    def test_full_year_body_period_word_uses_date_span_while_header_stays_report_type(self):
        wizard = self._create_wizard(
            report_type='period',
            date_start=fields.Date.to_date('2024-01-01'),
            date_end=fields.Date.to_date('2024-12-31'),
        )

        report_data = wizard._get_report_data()
        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )

        self.assertEqual(report_data['report_period_word'], 'year')
        self.assertIn('For the Period Ended 31 December 2024 (in AED)', rendered)
        self.assertIn('financial statements for the year ended 31 December 2024.', rendered)

    def test_partial_year_body_period_word_uses_date_span_while_header_stays_report_type(self):
        wizard = self._create_wizard(
            report_type='year',
            date_start=fields.Date.to_date('2024-04-01'),
            date_end=fields.Date.to_date('2024-06-30'),
        )

        report_data = wizard._get_report_data()
        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )
        soce_profit_row = next(
            row for row in report_data['soce_rows']
            if (row.get('label') or '').startswith('Total comprehensive')
        )

        self.assertEqual(report_data['report_period_word'], 'period')
        self.assertEqual(soce_profit_row.get('period_word'), 'period')
        self.assertIn('For the Year Ended 30 June 2024 (in AED)', rendered)
        self.assertIn('financial statements for the period ended 30 June 2024.', rendered)

    def test_full_year_cashflow_cash_equivalent_labels_use_year(self):
        wizard = self._create_wizard(
            report_type='period',
            date_start=fields.Date.to_date('2024-01-01'),
            date_end=fields.Date.to_date('2024-12-31'),
        )

        report_data = wizard._get_report_data()
        rendered = self._normalize_html_text(
            self._render_report_sections_html(
                wizard,
                ['cash_flows'],
                report_data=report_data,
            )
        )

        self.assertEqual(report_data['report_period_word'], 'year')
        self.assertIn('Net profit for the year', rendered)
        self.assertIn('Cash and cash equivalents, beginning of the year', rendered)
        self.assertIn('Cash and cash equivalents, end of the year', rendered)
        self.assertNotIn('Net profit for the period', rendered)
        self.assertNotIn('Cash and cash equivalents, beginning of the period', rendered)
        self.assertNotIn('Cash and cash equivalents, end of the period', rendered)

    def test_two_year_cashflow_cash_equivalent_labels_use_comparative_period_word(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            report_type='period',
            date_start=fields.Date.to_date('2024-01-01'),
            date_end=fields.Date.to_date('2024-12-31'),
        )

        report_data = wizard._get_report_data()
        rendered = self._normalize_html_text(
            self._render_report_sections_html(
                wizard,
                ['cash_flows'],
                report_data=report_data,
            )
        )

        self.assertEqual(report_data['comparative_period_word'], 'year')
        self.assertIn('Net profit for the year', rendered)
        self.assertIn('Cash and cash equivalents, beginning of the year', rendered)
        self.assertIn('Cash and cash equivalents, end of the year', rendered)
        self.assertNotIn('Net profit for the period', rendered)
        self.assertNotIn('Cash and cash equivalents, beginning of the period', rendered)
        self.assertNotIn('Cash and cash equivalents, end of the period', rendered)

    def test_financial_review_1y_shows_net_loss_amount_when_revenue_rounds_to_zero(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        report_data = self._financial_review_report_data(
            wizard,
            revenue_total=0.0,
            net_profit_after_tax=-250.0,
            net_profit_margin=0.0,
        )

        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )

        self.assertEqual(report_data['financial_review_net_current_display_mode'], 'amount')
        self.assertIn('Net (loss)', rendered)
        self.assertIn('(250)', rendered)
        self.assertNotIn('Net profit margin', rendered)
        self.assertNotIn('0.00%', rendered)

    def test_financial_review_1y_shows_net_loss_amount_at_100_percent_loss_margin(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        report_data = self._financial_review_report_data(
            wizard,
            revenue_total=100.0,
            net_profit_after_tax=-100.0,
            net_profit_margin=-100.0,
        )

        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )

        self.assertEqual(report_data['financial_review_net_current_display_mode'], 'amount')
        self.assertIn('Net (loss)', rendered)
        self.assertIn('(100)', rendered)
        self.assertNotIn('(100.00%)', rendered)

    def test_financial_review_1y_keeps_percentage_below_100_percent_loss_margin(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        report_data = self._financial_review_report_data(
            wizard,
            revenue_total=200.0,
            net_profit_after_tax=-100.0,
            net_profit_margin=-50.0,
        )

        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )

        self.assertEqual(report_data['financial_review_net_current_display_mode'], 'margin')
        self.assertIn('Net (loss) margin', rendered)
        self.assertIn('(50.00%)', rendered)

    def test_financial_review_2y_shows_both_amounts_when_one_year_triggers_amount_mode(self):
        wizard = self._create_wizard(audit_period_category='normal_2y')
        report_data = self._financial_review_report_data(
            wizard,
            revenue_total=100.0,
            net_profit_after_tax=-100.0,
            net_profit_margin=-100.0,
            show_prior_year=True,
            prev_revenue_total=1000.0,
            prev_net_profit_after_tax=100.0,
            prev_net_profit_margin=10.0,
        )

        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )

        self.assertEqual(report_data['financial_review_net_current_display_mode'], 'amount')
        self.assertEqual(report_data['financial_review_net_prior_display_mode'], 'amount')
        self.assertIn('Net (loss) / profit', rendered)
        self.assertIn('(100)', rendered)
        self.assertNotIn('(100.00%)', rendered)
        self.assertNotIn('10.00%', rendered)

    def test_financial_review_2y_keeps_percentages_when_neither_year_triggers_amount_mode(self):
        wizard = self._create_wizard(audit_period_category='normal_2y')
        report_data = self._financial_review_report_data(
            wizard,
            revenue_total=200.0,
            net_profit_after_tax=-100.0,
            net_profit_margin=-50.0,
            show_prior_year=True,
            prev_revenue_total=1000.0,
            prev_net_profit_after_tax=100.0,
            prev_net_profit_margin=10.0,
        )

        rendered = self._normalize_html_text(
            self._render_report_of_directors_html(wizard, report_data=report_data)
        )

        self.assertEqual(report_data['financial_review_net_current_display_mode'], 'margin')
        self.assertEqual(report_data['financial_review_net_prior_display_mode'], 'margin')
        self.assertIn('Net (loss) / profit margin', rendered)
        self.assertIn('(50.00%)', rendered)
        self.assertIn('10.00%', rendered)

    def test_cashflow_owner_current_account_uses_period_net_movement(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        owner_current_row = {
            'id': False,
            'code': '12040101',
            'name': 'Owner current account',
            'initial_balance': 100.0,
            'debit': 400.0,
            'credit': 150.0,
            'movement_balance': 250.0,
            'end_balance': 900.0,
            'balance': 900.0,
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(owner_current_row)]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        self.assertEqual(report_data['owner_current_account'], -250.0)

    def test_prior_year_adjustment_is_soce_line_and_cashflow_addback(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        prior_year_adjustment_row = {
            'id': False,
            'code': '31010501',
            'name': 'Prior year adjustment',
            'initial_balance': 0.0,
            'debit': 0.0,
            'credit': 250.0,
            'movement_balance': -250.0,
            'end_balance': -250.0,
            'balance': -250.0,
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(prior_year_adjustment_row)]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        soce_profit_index = next(
            idx for idx, row in enumerate(report_data['soce_rows'])
            if (row.get('label') or '').startswith('Total comprehensive')
        )
        soce_adjustment_row = report_data['soce_rows'][soce_profit_index + 1]

        self.assertEqual(report_data['prior_year_adjustment'], 250.0)
        self.assertEqual(report_data['operating_cashflow_before_working_capital'], 250.0)
        self.assertEqual(report_data['retained_earnings_balance'], 250.0)
        self.assertEqual(soce_adjustment_row['label'], 'Prior year adjustment')
        self.assertEqual(soce_adjustment_row['retained_earnings'], 250.0)
        self.assertEqual(soce_adjustment_row['total_equity'], 250.0)

        html = self._render_report_sections_html(
            wizard,
            ['changes_in_equity', 'cash_flows'],
            report_data=report_data,
        )

        self.assertIn('Prior year adjustment', html)
        self.assertIn('<td class="text-left">Prior year adjustment</td>', html)
        self.assertIn('250.00', html)

    def test_bad_debt_expense_is_cashflow_addback(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        bad_debt_row = {
            'id': False,
            'code': '51220101',
            'name': 'Bad Debts',
            'initial_balance': 0.0,
            'debit': 300.0,
            'credit': 0.0,
            'movement_balance': 300.0,
            'end_balance': 300.0,
            'balance': 300.0,
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(bad_debt_row)]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        self.assertEqual(report_data['net_profit_before_tax'], -300.0)
        self.assertEqual(report_data['bad_debt_expense_addback'], 300.0)
        self.assertEqual(report_data['operating_cashflow_before_working_capital'], 0.0)

        html = self._render_report_sections_html(
            wizard,
            ['cash_flows'],
            report_data=report_data,
        )

        self.assertIn('<td class="text-left">Bad debt expense</td>', html)
        self.assertIn('>300<', html)

    def test_interest_paid_is_reclassified_to_financing_activities(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        interest_rows = [
            {
                'id': False,
                'code': '51240101',
                'name': 'Interest paid on loan',
                'initial_balance': 0.0,
                'debit': 80.0,
                'credit': 0.0,
                'movement_balance': 80.0,
                'end_balance': 80.0,
                'balance': 80.0,
            },
            {
                'id': False,
                'code': '51240102',
                'name': 'Interest paid on credit facilities',
                'initial_balance': 0.0,
                'debit': 40.0,
                'credit': 0.0,
                'movement_balance': 40.0,
                'end_balance': 40.0,
                'balance': 40.0,
            },
        ]

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(row) for row in interest_rows]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        self.assertEqual(report_data['net_profit_before_tax'], -120.0)
        self.assertEqual(report_data['interest_paid_addback'], 120.0)
        self.assertEqual(report_data['interest_paid'], -120.0)
        self.assertEqual(report_data['operating_cashflow_before_working_capital'], 0.0)
        self.assertEqual(report_data['net_cash_generated_from_financing_activities'], -120.0)

        html = self._render_report_sections_html(
            wizard,
            ['cash_flows'],
            report_data=report_data,
        )

        self.assertIn('<td class="text-left">Finance cost</td>', html)
        self.assertIn('<td class="text-left">Interest paid</td>', html)
        self.assertIn('(120)', html)

    def test_gain_on_disposal_is_cashflow_adjustment(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        gain_on_disposal_row = {
            'id': False,
            'code': '41031101',
            'name': 'Gain on Disposal',
            'initial_balance': 0.0,
            'debit': 0.0,
            'credit': 400.0,
            'movement_balance': -400.0,
            'end_balance': -400.0,
            'balance': -400.0,
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(gain_on_disposal_row)]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        self.assertEqual(report_data['net_profit_before_tax'], 400.0)
        self.assertEqual(report_data['gain_on_disposal_adjustment'], -400.0)
        self.assertEqual(report_data['operating_cashflow_before_working_capital'], 0.0)

        html = self._render_report_sections_html(
            wizard,
            ['cash_flows'],
            report_data=report_data,
        )

        self.assertIn('<td class="text-left">Gain on disposal</td>', html)
        self.assertIn('(400)', html)

    def test_generic_note_render_segments_keep_two_rows_at_start_and_end(self):
        wizard = self._create_wizard()
        lines = [
            {'code': f'5102010{idx}', 'name': f'Line {idx}', 'current': float(idx), 'prev': 0.0}
            for idx in range(1, 8)
        ]

        segments = wizard._build_generic_note_render_segments(lines)

        self.assertEqual([len(segment['lines']) for segment in segments], [2, 2, 3])
        self.assertTrue(segments[0]['show_title'])
        self.assertFalse(segments[0]['show_total'])
        self.assertFalse(segments[1]['show_title'])
        self.assertFalse(segments[1]['show_total'])
        self.assertTrue(segments[-1]['show_total'])

    def test_revision_snapshot_restores_ignore_notes_last_page_margins(self):
        wizard = self._create_wizard(ignore_notes_last_page_margins=True)
        snapshot_json = wizard._get_wizard_snapshot_json()
        revision = self._create_document_with_revision(snapshot_json)

        with patch.object(self.AuditReportModel, '_load_tb_override_lines', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_apply_tb_overrides_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: ''), \
                patch.object(self.AuditReportModel, '_apply_lor_extra_items_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            restored_wizard = revision._build_audit_report_wizard_from_snapshot()

        self.assertTrue(json.loads(snapshot_json)['ignore_notes_last_page_margins'])
        self.assertTrue(restored_wizard.ignore_notes_last_page_margins)

    def test_revision_snapshot_restores_investment_note_schedule_checkbox(self):
        wizard = self._create_wizard(show_investment_note_schedule=False)
        snapshot_json = wizard._get_wizard_snapshot_json()
        revision = self._create_document_with_revision(snapshot_json)

        with patch.object(self.AuditReportModel, '_load_tb_override_lines', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_apply_tb_overrides_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: ''), \
                patch.object(self.AuditReportModel, '_apply_lor_extra_items_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            restored_wizard = revision._build_audit_report_wizard_from_snapshot()

        self.assertFalse(json.loads(snapshot_json)['show_investment_note_schedule'])
        self.assertFalse(restored_wizard.show_investment_note_schedule)

    def test_revision_snapshot_restores_business_activity_include_providing(self):
        wizard = self._create_wizard(business_activity_include_providing=False)
        snapshot_json = wizard._get_wizard_snapshot_json()
        revision = self._create_document_with_revision(snapshot_json)

        with patch.object(self.AuditReportModel, '_load_tb_override_lines', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_apply_tb_overrides_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: ''), \
                patch.object(self.AuditReportModel, '_apply_lor_extra_items_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            restored_wizard = revision._build_audit_report_wizard_from_snapshot()

        self.assertFalse(json.loads(snapshot_json)['business_activity_include_providing'])
        self.assertFalse(restored_wizard.business_activity_include_providing)

    def test_business_activity_words_can_be_toggled_across_report_and_notes(self):
        self.company.trade_license_activities = 'Consulting'
        wizard = self._create_wizard(
            business_activity_include_providing=False,
            business_activity_include_services=False,
        )

        report_data = wizard._get_report_data()
        rendered = self._normalize_html_text(
            self._render_report_sections_html(
                wizard,
                ['report_of_directors', 'notes_to_financial_statements'],
                report_data=report_data,
            )
        )

        self.assertEqual(rendered.count('The business activity of the Entity is consulting.'), 2)
        self.assertNotIn('providing consulting', rendered)
        self.assertNotIn('consulting services', rendered)

    def test_dmcc_summary_sheet_renders_dynamic_header_and_portal_account(self):
        self.company.free_zone = 'Dubai Multi Commodities Centre Free Zone'
        wizard = self._create_wizard(report_type='year', portal_account_no='368661')

        rendered = self._normalize_html_text(
            self._render_report_sections_html(
                wizard,
                ['dmcc_sheet'],
                report_data=wizard._get_report_data(),
            )
        )

        self.assertIn('DMCC Summary Sheet', rendered)
        self.assertIn('For the Year Ended 31 December 2024 (in AED)', rendered)
        self.assertIn('Portal Account', rendered)
        self.assertIn('368661', rendered)

    def test_company_free_zone_maps_to_expected_auditor_template(self):
        self.assertEqual(
            self.controller._get_auditor_template_from_company_freezone(
                'Dubai Integrated Economic Zones Authority'
            ),
            'ifza',
        )
        self.assertEqual(
            self.controller._get_auditor_template_from_company_freezone(
                'Dubai Multi Commodities Centre Free Zone'
            ),
            'dmcc',
        )
        self.assertEqual(
            self.controller._get_auditor_template_from_company_freezone('Meydan Free Zone'),
            'default',
        )

    def test_soce_first_balance_label_date_is_manual_only(self):
        wizard = self._create_wizard(audit_period_category='normal_2y')

        report_data = wizard._get_report_data()
        first_balance_row = report_data['soce_rows'][0]

        self.assertEqual(first_balance_row['label'], 'Balance as at ')
        self.assertNotIn('01 January 2023', first_balance_row['label'])
        self.assertIn('set it manually', wizard.soce_warning_message)

    def test_retained_earnings_note_statutory_reserve_movements_follow_balance_deltas(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            soce_prior_opening_label_date=fields.Date.to_date('2023-01-01'),
        )

        def _tb_row(closing_balance, opening_balance):
            return {
                'id': False,
                'code': '31010301',
                'name': 'Statutory reserves',
                'initial_balance': opening_balance,
                'debit': 0.0,
                'credit': 0.0,
                'balance': closing_balance,
            }

        rows_by_range = {
            ('2024-01-01', '2024-12-31'): [_tb_row(210.0, 150.0)],
            ('2023-01-01', '2023-12-31'): [_tb_row(150.0, 90.0)],
            ('2022-01-01', '2022-12-31'): [_tb_row(90.0, 40.0)],
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            return [dict(row) for row in rows_by_range.get(range_key, [])]

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        prior_opening_balance_row = next(
            row for row in report_data['soce_rows']
            if row.get('is_balance')
        )
        prior_opening_statutory_reserves = prior_opening_balance_row.get('statutory_reserves')

        self.assertEqual(report_data['notes_statutory_reserves_equity'], 210.0)
        self.assertEqual(report_data['notes_prev_statutory_reserves_equity'], 150.0)
        self.assertEqual(report_data['notes_statutory_reserves_movement'], 60.0)
        self.assertEqual(report_data['notes_prev_statutory_reserves_movement'], 60.0)
        self.assertEqual(
            report_data['notes_statutory_reserves_movement'],
            report_data['notes_statutory_reserves_equity'] - report_data['notes_prev_statutory_reserves_equity'],
        )
        self.assertEqual(
            report_data['notes_prev_statutory_reserves_movement'],
            report_data['notes_prev_statutory_reserves_equity'] - prior_opening_statutory_reserves,
        )

    def test_notes_template_renders_segmented_tbodies_and_bottom_margin_page_class(self):
        html_default = self._render_notes_only_template(
            'audit_report_template.html',
            show_prior_year=False,
            ignore_notes_last_page_margins=False,
        )
        html_compact = self._render_notes_only_template(
            'audit_report_template.html',
            show_prior_year=False,
            ignore_notes_last_page_margins=True,
        )

        self.assertEqual(html_default.count('note-block note-block-segment'), 3)
        self.assertEqual(html_compact.count('note-block note-block-segment'), 3)
        self.assertEqual(html_default.count('<br>'), 2)
        self.assertEqual(html_compact.count('<br>'), 2)
        self.assertIn('notes-ignore-bottom-margin', html_compact)
        self.assertNotIn('notes-ignore-bottom-margin', html_default)

    def test_notes_template_2y_renders_segmented_tbodies(self):
        html = self._render_notes_only_template(
            'audit_report_template_2y.html',
            show_prior_year=True,
            ignore_notes_last_page_margins=False,
        )

        self.assertEqual(html.count('note-block note-block-segment'), 3)

    def test_inventory_note_is_renamed_to_investments_and_gets_schedule_marker(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        inventory_row = {
            'id': False,
            'code': '12010101',
            'name': 'Inventory',
            'initial_balance': 0.0,
            'debit': 100.0,
            'credit': 0.0,
            'movement_balance': 100.0,
            'end_balance': 100.0,
            'balance': 100.0,
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(inventory_row)]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        note = next(
            section for section in report_data['note_sections']
            if section.get('key') == '1201'
        )
        self.assertEqual(note['label'], 'Investments')
        self.assertTrue(note['is_investment_note'])

    def test_investments_note_renders_schedule_below_value_lines(self):
        wizard = self._create_wizard()
        investments_lines = [{
            'code': '12010101',
            'name': 'Inventory',
            'current': 100.0,
            'prev': 0.0,
        }]
        investments_note = {
            'key': '1201',
            'number': 5,
            'label': 'Investments',
            'lines': investments_lines,
            'line_segments': wizard._build_generic_note_render_segments(investments_lines),
            'total_current': 100.0,
            'total_prev': 0.0,
            'is_investment_note': True,
        }

        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[investments_note],
            note_numbers={'1201': 5},
        )

        self.assertIn('Investments</span>', html)
        self.assertIn('investment-note-table', html)
        self.assertIn('Fund Name', html)
        self.assertIn('No. of Shares', html)
        self.assertIn('NAV/Unit', html)
        self.assertIn('Total Value<br>(FCY)', html)
        self.assertIn('Exchange<br>Rate', html)
        self.assertIn('Value in<br>AED', html)
        self.assertIn('Total</td>', html)
        self.assertIn('Inventory', html)
        self.assertIn('100.00', html)
        self.assertLess(html.index('Inventory'), html.index('investment-note-table'))

    def test_investments_note_schedule_can_be_hidden(self):
        wizard = self._create_wizard()
        investments_lines = [{
            'code': '12010101',
            'name': 'Inventory',
            'current': 100.0,
            'prev': 0.0,
        }]
        investments_note = {
            'key': '1201',
            'number': 5,
            'label': 'Investments',
            'lines': investments_lines,
            'line_segments': wizard._build_generic_note_render_segments(investments_lines),
            'total_current': 100.0,
            'total_prev': 0.0,
            'is_investment_note': True,
        }

        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[investments_note],
            note_numbers={'1201': 5},
            show_investment_note_schedule=False,
        )

        self.assertIn('Investments</span>', html)
        self.assertIn('Inventory', html)
        self.assertIn('100.00', html)
        self.assertNotIn('investment-note-table', html)

    def test_ppe_note_splits_land_and_buildings_columns(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )
        ppe_rows = [
            {
                'id': False,
                'code': '11010101',
                'name': 'Land',
                'initial_balance': 1000.0,
                'debit': 100.0,
                'credit': 0.0,
                'movement_balance': 100.0,
                'end_balance': 1100.0,
                'balance': 1100.0,
            },
            {
                'id': False,
                'code': '11010102',
                'name': 'Buildings & Structures',
                'initial_balance': 2000.0,
                'debit': 200.0,
                'credit': 0.0,
                'movement_balance': 200.0,
                'end_balance': 2200.0,
                'balance': 2200.0,
            },
            {
                'id': False,
                'code': '11010103',
                'name': 'Accumulated Depreciation - Buildings & Structures',
                'initial_balance': -300.0,
                'debit': 0.0,
                'credit': 50.0,
                'movement_balance': -50.0,
                'end_balance': -350.0,
                'balance': -350.0,
            },
        ]

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(row) for row in ppe_rows]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        self.assertEqual(
            [column['label'] for column in report_data['ppe_note_columns']],
            ['Land', 'Building and Structures', 'Total'],
        )
        self.assertEqual(
            [column['code'] for column in report_data['ppe_note_columns']],
            ['land', 'buildings', 'total'],
        )
        schedule_rows = report_data['ppe_note_schedules'][0]['rows']
        cost_opening_row = next(
            row for row in schedule_rows
            if row.get('row_type') == 'line' and row.get('label') == 'As at 01 January 2024'
        )
        charge_row = next(row for row in schedule_rows if row.get('label') == 'Depreciation for the year')
        carrying_row = next(
            row for row in schedule_rows
            if row.get('label') == 'Carrying value as at 31 December 2024'
        )
        self.assertEqual(cost_opening_row['values'], [1000.0, 2000.0, 3000.0])
        self.assertEqual(charge_row['values'], [0.0, 50.0, 50.0])
        self.assertEqual(carrying_row['values'], [1100.0, 1850.0, 2950.0])

    def test_ppe_note_renders_explicit_equal_width_value_columns(self):
        ppe_note_columns = [
            {'code': 'furniture', 'label': 'Furniture and fixtures'},
            {'code': 'it', 'label': 'IT equipments'},
            {'code': 'office', 'label': 'Office equipments'},
            {'code': 'total', 'label': 'Total'},
        ]
        ppe_note_schedules = [{
            'rows': [
                {
                    'row_type': 'section',
                    'label': 'Cost',
                    'values': [None, None, None, None],
                },
                {
                    'row_type': 'line',
                    'label': 'As at 01 January 2025',
                    'values': [18158.0, 1599.0, 0.0, 19757.0],
                },
            ],
        }]
        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[{
                'number': 5,
                'label': 'Property plant and equipment',
                'lines': [],
                'line_segments': [],
                'total_current': 0.0,
                'total_prev': 0.0,
                'preserve_sign': False,
            }],
            note_numbers={'1101': 5},
            ppe_note_number=5,
            ppe_note_columns=ppe_note_columns,
            ppe_note_schedules=ppe_note_schedules,
        )

        self.assertIn('<colgroup>', html)
        self.assertIn('class="ppe-note-col-label"', html)
        self.assertEqual(html.count('class="ppe-note-col-value"'), len(ppe_note_columns))
        self.assertIn('--ppe-value-column-count: 4;', html)

    def test_intangible_note_renders_like_ppe_schedule_in_both_runtime_templates(self):
        intangible_note_columns = [
            {'code': '110701', 'label': 'Software & Licences'},
            {'code': '110702', 'label': 'Website & Blogs'},
            {'code': '110703', 'label': 'Other Intangible Assets'},
            {'code': 'total', 'label': 'Total'},
        ]
        intangible_note_schedules = [{
            'start_label': '01 January 2024',
            'end_label': '31 December 2024',
            'period_word': 'year',
            'rows': [
                {
                    'row_type': 'section',
                    'label': 'Cost',
                    'values': [None, None, None, None],
                },
                {
                    'row_type': 'line',
                    'label': 'As at 01 January 2024',
                    'values': [100.0, 200.0, 300.0, 600.0],
                },
                {
                    'row_type': 'line',
                    'label': 'Additions during the year',
                    'values': [10.0, 20.0, 30.0, 60.0],
                },
                {
                    'row_type': 'subtotal',
                    'css_class': 'ppe-row-cost-subtotal',
                    'label': 'As at 31 December 2024',
                    'values': [110.0, 220.0, 330.0, 660.0],
                },
                {
                    'row_type': 'section',
                    'label': 'Accumulated amortization',
                    'values': [None, None, None, None],
                },
                {
                    'row_type': 'line',
                    'label': 'As at 01 January 2024',
                    'values': [15.0, 5.0, 0.0, 20.0],
                },
                {
                    'row_type': 'line',
                    'label': 'Amortization for the year',
                    'values': [5.0, 3.0, 2.0, 10.0],
                },
                {
                    'row_type': 'subtotal',
                    'label': 'As at 31 December 2024',
                    'values': [20.0, 8.0, 2.0, 30.0],
                },
                {
                    'row_type': 'final',
                    'label': 'Carrying value as at 31 December 2024',
                    'values': [90.0, 212.0, 328.0, 630.0],
                },
            ],
        }]
        note_sections = [{
            'number': 6,
            'label': 'Intangible assets',
            'lines': [],
            'line_segments': [],
            'total_current': 0.0,
            'total_prev': 0.0,
            'preserve_sign': False,
        }]

        for template_name, show_prior_year in (
            ('audit_report_template.html', False),
            ('audit_report_template_2y.html', True),
        ):
            html = self._render_notes_only_template(
                template_name,
                show_prior_year=show_prior_year,
                note_sections=note_sections,
                note_numbers={'1107': 6},
                intangible_note_number=6,
                intangible_note_columns=intangible_note_columns,
                intangible_note_schedules=intangible_note_schedules,
            )

            self.assertIn('intangible-note-block', html)
            self.assertIn('Software and Licences', html)
            self.assertIn('Accumulated amortization', html)
            self.assertIn('Amortization for the year', html)
            self.assertIn('Carrying value as at 31 December 2024', html)
            self.assertIn('--ppe-value-column-count: 4;', html)
            self.assertEqual(html.count('class="ppe-note-col-value"'), len(intangible_note_columns))

    def test_ppe_note_css_bolds_headers_subtotal_and_grand_total_rows(self):
        css_content = self.controller._get_cached_css_content(self.controller._css_path())

        self.assertIn(
            '.statement-table.note-sections-table .ppe-note-table .ppe-row-subtotal td',
            css_content,
        )
        self.assertIn(
            '.statement-table.note-sections-table .ppe-note-table .ppe-row-final td',
            css_content,
        )
        self.assertRegex(
            css_content,
            r'\.ppe-note-table th\s*\{[^}]*font-weight:\s*bold;',
        )
        self.assertRegex(
            css_content,
            r'\.ppe-note-table \.ppe-note-currency\s*\{[^}]*font-weight:\s*bold;',
        )
        self.assertRegex(
            css_content,
            r'\.ppe-note-table \.ppe-note-amount\s*\{[^}]*font-weight:\s*normal;',
        )
        self.assertRegex(
            css_content,
            r'\.ppe-note-table \.ppe-row-section td\s*\{[^}]*font-weight:\s*normal;',
        )

    def test_prior_year_column_css_keeps_only_totals_bold(self):
        css_content = self.controller._get_cached_css_content(self.controller._css_path())

        self.assertIn('.statement-table.has-prior th:nth-child(4),', css_content)
        self.assertIn('.statement-table.has-prior td:nth-child(4) {\n    font-weight: normal;', css_content)
        self.assertIn('.statement-table .total-row td {\n    font-weight: bold;', css_content)
        self.assertIn('.statement-table .grand-total-row td {\n    font-weight: bold;', css_content)
        self.assertIn(
            '.statement-table.note-sections-table thead.note-sections-year-header-block '
            'tr.note-sections-year-header th:nth-child(4)',
            css_content,
        )
        self.assertIn('.note-financial-table td:nth-child(3) {\n    font-weight: normal;', css_content)
        self.assertIn(
            '.note-financial-table .total-row td:nth-child(3) {\n    font-weight: normal;',
            css_content,
        )
        self.assertIn(
            '.related-parties-table.related-parties-2y .rp-subheads th.rp-prior-year',
            css_content,
        )

    def test_previous_settings_round_trip_preserves_correction_error_payload(self):
        wizard = self._create_wizard(
            emphasis_correction_error=True,
            correction_error_note_body='Paragraph one\nParagraph two',
        )
        wizard.correction_error_line_ids = wizard._correction_error_rows_to_commands(
            [
                {'sequence': 10, 'row_type': 'section', 'description': 'Effect on statement of financial position'},
                {'sequence': 20, 'row_type': 'line', 'description': 'Cash and bank balance', 'amount_as_reported': 10.0, 'amount_as_restated': 15.0, 'amount_restatement': 5.0},
            ],
            clear_existing=True,
        )

        wizard._store_previous_settings()

        restored = self._create_wizard(use_previous_settings=True)
        restored._onchange_use_previous_settings()

        self.assertTrue(restored.emphasis_correction_error)
        self.assertEqual(restored.correction_error_note_body, 'Paragraph one\nParagraph two')
        self.assertEqual(len(restored.correction_error_line_ids), 2)
        self.assertEqual(restored.correction_error_line_ids[0].row_type, 'section')
        self.assertEqual(restored.correction_error_line_ids[1].description, 'Cash and bank balance')

    def test_previous_settings_round_trip_preserves_unaudited_prior_year_flag(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            show_unaudited_prior_year=True,
        )

        wizard._store_previous_settings()

        restored = self._create_wizard(use_previous_settings=True)
        restored._onchange_use_previous_settings()

        self.assertTrue(restored.show_unaudited_prior_year)

    def test_previous_settings_round_trip_preserves_portal_account_no(self):
        wizard = self._create_wizard(portal_account_no='DMCC-368661')

        wizard._store_previous_settings()

        previous = wizard._get_previous_settings()
        restored = self._create_wizard(use_previous_settings=True, portal_account_no=False)
        restored._onchange_use_previous_settings()
        defaults = self.env['audit.report'].default_get(['portal_account_no'])

        self.assertEqual(previous['portal_account_no'], 'DMCC-368661')
        self.assertEqual(restored.portal_account_no, 'DMCC-368661')
        self.assertEqual(defaults['portal_account_no'], 'DMCC-368661')

    def test_share_capital_note_formats_whole_currency_amounts_without_trailing_decimal(self):
        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[{
                'number': 2,
                'label': 'Share capital',
                'lines': [],
                'line_segments': [],
                'total_current': 0.0,
                'total_prev': 0.0,
                'preserve_sign': False,
            }],
            note_numbers={'share_capital': 2},
            share_note_number=2,
            share_rows=[
                {'name': 'Member One', 'value': 1.0, 'shares': 4, 'total': 4.0},
                {'name': 'Member Two', 'value': 1.25, 'shares': 1, 'total': 1.25},
            ],
            authorized_share_capital=5.25,
            total_shares_count=5,
            share_value_default=1.0,
        )

        self.assertIn('Authorized share capital of the Entity is AED 5.25', html)
        self.assertIn('shares of AED 1 each', html)
        self.assertIn('>4</td>', html)
        self.assertIn('>1.25</td>', html)
        self.assertNotIn('1.0', html)
        self.assertNotIn('4.0', html)

    def test_share_capital_note_renders_paid_status_sentence(self):
        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[{
                'number': 2,
                'label': 'Share capital',
                'lines': [],
                'line_segments': [],
                'total_current': 0.0,
                'total_prev': 0.0,
                'preserve_sign': False,
            }],
            note_numbers={'share_capital': 2},
            share_note_number=2,
            share_rows=[{'name': 'Member One', 'value': 1.0, 'shares': 4, 'total': 4.0}],
            authorized_share_capital=4.0,
            total_shares_count=4,
            share_value_default=1.0,
        )

        self.assertIn(
            'The capital of the Entity is paid and is represented and distributed in the following manner:',
            html,
        )

    def test_share_capital_note_renders_unpaid_status_sentence(self):
        html = self._render_notes_only_template(
            'audit_report_template.html',
            note_sections=[{
                'number': 2,
                'label': 'Share capital',
                'lines': [],
                'line_segments': [],
                'total_current': 0.0,
                'total_prev': 0.0,
                'preserve_sign': False,
            }],
            note_numbers={'share_capital': 2},
            share_note_number=2,
            share_rows=[{'name': 'Member One', 'value': 1.0, 'shares': 4, 'total': 4.0}],
            authorized_share_capital=4.0,
            total_shares_count=4,
            share_value_default=1.0,
            share_capital_paid_status='unpaid',
        )

        self.assertIn(
            'The capital of the Entity is unpaid and is represented and distributed in the following manner:',
            html,
        )

    def test_notes_template_renders_correction_error_note_before_regular_notes(self):
        wizard = self._create_wizard(audit_period_category='normal_2y')
        regular_lines = [
            {'code': '51020101', 'name': 'Administrative expense', 'current': 40.0, 'prev': 30.0},
            {'code': '51020102', 'name': 'Professional fee', 'current': 20.0, 'prev': 10.0},
        ]
        correction_note = {
            'key': 'correction_error',
            'number': 5,
            'label': 'Correction of Error',
            'paragraphs': ['Prior period balances were corrected.', 'Comparatives were re-stated accordingly.'],
            'correction_header_date_display': '31 December 2023',
            'correction_rows': [
                {'sequence': 10, 'row_type': 'section', 'description': 'Effect on statement of financial position'},
                {'sequence': 20, 'row_type': 'subheading', 'description': 'Current assets'},
                {'sequence': 30, 'row_type': 'line', 'description': 'Cash and bank balance', 'amount_as_reported': 354163.0, 'amount_as_restated': 765463.0, 'amount_restatement': 411300.0},
                {'sequence': 40, 'row_type': 'text', 'description': 'There is no effect on statement of comprehensive income'},
            ],
        }
        regular_note = {
            'number': 6,
            'label': 'Operating expenses',
            'lines': regular_lines,
            'line_segments': wizard._build_generic_note_render_segments(regular_lines),
            'total_current': 60.0,
            'total_prev': 40.0,
            'preserve_sign': False,
        }

        html = self._render_notes_only_template(
            'audit_report_template_2y.html',
            show_prior_year=True,
            note_sections=[correction_note, regular_note],
            note_numbers={'correction_error': 5, 'pl_opex': 6},
            correction_error_note_number=5,
            show_prior_year_marker=True,
            prior_year_marker_label='Re-stated',
        )

        self.assertIn('Correction of Error', html)
        self.assertIn('As re-stated', html)
        self.assertIn('Effect on statement of financial position', html)
        self.assertIn('correction-error-date-heading', html)
        self.assertIn('correction-error-currency-head', html)
        self.assertLess(html.index('Effect on statement of financial position'), html.index('Current assets'))
        self.assertLess(html.index('Current assets'), html.index('Cash and bank balance'))
        self.assertLess(html.index('Correction of Error'), html.index('Operating expenses'))
        self.assertIn('Re-stated', html)

    def test_notes_template_renders_unaudited_prior_year_marker(self):
        html = self._render_notes_only_template(
            'audit_report_template_2y.html',
            show_prior_year=True,
            show_prior_year_marker=True,
            prior_year_marker_label='Unaudited',
        )

        self.assertIn('Unaudited', html)

    def test_balance_sheet_template_renders_configured_prior_year_marker_label(self):
        html_default = self._render_balance_sheet_only_template(
            'audit_report_template_2y.html',
            show_prior_year_marker=False,
        )
        html_flagged = self._render_balance_sheet_only_template(
            'audit_report_template_2y.html',
            show_prior_year_marker=True,
            prior_year_marker_label='Unaudited',
        )

        self.assertNotIn('Unaudited', html_default)
        self.assertIn('Unaudited', html_flagged)

    def test_report_data_builds_unaudited_other_matter_paragraph_with_period_logic(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            report_type='year',
            date_start=fields.Date.to_date('2024-04-01'),
            date_end=fields.Date.to_date('2024-06-30'),
            show_unaudited_prior_year=True,
            soce_prior_opening_label_date=fields.Date.to_date('2023-04-01'),
        )
        report_data = wizard._get_report_data()

        self.assertTrue(report_data['show_unaudited_prior_year'])
        self.assertTrue(report_data['show_prior_year_marker'])
        self.assertEqual(report_data['prior_year_marker_label'], 'Unaudited')
        self.assertTrue(report_data['show_other_matter'])
        self.assertEqual(report_data['other_matter_period_word'], 'period')
        self.assertEqual(report_data['other_matter_date_display'], '30 June 2023')
        self.assertIn('for the period ended 30 June 2023 were unaudited.', report_data['other_matter_paragraph'])

    def test_report_data_uses_loan_from_related_party_balance_sheet_label(self):
        wizard = self._create_wizard()

        report_data = wizard._get_report_data()

        self.assertEqual(report_data['main_head_labels']['2102'], 'Loan from related party')

    def test_report_data_warns_when_director_salary_exists_and_related_party_note_is_off(self):
        wizard = self._create_wizard(show_related_parties_note=False)

        def _director_salary_row(amount):
            return {
                'id': False,
                'code': '51070101',
                'name': "Director's Salary",
                'initial_balance': 0.0,
                'debit': amount,
                'credit': 0.0,
                'balance': amount,
            }

        rows_by_range = {
            (
                fields.Date.to_string(wizard.date_start),
                fields.Date.to_string(wizard.date_end),
            ): [_director_salary_row(1200.0)],
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            return [dict(row) for row in rows_by_range.get(range_key, [])]

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        warning_text = report_data.get('tb_warning_current') or ''
        self.assertIn('Director salary account (51070101)', warning_text)
        self.assertIn('related parties checkbox is not selected', warning_text)

    def test_report_data_skips_director_salary_related_party_warning_when_note_is_on(self):
        wizard = self._create_wizard(show_related_parties_note=True)

        def _director_salary_row(amount):
            return {
                'id': False,
                'code': '51070101',
                'name': "Director's Salary",
                'initial_balance': 0.0,
                'debit': amount,
                'credit': 0.0,
                'balance': amount,
            }

        rows_by_range = {
            (
                fields.Date.to_string(wizard.date_start),
                fields.Date.to_string(wizard.date_end),
            ): [_director_salary_row(1200.0)],
        }

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            return [dict(row) for row in rows_by_range.get(range_key, [])]

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        warning_text = report_data.get('tb_warning_current') or ''
        self.assertNotIn('Director salary account (51070101)', warning_text)

    def test_report_data_uses_stocks_balance_sheet_label_for_1207(self):
        wizard = self._create_wizard()

        report_data = wizard._get_report_data()

        self.assertEqual(report_data['main_head_labels']['1207'], 'Stocks')
        self.assertIn('Stocks', report_data['current_assets'])

    def test_new_non_current_groups_render_without_notes_and_feed_cashflow(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        current_range = (
            fields.Date.to_string(wizard.date_start),
            fields.Date.to_string(wizard.date_end),
        )

        rows = [
            {
                'id': False,
                'code': '11100101',
                'name': 'Investing Activity - 1',
                'initial_balance': 50.0,
                'debit': 25.0,
                'credit': 0.0,
                'movement_balance': 25.0,
                'end_balance': 75.0,
                'balance': 75.0,
            },
            {
                'id': False,
                'code': '11110101',
                'name': 'Non Current Assets',
                'initial_balance': 80.0,
                'debit': 20.0,
                'credit': 0.0,
                'movement_balance': 20.0,
                'end_balance': 100.0,
                'balance': 100.0,
            },
            {
                'id': False,
                'code': '11070101',
                'name': 'Software License - Cost',
                'initial_balance': 120.0,
                'debit': 15.0,
                'credit': 0.0,
                'movement_balance': 15.0,
                'end_balance': 135.0,
                'balance': 135.0,
            },
            {
                'id': False,
                'code': '11070103',
                'name': 'Accumulated Amortization - Intangibles',
                'initial_balance': -30.0,
                'debit': 0.0,
                'credit': 5.0,
                'movement_balance': -5.0,
                'end_balance': -35.0,
                'balance': -35.0,
            },
            {
                'id': False,
                'code': '21050101',
                'name': 'Financing Activity - 1',
                'initial_balance': -50.0,
                'debit': 0.0,
                'credit': 40.0,
                'movement_balance': -40.0,
                'end_balance': -90.0,
                'balance': -90.0,
            },
            {
                'id': False,
                'code': '21060101',
                'name': 'Non Current Liabilities',
                'initial_balance': -100.0,
                'debit': 0.0,
                'credit': 30.0,
                'movement_balance': -30.0,
                'end_balance': -130.0,
                'balance': -130.0,
            },
            {
                'id': False,
                'code': '21070101',
                'name': 'Deposit',
                'initial_balance': -200.0,
                'debit': 0.0,
                'credit': 60.0,
                'movement_balance': -60.0,
                'end_balance': -260.0,
                'balance': -260.0,
            },
        ]

        def _fake_fetch_grouped_rows(_wizard, date_start, date_end):
            range_key = (
                fields.Date.to_string(date_start) if date_start else False,
                fields.Date.to_string(date_end) if date_end else False,
            )
            if range_key == current_range:
                return [dict(row) for row in rows]
            return []

        with patch.object(
            self.AuditReportModel,
            '_fetch_grouped_account_rows_from_odoo_trial_balance',
            autospec=True,
            side_effect=_fake_fetch_grouped_rows,
        ):
            report_data = wizard._get_report_data()

        self.assertEqual(report_data['non_current_assets']['Investing activities'], 75.0)
        self.assertEqual(report_data['non_current_assets']['Non current assets'], 100.0)
        self.assertEqual(report_data['non_current_assets_total'], 175.0)
        self.assertEqual(report_data['non_current_liabilities']['Financing activities'], -90.0)
        self.assertEqual(report_data['non_current_liabilities']['Non current liabilities'], -130.0)
        self.assertEqual(report_data['non_current_liabilities']['Deposit'], -260.0)
        self.assertEqual(report_data['non_current_liabilities_total'], -480.0)

        self.assertEqual(report_data['investing_activity_cashflow'], -25.0)
        self.assertEqual(report_data['non_current_asset_cashflow'], -20.0)
        self.assertEqual(report_data['current_intangible_assets'], -15.0)
        self.assertEqual(report_data['net_cash_generated_from_investing_activities'], -60.0)
        self.assertEqual(report_data['financing_activity_cashflow'], 40.0)
        self.assertEqual(report_data['non_current_liability_cashflow'], 30.0)
        self.assertEqual(report_data['deposit_cashflow'], 60.0)
        self.assertEqual(report_data['net_cash_generated_from_financing_activities'], 130.0)

        for code in ('1110', '1111', '2105', '2106', '2107'):
            self.assertNotIn(code, report_data['note_numbers'])

        html = self._render_report_sections_html(
            wizard,
            ['balance_sheet_page', 'cash_flows'],
            report_data=report_data,
        )

        self.assertIn('<td class="text-left">Investing activities</td>', html)
        self.assertIn('<td class="text-left">Non current assets</td>', html)
        self.assertIn('<td class="text-left">Intangible assets</td>', html)
        self.assertIn('-15.00', html)
        self.assertIn('<td class="text-left">Financing activities</td>', html)
        self.assertIn('<td class="text-left">Non current liabilities</td>', html)
        self.assertIn('<td class="text-left">Deposit</td>', html)

    def test_auditor_report_template_places_other_matter_between_basis_and_emphasis(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            report_type='year',
            date_start=fields.Date.to_date('2024-04-01'),
            date_end=fields.Date.to_date('2024-06-30'),
            show_unaudited_prior_year=True,
            soce_prior_opening_label_date=fields.Date.to_date('2023-04-01'),
        )
        report_data = wizard._get_report_data()
        report_data['show_emphasis_of_matter'] = True
        report_data['emphasis_note_items'] = [{
            'note_ref': 5,
            'matter_text': 'the correction of a prior period error',
        }]
        html = self._render_report_sections_html(
            wizard,
            ['independent_auditor_report'],
            report_data=report_data,
        )

        self.assertIn('Basis for Opinion:', html)
        self.assertIn('Other Matter:', html)
        self.assertIn('Emphasis of Matter:', html)
        self.assertIn(f"<strong>{report_data['other_matter_company_name']}</strong>", html)
        self.assertIn('for the period ended 30 June 2023 were unaudited.', html)
        self.assertLess(html.index('Basis for Opinion:'), html.index('Other Matter:'))
        self.assertLess(html.index('Other Matter:'), html.index('Emphasis of Matter:'))

    def test_rendered_report_includes_wrapping_rule_for_second_signatory_name(self):
        wizard = self._create_wizard(signature_include_1=True)
        report_data = wizard._get_report_data()
        long_second_name = (
            'Very Long Second Signatory Name Intended To Wrap Inside The Signature Placeholder'
        )
        report_data['signature_names'] = ['Director One', long_second_name]
        html = self.controller._render_report_html(
            wizard,
            sections_to_render=['report_of_directors'],
            toc_entries=[],
            report_data=report_data,
            css_content=self.controller._get_cached_css_content(self.controller._css_path()),
        )

        self.assertIn(long_second_name, html)
        self.assertIn('.signature-block p:nth-child(2)', html)
        self.assertIn('overflow-wrap: anywhere;', html)

    def test_rendered_report_includes_balance_sheet_grand_total_non_italic_rule(self):
        wizard = self._create_wizard()
        report_data = wizard._get_report_data()
        html = self.controller._render_report_html(
            wizard,
            sections_to_render=['balance_sheet_page'],
            toc_entries=[],
            report_data=report_data,
            css_content=self.controller._get_cached_css_content(self.controller._css_path()),
        )

        self.assertIn('.balance_sheet_page .statement-table .grand-total-row td:first-child', html)
        self.assertIn('font-style: normal;', html)

    def test_entity_information_adds_spacing_class_for_more_than_four_owners(self):
        html_without_extra_spacing = self._render_entity_information_template(
            'audit_report_template.html',
            ['Owner 1', 'Owner 2', 'Owner 3', 'Owner 4'],
        )
        html_with_extra_spacing = self._render_entity_information_template(
            'audit_report_template.html',
            ['Owner 1', 'Owner 2', 'Owner 3', 'Owner 4', 'Owner 5'],
        )

        self.assertNotIn('entity-owner-row entity-owner-row-spacious', html_without_extra_spacing)
        self.assertIn('entity-owner-row entity-owner-row-spacious', html_with_extra_spacing)
