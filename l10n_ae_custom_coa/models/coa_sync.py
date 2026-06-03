# Part of Odoo. See LICENSE file for full copyright and licensing details.

import csv

from odoo import Command, _, models
from odoo.exceptions import UserError
from odoo.tools import file_open


SOURCE_TEMPLATE_PATH = 'l10n_ae_custom_coa/data/template/account.account-ae_custom.csv'
SYNC_SCALAR_MUTABLE_FIELDS = ('name', 'account_type', 'reconcile')
DEFAULT_RECEIVABLE_CODE = '12020101'
DEFAULT_PAYABLE_CODE = '22020101'
DEFAULT_INCOME_CODE = '41010103'
DEFAULT_EXPENSE_CODE = '51190101'
DEFAULT_DEFERRED_EXPENSE_CODE = '12030201'
DEFAULT_DEFERRED_REVENUE_CODE = '22030110'
DEFAULT_BANK_JOURNAL_ACCOUNT_CODE = '12040201'
DEFAULT_OWNER_CURRENT_ACCOUNT_CODE = '12040101'
DEFAULT_OWNER_CURRENT_JOURNAL_NAME = 'Owner Current Account'
DEFAULT_OWNER_CURRENT_JOURNAL_CODE = 'OCA'


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _post_load_data(self, template_code, company, template_data):
        super()._post_load_data(template_code, company, template_data)
        if template_code != 'ae_custom':
            return
        self._apply_ae_custom_company_defaults(company)
        result = self._sync_ae_custom_coa(company=company, apply=True, strict=True)
        if result['errors']:
            raise UserError(_(
                "Custom CoA post-install sync failed:\n%s",
                "\n".join(result['errors']),
            ))

    def _sync_ae_custom_coa(self, company=None, apply=False, strict=True):
        company = company or self.env.company
        if isinstance(company, int):
            company = self.env['res.company'].browse(company)
        company.ensure_one()

        result = {
            'source_accounts': 0,
            'created': [],
            'updated': [],
            'skipped_used': [],
            'archived': [],
            'preserved_required': [],
            'preserved_referenced': [],
            'errors': [],
        }

        try:
            source_accounts = self._get_ae_custom_source_accounts()
        except Exception as err:  # pylint: disable=broad-except
            result['errors'].append(str(err))
            return result

        result['source_accounts'] = len(source_accounts)
        source_codes = set(source_accounts)

        Account = self.env['account.account'].sudo().with_company(company).with_context(active_test=False)
        account_domain = [*Account._check_company_domain(company)]
        existing_accounts = Account.search(account_domain)
        existing_by_code = {account.code: account for account in existing_accounts if account.code}
        cached_tax_ids = {}
        missing_tax_xmlids = set()

        created_xmlids = []

        for code in sorted(source_accounts):
            source = source_accounts[code]
            expected_tax_ids = []
            unresolved_taxes = []
            for tax_xmlid in source['tax_xmlids']:
                if tax_xmlid not in cached_tax_ids:
                    tax_record = self.with_company(company).ref(tax_xmlid, raise_if_not_found=False)
                    cached_tax_ids[tax_xmlid] = tax_record.id if tax_record else False
                tax_id = cached_tax_ids[tax_xmlid]
                if tax_id:
                    expected_tax_ids.append(tax_id)
                else:
                    unresolved_taxes.append(tax_xmlid)

            if unresolved_taxes:
                for missing_xmlid in unresolved_taxes:
                    if missing_xmlid in missing_tax_xmlids:
                        continue
                    missing_tax_xmlids.add(missing_xmlid)
                    result['errors'].append(
                        _("Missing account tax template XMLID: %(xmlid)s", xmlid=missing_xmlid)
                    )
                continue

            account = existing_by_code.get(code)
            if not account:
                result['created'].append({
                    'code': code,
                    'name': source['name'],
                    'xmlid': source['xmlid'],
                })
                if not apply:
                    continue
                try:
                    created_account = Account.create({
                        'name': source['name'],
                        'code': code,
                        'account_type': source['account_type'],
                        'reconcile': source['reconcile'],
                        'tax_ids': [Command.set(expected_tax_ids)],
                        'company_ids': [Command.link(company.id)],
                    })
                    created_xmlids.append({
                        'xml_id': f"account.{company.id}_{source['xmlid']}",
                        'record': created_account,
                        'noupdate': True,
                    })
                except Exception as err:  # pylint: disable=broad-except
                    result['errors'].append(
                        _("Failed creating account %(code)s (%(name)s): %(error)s", code=code, name=source['name'], error=str(err))
                    )
                continue

            changes = {}
            display_changes = {}
            for field_name in SYNC_SCALAR_MUTABLE_FIELDS:
                if account[field_name] == source[field_name]:
                    continue
                changes[field_name] = source[field_name]
                display_changes[field_name] = source[field_name]

            if set(account.tax_ids.ids) != set(expected_tax_ids):
                changes['tax_ids'] = [Command.set(expected_tax_ids)]
                display_changes['tax_ids'] = ','.join(source['tax_xmlids'])

            if not changes:
                continue

            update_info = {
                'code': account.code,
                'name': account.name,
                'changes': display_changes,
            }
            if account.used:
                result['skipped_used'].append({
                    **update_info,
                    'reason': 'used_account_update_blocked',
                })
                continue

            result['updated'].append(update_info)
            if apply:
                try:
                    account.write(changes)
                except Exception as err:  # pylint: disable=broad-except
                    result['errors'].append(
                        _("Failed updating account %(code)s (%(name)s): %(error)s", code=account.code, name=account.name, error=str(err))
                    )

        if apply and created_xmlids:
            self.env['ir.model.data']._update_xmlids(created_xmlids)

        if strict:
            referenced_ids = self._get_referenced_account_ids(company)
            # Accounts created above are source accounts and excluded from archive candidates.
            archive_candidates = existing_accounts.filtered(lambda account: account.active and account.code not in source_codes)

            for account in archive_candidates:
                if account.used:
                    result['skipped_used'].append({
                        'code': account.code,
                        'name': account.name,
                        'reason': 'used_account_archive_blocked',
                    })
                    continue
                if account.id in referenced_ids:
                    result['preserved_referenced'].append({
                        'code': account.code,
                        'name': account.name,
                    })
                    continue

                result['archived'].append({
                    'code': account.code,
                    'name': account.name,
                })
                if apply:
                    try:
                        account.active = False
                    except Exception as err:  # pylint: disable=broad-except
                        result['errors'].append(
                            _("Failed archiving account %(code)s (%(name)s): %(error)s", code=account.code, name=account.name, error=str(err))
                        )

        if apply:
            self._apply_ae_custom_company_defaults(company)

        return result

    def _get_ae_custom_source_accounts(self):
        source_accounts = {}
        with file_open(SOURCE_TEMPLATE_PATH, 'r') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                code = (row.get('code') or '').strip()
                if not code:
                    continue
                source_accounts[code] = {
                    'xmlid': (row.get('id') or '').strip(),
                    'name': (row.get('name') or '').strip(),
                    'account_type': (row.get('account_type') or '').strip(),
                    'reconcile': self._csv_to_bool(row.get('reconcile')),
                    'tax_xmlids': self._csv_to_xmlids(row.get('tax_ids')),
                }
        return source_accounts

    def _get_referenced_account_ids(self, company):
        account_ids = set()
        company = company.sudo()
        Account = self.env['account.account'].sudo().with_company(company).with_context(active_test=False)
        account_domain = [*Account._check_company_domain(company)]
        company_account_ids = set(Account.search(account_domain).ids)

        company_fields = [
            field_name
            for field_name, field in company._fields.items()
            if field.type == 'many2one' and field.comodel_name == 'account.account'
        ]
        for field_name in company_fields:
            if company[field_name]:
                account_ids.add(company[field_name].id)

        Journal = self.env['account.journal'].sudo().with_company(company).with_context(active_test=False)
        journals = Journal.search([('company_id', '=', company.id)])
        journal_fields = [
            field_name
            for field_name, field in Journal._fields.items()
            if field.type == 'many2one' and field.comodel_name == 'account.account'
        ]
        for field_name in journal_fields:
            account_ids.update(journals.mapped(field_name).ids)

        tax_repartition_lines = self.env['account.tax.repartition.line'].sudo().with_context(active_test=False).search([
            ('tax_id.company_id', '=', company.id),
            ('account_id', '!=', False),
        ])
        account_ids.update(tax_repartition_lines.mapped('account_id').ids)

        if 'account.reconcile.model.line' in self.env:
            reconcile_lines = self.env['account.reconcile.model.line'].sudo().with_context(active_test=False).search([
                ('model_id.company_id', '=', company.id),
                ('account_id', '!=', False),
            ])
            account_ids.update(reconcile_lines.mapped('account_id').ids)

        if 'account.payment.method.line' in self.env:
            payment_method_lines = self.env['account.payment.method.line'].sudo().with_context(active_test=False).search([
                ('journal_id.company_id', '=', company.id),
                ('payment_account_id', '!=', False),
            ])
            account_ids.update(payment_method_lines.mapped('payment_account_id').ids)

        if 'ir.property' in self.env:
            property_company_ids = [company.id]
            if company.root_id and company.root_id.id != company.id:
                property_company_ids.append(company.root_id.id)
            properties = self.env['ir.property'].sudo().with_context(active_test=False).search([
                ('company_id', 'in', [False, *property_company_ids]),
                ('value_reference', 'like', 'account.account,%'),
            ])
            for property_record in properties:
                try:
                    account_id = int(property_record.value_reference.split(',')[1])
                except (TypeError, ValueError, AttributeError, IndexError):
                    continue
                account_ids.add(account_id)

        return account_ids & company_account_ids

    def _apply_ae_custom_company_defaults(self, company):
        company = company.sudo()
        Account = self.env['account.account'].sudo().with_company(company).with_context(active_test=False)
        account_domain = [*Account._check_company_domain(company)]

        receivable = Account.search([*account_domain, ('code', '=', DEFAULT_RECEIVABLE_CODE)], limit=1)
        payable = Account.search([*account_domain, ('code', '=', DEFAULT_PAYABLE_CODE)], limit=1)
        income = Account.search([*account_domain, ('code', '=', DEFAULT_INCOME_CODE)], limit=1)
        expense = Account.search([*account_domain, ('code', '=', DEFAULT_EXPENSE_CODE)], limit=1)
        deferred_expense = Account.search([*account_domain, ('code', '=', DEFAULT_DEFERRED_EXPENSE_CODE)], limit=1)
        deferred_revenue = Account.search([*account_domain, ('code', '=', DEFAULT_DEFERRED_REVENUE_CODE)], limit=1)
        bank_liquidity = Account.search([*account_domain, ('code', '=', DEFAULT_BANK_JOURNAL_ACCOUNT_CODE)], limit=1)
        owner_current = Account.search([*account_domain, ('code', '=', DEFAULT_OWNER_CURRENT_ACCOUNT_CODE)], limit=1)

        if receivable:
            company.account_default_pos_receivable_account_id = receivable
            self.env['ir.default'].sudo().set(
                'res.partner', 'property_account_receivable_id', receivable.id, company_id=company.id
            )
        if payable:
            self.env['ir.default'].sudo().set(
                'res.partner', 'property_account_payable_id', payable.id, company_id=company.id
            )
        if income:
            company.income_account_id = income
        if expense:
            company.expense_account_id = expense
        if deferred_expense:
            company.expense_accrual_account_id = deferred_expense
        if deferred_revenue:
            company.revenue_accrual_account_id = deferred_revenue

        sale_journal = self.with_company(company).ref('sale', raise_if_not_found=False)
        if sale_journal and income:
            sale_journal.default_account_id = income
        purchase_journal = self.with_company(company).ref('purchase', raise_if_not_found=False)
        if purchase_journal and expense:
            purchase_journal.default_account_id = expense
        bank_journal = self.with_company(company).ref('bank', raise_if_not_found=False)
        if bank_journal and bank_liquidity:
            bank_journal.default_account_id = bank_liquidity
        self._apply_ae_custom_cash_journal_defaults(company, owner_current)

    def _apply_ae_custom_cash_journal_defaults(self, company, owner_current):
        if not owner_current:
            return

        Journal = self.env['account.journal'].sudo().with_company(company).with_context(active_test=False)
        cash_journal = self.with_company(company).ref('cash', raise_if_not_found=False)
        if not cash_journal:
            cash_journal = Journal.search([
                ('company_id', '=', company.id),
                ('type', '=', 'cash'),
            ], limit=1)
        if not cash_journal:
            return

        values = {
            'name': DEFAULT_OWNER_CURRENT_JOURNAL_NAME,
            'default_account_id': owner_current.id,
            'show_on_dashboard': True,
        }
        existing_oca_journal = Journal.search([
            ('company_id', '=', company.id),
            ('code', '=', DEFAULT_OWNER_CURRENT_JOURNAL_CODE),
            ('id', '!=', cash_journal.id),
        ], limit=1)
        has_moves = bool(self.env['account.move'].sudo().search_count([
            ('company_id', '=', company.id),
            ('journal_id', '=', cash_journal.id),
        ], limit=1))
        if not existing_oca_journal and not has_moves:
            values['code'] = DEFAULT_OWNER_CURRENT_JOURNAL_CODE
        cash_journal.write(values)

    @staticmethod
    def _csv_to_bool(value):
        if isinstance(value, bool):
            return value
        value = str(value or '').strip().lower()
        return value in {'1', 'true', 'yes'}

    @staticmethod
    def _csv_to_xmlids(value):
        return tuple(
            xmlid.strip()
            for xmlid in str(value or '').split(',')
            if xmlid.strip()
        )


class ResCompany(models.Model):
    _inherit = 'res.company'

    def run_ae_custom_coa_sync(self, apply=False, strict=True):
        self.ensure_one()
        return self.env['account.chart.template']._sync_ae_custom_coa(
            company=self,
            apply=apply,
            strict=strict,
        )
