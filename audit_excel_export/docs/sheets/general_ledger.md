# General Ledger (Sheet)

This sheet is generated from Odoo's own General Ledger XLSX exporter instead of a custom table layout.

## Data source
- Report: `account_reports.general_ledger_report`
- Export API used: `report.export_to_xlsx(options)`
- In the returned workbook, the first worksheet (`General Ledger`) is copied into the audit export workbook.

## Filters applied (from wizard)
- Companies: `company_ids` (via `allowed_company_ids` context)
- Date range: `date_from` to `date_to` (`custom` / `range`)
- Journals: `journal_ids`
- Partners: `partner_ids`
- Analytic accounts: `analytic_account_ids`
- Include draft entries: `include_draft_entries`
- Unfold all: `unfold_all`
- Hide zero lines: `hide_zero_lines`
- Optional JSON override: `gl_options_json`

## Output behavior
- The sheet structure, line hierarchy, and grouping follow native Odoo General Ledger XLSX output.
- Account headers, detail rows (including labels like `Initial Balance`), totals, and native number/date formatting are preserved.
- Styles and merged cells from Odoo XLSX are copied to keep the visual layout consistent.
- A post-copy narration cleaner can rewrite noisy detail-row labels in the `Account Name` column.
  - Target rows: detail rows with empty `Code`, excluding `Initial Balance`, `Total*`, and `Load more...`.
  - The original raw narration is preserved as an Excel cell comment (`Raw narration: ...`).
  - Debit/Credit/Balance and other columns are not altered.

## Notes
- The native Odoo export includes a `Filters` sheet; this module currently copies only the `General Ledger` worksheet.
- Other native-copy sheets: `Customer Invoices`, `Vendor Bills`, `Aged Receivables`, `Aged Payables`, `Trial Balance`.
- Cleaner toggle (system parameter): `audit_excel_export.gl_narration_cleaner_enabled`
  - Disabled only when set to false-like values: `0`, `false`, `no`, `off`.
