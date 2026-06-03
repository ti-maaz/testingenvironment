# Cash Flow Line Calculations (Audit_Report)

Source: `Custom/Audit_Report/models/audit_report.py` and `Custom/Audit_Report/templates/audit_report_template.html`

This document lists every cash flow line shown in the template and how each value is calculated
in the current implementation.

Notes:
- Period values come from posted move lines within `date_start` to `date_end` (P&L).
- Balance sheet movements use balances as of `date_end` and `prior_date_end`.
- Liability and equity balances are negated via `_liability_to_positive` to treat increases as positive.
- Prior year values use the same formulas with `prev_*` and `prev_prev_*` variables.

| Section | Line label (template) | Variable | Calculation | Sources / notes |
|---|---|---|---|---|
| Operating | Net profit for the year | `net_profit_before_tax` | `gross_profit - operating_expenses_total - investment_gain_loss_total + other_income_total` | Revenue codes `4101, 4102`; other income `4103`; cost of revenue `5101`; investment gain/loss `5201`; operating expenses = total `51xx` minus cost and corporate tax expense (`51270101`). |
| Operating | Prior year adjustment | `prior_year_adjustment` | `-period_prefix_totals[8]['31010501']` | Prior year adjustment equity account movement added back below net profit. |
| Operating | Bad debt expense | `bad_debt_expense_addback` | `period_prefix_totals[8]['51220101']` | Bad debt expense is added back below net profit with other non-cash / reclassification adjustments. |
| Operating | Gain on disposal | `gain_on_disposal_adjustment` | `period_prefix_totals[8]['41031101']` | Gain on disposal income movement is shown under adjustments; credit gains reduce operating cash flow before working capital. |
| Operating | Depreciation | `current_depreciation_total` | `period_prefix_totals[6]['511401']` | Depreciation expense accounts under `511401` (period totals). |
| Operating | Finance cost | `interest_paid_addback` | `period_prefix_totals[6]['512401']` | Interest paid accounts are added back before working capital because the cash outflow is shown in financing activities. |
| Operating | Operating cash flow before working capital | `operating_cashflow_before_working_capital` | `net_profit_before_tax + prior_year_adjustment + bad_debt_expense_addback + gain_on_disposal_adjustment + current_depreciation_total + end_service_benefits_adjustment + interest_paid_addback` | Uses the operating adjustment lines above. |
| Operating | (Increase)/decrease in due to related parties | `decrease_increase_due_related_party` | `current_due - prior_due` | `current_due = -current_prefix_totals[8]['22030101']`; prior uses `prev_prefix_totals`. |
| Operating | (Increase)/decrease in trade receivables | `decrease_increase_in_trade_receivables` | `current_assets[Accounts receivable] - prev_current_assets[Accounts receivable]` | Group `1202` from current assets section totals. |
| Operating | Increase/(decrease) in trade and other payables | `increase_decrease_trade_other_payables` | `(current_payables_total - prior_payables_total) + current_interest_paid` | `current_payables_total = -(current_group_totals['2202'] + current_group_totals['2203'])`; `current_interest_paid = -(period_prefix_totals[6]['512401'])`. |
| Operating | Increase/(decrease) in payable to directors | `decrease_in_payable_director` | `current_director_payables_total - prior_director_payables_total` | Director payables `22030102, 22030103` from `current_prefix_totals[8]`. |
| Operating | Other operating cash flows | `other_operating_cashflows` | `activity_totals['Operating']` | Movements by account code mapped to Activity=Operating in `coa_activity_mapping.csv`. Uses 8-digit balances: `(current - prior)` with asset movements negated. |
| Operating | Net cash generated from operations | `net_cash_generated_from_operations` | `operating_cashflow_before_working_capital + due_related_party + trade_receivables + trade_other_payables + payable_director + other_operating` | Sum of operating lines above. |
| Investing | Purchase of property and equipment | `current_property` | `-_sum_period_cost_balances(period_rows, '1101')` | PPE cost-account movements under `1101`, excluding accumulated depreciation accounts. |
| Investing | Right-of-use assets | `current_rou_assets` | `-period_group_totals['1102']` | ROU group `1102` (period totals). |
| Investing | Intangible assets | `current_intangilbe` | `-period_group_totals['1107']` | Intangible group `1107` (period totals). |
| Investing | Other investing cash flows | `other_investing_cashflows` | `activity_totals['Investing']` | Movements mapped to Activity=Investing in `coa_activity_mapping.csv`. |
| Investing | Net cash used in investing activities | `net_cash_used_in_investing_activities` | `current_property + current_rou_assets + current_intangilbe + other_investing` | Sum of investing lines above. |
| Financing | Other financing cash flows | `other_financing_cashflows` | `activity_totals['Financing']` | Movements mapped to Activity=Financing in `coa_activity_mapping.csv`. |
| Financing | Interest paid | `interest_paid` | `-period_prefix_totals[6]['512401']` | Interest paid on loan and credit facilities (`512401xx`) is shown as a financing cash outflow. |
| Financing | Net cash from financing activities | `cash_from_financing_activities` | `(current_financing_liabilities - prior_financing_liabilities) + (current_share_capital - prior_share_capital) - (current_dividend_paid - prior_dividend_paid) + other_financing + interest_paid` | Financing liabilities = `-(2101+2102+2201)` less bank overdraft `220101` and credit card subgroup `220103`; share capital `310101`; dividend paid `31010202`; interest paid `512401`. |
| Summary | Net increase/(decrease) in cash and cash equivalents | `net_cash_and_cash_equivalents` | `net_cash_generated_from_operations + net_cash_used_in_investing_activities + cash_from_financing_activities` | Sum of three section totals. |
| Summary | Cash and cash equivalents at beginning of year | `cash_beginning_year` | `prev_current_assets[Cash and bank balances]` | Group `1204` from prior current assets. |
| Summary | Cash and cash equivalents at end of year | `cash_end_of_year` | `current_assets[Cash and bank balances]` | Group `1204` from current assets. |

Other cash flow movements (Operating / Investing / Financing) use `coa_activity_mapping.csv` with these excluded prefixes:
`1204, 1205, 1202, 2202, 2203, 22030101, 22030102, 22030103, 1101, 1102, 1107, 2101, 2102, 2201, 220101, 220103, 310101, 31010202`.
