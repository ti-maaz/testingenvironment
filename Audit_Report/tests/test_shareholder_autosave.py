import json

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditReportShareholderAutosave(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _create_wizard(self, **overrides):
        values = {
            'company_id': self.company.id,
            'date_start': fields.Date.to_date('2024-01-01'),
            'date_end': fields.Date.to_date('2024-12-31'),
            'report_type': 'period',
            'audit_period_category': 'normal_1y',
            'signature_date_mode': 'today',
            'use_previous_settings': False,
        }
        values.update(overrides)
        return self.env['audit.report'].create(values)

    def _create_internal_user(self, login):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': f'{login}@example.com',
            'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    def test_previous_settings_are_shared_across_users_for_company(self):
        other_user = self._create_internal_user('audit-settings-shared-user')
        wizard = self._create_wizard(
            portal_account_no='DMCC-SHARED-001',
            share_capital_paid_status='unpaid',
        )
        other_model = self.env['audit.report'].with_user(other_user)
        param = self.env['ir.config_parameter'].sudo()

        param.set_param(wizard._previous_settings_key(), '')
        param.set_param(wizard._legacy_previous_settings_key(), '')
        param.set_param(other_model._legacy_previous_settings_key(), '')

        wizard._store_previous_settings()

        self.assertNotIn('user_', wizard._previous_settings_key())
        previous = other_model._get_previous_settings()
        self.assertEqual(previous.get('portal_account_no'), 'DMCC-SHARED-001')
        self.assertEqual(previous.get('share_capital_paid_status'), 'unpaid')

    def test_previous_settings_can_read_legacy_user_key_until_shared_save(self):
        wizard = self._create_wizard()
        param = self.env['ir.config_parameter'].sudo()

        param.set_param(wizard._previous_settings_key(), '')
        param.set_param(
            wizard._legacy_previous_settings_key(),
            json.dumps({'portal_account_no': 'DMCC-LEGACY-001'}),
        )

        self.assertEqual(
            wizard._get_previous_settings().get('portal_account_no'),
            'DMCC-LEGACY-001',
        )

    def test_onchange_shareholder_preferences_autosaves_previous_settings(self):
        wizard = self._create_wizard(
            share_capital_paid_status='paid',
            signature_include_2=False,
            director_include_2=False,
        )

        wizard.share_capital_paid_status = 'unpaid'
        wizard.signature_include_2 = True
        wizard.director_include_2 = True
        wizard._onchange_autosave_shareholder_preferences()

        previous = wizard._get_previous_settings()
        self.assertEqual(previous.get('share_capital_paid_status'), 'unpaid')
        self.assertTrue(previous.get('signature_include_2'))
        self.assertTrue(previous.get('director_include_2'))

    def test_onchange_shareholder_preferences_syncs_company_share(self):
        wizard = self._create_wizard(share_capital_paid_status='paid')

        wizard.share_capital_paid_status = 'unpaid'
        wizard._onchange_autosave_shareholder_preferences()

        self.company.invalidate_recordset(['company_share'])
        self.assertEqual(self.company.company_share, 'unpaid')
