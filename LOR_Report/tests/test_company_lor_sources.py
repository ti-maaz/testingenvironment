from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.LOR_Report.controllers.main import LorReportController
from odoo.addons.LOR_Report.hooks import post_init_hook
from odoo.addons.LOR_Report.models import res_company as res_company_model
from odoo.addons.LOR_Report.models.res_company import get_default_lor_css_source
from odoo.addons.LOR_Report.models.res_company import get_default_lor_html_source


@tagged('post_install', '-at_install')
class TestCompanyLorSources(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({'name': 'LOR Template Co'})
        self.audit_wizard = self.env['audit.report'].create({
            'company_id': self.company.id,
            'date_start': date(2025, 1, 1),
            'date_end': date(2025, 12, 31),
        })
        self.wizard = self.env['lor.report.wizard'].create({
            'audit_report_id': self.audit_wizard.id,
        })
        self.controller = LorReportController()

    def test_new_company_receives_default_lor_sources(self):
        self.assertFalse(self.company.lor_template_html_source)
        self.assertEqual(
            self.controller._get_lor_template_content_for_company(self.company),
            get_default_lor_html_source(),
        )
        self.assertEqual(self.company.lor_template_css_source, get_default_lor_css_source())

    def test_custom_company_source_is_used_for_lor_rendering(self):
        custom_html = (
            '<html><body>'
            '<p>{{ company_name | upper | e }}</p>'
            '<p>Date: <<DATE>></p>'
            '</body></html>'
        )
        custom_css = 'body { font-family: Arial; }'

        self.company.write({
            'lor_template_html_source': custom_html,
            'lor_template_css_source': custom_css,
        })

        template_text = self.controller._get_lor_template_content_for_company(self.company)
        css_text = self.controller._get_lor_css_content_for_company(self.company)
        placeholder_values = self.controller._build_lor_placeholder_values(self.wizard)
        rendered = self.controller._render_lor_template_content_from_source(
            template_text,
            placeholder_values,
        )

        self.assertEqual(template_text, get_default_lor_html_source())
        self.assertEqual(css_text, custom_css)
        self.assertNotEqual(template_text, custom_html)
        self.assertNotIn('Date: <<DATE>>', rendered)

    def test_wizard_action_uses_standalone_lor_route(self):
        action = self.wizard.action_generate_docx()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], f'/lor_report/docx/{self.wizard.id}')

    def test_audit_wizard_action_opens_standalone_lor_wizard(self):
        action = self.audit_wizard.action_open_lor_wizard()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'lor.report.wizard')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['default_audit_report_id'], self.audit_wizard.id)
        self.assertEqual(action['context']['default_company_id'], self.company.id)

    def test_lor_wizard_defaults_to_latest_audit_report_for_company(self):
        wizard = self.env['lor.report.wizard'].with_context(
            default_company_id=self.company.id,
        ).create({})

        self.assertEqual(wizard.company_id, self.company)
        self.assertEqual(wizard.audit_report_id, self.audit_wizard)
        self.assertEqual(wizard.date_end, date(2025, 12, 31))

    def test_lor_default_get_prefills_signature_flags_from_audit_report(self):
        self.audit_wizard.write({
            'signature_include_2': True,
            'signature_include_4': True,
        })

        defaults = self.env['lor.report.wizard'].with_context(
            default_audit_report_id=self.audit_wizard.id,
            default_company_id=self.company.id,
        ).default_get([
            'company_id',
            'audit_report_id',
            'signature_include_2',
            'signature_include_4',
        ])

        self.assertEqual(defaults.get('company_id'), self.company.id)
        self.assertEqual(defaults.get('audit_report_id'), self.audit_wizard.id)
        self.assertTrue(defaults.get('signature_include_2'))
        self.assertTrue(defaults.get('signature_include_4'))

    def test_lor_wizard_can_open_without_any_audit_report(self):
        company = self.env['res.company'].create({'name': 'Standalone LOR Co'})
        wizard = self.env['lor.report.wizard'].with_context(
            default_company_id=company.id,
        ).create({})

        self.assertEqual(wizard.company_id, company)
        self.assertFalse(wizard.audit_report_id)
        self.assertTrue(wizard.date_end)

        action = wizard.action_generate_docx()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], f'/lor_report/docx/{wizard.id}')

    def test_lor_wizard_reads_company_information_from_audit_wizard(self):
        self.audit_wizard.write({
            'company_city': 'Dubai',
            'company_license_number': 'LIC-001',
            'shareholder_1': 'Jane Signatory',
            'share_capital_paid_status': 'unpaid',
        })

        self.assertEqual(self.wizard.company_city, 'Dubai')
        self.assertEqual(self.wizard.company_license_number, 'LIC-001')
        self.assertEqual(self.wizard.shareholder_1, 'Jane Signatory')
        self.assertEqual(self.wizard.share_capital_paid_status, 'unpaid')

    def test_lor_wizard_edits_sync_back_to_company_and_audit_wizard(self):
        self.wizard.write({
            'company_city': 'Abu Dhabi',
            'company_license_number': 'LIC-009',
            'shareholder_1': 'Updated Shareholder',
            'signature_include_1': True,
            'share_capital_paid_status': 'unpaid',
        })

        self.company.invalidate_recordset(['city', 'company_license_number', 'shareholder_1'])
        self.audit_wizard.invalidate_recordset([
            'company_city',
            'company_license_number',
            'shareholder_1',
            'signature_include_1',
            'share_capital_paid_status',
        ])

        self.assertEqual(self.company.city, 'Abu Dhabi')
        self.assertEqual(self.company.company_license_number, 'LIC-009')
        self.assertEqual(self.company.company_share, 'unpaid')
        self.assertEqual(self.company.shareholder_1, 'Updated Shareholder')
        self.assertEqual(self.audit_wizard.company_city, 'Abu Dhabi')
        self.assertEqual(self.audit_wizard.company_license_number, 'LIC-009')
        self.assertEqual(self.audit_wizard.shareholder_1, 'Updated Shareholder')
        self.assertTrue(self.audit_wizard.signature_include_1)
        self.assertEqual(self.audit_wizard.share_capital_paid_status, 'unpaid')

    def test_lor_onchange_shareholder_info_syncs_immediately(self):
        self.wizard.share_capital_paid_status = 'unpaid'
        self.wizard.signature_include_2 = True
        self.wizard.shareholder_2 = 'Immediate Sync User'
        self.wizard._onchange_instant_sync_shareholder_info()

        self.company.invalidate_recordset(['company_share', 'shareholder_2'])
        self.audit_wizard.invalidate_recordset(['signature_include_2', 'share_capital_paid_status'])

        self.assertEqual(self.company.company_share, 'unpaid')
        self.assertEqual(self.company.shareholder_2, 'Immediate Sync User')
        self.assertTrue(self.audit_wizard.signature_include_2)
        self.assertEqual(self.audit_wizard.share_capital_paid_status, 'unpaid')

    def test_lor_wizard_date_end_can_override_audit_report_end_date(self):
        self.wizard.write({
            'date_end': date(2026, 1, 31),
        })

        self.audit_wizard.invalidate_recordset(['date_end'])

        self.assertEqual(self.wizard.date_end, date(2026, 1, 31))
        self.assertEqual(self.audit_wizard.date_end, date(2025, 12, 31))

    def test_manager_names_follow_requested_joining_rules(self):
        self.audit_wizard.write({
            'shareholder_1': 'Alice',
            'shareholder_2': 'Bob',
            'shareholder_3': 'Charlie',
            'shareholder_4': False,
            'signature_include_1': True,
            'signature_include_2': True,
            'signature_include_3': True,
        })
        self.assertEqual(self.audit_wizard.lor_manager_name_display, 'Alice, Bob and Charlie')
        self.assertEqual(self.wizard.manager_name_display, 'Alice, Bob and Charlie')
        self.assertEqual(
            self.controller._build_lor_placeholder_values(self.wizard)['MANAGER'],
            'Alice, Bob and Charlie',
        )

        self.audit_wizard.write({
            'shareholder_3': False,
            'signature_include_3': False,
        })
        self.assertEqual(self.wizard.manager_name_display, 'Alice and Bob')

        self.audit_wizard.write({
            'shareholder_2': False,
            'signature_include_2': False,
        })
        self.assertEqual(self.wizard.manager_name_display, 'Alice')

    def test_only_signature_rows_are_counted_as_managers(self):
        self.audit_wizard.write({
            'shareholder_1': 'Alice',
            'shareholder_2': 'Bob',
            'shareholder_3': 'Charlie',
            'signature_include_2': True,
        })

        self.assertEqual(self.wizard.manager_name_display, 'Bob')
        self.assertEqual(
            self.controller._build_lor_placeholder_values(self.wizard)['MANAGER'],
            'Bob',
        )

    def test_manager_name_is_blank_when_no_signature_row_is_selected(self):
        self.audit_wizard.write({
            'shareholder_1': 'Alice',
            'shareholder_2': 'Bob',
        })

        self.assertEqual(self.wizard.manager_name_display, '')
        self.assertEqual(
            self.controller._build_lor_placeholder_values(self.wizard)['MANAGER'],
            '',
        )

    def test_lor_wizard_auto_signature_mode_uses_generation_day(self):
        self.audit_wizard.write({
            'signature_date_mode': 'today',
            'signature_manual_date': False,
        })

        with patch.object(fields.Date, 'context_today', return_value=date(2026, 1, 20)):
            wizard = self.env['lor.report.wizard'].create({
                'audit_report_id': self.audit_wizard.id,
            })

            self.assertEqual(wizard.signature_date_mode, 'auto')
            self.assertEqual(
                self.controller._build_lor_placeholder_values(wizard)['DATE'],
                '20/01/2026',
            )

    def test_lor_wizard_manual_signature_mode_follows_audit_report_default(self):
        self.audit_wizard.write({
            'signature_date_mode': 'manual',
            'signature_manual_date': date(2025, 11, 15),
        })

        wizard = self.env['lor.report.wizard'].create({
            'audit_report_id': self.audit_wizard.id,
        })

        self.assertEqual(wizard.signature_date_mode, 'manual')
        self.assertEqual(wizard.signature_manual_date, date(2025, 11, 15))
        self.assertEqual(
            self.controller._build_lor_placeholder_values(wizard)['DATE'],
            '15/11/2025',
        )

    def test_audit_wizard_full_year_range_renders_year_wording(self):
        rendered = self.controller._render_lor_template_content_from_source(
            '<html><body><p>For the {{ period_word | e }} ended {{ end_date | e }}</p></body></html>',
            self.controller._build_lor_placeholder_values(self.wizard),
        )

        self.assertIn('For the year ended 31 December 2025', rendered)

    def test_audit_wizard_short_range_renders_period_wording(self):
        audit_wizard = self.env['audit.report'].create({
            'company_id': self.company.id,
            'date_start': date(2025, 1, 1),
            'date_end': date(2025, 6, 30),
        })
        short_range_wizard = self.env['lor.report.wizard'].create({
            'audit_report_id': audit_wizard.id,
        })

        rendered = self.controller._render_lor_template_content_from_source(
            '<html><body><p>For the {{ period_word | e }} ended {{ end_date | e }}</p></body></html>',
            self.controller._build_lor_placeholder_values(short_range_wizard),
        )

        self.assertIn('For the period ended 30 June 2025', rendered)

    def test_generate_lor_menu_moves_under_custom_modules_when_available(self):
        custom_modules_menu = self.env.ref(
            'Audit_Report.menu_custom_modules',
            raise_if_not_found=False,
        )
        if not custom_modules_menu:
            custom_modules_menu = self.env['ir.ui.menu'].create({
                'name': 'Custom Modules',
            })
            self.env['ir.model.data'].create({
                'module': 'Audit_Report',
                'name': 'menu_custom_modules',
                'model': 'ir.ui.menu',
                'res_id': custom_modules_menu.id,
                'noupdate': True,
            })

        generate_menu = self.env.ref('LOR_Report.lor_report_generate_menu')
        self.env['lor.report.wizard']._sync_generate_lor_menu_parent()
        generate_menu.invalidate_recordset(['parent_id', 'sequence'])

        self.assertEqual(generate_menu.parent_id, custom_modules_menu)
        self.assertEqual(generate_menu.sequence, 110)

    def test_post_init_hook_backfills_blank_company_sources(self):
        company = self.env['res.company'].create({'name': 'Backfill Co'})
        company.write({
            'lor_template_html_source': False,
            'lor_template_css_source': False,
        })

        post_init_hook(self.env)
        company.invalidate_recordset(['lor_template_html_source', 'lor_template_css_source'])

        self.assertFalse(company.lor_template_html_source)
        self.assertEqual(
            self.controller._get_lor_template_content_for_company(company),
            get_default_lor_html_source(),
        )
        self.assertEqual(company.lor_template_css_source, get_default_lor_css_source())

    def test_post_init_hook_updates_companies_using_previous_default_html(self):
        company = self.env['res.company'].create({'name': 'Legacy HTML Co'})
        previous_default_html = 'PREVIOUS_DEFAULT_LOR_HTML'
        company.write({'lor_template_html_source': previous_default_html})

        original_hash = res_company_model._hash_template_source

        def fake_hash(text_value):
            if text_value == previous_default_html:
                return '7fc99ff84931b249bf4a4fc885ee78f77ca1bb47fea105ad37769bcd2ac78ca4'
            return original_hash(text_value)

        with patch.object(res_company_model, '_hash_template_source', side_effect=fake_hash):
            post_init_hook(self.env)

        company.invalidate_recordset(['lor_template_html_source'])
        self.assertFalse(company.lor_template_html_source)
        self.assertEqual(
            self.controller._get_lor_template_content_for_company(company),
            get_default_lor_html_source(),
        )
