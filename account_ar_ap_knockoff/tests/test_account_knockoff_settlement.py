import base64

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestAccountKnockoffSettlement(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.knockoff_manager = cls.simple_accountman
        cls.knockoff_manager.write({
            'group_ids': [Command.link(cls.env.ref('account_ar_ap_knockoff.group_knockoff_manager').id)],
        })
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id
        cls.misc_journal = cls.company_data['default_journal_misc']
        cls.sale_journal = cls.company_data['default_journal_sale']
        cls.purchase_journal = cls.company_data['default_journal_purchase']
        cls.receivable_account = cls.company_data['default_account_receivable']
        cls.payable_account = cls.company_data['default_account_payable']
        cls.revenue_account = cls.company_data['default_account_revenue']
        cls.expense_account = cls.company_data['default_account_expense']
        cls.customer_partner = cls.partner_a
        cls.vendor_partner = cls.partner_a
        cls.other_partner = cls.partner_b

    def _create_customer_invoice(self, partner, amount, invoice_date='2026-05-01'):
        return self._create_invoice_one_line(
            move_type='out_invoice',
            partner_id=partner,
            journal_id=self.sale_journal,
            account_id=self.revenue_account,
            price_unit=amount,
            quantity=1.0,
            tax_ids=self.env['account.tax'],
            post=True,
            invoice_date=invoice_date,
        )

    def _create_vendor_bill(self, partner, amount, invoice_date='2026-05-01'):
        return self._create_invoice_one_line(
            move_type='in_invoice',
            partner_id=partner,
            journal_id=self.purchase_journal,
            account_id=self.expense_account,
            price_unit=amount,
            quantity=1.0,
            tax_ids=self.env['account.tax'],
            post=True,
            invoice_date=invoice_date,
        )

    def _create_open_entry(self, open_lines, move_date='2026-05-01'):
        line_vals = []
        total_balance = 0.0
        for index, open_line in enumerate(open_lines, start=1):
            balance = open_line['balance']
            total_balance += balance
            partner = open_line.get('partner')
            line_vals.append(Command.create({
                'name': open_line.get('name', f'Open Line {index}'),
                'account_id': open_line['account_id'].id,
                'partner_id': partner.id if partner else False,
                'date_maturity': move_date,
                'debit': balance if balance > 0.0 else 0.0,
                'credit': -balance if balance < 0.0 else 0.0,
                'currency_id': self.company_currency.id,
                'amount_currency': balance,
            }))

        counterpart_account = self.revenue_account if total_balance > 0.0 else self.expense_account
        line_vals.append(Command.create({
            'name': 'Counterpart',
            'account_id': counterpart_account.id,
            'debit': -total_balance if total_balance < 0.0 else 0.0,
            'credit': total_balance if total_balance > 0.0 else 0.0,
            'currency_id': self.company_currency.id,
            'amount_currency': -total_balance,
        }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': move_date,
            'line_ids': line_vals,
        })
        move.action_post()
        return move

    def _create_attachment(self, name='support.txt'):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'knockoff support'),
            'mimetype': 'text/plain',
        })

    def _create_settlement(
        self,
        customer_moves,
        vendor_moves,
        settlement_type='same_partner',
        amount=None,
        reason=None,
        attachment=None,
    ):
        vals = {
            'company_id': self.company.id,
            'journal_id': self.misc_journal.id,
            'settlement_type': settlement_type,
            'settlement_date': fields.Date.to_date('2026-05-05'),
            'customer_invoice_ids': [Command.set(customer_moves.ids)],
            'vendor_bill_ids': [Command.set(vendor_moves.ids)],
            'reason': reason,
        }
        if attachment:
            vals['attachment_ids'] = [Command.set(attachment.ids)]
        settlement = self.env['account.knockoff.settlement'].create(vals)
        if amount is not None:
            settlement.amount = amount
        return settlement

    def _run_workflow(self, settlement):
        settlement.with_user(self.knockoff_manager).action_compute_allocation()
        settlement.with_user(self.knockoff_manager).action_submit()
        settlement.with_user(self.knockoff_manager).action_approve()
        settlement.with_user(self.knockoff_manager).action_create_knockoff_entry()
        return settlement

    def _assert_open_amount(self, settlement, move, allocation_type, expected):
        self.assertEqual(
            settlement.currency_id.round(settlement._get_move_open_amount(move, allocation_type)),
            settlement.currency_id.round(expected),
        )

    def test_invoice_and_bill_equal_amounts_full_reconcile(self):
        invoice = self._create_customer_invoice(self.customer_partner, 100.0)
        bill = self._create_vendor_bill(self.vendor_partner, 100.0)
        settlement = self._create_settlement(invoice, bill)

        self.assertEqual(settlement.amount, 100.0)
        self._run_workflow(settlement)

        self.assertEqual(settlement.state, 'posted')
        self.assertTrue(settlement.move_id)
        self._assert_open_amount(settlement, invoice, 'customer_invoice', 0.0)
        self._assert_open_amount(settlement, bill, 'vendor_bill', 0.0)

    def test_invoice_greater_than_bill_leaves_receivable_open(self):
        invoice = self._create_customer_invoice(self.customer_partner, 150.0)
        bill = self._create_vendor_bill(self.vendor_partner, 100.0)
        settlement = self._create_settlement(invoice, bill)

        self.assertEqual(settlement.amount, 100.0)
        self._run_workflow(settlement)

        self._assert_open_amount(settlement, invoice, 'customer_invoice', 50.0)
        self._assert_open_amount(settlement, bill, 'vendor_bill', 0.0)

    def test_bill_greater_than_invoice_leaves_payable_open(self):
        invoice = self._create_customer_invoice(self.customer_partner, 100.0)
        bill = self._create_vendor_bill(self.vendor_partner, 150.0)
        settlement = self._create_settlement(invoice, bill)

        self.assertEqual(settlement.amount, 100.0)
        self._run_workflow(settlement)

        self._assert_open_amount(settlement, invoice, 'customer_invoice', 0.0)
        self._assert_open_amount(settlement, bill, 'vendor_bill', 50.0)

    def test_invoice_and_payable_journal_entry_reconcile(self):
        invoice = self._create_customer_invoice(self.customer_partner, 120.0)
        payable_entry = self._create_open_entry([{
            'account_id': self.payable_account,
            'partner': self.vendor_partner,
            'balance': -120.0,
            'name': 'Vendor payable',
        }])
        settlement = self._create_settlement(invoice, payable_entry)

        self.assertFalse(payable_entry.partner_id)
        self.assertEqual(settlement.partner_id, self.vendor_partner.commercial_partner_id)
        self._run_workflow(settlement)

        self._assert_open_amount(settlement, invoice, 'customer_invoice', 0.0)
        self._assert_open_amount(settlement, payable_entry, 'vendor_bill', 0.0)

    def test_receivable_journal_entry_and_bill_reconcile(self):
        receivable_entry = self._create_open_entry([{
            'account_id': self.receivable_account,
            'partner': self.customer_partner,
            'balance': 130.0,
            'name': 'Customer receivable',
        }])
        bill = self._create_vendor_bill(self.vendor_partner, 130.0)
        settlement = self._create_settlement(receivable_entry, bill)

        self.assertFalse(receivable_entry.partner_id)
        self.assertEqual(settlement.partner_id, self.customer_partner.commercial_partner_id)
        self._run_workflow(settlement)

        self._assert_open_amount(settlement, receivable_entry, 'customer_invoice', 0.0)
        self._assert_open_amount(settlement, bill, 'vendor_bill', 0.0)

    def test_third_party_mixed_partner_journal_entry_is_allowed(self):
        invoice = self._create_customer_invoice(self.customer_partner, 100.0)
        mixed_payable_entry = self._create_open_entry([
            {
                'account_id': self.payable_account,
                'partner': self.vendor_partner,
                'balance': -40.0,
                'name': 'Vendor payable A',
            },
            {
                'account_id': self.payable_account,
                'partner': self.other_partner,
                'balance': -60.0,
                'name': 'Vendor payable B',
            },
        ])
        attachment = self._create_attachment()
        settlement = self._create_settlement(
            invoice,
            mixed_payable_entry,
            settlement_type='third_party',
            reason='Third-party offset support',
            attachment=attachment,
        )

        self.assertEqual(settlement.customer_partner_id, self.customer_partner.commercial_partner_id)
        self.assertFalse(settlement.vendor_partner_id)
        self._run_workflow(settlement)

        self._assert_open_amount(settlement, invoice, 'customer_invoice', 0.0)
        self._assert_open_amount(settlement, mixed_payable_entry, 'vendor_bill', 0.0)

    def test_same_partner_mixed_partner_journal_entry_fails_on_submit(self):
        invoice = self._create_customer_invoice(self.customer_partner, 100.0)
        mixed_payable_entry = self._create_open_entry([
            {
                'account_id': self.payable_account,
                'partner': self.vendor_partner,
                'balance': -40.0,
                'name': 'Vendor payable A',
            },
            {
                'account_id': self.payable_account,
                'partner': self.other_partner,
                'balance': -60.0,
                'name': 'Vendor payable B',
            },
        ])
        settlement = self._create_settlement(invoice, mixed_payable_entry)

        settlement.with_user(self.knockoff_manager).action_compute_allocation()
        self.assertFalse(settlement.partner_id)
        with self.assertRaisesRegex(UserError, 'one common non-empty partner'):
            settlement.with_user(self.knockoff_manager).action_submit()

    def test_same_partner_partnerless_journal_entry_fails_on_submit(self):
        invoice = self._create_customer_invoice(self.customer_partner, 90.0)
        partnerless_payable_entry = self._create_open_entry([{
            'account_id': self.payable_account,
            'balance': -90.0,
            'name': 'Partnerless payable',
        }])
        settlement = self._create_settlement(invoice, partnerless_payable_entry)

        settlement.with_user(self.knockoff_manager).action_compute_allocation()
        self.assertFalse(settlement.partner_id)
        with self.assertRaisesRegex(UserError, 'one common non-empty partner'):
            settlement.with_user(self.knockoff_manager).action_submit()

    def test_over_allocation_protection_with_multi_line_journal_entry(self):
        receivable_entry = self._create_open_entry([
            {
                'account_id': self.receivable_account,
                'partner': self.customer_partner,
                'balance': 30.0,
                'name': 'Receivable split A',
            },
            {
                'account_id': self.receivable_account,
                'partner': self.customer_partner,
                'balance': 30.0,
                'name': 'Receivable split B',
            },
        ])
        invoice = self._create_customer_invoice(self.customer_partner, 60.0)
        bill = self._create_vendor_bill(self.vendor_partner, 120.0)
        settlement = self._create_settlement(receivable_entry | invoice, bill)

        settlement.with_user(self.knockoff_manager).action_compute_allocation()
        settlement.line_ids = [
            Command.clear(),
            Command.create({
                'move_id': receivable_entry.id,
                'move_type': 'customer_invoice',
                'allocated_amount': 50.0,
            }),
            Command.create({
                'move_id': receivable_entry.id,
                'move_type': 'customer_invoice',
                'allocated_amount': 50.0,
            }),
            Command.create({
                'move_id': invoice.id,
                'move_type': 'customer_invoice',
                'allocated_amount': 20.0,
            }),
            Command.create({
                'move_id': bill.id,
                'move_type': 'vendor_bill',
                'allocated_amount': 120.0,
            }),
        ]

        with self.assertRaisesRegex(UserError, 'total allocated amount'):
            settlement._validate_allocation_lines()

    def test_line_level_partner_derivation_ignores_blank_move_partner(self):
        receivable_entry = self._create_open_entry([{
            'account_id': self.receivable_account,
            'partner': self.customer_partner,
            'balance': 75.0,
            'name': 'Receivable with line partner',
        }])
        bill = self._create_vendor_bill(self.vendor_partner, 75.0)
        settlement = self._create_settlement(receivable_entry, bill)

        self.assertFalse(receivable_entry.partner_id)
        self.assertEqual(settlement.partner_id, self.customer_partner.commercial_partner_id)
        settlement.with_user(self.knockoff_manager).action_compute_allocation()
        customer_line = settlement.line_ids.filtered(lambda line: line.move_id == receivable_entry)
        self.assertEqual(customer_line.partner_id, self.customer_partner.commercial_partner_id)

    def test_multi_currency_invoice_and_bill_reconcile(self):
        # Setup currencies
        currency_usd = self.env.ref('base.USD')
        currency_eur = self.env.ref('base.EUR')
        
        # Activate currencies if not already active
        if not currency_usd.active:
            currency_usd.active = True
        if not currency_eur.active:
            currency_eur.active = True
        
        # Ensure exchange rates exist for the test date
        rate_date = fields.Date.to_date('2026-05-01')
        self.env['res.currency.rate'].create([
            {'currency_id': currency_usd.id, 'rate': 1.1, 'name': rate_date, 'company_id': self.company.id},
            {'currency_id': currency_eur.id, 'rate': 1.0, 'name': rate_date, 'company_id': self.company.id},
        ])

        # Create USD invoice (110 USD = 100 EUR)
        invoice = self._create_invoice_one_line(
            move_type='out_invoice',
            partner_id=self.customer_partner,
            journal_id=self.sale_journal,
            account_id=self.revenue_account,
            price_unit=110.0,
            currency_id=currency_usd.id,
            post=True,
            invoice_date='2026-05-01',
        )
        
        # Create EUR bill (100 EUR)
        bill = self._create_invoice_one_line(
            move_type='in_invoice',
            partner_id=self.vendor_partner,
            journal_id=self.purchase_journal,
            account_id=self.expense_account,
            price_unit=100.0,
            currency_id=currency_eur.id,
            post=True,
            invoice_date='2026-05-01',
        )

        # Create settlement in EUR
        settlement = self._create_settlement(invoice, bill)
        settlement.currency_id = currency_eur.id
        
        # In EUR, invoice residual should be 100.0 (110 USD / 1.1)
        self._assert_open_amount(settlement, invoice, 'customer_invoice', 100.0)
        self.assertEqual(settlement.amount, 100.0)
        
        self._run_workflow(settlement)

        self.assertEqual(settlement.state, 'posted')
        self._assert_open_amount(settlement, invoice, 'customer_invoice', 0.0)
        self._assert_open_amount(settlement, bill, 'vendor_bill', 0.0)
