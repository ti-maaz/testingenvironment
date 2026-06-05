# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)


class VatThreshold(models.Model):
    _name = 'vat.threshold'
    _description = 'VAT Threshold Management'
    _order = 'last_check_date desc'
    _sql_constraints = [
        (
            'vat_threshold_company_unique',
            'unique(company_id)',
            'A VAT threshold record already exists for this company.',
        ),
    ]

    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
        store=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        ondelete='cascade',
        # index=True,
        # check_company=True,
    )
    company_name = fields.Char(
        string='Company Name',
        related='company_id.name',
        store=True,
        readonly=True
    )
    
    # Revenue Account Codes
    revenue_uae_clients = fields.Monetary(
        string='Revenue - UAE Clients (41010101)',
        compute='_compute_revenue',
        store=True,
        currency_field='currency_id',
        help='Account code 41010101'
    )
    revenue_international_clients = fields.Monetary(
        string='Revenue - International Clients (41010102)',
        compute='_compute_revenue',
        store=True,
        currency_field='currency_id',
        help='Account code 41010102'
    )
    revenue_related_party = fields.Monetary(
        string='Revenue - Related Party (41020101)',
        compute='_compute_revenue',
        store=True,
        currency_field='currency_id',
        help='Account code 41020101'
    )
    
    total_sales = fields.Monetary(
        string='Total Sales',
        compute='_compute_revenue',
        store=True,
        currency_field='currency_id',
        help='Sum of all revenue accounts'
    )
    
    is_vat_registered = fields.Boolean(
        string='VAT Registered',
        compute='_compute_vat_status',
        store=True,
        help='Checked if company has VAT registration number'
    )
    
    email_sent = fields.Boolean(
        string='Email Sent',
        default=False,
        help='Indicates if threshold notification email was sent'
    )
    
    vat_verified = fields.Boolean(
        string='VAT Verified',
        default=False,
        help='Manually mark if VAT status is verified'
    )
    
    threshold_action = fields.Selection(
        [
            ('none', 'No Action Required'),
            ('voluntary_register', 'Voluntary VAT Registration'),
            ('register_warning', 'Approaching Mandatory VAT Registration'),
            ('register', 'Register for VAT'),
            ('cancel_warning', 'Approaching VAT Cancellation'),
            ('cancel', 'Cancel VAT Registration'),
        ],
        string='Action Required',
        default='none',
        compute='_compute_threshold_action',
        store=True
    )
    
    last_check_date = fields.Datetime(
        string='Last Check Date',
        default=fields.Datetime.now
    )
    
    email_sent_date = fields.Datetime(
        string='Email Sent Date',
        readonly=True
    )
    
    # Rolling Period Fields
    date_from = fields.Date(
        string='Date From',
        compute='_compute_rolling_period',
        store=True,
        help='Start date of 9-month rolling period'
    )
    date_to = fields.Date(
        string='Date To',
        compute='_compute_rolling_period',
        store=True,
        help='End date of rolling period (today)'
    )
    rolling_period_months = fields.Integer(
        string='Rolling Period (Months)',
        default=9,
        help='Number of months for rolling period calculation'
    )
    
    # Rolling Period Revenue (9 months)
    rolling_revenue_uae_clients = fields.Monetary(
        string='Rolling Revenue - UAE Clients',
        compute='_compute_rolling_revenue',
        store=True,
        currency_field='currency_id',
        help='UAE Clients revenue for rolling 9-month period'
    )
    rolling_revenue_international_clients = fields.Monetary(
        string='Rolling Revenue - International Clients',
        compute='_compute_rolling_revenue',
        store=True,
        currency_field='currency_id',
        help='International Clients revenue for rolling 9-month period'
    )
    rolling_revenue_related_party = fields.Monetary(
        string='Rolling Revenue - Related Party',
        compute='_compute_rolling_revenue',
        store=True,
        currency_field='currency_id',
        help='Related Party revenue for rolling 9-month period'
    )
    rolling_total_sales = fields.Monetary(
        string='Rolling Total Sales (9 Months)',
        compute='_compute_rolling_revenue',
        store=True,
        currency_field='currency_id',
        help='Total sales for rolling 9-month period'
    )
    threshold_breach_date = fields.Date(
        string='Threshold Breach Date',
        compute='_compute_threshold_breach_date',
        store=True,
        help='Date on which the company first crossed the current VAT threshold within the rolling period.'
    )

    @api.model
    def _get_float_config_parameter(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @api.model
    def _get_threshold_configuration(self):
        return {
            'cancel_threshold': self._get_float_config_parameter(
                'vat_threshold.cancel_threshold',
                187500.0,
            ),
            'voluntary_threshold': self._get_float_config_parameter(
                'vat_threshold.voluntary_threshold',
                210000.0,
            ),
            'mandatory_threshold': self._get_float_config_parameter(
                'vat_threshold.mandatory_threshold',
                375000.0,
            ),
            'mandatory_warning_threshold': self._get_float_config_parameter(
                'vat_threshold.mandatory_warning_threshold',
                350000.0,
            ),
            'cancellation_warning_threshold': self._get_float_config_parameter(
                'vat_threshold.cancellation_warning_threshold',
                200000.0,
            ),
        }

    @api.model
    def _get_cancellation_threshold(self):
        return self._get_threshold_configuration()['cancel_threshold']

    @api.model
    def _get_voluntary_registration_threshold(self):
        return self._get_threshold_configuration()['voluntary_threshold']

    @api.model
    def _get_mandatory_registration_threshold(self):
        return self._get_threshold_configuration()['mandatory_threshold']

    @api.model
    def _get_mandatory_registration_warning_threshold(self):
        return self._get_threshold_configuration()['mandatory_warning_threshold']

    @api.model
    def _get_cancellation_warning_threshold(self):
        return self._get_threshold_configuration()['cancellation_warning_threshold']

    @api.model
    def _format_threshold_amount(self, amount):
        return f"{amount:,.2f} AED"

    @api.depends('company_id')
    def _compute_revenue(self):
        for record in self:
            if not record.company_id:
                record.revenue_uae_clients = 0.0
                record.revenue_international_clients = 0.0
                record.revenue_related_party = 0.0
                record.total_sales = 0.0
                continue
            
            # Get account move lines for revenue accounts
            # Account codes: 41010101, 41010102, 41020101
            account_codes = ['41010101', '41010102', '41020101']
            
            # Search in the target company context so company-dependent codes resolve correctly.
            account_env = self.env['account.account'].with_company(record.company_id).sudo()
            accounts = account_env.search([
                ('code', 'in', account_codes),
                ('company_ids', 'in', [record.company_id.id])
            ])
            
            # Initialize values
            record.revenue_uae_clients = 0.0
            record.revenue_international_clients = 0.0
            record.revenue_related_party = 0.0
            
            balance_by_account = self._get_account_balances(record.company_id, accounts.ids)

            balance_by_code = defaultdict(float)
            for account in accounts:
                balance_by_code[account.code] += balance_by_account.get(account.id, 0.0)

            record.revenue_uae_clients = balance_by_code['41010101']
            record.revenue_international_clients = balance_by_code['41010102']
            record.revenue_related_party = balance_by_code['41020101']
            record.total_sales = (
                record.revenue_uae_clients + 
                record.revenue_international_clients + 
                record.revenue_related_party
            )

    @api.depends('company_id', 'company_id.vat_registration_number')
    def _compute_vat_status(self):
        for record in self:
            # Check if company has VAT registration number (from company_exte module)
            record.is_vat_registered = bool(record.company_id.vat_registration_number)

    @api.depends('last_check_date', 'rolling_period_months')
    def _compute_rolling_period(self):
        """Calculate rolling period dates (default 9 months)"""
        from dateutil.relativedelta import relativedelta
        
        for record in self:
            # Use today as end date
            date_to = fields.Date.today()
            # Calculate start date by subtracting months
            date_from = date_to - relativedelta(months=record.rolling_period_months)
            
            record.date_to = date_to
            record.date_from = date_from

    @api.depends('company_id', 'date_from', 'date_to', 'rolling_period_months')
    def _compute_rolling_revenue(self):
        """Calculate revenue for rolling 9-month period"""
        from dateutil.relativedelta import relativedelta
        
        for record in self:
            if not record.company_id:
                record.rolling_revenue_uae_clients = 0.0
                record.rolling_revenue_international_clients = 0.0
                record.rolling_revenue_related_party = 0.0
                record.rolling_total_sales = 0.0
                continue
            
            # Ensure dates are computed
            if not record.date_from or not record.date_to:
                date_to = fields.Date.today()
                date_from = date_to - relativedelta(months=record.rolling_period_months or 9)
            else:
                date_from = record.date_from
                date_to = record.date_to
            
            _logger.info("Computing rolling revenue for company: %s, date_from: %s, date_to: %s", 
                        record.company_id.name, date_from, date_to)
            
            # Account codes for revenue - using LIKE for flexible matching
            # 41010101 = UAE Clients, 41010102 = International Clients, 41020101 = Related Party
            account_env = self.env['account.account'].with_company(record.company_id).sudo()
            domain_uae = [
                ('code', '=like', '41010101%'),
                ('company_ids', 'in', [record.company_id.id])
            ]
            domain_intl = [
                ('code', '=like', '41010102%'),
                ('company_ids', 'in', [record.company_id.id])
            ]
            domain_related = [
                ('code', '=like', '41020101%'),
                ('company_ids', 'in', [record.company_id.id])
            ]
            
            # Initialize values
            record.rolling_revenue_uae_clients = 0.0
            record.rolling_revenue_international_clients = 0.0
            record.rolling_revenue_related_party = 0.0
            
            accounts_uae = account_env.search(domain_uae)
            record.rolling_revenue_uae_clients = self._get_account_balance(
                record.company_id,
                accounts_uae.ids,
                date_from=date_from,
                date_to=date_to,
            )
            _logger.info("UAE rolling revenue for %s: %s", record.company_id.name, record.rolling_revenue_uae_clients)

            accounts_intl = account_env.search(domain_intl)
            record.rolling_revenue_international_clients = self._get_account_balance(
                record.company_id,
                accounts_intl.ids,
                date_from=date_from,
                date_to=date_to,
            )
            _logger.info("Intl rolling revenue for %s: %s", record.company_id.name, record.rolling_revenue_international_clients)

            accounts_related = account_env.search(domain_related)
            record.rolling_revenue_related_party = self._get_account_balance(
                record.company_id,
                accounts_related.ids,
                date_from=date_from,
                date_to=date_to,
            )
            _logger.info("Related rolling revenue for %s: %s", record.company_id.name, record.rolling_revenue_related_party)
            
            record.rolling_total_sales = (
                record.rolling_revenue_uae_clients + 
                record.rolling_revenue_international_clients + 
                record.rolling_revenue_related_party
            )
            _logger.info("Total rolling sales for %s: %s", record.company_id.name, record.rolling_total_sales)

    @api.depends('rolling_total_sales', 'is_vat_registered')
    def _compute_threshold_action(self):
        """
        Logic based on 9-month rolling period sales and configured thresholds:
        - VAT Registered + Sales < cancellation threshold → Cancel VAT
        - VAT Registered + Sales < cancellation warning threshold → Cancellation warning
        - Not VAT Registered + Sales >= mandatory warning threshold → Mandatory VAT warning
        - Not VAT Registered + Sales >= voluntary threshold → Voluntary VAT registration
        - Not VAT Registered + Sales > mandatory threshold → Register VAT
        """
        thresholds = self._get_threshold_configuration()
        cancel_threshold = thresholds['cancel_threshold']
        voluntary_threshold = thresholds['voluntary_threshold']
        mandatory_threshold = thresholds['mandatory_threshold']
        mandatory_warning_threshold = thresholds['mandatory_warning_threshold']
        cancellation_warning_threshold = thresholds['cancellation_warning_threshold']
        
        for record in self:
            # Use rolling_total_sales (9-month period) for threshold calculation
            sales = record.rolling_total_sales or 0.0
            
            if record.is_vat_registered:
                if sales < cancel_threshold:
                    record.threshold_action = 'cancel'
                elif sales < cancellation_warning_threshold:
                    record.threshold_action = 'cancel_warning'
                else:
                    record.threshold_action = 'none'
            else:
                if sales > mandatory_threshold:
                    record.threshold_action = 'register'
                elif sales >= mandatory_warning_threshold:
                    record.threshold_action = 'register_warning'
                elif sales >= voluntary_threshold:
                    record.threshold_action = 'voluntary_register'
                else:
                    record.threshold_action = 'none'

    @api.depends('company_id', 'date_from', 'date_to', 'threshold_action', 'rolling_total_sales')
    def _compute_threshold_breach_date(self):
        """Compute the first date the company crossed the active VAT threshold."""
        thresholds = self._get_threshold_configuration()
        threshold_map = {
            'voluntary_register': thresholds['voluntary_threshold'],
            'register_warning': thresholds['mandatory_warning_threshold'],
            'register': thresholds['mandatory_threshold'],
        }

        for record in self:
            record.threshold_breach_date = False

            threshold_amount = threshold_map.get(record.threshold_action)
            if not record.company_id or not threshold_amount or not record.date_from or not record.date_to:
                continue

            account_env = self.env['account.account'].with_company(record.company_id).sudo()
            accounts = account_env.search([
                ('company_ids', 'in', [record.company_id.id]),
                '|',
                '|',
                ('code', '=like', '41010101%'),
                ('code', '=like', '41010102%'),
                ('code', '=like', '41020101%'),
            ])
            record.threshold_breach_date = self._get_threshold_breach_date(
                record.company_id,
                accounts.ids,
                threshold_amount,
                date_from=record.date_from,
                date_to=record.date_to,
            )

    def _get_account_balances(self, company, account_ids, date_from=None, date_to=None):
        """Return a mapping of account id -> balance for posted journal items."""
        if not account_ids:
            return {}

        domain = [
            ('account_id', 'in', account_ids),
            ('move_id.state', '=', 'posted'),
            ('company_id', '=', company.id),
        ]
        if date_from:
            domain.append(('move_id.date', '>=', date_from))
        if date_to:
            domain.append(('move_id.date', '<=', date_to))

        grouped = self.env['account.move.line'].with_company(company).sudo().read_group(
            domain,
            ['account_id', 'credit:sum', 'debit:sum'],
            ['account_id'],
            lazy=False,
        )
        return {
            row['account_id'][0]: (row.get('credit', 0.0) or 0.0) - (row.get('debit', 0.0) or 0.0)
            for row in grouped
            if row.get('account_id')
        }

    def _get_account_balance(self, company, account_ids, date_from=None, date_to=None):
        """Return the total balance for a set of accounts (sum of all account balances)."""
        balances = self._get_account_balances(company, account_ids, date_from=date_from, date_to=date_to)
        return sum(balances.values()) if balances else 0.0

    def _get_threshold_breach_date(self, company, account_ids, threshold_amount, date_from=None, date_to=None):
        """Return the first accounting date where cumulative sales crossed the threshold."""
        if not account_ids or not threshold_amount:
            return False

        domain = [
            ('account_id', 'in', account_ids),
            ('move_id.state', '=', 'posted'),
            ('company_id', '=', company.id),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))

        move_lines = self.env['account.move.line'].with_company(company).sudo().search(
            domain,
            order='date asc, id asc',
        )

        cumulative_sales = 0.0
        for line in move_lines:
            cumulative_sales += (line.credit or 0.0) - (line.debit or 0.0)
            if cumulative_sales >= threshold_amount:
                return line.date
        return False

    @api.model
    def _get_configured_report_users(self):
        """Return configured VAT recipient users."""
        param_value = self.env['ir.config_parameter'].sudo().get_param(
            'vat_threshold.daily_report_user_ids',
            '',
        )
        user_ids = [
            int(raw_id)
            for raw_id in param_value.split(',')
            if raw_id.strip().isdigit()
        ]
        if not user_ids:
            return self.env['res.users']
        return self.env['res.users'].sudo().browse(user_ids).exists().filtered(
            lambda user: user.active and not user.share and bool(user.email)
        )

    @api.model
    def _get_daily_report_user_batches(self, records=None, recipient_users=None):
        """Group VAT threshold records per configured user based on assigned companies."""
        records = (records or self.search([])).sudo()
        recipient_users = recipient_users or self._get_configured_report_users()
        batches = {}

        if not records or not recipient_users:
            return batches

        target_company_ids = set(records.mapped('company_id').ids)
        company_to_user_ids = defaultdict(set)

        for user in recipient_users:
            assigned_company_ids = target_company_ids.intersection(user.company_ids.ids)
            if not assigned_company_ids:
                continue
            batches[user.id] = {
                'user': user,
                'register_warning_list': self.browse(),
                'register_list': self.browse(),
                'voluntary_register_list': self.browse(),
                'cancel_warning_list': self.browse(),
                'cancel_list': self.browse(),
                'no_action_list': self.browse(),
            }
            for company_id in assigned_company_ids:
                company_to_user_ids[company_id].add(user.id)

        for record in records:
            for user_id in company_to_user_ids.get(record.company_id.id, set()):
                batch = batches[user_id]
                if record.threshold_action == 'register_warning':
                    batch['register_warning_list'] |= record
                elif record.threshold_action == 'register':
                    batch['register_list'] |= record
                elif record.threshold_action == 'voluntary_register':
                    batch['voluntary_register_list'] |= record
                elif record.threshold_action == 'cancel_warning':
                    batch['cancel_warning_list'] |= record
                elif record.threshold_action == 'cancel':
                    batch['cancel_list'] |= record
                else:
                    batch['no_action_list'] |= record

        return {
            user_id: batch
            for user_id, batch in batches.items()
            if (
                batch['register_warning_list']
                or batch['register_list']
                or batch['voluntary_register_list']
                or batch['cancel_warning_list']
                or batch['cancel_list']
                or batch['no_action_list']
            )
        }

    def _get_threshold_notification_recipient_emails(self):
        """Return configured user emails for this company's threshold notifications."""
        self.ensure_one()
        recipient_users = self._get_configured_report_users()
        if not recipient_users:
            return []
        return recipient_users.filtered(
            lambda user: self.company_id.id in user.company_ids.ids
        ).mapped('email')

    @api.model
    def _get_additional_report_recipient_emails(self):
        """Return additional configured emails that should receive the full report."""
        recipients_str = self.env['ir.config_parameter'].sudo().get_param(
            'vat_threshold.daily_report_recipients',
            '',
        )
        emails = [email.strip() for email in recipients_str.split(',') if email.strip()]
        return list(dict.fromkeys(emails))

    def _send_daily_report_email(
        self,
        email_to,
        register_warning_list,
        register_list,
        voluntary_register_list,
        cancel_warning_list,
        cancel_list,
        no_action_list,
        subject_prefix='',
    ):
        if not email_to:
            return False

        email_body = self._prepare_daily_report_body(
            register_warning_list,
            register_list,
            voluntary_register_list,
            cancel_warning_list,
            cancel_list,
            no_action_list,
        )
        mail_values = {
            'subject': f'{subject_prefix}Daily VAT Threshold Report - {fields.Date.today()}',
            'body_html': email_body,
            'email_to': email_to,
            'email_from': self.env.user.email or 'noreply@example.com',
        }
        self.env['mail.mail'].create(mail_values).send()
        return True

    @api.model
    def _send_consolidated_threshold_report(
        self,
        records=None,
        subject_prefix='',
        include_no_action=False,
        mark_sent=False,
    ):
        """
        Send a single consolidated report per configured user and a full report to
        additional email recipients.
        """
        self._ensure_system_user()
        records = (records or self.search([])).sudo()
        records = records.filtered(
            lambda record: record.threshold_action in (
                'register_warning',
                'register',
                'voluntary_register',
                'cancel_warning',
                'cancel',
                'none',
            )
        )

        register_warning_list = records.filtered(
            lambda record: record.threshold_action == 'register_warning'
        )
        register_list = records.filtered(lambda record: record.threshold_action == 'register')
        voluntary_register_list = records.filtered(
            lambda record: record.threshold_action == 'voluntary_register'
        )
        cancel_warning_list = records.filtered(
            lambda record: record.threshold_action == 'cancel_warning'
        )
        cancel_list = records.filtered(lambda record: record.threshold_action == 'cancel')
        no_action_list = (
            records.filtered(lambda record: record.threshold_action == 'none')
            if include_no_action else self.browse()
        )
        action_records = (
            register_warning_list
            | register_list
            | voluntary_register_list
            | cancel_warning_list
            | cancel_list
        )

        if not action_records:
            return {
                'sent_records': self.browse(),
                'sent_to': [],
            }

        sent_records = self.browse()
        sent_to = []
        recipient_users = self._get_configured_report_users()
        batch_records = action_records | no_action_list if include_no_action else action_records

        if recipient_users:
            user_batches = self._get_daily_report_user_batches(
                batch_records,
                recipient_users=recipient_users,
            )
            for batch in user_batches.values():
                if (
                    not batch['register_warning_list']
                    and not batch['register_list']
                    and not batch['voluntary_register_list']
                    and not batch['cancel_warning_list']
                    and not batch['cancel_list']
                ):
                    continue
                try:
                    if self._send_daily_report_email(
                        batch['user'].email,
                        batch['register_warning_list'],
                        batch['register_list'],
                        batch['voluntary_register_list'],
                        batch['cancel_warning_list'],
                        batch['cancel_list'],
                        batch['no_action_list'] if include_no_action else self.browse(),
                        subject_prefix=subject_prefix,
                    ):
                        sent_records |= (
                            batch['register_warning_list']
                            | batch['register_list']
                            | batch['voluntary_register_list']
                            | batch['cancel_warning_list']
                            | batch['cancel_list']
                        )
                        sent_to.append(batch['user'].email)
                except Exception as error:
                    _logger.error(
                        "Failed to send consolidated VAT report to %s: %s",
                        batch['user'].email,
                        str(error),
                    )

        additional_emails = self._get_additional_report_recipient_emails()
        if additional_emails:
            try:
                if self._send_daily_report_email(
                    ', '.join(additional_emails),
                    register_warning_list,
                    register_list,
                    voluntary_register_list,
                    cancel_warning_list,
                    cancel_list,
                    no_action_list if include_no_action else self.browse(),
                    subject_prefix=subject_prefix,
                ):
                    sent_records |= action_records
                    sent_to.extend(additional_emails)
            except Exception as error:
                _logger.error(
                    "Failed to send consolidated VAT report to additional recipients %s: %s",
                    ', '.join(additional_emails),
                    str(error),
                )

        if not recipient_users and not additional_emails and not include_no_action:
            for record in action_records:
                if record.send_threshold_notification():
                    sent_records |= record

        if mark_sent and sent_records:
            sent_records.write({
                'email_sent': True,
                'email_sent_date': fields.Datetime.now(),
            })

        return {
            'sent_records': sent_records,
            'sent_to': list(dict.fromkeys(sent_to)),
        }

    def _is_system_user(self):
        return self.env.uid == SUPERUSER_ID or self.env.user.has_group('base.group_system')

    def _ensure_system_user(self):
        if not self._is_system_user():
            raise AccessError(_('This action is restricted to system administrators.'))

    def _ensure_vat_operator(self):
        if self._is_system_user() or self.env.user.has_group('vat_threshold.group_custom_module_vat_threshold'):
            return
        raise AccessError(_('This action requires VAT Threshold permission.'))

    def _ensure_vat_operator_company_access(self):
        self._ensure_vat_operator()
        if self._is_system_user() or not self:
            return

        allowed_company_ids = set(self.env.user.company_ids.ids)
        denied_records = self.sudo().filtered(
            lambda record: record.company_id.id not in allowed_company_ids
        )
        if denied_records:
            raise AccessError(_('You can only operate VAT Threshold records for your allowed companies.'))

    def _refresh_threshold_decisions(self):
        """Re-evaluate action and breach dates without recalculating revenue figures."""
        previous_actions = {}
        if self:
            self.env.cr.execute("SELECT id, threshold_action FROM vat_threshold WHERE id IN %s", (tuple(self.ids),))
            previous_actions = {row[0]: row[1] for row in self.env.cr.fetchall()}

        for record in self:
            previous_action = previous_actions.get(record.id)
            record._compute_threshold_action()
            record._compute_threshold_breach_date()
            vals = {'last_check_date': fields.Datetime.now()}
            if record.threshold_action != previous_action:
                vals.update({
                    'email_sent': False,
                    'email_sent_date': False,
                })
            record.write(vals)

    def _refresh_threshold_values(self):
        """Recompute all stored VAT threshold values for the current recordset."""
        for record in self:
            record._compute_rolling_period()
            record._compute_rolling_revenue()
            record._compute_revenue()
            record._compute_vat_status()
            record._compute_threshold_action()
            record._compute_threshold_breach_date()
            record.write({
                'last_check_date': fields.Datetime.now(),
                'email_sent': False,
                'email_sent_date': False,
            })

    def action_check_threshold(self):
        """Manual action to check threshold and send consolidated email if needed."""
        self._ensure_system_user()
        self._refresh_threshold_values()

        pending_records = self.filtered(
            lambda record: record.threshold_action != 'none' and not record.email_sent
        )
        self._send_consolidated_threshold_report(
            pending_records,
            mark_sent=True,
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def send_threshold_notification(self):
        """Send email notification based on threshold action"""
        self.ensure_one()
        self._ensure_system_user()
        
        if self.threshold_action == 'none':
            return False
        
        # Find the appropriate email template from the module XML IDs.
        template_map = {
            'register_warning': 'vat_threshold.email_template_vat_register_warning',
            'register': 'vat_threshold.email_template_vat_register',
            'voluntary_register': 'vat_threshold.email_template_vat_voluntary_register',
            'cancel_warning': 'vat_threshold.email_template_vat_cancel_warning',
            'cancel': 'vat_threshold.email_template_vat_cancel',
        }
        template_xmlid = template_map.get(self.threshold_action)
        template = self.env.ref(template_xmlid, raise_if_not_found=False) if template_xmlid else False
        
        if not template:
            _logger.warning("Email template not found for action: %s", self.threshold_action)
            return False
        
        # Send the email
        try:
            recipient_emails = self._get_threshold_notification_recipient_emails()
            email_values = {}
            if recipient_emails:
                email_values['email_to'] = ', '.join(recipient_emails)
            template.send_mail(self.id, force_send=True, email_values=email_values or None)
            self.write({
                'email_sent': True,
                'email_sent_date': fields.Datetime.now()
            })
            _logger.info(
                "VAT threshold notification sent for company: %s to %s",
                self.company_id.name,
                email_values.get('email_to') or self.company_id.email,
            )
            return True
        except Exception as e:
            _logger.error("Failed to send VAT threshold email: %s", str(e))
            return False

    @api.model
    def _cron_check_vat_threshold(self):
        """Cron job to refresh VAT thresholds for all companies."""
        _logger.info("Starting VAT threshold cron check (9-month rolling period)...")

        companies = self.env['res.company'].search([])
        processed_records = self.browse()

        for company in companies:
            threshold_record = self.search([('company_id', '=', company.id)], limit=1)

            if not threshold_record:
                threshold_record = self.create({'company_id': company.id})

            threshold_record._refresh_threshold_values()
            processed_records |= threshold_record

        pending_records = processed_records.filtered(
            lambda record: record.threshold_action != 'none' and not record.email_sent
        )
        _logger.info(
            "VAT threshold cron check completed (9-month rolling period). Pending consolidated notifications: %d",
            len(pending_records),
        )

        return pending_records

    def action_verify_vat(self):
        """Mark VAT as verified"""
        self._ensure_vat_operator_company_access()
        self.sudo().write({'vat_verified': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_reset_email(self):
        """Reset email sent status to allow re-sending"""
        self._ensure_vat_operator_company_access()
        self.sudo().write({
            'email_sent': False,
            'email_sent_date': False
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_manual_update_rolling_period(self):
        """Manual refresh of rolling VAT values."""
        self._ensure_vat_operator_company_access()
        self.sudo()._refresh_threshold_values()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_create_missing_company_records(self):
        """Create VAT threshold records for all companies that don't have one - Admin only"""
        self._ensure_system_user()
        companies = self.env['res.company'].search([])
        existing_thresholds = self.sudo().search([])
        existing_company_ids = existing_thresholds.mapped('company_id.id')
        
        created_count = 0
        for company in companies:
            if company.id not in existing_company_ids:
                self.create({'company_id': company.id})
                created_count += 1
                _logger.info("Created VAT threshold record for company: %s", company.name)
        
        # Force recompute all records
        all_records = self.search([])
        all_records._refresh_threshold_values()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_recompute_all_records(self):
        """Force recompute on selected records, or all records if nothing is selected."""
        self._ensure_vat_operator()
        if self:
            records = self
        elif self._is_system_user():
            records = self.sudo().search([])
        else:
            records = self.search([])
        records._ensure_vat_operator_company_access()
        records.sudo()._refresh_threshold_values()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_batch_mark_verified(self):
        """Mark selected records as VAT verified."""
        self._ensure_vat_operator_company_access()
        self.sudo().write({'vat_verified': True})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_batch_mark_unverified(self):
        """Mark selected records as VAT unverified."""
        self._ensure_vat_operator_company_access()
        self.sudo().write({'vat_verified': False})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_open_settings(self):
        """Open VAT Threshold Settings."""
        self._ensure_system_user()
        return {
            'type': 'ir.actions.act_window',
            'name': 'VAT Threshold Settings',
            'res_model': 'res.config.settings',
            'view_mode': 'form',
            'target': 'new',
            'view_id': self.env.ref('vat_threshold.vat_threshold_config_view_form').id,
        }

    def action_test_send_email(self):
        """Test button to send a test email to configured recipients"""
        self._ensure_system_user()
        all_records = self.search([])
        result = self._send_consolidated_threshold_report(
            all_records,
            subject_prefix='[TEST] ',
            include_no_action=True,
        )

        if result['sent_to']:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f'Test email sent successfully to: {", ".join(result["sent_to"])}',
                    'type': 'success',
                    'sticky': False,
                }
            }

        if not self._get_configured_report_users() and not self._get_additional_report_recipient_emails():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No report recipients configured! Please configure users or email addresses in Settings first.',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Info',
                'message': 'No companies currently require VAT action, so no test report was sent.',
                'type': 'warning',
                'sticky': False,
            }
        }

    @api.model
    def _cron_send_daily_report(self):
        """Cron job to send pending consolidated VAT notifications."""
        _logger.info("Starting daily VAT threshold email report...")

        pending_records = self.search([
            ('threshold_action', '!=', 'none'),
            ('email_sent', '=', False),
        ])
        if not pending_records:
            _logger.info("No pending threshold actions detected - skipping email report")
            return

        result = self._send_consolidated_threshold_report(
            pending_records,
            mark_sent=True,
        )
        if result['sent_to']:
            _logger.info(
                "Daily VAT threshold report sent to: %s",
                ', '.join(result['sent_to']),
            )
            return

        _logger.info("No matching recipients found for pending VAT threshold report")

    def _prepare_daily_report_body(
        self,
        register_warning_list,
        register_list,
        voluntary_register_list,
        cancel_warning_list,
        cancel_list,
        no_action_list,
    ):
        """Prepare HTML body for daily consolidated report"""
        thresholds = self._get_threshold_configuration()
        cancel_threshold = self._format_threshold_amount(thresholds['cancel_threshold'])
        cancellation_warning_threshold = self._format_threshold_amount(
            thresholds['cancellation_warning_threshold']
        )
        voluntary_threshold = self._format_threshold_amount(thresholds['voluntary_threshold'])
        mandatory_warning_threshold = self._format_threshold_amount(
            thresholds['mandatory_warning_threshold']
        )
        mandatory_threshold = self._format_threshold_amount(thresholds['mandatory_threshold'])
        
        def format_currency(amount):
            return f"{amount:,.2f} AED"

        register_warning_html = ""
        if register_warning_list:
            register_warning_html = """
            <h3 style="color: #f0ad4e;">📋 LIST 1: COMPANIES APPROACHING MANDATORY VAT REGISTRATION</h3>
            <table style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                <tr style="background-color: #f5f5f5;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Company</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Rolling Sales (9 Months)</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Warning Date</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Status</th>
                </tr>
            """
            for rec in register_warning_list:
                register_warning_html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{rec.company_id.name}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{format_currency(rec.rolling_total_sales)}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{rec.threshold_breach_date or '-'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #f0ad4e;">⚠️ Mandatory VAT Warning</td>
                </tr>
                """
            register_warning_html += f"""
            </table>
            <p><strong>Total: {len(register_warning_list)} companies are approaching mandatory VAT registration</strong></p>
            """
        else:
            register_warning_html = """
            <h3 style="color: #5cb85c;">📋 LIST 1: COMPANIES APPROACHING MANDATORY VAT REGISTRATION</h3>
            <p style="color: #5cb85c; padding: 10px; background-color: #dff0d8; border-radius: 5px;">✅ No companies are currently near the mandatory VAT registration threshold.</p>
            """
        
        # Build register list HTML
        register_html = ""
        if register_list:
            register_html = """
            <h3 style="color: #d9534f;">📋 LIST 2: COMPANIES REQUIRING VAT REGISTRATION</h3>
            <table style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                <tr style="background-color: #f5f5f5;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Company</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Rolling Sales (9 Months)</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Breach Date</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Status</th>
                </tr>
            """
            for rec in register_list:
                register_html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{rec.company_id.name}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{format_currency(rec.rolling_total_sales)}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{rec.threshold_breach_date or '-'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #d9534f;">⚠️ Register VAT</td>
                </tr>
                """
            register_html += f"""
            </table>
            <p><strong>Total: {len(register_list)} companies require VAT registration</strong></p>
            """
        else:
            register_html = """
            <h3 style="color: #5cb85c;">📋 LIST 2: COMPANIES REQUIRING VAT REGISTRATION</h3>
            <p style="color: #5cb85c; padding: 10px; background-color: #dff0d8; border-radius: 5px;">✅ No companies require VAT registration at this time.</p>
            """

        voluntary_register_html = ""
        if voluntary_register_list:
            voluntary_register_html = """
            <h3 style="color: #17a2b8;">📋 LIST 3: COMPANIES ELIGIBLE FOR VOLUNTARY VAT REGISTRATION</h3>
            <table style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                <tr style="background-color: #f5f5f5;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Company</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Rolling Sales (9 Months)</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Breach Date</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Status</th>
                </tr>
            """
            for rec in voluntary_register_list:
                voluntary_register_html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{rec.company_id.name}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{format_currency(rec.rolling_total_sales)}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{rec.threshold_breach_date or '-'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #17a2b8;">⚠️ Voluntary VAT Registration</td>
                </tr>
                """
            voluntary_register_html += f"""
            </table>
            <p><strong>Total: {len(voluntary_register_list)} companies are eligible for voluntary VAT registration</strong></p>
            """
        else:
            voluntary_register_html = """
            <h3 style="color: #5cb85c;">📋 LIST 3: COMPANIES ELIGIBLE FOR VOLUNTARY VAT REGISTRATION</h3>
            <p style="color: #5cb85c; padding: 10px; background-color: #dff0d8; border-radius: 5px;">✅ No companies are currently eligible for voluntary VAT registration.</p>
            """

        cancel_warning_html = ""
        if cancel_warning_list:
            cancel_warning_html = """
            <h3 style="color: #fd7e14;">📋 LIST 4: COMPANIES APPROACHING VAT CANCELLATION</h3>
            <table style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                <tr style="background-color: #f5f5f5;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Company</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Rolling Sales (9 Months)</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Status</th>
                </tr>
            """
            for rec in cancel_warning_list:
                cancel_warning_html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{rec.company_id.name}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{format_currency(rec.rolling_total_sales)}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #fd7e14;">⚠️ VAT Cancellation Warning</td>
                </tr>
                """
            cancel_warning_html += f"""
            </table>
            <p><strong>Total: {len(cancel_warning_list)} companies are approaching VAT cancellation</strong></p>
            """
        else:
            cancel_warning_html = """
            <h3 style="color: #5cb85c;">📋 LIST 4: COMPANIES APPROACHING VAT CANCELLATION</h3>
            <p style="color: #5cb85c; padding: 10px; background-color: #dff0d8; border-radius: 5px;">✅ No companies are currently near the VAT cancellation threshold.</p>
            """

        cancel_html = ""
        if cancel_list:
            cancel_html = """
            <h3 style="color: #0275d8;">📋 LIST 5: COMPANIES REQUIRING VAT CANCELLATION</h3>
            <table style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                <tr style="background-color: #f5f5f5;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Company</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Rolling Sales (9 Months)</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Status</th>
                </tr>
            """
            for rec in cancel_list:
                cancel_html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{rec.company_id.name}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{format_currency(rec.rolling_total_sales)}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: center; color: #0275d8;">⚠️ Cancel VAT</td>
                </tr>
                """
            cancel_html += f"""
            </table>
            <p><strong>Total: {len(cancel_list)} companies eligible for VAT cancellation</strong></p>
            """
        else:
            cancel_html = """
            <h3 style="color: #5cb85c;">📋 LIST 5: COMPANIES REQUIRING VAT CANCELLATION</h3>
            <p style="color: #5cb85c; padding: 10px; background-color: #dff0d8; border-radius: 5px;">✅ No companies require VAT cancellation at this time.</p>
            """
        
        # Summary
        total_checked = (
            len(register_warning_list)
            + len(register_list)
            + len(voluntary_register_list)
            + len(cancel_warning_list)
            + len(cancel_list)
            + len(no_action_list)
        )
        summary_html = f"""
        <h3 style="color: #333;">📊 SUMMARY</h3>
        <table style="border-collapse: collapse; width: 100%; max-width: 400px; margin-top: 15px;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #f5f5f5;"><strong>Total Companies Checked:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{total_checked}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #fff3cd;"><strong>Approaching Mandatory Registration:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: #f0ad4e;">{len(register_warning_list)}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #fcf8e3;"><strong>Require Registration:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: #d9534f;">{len(register_list)}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #d9edf7;"><strong>Eligible for Voluntary Registration:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: #17a2b8;">{len(voluntary_register_list)}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #ffe5d0;"><strong>Approaching Cancellation:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: #fd7e14;">{len(cancel_warning_list)}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #e7f3fe;"><strong>Require Cancellation:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: #0275d8;">{len(cancel_list)}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: #dff0d8;"><strong>No Action Required:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: #5cb85c;">{len(no_action_list)}</td>
            </tr>
        </table>
        """
        
        # Full email body
        body = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; max-width: 800px;">
            <h2 style="color: #333; border-bottom: 2px solid #875A7B; padding-bottom: 10px;">
                Daily VAT Threshold Report - {fields.Date.today()}
            </h2>
            
            <p>Dear Team,</p>
            <p>Please find below the daily VAT threshold status report based on the 9-month rolling period calculation.</p>
            
            <hr style="border: 1px solid #eee; margin: 20px 0;"/>
            
            {register_warning_html}
            
            <hr style="border: 1px solid #eee; margin: 20px 0;"/>
            
            {register_html}
            
            <hr style="border: 1px solid #eee; margin: 20px 0;"/>

            {voluntary_register_html}

            <hr style="border: 1px solid #eee; margin: 20px 0;"/>

            {cancel_warning_html}

            <hr style="border: 1px solid #eee; margin: 20px 0;"/>
            
            {cancel_html}
            
            <hr style="border: 1px solid #eee; margin: 20px 0;"/>
            
            {summary_html}
            
            <br/>
            <p style="color: #666; font-size: 12px;">
                <strong>Threshold Limits:</strong><br/>
                • Mandatory Registration Warning: Sales >= {mandatory_warning_threshold} and <= {mandatory_threshold} (9-month rolling)<br/>
                • Registration Required: Sales > {mandatory_threshold} (9-month rolling)<br/>
                • Voluntary Registration Available: Sales >= {voluntary_threshold} and < {mandatory_warning_threshold} (9-month rolling)<br/>
                • Cancellation Warning: Sales < {cancellation_warning_threshold} and >= {cancel_threshold} (9-month rolling)<br/>
                • Cancellation Possible: Sales < {cancel_threshold} (9-month rolling)
            </p>
            
            <br/>
            <p>Best regards,</p>
            <p><strong>System Administrator</strong></p>
        </div>
        """
        
        return body
