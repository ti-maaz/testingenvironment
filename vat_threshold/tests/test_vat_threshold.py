from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from unittest.mock import patch


@tagged('post_install', '-at_install')
class TestVatThreshold(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_system = cls.env.ref('base.group_system')
        cls.group_vat_threshold = cls.env.ref('vat_threshold.group_custom_module_vat_threshold')
        cls.vat_threshold_category = cls.env.ref(
            'vat_threshold.module_category_vat_threshold'
        )

    def _make_company(self, name):
        company = self.env['res.company'].create({'name': name})
        threshold = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        self.assertTrue(threshold, 'VAT threshold record should be auto-created for new companies')
        return company

    def _make_internal_user(self, company, prefix='vat_threshold_user', groups=None):
        login = f'{prefix}_{company.id}'
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': f'{login}@example.com',
            'company_id': company.id,
            'company_ids': [Command.set([company.id])],
            'group_ids': [Command.set(groups or [self.group_user.id])],
        })

    def _set_report_users(self, users):
        self.env['ir.config_parameter'].sudo().set_param(
            'vat_threshold.daily_report_user_ids',
            ','.join(str(user_id) for user_id in users.ids),
        )

    def _make_journal(self, company):
        journal = self.env['account.journal'].search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)
        if journal:
            return journal
        return self.env['account.journal'].create({
            'name': f'{company.name} Misc Journal',
            'code': f'VT{company.id % 1000:03d}',
            'type': 'general',
            'company_id': company.id,
        })

    def _make_account(self, company, code, name, account_type='income'):
        return self.env['account.account'].create({
            'name': name,
            'code': code,
            'account_type': account_type,
            'company_ids': [Command.set([company.id])],
        })

    def _post_entry(self, company, journal, credit_lines, debit_account, move_date=None):
        total_credit = sum(amount for _, amount in credit_lines)
        line_commands = [
            Command.create({
                'name': account.display_name,
                'account_id': account.id,
                'credit': amount,
                'debit': 0.0,
            })
            for account, amount in credit_lines
        ]
        line_commands.append(Command.create({
            'name': 'Counterpart',
            'account_id': debit_account.id,
            'debit': total_credit,
            'credit': 0.0,
        }))
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': move_date or fields.Date.today(),
            'line_ids': line_commands,
        })
        move.action_post()
        return move

    def test_auto_creates_threshold_record_for_new_company(self):
        company = self._make_company('VAT Auto Create Co')
        threshold = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)

        self.assertTrue(threshold)
        self.assertEqual(threshold.company_id, company)

    def test_company_rule_limits_visibility_to_allowed_company(self):
        company_a = self._make_company('VAT Scope A')
        company_b = self._make_company('VAT Scope B')
        user = self._make_internal_user(
            company_a,
            prefix='vat_scope',
            groups=[self.group_user.id, self.group_vat_threshold.id],
        )

        records = self.env['vat.threshold'].with_user(user).search([])

        self.assertEqual(set(records.mapped('company_id.id')), {company_a.id})
        self.assertEqual(len(records), 1)
        self.assertFalse(records.filtered(lambda r: r.company_id.id == company_b.id))

    def test_vat_threshold_group_is_assignable(self):
        user = self._make_internal_user(company=self.env.company, prefix='vat_assignable')

        self.assertEqual(self.group_vat_threshold.privilege_id.category_id, self.vat_threshold_category)
        self.assertNotIn(self.group_vat_threshold, user.group_ids)

        user.write({'group_ids': [Command.link(self.group_vat_threshold.id)]})
        self.assertIn(self.group_vat_threshold, user.group_ids)

        user.write({'group_ids': [Command.unlink(self.group_vat_threshold.id)]})
        self.assertNotIn(self.group_vat_threshold, user.group_ids)

    def test_vat_threshold_menu_and_operator_actions_use_vat_group(self):
        parent_menu = self.env.ref('vat_threshold.menu_vat_threshold_root')
        menu = self.env.ref('vat_threshold.menu_vat_threshold_records')
        action = self.env.ref('vat_threshold.vat_threshold_action')
        recompute_action = self.env.ref('vat_threshold.action_recompute_all_records')
        batch_verify_action = self.env.ref('vat_threshold.action_batch_mark_verified')
        batch_unverify_action = self.env.ref('vat_threshold.action_batch_mark_unverified')

        self.assertIn(self.group_vat_threshold, parent_menu.group_ids)
        self.assertIn(self.group_vat_threshold, menu.group_ids)
        self.assertIn(self.group_vat_threshold, action.group_ids)
        self.assertEqual(set(recompute_action.group_ids.ids), {self.group_system.id, self.group_vat_threshold.id})
        self.assertEqual(set(batch_verify_action.group_ids.ids), {self.group_system.id, self.group_vat_threshold.id})
        self.assertEqual(set(batch_unverify_action.group_ids.ids), {self.group_system.id, self.group_vat_threshold.id})

    def test_email_and_settings_actions_are_restricted_to_system_users(self):
        company = self._make_company('VAT Admin Guard Co')
        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        user = self._make_internal_user(
            company,
            prefix='vat_guard',
            groups=[self.group_user.id, self.group_vat_threshold.id],
        )

        with self.assertRaises(AccessError):
            record.with_user(user).action_check_threshold()

        with self.assertRaises(AccessError):
            record.with_user(user).action_open_settings()

        with self.assertRaises(AccessError):
            record.with_user(user).action_test_send_email()

        with self.assertRaises(AccessError):
            record.with_user(user).send_threshold_notification()

        with self.assertRaises(AccessError):
            self.env['vat.threshold'].with_user(user)._send_consolidated_threshold_report(record)

    def test_vat_operator_can_operate_assigned_company_records(self):
        company = self._make_company('VAT Operator Co')
        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        user = self._make_internal_user(
            company,
            prefix='vat_operator',
            groups=[self.group_user.id, self.group_vat_threshold.id],
        )

        record.write({
            'email_sent': True,
            'email_sent_date': fields.Datetime.now(),
            'vat_verified': False,
        })

        action = record.with_user(user).action_verify_vat()
        record.invalidate_recordset(['vat_verified'])
        self.assertEqual(action['tag'], 'reload')
        self.assertTrue(record.vat_verified)

        record.with_user(user).action_batch_mark_unverified()
        record.invalidate_recordset(['vat_verified'])
        self.assertFalse(record.vat_verified)

        record.with_user(user).action_reset_email()
        record.invalidate_recordset(['email_sent', 'email_sent_date'])
        self.assertFalse(record.email_sent)
        self.assertFalse(record.email_sent_date)

        action = record.with_user(user).action_recompute_all_records()
        self.assertEqual(action['tag'], 'reload')

    def test_vat_operator_cannot_operate_unassigned_company_records(self):
        company_a = self._make_company('VAT Operator Scope A')
        company_b = self._make_company('VAT Operator Scope B')
        user = self._make_internal_user(
            company_a,
            prefix='vat_operator_scope',
            groups=[self.group_user.id, self.group_vat_threshold.id],
        )
        record_b = self.env['vat.threshold'].search([('company_id', '=', company_b.id)], limit=1)

        with self.assertRaises(AccessError):
            record_b.with_user(user).action_verify_vat()

    def test_vat_operator_cannot_arbitrarily_write_create_or_delete_records(self):
        company = self._make_company('VAT Operator ACL Co')
        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        user = self._make_internal_user(
            company,
            prefix='vat_operator_acl',
            groups=[self.group_user.id, self.group_vat_threshold.id],
        )
        threshold_model = self.env['vat.threshold'].with_user(user)

        with self.assertRaises(AccessError):
            record.with_user(user).write({'vat_verified': True})

        with self.assertRaises(AccessError):
            threshold_model.create({'company_id': company.id})

        with self.assertRaises(AccessError):
            record.with_user(user).unlink()

    def test_refresh_recomputes_sales_and_resets_email_flags(self):
        company = self._make_company('VAT Revenue Co')
        journal = self._make_journal(company)
        revenue_uae = self._make_account(company, '41010101', 'UAE Client Revenue')
        revenue_intl = self._make_account(company, '41010102', 'International Revenue')
        revenue_related = self._make_account(company, '41020101', 'Related Party Revenue')
        counter_account = self._make_account(company, '99999998', 'VAT Counterpart', account_type='asset_current')

        self._post_entry(
            company,
            journal,
            [
                (revenue_uae, 150000.0),
                (revenue_intl, 100000.0),
                (revenue_related, 200000.0),
            ],
            counter_account,
        )

        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        record._refresh_threshold_values()

        self.assertEqual(record.rolling_revenue_uae_clients, 150000.0)
        self.assertEqual(record.rolling_revenue_international_clients, 100000.0)
        self.assertEqual(record.rolling_revenue_related_party, 200000.0)
        self.assertEqual(record.rolling_total_sales, 450000.0)
        self.assertEqual(record.threshold_action, 'register')
        self.assertFalse(record.email_sent)
        self.assertFalse(record.email_sent_date)

        record.write({
            'email_sent': True,
            'email_sent_date': fields.Datetime.now(),
        })
        company.sudo().write({'vat_registration_number': 'AE123456789'})
        company.invalidate_recordset(['vat_registration_number'])

        record._refresh_threshold_values()

        self.assertTrue(record.is_vat_registered)
        self.assertEqual(record.threshold_action, 'none')
        self.assertFalse(record.email_sent)
        self.assertFalse(record.email_sent_date)

    def test_threshold_action_uses_voluntary_registration_band(self):
        company = self._make_company('VAT Voluntary Threshold Co')
        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)

        record.write({'rolling_total_sales': 209999.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'none')

        record.write({'rolling_total_sales': 210000.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'voluntary_register')

        record.write({'rolling_total_sales': 300000.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'voluntary_register')

        record.write({'rolling_total_sales': 349999.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'voluntary_register')

        record.write({'rolling_total_sales': 350000.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'register_warning')

        record.write({'rolling_total_sales': 375000.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'register_warning')

        record.write({'rolling_total_sales': 375001.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'register')

    def test_threshold_action_uses_cancellation_warning_band(self):
        company = self._make_company('VAT Cancellation Warning Co')
        company.sudo().write({'vat_registration_number': 'AE998877665'})
        company.invalidate_recordset(['vat_registration_number'])
        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)

        record.write({'rolling_total_sales': 200001.0})
        record._compute_vat_status()
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'none')

        record.write({'rolling_total_sales': 200000.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'none')

        record.write({'rolling_total_sales': 199999.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'cancel_warning')

        record.write({'rolling_total_sales': 187500.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'cancel_warning')

        record.write({'rolling_total_sales': 187499.0})
        record._compute_threshold_action()
        self.assertEqual(record.threshold_action, 'cancel')

    def test_breach_date_tracks_first_day_threshold_was_crossed(self):
        company = self._make_company('VAT Breach Date Co')
        journal = self._make_journal(company)
        revenue_uae = self._make_account(company, '41010101', 'UAE Client Revenue')
        counter_account = self._make_account(company, '99999997', 'VAT Breach Counterpart', account_type='asset_current')

        first_date = fields.Date.today() - relativedelta(days=10)
        second_date = fields.Date.today() - relativedelta(days=5)
        third_date = fields.Date.today() - relativedelta(days=1)

        self._post_entry(
            company,
            journal,
            [(revenue_uae, 200000.0)],
            counter_account,
            move_date=first_date,
        )
        self._post_entry(
            company,
            journal,
            [(revenue_uae, 160000.0)],
            counter_account,
            move_date=second_date,
        )
        self._post_entry(
            company,
            journal,
            [(revenue_uae, 20000.0)],
            counter_account,
            move_date=third_date,
        )

        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        record._refresh_threshold_values()

        self.assertEqual(record.threshold_action, 'register')
        self.assertEqual(record.threshold_breach_date, third_date)

        record.write({'threshold_action': 'register_warning'})
        record._compute_threshold_breach_date()
        self.assertEqual(record.threshold_breach_date, second_date)

        record.write({'threshold_action': 'voluntary_register'})
        record._compute_threshold_breach_date()
        self.assertEqual(record.threshold_breach_date, second_date)

    def test_settings_can_override_threshold_values_and_trigger_recompute(self):
        company = self._make_company('VAT Dynamic Threshold Co')
        journal = self._make_journal(company)
        revenue_uae = self._make_account(company, '41010101', 'Dynamic Threshold Revenue')
        counter_account = self._make_account(
            company,
            '99999996',
            'Dynamic Threshold Counterpart',
            account_type='asset_current',
        )
        self._post_entry(
            company,
            journal,
            [(revenue_uae, 200000.0)],
            counter_account,
        )

        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)
        record._refresh_threshold_values()
        self.assertEqual(record.threshold_action, 'none')

        config = self.env['res.config.settings'].create({
            'cancel_threshold': 180000.0,
            'cancellation_warning_threshold': 220000.0,
            'voluntary_threshold': 180000.0,
            'mandatory_warning_threshold': 190000.0,
            'mandatory_threshold': 300000.0,
        })
        action = config.action_save_settings()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['next']['type'], 'ir.actions.act_window_close')
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param('vat_threshold.mandatory_warning_threshold'),
            '190000.0',
        )
        record.invalidate_recordset(['threshold_action'])
        self.assertEqual(record.threshold_action, 'register_warning')

    def test_operator_actions_and_system_settings_have_expected_groups(self):
        recompute_action = self.env.ref('vat_threshold.action_recompute_all_records')
        create_missing_action = self.env.ref('vat_threshold.action_create_missing_companies')
        batch_verify_action = self.env.ref('vat_threshold.action_batch_mark_verified')
        batch_unverify_action = self.env.ref('vat_threshold.action_batch_mark_unverified')
        settings_action = self.env.ref('vat_threshold.action_vat_threshold_config')

        self.assertEqual(set(recompute_action.group_ids.ids), {self.group_system.id, self.group_vat_threshold.id})
        self.assertEqual(set(create_missing_action.group_ids.ids), {self.group_system.id})
        self.assertEqual(set(batch_verify_action.group_ids.ids), {self.group_system.id, self.group_vat_threshold.id})
        self.assertEqual(set(batch_unverify_action.group_ids.ids), {self.group_system.id, self.group_vat_threshold.id})
        self.assertEqual(set(settings_action.group_ids.ids), {self.group_system.id})

    def test_daily_report_batches_follow_configured_users_and_company_assignment(self):
        company_a = self._make_company('VAT Hashir A')
        company_b = self._make_company('VAT Hashir B')
        company_c = self._make_company('VAT Hashir C')

        user_hashir = self._make_internal_user(company_a, prefix='hashir')
        user_hashir.write({'company_ids': [Command.set([company_a.id, company_c.id])]})
        user_other = self._make_internal_user(company_b, prefix='other')
        user_other.write({'company_ids': [Command.set([company_b.id])]})
        self._set_report_users(user_hashir | user_other)

        record_a = self.env['vat.threshold'].search([('company_id', '=', company_a.id)], limit=1)
        record_b = self.env['vat.threshold'].search([('company_id', '=', company_b.id)], limit=1)
        record_c = self.env['vat.threshold'].search([('company_id', '=', company_c.id)], limit=1)

        record_a.write({'threshold_action': 'register_warning'})
        record_b.write({'threshold_action': 'voluntary_register'})
        record_c.write({'threshold_action': 'cancel_warning'})

        batches = self.env['vat.threshold']._get_daily_report_user_batches(record_a | record_b | record_c)

        self.assertEqual(set(batches.keys()), {user_hashir.id, user_other.id})
        self.assertEqual(set(batches[user_hashir.id]['register_warning_list'].ids), {record_a.id})
        self.assertEqual(set(batches[user_hashir.id]['cancel_warning_list'].ids), {record_c.id})
        self.assertFalse(batches[user_hashir.id]['register_list'])
        self.assertFalse(batches[user_hashir.id]['voluntary_register_list'])
        self.assertFalse(batches[user_hashir.id]['cancel_list'])
        self.assertFalse(batches[user_hashir.id]['no_action_list'])
        self.assertFalse(batches[user_other.id]['register_warning_list'])
        self.assertFalse(batches[user_other.id]['register_list'])
        self.assertEqual(set(batches[user_other.id]['voluntary_register_list'].ids), {record_b.id})
        self.assertFalse(batches[user_other.id]['cancel_warning_list'])
        self.assertFalse(batches[user_other.id]['cancel_list'])
        self.assertFalse(batches[user_other.id]['no_action_list'])

    def test_threshold_notification_prefers_configured_assigned_user_email(self):
        company = self._make_company('VAT Assigned Mail Co')
        company.write({'email': 'client@example.com'})
        user_hashir = self._make_internal_user(company, prefix='hashir_mail')
        user_hashir.write({'email': 'hashir@example.com'})
        self._set_report_users(user_hashir)

        record = self.env['vat.threshold'].search([('company_id', '=', company.id)], limit=1)

        self.assertEqual(record._get_threshold_notification_recipient_emails(), ['hashir@example.com'])

    def test_consolidated_threshold_report_sends_one_email_per_user_plus_global_recipients(self):
        company_a = self._make_company('VAT Combined A')
        company_b = self._make_company('VAT Combined B')
        company_c = self._make_company('VAT Combined C')

        user_a = self._make_internal_user(company_a, prefix='combined_a')
        user_a.write({
            'email': 'combined-a@example.com',
            'company_ids': [Command.set([company_a.id, company_c.id])],
        })
        user_b = self._make_internal_user(company_b, prefix='combined_b')
        user_b.write({
            'email': 'combined-b@example.com',
            'company_ids': [Command.set([company_b.id])],
        })
        self._set_report_users(user_a | user_b)
        self.env['ir.config_parameter'].sudo().set_param(
            'vat_threshold.daily_report_recipients',
            'finance@example.com, audit@example.com',
        )

        record_a = self.env['vat.threshold'].search([('company_id', '=', company_a.id)], limit=1)
        record_b = self.env['vat.threshold'].search([('company_id', '=', company_b.id)], limit=1)
        record_c = self.env['vat.threshold'].search([('company_id', '=', company_c.id)], limit=1)
        record_a.write({'threshold_action': 'register_warning'})
        record_b.write({'threshold_action': 'voluntary_register'})
        record_c.write({'threshold_action': 'cancel_warning'})

        sent_payloads = []

        def fake_send(
            _self,
            email_to,
            register_warning_list,
            register_list,
            voluntary_register_list,
            cancel_warning_list,
            cancel_list,
            no_action_list,
            subject_prefix='',
        ):
            sent_payloads.append({
                'email_to': email_to,
                'register_warning_ids': set(register_warning_list.ids),
                'register_ids': set(register_list.ids),
                'voluntary_register_ids': set(voluntary_register_list.ids),
                'cancel_warning_ids': set(cancel_warning_list.ids),
                'cancel_ids': set(cancel_list.ids),
                'no_action_ids': set(no_action_list.ids),
                'subject_prefix': subject_prefix,
            })
            return True

        with patch.object(type(self.env['vat.threshold']), '_send_daily_report_email', autospec=True, side_effect=fake_send):
            result = self.env['vat.threshold']._send_consolidated_threshold_report(
                record_a | record_b | record_c,
                mark_sent=True,
            )

        self.assertEqual(len(sent_payloads), 3)
        self.assertEqual(
            {payload['email_to'] for payload in sent_payloads},
            {
                'combined-a@example.com',
                'combined-b@example.com',
                'finance@example.com, audit@example.com',
            },
        )

        user_a_payload = next(payload for payload in sent_payloads if payload['email_to'] == 'combined-a@example.com')
        self.assertEqual(user_a_payload['register_warning_ids'], {record_a.id})
        self.assertFalse(user_a_payload['register_ids'])
        self.assertFalse(user_a_payload['voluntary_register_ids'])
        self.assertEqual(user_a_payload['cancel_warning_ids'], {record_c.id})
        self.assertFalse(user_a_payload['cancel_ids'])

        user_b_payload = next(payload for payload in sent_payloads if payload['email_to'] == 'combined-b@example.com')
        self.assertFalse(user_b_payload['register_warning_ids'])
        self.assertFalse(user_b_payload['register_ids'])
        self.assertEqual(user_b_payload['voluntary_register_ids'], {record_b.id})
        self.assertFalse(user_b_payload['cancel_warning_ids'])
        self.assertFalse(user_b_payload['cancel_ids'])

        global_payload = next(
            payload
            for payload in sent_payloads
            if payload['email_to'] == 'finance@example.com, audit@example.com'
        )
        self.assertEqual(global_payload['register_warning_ids'], {record_a.id})
        self.assertFalse(global_payload['register_ids'])
        self.assertEqual(global_payload['voluntary_register_ids'], {record_b.id})
        self.assertEqual(global_payload['cancel_warning_ids'], {record_c.id})
        self.assertFalse(global_payload['cancel_ids'])

        self.assertEqual(set(result['sent_records'].ids), {record_a.id, record_b.id, record_c.id})
        self.assertEqual(
            set(result['sent_to']),
            {'combined-a@example.com', 'combined-b@example.com', 'finance@example.com', 'audit@example.com'},
        )

        for record in (record_a | record_b | record_c):
            self.assertTrue(record.email_sent)
            self.assertTrue(record.email_sent_date)

    def test_daily_report_body_includes_voluntary_registration_section(self):
        company_a = self._make_company('VAT Body Warning')
        company_b = self._make_company('VAT Body Register')
        company_c = self._make_company('VAT Body Voluntary')
        company_d = self._make_company('VAT Body Cancel Warning')
        company_e = self._make_company('VAT Body Cancel')
        company_f = self._make_company('VAT Body None')

        record_a = self.env['vat.threshold'].search([('company_id', '=', company_a.id)], limit=1)
        record_b = self.env['vat.threshold'].search([('company_id', '=', company_b.id)], limit=1)
        record_c = self.env['vat.threshold'].search([('company_id', '=', company_c.id)], limit=1)
        record_d = self.env['vat.threshold'].search([('company_id', '=', company_d.id)], limit=1)
        record_e = self.env['vat.threshold'].search([('company_id', '=', company_e.id)], limit=1)
        record_f = self.env['vat.threshold'].search([('company_id', '=', company_f.id)], limit=1)

        breach_date_warning = fields.Date.today() - relativedelta(days=9)
        breach_date_register = fields.Date.today() - relativedelta(days=3)
        breach_date_voluntary = fields.Date.today() - relativedelta(days=7)

        breach_dates = {
            'VAT Body Warning': breach_date_warning,
            'VAT Body Register': breach_date_register,
            'VAT Body Voluntary': breach_date_voluntary,
        }

        def mock_get_threshold_breach_date(self_rec, company, account_ids, threshold_amount, date_from=None, date_to=None):
            return breach_dates.get(company.name, False)

        with patch('odoo.addons.vat_threshold.models.vat_threshold.VatThreshold._get_threshold_breach_date', mock_get_threshold_breach_date):
            record_a.write({
                'threshold_action': 'register_warning',
                'rolling_total_sales': 360000.0,
                'threshold_breach_date': breach_date_warning,
            })
            record_b.write({
                'threshold_action': 'register',
                'rolling_total_sales': 450000.0,
                'threshold_breach_date': breach_date_register,
            })
            record_c.write({
                'threshold_action': 'voluntary_register',
                'rolling_total_sales': 250000.0,
                'threshold_breach_date': breach_date_voluntary,
            })
            record_d.write({'threshold_action': 'cancel_warning', 'rolling_total_sales': 195000.0})
            record_e.write({'threshold_action': 'cancel', 'rolling_total_sales': 100000.0})
            record_f.write({'threshold_action': 'none', 'rolling_total_sales': 50000.0})

            body = self.env['vat.threshold']._prepare_daily_report_body(
                record_a,
                record_b,
                record_c,
                record_d,
                record_e,
                record_f,
            )

        self.assertIn('COMPANIES APPROACHING MANDATORY VAT REGISTRATION', body)
        self.assertIn('COMPANIES ELIGIBLE FOR VOLUNTARY VAT REGISTRATION', body)
        self.assertIn('COMPANIES APPROACHING VAT CANCELLATION', body)
        self.assertIn('Mandatory VAT Warning', body)
        self.assertIn('Voluntary VAT Registration', body)
        self.assertIn('VAT Cancellation Warning', body)
        self.assertIn(str(breach_date_warning), body)
        self.assertIn('Eligible for Voluntary Registration:', body)
        self.assertIn(str(breach_date_register), body)
        self.assertIn(str(breach_date_voluntary), body)
        self.assertIn(company_c.name, body)
