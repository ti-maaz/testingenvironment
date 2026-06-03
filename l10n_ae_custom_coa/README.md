UAE Custom CoA Localization (l10n_ae_custom_coa)
=================================================

This module extends l10n_ae with a custom chart template ae_custom while preserving UAE taxes and fiscal positions from the official localization.

What it does
------------

* Adds chart template code: ae_custom.
* Loads custom accounts from data/template/account.account-ae_custom.csv.
* Keeps UAE tax configuration unchanged by reading tax and fiscal-position templates from l10n_ae.
* Remaps UAE tax and system account references to custom ae_custom_account_* XMLIDs.
* For ae_custom, disables Odoo auto-generated utility accounts and binds utility settings to these codes:

  * Suspense: 12040209
  * Outstanding Receipts: 12040210
  * Outstanding Payments: 12040211
  * Cash Difference Gain/Loss: 41030504 / 51220106
  * Liquidity Transfer: 12060101
* Sets deferred accounts:

  * Deferred Expense: 12030201
  * Deferred Revenue: 22030110
* Enforces strict account synchronization through _sync_ae_custom_coa:

  * create missing source accounts
  * update only unused source accounts
  * skip updates on used accounts
  * archive unmanaged accounts only when safe
  * preserve referenced and system-linked accounts only

Source of truth and regeneration
--------------------------------

Generate the account template CSV from the workbook::

    python3 Custom/l10n_ae_custom_coa/scripts/generate_account_template.py \
      --input "/home/nabeel/odoo19/Account (account.account).xlsx" \
      --output "/home/nabeel/odoo19/Custom/l10n_ae_custom_coa/data/template/account.account-ae_custom.csv"

New company flow
----------------

1. Install l10n_ae_custom_coa.
2. Select localization template ae_custom for a UAE company.
3. Chart load finishes with automatic strict sync in _post_load_data.

Existing company migration flow
-------------------------------

Run dry-run first::

    company.run_ae_custom_coa_sync(apply=False, strict=True)

Apply only after review::

    company.run_ae_custom_coa_sync(apply=True, strict=True)

Rollback guidance
-----------------

* Restore from a database backup when available.
* For archived accounts only, unarchive with:

  * filter active = False
  * set active = True
