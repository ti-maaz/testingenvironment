from odoo import Command
from odoo.addons.custom_module_permissions.hooks import post_init_hook
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditReportPermissions(TransactionCase):
    def test_group_and_visibility_bindings(self):
        group = self.env.ref('custom_module_permissions.group_custom_module_audit_report')
        self.assertTrue(group)
        self.assertEqual(
            group.privilege_id.category_id,
            self.env.ref('custom_module_permissions.module_category_custom_module_access'),
        )
        self.assertIn(self.env.ref('base.group_user'), group.implied_ids)

        for xmlid in (
            'Audit_Report.account_report_menu',
            'Audit_Report.account_report_generate_menu',
            'Audit_Report.audit_report_saved_menu',
            'Audit_Report.audit_report_revision_menu',
            'Audit_Report.audit_report_wizard_action',
            'Audit_Report.audit_report_document_action',
            'Audit_Report.audit_report_revision_action',
        ):
            record = self.env.ref(xmlid)
            self.assertEqual(set(record.group_ids.ids), {group.id})

    def test_post_init_grants_group_to_internal_users(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'bridge_audit_user',
            'login': 'bridge_audit_user',
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        group = self.env.ref('custom_module_permissions.group_custom_module_audit_report')
        self.assertNotIn(group, user.group_ids)
        post_init_hook(self.env)
        user.invalidate_recordset(['group_ids'])
        self.assertIn(group, user.group_ids)
