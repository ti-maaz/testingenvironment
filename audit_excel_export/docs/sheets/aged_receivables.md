# Aged Receivables (Sheet)

This sheet is now taken from Odoo's native Aged Receivable XLSX export.

## Data source
- Report: `account_reports.aged_receivable_report`
- Export API used: `report.export_to_xlsx(options)`
- The first worksheet from the exported workbook is copied into the audit export workbook as `Aged Receivables`.

## Filters applied (from wizard)
- Companies: `company_ids` (`allowed_company_ids` context)
- As-of date: `aged_as_of_date` (`custom` / `single`)
- Journals: `journal_ids`
- Partners: `partner_ids`
- Analytic accounts: `analytic_account_ids`
- Include draft entries: `include_draft_entries`
- Unfold all: `unfold_all`
- Hide zero lines: `hide_zero_lines`
- Aging behavior: `aging_based_on`, `aging_interval`, `show_currency`, `show_account`
- Optional JSON override: `aged_receivable_options_json`

## Output behavior
- Layout and headers follow native Odoo Aged Receivable XLSX output.
- Grouping/subtotals, formatting, merged cells, and report presentation are preserved via sheet copy.
- This replaces the previous custom fixed/dynamic aged table builder for this sheet.
