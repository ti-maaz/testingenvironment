from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests.common import tagged


@tagged('post_install', '-at_install')
class TestAECustomSync(AccountTestInvoicingCommon):
    country_code = 'AE'
    chart_template = 'ae_custom'

    @classmethod
    def _account_by_code(cls, company, code):
        Account = cls.env['account.account'].with_company(company).with_context(active_test=False)
        domain = [*cls.env['account.account']._check_company_domain(company), ('code', '=', code)]
        return Account.search(domain, limit=1)

    def _mark_account_used(self, company, account):
        debit_account = self._account_by_code(company, '51190101')
        journal = self.env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)
        move = self.env['account.move'].with_company(company).create({
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'line_ids': [
                Command.create({
                    'name': 'Used account marker',
                    'account_id': account.id,
                    'credit': 10.0,
                }),
                Command.create({
                    'name': 'Used account marker',
                    'account_id': debit_account.id,
                    'debit': 10.0,
                }),
            ],
        })
        move.action_post()

    def test_sync_dry_run_no_mutation(self):
        company = self._create_company(name='AE Custom Dry Run Co')
        account = self._account_by_code(company, '12020101')
        original_name = account.name
        account.name = 'Dry Run Mismatch'

        result = company.run_ae_custom_coa_sync(apply=False, strict=True)

        self.assertTrue(any(line['code'] == '12020101' for line in result['updated']))
        self.assertEqual(self._account_by_code(company, '12020101').name, 'Dry Run Mismatch')
        self.assertNotEqual(original_name, 'Dry Run Mismatch')

    def test_sync_apply_updates_unused_only(self):
        company = self._create_company(name='AE Custom Apply Co')
        unused_account = self._account_by_code(company, '12020101')
        used_account = self._account_by_code(company, '41010103')
        source_unused_name = unused_account.name
        source_used_name = used_account.name

        self._mark_account_used(company, used_account)
        unused_account.name = 'Unused Changed Name'
        used_account.name = 'Used Changed Name'

        result = company.run_ae_custom_coa_sync(apply=True, strict=False)

        self.assertEqual(self._account_by_code(company, '12020101').name, source_unused_name)
        self.assertEqual(self._account_by_code(company, '41010103').name, 'Used Changed Name')
        self.assertTrue(any(line['code'] == '41010103' for line in result['skipped_used']))
        self.assertNotEqual(source_used_name, 'Used Changed Name')

    def test_strict_archive_respects_protection(self):
        company = self._create_company(name='AE Custom Strict Co')
        Account = self.env['account.account'].with_company(company).with_context(active_test=False)

        legacy_uae_like = Account.create({
            'name': 'Legacy UAE VAT Output',
            'code': '201017',
            'account_type': 'liability_current',
            'reconcile': False,
            'company_ids': [Command.link(company.id)],
        })
        archive_candidate = Account.create({
            'name': 'Archive Candidate',
            'code': '99887766',
            'account_type': 'expense',
            'reconcile': False,
            'company_ids': [Command.link(company.id)],
        })
        referenced_candidate = Account.create({
            'name': 'Referenced Candidate',
            'code': '99887767',
            'account_type': 'expense',
            'reconcile': False,
            'company_ids': [Command.link(company.id)],
        })

        journal = self.env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)
        journal.default_account_id = referenced_candidate

        result = company.run_ae_custom_coa_sync(apply=True, strict=True)

        self.assertFalse(archive_candidate.with_context(active_test=False).active)
        self.assertFalse(legacy_uae_like.with_context(active_test=False).active)
        self.assertTrue(referenced_candidate.with_context(active_test=False).active)
        self.assertTrue(any(line['code'] == '99887766' for line in result['archived']))
        self.assertTrue(any(line['code'] == '201017' for line in result['archived']))
        self.assertTrue(any(line['code'] == '99887767' for line in result['preserved_referenced']))
        self.assertEqual(result['preserved_required'], [])

    def test_sync_apply_restores_account_default_taxes(self):
        company = self._create_company(name='AE Custom Tax Sync Co')
        account = self._account_by_code(company, '41010102')
        export_tax = self.env.ref(f'account.{company.id}_uae_export_tax', raise_if_not_found=False)

        self.assertTrue(export_tax)
        self.assertSetEqual(set(account.tax_ids.ids), {export_tax.id})

        account.tax_ids = [Command.clear()]
        result = company.run_ae_custom_coa_sync(apply=True, strict=False)

        self.assertSetEqual(set(self._account_by_code(company, '41010102').tax_ids.ids), {export_tax.id})
        self.assertTrue(any(line['code'] == '41010102' for line in result['updated']))

    def test_sync_apply_restores_owner_current_cash_journal(self):
        company = self._create_company(name='AE Custom Cash Journal Sync Co')
        cash_journal = self.env.ref(f'account.{company.id}_cash', raise_if_not_found=False)
        petty_cash = self._account_by_code(company, '12040102')

        self.assertTrue(cash_journal)
        self.assertTrue(petty_cash)
        cash_journal.write({
            'name': 'Cash',
            'code': 'CSH',
            'default_account_id': petty_cash.id,
            'show_on_dashboard': False,
        })

        company.run_ae_custom_coa_sync(apply=True, strict=False)

        self.assertEqual(cash_journal.name, 'Owner Current Account')
        self.assertEqual(cash_journal.code, 'OCA')
        self.assertEqual(cash_journal.default_account_id.code, '12040101')
        self.assertTrue(cash_journal.show_on_dashboard)
