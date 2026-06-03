import uuid

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestChartOfAccountsPermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_account_manager = cls.env.ref('account.group_account_manager')
        cls.group_manage_coa = cls.env.ref(
            'custom_module_permissions.group_custom_module_manage_chart_of_accounts'
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

    def _new_account_vals(self):
        suffix = uuid.uuid4().hex[:8]
        return {
            'name': f'Test CoA {suffix}',
            'code': f'T{suffix[:6].upper()}',
            'account_type': 'asset_current',
            'company_ids': [Command.set(self.env.company.ids)],
        }

    def test_manager_without_custom_group_cannot_create_write_archive_unlink(self):
        user = self._make_user(
            prefix='coa_denied',
            groups=[self.group_user.id, self.group_account_manager.id],
        )

        with self.assertRaises(AccessError):
            self.env['account.account'].with_user(user).create(self._new_account_vals())

        account = self.env['account.account'].create(self._new_account_vals())

        with self.assertRaises(AccessError):
            account.with_user(user).write({'name': 'Blocked Update'})

        with self.assertRaises(AccessError):
            account.with_user(user).write({'active': False})

        with self.assertRaises(AccessError):
            account.with_user(user).unlink()

    def test_manager_with_custom_group_can_create_write_archive_unlink(self):
        user = self._make_user(
            prefix='coa_allowed',
            groups=[
                self.group_user.id,
                self.group_account_manager.id,
                self.group_manage_coa.id,
            ],
        )

        account = self.env['account.account'].with_user(user).create(self._new_account_vals())
        self.assertTrue(account.exists())

        account.with_user(user).write({'name': 'Allowed Update'})
        self.assertEqual(account.name, 'Allowed Update')

        account.with_user(user).write({'active': False})
        self.assertFalse(account.active)

        account.with_user(user).unlink()
        self.assertFalse(account.exists())

    def test_import_path_respects_custom_coa_permission(self):
        denied_user = self._make_user(
            prefix='coa_import_denied',
            groups=[self.group_user.id, self.group_account_manager.id],
        )
        allowed_user = self._make_user(
            prefix='coa_import_allowed',
            groups=[
                self.group_user.id,
                self.group_account_manager.id,
                self.group_manage_coa.id,
            ],
        )

        denied_vals = self._new_account_vals()
        denied_result = self.env['account.account'].with_user(denied_user).load(
            ['name', 'code', 'account_type'],
            [[denied_vals['name'], denied_vals['code'], denied_vals['account_type']]],
        )
        denied_account = self.env['account.account'].search([
            ('code', '=', denied_vals['code']),
            ('company_ids', 'in', self.env.company.ids),
        ])

        self.assertTrue(denied_result.get('messages'))
        self.assertFalse(denied_account)

        allowed_vals = self._new_account_vals()
        allowed_result = self.env['account.account'].with_user(allowed_user).load(
            ['name', 'code', 'account_type'],
            [[allowed_vals['name'], allowed_vals['code'], allowed_vals['account_type']]],
        )
        allowed_account = self.env['account.account'].search([
            ('code', '=', allowed_vals['code']),
            ('company_ids', 'in', self.env.company.ids),
        ])

        self.assertFalse(allowed_result.get('messages'))
        self.assertTrue(allowed_account)
