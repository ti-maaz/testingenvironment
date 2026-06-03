from odoo.addons.account_accountant.tests.common import TestBankRecWidgetCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestAccountBankRecode(TestBankRecWidgetCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_account = cls.company_data['default_account_revenue']
        cls.target_account = cls.company_data['default_account_expense']

    def _create_reconciled_statement_line(self, amount=100.0, payment_ref='Original Label'):
        statement_line = self._create_st_line(
            amount=amount,
            payment_ref=payment_ref,
            update_create_date=False,
        )
        suspense_line = statement_line.line_ids.filtered(
            lambda line: line.account_id == statement_line.journal_id.suspense_account_id
        )
        statement_line.set_account_bank_statement_line(suspense_line.id, self.source_account.id)
        return statement_line

    def _create_wizard(self, statement_lines, **values):
        return self.env['account.bank.recode.wizard'].with_context(
            active_model='account.bank.statement.line',
            active_ids=statement_lines.ids,
        ).create(values)

    def test_reconciled_account_recode_changes_counterpart_account(self):
        statement_line = self._create_reconciled_statement_line()

        wizard = self._create_wizard(
            statement_line,
            recode_target='account',
            transaction_state='reconciled',
            target_account_id=self.target_account.id,
        )

        wizard.action_recode()

        statement_line.invalidate_recordset(['is_reconciled'])
        _liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()
        self.assertTrue(statement_line.is_reconciled)
        self.assertFalse(suspense_lines)
        self.assertEqual(other_lines.account_id, self.target_account)

    def test_unreconciled_account_recode_transfers_suspense_to_target_account(self):
        statement_line = self._create_st_line(
            amount=100.0,
            payment_ref='Pending Label',
            update_create_date=False,
        )

        wizard = self._create_wizard(
            statement_line,
            recode_target='account',
            transaction_state='unreconciled',
            target_account_id=self.target_account.id,
        )

        wizard.action_recode()

        statement_line.invalidate_recordset(['is_reconciled'])
        _liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()
        self.assertTrue(statement_line.is_reconciled)
        self.assertFalse(suspense_lines)
        self.assertEqual(other_lines.account_id, self.target_account)

    def test_reconciled_label_recode_updates_transaction_label_only(self):
        statement_line = self._create_reconciled_statement_line(payment_ref='Old Label')
        liquidity_lines, _suspense_lines, other_lines = statement_line._seek_for_lines()
        counterpart_line = other_lines

        wizard = self._create_wizard(
            statement_line,
            recode_target='label',
            transaction_state='reconciled',
            new_label='Updated Label',
        )

        wizard.action_recode()

        statement_line.invalidate_recordset(['payment_ref', 'is_reconciled'])
        liquidity_line = self.env['account.move.line'].browse(liquidity_lines.id)
        counterpart_line = self.env['account.move.line'].browse(counterpart_line.id)
        _liquidity_lines, suspense_lines, current_other_lines = statement_line._seek_for_lines()
        self.assertEqual(statement_line.payment_ref, 'Updated Label')
        self.assertEqual(liquidity_line.name, 'Updated Label')
        self.assertEqual(counterpart_line.name, 'Old Label')
        self.assertFalse(suspense_lines)
        self.assertEqual(current_other_lines.account_id, self.source_account)
        self.assertTrue(statement_line.is_reconciled)

    def test_unreconciled_label_recode_updates_liquidity_and_suspense_names(self):
        statement_line = self._create_st_line(
            amount=100.0,
            payment_ref='Old Pending Label',
            update_create_date=False,
        )

        wizard = self._create_wizard(
            statement_line,
            recode_target='label',
            transaction_state='unreconciled',
            new_label='Updated Pending Label',
        )

        wizard.action_recode()

        statement_line.invalidate_recordset(['payment_ref', 'is_reconciled'])
        liquidity_lines, suspense_lines, _other_lines = statement_line._seek_for_lines()
        self.assertEqual(statement_line.payment_ref, 'Updated Pending Label')
        self.assertEqual(liquidity_lines.name, 'Updated Pending Label')
        self.assertEqual(suspense_lines.name, 'Updated Pending Label')
        self.assertFalse(statement_line.is_reconciled)

    def test_mixed_selection_only_processes_chosen_transaction_state(self):
        reconciled_line = self._create_reconciled_statement_line(payment_ref='Reconciled Label')
        unreconciled_line = self._create_st_line(
            amount=80.0,
            payment_ref='Pending Label',
            update_create_date=False,
        )

        wizard = self._create_wizard(
            reconciled_line | unreconciled_line,
            recode_target='account',
            transaction_state='unreconciled',
            target_account_id=self.target_account.id,
        )

        self.assertEqual(wizard.applicable_count, 1)
        self.assertEqual(wizard.ignored_count, 1)
        self.assertIn('already reconciled', wizard.selection_note)

        wizard.action_recode()

        _liquidity_lines, _suspense_lines, reconciled_other_lines = reconciled_line._seek_for_lines()
        _liquidity_lines, suspense_lines, unreconciled_other_lines = unreconciled_line._seek_for_lines()
        self.assertEqual(reconciled_other_lines.account_id, self.source_account)
        self.assertFalse(suspense_lines)
        self.assertEqual(unreconciled_other_lines.account_id, self.target_account)

    def test_recode_requires_applicable_transactions(self):
        statement_line = self._create_reconciled_statement_line()

        wizard = self._create_wizard(
            statement_line,
            recode_target='account',
            transaction_state='unreconciled',
            target_account_id=self.target_account.id,
        )

        with self.assertRaisesRegex(UserError, 'No unreconciled transactions'):
            wizard.action_recode()

    def test_default_get_prefills_unreconciled_state_for_unreconciled_selection(self):
        statement_line = self._create_st_line(
            amount=50.0,
            payment_ref='Needs Review',
            update_create_date=False,
        )

        defaults = self.env['account.bank.recode.wizard'].with_context(
            active_model='account.bank.statement.line',
            active_ids=statement_line.ids,
        ).default_get(['transaction_state', 'statement_line_ids', 'company_id'])

        self.assertEqual(defaults['transaction_state'], 'unreconciled')
        self.assertEqual(defaults['company_id'], statement_line.company_id.id)
        self.assertEqual(defaults['statement_line_ids'][0][2], statement_line.ids)

    def test_unreconcile_moves_counterpart_to_suspense_account(self):
        """Test that unreconcile moves counterpart lines back to suspense account."""
        statement_line = self._create_reconciled_statement_line(
            amount=100.0,
            payment_ref='Reconciled Transaction',
        )
        suspense_account = statement_line.journal_id.suspense_account_id

        # Verify initial state - transaction is reconciled
        self.assertTrue(statement_line.is_reconciled)
        _liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()
        self.assertFalse(suspense_lines)
        self.assertEqual(other_lines.account_id, self.source_account)

        # Create wizard with unreconcile option
        wizard = self._create_wizard(
            statement_line,
            recode_target='unreconcile',
        )

        wizard.action_recode()

        # Verify the transaction is now unreconciled
        statement_line.invalidate_recordset(['is_reconciled'])
        _liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()
        self.assertFalse(statement_line.is_reconciled)
        # Counterpart line should now be in suspense account
        self.assertEqual(other_lines.account_id, suspense_account)
        # No suspense lines should exist after unreconcile
        self.assertFalse(suspense_lines)

    def test_unreconcile_bulk_transactions(self):
        """Test that unreconcile works for multiple transactions at once."""
        statement_line_1 = self._create_reconciled_statement_line(
            amount=100.0,
            payment_ref='Reconciled Transaction 1',
        )
        statement_line_2 = self._create_reconciled_statement_line(
            amount=200.0,
            payment_ref='Reconciled Transaction 2',
        )
        suspense_account = statement_line_1.journal_id.suspense_account_id

        wizard = self._create_wizard(
            statement_line_1 | statement_line_2,
            recode_target='unreconcile',
        )

        wizard.action_recode()

        for statement_line in statement_line_1 | statement_line_2:
            statement_line.invalidate_recordset(['is_reconciled'])
            _liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()
            self.assertFalse(statement_line.is_reconciled)
            self.assertEqual(other_lines.account_id, suspense_account)

    def test_unreconcile_requires_reconciled_transactions(self):
        """Test that unreconcile only works on reconciled transactions."""
        unreconciled_line = self._create_st_line(
            amount=100.0,
            payment_ref='Unreconciled Transaction',
            update_create_date=False,
        )

        wizard = self._create_wizard(
            unreconciled_line,
            recode_target='unreconcile',
        )

        with self.assertRaisesRegex(UserError, 'No reconciled transactions'):
            wizard.action_recode()

    def test_unreconcile_mixed_selection_only_processes_reconciled(self):
        """Test that unreconcile only processes reconciled transactions from mixed selection."""
        reconciled_line = self._create_reconciled_statement_line(
            amount=100.0,
            payment_ref='Reconciled',
        )
        unreconciled_line = self._create_st_line(
            amount=80.0,
            payment_ref='Unreconciled',
            update_create_date=False,
        )
        suspense_account = reconciled_line.journal_id.suspense_account_id

        wizard = self._create_wizard(
            reconciled_line | unreconciled_line,
            recode_target='unreconcile',
        )

        wizard.action_recode()

        # Reconciled line should be unreconciled
        reconciled_line.invalidate_recordset(['is_reconciled'])
        _liquidity_lines, suspense_lines, other_lines = reconciled_line._seek_for_lines()
        self.assertFalse(reconciled_line.is_reconciled)
        self.assertEqual(other_lines.account_id, suspense_account)

        # Unreconciled line should remain unchanged
        unreconciled_line.invalidate_recordset(['is_reconciled'])
        _liquidity_lines, suspense_lines, other_lines = unreconciled_line._seek_for_lines()
        self.assertFalse(unreconciled_line.is_reconciled)
        # It should still have suspense lines since it was never reconciled
        self.assertTrue(suspense_lines)
