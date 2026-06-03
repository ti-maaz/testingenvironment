from odoo import Command
from odoo.addons.custom_module_permissions.hooks import post_init_hook
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditExcelExportPermissions(TransactionCase):
    def test_group_and_visibility_bindings(self):
        group = self.env.ref('custom_module_permissions.group_custom_module_audit_excel_export')
        self.assertTrue(group)
        self.assertEqual(
            group.privilege_id.category_id,
            self.env.ref('custom_module_permissions.module_category_custom_module_access'),
        )
        self.assertIn(self.env.ref('base.group_user'), group.implied_ids)

        for xmlid in (
            'audit_excel_export.menu_audit_excel_export',
            'audit_excel_export.action_audit_excel_export_wizard',
        ):
            record = self.env.ref(xmlid)
            self.assertEqual(set(record.group_ids.ids), {group.id})

    def test_post_init_grants_group_to_internal_users(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'bridge_excel_user',
            'login': 'bridge_excel_user',
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        group = self.env.ref('custom_module_permissions.group_custom_module_audit_excel_export')
        self.assertNotIn(group, user.group_ids)
        post_init_hook(self.env)
        user.invalidate_recordset(['group_ids'])
        self.assertIn(group, user.group_ids)
