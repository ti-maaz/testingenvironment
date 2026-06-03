import uuid

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditCompanyInfoPermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_audit_report = cls.env.ref('custom_module_permissions.group_custom_module_audit_report')
        cls.group_editor = cls.env.ref(
            'custom_module_permissions.group_custom_module_audit_company_info_editor'
        )

    @classmethod
    def _make_user(cls, prefix, groups):
        login = f'{prefix}_{uuid.uuid4().hex[:8]}'
        company = cls.env.company
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': f'{login}@example.com',
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set(groups)],
        })

    def test_editor_group_metadata(self):
        self.assertTrue(self.group_editor)
        self.assertIn(self.group_user, self.group_editor.implied_ids)
        self.assertIn(self.group_audit_report, self.group_editor.implied_ids)
        self.assertEqual(
            self.group_editor.privilege_id.category_id,
            self.env.ref('custom_module_permissions.module_category_custom_module_access'),
        )

    def test_internal_user_without_editor_group_cannot_write_company(self):
        user = self._make_user(
            prefix='audit_company_denied',
            groups=[self.group_user.id],
        )
        with self.assertRaises(AccessError):
            self.env.company.with_user(user).write({'street': 'Blocked street'})

    def test_internal_user_with_editor_group_can_write_company(self):
        user = self._make_user(
            prefix='audit_company_allowed',
            groups=[self.group_user.id, self.group_editor.id],
        )

        company = self.env.company
        original_street = company.street
        try:
            company.with_user(user).write({'street': 'Audit Report Company Info Street'})
            self.assertEqual(company.street, 'Audit Report Company Info Street')
        finally:
            company.write({'street': original_street})
