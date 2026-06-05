import uuid

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCustomModulePermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_system = cls.env.ref('base.group_system')
        cls.category = cls.env.ref('custom_module_permissions.module_category_custom_module_access')

    @classmethod
    def _make_internal_user(cls, prefix, groups=None):
        login = f'{prefix}_{uuid.uuid4().hex[:8]}'
        company = cls.env.company
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': f'{login}@example.com',
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set((groups or [cls.group_user.id]))],
        })

    def test_category_exists(self):
        self.assertTrue(self.category.exists())

    def test_custom_module_groups_inverse_preserves_non_custom_groups(self):
        user = self._make_internal_user(
            prefix='cmp_inverse',
            groups=[self.group_user.id, self.group_system.id],
        )

        groups_model = self.env['res.groups']
        privilege = self.env['res.groups.privilege'].create({
            'name': 'Core Test Privilege',
            'category_id': self.category.id,
        })
        custom_group_a = groups_model.create({
            'name': 'Core Test Group A',
            'privilege_id': privilege.id,
            'implied_ids': [Command.link(self.group_user.id)],
        })
        custom_group_b = groups_model.create({
            'name': 'Core Test Group B',
            'privilege_id': privilege.id,
            'implied_ids': [Command.link(self.group_user.id)],
        })

        self.assertFalse(user.custom_module_group_ids)
        self.assertIn(self.group_system, user.group_ids)

        user.write({'custom_module_group_ids': [Command.set([custom_group_a.id])]})
        self.assertIn(self.group_system, user.group_ids)
        self.assertEqual(set(user.custom_module_group_ids.ids), {custom_group_a.id})

        user.write({'custom_module_group_ids': [Command.set([custom_group_b.id])]})
        self.assertIn(self.group_system, user.group_ids)
        self.assertEqual(set(user.custom_module_group_ids.ids), {custom_group_b.id})
        self.assertNotIn(custom_group_a, user.custom_module_group_ids)

    def test_new_internal_user_has_no_custom_module_groups_by_default(self):
        user = self._make_internal_user(prefix='cmp_new_default')
        self.assertFalse(user.custom_module_group_ids)

    def test_users_form_has_custom_module_field(self):
        users_view = self.env.ref('custom_module_permissions.view_users_form_custom_module_permissions')
        self.assertIn('custom_module_group_ids', users_view.arch_db)

    def test_custom_modules_parent_menu_has_expected_groups(self):
        menu = self.env.ref('Audit_Report.menu_custom_modules', raise_if_not_found=False)
        if not menu:
            self.skipTest('Audit_Report.menu_custom_modules is not present in this database')
        expected_group_ids = {
            self.env.ref('custom_module_permissions.group_custom_module_audit_report').id,
            self.env.ref('custom_module_permissions.group_custom_module_audit_excel_export').id,
        }
        self.assertEqual(set(menu.group_ids.ids), expected_group_ids)
