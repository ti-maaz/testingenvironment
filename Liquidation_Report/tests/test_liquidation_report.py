import xml.etree.ElementTree as ET
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from odoo.tests import TransactionCase, tagged

from odoo.addons.Liquidation_Report.controllers.main import LiquidationReportController


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W_NS}


@tagged('post_install', '-at_install')
class TestLiquidationReport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.controller = LiquidationReportController()
        self.company = self.env['res.company'].create({
            'name': 'Liquidation Sample FZCO',
            'free_zone': 'Dubai Integrated Economic Zones Authority',
            'company_license_number': 'LIC-001',
            'street': 'DSO-IFZA, IFZA Properties, Dubai Silicon Oasis',
            'city': 'Dubai',
            'shareholder_1': 'First Shareholder',
        })
        self.audit_report = self.env['audit.report'].create({
            'company_id': self.company.id,
            'date_start': date(2025, 1, 1),
            'date_end': date(2025, 4, 13),
            'signature_include_1': True,
        })

    def _wizard(self, **vals):
        defaults = {
            'audit_report_id': self.audit_report.id,
        }
        defaults.update(vals)
        return self.env['liquidation.report.wizard'].create(defaults)

    def _document_xml(self, docx_content):
        with ZipFile(BytesIO(docx_content)) as archive:
            return archive.read('word/document.xml').decode('utf-8')

    def _document_text(self, docx_content):
        root = ET.fromstring(self._document_xml(docx_content).encode('utf-8'))
        return ''.join(text_node.text or '' for text_node in root.findall('.//w:t', NS))

    def test_wizard_defaults_from_audit_report_and_company(self):
        wizard = self._wizard()

        self.assertEqual(wizard.company_id, self.company)
        self.assertEqual(wizard.report_type, 'ifza')
        self.assertEqual(wizard.liquidation_date, date(2025, 4, 13))
        self.assertEqual(wizard.company_license_number, 'LIC-001')
        self.assertEqual(wizard.contact_person, 'First Shareholder')

    def test_meydan_defaults_to_ifza_report_type(self):
        meydan_company = self.env['res.company'].create({
            'name': 'Meydan Liquidation FZ',
            'free_zone': 'Meydan Free Zone',
            'company_license_number': 'MEY-001',
        })
        wizard = self.env['liquidation.report.wizard'].with_context(
            default_company_id=meydan_company.id,
        ).create({})

        self.assertEqual(wizard.company_id, meydan_company)
        self.assertEqual(wizard.report_type, 'ifza')

    def test_all_other_freezones_default_to_all_freezones_and_can_be_overridden(self):
        self.company.write({'free_zone': 'Ajman Free Zone'})
        wizard = self._wizard()

        self.assertEqual(wizard.report_type, 'all_freezones')

        wizard.write({'report_type': 'ifza'})
        self.assertEqual(wizard.report_type, 'ifza')

    def test_ifza_docx_replaces_highlighted_placeholders_and_keeps_static_contact_values(self):
        wizard = self._wizard()
        docx_content = self.controller._build_liquidation_docx(wizard)
        document_xml = self._document_xml(docx_content)
        document_text = self._document_text(docx_content)

        self.assertIn('LIQUIDATION SAMPLE FZCO', document_text)
        self.assertIn('License number LIC-001', document_text)
        self.assertIn('13th April 2025', document_text)
        self.assertIn('Name of contact person: First Shareholder', document_text)
        self.assertIn('DSO-IFZA, IFZA Properties, Dubai Silicon Oasis, Dubai', document_text)
        self.assertIn('email@exchange.com', document_text)
        self.assertIn('+971', document_text)
        self.assertNotIn('<w:highlight', document_xml)

    def test_all_freezones_docx_replaces_placeholders_and_keeps_static_ref(self):
        self.company.write({
            'free_zone': 'Ajman Free Zone',
            'street': 'Ajman Free Zone Business Centre',
            'city': 'Ajman',
            'company_license_number': 'AJM-456',
        })
        wizard = self._wizard(
            report_type='all_freezones',
            letter_date=date(2026, 5, 7),
        )
        docx_content = self.controller._build_liquidation_docx(wizard)
        document_xml = self._document_xml(docx_content)
        document_text = self._document_text(docx_content)

        self.assertIn('Date: 7 May 2026', document_text)
        self.assertIn('Ref: V019', document_text)
        self.assertIn('To:  Ajman Free Zone, Ajman, UAE.', document_text)
        self.assertIn('For:  LIQUIDATION SAMPLE FZCO', document_text)
        self.assertIn('Ajman Free Zone Business Centre, Ajman, UAE.', document_text)
        self.assertIn('bearing license No. AJM-456', document_text)
        self.assertNotIn('<w:highlight', document_xml)

    def test_audit_wizard_action_opens_liquidation_wizard(self):
        action = self.audit_report.action_open_liquidation_wizard()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'liquidation.report.wizard')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['default_audit_report_id'], self.audit_report.id)
        self.assertEqual(action['context']['default_company_id'], self.company.id)

    def test_generate_liquidation_menu_moves_under_custom_modules(self):
        generate_menu = self.env.ref('Liquidation_Report.liquidation_report_generate_menu')
        self.env['liquidation.report.wizard']._sync_generate_liquidation_menu_parent()
        generate_menu.invalidate_recordset(['parent_id', 'sequence'])

        self.assertEqual(generate_menu.parent_id, self.env.ref('Audit_Report.menu_custom_modules'))
        self.assertEqual(generate_menu.sequence, 120)

    def test_controller_blocks_companies_not_allowed_for_user(self):
        other_company = self.env['res.company'].create({
            'name': 'Blocked Liquidation Co',
            'free_zone': 'Ajman Free Zone',
            'company_license_number': 'BLK-001',
        })
        blocked_wizard = self.env['liquidation.report.wizard'].with_context(
            default_company_id=other_company.id,
        ).create({
            'company_id': other_company.id,
            'report_type': 'all_freezones',
            'liquidation_date': date(2025, 4, 13),
            'letter_date': date(2026, 5, 7),
        })
        allowed_user = self.env['res.users'].create({
            'name': 'Liquidation Limited User',
            'login': 'liquidation_limited_user',
            'email': 'liquidation_limited_user@example.com',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
        })

        fake_request = SimpleNamespace(
            env=SimpleNamespace(user=allowed_user),
            make_response=lambda body, headers=None, status=200: {
                'body': body,
                'headers': headers or [],
                'status': status,
            },
        )
        with patch('odoo.addons.Liquidation_Report.controllers.main.request', fake_request):
            response = self.controller._generate_liquidation_docx_response(blocked_wizard)

        self.assertEqual(response['status'], 403)
