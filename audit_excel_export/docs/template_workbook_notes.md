# Template Workbook Integration Notes

## Template Source Resolution
- The export loads a real workbook template file and reuses its native formatting/layout.
- The template is bundled in-module at:
  - `Custom/audit_excel_export/data/afs_excel_template.xlsx`
- The bundled file is a slimmed workbook containing only the required formatted template tabs to keep memory usage stable at runtime.

## Formula/Style Preservation Method
- Template sheets are copied from the source workbook without rebuilding styles in Python.
- Renamed tabs (`SUMMARY`→`Summary Sheet`, `SoFP`→`SOFP`, `SoCI`→`SOCI`, `SoCE`→`SOCE`, `SoCF`→`SOCF`) have formula and defined-name references rewritten to keep links valid.
- `General Ledger`, `Customer Invoices`, `Vendor Bills`, `Aged Receivables`, `Aged Payables`, and `Trial Balance` are copied from native XLSX exports.
- Customer/Vendor sheets come from module-defined `account.report` variants and are copied the same way as standard reports.

## Sample-Figure Cleanup Policy
- Cleanup stage runs for template-style sheets except `Trial Balance`.
- Formula cells are preserved.
- Static numeric/date/boolean placeholder values are cleared so non-TB sheets stay free of sample figures.

## Template Population Rule
- The `Trial Balance` tab now uses native Odoo XLSX output from `account_reports.trial_balance_report`.
- `Client Details` is populated from wizard/company context (client name, period dates, and available registration/profile fields).
- `Share Capital` is populated when shareholder fields exist on the selected company.
- Other template-style sheets remain formula/layout driven and are not directly business-populated.
