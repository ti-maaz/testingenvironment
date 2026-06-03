# Audit Excel Export

## How narration cleaning works

The General Ledger sheet supports a narration cleaner that rewrites noisy move-detail
line descriptions into a shorter, consistent label format while preserving the raw text.

### What is cleaned

- Only the `General Ledger` worksheet.
- Only detail rows where:
  - `Code` column is empty,
  - `Account Name` has a value,
  - row label is not `Initial Balance`,
  - row label does not start with `Total`,
  - row label is not `Load more...`.

### What is preserved

- Original raw narration is stored in the same `Account Name` cell comment
  (`Raw narration: ...`).
- Numeric/date columns are not modified.

### Output shape

The cleaner returns structured values and composes labels such as:

- `IN TT | <Counterparty> | <Ref> | <Bank Ref>`
- `FEE | <Type> | VAT | <Ref>`
- `CARD | Payment | ****<last4> | <Bank Ref>`

### Feature toggle

System parameter:

- `audit_excel_export.gl_narration_cleaner_enabled`

Behavior:

- Enabled by default (parameter missing/empty).
- Disable with false-like values: `0`, `false`, `no`, `off`.
