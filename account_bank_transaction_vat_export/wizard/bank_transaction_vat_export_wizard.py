import base64
import io
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class BankTransactionVatExportWizard(models.TransientModel):
    _name = 'bank.transaction.vat.export.wizard'
    _description = 'Bank Transaction VAT Export Wizard'

    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    journal_ids = fields.Many2many('account.journal', string='Bank Journals', 
                                    domain=[('type', '=', 'bank')], required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def action_export(self):
        self.ensure_one()
        
        # Search for bank statement lines
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('journal_id', 'in', self.journal_ids.ids),
            ('state', '=', 'posted'),
        ]
        lines = self.env['account.bank.statement.line'].search(domain, order='date asc')
        
        if not lines:
            raise UserError(_('No transactions found for the selected criteria.'))

        output = io.BytesIO()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter library is not installed.'))

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('VAT Working')

        # Formats
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'font_size': 14})
        section_header_format = workbook.add_format({'bold': True, 'font_color': 'red', 'font_size': 12})
        table_header_format = workbook.add_format({'bold': True, 'bg_color': '#002060', 'font_color': 'white', 'border': 1, 'align': 'center'})
        data_format = workbook.add_format({'border': 1})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
        total_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '#,##0.00', 'bg_color': '#F2F2F2'})
        grand_total_format = workbook.add_format({'bold': True, 'num_format': '#,##0.00'})

        # Header
        sheet.merge_range('A1:N1', self.company_id.name, header_format)
        sheet.merge_range('A2:N2', 'VAT Working', header_format)
        sheet.merge_range('A3:N3', f'Quarter Ended {self.date_to.strftime("%d %B %Y")}', header_format)

        columns = [
            'Date', 'Inv.No', 'Description', 'Currency', 'Amount', 
            'Exchange Rate', 'Net', 'VAT', 'Gross', 'Status', 
            'Payment Date', 'Payment Made', 'Payment Due', 'Bank Name'
        ]
        
        row = 5
        
        categories = [
            ('standard', 'Standard Rated Sales'),
            ('zero_rated', 'Zero Rated Sales'),
            ('exempt', 'Exempt Sales'),
            ('out_of_scope', 'Out of Scope'),
        ]

        grand_net = 0.0
        grand_vat = 0.0
        grand_gross = 0.0

        for cat_key, cat_name in categories:
            cat_lines = lines.filtered(lambda l: l.vat_category == cat_key)
            
            # Section Header
            sheet.write(row, 0, cat_name, section_header_format)
            row += 1
            
            # Table Headers
            for col, title in enumerate(columns):
                sheet.write(row, col, title, table_header_format)
            row += 1
            
            section_net = 0.0
            section_vat = 0.0
            section_gross = 0.0
            
            for line in cat_lines:
                # Basic values
                date_str = line.date.strftime('%Y-%m-%d')
                inv_no = line.payment_ref or ''
                description = line.payment_ref or line.name or ''
                currency = line.currency_id.name or self.company_id.currency_id.name
                amount_currency = line.amount_currency if line.currency_id else line.amount
                
                # Exchange Rate calculation
                # Odoo's amount is in company currency, amount_currency is in line currency
                # Rate = Amount / Amount Currency
                rate = 1.0
                if line.currency_id and line.currency_id != self.company_id.currency_id:
                    if amount_currency != 0:
                        rate = abs(line.amount / amount_currency)
                
                # For VAT report, we usually show positive numbers for sales
                # Bank statement lines: positive is money in (sale), negative is money out (refund)
                is_refund = line.amount < 0
                status = 'Refund' if is_refund else 'Paid'
                
                # Values in company currency
                gross = abs(line.amount)
                
                # VAT Calculation logic
                vat_rate = 0.05 if cat_key == 'standard' else 0.0
                net = gross / (1 + vat_rate)
                vat = gross - net
                
                sheet.write(row, 0, date_str, data_format)
                sheet.write(row, 1, inv_no, data_format)
                sheet.write(row, 2, description, data_format)
                sheet.write(row, 3, currency, data_format)
                sheet.write(row, 4, abs(amount_currency), num_format)
                sheet.write(row, 5, rate, num_format)
                sheet.write(row, 6, net, num_format)
                sheet.write(row, 7, vat, num_format)
                sheet.write(row, 8, gross, num_format)
                sheet.write(row, 9, status, data_format)
                sheet.write(row, 10, date_str, data_format)
                sheet.write(row, 11, '', data_format) # Payment Made
                sheet.write(row, 12, '', data_format) # Payment Due
                sheet.write(row, 13, line.journal_id.name, data_format)
                
                section_net += net
                section_vat += vat
                section_gross += gross
                row += 1

            # Section Totals
            sheet.write(row, 5, 'Total', workbook.add_format({'bold': True, 'align': 'right'}))
            sheet.write(row, 6, section_net, total_format)
            sheet.write(row, 7, section_vat, total_format)
            sheet.write(row, 8, section_gross, total_format)
            row += 2 # Space between sections
            
            grand_net += section_net
            grand_vat += section_vat
            grand_gross += section_gross

        # Grand Totals
        row += 1
        sheet.write(row, 5, 'Grand total', workbook.add_format({'bold': True, 'align': 'right'}))
        sheet.write(row, 6, grand_net, grand_total_format)
        sheet.write(row, 7, grand_vat, grand_total_format)
        sheet.write(row, 8, grand_gross, grand_total_format)

        # Column widths
        sheet.set_column('A:A', 12)
        sheet.set_column('B:B', 15)
        sheet.set_column('C:C', 40)
        sheet.set_column('D:D', 10)
        sheet.set_column('E:I', 15)
        sheet.set_column('J:J', 10)
        sheet.set_column('K:N', 15)

        workbook.close()
        output.seek(0)
        
        file_name = f'VAT_Working_{self.date_to.strftime("%Y%m%d")}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
