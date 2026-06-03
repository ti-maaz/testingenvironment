import base64
import io
import unittest

try:
    from openpyxl import Workbook, load_workbook
except ImportError:
    Workbook = load_workbook = None

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import Form, tagged


@tagged('post_install', '-at_install')
@unittest.skipUnless(Workbook and load_workbook, 'openpyxl is required for XLSX assertions')
class TestVatAuditExcelPack(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.date_from = fields.Date.from_string('2025-04-01')
        cls.date_to = fields.Date.from_string('2025-06-30')
        cls.sale_tax = cls.company_data['default_tax_sale']
        cls.purchase_tax = cls.company_data['default_tax_purchase']
        cls.bank_journal = cls.company_data['default_journal_bank']
        cls.bank_sale_nature_account_uae = cls._make_account(
            '41010101',
            'Revenue - UAE Clients',
        )
        cls.bank_sale_nature_account_international = cls._make_account(
            '41010102',
            'Revenue - International Clients',
        )
        cls.bank_sale_nature_account_related = cls._make_account(
            '41020101',
            'Revenue - Related Party',
        )
        cls.bank_sale_non_revenue_account = cls._make_account(
            '41030101',
            'Revenue - Other Clients',
        )
        cls.output_vat_account = cls._make_account(
            '22020101',
            'VAT Output',
            account_type='liability_current',
        )
        cls.input_vat_account = cls._make_account(
            '12030403',
            'VAT Input',
            account_type='asset_current',
        )
        cls.bank_purchase_expense_account = cls._make_account(
            '51220101',
            'Bank Charges Expense',
            account_type='expense',
        )
        cls.zero_sale_tax = cls.env['account.tax'].create({
            'name': 'Zero Rated Sale Tax',
            'amount_type': 'percent',
            'amount': 0.0,
            'type_tax_use': 'sale',
            'company_id': cls.env.company.id,
        })
        cls.zero_ex_sale_tax = cls.env['account.tax'].create({
            'name': '0% EX',
            'amount_type': 'percent',
            'amount': 0.0,
            'type_tax_use': 'sale',
            'company_id': cls.env.company.id,
        })
        cls.zero_ext_sale_tax = cls.env['account.tax'].create({
            'name': '0% EXT',
            'amount_type': 'percent',
            'amount': 0.0,
            'type_tax_use': 'sale',
            'company_id': cls.env.company.id,
        })

    @classmethod
    def _make_account(cls, code, name, *, account_type=None):
        return cls.env['account.account'].create({
            'name': name,
            'code': code,
            'account_type': account_type or cls.company_data['default_account_revenue'].account_type,
            'company_ids': [Command.set(cls.env.company.ids)],
        })

    @classmethod
    def _make_currency(cls, name, symbol):
        return cls.env['res.currency'].create({
            'name': name,
            'symbol': symbol,
            'rounding': 0.01,
        })

    def _create_wizard(self, **overrides):
        values = {
            'company_id': self.env.company.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'target_move': 'posted',
            'include_general_ledger': False,
            'include_trial_balance': False,
            'include_profit_loss': False,
            'include_balance_sheet': False,
            'include_aged_receivable': False,
            'include_aged_payable': False,
        }
        values.update(overrides)
        return self.env['vat.audit.excel.pack.wizard'].create(values)

    def _create_invoice(self, move_type, lines):
        move_form = Form(
            self.env['account.move']
            .with_company(self.env.company)
            .with_context(default_move_type=move_type)
        )
        move_form.invoice_date = self.date_from
        if not move_form._get_modifier('date', 'invisible'):
            move_form.date = self.date_from
        move_form.partner_id = self.partner_a

        for amount, taxes in lines:
            with move_form.invoice_line_ids.new() as line_form:
                line_form.name = 'test line'
                line_form.price_unit = amount
                line_form.tax_ids.clear()
                for tax in taxes:
                    line_form.tax_ids.add(tax)

        move = move_form.save()
        move.action_post()
        return move

    def _create_bank_statement_line(
        self,
        *,
        amount,
        vat_category,
        payment_ref,
        counterpart_account=None,
        partner=None,
        date=None,
        foreign_currency=None,
        amount_currency=None,
        vat_output_account=None,
        vat_amount=0.0,
        vat_input_account=None,
        vat_input_amount=0.0,
    ):
        values = {
            'date': date or self.date_from,
            'journal_id': self.bank_journal.id,
            'partner_id': (partner or self.partner_a).id,
            'payment_ref': payment_ref,
            'amount': amount,
            'vat_category': vat_category,
        }
        if foreign_currency:
            values['foreign_currency_id'] = foreign_currency.id
            values['amount_currency'] = amount_currency
        statement_line = self.env['account.bank.statement.line'].create(values)
        if counterpart_account:
            _liquidity_lines, suspense_lines, _other_lines = statement_line._seek_for_lines()
            statement_line.set_account_bank_statement_line(suspense_lines.id, counterpart_account.id)
        if vat_output_account and vat_amount:
            self._add_bank_statement_vat_output_line(
                statement_line,
                vat_output_account=vat_output_account,
                vat_amount=vat_amount,
            )
        if vat_input_account and vat_input_amount:
            self._add_bank_statement_vat_input_line(
                statement_line,
                vat_input_account=vat_input_account,
                vat_input_amount=vat_input_amount,
            )
        return statement_line

    def _add_bank_statement_vat_output_line(self, statement_line, *, vat_output_account, vat_amount):
        move = statement_line.move_id
        was_posted = move.state == 'posted'
        if was_posted:
            move.button_draft()

        _liquidity_lines, _suspense_lines, other_lines = statement_line._seek_for_lines()
        revenue_line = other_lines.filtered(
            lambda line: line.account_id.account_type == self.company_data['default_account_revenue'].account_type
        )[:1]
        if not revenue_line:
            return

        vat_amount = abs(float(vat_amount or 0.0))
        if float(statement_line.amount or 0.0) >= 0.0:
            revenue_line.with_context(check_move_validity=False).write({
                'credit': revenue_line.credit - vat_amount,
            })
            tax_values = {'debit': 0.0, 'credit': vat_amount}
        else:
            revenue_line.with_context(check_move_validity=False).write({
                'debit': revenue_line.debit - vat_amount,
            })
            tax_values = {'debit': vat_amount, 'credit': 0.0}

        self.env['account.move.line'].with_context(check_move_validity=False).create({
            'move_id': move.id,
            'name': 'VAT Output',
            'account_id': vat_output_account.id,
            'partner_id': statement_line.partner_id.id,
            **tax_values,
        })

        if was_posted:
            move.action_post()

    def _add_bank_statement_vat_input_line(self, statement_line, *, vat_input_account, vat_input_amount):
        move = statement_line.move_id
        was_posted = move.state == 'posted'
        if was_posted:
            move.button_draft()

        _liquidity_lines, _suspense_lines, other_lines = statement_line._seek_for_lines()
        expense_line = other_lines.filtered(lambda line: line.account_id != vat_input_account)[:1]
        if not expense_line:
            return

        vat_input_amount = abs(float(vat_input_amount or 0.0))
        if float(statement_line.amount or 0.0) <= 0.0:
            expense_line.with_context(check_move_validity=False).write({
                'debit': expense_line.debit - vat_input_amount,
            })
            tax_values = {'debit': vat_input_amount, 'credit': 0.0}
        else:
            expense_line.with_context(check_move_validity=False).write({
                'credit': expense_line.credit - vat_input_amount,
            })
            tax_values = {'debit': 0.0, 'credit': vat_input_amount}

        self.env['account.move.line'].with_context(check_move_validity=False).create({
            'move_id': move.id,
            'name': 'VAT Input',
            'account_id': vat_input_account.id,
            'partner_id': statement_line.partner_id.id,
            **tax_values,
        })

        if was_posted:
            move.action_post()

    def _create_currency_rate(self, currency, rate, *, date=None):
        return self.env['res.currency.rate'].create({
            'currency_id': currency.id,
            'rate': rate,
            'name': date or self.date_from,
            'company_id': self.env.company.root_id.id,
        })

    def _reconcile_statement_line_to_invoice(self, statement_line, invoice):
        _liquidity_lines, suspense_lines, _other_lines = statement_line.with_context(
            skip_account_move_synchronization=True
        )._seek_for_lines()
        invoice_line = invoice.line_ids.filtered(
            lambda line: line.account_type in ('asset_receivable', 'liability_payable')
        )
        suspense_lines.account_id = invoice_line.account_id
        (suspense_lines + invoice_line).reconcile()

    def _get_workbook_from_wizard(self, wizard):
        return load_workbook(io.BytesIO(base64.b64decode(wizard.file_data)), data_only=False)

    def _find_row_number(self, sheet, label):
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value == label:
                    return cell.row
        self.fail(f'Could not find row label {label!r}')

    def test_bank_vat_category_field_is_available_from_vat_pack(self):
        vat_category_field = self.env['account.bank.statement.line']._fields.get('vat_category')

        self.assertTrue(vat_category_field)
        self.assertEqual(vat_category_field.type, 'selection')
        self.assertEqual(
            vat_category_field.selection,
            [
                ('standard', 'Standard Rated Sales'),
                ('zero_rated', 'Zero Rated Sales'),
                ('exempt', 'Exempt Sales'),
                ('out_of_scope', 'Out of Scope'),
            ],
        )

    def test_invoice_sales_are_still_included(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (10.0, self.sale_tax),
                (15.0, self.sale_tax),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 0)
        invoice_row = sale_sections['standard_rated'][0]
        self.assertAlmostEqual(invoice_row[4], float(invoice.amount_untaxed or 0.0))
        self.assertAlmostEqual(invoice_row[6], abs(float(invoice.amount_untaxed_signed or 0.0)))
        self.assertAlmostEqual(invoice_row[8], abs(float(invoice.amount_total_signed or 0.0)))
        self.assertEqual(invoice_row[9], 'Not Paid')
        self.assertEqual(invoice_row[10], '')
        self.assertAlmostEqual(invoice_row[11], 0.0)
        self.assertAlmostEqual(invoice_row[12], abs(float(invoice.amount_total_signed or 0.0)))
        self.assertEqual(invoice_row[13], '')

    def test_sales_receipts_are_included(self):
        receipt = self._create_invoice(
            'out_receipt',
            [
                (25.0, self.sale_tax),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        receipt_row = sale_sections['standard_rated'][0]
        self.assertEqual(receipt_row[1], receipt.name or receipt.payment_reference or receipt.ref or '/')
        self.assertAlmostEqual(receipt_row[4], float(receipt.amount_untaxed or 0.0))
        self.assertAlmostEqual(receipt_row[8], abs(float(receipt.amount_total_signed or 0.0)))

    def test_mixed_sales_invoice_stays_in_sale_sheet(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (100.0, self.sale_tax),
                (30.0, []),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertFalse(purchase_rows)
        self.assertFalse(not_claimable_rows)

        sale_row = sale_sections['standard_rated'][0]
        self.assertEqual(sale_row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(sale_row[4], 100.0)
        self.assertAlmostEqual(sale_row[6], 100.0)
        self.assertAlmostEqual(sale_row[7], 5.0)
        self.assertAlmostEqual(sale_row[8], 105.0)

        zero_row = sale_sections['zero_rated'][0]
        self.assertEqual(zero_row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(zero_row[4], 30.0)
        self.assertAlmostEqual(zero_row[6], 30.0)
        self.assertAlmostEqual(zero_row[7], 0.0)
        self.assertAlmostEqual(zero_row[8], 30.0)

    def test_mixed_sales_refund_stays_in_sale_sheet(self):
        refund = self._create_invoice(
            'out_refund',
            [
                (100.0, self.sale_tax),
                (30.0, []),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertFalse(not_claimable_rows)

        sale_row = sale_sections['standard_rated'][0]
        self.assertAlmostEqual(sale_row[4], -100.0)
        self.assertAlmostEqual(sale_row[6], -100.0)
        self.assertAlmostEqual(sale_row[7], -5.0)
        self.assertAlmostEqual(sale_row[8], -105.0)

        zero_row = sale_sections['zero_rated'][0]
        self.assertAlmostEqual(zero_row[4], -30.0)
        self.assertAlmostEqual(zero_row[6], -30.0)
        self.assertAlmostEqual(zero_row[7], 0.0)
        self.assertAlmostEqual(zero_row[8], -30.0)

    def test_mixed_standard_and_zero_ex_sales_stay_in_sale_sheet(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (100.0, self.sale_tax),
                (30.0, self.zero_ex_sale_tax),
                (20.0, self.zero_ext_sale_tax),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertEqual(len(sale_sections['exempt']), 1)
        self.assertFalse(not_claimable_rows)

        sale_row = sale_sections['standard_rated'][0]
        self.assertEqual(sale_row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(sale_row[4], 100.0)
        self.assertAlmostEqual(sale_row[7], 5.0)
        self.assertAlmostEqual(sale_row[8], 105.0)

        zero_row = sale_sections['zero_rated'][0]
        self.assertAlmostEqual(zero_row[4], 20.0)
        self.assertAlmostEqual(zero_row[7], 0.0)
        self.assertAlmostEqual(zero_row[8], 20.0)

        exempt_row = sale_sections['exempt'][0]
        self.assertAlmostEqual(exempt_row[4], 30.0)
        self.assertAlmostEqual(exempt_row[7], 0.0)
        self.assertAlmostEqual(exempt_row[8], 30.0)

    def test_zero_rated_taxed_sales_stay_in_sale_sheet(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (75.0, self.zero_sale_tax),
                (25.0, self.zero_sale_tax),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertFalse(not_claimable_rows)
        row = sale_sections['zero_rated'][0]
        self.assertEqual(row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(row[4], 100.0)
        self.assertAlmostEqual(row[7], 0.0)
        self.assertAlmostEqual(row[8], 100.0)

    def test_pure_zero_ex_and_zero_ext_sales_stay_in_sale_sheet(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (90.0, self.zero_ex_sale_tax),
                (10.0, self.zero_ext_sale_tax),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertEqual(len(sale_sections['exempt']), 1)
        self.assertFalse(not_claimable_rows)
        zero_row = sale_sections['zero_rated'][0]
        self.assertEqual(zero_row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(zero_row[4], 10.0)
        self.assertAlmostEqual(zero_row[7], 0.0)
        self.assertAlmostEqual(zero_row[8], 10.0)

        exempt_row = sale_sections['exempt'][0]
        self.assertEqual(exempt_row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(exempt_row[4], 90.0)
        self.assertAlmostEqual(exempt_row[7], 0.0)
        self.assertAlmostEqual(exempt_row[8], 90.0)

    def test_pure_no_tax_sales_stay_in_sale_sheet(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (90.0, []),
                (10.0, []),
            ],
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertFalse(not_claimable_rows)
        row = sale_sections['zero_rated'][0]
        self.assertEqual(row[1], invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertAlmostEqual(row[4], 100.0)
        self.assertAlmostEqual(row[7], 0.0)
        self.assertAlmostEqual(row[8], 100.0)

    def test_standard_sale_rows_use_safe_net_vat_gross_formulas(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (100.0, self.sale_tax),
            ],
        )
        wizard = self._create_wizard()
        workbook = Workbook()
        workbook.remove(workbook.active)

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()
        wizard._write_sale_sheet(workbook, set(), sheet_name='Sale', sections=sale_sections)

        sheet = workbook['Sale']
        row = self._find_row_number(sheet, invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertEqual(sheet.cell(row=row, column=7).value, f'=E{row}*F{row}')
        self.assertEqual(sheet.cell(row=row, column=8).value, f'=G{row}*0.05')
        self.assertEqual(sheet.cell(row=row, column=9).value, f'=G{row}+H{row}')
        self.assertIsNone(sheet.cell(row=row, column=15).value)
        self.assertIsNone(sheet.cell(row=row, column=16).value)

    def test_zero_rated_sale_rows_use_zero_vat_formula(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (100.0, self.zero_sale_tax),
            ],
        )
        wizard = self._create_wizard()
        workbook = Workbook()
        workbook.remove(workbook.active)

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()
        wizard._write_sale_sheet(workbook, set(), sheet_name='Sale', sections=sale_sections)

        sheet = workbook['Sale']
        row = self._find_row_number(sheet, invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertEqual(sheet.cell(row=row, column=7).value, f'=E{row}*F{row}')
        self.assertEqual(sheet.cell(row=row, column=8).value, '=0')
        self.assertEqual(sheet.cell(row=row, column=9).value, f'=G{row}+H{row}')

    def test_mixed_sale_with_partial_vat_uses_split_safe_formulas(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (100.0, self.sale_tax),
                (30.0, []),
            ],
        )
        wizard = self._create_wizard()
        workbook = Workbook()
        workbook.remove(workbook.active)

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()
        wizard._write_sale_sheet(workbook, set(), sheet_name='Sale', sections=sale_sections)

        sheet = workbook['Sale']
        row = self._find_row_number(sheet, invoice.name or invoice.payment_reference or invoice.ref or '/')
        self.assertEqual(sheet.cell(row=row, column=7).value, f'=E{row}*F{row}')
        self.assertEqual(sheet.cell(row=row, column=8).value, f'=G{row}*0.05')
        self.assertEqual(sheet.cell(row=row, column=9).value, f'=G{row}+H{row}')

    def test_direct_bank_sales_land_in_all_four_sections(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-STANDARD',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        self._create_bank_statement_line(
            amount=50.0,
            vat_category='zero_rated',
            payment_ref='BANK-ZERO',
            counterpart_account=self.bank_sale_nature_account_international,
        )
        self._create_bank_statement_line(
            amount=40.0,
            vat_category='exempt',
            payment_ref='BANK-EXEMPT',
            counterpart_account=self.bank_sale_nature_account_related,
        )
        self._create_bank_statement_line(
            amount=30.0,
            vat_category='out_of_scope',
            payment_ref='BANK-OOS',
            counterpart_account=self.bank_sale_nature_account_uae,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertEqual(len(sale_sections['exempt']), 1)
        self.assertEqual(len(sale_sections['out_of_scope']), 1)

        standard_row = sale_sections['standard_rated'][0]
        self.assertEqual(standard_row[1], '')
        self.assertEqual(standard_row[2], 'BANK-STANDARD')
        self.assertAlmostEqual(standard_row[6], 100.0)
        self.assertAlmostEqual(standard_row[7], 5.0)
        self.assertAlmostEqual(standard_row[8], 105.0)
        self.assertEqual(standard_row[9], 'Paid')
        self.assertEqual(standard_row[10], self.date_from)
        self.assertAlmostEqual(standard_row[11], 105.0)
        self.assertAlmostEqual(standard_row[12], 0.0)
        self.assertEqual(standard_row[13], self.bank_journal.display_name)

        zero_row = sale_sections['zero_rated'][0]
        exempt_row = sale_sections['exempt'][0]
        out_of_scope_row = sale_sections['out_of_scope'][0]
        self.assertAlmostEqual(zero_row[7], 0.0)
        self.assertAlmostEqual(exempt_row[7], 0.0)
        self.assertAlmostEqual(out_of_scope_row[7], 0.0)

    def test_bank_line_reconciled_to_customer_invoice_is_excluded(self):
        invoice = self._create_invoice(
            'out_invoice',
            [
                (100.0, self.sale_tax),
            ],
        )
        statement_line = self._create_bank_statement_line(
            amount=float(invoice.amount_total or 0.0),
            vat_category='standard',
            payment_ref='INVOICE-RECEIPT',
        )
        self._reconcile_statement_line_to_invoice(statement_line, invoice)
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertTrue(
            all(row[2] != 'INVOICE-RECEIPT' for row in sale_sections['standard_rated'])
        )

    def test_bank_sale_with_revenue_and_vat_output_is_standard_rated(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='zero_rated',
            payment_ref='BANK-OUTPUT-VAT',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 0)
        row = sale_sections['standard_rated'][0]
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-OUTPUT-VAT')
        self.assertAlmostEqual(row[6], 100.0)
        self.assertAlmostEqual(row[7], 5.0)
        self.assertAlmostEqual(row[8], 105.0)

    def test_bank_sale_with_revenue_only_is_zero_rated_when_not_marked_standard(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='zero_rated',
            payment_ref='BANK-REVENUE-ONLY',
            counterpart_account=self.bank_sale_nature_account_uae,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 0)
        self.assertEqual(len(sale_sections['zero_rated']), 1)
        row = sale_sections['zero_rated'][0]
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-REVENUE-ONLY')
        self.assertAlmostEqual(row[6], 105.0)
        self.assertAlmostEqual(row[7], 0.0)
        self.assertAlmostEqual(row[8], 105.0)

    def test_bank_sale_marked_standard_is_standard_rated_without_vat_move_line(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-MARKED-STANDARD',
            counterpart_account=self.bank_sale_nature_account_uae,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 0)
        row = sale_sections['standard_rated'][0]
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-MARKED-STANDARD')
        self.assertAlmostEqual(row[6], 100.0)
        self.assertAlmostEqual(row[7], 5.0)
        self.assertAlmostEqual(row[8], 105.0)

    def test_negative_bank_sale_reduces_sale_totals(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-POSITIVE',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        self._create_bank_statement_line(
            amount=-52.5,
            vat_category='standard',
            payment_ref='BANK-REFUND',
            counterpart_account=self.bank_sale_nature_account_international,
            vat_output_account=self.output_vat_account,
            vat_amount=2.5,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        rows = sale_sections['standard_rated']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][9], 'Paid')
        self.assertEqual(rows[1][9], 'Refund')
        self.assertAlmostEqual(sum(row[6] for row in rows), 50.0)
        self.assertAlmostEqual(sum(row[7] for row in rows), 2.5)
        self.assertAlmostEqual(sum(row[8] for row in rows), 52.5)

    def test_bank_sale_uses_odoo_currency_rate_when_available(self):
        foreign_currency = self._make_currency('XRT', 'XRT')
        self._create_currency_rate(foreign_currency, 1.2)
        self._create_bank_statement_line(
            amount=210.0,
            amount_currency=200.0,
            foreign_currency=foreign_currency,
            vat_category='standard',
            payment_ref='BANK-FX-ODOO',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=10.0,
        )
        wizard = self._create_wizard()
        company_currency = self.env.company.currency_id

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        row = sale_sections['standard_rated'][0]
        expected_gross = company_currency.round(200.0 * 1.2)
        expected_net = company_currency.round(expected_gross / 1.05)
        expected_vat = company_currency.round(expected_gross - expected_net)
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-FX-ODOO')
        self.assertAlmostEqual(row[4], 200.0)
        self.assertAlmostEqual(row[5], 1.2)
        self.assertAlmostEqual(row[6], expected_net)
        self.assertAlmostEqual(row[7], expected_vat)
        self.assertAlmostEqual(row[8], expected_gross)
        self.assertEqual(row[9], 'Paid')

    def test_bank_sale_refund_uses_odoo_currency_rate_when_available(self):
        foreign_currency = self._make_currency('XRF', 'XRF')
        self._create_currency_rate(foreign_currency, 1.2)
        self._create_bank_statement_line(
            amount=-105.0,
            amount_currency=-100.0,
            foreign_currency=foreign_currency,
            vat_category='standard',
            payment_ref='BANK-FX-REFUND',
            counterpart_account=self.bank_sale_nature_account_international,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        wizard = self._create_wizard()
        company_currency = self.env.company.currency_id

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        row = sale_sections['standard_rated'][0]
        expected_gross = company_currency.round(-100.0 * 1.2)
        expected_net = company_currency.round(expected_gross / 1.05)
        expected_vat = company_currency.round(expected_gross - expected_net)
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-FX-REFUND')
        self.assertAlmostEqual(row[4], -100.0)
        self.assertAlmostEqual(row[5], 1.2)
        self.assertAlmostEqual(row[6], expected_net)
        self.assertAlmostEqual(row[7], expected_vat)
        self.assertAlmostEqual(row[8], expected_gross)
        self.assertEqual(row[9], 'Refund')

    def test_bank_sale_falls_back_to_booked_ratio_when_no_odoo_rate_exists(self):
        foreign_currency = self._make_currency('XRB', 'XRB')
        self._create_currency_rate(
            foreign_currency,
            1.8,
            date=fields.Date.from_string('2025-04-15'),
        )
        self._create_bank_statement_line(
            amount=126.0,
            amount_currency=100.0,
            foreign_currency=foreign_currency,
            vat_category='zero_rated',
            payment_ref='BANK-FX-FALLBACK',
            counterpart_account=self.bank_sale_nature_account_related,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        row = sale_sections['zero_rated'][0]
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-FX-FALLBACK')
        self.assertAlmostEqual(row[4], 100.0)
        self.assertAlmostEqual(row[5], 1.26)
        self.assertAlmostEqual(row[6], 126.0)
        self.assertAlmostEqual(row[7], 0.0)
        self.assertAlmostEqual(row[8], 126.0)
        self.assertEqual(row[9], 'Paid')

    def test_company_currency_bank_sale_keeps_exchange_rate_one(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-COMPANY-CURRENCY',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        row = sale_sections['standard_rated'][0]
        self.assertEqual(row[1], '')
        self.assertEqual(row[2], 'BANK-COMPANY-CURRENCY')
        self.assertAlmostEqual(row[4], 105.0)
        self.assertAlmostEqual(row[5], 1.0)
        self.assertAlmostEqual(row[6], 100.0)
        self.assertAlmostEqual(row[7], 5.0)
        self.assertAlmostEqual(row[8], 105.0)
        self.assertEqual(row[9], 'Paid')

    def test_sale_sheet_grand_totals_sum_all_sections(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-STANDARD',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        self._create_bank_statement_line(
            amount=50.0,
            vat_category='zero_rated',
            payment_ref='BANK-ZERO',
            counterpart_account=self.bank_sale_nature_account_international,
        )
        self._create_bank_statement_line(
            amount=40.0,
            vat_category='exempt',
            payment_ref='BANK-EXEMPT',
            counterpart_account=self.bank_sale_nature_account_related,
        )
        self._create_bank_statement_line(
            amount=30.0,
            vat_category='out_of_scope',
            payment_ref='BANK-OOS',
            counterpart_account=self.bank_sale_nature_account_uae,
        )
        wizard = self._create_wizard()
        workbook = Workbook()
        workbook.remove(workbook.active)
        used_sheet_names = set()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()
        wizard._write_sale_sheet(
            workbook,
            used_sheet_names,
            sheet_name='Sale',
            sections=sale_sections,
        )

        sheet = workbook['Sale']
        grand_total_row = self._find_row_number(sheet, 'Grand total')
        total_rows = [
            cell.row
            for cell in sheet['B']
            if cell.value == 'Total'
        ]
        self.assertEqual(
            sheet.cell(row=grand_total_row, column=7).value,
            '=' + '+'.join(f'G{row}' for row in total_rows),
        )
        self.assertEqual(
            sheet.cell(row=grand_total_row, column=8).value,
            '=' + '+'.join(f'H{row}' for row in total_rows),
        )
        self.assertEqual(
            sheet.cell(row=grand_total_row, column=9).value,
            '=' + '+'.join(f'I{row}' for row in total_rows),
        )

    def test_direct_bank_sales_require_allowed_revenue_nature(self):
        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-ALLOWED',
            counterpart_account=self.bank_sale_nature_account_uae,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        self._create_bank_statement_line(
            amount=50.0,
            vat_category='zero_rated',
            payment_ref='BANK-BLOCKED',
            counterpart_account=self.bank_sale_non_revenue_account,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(sale_sections['standard_rated'][0][1], '')
        self.assertEqual(sale_sections['standard_rated'][0][2], 'BANK-ALLOWED')
        self.assertEqual(len(sale_sections['zero_rated']), 0)

    def test_direct_bank_sales_with_named_revenue_natures_are_included(self):
        bank_sale_nature_account_uae_alias = self._make_account(
            '41030102',
            'Revenue UAE Client',
        )
        bank_sale_nature_account_international_alias = self._make_account(
            '41030103',
            'Revenue International Client',
        )
        bank_sale_nature_account_related_alias = self._make_account(
            '41030104',
            'Related Party Revenue',
        )

        self._create_bank_statement_line(
            amount=105.0,
            vat_category='standard',
            payment_ref='BANK-UAE-ALIAS',
            counterpart_account=bank_sale_nature_account_uae_alias,
            vat_output_account=self.output_vat_account,
            vat_amount=5.0,
        )
        self._create_bank_statement_line(
            amount=50.0,
            vat_category='zero_rated',
            payment_ref='BANK-INTL-ALIAS',
            counterpart_account=bank_sale_nature_account_international_alias,
        )
        self._create_bank_statement_line(
            amount=-40.0,
            vat_category='exempt',
            payment_ref='BANK-RELATED-ALIAS',
            counterpart_account=bank_sale_nature_account_related_alias,
        )
        wizard = self._create_wizard()

        sale_sections, _purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(sale_sections['standard_rated']), 1)
        self.assertEqual(len(sale_sections['zero_rated']), 1)
        self.assertEqual(len(sale_sections['exempt']), 1)
        self.assertEqual(sale_sections['standard_rated'][0][1], '')
        self.assertEqual(sale_sections['standard_rated'][0][2], 'BANK-UAE-ALIAS')
        self.assertEqual(sale_sections['zero_rated'][0][1], '')
        self.assertEqual(sale_sections['zero_rated'][0][2], 'BANK-INTL-ALIAS')
        self.assertEqual(sale_sections['exempt'][0][1], '')
        self.assertEqual(sale_sections['exempt'][0][2], 'BANK-RELATED-ALIAS')
        self.assertEqual(sale_sections['exempt'][0][9], 'Refund')

    def test_direct_bank_purchase_with_vat_input_is_included_in_purchases(self):
        self._create_bank_statement_line(
            amount=-105.0,
            vat_category='zero_rated',
            payment_ref='BANK-PURCHASE-VAT-INPUT',
            counterpart_account=self.bank_purchase_expense_account,
            vat_input_account=self.input_vat_account,
            vat_input_amount=5.0,
        )
        wizard = self._create_wizard()

        sale_sections, purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertFalse(any(sale_sections.values()))
        self.assertEqual(len(purchase_rows), 1)
        self.assertEqual(len(not_claimable_rows), 0)
        row = purchase_rows[0]
        self.assertEqual(row[0], '')
        self.assertEqual(row[1], 'BANK-PURCHASE-VAT-INPUT')
        self.assertAlmostEqual(row[3], 105.0)
        self.assertAlmostEqual(row[4], 1.0)
        self.assertAlmostEqual(row[5], 100.0)
        self.assertAlmostEqual(row[6], 5.0)
        self.assertAlmostEqual(row[7], 105.0)
        self.assertEqual(row[8], 'Paid')
        self.assertEqual(row[9], self.date_from)
        self.assertAlmostEqual(row[10], 105.0)
        self.assertAlmostEqual(row[11], 0.0)
        self.assertEqual(row[12], self.bank_journal.display_name)

    def test_direct_bank_purchase_without_vat_input_is_excluded_from_not_claimable(self):
        self._create_bank_statement_line(
            amount=-100.0,
            vat_category='zero_rated',
            payment_ref='BANK-PURCHASE-NO-VAT',
            counterpart_account=self.bank_purchase_expense_account,
        )
        wizard = self._create_wizard()

        sale_sections, purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertFalse(any(sale_sections.values()))
        self.assertEqual(len(purchase_rows), 0)
        self.assertEqual(len(not_claimable_rows), 0)

    def test_direct_bank_purchase_vat_rows_use_gross_inclusive_formulas(self):
        self._create_bank_statement_line(
            amount=-105.0,
            vat_category='zero_rated',
            payment_ref='BANK-PURCHASE-FORMULA',
            counterpart_account=self.bank_purchase_expense_account,
            vat_input_account=self.input_vat_account,
            vat_input_amount=5.0,
        )
        wizard = self._create_wizard()
        workbook = Workbook()
        workbook.remove(workbook.active)

        _sale_sections, purchase_rows, _not_claimable_rows = wizard._build_vat_working_rows()
        wizard._write_vat_working_sheet(
            workbook,
            set(),
            sheet_name='Purchases',
            title='Purchases',
            subtitle='VAT Working',
            section_label='Purchases',
            headers=wizard._get_vat_working_headers(),
            rows=purchase_rows,
        )

        sheet = workbook['Purchases']
        row = self._find_row_number(sheet, 'BANK-PURCHASE-FORMULA')
        self.assertEqual(sheet.cell(row=row, column=7).value, f'=I{row}/1.05')
        self.assertEqual(sheet.cell(row=row, column=8).value, f'=I{row}-G{row}')
        self.assertEqual(sheet.cell(row=row, column=9).value, f'=E{row}*F{row}')

    def test_not_claimable_purchase_rows_use_zero_vat_formula(self):
        bill = self._create_invoice(
            'in_invoice',
            [
                (100.0, []),
            ],
        )
        wizard = self._create_wizard()
        workbook = Workbook()
        workbook.remove(workbook.active)

        _sale_sections, _purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()
        wizard._write_vat_working_sheet(
            workbook,
            set(),
            sheet_name='Not Claimable',
            title='Not Claimable',
            subtitle='VAT Working',
            section_label='Not Claimable',
            headers=wizard._get_vat_working_headers(partner_label='Partner Name'),
            rows=not_claimable_rows,
        )

        sheet = workbook['Not Claimable']
        row = self._find_row_number(sheet, bill.name or bill.payment_reference or bill.ref or '/')
        self.assertEqual(sheet.cell(row=row, column=7).value, f'=E{row}*F{row}')
        self.assertEqual(sheet.cell(row=row, column=8).value, '=0')
        self.assertEqual(sheet.cell(row=row, column=9).value, f'=G{row}+H{row}')

    def test_purchase_not_claimable_rows_still_come_from_purchase_lines(self):
        bill = self._create_invoice(
            'in_invoice',
            [
                (100.0, self.purchase_tax),
                (50.0, self.purchase_tax),
                (30.0, []),
                (20.0, []),
            ],
        )
        wizard = self._create_wizard()

        _sale_sections, purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(purchase_rows), 1)
        self.assertEqual(len(not_claimable_rows), 1)
        self.assertEqual(purchase_rows[0][1], bill.name or bill.payment_reference or bill.ref or '/')
        self.assertAlmostEqual(purchase_rows[0][4], 150.0)
        self.assertEqual(not_claimable_rows[0][1], bill.name or bill.payment_reference or bill.ref or '/')
        self.assertAlmostEqual(not_claimable_rows[0][4], 50.0)

    def test_purchase_refund_reduces_purchase_and_not_claimable_totals(self):
        refund = self._create_invoice(
            'in_refund',
            [
                (100.0, self.purchase_tax),
                (30.0, []),
            ],
        )
        wizard = self._create_wizard()

        _sale_sections, purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(purchase_rows), 1)
        self.assertEqual(len(not_claimable_rows), 1)

        purchase_row = purchase_rows[0]
        self.assertEqual(purchase_row[1], refund.name or refund.payment_reference or refund.ref or '/')
        self.assertAlmostEqual(purchase_row[4], -100.0)
        self.assertAlmostEqual(purchase_row[6], -100.0)
        self.assertAlmostEqual(purchase_row[7], -5.0)
        self.assertAlmostEqual(purchase_row[8], -105.0)

        not_claimable_row = not_claimable_rows[0]
        self.assertEqual(not_claimable_row[1], refund.name or refund.payment_reference or refund.ref or '/')
        self.assertAlmostEqual(not_claimable_row[4], -30.0)
        self.assertAlmostEqual(not_claimable_row[6], -30.0)
        self.assertAlmostEqual(not_claimable_row[7], 0.0)
        self.assertAlmostEqual(not_claimable_row[8], -30.0)

    def test_purchase_bill_with_multiple_taxed_lines_shows_once_in_purchases(self):
        bill = self._create_invoice(
            'in_invoice',
            [
                (100.0, self.purchase_tax),
                (40.0, self.purchase_tax),
                (10.0, self.purchase_tax),
            ],
        )
        wizard = self._create_wizard()

        _sale_sections, purchase_rows, not_claimable_rows = wizard._build_vat_working_rows()

        self.assertEqual(len(purchase_rows), 1)
        self.assertFalse(not_claimable_rows)
        row = purchase_rows[0]
        self.assertEqual(row[1], bill.name or bill.payment_reference or bill.ref or '/')
        self.assertAlmostEqual(row[4], 150.0)
        self.assertAlmostEqual(row[6], 150.0)
        self.assertAlmostEqual(row[7], 7.5)
        self.assertAlmostEqual(row[8], 157.5)

    def test_action_generate_excel_pack_handles_no_eligible_bank_lines(self):
        wizard = self._create_wizard()

        action = wizard.action_generate_excel_pack()

        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertTrue(wizard.file_data)

        workbook = self._get_workbook_from_wizard(wizard)
        self.assertEqual(workbook.sheetnames, ['Sale', 'Purchases', 'Not Claimable'])
        sale_sheet = workbook['Sale']
        self.assertEqual(sale_sheet['A4'].value, 'Standard Rated Sales')
        self.assertEqual(sale_sheet['A5'].value, 'Date')
        self.assertEqual(sale_sheet['B5'].value, 'Inv.No')
        self.assertEqual(sale_sheet['C5'].value, 'Client Name')
        self.assertEqual(sale_sheet['K5'].value, 'Payment Date')
        self.assertEqual(sale_sheet['L5'].value, 'Payment Made')
        self.assertEqual(sale_sheet['M5'].value, 'Payment Due')
        self.assertEqual(sale_sheet['N5'].value, 'Bank Name')
        self.assertIsNone(sale_sheet['O5'].value)
        self.assertIsNone(sale_sheet['P5'].value)
        self.assertIsNotNone(self._find_row_number(sale_sheet, 'Zero Rated Sales'))
        self.assertIsNotNone(self._find_row_number(sale_sheet, 'Exempt Sales'))
        self.assertIsNotNone(self._find_row_number(sale_sheet, 'Out of Scope'))
        purchase_sheet = workbook['Purchases']
        self.assertEqual(purchase_sheet['A5'].value, 'Date')
        self.assertEqual(purchase_sheet['B5'].value, 'Inv No')
        self.assertEqual(purchase_sheet['C5'].value, 'Vendor Name')
        self.assertEqual(purchase_sheet['D5'].value, 'Currency')
        self.assertEqual(purchase_sheet['E5'].value, 'Amount')
        self.assertEqual(purchase_sheet['F5'].value, 'Exchange Rate')
        self.assertEqual(purchase_sheet['G5'].value, 'Net')
        self.assertEqual(purchase_sheet['H5'].value, 'VAT')
        self.assertEqual(purchase_sheet['I5'].value, 'Gross')
        self.assertEqual(purchase_sheet['J5'].value, 'Status')
        self.assertEqual(purchase_sheet['K5'].value, 'Payment Date')
        self.assertEqual(purchase_sheet['L5'].value, 'Payment Made')
        self.assertEqual(purchase_sheet['M5'].value, 'Payment Due')
        self.assertEqual(purchase_sheet['N5'].value, 'Bank Name')
        self.assertEqual(purchase_sheet['O5'].value, 'TRN Number')
        self.assertEqual(purchase_sheet['P5'].value, 'Company Name')
        not_claimable_sheet = workbook['Not Claimable']
        self.assertEqual(not_claimable_sheet['C5'].value, 'Partner Name')
        self.assertEqual(not_claimable_sheet['O5'].value, 'TRN Number')
        self.assertEqual(not_claimable_sheet['P5'].value, 'Company Name')
    def test_vendor_bill_compliance_fields_from_vat_pack(self):
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': self.date_from,
            'has_trn': 'yes',
            'has_company_name': 'simplify',
        })
        self.assertEqual(move.has_trn, 'yes')
        self.assertEqual(move.has_company_name, 'simplify')
