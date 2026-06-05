from odoo.addons.account_accountant.tests.common import TestBankRecWidgetCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestBankGLLabelSync(TestBankRecWidgetCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank_sync_journal = cls.company_data['default_journal_bank'].copy({
            'name': 'Bank Label Sync Journal',
            'code': 'BLSJ',
        })
        cls.bank_sync_journal.use_bank_label_in_gl = False

    def setUp(self):
        super().setUp()
        self.bank_sync_journal.use_bank_label_in_gl = False

    def _create_sync_statement_line(self, amount=100.0, payment_ref='Bank Label'):
        return self._create_st_line(
            amount=amount,
            payment_ref=payment_ref,
            update_create_date=False,
            journal_id=self.bank_sync_journal.id,
        )

    def _assert_statement_move_line_labels(self, statement_line, expected_label):
        move_lines = statement_line.move_id.line_ids.filtered(
            lambda line: line.statement_line_id == statement_line
        )
        self.assertTrue(move_lines, 'Expected statement-linked journal items.')
        self.assertTrue(
            all(line.name == expected_label for line in move_lines),
            'Expected all statement-linked journal item labels to match payment_ref.',
        )

    def test_mark_as_account_keeps_payment_ref_labels_when_enabled(self):
        payment_ref = 'Bank Payment 001'
        statement_line = self._create_sync_statement_line(payment_ref=payment_ref)
        statement_line.journal_id.use_bank_label_in_gl = True

        _liquidity_line, suspense_lines, _other_lines = statement_line._seek_for_lines()
        self.assertEqual(len(suspense_lines), 1)
        move = statement_line.move_id
        if move.state == 'posted':
            move.button_draft()
        suspense_lines.with_context(skip_readonly_check=True).write({
            'account_id': self.company_data['default_account_revenue'].id,
        })
        move.action_post()

        statement_line.invalidate_recordset(['payment_ref'])
        self.assertEqual(statement_line.payment_ref, payment_ref)
        self._assert_statement_move_line_labels(statement_line, payment_ref)

    def test_account_update_restores_payment_ref_after_move_sync(self):
        payment_ref = 'Bank Sync Source Label'
        statement_line = self._create_sync_statement_line(payment_ref=payment_ref)
        statement_line.journal_id.use_bank_label_in_gl = True

        liquidity_line, suspense_lines, _other_lines = statement_line._seek_for_lines()
        self.assertEqual(len(liquidity_line), 1)
        self.assertEqual(len(suspense_lines), 1)

        liquidity_line.with_context(
            skip_account_move_synchronization=True,
            skip_bank_label_sync_enforcement=True,
            tracking_disable=True,
        ).write({'name': 'Unexpected Liquidity Label'})

        suspense_lines.with_context(skip_readonly_check=True).write({
            'account_id': self.company_data['default_account_expense'].id,
        })

        statement_line.invalidate_recordset(['payment_ref'])
        self.assertEqual(statement_line.payment_ref, payment_ref)
        self._assert_statement_move_line_labels(statement_line, payment_ref)

    def test_payment_ref_write_reapplies_labels_when_enabled(self):
        statement_line = self._create_sync_statement_line(payment_ref='Old Label')
        statement_line.journal_id.use_bank_label_in_gl = True

        new_label = 'Updated Label'
        statement_line.write({'payment_ref': new_label})

        statement_line.invalidate_recordset(['payment_ref'])
        self.assertEqual(statement_line.payment_ref, new_label)
        self._assert_statement_move_line_labels(statement_line, new_label)

    def test_disabled_journal_keeps_core_label_behavior(self):
        statement_line = self._create_sync_statement_line(payment_ref='Original Label')
        self.assertFalse(statement_line.journal_id.use_bank_label_in_gl)

        liquidity_line, _suspense_lines, _other_lines = statement_line._seek_for_lines()
        manual_label = 'Manual Core Label'
        liquidity_line.with_context(skip_readonly_check=True).write({'name': manual_label})

        statement_line.invalidate_recordset(['payment_ref'])
        liquidity_line.invalidate_recordset(['name'])
        self.assertEqual(liquidity_line.name, manual_label)
        self.assertEqual(statement_line.payment_ref, manual_label)