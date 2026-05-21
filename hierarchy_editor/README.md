# Company Hierarchy Converter

Company Hierarchy Converter provides a guarded wizard for changing Odoo 19 parent/branch company relationships by writing `res.company.parent_id` directly through the ORM, with preflight validation and immutable audit logging. It never deletes, archives, duplicates, or migrates transactional data such as journal entries, invoices, payments, stock moves, reconciliations, sequences, or chart-of-account records.

## Installation

1. Place `company_hierarchy_converter` in an Odoo addons path.
2. Restart Odoo.
3. Update the Apps list.
4. Install **Company Hierarchy Converter**.

## Usage: Branch -> Parent

1. Go to **Settings -> Users & Companies -> Hierarchy Converter**.
2. Select the branch company as **Source Company**.
3. Choose **Branch -> Parent**.
4. Leave **Dry Run** enabled and click **Run Preflight**.
5. Review the preflight report. If no blockers are shown, close the wizard or repeat with **Dry Run** disabled.
6. Click **Execute**. The branch is promoted by setting its `parent_id` to empty, and an audit row is created.
7. Review the audit entry from the wizard or from **Settings -> Technical -> Hierarchy Audit Log**.

## Known Limitations

- Cross-country reparenting is not supported. Branches must share their parent's country.
- Cross-currency reparenting is not supported.
- Chart of Accounts materialization is not supported by design. Odoo 19 uses `account.account.company_ids` as a Many2many relationship, and this module only links accounts to the new hierarchy root where visibility requires it.
- The adoptive-parent scenario requires the **Target Parent** and **Target Adoptee** fields to reference the same standalone company. This keeps the otherwise ambiguous Odoo field contract explicit and auditable.
