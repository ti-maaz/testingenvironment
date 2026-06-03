from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import Form, tagged


@tagged('post_install', '-at_install')
class TestCustomerInvoiceSerialCheck(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.invoice_date = fields.Date.from_string('2025-04-01')

    def _create_invoice(self, move_type='out_invoice', *, state='posted'):
        move_form = Form(
            self.env['account.move']
            .with_company(self.env.company)
            .with_context(default_move_type=move_type)
        )
        move_form.invoice_date = self.invoice_date
        if not move_form._get_modifier('date', 'invisible'):
            move_form.date = self.invoice_date
        move_form.partner_id = self.partner_a

        with move_form.invoice_line_ids.new() as line_form:
            line_form.name = 'Serial check test line'
            line_form.price_unit = 100.0
            line_form.tax_ids.clear()

        move = move_form.save()
        if state == 'posted':
            move.action_post()
        elif state == 'cancel':
            move.action_post()
            move.button_cancel()
        return move

    def _move_to_sequence_gap(self, move, reference_move, sequence_gap=1000):
        format_string, format_values = reference_move._get_sequence_format_param(reference_move.name)
        format_values['seq'] = reference_move.sequence_number + sequence_gap
        move.name = format_string.format(**format_values)
        # Invalidate recordset to force recomputation of made_sequence_gap
        move.invalidate_recordset(['made_sequence_gap'])

    def test_missing_customer_invoice_serial_action_opens_gap_invoices(self):
        regular_invoice = self._create_invoice()
        gap_invoice = self._create_invoice()
        self._move_to_sequence_gap(gap_invoice, regular_invoice)
        self.assertTrue(gap_invoice.made_sequence_gap)

        action = self.env['account.move'].action_check_missing_customer_invoice_serials()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'account.move')
        self.assertIn(('move_type', '=', 'out_invoice'), action['domain'])
        self.assertIn(('state', '=', 'posted'), action['domain'])
        self.assertIn(('made_sequence_gap', '=', True), action['domain'])
        self.assertEqual(
            self.env['account.move'].search(action['domain']),
            gap_invoice,
        )

    def test_missing_customer_invoice_serial_action_ignores_non_customer_invoice_moves(self):
        reference_invoice = self._create_invoice()
        customer_invoice = self._create_invoice()
        customer_refund = self._create_invoice('out_refund')
        vendor_bill = self._create_invoice('in_invoice')
        draft_invoice = self._create_invoice(state='draft')
        cancelled_invoice = self._create_invoice()

        for offset, move in enumerate(
            customer_invoice | customer_refund | vendor_bill | draft_invoice | cancelled_invoice,
            start=1000,
        ):
            self._move_to_sequence_gap(move, reference_invoice, sequence_gap=offset)
        cancelled_invoice.button_cancel()

        action = self.env['account.move'].action_check_missing_customer_invoice_serials()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(
            self.env['account.move'].search(action['domain']),
            customer_invoice,
        )

    def test_missing_customer_invoice_serial_action_returns_notification_without_gaps(self):
        self._create_invoice()

        action = self.env['account.move'].action_check_missing_customer_invoice_serials()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'success')
