from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class HierarchyConverterCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.country = cls.env.ref('base.us')
        cls.currency = cls.country.currency_id
        cls.company_a = cls._create_converter_company('Co_A')
        cls.company_b = cls._create_converter_company('Co_B')
        cls.company_c = cls._create_converter_company('Co_C')
        cls.cr.precommit.run()
        cls.move_a = cls._create_posted_entry(cls.company_a, 'Co_A opening test entry')
        cls.move_b = cls._create_posted_entry(cls.company_b, 'Co_B opening test entry')
        cls.move_c = cls._create_posted_entry(cls.company_c, 'Co_C opening test entry')
        cls.historical_moves = cls.move_a | cls.move_b | cls.move_c

    @classmethod
    def _create_converter_company(cls, name):
        return cls._create_company(
            name=name,
            country_id=cls.country.id,
            currency_id=cls.currency.id,
        )

    @classmethod
    def _create_posted_entry(cls, company, label):
        data = cls.collect_company_accounting_data(company)
        move = cls.env['account.move'].with_company(company).create({
            'move_type': 'entry',
            'company_id': company.id,
            'journal_id': data['default_journal_misc'].id,
            'date': '2026-01-15',
            'line_ids': [
                Command.create({
                    'name': label,
                    'account_id': data['default_account_expense'].id,
                    'debit': 100.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': label,
                    'account_id': data['default_account_revenue'].id,
                    'debit': 0.0,
                    'credit': 100.0,
                }),
            ],
        })
        move.action_post()
        return move
