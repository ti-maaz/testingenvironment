import copy
import json
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.Audit_Report.controllers.main import AuditReportController


class DummyTrialBalanceReport:
    def __init__(self, report_id, normalized_options, lines_by_start_date, line_account_map):
        self.id = report_id
        self._normalized_options = normalized_options
        self._lines_by_start_date = lines_by_start_date
        self._line_account_map = line_account_map

    def get_options(self, previous_options):
        return copy.deepcopy(self._normalized_options)

    def _get_lines(self, options):
        date_from = ((options or {}).get('date') or {}).get('date_from')
        return copy.deepcopy(self._lines_by_start_date.get(date_from, []))

    def _get_res_id_from_line_id(self, line_id, model_name):
        return self._line_account_map.get(line_id)


class EchoTrialBalanceReport:
    def __init__(self, report_id):
        self.id = report_id

    def get_options(self, previous_options):
        options = copy.deepcopy(previous_options or {})
        options.setdefault('date', options.get('date') or {})
        options.setdefault('columns', [])
        options.setdefault('column_groups', {})
        return options


@tagged('post_install', '-at_install')
class TestAuditReportRevisionSnapshot(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.AuditReportModel = type(cls.env['audit.report'])

    def _make_snapshot(self, **overrides):
        snapshot = {
            'company_id': self.company.id,
            'date_start': '2024-01-01',
            'date_end': '2024-12-31',
            'balance_sheet_date_mode': 'end_only',
            'prior_year_mode': 'auto',
            'prior_balance_sheet_date_mode': 'end_only',
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'signature_date_mode': 'today',
            'draft_watermark': False,
        }
        snapshot.update(overrides)
        return json.dumps(snapshot)

    def _create_document_with_revision(self, snapshot_json, html_content='<html><body><p>Base</p></body></html>'):
        document = self.env['audit.report.document'].create({
            'name': 'Snapshot Test Report',
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'source_wizard_json': snapshot_json,
        })
        revision = document.create_revision_from_html(html_content)
        return document, revision

    def _wizard_values(self, **overrides):
        values = {
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'balance_sheet_date_mode': 'end_only',
            'prior_year_mode': 'auto',
            'prior_balance_sheet_date_mode': 'end_only',
            'report_type': 'period',
            'audit_period_category': 'normal_2y',
            'signature_date_mode': 'today',
            'use_previous_settings': False,
        }
        values.update(overrides)
        return values

    def _create_wizard(self, **overrides):
        return self.env['audit.report'].create(self._wizard_values(**overrides))

    def test_reporting_periods_fallbacks_missing_soce_date(self):
        wizard = self._create_wizard(soce_prior_opening_label_date=False)

        periods = wizard._get_reporting_periods()

        self.assertEqual(
            periods['soce_prior_opening_label_date'],
            fields.Date.to_date('2023-01-01'),
        )
        self.assertTrue(wizard.soce_warning_message)
        self.assertIn('fallback', wizard.soce_warning_message.lower())

    def test_reporting_periods_ignore_legacy_balance_sheet_snapshot_modes(self):
        wizard = self._create_wizard(
            audit_period_category='normal_2y',
            date_start=fields.Date.to_date('2024-04-01'),
            date_end=fields.Date.to_date('2024-06-30'),
            balance_sheet_date_mode='range',
            prior_balance_sheet_date_mode='range',
        )

        periods = wizard._get_reporting_periods()

        self.assertEqual(periods['prior_date_start'], fields.Date.to_date('2023-04-01'))
        self.assertEqual(periods['prior_date_end'], fields.Date.to_date('2023-06-30'))
        self.assertEqual(periods['prior_prior_date_start'], fields.Date.to_date('2022-04-01'))
        self.assertFalse(periods['balance_sheet_date_start'])
        self.assertFalse(periods['prior_balance_sheet_date_start'])
        self.assertFalse(periods['prior_prior_balance_sheet_date_start'])

    def test_cashflow_multiline_detail_rows_split_without_affecting_other_tables(self):
        Revision = self.env['audit.report.revision']
        root = Revision._parse_html("""
            <html>
              <body>
                <section class="cash_flows page">
                  <table class="statement-table has-prior">
                    <tbody>
                      <tr class="section-row"><td colspan="4">Cash flows from investing activities</td></tr>
                      <tr>
                        <td class="text-left">Property, plant and equipment<br/>IT equipment</td>
                        <td class="text-center"></td>
                        <td class="text-right">(47,260)<br/>(19,354)</td>
                        <td class="text-right">-</td>
                      </tr>
                      <tr class="total-row cf-investing">
                        <td class="text-left">Net cash (used in) investing activities</td>
                        <td class="text-center"></td>
                        <td class="text-right"><span class="amount-line amount-line-single">(66,620)</span></td>
                        <td class="text-right"><span class="amount-line amount-line-single">-</span></td>
                      </tr>
                    </tbody>
                  </table>
                </section>
                <section class="balance_sheet_page page">
                  <table class="statement-table has-prior">
                    <tbody>
                      <tr>
                        <td class="text-left">Property, plant and equipment<br/>IT equipment</td>
                        <td class="text-center"></td>
                        <td class="text-right">(47,260)<br/>(19,354)</td>
                        <td class="text-right">-</td>
                      </tr>
                    </tbody>
                  </table>
                </section>
              </body>
            </html>
        """)
        root = Revision._normalize_document_root(root)

        Revision._normalize_cashflow_multiline_detail_rows(root)

        cashflow_detail_rows = root.xpath(
            '//section[contains(concat(" ", normalize-space(@class), " "), " cash_flows ")]'
            '//table[contains(concat(" ", normalize-space(@class), " "), " statement-table ")]'
            '/tbody/tr[not(contains(concat(" ", normalize-space(@class), " "), " section-row "))'
            ' and not(contains(concat(" ", normalize-space(@class), " "), " total-row "))]'
        )
        self.assertEqual(len(cashflow_detail_rows), 2)
        self.assertEqual(cashflow_detail_rows[0].xpath('./td')[0].text, 'Property, plant and equipment')
        self.assertEqual(cashflow_detail_rows[0].xpath('./td')[2].text, '(47,260)')
        self.assertEqual(cashflow_detail_rows[0].xpath('./td')[3].text, '-')
        self.assertEqual(cashflow_detail_rows[1].xpath('./td')[0].text, 'IT equipment')
        self.assertEqual(cashflow_detail_rows[1].xpath('./td')[2].text, '(19,354)')
        self.assertEqual(cashflow_detail_rows[1].xpath('./td')[3].text, '')

        balance_rows = root.xpath(
            '//section[contains(concat(" ", normalize-space(@class), " "), " balance_sheet_page ")]'
            '//table[contains(concat(" ", normalize-space(@class), " "), " statement-table ")]/tbody/tr'
        )
        self.assertEqual(len(balance_rows), 1)
        self.assertEqual(len(balance_rows[0].xpath('./td[1]/br')), 1)

    def test_project_account_rows_switches_balance_alias_by_role(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        rows = [{
            'id': 1,
            'code': '999100',
            'initial_balance': 40.0,
            'debit': 27.0,
            'credit': 9.0,
            'end_balance': 58.0,
            'balance': 58.0,
        }]

        opening_rows = wizard._project_account_rows(rows, balance_role='opening')
        period_rows = wizard._project_account_rows(rows, balance_role='movement')
        closing_rows = wizard._project_account_rows(rows, balance_role='closing')

        self.assertEqual(opening_rows[0]['balance'], 40.0)
        self.assertEqual(period_rows[0]['movement_balance'], 18.0)
        self.assertEqual(period_rows[0]['balance'], 18.0)
        self.assertEqual(closing_rows[0]['end_balance'], 58.0)
        self.assertEqual(closing_rows[0]['balance'], 58.0)

    def test_convert_tb_row_to_usd_preserves_balance_role_alias(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        movement_row = wizard._convert_tb_row_to_usd({
            'initial_balance': 100.0,
            'debit': 20.0,
            'credit': 5.0,
            'movement_balance': 15.0,
            'end_balance': 115.0,
            'balance_role': 'movement',
            'balance': 15.0,
        }, 5.0)
        closing_row = wizard._convert_tb_row_to_usd({
            'initial_balance': 100.0,
            'debit': 20.0,
            'credit': 5.0,
            'movement_balance': 15.0,
            'end_balance': 115.0,
            'balance_role': 'closing',
            'balance': 115.0,
        }, 5.0)

        self.assertEqual(movement_row['balance'], 3.0)
        self.assertEqual(movement_row['end_balance'], 23.0)
        self.assertEqual(closing_row['balance'], 23.0)
        self.assertEqual(closing_row['movement_balance'], 3.0)

    def test_extract_native_tb_rows_include_opening_movement_and_closing_amounts(self):
        account = self.env['account.account'].create({
            'code': '999006',
            'name': 'TB Shape Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-02-01'),
            date_end=fields.Date.to_date('2024-02-29'),
        )
        options = {
            'date': {
                'date_from': '2024-02-01',
                'date_to': '2024-02-29',
                'mode': 'range',
                'filter': 'custom',
            },
            'columns': [
                {'column_group_key': 'feb_initial', 'expression_label': 'balance'},
                {'column_group_key': 'feb_debit', 'expression_label': 'debit'},
                {'column_group_key': 'feb_credit', 'expression_label': 'credit'},
                {'column_group_key': 'feb_end', 'expression_label': 'balance'},
            ],
            'column_groups': {
                'feb_initial': {
                    'forced_options': {
                        'trial_balance_column_type': 'initial_balance',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'single',
                            'date_to': '2024-01-31',
                        },
                    },
                },
                'feb_debit': {
                    'forced_options': {
                        'trial_balance_column_type': 'period',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-02-01',
                            'date_to': '2024-02-29',
                        },
                    },
                },
                'feb_credit': {
                    'forced_options': {
                        'trial_balance_column_type': 'period',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-02-01',
                            'date_to': '2024-02-29',
                        },
                    },
                },
                'feb_end': {
                    'forced_options': {
                        'trial_balance_column_type': 'end_balance',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-02-01',
                            'date_to': '2024-02-29',
                        },
                    },
                },
            },
        }
        dummy_report = DummyTrialBalanceReport(
            123,
            options,
            {},
            {'account_line_1': account.id},
        )
        rows = wizard._extract_native_tb_rows_from_odoo_trial_balance_lines(
            dummy_report,
            options,
            [{
                'id': 'account_line_1',
                'columns': [
                    {'column_group_key': 'feb_initial', 'expression_label': 'balance', 'no_format': 40.0},
                    {'column_group_key': 'feb_debit', 'expression_label': 'debit', 'no_format': 27.0},
                    {'column_group_key': 'feb_credit', 'expression_label': 'credit', 'no_format': 9.0},
                    {'column_group_key': 'feb_end', 'expression_label': 'balance', 'no_format': 58.0},
                ],
            }],
        )

        self.assertEqual(rows[0]['initial_balance'], 40.0)
        self.assertEqual(rows[0]['movement_balance'], 18.0)
        self.assertEqual(rows[0]['end_balance'], 58.0)
        self.assertEqual(rows[0]['balance'], 58.0)
        self.assertEqual(rows[0]['balance_role'], 'closing')

    def test_round_account_rows_for_reporting_rounds_each_account_before_aggregation(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')
        raw_rows = [
            {
                'id': 1,
                'code': '12040101',
                'initial_balance': 0.0,
                'debit': 10.5,
                'credit': 0.0,
                'movement_balance': 10.5,
                'end_balance': 10.5,
                'balance_role': 'closing',
                'balance': 10.5,
            },
            {
                'id': 2,
                'code': '12040102',
                'initial_balance': 0.0,
                'debit': 10.5,
                'credit': 0.0,
                'movement_balance': 10.5,
                'end_balance': 10.5,
                'balance_role': 'closing',
                'balance': 10.5,
            },
        ]

        raw_total = sum(
            row['balance']
            for row in wizard._project_account_rows(raw_rows, balance_role='closing')
        )
        rounded_rows = wizard._round_account_rows_for_reporting(raw_rows)
        rounded_total = sum(row['balance'] for row in rounded_rows)

        self.assertEqual(raw_total, 21.0)
        self.assertEqual(rounded_rows[0]['balance'], 11.0)
        self.assertEqual(rounded_rows[1]['balance'], 11.0)
        self.assertEqual(rounded_total, 22.0)

    def test_is_display_non_zero_uses_half_up_rounding_rule(self):
        wizard = self._create_wizard(audit_period_category='normal_1y')

        self.assertFalse(wizard._is_display_non_zero(0.49, precision=0))
        self.assertTrue(wizard._is_display_non_zero(0.5, precision=0))
        self.assertTrue(wizard._is_display_non_zero(-0.5, precision=0))

    def test_revision_wizard_uses_revision_snapshot_over_document_snapshot(self):
        initial_snapshot = self._make_snapshot(draft_watermark=False, signature_date_mode='today')
        updated_snapshot = self._make_snapshot(
            draft_watermark=True,
            signature_date_mode='manual',
            signature_manual_date='2024-12-31',
        )
        document, first_revision = self._create_document_with_revision(initial_snapshot)
        second_revision = document.create_revision_from_html(
            '<html><body><p>Second</p></body></html>',
            parent_revision=first_revision,
            wizard_snapshot_json=updated_snapshot,
        )

        with patch.object(self.AuditReportModel, '_load_tb_override_lines', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_apply_tb_overrides_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: ''), \
                patch.object(self.AuditReportModel, '_apply_lor_extra_items_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            wizard = second_revision._build_audit_report_wizard_from_snapshot()

        self.assertEqual(document.source_wizard_json, initial_snapshot)
        self.assertEqual(first_revision.wizard_snapshot_json, initial_snapshot)
        self.assertEqual(second_revision.wizard_snapshot_json, updated_snapshot)
        self.assertTrue(wizard.draft_watermark)
        self.assertEqual(wizard.signature_date_mode, 'manual')
        self.assertEqual(wizard.signature_manual_date, fields.Date.to_date('2024-12-31'))

    def test_revision_wizard_restores_correction_error_snapshot_payload(self):
        snapshot = self._make_snapshot(
            audit_period_category='normal_2y',
            emphasis_correction_error=True,
            correction_error_note_body='Paragraph one\nParagraph two',
            correction_error_rows=[
                {
                    'sequence': 10,
                    'row_type': 'section',
                    'description': 'Effect on statement of financial position',
                },
                {
                    'sequence': 20,
                    'row_type': 'line',
                    'description': 'Cash and bank balance',
                    'amount_as_reported': 354163.0,
                    'amount_as_restated': 765463.0,
                    'amount_restatement': 411300.0,
                },
            ],
        )
        document, revision = self._create_document_with_revision(snapshot)

        with patch.object(self.AuditReportModel, '_load_tb_override_lines', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_apply_tb_overrides_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: ''), \
                patch.object(self.AuditReportModel, '_apply_lor_extra_items_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            wizard = revision._build_audit_report_wizard_from_snapshot()

        self.assertEqual(document.source_wizard_json, snapshot)
        self.assertTrue(wizard.emphasis_correction_error)
        self.assertEqual(wizard.correction_error_note_body, 'Paragraph one\nParagraph two')
        self.assertEqual(len(wizard.correction_error_line_ids), 2)
        self.assertEqual(wizard.correction_error_line_ids[0].row_type, 'section')
        self.assertEqual(wizard.correction_error_line_ids[1].amount_as_restated, 765463.0)

    def test_revision_wizard_restores_unaudited_prior_year_flag(self):
        snapshot = self._make_snapshot(
            audit_period_category='normal_2y',
            show_unaudited_prior_year=True,
        )
        document, revision = self._create_document_with_revision(snapshot)

        with patch.object(self.AuditReportModel, '_load_tb_override_lines', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_apply_tb_overrides_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: ''), \
                patch.object(self.AuditReportModel, '_apply_lor_extra_items_from_serialized_payload', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            wizard = revision._build_audit_report_wizard_from_snapshot()

        self.assertEqual(document.source_wizard_json, snapshot)
        self.assertTrue(wizard.show_unaudited_prior_year)

    def test_revision_apply_rerenders_revision_and_persists_snapshot(self):
        initial_snapshot = self._make_snapshot(draft_watermark=False, signature_date_mode='today')
        document, revision = self._create_document_with_revision(initial_snapshot)
        wizard = self.env['audit.report'].with_context(audit_target_revision_id=revision.id).create(
            self._wizard_values(
                audit_period_category='normal_1y',
                signature_date_mode='manual',
                signature_manual_date=fields.Date.to_date('2024-12-31'),
                draft_watermark=True,
                audit_target_revision_id=revision.id,
                audit_target_document_id=document.id,
            )
        )

        rendered_html = '<html><body><p>Updated company details</p></body></html>'
        with patch.object(self.AuditReportModel, '_validate_emphasis_options', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: '{"rows": []}'), \
                patch.object(self.AuditReportModel, '_sync_lor_extra_items_json', lambda *args, **kwargs: '[{"item_text": "Updated"}]'), \
                patch.object(AuditReportController, '_templates_path', lambda *args, **kwargs: '/tmp'), \
                patch.object(AuditReportController, '_css_path', lambda *args, **kwargs: '/tmp/audit.css'), \
                patch.object(AuditReportController, '_get_template_env', lambda *args, **kwargs: object()), \
                patch.object(AuditReportController, '_get_cached_css_content', lambda *args, **kwargs: 'body{}'), \
                patch.object(AuditReportController, '_compute_toc_entries', lambda *args, **kwargs: None), \
                patch.object(AuditReportController, '_render_report_html', lambda *args, **kwargs: rendered_html):
            expected_snapshot = wizard._get_wizard_snapshot_json()
            action = wizard.action_apply_revision_changes_to_revision()

        new_revision = self.env['audit.report.revision'].browse(action['res_id'])
        self.assertNotEqual(new_revision.id, revision.id)
        self.assertEqual(new_revision.parent_revision_id, revision)
        self.assertIn('Updated company details', new_revision.html_content)
        self.assertEqual(new_revision.wizard_snapshot_json, expected_snapshot)

    def test_revision_apply_updates_child_revision_in_place(self):
        initial_snapshot = self._make_snapshot(draft_watermark=False, signature_date_mode='today')
        document, base_revision = self._create_document_with_revision(initial_snapshot)
        working_revision = document.create_revision_from_html(
            '<html><body><p>Working copy</p></body></html>',
            parent_revision=base_revision,
            tb_overrides_json='{"rows": ["old"]}',
            wizard_snapshot_json=initial_snapshot,
        )
        wizard = self.env['audit.report'].with_context(audit_target_revision_id=working_revision.id).create(
            self._wizard_values(
                audit_period_category='normal_1y',
                signature_date_mode='manual',
                signature_manual_date=fields.Date.to_date('2024-12-31'),
                draft_watermark=True,
                audit_target_revision_id=working_revision.id,
                audit_target_document_id=document.id,
            )
        )

        rendered_html = '<html><body><p>Working copy updated</p></body></html>'
        override_payload = '{"rows": ["updated"]}'
        lor_payload = '[{"item_text": "Updated"}]'
        with patch.object(self.AuditReportModel, '_validate_emphasis_options', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: override_payload), \
                patch.object(self.AuditReportModel, '_sync_lor_extra_items_json', lambda *args, **kwargs: lor_payload), \
                patch.object(AuditReportController, '_templates_path', lambda *args, **kwargs: '/tmp'), \
                patch.object(AuditReportController, '_css_path', lambda *args, **kwargs: '/tmp/audit.css'), \
                patch.object(AuditReportController, '_get_template_env', lambda *args, **kwargs: object()), \
                patch.object(AuditReportController, '_get_cached_css_content', lambda *args, **kwargs: 'body{}'), \
                patch.object(AuditReportController, '_compute_toc_entries', lambda *args, **kwargs: None), \
                patch.object(AuditReportController, '_render_report_html', lambda *args, **kwargs: rendered_html):
            expected_snapshot = wizard._get_wizard_snapshot_json()
            action = wizard.action_apply_revision_changes_to_revision()

        working_revision.invalidate_recordset()
        document.invalidate_recordset()
        self.assertEqual(action['res_id'], working_revision.id)
        self.assertIn('Working copy updated', working_revision.html_content)
        self.assertEqual(working_revision.tb_overrides_json, override_payload)
        self.assertEqual(working_revision.lor_extra_items_json, lor_payload)
        self.assertEqual(working_revision.wizard_snapshot_json, expected_snapshot)
        self.assertEqual(document.current_revision_id, working_revision)
        self.assertEqual(document.tb_overrides_json, override_payload)
        self.assertEqual(document.source_wizard_json, expected_snapshot)

    def test_revision_apply_as_new_revision_creates_checkpoint_from_child(self):
        initial_snapshot = self._make_snapshot(draft_watermark=False, signature_date_mode='today')
        document, base_revision = self._create_document_with_revision(initial_snapshot)
        working_revision = document.create_revision_from_html(
            '<html><body><p>Working copy</p></body></html>',
            parent_revision=base_revision,
            tb_overrides_json='{"rows": ["old"]}',
            wizard_snapshot_json=initial_snapshot,
        )
        wizard = self.env['audit.report'].with_context(audit_target_revision_id=working_revision.id).create(
            self._wizard_values(
                audit_period_category='normal_1y',
                draft_watermark=True,
                audit_target_revision_id=working_revision.id,
                audit_target_document_id=document.id,
            )
        )

        rendered_html = '<html><body><p>Checkpoint copy</p></body></html>'
        override_payload = '{"rows": ["checkpoint"]}'
        with patch.object(self.AuditReportModel, '_validate_emphasis_options', lambda *args, **kwargs: None), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}), \
                patch.object(self.AuditReportModel, '_sync_tb_overrides_json', lambda *args, **kwargs: override_payload), \
                patch.object(self.AuditReportModel, '_sync_lor_extra_items_json', lambda *args, **kwargs: ''), \
                patch.object(AuditReportController, '_templates_path', lambda *args, **kwargs: '/tmp'), \
                patch.object(AuditReportController, '_css_path', lambda *args, **kwargs: '/tmp/audit.css'), \
                patch.object(AuditReportController, '_get_template_env', lambda *args, **kwargs: object()), \
                patch.object(AuditReportController, '_get_cached_css_content', lambda *args, **kwargs: 'body{}'), \
                patch.object(AuditReportController, '_compute_toc_entries', lambda *args, **kwargs: None), \
                patch.object(AuditReportController, '_render_report_html', lambda *args, **kwargs: rendered_html):
            action = wizard.action_apply_revision_changes_as_new_revision()

        new_revision = self.env['audit.report.revision'].browse(action['res_id'])
        self.assertNotEqual(new_revision.id, working_revision.id)
        self.assertEqual(new_revision.parent_revision_id, working_revision)
        self.assertIn('Checkpoint copy', new_revision.html_content)
        self.assertEqual(new_revision.tb_overrides_json, override_payload)
        self.assertEqual(document.current_revision_id, new_revision)

    def test_revision_wizard_restores_payload_only_tb_override_rows(self):
        snapshot = self._make_snapshot()
        account = self.env['account.account'].create({
            'code': '999003',
            'name': 'Revision Payload Account',
            'account_type': 'expense',
        })
        override_payload = json.dumps([{
            'period_key': 'current',
            'account_id': account.id,
            'account_code': account.code,
            'account_name': account.name,
            'system_initial_balance': 0.0,
            'system_debit': 0.0,
            'system_credit': 0.0,
            'system_balance': 0.0,
            'override_initial_balance': 0.0,
            'override_debit': 250.0,
            'override_credit': 10.0,
            'override_balance': 240.0,
        }])
        document = self.env['audit.report.document'].create({
            'name': 'Snapshot Test Report',
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'source_wizard_json': snapshot,
        })
        revision = document.create_revision_from_html(
            '<html><body><p>Base</p></body></html>',
            tb_overrides_json=override_payload,
        )

        with patch.object(self.AuditReportModel, '_get_tb_override_system_rows', lambda *args, **kwargs: []), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            wizard = revision._build_audit_report_wizard_from_snapshot()

        self.assertEqual(len(wizard.tb_override_current_line_ids), 1)
        line = wizard.tb_override_current_line_ids
        self.assertEqual(line.account_id, account)
        self.assertEqual(line.account_code, '999003')
        self.assertEqual(line.override_debit, 250.0)
        self.assertEqual(line.override_credit, 10.0)
        self.assertEqual(line.override_balance, 240.0)

    def test_tb_import_normalizes_stale_client_options_before_extracting_rows(self):
        account = self.env['account.account'].create({
            'code': '999001',
            'name': 'TB Import Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-01-01'),
            date_end=fields.Date.to_date('2024-01-31'),
        )

        raw_options = {
            'date': {
                'date_from': '2024-02-01',
                'date_to': '2024-02-29',
                'mode': 'range',
                'filter': 'custom',
            },
            'columns': [
                {'column_group_key': 'jan_initial', 'expression_label': 'balance'},
                {'column_group_key': 'jan_debit', 'expression_label': 'debit'},
                {'column_group_key': 'jan_credit', 'expression_label': 'credit'},
                {'column_group_key': 'jan_end', 'expression_label': 'balance'},
            ],
            'column_groups': {
                'jan_initial': {
                    'forced_options': {
                        'trial_balance_column_type': 'initial_balance',
                        'trial_balance_column_block_id': '0',
                        'date': {
                            'mode': 'single',
                            'date_to': '2023-12-31',
                        },
                    },
                },
                'jan_debit': {
                    'forced_options': {
                        'trial_balance_column_type': 'period',
                        'trial_balance_column_block_id': '0',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-01-01',
                            'date_to': '2024-01-31',
                        },
                    },
                },
                'jan_credit': {
                    'forced_options': {
                        'trial_balance_column_type': 'period',
                        'trial_balance_column_block_id': '0',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-01-01',
                            'date_to': '2024-01-31',
                        },
                    },
                },
                'jan_end': {
                    'forced_options': {
                        'trial_balance_column_type': 'end_balance',
                        'trial_balance_column_block_id': '0',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-01-01',
                            'date_to': '2024-01-31',
                        },
                    },
                },
            },
        }
        normalized_options = {
            'date': {
                'date_from': '2024-02-01',
                'date_to': '2024-02-29',
                'mode': 'range',
                'filter': 'custom',
            },
            'columns': [
                {'column_group_key': 'feb_initial', 'expression_label': 'balance'},
                {'column_group_key': 'feb_debit', 'expression_label': 'debit'},
                {'column_group_key': 'feb_credit', 'expression_label': 'credit'},
                {'column_group_key': 'feb_end', 'expression_label': 'balance'},
            ],
            'column_groups': {
                'feb_initial': {
                    'forced_options': {
                        'trial_balance_column_type': 'initial_balance',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'single',
                            'date_to': '2024-01-31',
                        },
                    },
                },
                'feb_debit': {
                    'forced_options': {
                        'trial_balance_column_type': 'period',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-02-01',
                            'date_to': '2024-02-29',
                        },
                    },
                },
                'feb_credit': {
                    'forced_options': {
                        'trial_balance_column_type': 'period',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-02-01',
                            'date_to': '2024-02-29',
                        },
                    },
                },
                'feb_end': {
                    'forced_options': {
                        'trial_balance_column_type': 'end_balance',
                        'trial_balance_column_block_id': '1',
                        'date': {
                            'mode': 'range',
                            'date_from': '2024-02-01',
                            'date_to': '2024-02-29',
                        },
                    },
                },
            },
        }
        dummy_report = DummyTrialBalanceReport(
            987654,
            normalized_options,
            {
                '2024-01-01': [{
                    'id': 'account_line_1',
                    'columns': [
                        {'column_group_key': 'jan_initial', 'expression_label': 'balance', 'no_format': 14.0},
                        {'column_group_key': 'jan_debit', 'expression_label': 'debit', 'no_format': 11.0},
                        {'column_group_key': 'jan_credit', 'expression_label': 'credit', 'no_format': 3.0},
                        {'column_group_key': 'jan_end', 'expression_label': 'balance', 'no_format': 22.0},
                    ],
                }],
                '2024-02-01': [{
                    'id': 'account_line_1',
                    'columns': [
                        {'column_group_key': 'feb_initial', 'expression_label': 'balance', 'no_format': 40.0},
                        {'column_group_key': 'feb_debit', 'expression_label': 'debit', 'no_format': 27.0},
                        {'column_group_key': 'feb_credit', 'expression_label': 'credit', 'no_format': 9.0},
                        {'column_group_key': 'feb_end', 'expression_label': 'balance', 'no_format': 58.0},
                    ],
                }],
            },
            {'account_line_1': account.id},
        )

        with patch.object(self.AuditReportModel, '_get_odoo_trial_balance_report', lambda *args, **kwargs: dummy_report), \
                patch.object(self.AuditReportModel, '_get_report_data', lambda *args, **kwargs: {}):
            result = wizard._apply_tb_override_import_from_options(raw_options, period_key='current')

        self.assertEqual(result['date_start'], '2024-02-01')
        self.assertEqual(result['date_end'], '2024-02-29')
        self.assertEqual(wizard.date_start, fields.Date.to_date('2024-02-01'))
        self.assertEqual(wizard.date_end, fields.Date.to_date('2024-02-29'))
        self.assertEqual(len(wizard.tb_override_current_line_ids), 1)

        line = wizard.tb_override_current_line_ids
        self.assertEqual(line.account_id, account)
        self.assertEqual(line.system_initial_balance, 40.0)
        self.assertEqual(line.system_debit, 27.0)
        self.assertEqual(line.system_credit, 9.0)
        self.assertEqual(line.system_balance, 58.0)

        stored_options = json.loads(wizard.tb_current_report_options_json)
        self.assertEqual(stored_options['date']['date_from'], '2024-02-01')
        self.assertIn('feb_debit', stored_options['column_groups'])

    def test_tb_override_delta_updates_cumulative_balances_using_end_balance_delta(self):
        account = self.env['account.account'].create({
            'code': '999002',
            'name': 'TB Delta Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-02-01'),
            date_end=fields.Date.to_date('2024-02-29'),
        )
        self.env['audit.report.tb.override.line'].create({
            'wizard_id': wizard.id,
            'period_key': 'current',
            'account_id': account.id,
            'account_code': '999002',
            'account_name': 'TB Delta Account',
            'system_initial_balance': 100.0,
            'system_debit': 20.0,
            'system_credit': 5.0,
            'system_balance': 115.0,
            'override_initial_balance': 130.0,
            'override_debit': 20.0,
            'override_credit': 5.0,
            'override_balance': 145.0,
        })

        override_map = wizard._build_tb_override_maps()['current']
        period_rows = wizard._apply_tb_overrides_to_rows([{
            'id': account.id,
            'code': '999002',
            'debit': 20.0,
            'credit': 5.0,
            'balance': 15.0,
        }], override_map, apply_mode='replace')
        cumulative_rows = wizard._apply_tb_overrides_to_rows([{
            'id': account.id,
            'code': '999002',
            'debit': 500.0,
            'credit': 400.0,
            'balance': 100.0,
        }], override_map, apply_mode='delta')

        self.assertEqual(period_rows[0]['initial_balance'], 130.0)
        self.assertEqual(period_rows[0]['debit'], 20.0)
        self.assertEqual(period_rows[0]['credit'], 5.0)
        self.assertEqual(period_rows[0]['balance'], 15.0)
        self.assertEqual(period_rows[0]['end_balance'], 145.0)
        self.assertEqual(cumulative_rows[0]['debit'], 500.0)
        self.assertEqual(cumulative_rows[0]['credit'], 400.0)
        self.assertEqual(cumulative_rows[0]['balance'], 130.0)

    def test_tb_override_line_write_ignores_stale_balance_payload_on_debit_edit(self):
        account = self.env['account.account'].create({
            'code': '999003',
            'name': 'TB Inline Edit Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-02-01'),
            date_end=fields.Date.to_date('2024-02-29'),
        )
        line = self.env['audit.report.tb.override.line'].create({
            'wizard_id': wizard.id,
            'period_key': 'current',
            'account_id': account.id,
            'account_code': '999003',
            'account_name': 'TB Inline Edit Account',
            'system_initial_balance': 0.0,
            'system_debit': 10.0,
            'system_credit': 0.0,
            'system_balance': 10.0,
            'override_initial_balance': 0.0,
            'override_debit': 10.0,
            'override_credit': 0.0,
            'override_balance': 10.0,
        })

        # Editable list payloads can include the stale end balance even when debit was the only real edit.
        line.write({
            'override_debit': 11.0,
            'override_balance': 10.0,
        })

        self.assertEqual(line.override_initial_balance, 0.0)
        self.assertEqual(line.override_debit, 11.0)
        self.assertEqual(line.override_credit, 0.0)
        self.assertEqual(line.override_balance, 11.0)

    def test_tb_override_line_write_backsolves_credit_for_direct_balance_edit(self):
        account = self.env['account.account'].create({
            'code': '999004',
            'name': 'TB Balance Edit Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-02-01'),
            date_end=fields.Date.to_date('2024-02-29'),
        )
        line = self.env['audit.report.tb.override.line'].create({
            'wizard_id': wizard.id,
            'period_key': 'current',
            'account_id': account.id,
            'account_code': '999004',
            'account_name': 'TB Balance Edit Account',
            'system_initial_balance': 100.0,
            'system_debit': 20.0,
            'system_credit': 5.0,
            'system_balance': 115.0,
            'override_initial_balance': 100.0,
            'override_debit': 20.0,
            'override_credit': 5.0,
            'override_balance': 115.0,
        })

        line.write({
            'override_balance': 100.0,
        })

        self.assertEqual(line.override_initial_balance, 100.0)
        self.assertEqual(line.override_debit, 20.0)
        self.assertEqual(line.override_credit, 20.0)
        self.assertEqual(line.override_balance, 100.0)

    def test_tb_override_line_write_rounds_direct_balance_edit_to_whole_number(self):
        account = self.env['account.account'].create({
            'code': '999044',
            'name': 'TB Rounded Balance Edit Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-02-01'),
            date_end=fields.Date.to_date('2024-02-29'),
        )
        line = self.env['audit.report.tb.override.line'].create({
            'wizard_id': wizard.id,
            'period_key': 'current',
            'account_id': account.id,
            'account_code': '999044',
            'account_name': 'TB Rounded Balance Edit Account',
            'system_initial_balance': 100.0,
            'system_debit': 20.0,
            'system_credit': 5.0,
            'system_balance': 115.0,
            'override_initial_balance': 100.0,
            'override_debit': 20.0,
            'override_credit': 5.0,
            'override_balance': 115.0,
        })

        line.write({
            'override_balance': 100.6,
        })

        self.assertEqual(line.override_initial_balance, 100.0)
        self.assertEqual(line.override_debit, 20.0)
        self.assertEqual(line.override_credit, 19.0)
        self.assertEqual(line.override_balance, 101.0)
        self.assertEqual(line.effective_balance, 101.0)

    def test_tb_override_rows_round_end_balances_before_apply(self):
        account = self.env['account.account'].create({
            'code': '999005',
            'name': 'TB Decimal Account',
            'account_type': 'expense',
        })
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-02-01'),
            date_end=fields.Date.to_date('2024-02-29'),
        )
        line = self.env['audit.report.tb.override.line'].create({
            'wizard_id': wizard.id,
            'period_key': 'current',
            'account_id': account.id,
            'account_code': '999005',
            'account_name': 'TB Decimal Account',
            'system_initial_balance': 100.25,
            'system_debit': 20.10,
            'system_credit': 5.05,
            'system_balance': 115.30,
            'override_initial_balance': 130.25,
            'override_debit': 20.10,
            'override_credit': 5.05,
            'override_balance': 145.30,
        })

        self.assertEqual(line.system_balance, 115.0)
        self.assertEqual(line.override_balance, 145.0)
        self.assertEqual(line.effective_balance, 145.0)

        override_map = wizard._build_tb_override_maps()['current']
        period_rows = wizard._apply_tb_overrides_to_rows([{
            'id': account.id,
            'code': '999005',
            'debit': 20.10,
            'credit': 5.05,
            'balance': 15.05,
        }], override_map, apply_mode='replace')

        self.assertEqual(period_rows[0]['initial_balance'], 130.25)
        self.assertEqual(period_rows[0]['debit'], 20.10)
        self.assertEqual(period_rows[0]['credit'], 5.05)
        self.assertEqual(period_rows[0]['balance'], 15.05)
        self.assertEqual(period_rows[0]['end_balance'], 145.0)

    def test_tb_browser_config_rebuilds_stale_saved_options_for_current_period(self):
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-03-01'),
            date_end=fields.Date.to_date('2024-03-31'),
            tb_current_report_options_json=json.dumps({
                'date': {
                    'date_from': '2024-02-01',
                    'date_to': '2024-02-29',
                    'mode': 'range',
                    'filter': 'custom',
                },
            }),
        )

        with patch.object(self.AuditReportModel, '_get_odoo_trial_balance_report', lambda *args, **kwargs: EchoTrialBalanceReport(12345)):
            config = wizard.get_tb_browser_config('current')

        self.assertEqual(config['options']['date']['date_from'], '2024-03-01')
        self.assertEqual(config['options']['date']['date_to'], '2024-03-31')
        self.assertEqual(config['options']['audit_tb_browser_anchor']['date_from'], '2024-03-01')
        self.assertEqual(config['options']['audit_tb_browser_anchor']['date_to'], '2024-03-31')

    def test_tb_browser_config_preserves_custom_tb_date_when_anchor_matches_wizard_period(self):
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-01-01'),
            date_end=fields.Date.to_date('2024-01-31'),
        )
        candidate_options = {
            'date': {
                'date_from': '2024-02-01',
                'date_to': '2024-02-29',
                'mode': 'range',
                'filter': 'custom',
            },
            'audit_tb_browser_anchor': {
                'period_key': 'current',
                'date_from': '2024-01-01',
                'date_to': '2024-01-31',
            },
        }
        wizard_state = {
            'audit_period_category': 'normal_1y',
            'date_start': '2024-01-01',
            'date_end': '2024-01-31',
            'prior_year_mode': 'auto',
            'prior_date_start': False,
            'prior_date_end': False,
        }

        with patch.object(self.AuditReportModel, '_get_odoo_trial_balance_report', lambda *args, **kwargs: EchoTrialBalanceReport(12345)):
            config = wizard.get_tb_browser_config('current', candidate_options, wizard_state)

        self.assertEqual(config['options']['date']['date_from'], '2024-02-01')
        self.assertEqual(config['options']['date']['date_to'], '2024-02-29')
        self.assertEqual(config['options']['audit_tb_browser_anchor']['date_from'], '2024-01-01')
        self.assertEqual(config['options']['audit_tb_browser_anchor']['date_to'], '2024-01-31')

    def test_tb_browser_config_rejects_cached_options_after_wizard_date_change(self):
        wizard = self._create_wizard(
            audit_period_category='normal_1y',
            date_start=fields.Date.to_date('2024-01-01'),
            date_end=fields.Date.to_date('2024-01-31'),
        )
        candidate_options = {
            'date': {
                'date_from': '2024-02-01',
                'date_to': '2024-02-29',
                'mode': 'range',
                'filter': 'custom',
            },
            'audit_tb_browser_anchor': {
                'period_key': 'current',
                'date_from': '2024-01-01',
                'date_to': '2024-01-31',
            },
        }
        wizard_state = {
            'audit_period_category': 'normal_1y',
            'date_start': '2024-03-01',
            'date_end': '2024-03-31',
            'prior_year_mode': 'auto',
            'prior_date_start': False,
            'prior_date_end': False,
        }

        with patch.object(self.AuditReportModel, '_get_odoo_trial_balance_report', lambda *args, **kwargs: EchoTrialBalanceReport(12345)):
            config = wizard.get_tb_browser_config('current', candidate_options, wizard_state)

        self.assertEqual(config['options']['date']['date_from'], '2024-03-01')
        self.assertEqual(config['options']['date']['date_to'], '2024-03-31')
        self.assertEqual(config['options']['audit_tb_browser_anchor']['date_from'], '2024-03-01')
        self.assertEqual(config['options']['audit_tb_browser_anchor']['date_to'], '2024-03-31')

    def test_tb_browser_preview_config_supports_unsaved_wizard_state(self):
        wizard_state = {
            'audit_period_category': 'normal_1y',
            'date_start': '2024-04-01',
            'date_end': '2024-04-30',
            'prior_year_mode': 'auto',
            'prior_date_start': False,
            'prior_date_end': False,
        }

        with patch.object(self.AuditReportModel, '_get_odoo_trial_balance_report', lambda *args, **kwargs: EchoTrialBalanceReport(12345)):
            config = self.env['audit.report'].get_tb_browser_preview_config(
                self.company.id,
                'current',
                False,
                wizard_state,
            )

        self.assertEqual(config['options']['date']['date_from'], '2024-04-01')
        self.assertEqual(config['options']['date']['date_to'], '2024-04-30')
        self.assertFalse(config['context']['audit_tb_override_wizard_id'])
