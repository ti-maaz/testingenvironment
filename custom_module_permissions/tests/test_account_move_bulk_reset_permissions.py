import uuid

from odoo import Command
from odoo.addons.custom_module_permissions.hooks import post_init_hook
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountMoveBulkResetPermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_manager = cls.env.ref('account.group_account_manager')
        cls.group_bulk_reset = cls.env.ref(
            'custom_module_permissions.group_custom_module_account_move_bulk_reset_to_draft'
        )
        cls.category = cls.env.ref('custom_module_permissions.module_category_custom_module_access')

    @classmethod
    def _make_internal_user(cls, prefix, groups):
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

    def test_group_and_visibility_bindings(self):
        self.assertTrue(self.group_bulk_reset)
        self.assertEqual(self.group_bulk_reset.privilege_id.category_id, self.category)
        self.assertIn(self.group_user, self.group_bulk_reset.implied_ids)

        for xmlid in (
            'account_move_bulk_reset_to_draft.action_bulk_reset_to_draft_account_move',
            'account_move_bulk_reset_to_draft.action_bulk_reset_to_draft_and_delete_account_move',
        ):
            record = self.env.ref(xmlid)
            self.assertEqual(set(record.group_ids.ids), {self.group_bulk_reset.id})

    def test_post_init_does_not_auto_grant_bulk_reset_group(self):
        user = self._make_internal_user(
            prefix='cmp_bulk_reset_default',
            groups=[self.group_user.id],
        )

        post_init_hook(self.env)
        user.invalidate_recordset(['group_ids'])

        self.assertNotIn(self.group_bulk_reset, user.group_ids)

    def test_bulk_reset_requires_both_account_manager_and_custom_permission(self):
        manager_only_user = self._make_internal_user(
            prefix='cmp_bulk_reset_manager_only',
            groups=[self.group_user.id, self.group_manager.id],
        )
        permitted_user = self._make_internal_user(
            prefix='cmp_bulk_reset_allowed',
            groups=[self.group_user.id, self.group_manager.id, self.group_bulk_reset.id],
        )

        with self.assertRaises(AccessError):
            self.env['account.move'].with_user(manager_only_user)._check_bulk_move_action_access()

        self.env['account.move'].with_user(permitted_user)._check_bulk_move_action_access()
