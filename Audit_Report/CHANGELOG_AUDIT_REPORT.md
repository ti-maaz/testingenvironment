# Audit_Report Module Changelog

This file tracks simple code-change summaries for `Custom/Audit_Report` only.
## 2026-02-24 16:36:37
- Stage: start
- Summary: Start changelog tracking for Audit_Report module
## 2026-02-24 16:36:37
- Stage: change
- Summary: Updated retained earnings rollforward and SOCE statutory transfer labeling
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-24 16:42:03
- Stage: change
- Summary: Removed before-tax bottom amount lines when corporate tax provision line is shown in PnL
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-24 16:47:20
- Stage: change
- Summary: Removed statutory reserve note reference from balance sheet and moved statutory reserve line below total comprehensive in SOCE/retained earnings notes.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-24 16:49:25
- Stage: change
- Summary: Normalized retained earnings note block structure while keeping statutory-reserve row below total comprehensive and above dividend.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-24 18:52:55
- Stage: change
- Summary: Merged Stripe/other wallets into prepayment receivables presentation and removed standalone Stripe line from statement/financial-assets note output.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-25 10:25:24
- Stage: change
- Summary: Updated receivable line-label logic so Stripe/other wallets (1205) are recognized under "Other receivables" instead of showing only "Prepayment" when wallets exist.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 10:31:32
- Stage: change
- Summary: Excluded VAT receivable (120304) and VAT payable (220302, including VAT input/output subaccounts) from financial assets and liabilities note table line totals and grand totals.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
## 2026-02-25 10:35:27
- Stage: change
- Summary: Kept entity information city on same line as street by binding city after comma in address output.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_style.css
## 2026-02-25 10:39:09
- Stage: change
- Summary: Made entity-information street and city render as one non-breaking address segment to prevent city wrapping onto next line.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_style.css
## 2026-02-25 10:43:36
- Stage: change
- Summary: Re-enabled wrapping for entity information office address and removed no-wrap constraints on city/country segments.
- Files:
  - Custom/Audit_Report/templates/audit_report_style.css
## 2026-02-25 10:52:07
- Stage: change
- Summary: Kept address wrapping enabled but prevented city and country phrase splitting by making those segments non-breaking.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_style.css
## 2026-02-25 10:57:41
- Stage: change
- Summary: Restricted corporate-tax-liability-paid checkbox impact to cash-flow tax-paid line only.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 11:15:45
- Stage: change
- Summary: Adjusted SOCE first balance retained earnings to use opening carry-forward from prior closing and movements.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 12:15:45
- Stage: change
- Summary: Improved trial-balance overrides UI with compact layout, clearer actions, and better column spacing.
- Files:
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/__manifest__.py
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-02-25 12:16:39
- Stage: change
- Summary: Hardened trial-balance override SCSS selectors to apply reliably in Odoo form rendering.
- Files:
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-02-25 12:28:46
- Stage: change
- Summary: SOCE first opening balance retained earnings now sources account 31010102 instead of 31010203.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 12:34:57
- Stage: change
- Summary: Reverted SOCE opening retained-earnings source change and restored previous carry-forward logic.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 12:50:38
- Stage: change
- Summary: Swapped retained-earnings display logic between first and second SOCE opening balance rows, with totals adjusted accordingly.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 13:15:41
- Stage: change
- Summary: Moved SOCE opening-balance retained-earnings swap into core calculation logic and removed display-only swap layer.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 14:16:17
- Stage: change
- Summary: Made middle SOCE balance row a subtotal carry-forward of prior opening plus comparative movements across equity columns.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 14:23:26
- Stage: change
- Summary: Aligned prior-year retained earnings with middle SOCE subtotal carry-forward so both use the same value.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 15:46:24
- Stage: change
- Summary: Applied account-level half-up rounding before report calculations so totals/subtotals are sums of rounded values, including override-adjusted rows.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-25 15:57:35
- Stage: change
- Summary: Added explicit half_up_down rounding rule and routed report amount rounding through it.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-02-26 11:11:04
- Stage: change
- Summary: Retained earnings notes now pull statutory reserves directly from account 31010301 (not SOCE-derived values).
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-26 11:13:33
- Stage: change
- Summary: Retained earnings note now shows statutory reserve yearly movement values instead of end balances.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-26 11:33:31
- Stage: change
- Summary: Formatted negative statutory reserve SOCE amount-line values with parentheses for current and prior columns.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-26 11:34:40
- Stage: change
- Summary: Retained earnings note now always displays statutory reserve movements in parentheses for current and prior columns.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
## 2026-02-27 15:29:38
- Stage: change
- Summary: Kept SOCE owner-current-account movement label on one line across 3/4/5/6-column layouts.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/views/audit_report_template_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_style.css
## 2026-02-27 15:34:40
- Stage: change
- Summary: Forced TB override wizard reopen in edit mode and enabled inline edit on TB override lists.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/models/audit_report_document.py
  - Custom/Audit_Report/views/views.xml
## 2026-02-27 15:43:43
- Stage: change
- Summary: Fixed 2-year TB override editability by using separate current/prior one2many fields in wizard view.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/views/views.xml
## 2026-03-01 15:01:00
- Stage: start
- Summary: Start: simplify revision wizard and editor UX
## 2026-03-01 15:01:00
- Stage: change
- Summary: Simplified revision editor UX with friendlier labels, a table picker flow, and removed the technical table index tab from revision form.
- Files:
  - Custom/Audit_Report/controllers/main.py
  - Custom/Audit_Report/views/views.xml
## 2026-03-01 15:01:38
- Stage: change
- Summary: Aligned remaining revision helper text/tooltips to the new Visual Editor naming.
- Files:
  - Custom/Audit_Report/controllers/main.py
  - Custom/Audit_Report/views/views.xml
## 2026-03-01 15:02:01
- Stage: change
- Summary: Removed obsolete structured-editor sidebar styles after switching to the new table picker layout.
- Files:
  - Custom/Audit_Report/controllers/main.py
## 2026-03-01 15:09:07
- Stage: change
- Summary: Restored structured editor sidebar table selection and original editor wording; kept revision wizard/modal label updates.
- Files:
  - Custom/Audit_Report/controllers/main.py
## 2026-03-02 10:46:21
- Stage: start
- Summary: Start: add manual date options for signature placeholders
## 2026-03-02 10:46:21
- Stage: change
- Summary: Added signature placeholder date source options (today/report end/manual date) with wizard controls and snapshot/settings persistence.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/views/views.xml
## 2026-03-04 14:10:13
- Stage: change
- Summary: Forced TB overrides to load/apply on explicit period ranges only (no snapshot ranges) and renamed the cash note label to "Cash at bank".
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-03-04 14:22:15
- Stage: change
- Summary: Renamed SOCE statutory reserve transfer rows and retained-earnings note statutory reserve line to "Transferred to statutory reserves".
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/views/audit_report_template_2y.html
## 2026-03-05 12:25:55
- Stage: change
- Summary: Applied TB override deltas to derived period-end ranges so editor updates flow into PDF output.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-03-05 14:13:15
- Stage: change
- Summary: Made LOR editor tab compact with constrained card layout and tighter line-table styling.
- Files:
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-03-05 14:27:34
- Stage: change
- Summary: Added period-specific TB add-account actions (current/prior) with a picker wizard for manual account overrides.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/models/audit_report_tb_override.py
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/security/ir.model.access.csv
## 2026-03-05 14:33:25
- Stage: change
- Summary: Refined LOR tab layout by removing helper text, centering the section heading, expanding the list area, and using a squarer modal size when LOR tab is active.
- Files:
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-03-05 14:35:33
- Stage: change
- Summary: Fixed TB add-account wizard view domain by removing unsupported account.deprecated field for Odoo 19.
- Files:
  - Custom/Audit_Report/views/views.xml
## 2026-03-05 14:39:46
- Stage: change
- Summary: Made TB add-account wizard account field optional at creation and removed unsupported deprecated-domain filter.
- Files:
  - Custom/Audit_Report/models/audit_report_tb_override.py
## 2026-03-05 14:45:04
- Stage: change
- Summary: Replaced mixed-unit Sass min() usage in LOR modal sizing with compile-safe width/height plus max constraints.
- Files:
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-03-05 14:47:56
- Stage: change
- Summary: Updated signature placeholder CSS so single-signatory blocks span full width and keep the company-name line on one line.
- Files:
  - Custom/Audit_Report/templates/audit_report_style.css
## 2026-03-05 14:50:09
- Stage: change
- Summary: Removed floating Shareholders helper text from wizard tab and cleaned unused styling for a more compact layout.
- Files:
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-03-05 14:57:26
- Stage: change
- Summary: Adjusted operating-expense note labels: Marketing/Advertisement -> Advertising, Director's Salary -> Director salary, and merged Business Travel + Fuel for Business Travel under Travelling and accommodation.
- Files:
  - Custom/Audit_Report/models/audit_report.py
## 2026-03-05 15:02:52
- Stage: start
- Summary: Start: Clean Trial Balance Overrides tab layout
## 2026-03-05 15:05:14
- Stage: change
- Summary: Cleaned Trial Balance Overrides tab layout and compacted section UI
- Files:
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/static/src/scss/trial_balance_overrides.scss
## 2026-03-10 16:16:02
- Stage: change
- Summary: Added investment gain/loss P&L line, note, and template support
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/cash_flow_account_mapping.csv
  - Custom/Audit_Report/cash_flow_account_mapping.md
## 2026-04-28 11:51:34
- Stage: change
- Summary: Added account 31010501 as a prior year adjustment line in SOCE, retained earnings note, and operating cash-flow add-back.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/cash_flow_account_mapping.csv
  - Custom/Audit_Report/cash_flow_account_mapping.md
## 2026-04-28 16:38:35
- Stage: change
- Summary: Added account 41031101 as a Gain on disposal operating cash-flow adjustment row.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/cash_flow_account_mapping.csv
  - Custom/Audit_Report/cash_flow_account_mapping.md
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-29 14:32:42
- Stage: change
- Summary: Saved and restored DMCC portal account number in previous settings.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-29 13:10:12
- Stage: change
- Summary: Reverted separate vehicle depreciation cash-flow row and split PPE note land/building columns.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/cash_flow_account_mapping.csv
  - Custom/Audit_Report/cash_flow_account_mapping.md
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-28 12:14:46
- Stage: change
- Summary: Renamed cash-flow adjustment add-back label to Prior year adjustment.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/cash_flow_account_mapping.csv
  - Custom/Audit_Report/cash_flow_account_mapping.md
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-28 12:26:42
- Stage: change
- Summary: Added an empty investment-note schedule with fund, currency, shares, NAV, FCY value, exchange rate, and AED value headings.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/templates/audit_report_investment_note_block.html
  - Custom/Audit_Report/templates/audit_report_style.css
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-28 12:33:09
- Stage: change
- Summary: Updated the investment-note schedule to render below the existing investment values instead of replacing them.
- Files:
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-28 12:48:51
- Stage: change
- Summary: Added a report option checkbox to show or hide the blank investment-note schedule.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/views/views.xml
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-28 13:00:37
- Stage: change
- Summary: Bound the blank schedule to the 1201 inventory note, renamed that note to Investments, and kept it controlled by the investments schedule checkbox.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-29 12:22:36
- Stage: change
- Summary: Added bad debt expense as a cash-flow add-back and reclassified interest paid accounts to financing activities.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/audit_report_template_1y.html
  - Custom/Audit_Report/cash_flow_account_mapping.csv
  - Custom/Audit_Report/cash_flow_account_mapping.md
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
## 2026-04-29 17:56:20
- Stage: change
- Summary: Added 1110/1111 and 2105/2106/2107 audit-report classifications for SOFP and cash-flow presentation without note references.
- Files:
  - Custom/Audit_Report/models/audit_report.py
  - Custom/Audit_Report/templates/audit_report_template.html
  - Custom/Audit_Report/templates/audit_report_template_1y.html
  - Custom/Audit_Report/templates/audit_report_template_2y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_1y.html
  - Custom/Audit_Report/templates/audit_report_template_dormant_2y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_1y.html
  - Custom/Audit_Report/templates/audit_report_template_cessation_2y.html
  - Custom/Audit_Report/tests/test_audit_report_note_rendering.py
