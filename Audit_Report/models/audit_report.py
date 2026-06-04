import csv
import json
import logging
import re
import time
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

CT_EXPENSE_ACCOUNT_CODES = ('51270101',)
CT_LIABILITY_ACCOUNT_CODES = ('22040101',)
CASHFLOW_CURRENT_LIABILITY_PREFIXES = ('220101', '220103')
LONG_TERM_DEPOSITS_PREFIX = '110501'
SECURITY_DEPOSIT_ACCOUNT_CODE = '11050102'
RELATED_PARTY_LOAN_PREFIX = '2102'
DIRECTOR_SALARY_ACCOUNT_CODE = '51070101'
PRIOR_YEAR_ADJUSTMENT_ACCOUNT_CODE = '31010501'
GAIN_ON_DISPOSAL_ACCOUNT_CODE = '41031101'
BAD_DEBT_EXPENSE_ACCOUNT_CODE = '51220101'
INTEREST_PAID_PREFIX = '512401'
LIQUIDATION_GOING_CONCERN_PARAGRAPH_TEMPLATES = (
    "The financial statements have been prepared on a non-going concern basis, "
    "which contemplates the realization of assets and the settlement of liabilities "
    "in the normal course of business. However, the Director of the Entity has "
    "decided to liquidate the Entity during the year {year}. As a result, the Entity "
    "will cease operations and liquidate its assets to settle its liabilities during "
    "the year {year}.",
    "The decision to liquidate the Entity indicates that the going concern "
    "assumption is no longer appropriate. Consequently, the financial statement has "
    "been prepared on a liquidation basis, which requires assets to be measured at "
    "their net realizable value and liabilities to be measured at their settlement "
    "amounts.",
    "The management has assessed the impact of liquidation on the financial position "
    "and performance of the Entity and has made necessary adjustments to reflect "
    "the change in the basis of preparation.",
)
LEGACY_LIQUIDATION_GOING_CONCERN_YEAR = 2025


class AuditReport(models.TransientModel):
    _name = 'audit.report'
    _description = 'Audit Report'

    SIGNATURE_INCLUDE_FIELD_NAMES = [f'signature_include_{idx}' for idx in range(1, 11)]
    SIGNATURE_ROLE_FIELD_NAMES = [f'signature_role_{idx}' for idx in range(1, 11)]
    DIRECTOR_INCLUDE_FIELD_NAMES = [f'director_include_{idx}' for idx in range(1, 11)]
    OWNER_INCLUDE_FIELD_NAMES = [f'owner_include_{idx}' for idx in range(1, 11)]
    SHAREHOLDER_PREFERENCE_AUTOSAVE_FIELD_NAMES = [
        'share_capital_paid_status',
        'show_shareholder_note',
        'show_share_capital_conversion_note',
        'share_conversion_currency',
        'share_conversion_original_value',
        'share_conversion_exchange_rate',
        'show_share_capital_transfer_note',
        'share_transfer_date',
        'share_transfer_from',
        'share_transfer_shares',
        'share_transfer_percentage',
        'share_transfer_to',
        *SIGNATURE_INCLUDE_FIELD_NAMES,
        *SIGNATURE_ROLE_FIELD_NAMES,
        *DIRECTOR_INCLUDE_FIELD_NAMES,
        *OWNER_INCLUDE_FIELD_NAMES,
    ]

    SIGNATORY_ROLE_SELECTION = [
        ('primary', 'Primary'),
        ('secondary', 'Secondary'),
    ]
    SIGNATURE_DATE_MODE_SELECTION = [
        ('today', 'Auto (today)'),
        ('report_end', 'Report end date'),
        ('manual', 'Manual date'),
    ]

    date_start = fields.Date(string='Date Start', required=True)
    date_end = fields.Date(string='Date End', required=True)
    balance_sheet_date_mode = fields.Selection(
        [
            ('end_only', 'End date only (snapshot)'),
            ('range', 'Date range (start to end)'),
        ],
        string='Balance Sheet Dates',
        required=True,
        default='end_only',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    company_name = fields.Char(related='company_id.name', readonly=False)
    company_street = fields.Char(related='company_id.street', readonly=False)
    company_street2 = fields.Char(related='company_id.street2', readonly=False)
    company_city = fields.Char(related='company_id.city', readonly=False)
    company_state_id = fields.Many2one(related='company_id.state_id', readonly=False)
    company_zip = fields.Char(related='company_id.zip', readonly=False)
    company_country_id = fields.Many2one(related='company_id.country_id', readonly=False)
    company_free_zone = fields.Selection(
        selection=[
            ("Abu Dhabi Global Market", "Abu Dhabi Global Market"),
            ("Ajman Free Zone", "Ajman Free Zone, Ajman"),
            ("Ajman NuVentures Centre Free Zone", "Ajman NuVentures Centre Free Zone"),
            ("Creative Media Authority", "Creative Media Authority"),
            ("Department of Economic Development", "Department of Economic Development"),
            ("Department of Economy and Tourism", "Department of Economy and Tourism"),
            ("Dubai Aviation City Corporation", "Dubai Aviation City Corporation"),
            ("Dubai Development Authority Zone", "Dubai Development Authority Zone"),
            ("Dubai International Financial Centre", "Dubai International Financial Centre"),
            ("Dubai Integrated Economic Zones Authority", "Dubai Integrated Economic Zones Authority"),
            ("Dubai Multi Commodities Centre Free Zone", "Dubai Multi Commodities Centre Free Zone"),
            ("Dubai World Trade Centre Authority", "Dubai World Trade Centre Authority"),
            ("Meydan Free Zone", "Meydan Free Zone"),
            ("Ports, Customs and Free Zone Corporation", "Ports, Customs and Free Zone Corporation"),
            ("Creative City Media Free Zone", "Creative City Media Free Zone"),
            ("Ras Al Khaimah Economic Zone", "Ras Al Khaimah Economic Zone"),
            ("Ras Al Khaimah International Corporate Centre", "Ras Al Khaimah International Corporate Centre"),
            ("Sharjah Media City", "Sharjah Media City"),
            ("Sharjah Publishing City", "Sharjah Publishing City"),
            ("Sharjah Research Technology and Innovation Park Free Zone Authority", "Sharjah Research Technology and Innovation Park Free Zone Authority"),
        ],
        string='Company Free Zone',
        compute='_compute_company_free_zone',
        inverse='_inverse_company_free_zone',
        store=False,
    )
    company_license_number = fields.Char(
        string='Company License Number',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_company_license_number',
        store=False,
    )
    portal_account_no = fields.Char(string='Portal Account')
    trade_license_activities = fields.Text(
        string='Trade License Activities',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_trade_license_activities',
        store=False,
    )
    business_activity_include_services = fields.Boolean(
        string='Append "services" to business activity',
        default=True,
    )
    business_activity_include_providing = fields.Boolean(
        string='Prepend "providing" to business activity',
        default=True,
    )
    incorporation_date = fields.Date(
        string='Company Incorporation Date',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_incorporation_date',
        store=False,
    )
    corporate_tax_registration_number = fields.Char(
        string='Corporate Tax Registration Number',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_corporate_tax_registration_number',
        store=False,
    )
    vat_registration_number = fields.Char(
        string='VAT Registration Number',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_vat_registration_number',
        store=False,
    )
    corporate_tax_start_date = fields.Date(
        string='Corporate Tax Start Date',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_corporate_tax_start_date',
        store=False,
    )
    corporate_tax_end_date = fields.Date(
        string='Corporate Tax End Date',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_corporate_tax_end_date',
        store=False,
    )
    implementing_regulations_freezone = fields.Text(
        string='Implementing Regulations for Free Zones',
        compute='_compute_company_exte_scalar_fields',
        inverse='_inverse_implementing_regulations_freezone',
        store=False,
    )

    @api.onchange('company_free_zone')
    def _onchange_company_free_zone(self):
        if not self.company_free_zone or not self.company_id:
            return
        if hasattr(self.company_id, '_get_free_zone_implementing_regulations'):
            mapped = self.company_id._get_free_zone_implementing_regulations(self.company_free_zone)
            if mapped:
                self.implementing_regulations_freezone = mapped
        if hasattr(self.company_id, '_get_free_zone_location_defaults'):
            location_defaults = self.company_id._get_free_zone_location_defaults(self.company_free_zone)
            if location_defaults.get('street'):
                self.company_street = location_defaults['street']
            if location_defaults.get('city'):
                self.company_city = location_defaults['city']

    @api.onchange('corporate_tax_start_date', 'corporate_tax_end_date')
    def _onchange_corporate_tax_dates(self):
        """Auto-check/uncheck 'Show CT first tax year line' based on CT dates."""
        if self.corporate_tax_start_date and self.corporate_tax_end_date:
            self.show_ct_first_tax_year_line = True
        else:
            self.show_ct_first_tax_year_line = False

    shareholder_1 = fields.Char(string='Shareholder 1', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_2 = fields.Char(string='Shareholder 2', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_3 = fields.Char(string='Shareholder 3', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_4 = fields.Char(string='Shareholder 4', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_5 = fields.Char(string='Shareholder 5', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_6 = fields.Char(string='Shareholder 6', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_7 = fields.Char(string='Shareholder 7', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_8 = fields.Char(string='Shareholder 8', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_9 = fields.Char(string='Shareholder 9', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)
    shareholder_10 = fields.Char(string='Shareholder 10', compute='_compute_company_exte_scalar_fields', inverse='_inverse_shareholder_fields', store=False)

    nationality_1 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 1', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_2 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 2', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_3 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 3', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_4 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 4', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_5 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 5', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_6 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 6', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_7 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 7', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_8 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 8', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_9 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 9', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)
    nationality_10 = fields.Selection(selection='_selection_nationality_compat', string='Nationality 10', compute='_compute_company_exte_scalar_fields', inverse='_inverse_nationality_fields', store=False)

    number_of_shares_1 = fields.Integer(string='No. of Shares 1', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_2 = fields.Integer(string='No. of Shares 2', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_3 = fields.Integer(string='No. of Shares 3', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_4 = fields.Integer(string='No. of Shares 4', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_5 = fields.Integer(string='No. of Shares 5', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_6 = fields.Integer(string='No. of Shares 6', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_7 = fields.Integer(string='No. of Shares 7', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_8 = fields.Integer(string='No. of Shares 8', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_9 = fields.Integer(string='No. of Shares 9', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)
    number_of_shares_10 = fields.Integer(string='No. of Shares 10', compute='_compute_company_exte_scalar_fields', inverse='_inverse_number_of_shares_fields', store=False)

    share_value_1 = fields.Float(string='Share Value 1', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_2 = fields.Float(string='Share Value 2', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_3 = fields.Float(string='Share Value 3', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_4 = fields.Float(string='Share Value 4', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_5 = fields.Float(string='Share Value 5', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_6 = fields.Float(string='Share Value 6', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_7 = fields.Float(string='Share Value 7', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_8 = fields.Float(string='Share Value 8', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_9 = fields.Float(string='Share Value 9', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)
    share_value_10 = fields.Float(string='Share Value 10', compute='_compute_company_exte_scalar_fields', inverse='_inverse_share_value_fields', store=False)

    signature_include_1 = fields.Boolean(string='Signatory 1', default=False)
    signature_include_2 = fields.Boolean(string='Signatory 2', default=False)
    signature_include_3 = fields.Boolean(string='Signatory 3', default=False)
    signature_include_4 = fields.Boolean(string='Signatory 4', default=False)
    signature_include_5 = fields.Boolean(string='Signatory 5', default=False)
    signature_include_6 = fields.Boolean(string='Signatory 6', default=False)
    signature_include_7 = fields.Boolean(string='Signatory 7', default=False)
    signature_include_8 = fields.Boolean(string='Signatory 8', default=False)
    signature_include_9 = fields.Boolean(string='Signatory 9', default=False)
    signature_include_10 = fields.Boolean(string='Signatory 10', default=False)
    director_include_1 = fields.Boolean(string='Director 1', default=True)
    director_include_2 = fields.Boolean(string='Director 2', default=False)
    director_include_3 = fields.Boolean(string='Director 3', default=False)
    director_include_4 = fields.Boolean(string='Director 4', default=False)
    director_include_5 = fields.Boolean(string='Director 5', default=False)
    director_include_6 = fields.Boolean(string='Director 6', default=False)
    director_include_7 = fields.Boolean(string='Director 7', default=False)
    director_include_8 = fields.Boolean(string='Director 8', default=False)
    director_include_9 = fields.Boolean(string='Director 9', default=False)
    director_include_10 = fields.Boolean(string='Director 10', default=False)
    owner_include_1 = fields.Boolean(string='Owner 1', default=True)
    owner_include_2 = fields.Boolean(string='Owner 2', default=True)
    owner_include_3 = fields.Boolean(string='Owner 3', default=True)
    owner_include_4 = fields.Boolean(string='Owner 4', default=True)
    owner_include_5 = fields.Boolean(string='Owner 5', default=True)
    owner_include_6 = fields.Boolean(string='Owner 6', default=True)
    owner_include_7 = fields.Boolean(string='Owner 7', default=True)
    owner_include_8 = fields.Boolean(string='Owner 8', default=True)
    owner_include_9 = fields.Boolean(string='Owner 9', default=True)
    owner_include_10 = fields.Boolean(string='Owner 10', default=True)

    signature_role_1 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 1',
        default='primary',
    )
    signature_role_2 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 2',
        default='secondary',
    )
    signature_role_3 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 3',
        default='secondary',
    )
    signature_role_4 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 4',
        default='secondary',
    )
    signature_role_5 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 5',
        default='secondary',
    )
    signature_role_6 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 6',
        default='secondary',
    )
    signature_role_7 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 7',
        default='secondary',
    )
    signature_role_8 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 8',
        default='secondary',
    )
    signature_role_9 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 9',
        default='secondary',
    )
    signature_role_10 = fields.Selection(
        SIGNATORY_ROLE_SELECTION,
        string='Signatory role 10',
        default='secondary',
    )

    total_share_1 = fields.Float(string='Total Share 1', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_2 = fields.Float(string='Total Share 2', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_3 = fields.Float(string='Total Share 3', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_4 = fields.Float(string='Total Share 4', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_5 = fields.Float(string='Total Share 5', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_6 = fields.Float(string='Total Share 6', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_7 = fields.Float(string='Total Share 7', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_8 = fields.Float(string='Total Share 8', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_9 = fields.Float(string='Total Share 9', compute='_compute_total_shares_wizard', store=False, readonly=True)
    total_share_10 = fields.Float(string='Total Share 10', compute='_compute_total_shares_wizard', store=False, readonly=True)

    # ------------------------------------------------------------------ #
    # company_exte soft-dependency: compute / inverse helpers             #
    # All getattr calls return False/0 when company_exte is not installed #
    # ------------------------------------------------------------------ #

    _COMPANY_EXTE_SCALAR_FIELDS = [
        'company_license_number', 'trade_license_activities',
        'incorporation_date', 'corporate_tax_registration_number',
        'vat_registration_number', 'corporate_tax_start_date',
        'corporate_tax_end_date', 'implementing_regulations_freezone',
        *[f'shareholder_{i}' for i in range(1, 11)],
        *[f'nationality_{i}' for i in range(1, 11)],
        *[f'number_of_shares_{i}' for i in range(1, 11)],
        *[f'share_value_{i}' for i in range(1, 11)],
    ]

    @api.model
    def _selection_nationality_compat(self):
        company_model = self.env['res.company']
        if hasattr(company_model, '_selection_shareholder_nationality'):
            return company_model._selection_shareholder_nationality()
        return []

    @api.depends('company_id')
    def _compute_company_free_zone(self):
        for rec in self:
            rec.company_free_zone = getattr(rec.company_id, 'free_zone', False)

    def _inverse_company_free_zone(self):
        for rec in self:
            if hasattr(rec.company_id, 'free_zone'):
                rec.company_id.free_zone = rec.company_free_zone

    @api.depends('company_id')
    def _compute_company_exte_scalar_fields(self):
        for rec in self:
            for fname in self._COMPANY_EXTE_SCALAR_FIELDS:
                rec[fname] = getattr(rec.company_id, fname, False)

    def _inverse_company_license_number(self):
        for rec in self:
            if hasattr(rec.company_id, 'company_license_number'):
                rec.company_id.company_license_number = rec.company_license_number

    def _inverse_trade_license_activities(self):
        for rec in self:
            if hasattr(rec.company_id, 'trade_license_activities'):
                rec.company_id.trade_license_activities = rec.trade_license_activities

    def _inverse_incorporation_date(self):
        for rec in self:
            if hasattr(rec.company_id, 'incorporation_date'):
                rec.company_id.incorporation_date = rec.incorporation_date

    def _inverse_corporate_tax_registration_number(self):
        for rec in self:
            if hasattr(rec.company_id, 'corporate_tax_registration_number'):
                rec.company_id.corporate_tax_registration_number = rec.corporate_tax_registration_number

    def _inverse_vat_registration_number(self):
        for rec in self:
            if hasattr(rec.company_id, 'vat_registration_number'):
                rec.company_id.vat_registration_number = rec.vat_registration_number

    def _inverse_corporate_tax_start_date(self):
        for rec in self:
            if hasattr(rec.company_id, 'corporate_tax_start_date'):
                rec.company_id.corporate_tax_start_date = rec.corporate_tax_start_date

    def _inverse_corporate_tax_end_date(self):
        for rec in self:
            if hasattr(rec.company_id, 'corporate_tax_end_date'):
                rec.company_id.corporate_tax_end_date = rec.corporate_tax_end_date

    def _inverse_implementing_regulations_freezone(self):
        for rec in self:
            if hasattr(rec.company_id, 'implementing_regulations_freezone'):
                rec.company_id.implementing_regulations_freezone = rec.implementing_regulations_freezone

    def _inverse_shareholder_fields(self):
        for rec in self:
            for i in range(1, 11):
                fname = f'shareholder_{i}'
                if hasattr(rec.company_id, fname):
                    rec.company_id[fname] = rec[fname]

    def _inverse_nationality_fields(self):
        for rec in self:
            for i in range(1, 11):
                fname = f'nationality_{i}'
                if hasattr(rec.company_id, fname):
                    rec.company_id[fname] = rec[fname]

    def _inverse_number_of_shares_fields(self):
        for rec in self:
            for i in range(1, 11):
                fname = f'number_of_shares_{i}'
                if hasattr(rec.company_id, fname):
                    rec.company_id[fname] = rec[fname]

    def _inverse_share_value_fields(self):
        for rec in self:
            for i in range(1, 11):
                fname = f'share_value_{i}'
                if hasattr(rec.company_id, fname):
                    rec.company_id[fname] = rec[fname]

    @api.depends(
        *[f'number_of_shares_{i}' for i in range(1, 11)],
        *[f'share_value_{i}' for i in range(1, 11)],
    )
    def _compute_total_shares_wizard(self):
        for rec in self:
            for i in range(1, 11):
                rec[f'total_share_{i}'] = (rec[f'number_of_shares_{i}'] or 0) * (rec[f'share_value_{i}'] or 0.0)

    report_type = fields.Selection(
        [
            ('period', 'Financial Statements for the Period Ended'),
            ('year', 'Financial Statements for the Year Ended'),
            ('management', 'Management Accounts for the Period Ended'),
        ],
        string='Report Type',
        required=True,
        default='period',
    )
    show_related_parties_note = fields.Boolean(
        string='Show related parties note',
        default=False,
    )
    show_shareholder_note = fields.Boolean(
        string='Show shareholder line and note',
        default=True,
    )
    show_ct_first_tax_year_line = fields.Boolean(
        string='Show CT first tax year line',
        default=True,
    )
    show_other_comprehensive_income_page = fields.Boolean(
        string='Show OCI page',
        default=False,
    )
    cashflow_net_profit_use_after_tax = fields.Boolean(
        string='Cash flow net profit line uses net profit after tax',
        default=False,
    )
    usd_statement = fields.Boolean(
        string='USD Statement',
        default=False,
        help='Master switch to render statements in USD format and apply USD-specific disclosures.',
    )
    draft_watermark = fields.Boolean(
        string='Draft Watermark (PDF)',
        default=False,
        help='Render a centered DRAFT watermark on generated PDFs.',
    )
    ignore_notes_last_page_margins = fields.Boolean(
        string='Reduce bottom margin on notes pages',
        default=False,
        help='Use a smaller bottom page margin for notes pages so the closing signature block is less likely to spill.',
    )
    show_investment_note_schedule = fields.Boolean(
        string='Show investments schedule',
        default=True,
        help='Render the blank fund schedule table below the Investments note values.',
    )
    gap_report_of_directors = fields.Boolean(
        string='Gap in report of directors',
        default=True,
    )
    gap_independent_auditor_report = fields.Boolean(
        string='Gap in independent auditor report',
        default=True,
    )
    gap_notes_to_financial_statements = fields.Boolean(
        string='Gap in notes to financial statements',
        default=True,
    )
    signature_break_lines_report_of_directors = fields.Integer(
        string='Break lines (Report of Directors)',
        default=5,
    )
    signature_break_lines_balance_sheet = fields.Integer(
        string='Break lines (Statement of financial position)',
        default=5,
    )
    signature_break_lines_profit_loss = fields.Integer(
        string='Break lines (Statement of profit and loss)',
        default=5,
    )
    signature_break_lines_changes_in_equity = fields.Integer(
        string='Break lines (Statement of changes in equity)',
        default=5,
    )
    signature_break_lines_cash_flows = fields.Integer(
        string='Break lines (Statement of cash flows)',
        default=5,
    )
    signature_break_lines_notes = fields.Integer(
        string='Break lines (Notes to financial statements)',
        default=5,
    )
    signature_date_mode = fields.Selection(
        SIGNATURE_DATE_MODE_SELECTION,
        string='Signature placeholder date',
        required=True,
        default='today',
    )
    signature_manual_date = fields.Date(
        string='Manual signature date',
    )
    use_previous_settings = fields.Boolean(
        string='Use Previous Settings',
        default=True,
    )
    audit_period_category = fields.Selection(
        [
            ('cessation_2y', '2 Years Cessation'),
            ('cessation_1y', '1 Year Cessation'),
            ('normal_1y', '1 Year Normal'),
            ('normal_2y', '2 Years Normal'),
            ('dormant_1y', '1 Year Dormant'),
            ('dormant_2y', '2 Years Dormant'),
        ],
        string='Audit Period Category',
        default='normal_2y',
    )
    share_capital_paid_status = fields.Selection(
        [
            ('paid', 'Paid'),
            ('unpaid', 'Unpaid'),
        ],
        string='Share capital status',
        default='paid',
    )
    show_share_capital_conversion_note = fields.Boolean(
        string='Show share capital conversion note',
        default=False,
    )
    share_conversion_currency = fields.Char(
        string='Original currency',
        default='GBP',
    )
    share_conversion_original_value = fields.Float(
        string='Original value per share',
        default=100.0,
    )
    share_conversion_exchange_rate = fields.Float(
        string='Exchange rate',
        default=4.66,
    )
    show_share_capital_transfer_note = fields.Boolean(
        string='Show share transfer note',
        default=False,
    )
    share_transfer_date = fields.Date(
        string='Transfer date',
    )
    share_transfer_from = fields.Char(
        string='Transferred from',
    )
    share_transfer_shares = fields.Integer(
        string='No. of shares transferred',
        default=0,
    )
    share_transfer_percentage = fields.Float(
        string='Transferred shares (%)',
        default=0.0,
    )
    share_transfer_to = fields.Char(
        string='Transferred to',
    )
    related_party_name = fields.Char(string='Related party')
    related_party_relationship = fields.Char(string='Nature of relationship')
    related_party_transaction = fields.Char(string='Nature of transactions')
    related_party_amount = fields.Float(string='Related party amount (current)')
    related_party_amount_prior = fields.Float(string='Related party amount (prior)')
    related_party_line_ids = fields.One2many(
        'audit.report.related.party.line',
        'wizard_id',
        string='Related Party Rows',
        copy=False,
    )
    correction_error_note_body = fields.Text(
        string='Correction of Error Note Body',
        copy=False,
    )
    correction_error_line_ids = fields.One2many(
        'audit.report.correction.error.line',
        'wizard_id',
        string='Correction of Error Rows',
        copy=False,
    )
    prior_year_mode = fields.Selection(
        [
            ('auto', 'Auto (1 year back)'),
            ('manual', 'Manual selection'),
        ],
        string='Prior Year Dates',
        required=True,
        default='auto',
    )
    prior_balance_sheet_date_mode = fields.Selection(
        [
            ('end_only', 'End date only (snapshot)'),
            ('range', 'Date range (start to end)'),
        ],
        string='Prior Balance Sheet Dates',
        required=True,
        default='end_only',
    )
    prior_date_start = fields.Date(string='Prior Date Start')
    prior_date_end = fields.Date(string='Prior Date End')
    prior_year_dates_warning_message = fields.Char(
        string='Prior year dates warning',
        compute='_compute_prior_year_dates_warning_message',
    )
    soce_prior_opening_label_date = fields.Date(
        string='SOCE First Balance Date (2-year, label only)'
    )
    soce_warning_message = fields.Char(
        string='SOCE warning',
        compute='_compute_soce_warning_message',
    )
    tb_override_line_ids = fields.One2many(
        'audit.report.tb.override.line',
        'wizard_id',
        string='Trial Balance Overrides',
        copy=False,
    )
    tb_override_current_line_ids = fields.One2many(
        'audit.report.tb.override.line',
        'wizard_id',
        string='Current Period Trial Balance Overrides',
        domain=[('period_key', '=', 'current')],
        copy=False,
    )
    tb_override_prior_line_ids = fields.One2many(
        'audit.report.tb.override.line',
        'wizard_id',
        string='Prior Period Trial Balance Overrides',
        domain=[('period_key', '=', 'prior')],
        copy=False,
    )
    tb_include_zero_accounts = fields.Boolean(
        string='Include zero-balance accounts',
        default=False,
    )
    tb_browser_active_period = fields.Selection(
        [
            ('current', 'Current'),
            ('prior', 'Prior'),
        ],
        string='Embedded TB Period',
        default='current',
        copy=False,
    )
    tb_current_report_options_json = fields.Text(
        string='Embedded Current TB Options',
        copy=False,
    )
    tb_prior_report_options_json = fields.Text(
        string='Embedded Prior TB Options',
        copy=False,
    )
    tb_enable_date_navigator = fields.Boolean(
        string='Enable TB date navigator',
        default=False,
        help='Shows previous/next period controls on the Trial Balance Overrides tab.',
    )
    tb_effective_prior_date_start = fields.Date(
        string='Effective Prior Start',
        compute='_compute_tb_effective_prior_dates',
        readonly=True,
        copy=False,
    )
    tb_effective_prior_date_end = fields.Date(
        string='Effective Prior End',
        compute='_compute_tb_effective_prior_dates',
        readonly=True,
        copy=False,
    )
    tb_convert_balances_to_usd = fields.Boolean(
        string='Convert TB balances to USD',
        default=False,
        help='Convert all chart-of-accounts balances from AED to USD for this report.',
    )
    tb_usd_conversion_rate = fields.Float(
        string='AED per 1 USD',
        default=3.6725,
        digits=(16, 6),
        help='Custom rate used when converting trial balance amounts to USD.',
    )
    replace_aed_text_with_usd = fields.Boolean(
        string='Replace AED text with USD',
        default=False,
        help='Replaces all AED text labels with USD in generated HTML/PDF output.',
    )
    tb_overrides_json = fields.Text(
        string='TB Overrides Snapshot',
        copy=False,
    )
    lor_extra_item_line_ids = fields.One2many(
        'audit.report.lor.extra.line',
        'wizard_id',
        string='LOR Extra Main List Items',
        copy=False,
    )
    lor_extra_items_json = fields.Text(
        string='LOR Extra Main List Items Snapshot',
        copy=False,
    )
    tb_diff_current = fields.Float(
        string='Current mismatch',
        digits='Account',
        readonly=True,
        copy=False,
    )
    tb_diff_prior = fields.Float(
        string='Prior mismatch',
        digits='Account',
        readonly=True,
        copy=False,
    )
    tb_warning_current = fields.Char(
        string='Current warning',
        readonly=True,
        copy=False,
    )
    tb_warning_prior = fields.Char(
        string='Prior warning',
        readonly=True,
        copy=False,
    )
    audit_target_revision_id = fields.Many2one(
        'audit.report.revision',
        string='Target Revision',
        readonly=True,
        copy=False,
    )
    audit_target_document_id = fields.Many2one(
        'audit.report.document',
        string='Target Document',
        readonly=True,
        copy=False,
    )
    emphasis_change_period = fields.Boolean(string='Change in Financial Year/Period')
    emphasis_correction_error = fields.Boolean(string='Correction of Error')
    show_unaudited_prior_year = fields.Boolean(string='Unaudited prior year')
    replace_going_concern_paragraph = fields.Boolean(
        string='Replace Going Concern Paragraph',
        help='Replace the report of directors going concern wording with liquidation text.',
    )
    replace_going_concern_year = fields.Integer(
        string='Liquidation Year',
        default=False,
        help='Year used in the replacement liquidation wording.',
    )
    emphasis_change_from_date = fields.Date(string='Changed From')
    emphasis_change_to_date = fields.Date(string='Changed To')
    additional_note_legal_status_change = fields.Boolean(string='Legal Status Change')
    additional_note_no_active_bank_account = fields.Boolean(string='No Active Bank Account')
    additional_note_business_bank_account_opened = fields.Boolean(
        string='Business Bank Account Opened Post Year-End'
    )
    emphasis_legal_change_date = fields.Date(string='Legal Change Date')
    emphasis_legal_status_from = fields.Char(string='Legal Status From')
    emphasis_legal_status_to = fields.Char(string='Legal Status To')

    @api.depends(
        'date_start',
        'date_end',
        'prior_year_mode',
        'prior_date_start',
        'prior_date_end',
        'audit_period_category',
    )
    def _compute_tb_effective_prior_dates(self):
        for record in self:
            start_date, end_date = record._tb_effective_prior_period_range()
            record.tb_effective_prior_date_start = start_date
            record.tb_effective_prior_date_end = end_date

    def _tb_effective_prior_period_range(self):
        self.ensure_one()
        period_category = (self.audit_period_category or '').lower()
        if period_category.endswith('_1y'):
            return False, False

        if self.prior_year_mode == 'manual' and self.prior_date_start and self.prior_date_end:
            return (
                fields.Date.to_date(self.prior_date_start),
                fields.Date.to_date(self.prior_date_end),
            )

        if not self.date_start or not self.date_end:
            return False, False

        current_start = fields.Date.to_date(self.date_start)
        current_end = fields.Date.to_date(self.date_end)
        return (
            current_start - relativedelta(years=1),
            current_end - relativedelta(years=1),
        )

    @api.model
    def _tb_shift_period_range(self, date_start, date_end, direction='next'):
        start_value = fields.Date.to_date(date_start) if date_start else False
        end_value = fields.Date.to_date(date_end) if date_end else False
        if not start_value or not end_value:
            return False, False

        step_days = (end_value - start_value).days + 1
        if step_days <= 0:
            raise ValidationError("Period end date must be on or after the start date.")

        signed_days = step_days if direction == 'next' else -step_days
        shift_delta = relativedelta(days=signed_days)
        return (
            start_value + shift_delta,
            end_value + shift_delta,
        )

    def _tb_navigator_supports_prior(self):
        self.ensure_one()
        period_category = (self.audit_period_category or '').lower()
        return not period_category.endswith('_1y')

    def _action_tb_shift_period(self, target_period, direction):
        self.ensure_one()
        if target_period not in ('current', 'prior'):
            raise ValidationError("Invalid TB navigator period selected.")
        if direction not in ('previous', 'next'):
            raise ValidationError("Invalid TB navigator direction selected.")

        shift_direction = 'previous' if direction == 'previous' else 'next'
        write_vals = {}

        if target_period == 'current':
            new_start, new_end = self._tb_shift_period_range(
                self.date_start,
                self.date_end,
                direction=shift_direction,
            )
            if not new_start or not new_end:
                raise ValidationError("Set both current period dates before moving them.")
            write_vals.update({
                'date_start': new_start,
                'date_end': new_end,
            })
        else:
            if not self._tb_navigator_supports_prior():
                raise ValidationError("Prior-period date navigation is available only for 2-year reports.")
            prior_start, prior_end = self._tb_effective_prior_period_range()
            new_start, new_end = self._tb_shift_period_range(
                prior_start,
                prior_end,
                direction=shift_direction,
            )
            if not new_start or not new_end:
                raise ValidationError("Set prior period dates before moving them.")
            write_vals.update({
                'prior_year_mode': 'manual',
                'prior_date_start': new_start,
                'prior_date_end': new_end,
            })

        self.write(write_vals)
        self._load_tb_override_lines(preserve_overrides=False)
        return self._reopen_wizard_form()

    def _previous_settings_key(self):
        return (
            f'audit_report_wizard.prev_settings.company_{self.env.company.id}'
        )

    def _legacy_previous_settings_key(self):
        return (
            f'audit_report_wizard.prev_settings.user_{self.env.user.id}.'
            f'company_{self.env.company.id}'
        )

    def _get_previous_settings(self):
        param = self.env['ir.config_parameter'].sudo()
        for key in (self._previous_settings_key(), self._legacy_previous_settings_key()):
            raw = param.get_param(key, default='')
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict):
                return data
        return {}

    @api.model
    def _note_line_key(self, value):
        text = str(value or '').strip().lower()
        if not text:
            return ''
        text = text.replace('&', ' and ')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @api.model
    def _split_note_paragraphs(self, text):
        return [
            line.strip()
            for line in (text or '').splitlines()
            if line and line.strip()
        ]

    @api.model
    def _canonical_note_line_display_name(self, value):
        normalized_name = self._note_line_key(value)
        if re.search(r'\bstaff salar(?:y|ies)\b', normalized_name):
            return 'Salaries and wages'
        if normalized_name in {
            'security deposit (landlord/rent)',
            'security deposits (landlord/rent)',
            'security deposit landlord/rent',
            'security deposits landlord/rent',
        }:
            return 'Security deposit'
        if normalized_name in {
            'long term loans payable related parties',
            'long term loans payable related party',
            'long term loan payable related parties',
            'long term loan payable related party',
        }:
            return 'Loan from related party'
        if normalized_name in {
            'audit fee accrual',
            'audit fees accrual',
            'audit and accounting fee accrual',
            'audit and accounting fees accrual',
            'audit and accounting accrual',
        }:
            return 'Audit and Accounting fee accrual'
        return value

    @api.model
    def _note_aggregated_prefix_labels(self):
        return {
            '120302': 'Prepayment',
            '120304': 'VAT recoverable',
            '220103': 'Credit card payable',
            '220201': 'Accounts payable',
            '220302': 'VAT payable',
        }

    @api.model
    def _filter_account_head_map_by_prefixes(self, account_heads, prefixes):
        normalized_prefixes = tuple(str(prefix or '') for prefix in (prefixes or []) if prefix)
        if not normalized_prefixes:
            return {}

        filtered = {}
        for group_code, accounts in (account_heads or {}).items():
            matching_accounts = {
                account_code: account_info
                for account_code, account_info in (accounts or {}).items()
                if any(str(account_code or '').startswith(prefix) for prefix in normalized_prefixes)
            }
            if matching_accounts:
                filtered[group_code] = matching_accounts
        return filtered

    @api.model
    def _sort_operating_expense_note_lines(self, lines):
        top_codes = ['51070101', '51080101']
        bottom_codes = ['51230101', '51220102']
        top_set = set(top_codes)
        bottom_set = set(bottom_codes)
        top_lines = [line for code in top_codes for line in lines if line.get('code') == code]
        bottom_lines = [line for code in bottom_codes for line in lines if line.get('code') == code]
        middle_lines = [
            line for line in lines
            if line.get('code') not in top_set and line.get('code') not in bottom_set
        ]
        middle_lines.sort(key=lambda line: self._note_line_key(line.get('name') or line.get('code') or ''))
        return top_lines + middle_lines + bottom_lines

    @api.model
    def _normalize_operating_expense_note_lines(self, lines):
        fee_codes = {'51260101', '51260201', '51260301'}
        rename_map = {
            'loss on difference on exchange': 'Exchange loss',
            'marketing and advertisement expenses': 'Advertising',
            'marketing and advertisement expense': 'Advertising',
            "director's salary": 'Director salary',
            'director salary': 'Director salary',
            'directors salary': 'Director salary',
            'subcontractor service': 'Subcontractor',
            'subcontractor services': 'Subcontractor',
            'entertainment expense': 'Entertainment',
            'entertainment expenses': 'Entertainment',
            'client entertainment': 'Entertainment',
            'business insurance': 'Insurance expense',
            'business insurance expense': 'Insurance expense',
            'business insurance expenses': 'Insurance expense',
            'staff salary': 'Salaries and wages',
            'staff salaries': 'Salaries and wages',
        }
        audit_accounting_fee_aliases = {
            'audit fee',
            'audit fees',
            'accounting fee',
            'accounting fees',
            'bookkeeping fee',
            'bookkeeping fees',
            'accounting and bookkeeping fee',
            'accounting and bookkeeping fees',
            'accounting and bookkeeping charges',
            'audit and accounting fee',
            'audit and accounting fees',
            'other accountant fee',
            'other accountant fees',
        }
        audit_accounting_fee_accrual_aliases = {
            'audit fee accrual',
            'audit fees accrual',
            'audit and accounting fee accrual',
            'audit and accounting fees accrual',
        }
        travel_name_aliases = {
            'business travel',
            'fuel for business travel',
            'business accommodation',
            'business accommodation expense',
            'local accommodation expense',
            'travelling and accommodation',
            'travelling and accommodation expense',
            'travelling and accommodation expenses',
            'travel and accommodation',
            'travel and accommodation expense',
            'travel and accommodation expenses',
            'travelling & accommodation',
            'travelling & accommodation expense',
            'travelling & accommodation expenses',
            'travel & accommodation',
            'travel & accommodation expense',
            'travel & accommodation expenses',
        }
        it_name_aliases = {
            'it and software expenses',
            'it and software expense',
            'it expense',
            'it expenses',
            'software subscription',
            'software subscriptions',
        }
        fee_current = fee_prev = 0.0
        audit_accounting_fee_current = audit_accounting_fee_prev = 0.0
        audit_accounting_fee_accrual_current = audit_accounting_fee_accrual_prev = 0.0
        travel_current = travel_prev = 0.0
        it_current = it_prev = 0.0
        normalized = []
        for line in lines:
            updated_line = dict(line)
            line_name = self._note_line_key(updated_line.get('name'))
            line_code = str(updated_line.get('code') or '')
            if line_code in fee_codes:
                fee_current += updated_line.get('current', 0.0)
                fee_prev += updated_line.get('prev', 0.0)
                continue
            if line_name in audit_accounting_fee_aliases:
                audit_accounting_fee_current += updated_line.get('current', 0.0)
                audit_accounting_fee_prev += updated_line.get('prev', 0.0)
                continue
            if line_name in audit_accounting_fee_accrual_aliases:
                audit_accounting_fee_accrual_current += updated_line.get('current', 0.0)
                audit_accounting_fee_accrual_prev += updated_line.get('prev', 0.0)
                continue
            if line_code.startswith('5103') or line_name in it_name_aliases:
                it_current += updated_line.get('current', 0.0)
                it_prev += updated_line.get('prev', 0.0)
                continue
            if line_name in travel_name_aliases:
                travel_current += updated_line.get('current', 0.0)
                travel_prev += updated_line.get('prev', 0.0)
                continue
            updated_line['name'] = rename_map.get(line_name, updated_line.get('name'))
            normalized.append(updated_line)

        if fee_current or fee_prev:
            normalized.append({
                'code': 'fee_subscription',
                'name': 'Fee and subscription',
                'current': fee_current,
                'prev': fee_prev,
            })
        if audit_accounting_fee_current or audit_accounting_fee_prev:
            normalized.append({
                'code': 'audit_accounting_fee',
                'name': 'Audit and accounting fee',
                'current': audit_accounting_fee_current,
                'prev': audit_accounting_fee_prev,
            })
        if audit_accounting_fee_accrual_current or audit_accounting_fee_accrual_prev:
            normalized.append({
                'code': 'audit_accounting_fee_accrual',
                'name': 'Audit and Accounting fee accrual',
                'current': audit_accounting_fee_accrual_current,
                'prev': audit_accounting_fee_accrual_prev,
            })
        if it_current or it_prev:
            normalized.append({
                'code': 'it_expenses',
                'name': 'IT expenses',
                'current': it_current,
                'prev': it_prev,
            })
        if travel_current or travel_prev:
            normalized.append({
                'code': 'travel_accommodation',
                'name': 'Travelling and accommodation',
                'current': travel_current,
                'prev': travel_prev,
            })
        return self._sort_operating_expense_note_lines(normalized)

    @api.model
    def _normalize_cost_of_revenue_note_lines(self, lines):
        rename_map = {
            'stock purchase': 'Purchases',
            'stock purchases': 'Purchases',
            'subcontractor service': 'Subcontractor',
            'subcontractor services': 'Subcontractor',
        }
        normalized = []
        for line in lines:
            updated_line = dict(line)
            normalized_name = self._note_line_key(updated_line.get('name'))
            if normalized_name in rename_map:
                updated_line['name'] = rename_map[normalized_name]
            normalized.append(updated_line)
        return normalized

    @api.model
    def _is_direct_cost_closing_work_in_progress_line(self, line):
        code = self._normalize_account_code(line.get('code') or '')
        name_key = self._note_line_key(line.get('name'))
        return code == '51010501' or name_key == 'closing work in progress'

    @api.model
    def _format_note_amount_display(self, amount, preserve_sign=False, zero_as_dash=False):
        value = amount or 0.0
        rounded_value = round(float(value), 0)
        if zero_as_dash and not rounded_value:
            return '-'
        if rounded_value == 0:
            return '-'
        if preserve_sign:
            if rounded_value < 0:
                return f"({abs(rounded_value):,.0f})"
            return f"{rounded_value:,.0f}"
        return f"{abs(rounded_value):,.0f}"

    @api.model
    def _prepare_direct_cost_note(self, lines):
        regular_lines = []
        closing_wip_current = 0.0
        closing_wip_prev = 0.0

        for line in lines or []:
            updated_line = dict(line)
            if self._is_direct_cost_closing_work_in_progress_line(updated_line):
                closing_wip_current += updated_line.get('current', 0.0) or 0.0
                closing_wip_prev += updated_line.get('prev', 0.0) or 0.0
                continue
            regular_lines.append(updated_line)

        subtotal_current = sum((line.get('current', 0.0) or 0.0) for line in regular_lines)
        subtotal_prev = sum((line.get('prev', 0.0) or 0.0) for line in regular_lines)
        closing_wip_current_abs = abs(closing_wip_current)
        closing_wip_prev_abs = abs(closing_wip_prev)
        total_current = subtotal_current - closing_wip_current_abs
        total_prev = subtotal_prev - closing_wip_prev_abs

        if not (closing_wip_current or closing_wip_prev):
            return {
                'lines': regular_lines,
                'total_current': total_current,
                'total_prev': total_prev,
                'force_single_segment': False,
            }

        prepared_lines = [{
            'code': 'direct_cost_opening_wip',
            'name': 'Opening work in progress',
            'current': 0.0,
            'prev': 0.0,
            'current_display': '-',
            'prev_display': '-',
        }]
        prepared_lines.extend(regular_lines)
        prepared_lines.extend([
            {
                'code': 'direct_cost_subtotal',
                'name': '',
                'current': subtotal_current,
                'prev': subtotal_prev,
                'current_display': self._format_note_amount_display(subtotal_current),
                'prev_display': self._format_note_amount_display(subtotal_prev),
                'row_class': 'total-row note-direct-cost-subtotal',
                'current_wrap_class': 'amount-line amount-line-top-single',
                'prev_wrap_class': 'amount-line amount-line-top-single',
            },
            {
                'code': 'direct_cost_closing_wip',
                'name': 'Less: Closing work in progress',
                'current': -closing_wip_current_abs,
                'prev': -closing_wip_prev_abs,
                'current_display': self._format_note_amount_display(
                    -closing_wip_current_abs,
                    preserve_sign=True,
                    zero_as_dash=True,
                ),
                'prev_display': self._format_note_amount_display(
                    -closing_wip_prev_abs,
                    preserve_sign=True,
                    zero_as_dash=True,
                ),
                'row_class': 'note-direct-cost-less-row',
            },
        ])

        return {
            'lines': prepared_lines,
            'total_current': total_current,
            'total_prev': total_prev,
            'force_single_segment': True,
        }

    @api.model
    def _invert_note_lines(self, lines):
        return [
            {
                **line,
                'current': -(line.get('current', 0.0) or 0.0),
                'prev': -(line.get('prev', 0.0) or 0.0),
            }
            for line in lines
        ]

    @api.model
    def _build_generic_note_render_segments(self, lines):
        detail_lines = [dict(line) for line in (lines or [])]
        if len(detail_lines) <= 2:
            return [{
                'show_title': True,
                'show_total': True,
                'lines': detail_lines,
            }]

        segments = [{
            'show_title': True,
            'show_total': False,
            'lines': detail_lines[:2],
        }]
        remaining = detail_lines[2:]
        final_line_count = 3 if len(remaining) % 2 == 1 else 2
        while len(remaining) > final_line_count:
            segments.append({
                'show_title': False,
                'show_total': False,
                'lines': remaining[:2],
            })
            remaining = remaining[2:]
        segments.append({
            'show_title': False,
            'show_total': True,
            'lines': remaining,
        })
        return segments

    @api.model
    def _collect_note_lines(
        self,
        group_codes,
        current_map,
        prev_map,
        owner_current_account_code='12040101',
        equity_group_code='3101',
    ):
        if len(group_codes) == 1 and group_codes[0] == '1204':
            cash_prefix = '120401'
            bank_prefix = '120402'
            transit_prefix = '120403'

            def _sum_prefix(prefix, account_map):
                total = 0.0
                for code, info in account_map.get('1204', {}).items():
                    if code == owner_current_account_code:
                        continue
                    if code.startswith(prefix):
                        total += info.get('balance', 0.0)
                return total

            current_bank = _sum_prefix(bank_prefix, current_map)
            prev_bank = _sum_prefix(bank_prefix, prev_map)
            current_cash = _sum_prefix(cash_prefix, current_map)
            prev_cash = _sum_prefix(cash_prefix, prev_map)
            current_transit = _sum_prefix(transit_prefix, current_map)
            prev_transit = _sum_prefix(transit_prefix, prev_map)

            lines = []
            if current_bank or prev_bank:
                lines.append({
                    'code': bank_prefix,
                    'name': 'Cash at bank',
                    'current': current_bank,
                    'prev': prev_bank,
                })
            if current_cash or prev_cash:
                lines.append({
                    'code': cash_prefix,
                    'name': 'Cash in hand',
                    'current': current_cash,
                    'prev': prev_cash,
                })
            if current_transit or prev_transit:
                lines.append({
                    'code': transit_prefix,
                    'name': 'Monies in transit',
                    'current': current_transit,
                    'prev': prev_transit,
                })
            if lines:
                return lines

        account_codes = set()
        for group_code in group_codes:
            account_codes.update(current_map.get(group_code, {}).keys())
            account_codes.update(prev_map.get(group_code, {}).keys())

        aggregated_prefixes = self._note_aggregated_prefix_labels()
        aggregated_lines = {
            prefix: {
                'code': prefix,
                'name': label,
                'current': 0.0,
                'prev': 0.0,
            }
            for prefix, label in aggregated_prefixes.items()
        }
        lines = []
        for account_code in sorted(account_codes):
            group_code = account_code[:4]
            current_info = current_map.get(group_code, {}).get(account_code, {})
            prev_info = prev_map.get(group_code, {}).get(account_code, {})
            current_balance = current_info.get('balance', 0.0)
            prev_balance = prev_info.get('balance', 0.0)
            if not (current_balance or prev_balance):
                continue
            aggregated_prefix = next(
                (prefix for prefix in aggregated_prefixes if account_code.startswith(prefix)),
                None,
            )
            if aggregated_prefix:
                aggregated_line = aggregated_lines[aggregated_prefix]
                aggregated_line['current'] += current_balance
                aggregated_line['prev'] += prev_balance
                continue
            lines.append({
                'code': account_code,
                'name': current_info.get('name') or prev_info.get('name') or '',
                'current': current_balance,
                'prev': prev_balance,
            })

        for aggregated_line in aggregated_lines.values():
            if aggregated_line['current'] or aggregated_line['prev']:
                lines.append(aggregated_line)

        for line in lines:
            line['name'] = self._canonical_note_line_display_name(line.get('name') or '')

        lines.sort(key=lambda line: line.get('code') or '')

        if len(group_codes) == 1 and group_codes[0] == equity_group_code:
            owner_current_account_group_code = owner_current_account_code[:4]
            current_owner_info = current_map.get(owner_current_account_group_code, {}).get(
                owner_current_account_code, {}
            )
            prev_owner_info = prev_map.get(owner_current_account_group_code, {}).get(
                owner_current_account_code, {}
            )
            current_owner_balance = current_owner_info.get('balance', 0.0)
            prev_owner_balance = prev_owner_info.get('balance', 0.0)
            if current_owner_balance or prev_owner_balance:
                lines.append({
                    'code': owner_current_account_code,
                    'name': (
                        current_owner_info.get('name')
                        or prev_owner_info.get('name')
                        or 'Owner current account'
                    ),
                    'current': current_owner_balance,
                    'prev': prev_owner_balance,
                })
                lines.sort(key=lambda line: line.get('code') or '')
        return lines

    def _store_previous_settings(self):
        related_party_rows = self._serialize_related_party_rows_payload()
        correction_error_rows = self._serialize_correction_error_rows_payload()
        first_related_party_row = (
            related_party_rows[0]
            if related_party_rows
            else self._blank_related_party_row_payload()
        )
        data = {
            'date_start': self.date_start.isoformat() if self.date_start else False,
            'date_end': self.date_end.isoformat() if self.date_end else False,
            'balance_sheet_date_mode': self.balance_sheet_date_mode,
            'prior_year_mode': self.prior_year_mode,
            'prior_balance_sheet_date_mode': self.prior_balance_sheet_date_mode,
            'prior_date_start': self.prior_date_start.isoformat() if self.prior_date_start else False,
            'prior_date_end': self.prior_date_end.isoformat() if self.prior_date_end else False,
            'soce_prior_opening_label_date': (
                self.soce_prior_opening_label_date.isoformat()
                if self.soce_prior_opening_label_date else False
            ),
            'report_type': self.report_type,
            'portal_account_no': self.portal_account_no or False,
            'audit_period_category': self.audit_period_category,
            'show_related_parties_note': self.show_related_parties_note,
            'show_shareholder_note': self.show_shareholder_note,
            'business_activity_include_services': self.business_activity_include_services,
            'business_activity_include_providing': self.business_activity_include_providing,
            'show_ct_first_tax_year_line': self.show_ct_first_tax_year_line,
            'show_other_comprehensive_income_page': self.show_other_comprehensive_income_page,
            'cashflow_net_profit_use_after_tax': self.cashflow_net_profit_use_after_tax,
            'show_unaudited_prior_year': self.show_unaudited_prior_year,
            'usd_statement': self.usd_statement,
            'draft_watermark': self.draft_watermark,
            'ignore_notes_last_page_margins': self.ignore_notes_last_page_margins,
            'show_investment_note_schedule': self.show_investment_note_schedule,
            'gap_report_of_directors': self.gap_report_of_directors,
            'gap_independent_auditor_report': self.gap_independent_auditor_report,
            'gap_notes_to_financial_statements': self.gap_notes_to_financial_statements,
            'signature_break_lines_report_of_directors': self.signature_break_lines_report_of_directors,
            'signature_break_lines_balance_sheet': self.signature_break_lines_balance_sheet,
            'signature_break_lines_profit_loss': self.signature_break_lines_profit_loss,
            'signature_break_lines_changes_in_equity': self.signature_break_lines_changes_in_equity,
            'signature_break_lines_cash_flows': self.signature_break_lines_cash_flows,
            'signature_break_lines_notes': self.signature_break_lines_notes,
            'signature_date_mode': self.signature_date_mode,
            'signature_manual_date': (
                self.signature_manual_date.isoformat() if self.signature_manual_date else False
            ),
            'share_capital_paid_status': self.share_capital_paid_status,
            'show_share_capital_conversion_note': self.show_share_capital_conversion_note,
            'share_conversion_currency': self.share_conversion_currency,
            'share_conversion_original_value': self.share_conversion_original_value,
            'share_conversion_exchange_rate': self.share_conversion_exchange_rate,
            'show_share_capital_transfer_note': self.show_share_capital_transfer_note,
            'share_transfer_date': self.share_transfer_date.isoformat() if self.share_transfer_date else False,
            'share_transfer_from': self.share_transfer_from,
            'share_transfer_shares': self.share_transfer_shares,
            'share_transfer_percentage': self.share_transfer_percentage,
            'share_transfer_to': self.share_transfer_to,
            'related_party_rows': related_party_rows,
            'related_party_name': first_related_party_row.get('name') or False,
            'related_party_relationship': first_related_party_row.get('relationship') or False,
            'related_party_transaction': first_related_party_row.get('transaction') or False,
            'related_party_amount': self._to_float(first_related_party_row.get('amount')),
            'related_party_amount_prior': self._to_float(first_related_party_row.get('amount_prior')),
            'correction_error_note_body': self.correction_error_note_body or False,
            'correction_error_rows': correction_error_rows,
            'emphasis_change_period': self.emphasis_change_period,
            'emphasis_correction_error': self.emphasis_correction_error,
            'replace_going_concern_paragraph': self.replace_going_concern_paragraph,
            'replace_going_concern_year': self.replace_going_concern_year or False,
            'emphasis_change_from_date': (
                self.emphasis_change_from_date.isoformat() if self.emphasis_change_from_date else False
            ),
            'emphasis_change_to_date': (
                self.emphasis_change_to_date.isoformat() if self.emphasis_change_to_date else False
            ),
            'additional_note_legal_status_change': self.additional_note_legal_status_change,
            'additional_note_no_active_bank_account': self.additional_note_no_active_bank_account,
            'additional_note_business_bank_account_opened': self.additional_note_business_bank_account_opened,
            'emphasis_legal_change_date': (
                self.emphasis_legal_change_date.isoformat() if self.emphasis_legal_change_date else False
            ),
            'emphasis_legal_status_from': self.emphasis_legal_status_from,
            'emphasis_legal_status_to': self.emphasis_legal_status_to,
            'tb_convert_balances_to_usd': self.tb_convert_balances_to_usd,
            'tb_usd_conversion_rate': self.tb_usd_conversion_rate,
            'replace_aed_text_with_usd': self.replace_aed_text_with_usd,
            'tb_enable_date_navigator': self.tb_enable_date_navigator,
        }
        for i in range(1, 11):
            include_key = f'signature_include_{i}'
            role_key = f'signature_role_{i}'
            director_key = f'director_include_{i}'
            owner_key = f'owner_include_{i}'
            data[include_key] = bool(getattr(self, include_key))
            data[role_key] = getattr(self, role_key) or ('primary' if i == 1 else 'secondary')
            data[director_key] = bool(getattr(self, director_key))
            data[owner_key] = bool(getattr(self, owner_key))
        self.env['ir.config_parameter'].sudo().set_param(
            self._previous_settings_key(),
            json.dumps(data),
        )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if not res.get('use_previous_settings', True):
            if 'related_party_line_ids' in fields_list and not res.get('related_party_line_ids'):
                res['related_party_line_ids'] = self._related_party_rows_to_commands(
                    include_blank=True
                )
            if 'correction_error_line_ids' in fields_list and not res.get('correction_error_line_ids'):
                res['correction_error_line_ids'] = self._correction_error_rows_to_commands()
            return res
        data = self._get_previous_settings()
        if not data:
            if 'related_party_line_ids' in fields_list and not res.get('related_party_line_ids'):
                res['related_party_line_ids'] = self._related_party_rows_to_commands(
                    include_blank=True
                )
            if 'correction_error_line_ids' in fields_list and not res.get('correction_error_line_ids'):
                res['correction_error_line_ids'] = self._correction_error_rows_to_commands()
            return res
        related_party_rows = self._resolve_related_party_rows_payload(
            data,
            include_blank=True,
        )
        correction_error_rows = self._resolve_correction_error_rows_payload(data)
        if 'related_party_line_ids' in fields_list:
            res['related_party_line_ids'] = self._related_party_rows_to_commands(
                related_party_rows
            )
        if 'correction_error_line_ids' in fields_list:
            res['correction_error_line_ids'] = self._correction_error_rows_to_commands(
                correction_error_rows
            )
        allowed_signature_date_modes = {
            value
            for value, _label in self.SIGNATURE_DATE_MODE_SELECTION
        }
        if 'date_start' in fields_list and data.get('date_start'):
            res['date_start'] = fields.Date.to_date(data['date_start'])
        if 'date_end' in fields_list and data.get('date_end'):
            res['date_end'] = fields.Date.to_date(data['date_end'])
        if 'balance_sheet_date_mode' in fields_list and data.get('balance_sheet_date_mode'):
            res['balance_sheet_date_mode'] = data['balance_sheet_date_mode']
        if 'prior_year_mode' in fields_list and data.get('prior_year_mode'):
            res['prior_year_mode'] = data['prior_year_mode']
        if 'prior_balance_sheet_date_mode' in fields_list:
            value = data.get('prior_balance_sheet_date_mode') or data.get('balance_sheet_date_mode')
            if value:
                res['prior_balance_sheet_date_mode'] = value
        if 'prior_date_start' in fields_list and data.get('prior_date_start'):
            res['prior_date_start'] = fields.Date.to_date(data['prior_date_start'])
        if 'prior_date_end' in fields_list and data.get('prior_date_end'):
            res['prior_date_end'] = fields.Date.to_date(data['prior_date_end'])
        if 'soce_prior_opening_label_date' in fields_list and data.get('soce_prior_opening_label_date'):
            res['soce_prior_opening_label_date'] = fields.Date.to_date(
                data['soce_prior_opening_label_date']
            )
        if 'report_type' in fields_list and data.get('report_type'):
            res['report_type'] = data['report_type']
        if 'portal_account_no' in fields_list and data.get('portal_account_no') is not None:
            res['portal_account_no'] = data['portal_account_no'] or False
        if 'audit_period_category' in fields_list and data.get('audit_period_category'):
            res['audit_period_category'] = data['audit_period_category']
        if 'show_related_parties_note' in fields_list and data.get('show_related_parties_note') is not None:
            res['show_related_parties_note'] = data['show_related_parties_note']
        if 'show_shareholder_note' in fields_list and data.get('show_shareholder_note') is not None:
            res['show_shareholder_note'] = data['show_shareholder_note']
        if (
            'business_activity_include_services' in fields_list
            and data.get('business_activity_include_services') is not None
        ):
            res['business_activity_include_services'] = data['business_activity_include_services']
        if (
            'business_activity_include_providing' in fields_list
            and data.get('business_activity_include_providing') is not None
        ):
            res['business_activity_include_providing'] = data['business_activity_include_providing']
        if 'show_ct_first_tax_year_line' in fields_list and data.get('show_ct_first_tax_year_line') is not None:
            res['show_ct_first_tax_year_line'] = data['show_ct_first_tax_year_line']
        if (
            'show_other_comprehensive_income_page' in fields_list
            and data.get('show_other_comprehensive_income_page') is not None
        ):
            res['show_other_comprehensive_income_page'] = data['show_other_comprehensive_income_page']
        if (
            'cashflow_net_profit_use_after_tax' in fields_list
            and data.get('cashflow_net_profit_use_after_tax') is not None
        ):
            res['cashflow_net_profit_use_after_tax'] = data['cashflow_net_profit_use_after_tax']
        if (
            'show_unaudited_prior_year' in fields_list
            and data.get('show_unaudited_prior_year') is not None
        ):
            res['show_unaudited_prior_year'] = data['show_unaudited_prior_year']
        if 'usd_statement' in fields_list and data.get('usd_statement') is not None:
            res['usd_statement'] = data['usd_statement']
        if 'draft_watermark' in fields_list and data.get('draft_watermark') is not None:
            res['draft_watermark'] = data['draft_watermark']
        if (
            'ignore_notes_last_page_margins' in fields_list
            and data.get('ignore_notes_last_page_margins') is not None
        ):
            res['ignore_notes_last_page_margins'] = data['ignore_notes_last_page_margins']
        if (
            'show_investment_note_schedule' in fields_list
            and data.get('show_investment_note_schedule') is not None
        ):
            res['show_investment_note_schedule'] = data['show_investment_note_schedule']
        if 'gap_report_of_directors' in fields_list and data.get('gap_report_of_directors') is not None:
            res['gap_report_of_directors'] = data['gap_report_of_directors']
        if (
            'gap_independent_auditor_report' in fields_list
            and data.get('gap_independent_auditor_report') is not None
        ):
            res['gap_independent_auditor_report'] = data['gap_independent_auditor_report']
        if (
            'gap_notes_to_financial_statements' in fields_list
            and data.get('gap_notes_to_financial_statements') is not None
        ):
            res['gap_notes_to_financial_statements'] = data['gap_notes_to_financial_statements']
        old_directors_breaks = data.get('signature_break_lines_directors')
        old_other_breaks = data.get('signature_break_lines_other')
        if 'signature_break_lines_report_of_directors' in fields_list:
            value = data.get('signature_break_lines_report_of_directors')
            if value is None:
                value = old_directors_breaks if old_directors_breaks is not None else old_other_breaks
            if value is not None:
                res['signature_break_lines_report_of_directors'] = value
        if 'signature_break_lines_balance_sheet' in fields_list:
            value = data.get('signature_break_lines_balance_sheet')
            if value is None:
                value = old_other_breaks
            if value is not None:
                res['signature_break_lines_balance_sheet'] = value
        if 'signature_break_lines_profit_loss' in fields_list:
            value = data.get('signature_break_lines_profit_loss')
            if value is None:
                value = old_other_breaks
            if value is not None:
                res['signature_break_lines_profit_loss'] = value
        if 'signature_break_lines_changes_in_equity' in fields_list:
            value = data.get('signature_break_lines_changes_in_equity')
            if value is None:
                value = old_other_breaks
            if value is not None:
                res['signature_break_lines_changes_in_equity'] = value
        if 'signature_break_lines_cash_flows' in fields_list:
            value = data.get('signature_break_lines_cash_flows')
            if value is None:
                value = old_other_breaks
            if value is not None:
                res['signature_break_lines_cash_flows'] = value
        if 'signature_break_lines_notes' in fields_list:
            value = data.get('signature_break_lines_notes')
            if value is None:
                value = old_other_breaks
            if value is not None:
                res['signature_break_lines_notes'] = value
        if (
            'signature_date_mode' in fields_list
            and data.get('signature_date_mode') in allowed_signature_date_modes
        ):
            res['signature_date_mode'] = data['signature_date_mode']
        if 'signature_manual_date' in fields_list and data.get('signature_manual_date'):
            res['signature_manual_date'] = fields.Date.to_date(data['signature_manual_date'])
        if 'share_capital_paid_status' in fields_list and data.get('share_capital_paid_status'):
            res['share_capital_paid_status'] = data['share_capital_paid_status']
        if (
            'show_share_capital_conversion_note' in fields_list
            and data.get('show_share_capital_conversion_note') is not None
        ):
            res['show_share_capital_conversion_note'] = data['show_share_capital_conversion_note']
        if 'share_conversion_currency' in fields_list and data.get('share_conversion_currency') is not None:
            res['share_conversion_currency'] = data['share_conversion_currency']
        if (
            'share_conversion_original_value' in fields_list
            and data.get('share_conversion_original_value') is not None
        ):
            res['share_conversion_original_value'] = data['share_conversion_original_value']
        if (
            'share_conversion_exchange_rate' in fields_list
            and data.get('share_conversion_exchange_rate') is not None
        ):
            res['share_conversion_exchange_rate'] = data['share_conversion_exchange_rate']
        if (
            'show_share_capital_transfer_note' in fields_list
            and data.get('show_share_capital_transfer_note') is not None
        ):
            res['show_share_capital_transfer_note'] = data['show_share_capital_transfer_note']
        if 'share_transfer_date' in fields_list and data.get('share_transfer_date'):
            res['share_transfer_date'] = fields.Date.to_date(data['share_transfer_date'])
        if 'share_transfer_from' in fields_list and data.get('share_transfer_from') is not None:
            res['share_transfer_from'] = data['share_transfer_from']
        if 'share_transfer_shares' in fields_list and data.get('share_transfer_shares') is not None:
            res['share_transfer_shares'] = data['share_transfer_shares']
        if 'share_transfer_percentage' in fields_list and data.get('share_transfer_percentage') is not None:
            res['share_transfer_percentage'] = data['share_transfer_percentage']
        if 'share_transfer_to' in fields_list and data.get('share_transfer_to') is not None:
            res['share_transfer_to'] = data['share_transfer_to']
        if 'related_party_name' in fields_list and data.get('related_party_name'):
            res['related_party_name'] = data['related_party_name']
        if 'related_party_relationship' in fields_list and data.get('related_party_relationship'):
            res['related_party_relationship'] = data['related_party_relationship']
        if 'related_party_transaction' in fields_list and data.get('related_party_transaction'):
            res['related_party_transaction'] = data['related_party_transaction']
        if 'related_party_amount' in fields_list and data.get('related_party_amount') is not None:
            res['related_party_amount'] = data['related_party_amount']
        if 'related_party_amount_prior' in fields_list and data.get('related_party_amount_prior') is not None:
            res['related_party_amount_prior'] = data['related_party_amount_prior']
        if 'correction_error_note_body' in fields_list and data.get('correction_error_note_body') is not None:
            res['correction_error_note_body'] = data['correction_error_note_body']
        if 'emphasis_change_period' in fields_list and data.get('emphasis_change_period') is not None:
            res['emphasis_change_period'] = data['emphasis_change_period']
        if 'emphasis_correction_error' in fields_list and data.get('emphasis_correction_error') is not None:
            res['emphasis_correction_error'] = data['emphasis_correction_error']
        if (
            'replace_going_concern_paragraph' in fields_list
            and data.get('replace_going_concern_paragraph') is not None
        ):
            res['replace_going_concern_paragraph'] = data['replace_going_concern_paragraph']
        if 'replace_going_concern_year' in fields_list:
            value = data.get('replace_going_concern_year')
            if value is None and data.get('replace_going_concern_paragraph'):
                value = LEGACY_LIQUIDATION_GOING_CONCERN_YEAR
            if value is not None:
                res['replace_going_concern_year'] = value
        if 'emphasis_change_from_date' in fields_list and data.get('emphasis_change_from_date'):
            res['emphasis_change_from_date'] = fields.Date.to_date(data['emphasis_change_from_date'])
        if 'emphasis_change_to_date' in fields_list and data.get('emphasis_change_to_date'):
            res['emphasis_change_to_date'] = fields.Date.to_date(data['emphasis_change_to_date'])
        if (
            'additional_note_legal_status_change' in fields_list
            and data.get('additional_note_legal_status_change') is not None
        ):
            res['additional_note_legal_status_change'] = data['additional_note_legal_status_change']
        if (
            'additional_note_no_active_bank_account' in fields_list
            and data.get('additional_note_no_active_bank_account') is not None
        ):
            res['additional_note_no_active_bank_account'] = data['additional_note_no_active_bank_account']
        if (
            'additional_note_business_bank_account_opened' in fields_list
            and data.get('additional_note_business_bank_account_opened') is not None
        ):
            res['additional_note_business_bank_account_opened'] = data[
                'additional_note_business_bank_account_opened'
            ]
        if 'emphasis_legal_change_date' in fields_list and data.get('emphasis_legal_change_date'):
            res['emphasis_legal_change_date'] = fields.Date.to_date(data['emphasis_legal_change_date'])
        if 'emphasis_legal_status_from' in fields_list and data.get('emphasis_legal_status_from'):
            res['emphasis_legal_status_from'] = data['emphasis_legal_status_from']
        if 'emphasis_legal_status_to' in fields_list and data.get('emphasis_legal_status_to'):
            res['emphasis_legal_status_to'] = data['emphasis_legal_status_to']
        if (
            'tb_convert_balances_to_usd' in fields_list
            and data.get('tb_convert_balances_to_usd') is not None
        ):
            res['tb_convert_balances_to_usd'] = data['tb_convert_balances_to_usd']
        if 'tb_usd_conversion_rate' in fields_list and data.get('tb_usd_conversion_rate') is not None:
            res['tb_usd_conversion_rate'] = data['tb_usd_conversion_rate']
        if (
            'replace_aed_text_with_usd' in fields_list
            and data.get('replace_aed_text_with_usd') is not None
        ):
            res['replace_aed_text_with_usd'] = data['replace_aed_text_with_usd']
        if (
            'tb_enable_date_navigator' in fields_list
            and data.get('tb_enable_date_navigator') is not None
        ):
            res['tb_enable_date_navigator'] = data['tb_enable_date_navigator']
        for i in range(1, 11):
            include_key = f'signature_include_{i}'
            role_key = f'signature_role_{i}'
            director_key = f'director_include_{i}'
            owner_key = f'owner_include_{i}'
            if include_key in fields_list and data.get(include_key) is not None:
                res[include_key] = data[include_key]
            if role_key in fields_list and data.get(role_key):
                res[role_key] = data[role_key]
            if director_key in fields_list and data.get(director_key) is not None:
                res[director_key] = data[director_key]
            if owner_key in fields_list and data.get(owner_key) is not None:
                res[owner_key] = data[owner_key]
        return res

    @api.onchange('use_previous_settings')
    def _onchange_use_previous_settings(self):
        if self.use_previous_settings:
            data = self._get_previous_settings() or {}
            self.related_party_line_ids = self._related_party_rows_to_commands(
                self._resolve_related_party_rows_payload(
                    data,
                    include_blank=True,
                ),
                clear_existing=True,
            )
            self.correction_error_line_ids = self._correction_error_rows_to_commands(
                self._resolve_correction_error_rows_payload(data),
                clear_existing=True,
            )
            allowed_signature_date_modes = {
                value
                for value, _label in self.SIGNATURE_DATE_MODE_SELECTION
            }
            if data.get('date_start'):
                self.date_start = fields.Date.to_date(data['date_start'])
            if data.get('date_end'):
                self.date_end = fields.Date.to_date(data['date_end'])
            if data.get('balance_sheet_date_mode'):
                self.balance_sheet_date_mode = data['balance_sheet_date_mode']
            if data.get('prior_year_mode'):
                self.prior_year_mode = data['prior_year_mode']
            prior_balance_sheet_mode = (
                data.get('prior_balance_sheet_date_mode')
                or data.get('balance_sheet_date_mode')
            )
            if prior_balance_sheet_mode:
                self.prior_balance_sheet_date_mode = prior_balance_sheet_mode
            if data.get('prior_date_start'):
                self.prior_date_start = fields.Date.to_date(data['prior_date_start'])
            if data.get('prior_date_end'):
                self.prior_date_end = fields.Date.to_date(data['prior_date_end'])
            if data.get('soce_prior_opening_label_date'):
                self.soce_prior_opening_label_date = fields.Date.to_date(
                    data['soce_prior_opening_label_date']
                )
            if data.get('report_type'):
                self.report_type = data['report_type']
            if data.get('portal_account_no') is not None:
                self.portal_account_no = data['portal_account_no'] or False
            if data.get('audit_period_category'):
                self.audit_period_category = data['audit_period_category']
            if data.get('show_related_parties_note') is not None:
                self.show_related_parties_note = data['show_related_parties_note']
            if data.get('show_shareholder_note') is not None:
                self.show_shareholder_note = data['show_shareholder_note']
            if data.get('business_activity_include_services') is not None:
                self.business_activity_include_services = data['business_activity_include_services']
            if data.get('business_activity_include_providing') is not None:
                self.business_activity_include_providing = data['business_activity_include_providing']
            if data.get('show_ct_first_tax_year_line') is not None:
                self.show_ct_first_tax_year_line = data['show_ct_first_tax_year_line']
            if data.get('show_other_comprehensive_income_page') is not None:
                self.show_other_comprehensive_income_page = data['show_other_comprehensive_income_page']
            if data.get('cashflow_net_profit_use_after_tax') is not None:
                self.cashflow_net_profit_use_after_tax = data['cashflow_net_profit_use_after_tax']
            if data.get('show_unaudited_prior_year') is not None:
                self.show_unaudited_prior_year = data['show_unaudited_prior_year']
            if data.get('usd_statement') is not None:
                self.usd_statement = data['usd_statement']
            if data.get('draft_watermark') is not None:
                self.draft_watermark = data['draft_watermark']
            if data.get('ignore_notes_last_page_margins') is not None:
                self.ignore_notes_last_page_margins = data['ignore_notes_last_page_margins']
            if data.get('show_investment_note_schedule') is not None:
                self.show_investment_note_schedule = data['show_investment_note_schedule']
            if data.get('gap_report_of_directors') is not None:
                self.gap_report_of_directors = data['gap_report_of_directors']
            if data.get('gap_independent_auditor_report') is not None:
                self.gap_independent_auditor_report = data['gap_independent_auditor_report']
            if data.get('gap_notes_to_financial_statements') is not None:
                self.gap_notes_to_financial_statements = data['gap_notes_to_financial_statements']
            old_directors_breaks = data.get('signature_break_lines_directors')
            old_other_breaks = data.get('signature_break_lines_other')
            if data.get('signature_break_lines_report_of_directors') is not None:
                self.signature_break_lines_report_of_directors = data['signature_break_lines_report_of_directors']
            elif old_directors_breaks is not None:
                self.signature_break_lines_report_of_directors = old_directors_breaks
            elif old_other_breaks is not None:
                self.signature_break_lines_report_of_directors = old_other_breaks
            if data.get('signature_break_lines_balance_sheet') is not None:
                self.signature_break_lines_balance_sheet = data['signature_break_lines_balance_sheet']
            elif old_other_breaks is not None:
                self.signature_break_lines_balance_sheet = old_other_breaks
            if data.get('signature_break_lines_profit_loss') is not None:
                self.signature_break_lines_profit_loss = data['signature_break_lines_profit_loss']
            elif old_other_breaks is not None:
                self.signature_break_lines_profit_loss = old_other_breaks
            if data.get('signature_break_lines_changes_in_equity') is not None:
                self.signature_break_lines_changes_in_equity = data['signature_break_lines_changes_in_equity']
            elif old_other_breaks is not None:
                self.signature_break_lines_changes_in_equity = old_other_breaks
            if data.get('signature_break_lines_cash_flows') is not None:
                self.signature_break_lines_cash_flows = data['signature_break_lines_cash_flows']
            elif old_other_breaks is not None:
                self.signature_break_lines_cash_flows = old_other_breaks
            if data.get('signature_break_lines_notes') is not None:
                self.signature_break_lines_notes = data['signature_break_lines_notes']
            elif old_other_breaks is not None:
                self.signature_break_lines_notes = old_other_breaks
            if data.get('signature_date_mode') in allowed_signature_date_modes:
                self.signature_date_mode = data['signature_date_mode']
            if data.get('signature_manual_date'):
                self.signature_manual_date = fields.Date.to_date(data['signature_manual_date'])
            if data.get('share_capital_paid_status'):
                self.share_capital_paid_status = data['share_capital_paid_status']
            if data.get('show_share_capital_conversion_note') is not None:
                self.show_share_capital_conversion_note = data['show_share_capital_conversion_note']
            if data.get('share_conversion_currency') is not None:
                self.share_conversion_currency = data['share_conversion_currency']
            if data.get('share_conversion_original_value') is not None:
                self.share_conversion_original_value = data['share_conversion_original_value']
            if data.get('share_conversion_exchange_rate') is not None:
                self.share_conversion_exchange_rate = data['share_conversion_exchange_rate']
            if data.get('show_share_capital_transfer_note') is not None:
                self.show_share_capital_transfer_note = data['show_share_capital_transfer_note']
            if data.get('share_transfer_date'):
                self.share_transfer_date = fields.Date.to_date(data['share_transfer_date'])
            if data.get('share_transfer_from') is not None:
                self.share_transfer_from = data['share_transfer_from']
            if data.get('share_transfer_shares') is not None:
                self.share_transfer_shares = data['share_transfer_shares']
            if data.get('share_transfer_percentage') is not None:
                self.share_transfer_percentage = data['share_transfer_percentage']
            if data.get('share_transfer_to') is not None:
                self.share_transfer_to = data['share_transfer_to']
            if data.get('related_party_name'):
                self.related_party_name = data['related_party_name']
            if data.get('related_party_relationship'):
                self.related_party_relationship = data['related_party_relationship']
            if data.get('related_party_transaction'):
                self.related_party_transaction = data['related_party_transaction']
            if data.get('related_party_amount') is not None:
                self.related_party_amount = data['related_party_amount']
            if data.get('related_party_amount_prior') is not None:
                self.related_party_amount_prior = data['related_party_amount_prior']
            if data.get('correction_error_note_body') is not None:
                self.correction_error_note_body = data['correction_error_note_body']
            if data.get('emphasis_change_period') is not None:
                self.emphasis_change_period = data['emphasis_change_period']
            if data.get('emphasis_correction_error') is not None:
                self.emphasis_correction_error = data['emphasis_correction_error']
            if data.get('replace_going_concern_paragraph') is not None:
                self.replace_going_concern_paragraph = data['replace_going_concern_paragraph']
            replacement_year = data.get('replace_going_concern_year')
            if replacement_year is None and data.get('replace_going_concern_paragraph'):
                replacement_year = LEGACY_LIQUIDATION_GOING_CONCERN_YEAR
            if replacement_year is not None:
                self.replace_going_concern_year = replacement_year
            if data.get('emphasis_change_from_date'):
                self.emphasis_change_from_date = fields.Date.to_date(data['emphasis_change_from_date'])
            if data.get('emphasis_change_to_date'):
                self.emphasis_change_to_date = fields.Date.to_date(data['emphasis_change_to_date'])
            if data.get('additional_note_legal_status_change') is not None:
                self.additional_note_legal_status_change = data['additional_note_legal_status_change']
            if data.get('additional_note_no_active_bank_account') is not None:
                self.additional_note_no_active_bank_account = data['additional_note_no_active_bank_account']
            if data.get('additional_note_business_bank_account_opened') is not None:
                self.additional_note_business_bank_account_opened = data[
                    'additional_note_business_bank_account_opened'
                ]
            if data.get('emphasis_legal_change_date'):
                self.emphasis_legal_change_date = fields.Date.to_date(data['emphasis_legal_change_date'])
            if data.get('emphasis_legal_status_from'):
                self.emphasis_legal_status_from = data['emphasis_legal_status_from']
            if data.get('emphasis_legal_status_to'):
                self.emphasis_legal_status_to = data['emphasis_legal_status_to']
            if data.get('tb_convert_balances_to_usd') is not None:
                self.tb_convert_balances_to_usd = data['tb_convert_balances_to_usd']
            if data.get('tb_usd_conversion_rate') is not None:
                self.tb_usd_conversion_rate = data['tb_usd_conversion_rate']
            if data.get('replace_aed_text_with_usd') is not None:
                self.replace_aed_text_with_usd = data['replace_aed_text_with_usd']
            if data.get('tb_enable_date_navigator') is not None:
                self.tb_enable_date_navigator = data['tb_enable_date_navigator']
            for i in range(1, 11):
                include_key = f'signature_include_{i}'
                role_key = f'signature_role_{i}'
                director_key = f'director_include_{i}'
                owner_key = f'owner_include_{i}'
                if data.get(include_key) is not None:
                    setattr(self, include_key, data[include_key])
                if data.get(role_key):
                    setattr(self, role_key, data[role_key])
                if data.get(director_key) is not None:
                    setattr(self, director_key, data[director_key])
                if data.get(owner_key) is not None:
                    setattr(self, owner_key, data[owner_key])
        else:
            self.date_start = False
            self.date_end = False
            self.balance_sheet_date_mode = 'end_only'
            self.prior_year_mode = 'auto'
            self.prior_balance_sheet_date_mode = 'end_only'
            self.prior_date_start = False
            self.prior_date_end = False
            self.soce_prior_opening_label_date = False
            self.report_type = 'period'
            self.portal_account_no = False
            self.audit_period_category = 'normal_2y'
            self.show_related_parties_note = False
            self.show_shareholder_note = True
            self.business_activity_include_services = True
            self.business_activity_include_providing = True
            self.show_ct_first_tax_year_line = True
            self.show_other_comprehensive_income_page = False
            self.cashflow_net_profit_use_after_tax = False
            self.show_unaudited_prior_year = False
            self.usd_statement = False
            self.draft_watermark = False
            self.ignore_notes_last_page_margins = False
            self.show_investment_note_schedule = True
            self.gap_report_of_directors = True
            self.gap_independent_auditor_report = True
            self.gap_notes_to_financial_statements = True
            self.signature_break_lines_report_of_directors = 5
            self.signature_break_lines_balance_sheet = 5
            self.signature_break_lines_profit_loss = 5
            self.signature_break_lines_changes_in_equity = 5
            self.signature_break_lines_cash_flows = 5
            self.signature_break_lines_notes = 5
            self.signature_date_mode = 'today'
            self.signature_manual_date = False
            self.share_capital_paid_status = 'paid'
            self.show_share_capital_conversion_note = False
            self.share_conversion_currency = 'GBP'
            self.share_conversion_original_value = 100.0
            self.share_conversion_exchange_rate = 4.66
            self.show_share_capital_transfer_note = False
            self.share_transfer_date = False
            self.share_transfer_from = False
            self.share_transfer_shares = 0
            self.share_transfer_percentage = 0.0
            self.share_transfer_to = False
            self.related_party_name = False
            self.related_party_relationship = False
            self.related_party_transaction = False
            self.related_party_amount = 0.0
            self.related_party_amount_prior = 0.0
            self.related_party_line_ids = self._related_party_rows_to_commands(
                include_blank=True,
                clear_existing=True,
            )
            self.correction_error_note_body = False
            self.correction_error_line_ids = self._correction_error_rows_to_commands(
                clear_existing=True,
            )
            self.emphasis_change_period = False
            self.emphasis_correction_error = False
            self.replace_going_concern_paragraph = False
            self.replace_going_concern_year = False
            self.emphasis_change_from_date = False
            self.emphasis_change_to_date = False
            self.additional_note_legal_status_change = False
            self.additional_note_no_active_bank_account = False
            self.additional_note_business_bank_account_opened = False
            self.emphasis_legal_change_date = False
            self.emphasis_legal_status_from = False
            self.emphasis_legal_status_to = False
            self.tb_convert_balances_to_usd = False
            self.tb_usd_conversion_rate = 3.6725
            self.replace_aed_text_with_usd = False
            self.tb_include_zero_accounts = False
            self.tb_enable_date_navigator = False
            self.tb_override_line_ids = [(5, 0, 0)]
            self.tb_overrides_json = False
            self.tb_diff_current = 0.0
            self.tb_diff_prior = 0.0
            self.tb_warning_current = False
            self.tb_warning_prior = False
            self.company_id = self.env.company
            for i in range(1, 11):
                setattr(self, f'signature_include_{i}', False)
                setattr(self, f'signature_role_{i}', 'primary' if i == 1 else 'secondary')
                setattr(self, f'director_include_{i}', i == 1)
                setattr(self, f'owner_include_{i}', True)

    @api.onchange('emphasis_change_period')
    def _onchange_emphasis_change_period(self):
        if not self.emphasis_change_period:
            self.emphasis_change_from_date = False
            self.emphasis_change_to_date = False

    @api.onchange('additional_note_legal_status_change')
    def _onchange_additional_note_legal_status_change(self):
        if not self.additional_note_legal_status_change:
            self.emphasis_legal_change_date = False
            self.emphasis_legal_status_from = False
            self.emphasis_legal_status_to = False

    @api.onchange('signature_date_mode')
    def _onchange_signature_date_mode(self):
        if self.signature_date_mode != 'manual':
            self.signature_manual_date = False

    @api.onchange('usd_statement')
    def _onchange_usd_statement(self):
        if self.usd_statement:
            self.tb_convert_balances_to_usd = True
            self.replace_aed_text_with_usd = True

    def _validate_comparative_disclosure_options(self):
        self.ensure_one()
        if self.emphasis_correction_error and self.show_unaudited_prior_year:
            raise ValidationError(
                "Correction of Error and Unaudited prior year cannot both be enabled at the same time."
            )

    def _get_prior_year_date_warning_message(self):
        self.ensure_one()
        period_category = (self.audit_period_category or '').lower()
        show_prior_year = not period_category.endswith('_1y')
        if not show_prior_year or self.prior_year_mode != 'manual':
            return False

        warning_lines = []
        if self.prior_date_start and self.date_start and self.prior_date_start >= self.date_start:
            warning_lines.append(
                _(
                    "Prior year start date (%s) should be before current year start date (%s)."
                ) % (
                    self.prior_date_start.strftime('%d %B %Y'),
                    self.date_start.strftime('%d %B %Y'),
                )
            )
        if self.prior_date_end and self.date_end and self.prior_date_end >= self.date_end:
            warning_lines.append(
                _(
                    "Prior year end date (%s) should be before current year end date (%s)."
                ) % (
                    self.prior_date_end.strftime('%d %B %Y'),
                    self.date_end.strftime('%d %B %Y'),
                )
            )
        return "\n".join(warning_lines) if warning_lines else False

    @api.onchange(
        'audit_period_category',
        'prior_year_mode',
        'date_start',
        'date_end',
        'prior_date_start',
        'prior_date_end',
    )
    def _onchange_prior_year_dates_warning(self):
        self.ensure_one()
        warning_message = self._get_prior_year_date_warning_message()
        if warning_message:
            return {
                'warning': {
                    'title': _('Prior year dates'),
                    'message': warning_message,
                }
            }
        return {}

    def _validate_emphasis_options(self):
        self.ensure_one()
        self._validate_comparative_disclosure_options()
        if (self.shareholder_1 or "").strip() and not self.signature_include_1:
            self.signature_include_1 = True
            _logger.warning(
                "Auto-enabled first shareholder signatory for wizard_id=%s because shareholder_1 is set.",
                self.id,
            )

        prior_year_date_warning = self._get_prior_year_date_warning_message()
        if prior_year_date_warning:
            _logger.warning(
                "Prior year dates warning for wizard_id=%s: %s",
                self.id,
                prior_year_date_warning,
            )

        period_category = (self.audit_period_category or '').lower()
        show_prior_year = not period_category.endswith('_1y')

        missing_generation_fields = self._get_report_generation_missing_field_issues(show_prior_year)
        if missing_generation_fields:
            raise ValidationError(
                _(
                    "AUDIT REPORT REQUIRED FIELDS MISSING: Unable to generate PDF. "
                    "Please complete the following fields before continuing:\n%s"
                ) % "\n".join(f"- {issue}" for issue in missing_generation_fields)
            )

        # Validate at least one signatory is selected
        has_signatory = any(
            getattr(self, f'signature_include_{i}', False)
            for i in range(1, 11)
        )
        if not has_signatory:
            raise ValidationError(
                _("SIGNATORY REQUIRED: Unable to generate PDF. "
                  "Please go to the 'Signatories' section and select at least one signatory "
                  "(check the checkbox next to a shareholder name under 'Signatories').")
            )

        # Validate shareholder nationality when shareholder exists
        missing_nationalities = []
        for i in range(1, 11):
            shareholder = getattr(self, f'shareholder_{i}', False)
            nationality = getattr(self, f'nationality_{i}', False)
            if shareholder and (shareholder or "").strip():
                if not nationality or not (nationality or "").strip():
                    missing_nationalities.append(f"Shareholder {i}: {shareholder.strip()}")
        
        if missing_nationalities:
            shareholder_list = ", ".join(missing_nationalities)
            raise ValidationError(
                _("SHAREHOLDER NATIONALITY REQUIRED: Unable to generate PDF. "
                  "The following shareholder(s) are missing nationality:\n\n"
                  "%s\n\n"
                  "Please go to the 'Shareholders' section and enter the nationality for each shareholder "
                  "(e.g., 'Pakistani', 'Indian', 'British', etc.).") % shareholder_list
            )

        if self.signature_date_mode == 'manual' and not self.signature_manual_date:
            raise ValidationError(
                "Please provide Manual Signature Date when signature placeholder date mode is set to Manual date."
            )
        if self.emphasis_correction_error:
            note_body = (self.correction_error_note_body or '').strip()
            correction_rows = self._serialize_correction_error_rows_payload()
            if not note_body:
                raise ValidationError(
                    "Please provide Correction of Error note text when Correction of Error is enabled."
                )
            if not correction_rows:
                raise ValidationError(
                    "Please add at least one Correction of Error table row when Correction of Error is enabled."
                )
        if self.emphasis_change_period:
            if not self.emphasis_change_from_date or not self.emphasis_change_to_date:
                raise ValidationError(
                    "Please provide both 'Changed From' and 'Changed To' dates for Emphasis of Matter."
                )
            if self.emphasis_change_from_date >= self.emphasis_change_to_date:
                raise ValidationError(
                    "'Changed To' date must be after 'Changed From' date for Emphasis of Matter."
                )
        if self.additional_note_legal_status_change:
            if (
                not self.emphasis_legal_change_date
                or not self.emphasis_legal_status_from
                or not self.emphasis_legal_status_to
            ):
                raise ValidationError(
                    "Please provide Legal Change Date, Legal Status From, and Legal Status To for Additional Notes."
                )
        if self.show_share_capital_conversion_note:
            currency = (self.share_conversion_currency or '').strip()
            if not currency:
                raise ValidationError(
                    "Please provide Original Currency for the share capital conversion note."
                )
            if (self.share_conversion_original_value or 0.0) <= 0.0:
                raise ValidationError(
                    "Original Value per Share must be greater than zero for the share capital conversion note."
                )
            if (self.share_conversion_exchange_rate or 0.0) <= 0.0:
                raise ValidationError(
                    "Exchange Rate must be greater than zero for the share capital conversion note."
                )
        if self.show_share_capital_transfer_note:
            if not self.share_transfer_date:
                raise ValidationError(
                    "Please provide Transfer Date for the share transfer note."
                )
            if not (self.share_transfer_from or '').strip():
                raise ValidationError(
                    "Please provide Transferred From for the share transfer note."
                )
            if (self.share_transfer_shares or 0) <= 0:
                raise ValidationError(
                    "No. of Shares Transferred must be greater than zero for the share transfer note."
                )
            percentage = self.share_transfer_percentage or 0.0
            if percentage <= 0.0:
                raise ValidationError(
                    "Transferred Shares (%) must be greater than zero for the share transfer note."
                )
            if percentage > 100.0:
                raise ValidationError(
                    "Transferred Shares (%) cannot be more than 100 for the share transfer note."
                )
            if not (self.share_transfer_to or '').strip():
                raise ValidationError(
                    "Please provide Transferred To for the share transfer note."
                )
        if self.replace_going_concern_paragraph:
            year = int(self.replace_going_concern_year or 0)
            if year <= 0:
                raise ValidationError(
                    "Please provide Liquidation Year for the replacement going concern paragraph."
                )
        if (self.usd_statement or self.tb_convert_balances_to_usd) and (self.tb_usd_conversion_rate or 0.0) <= 0.0:
            raise ValidationError(
                "Please provide a USD conversion rate greater than zero."
            )

    @staticmethod
    def _is_report_generation_value_missing(value):
        if isinstance(value, str):
            return not value.strip()
        return not value

    def _get_report_generation_missing_field_issues(self, show_prior_year=None):
        self.ensure_one()
        if show_prior_year is None:
            period_category = (self.audit_period_category or '').lower()
            show_prior_year = not period_category.endswith('_1y')

        missing_fields = []

        if show_prior_year and not self.soce_prior_opening_label_date:
            missing_fields.append(_(
                "SOCE FIRST BALANCE DATE REQUIRED: SOCE First Balance Date "
                "(2-year, label only) is missing in the 'Report Settings' tab."
            ))

        required_company_fields = [
            ('company_free_zone', _("FREE ZONE REQUIRED"), _("Company Free Zone")),
            ('company_street', _("COMPANY ADDRESS REQUIRED"), _("Address")),
            ('company_city', _("COMPANY CITY REQUIRED"), _("City")),
            ('company_license_number', _("COMPANY LICENSE NUMBER REQUIRED"), _("Company License Number")),
            ('trade_license_activities', _("TRADE LICENSE NUMBER REQUIRED"), _("Trade License Activities")),
            ('incorporation_date', _("CORPORATE INCORPORATION NUMBER REQUIRED"), _("Company Incorporation Date")),
            (
                'corporate_tax_registration_number',
                _("CORPORATE TAX REGISTRATION NUMBER REQUIRED"),
                _("Corporate Tax Registration Number"),
            ),
            ('corporate_tax_start_date', _("CORPORATE TAX START DATE REQUIRED"), _("Corporate Tax Start Date")),
            ('corporate_tax_end_date', _("CORPORATE TAX END DATE REQUIRED"), _("Corporate Tax End Date")),
            (
                'implementing_regulations_freezone',
                _("FREE ZONE REGULATIONS REQUIRED"),
                _("Implementing Regulations for Free Zones"),
            ),
        ]
        if (self.company_free_zone or '') == 'Dubai Multi Commodities Centre Free Zone':
            required_company_fields.append(
                ('portal_account_no', _("PORTAL ACCOUNT REQUIRED"), _("Portal Account"))
            )

        for field_name, issue_title, field_label in required_company_fields:
            if self._is_report_generation_value_missing(getattr(self, field_name, False)):
                missing_fields.append(_(
                    "%(issue_title)s: %(field_label)s is missing in the 'Company Info' tab."
                ) % {
                    'issue_title': issue_title,
                    'field_label': field_label,
                })

        return missing_fields

    def _action_open_soce_pdf_confirmation(self):
        self.ensure_one()
        confirmation = self.env['audit.report.soce.pdf.confirmation'].create({
            'report_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Review SOCE Date'),
            'res_model': 'audit.report.soce.pdf.confirmation',
            'view_mode': 'form',
            'res_id': confirmation.id,
            'target': 'new',
        }

    @api.onchange(
        'company_street',
        'company_city',
        'company_free_zone',
        'company_license_number',
        'trade_license_activities',
        'incorporation_date',
        'corporate_tax_registration_number',
        'vat_registration_number',
        'corporate_tax_start_date',
        'corporate_tax_end_date',
        'implementing_regulations_freezone',
        'shareholder_1',
        'shareholder_2',
        'shareholder_3',
        'shareholder_4',
        'shareholder_5',
        'shareholder_6',
        'shareholder_7',
        'shareholder_8',
        'shareholder_9',
        'shareholder_10',
        'nationality_1',
        'nationality_2',
        'nationality_3',
        'nationality_4',
        'nationality_5',
        'nationality_6',
        'nationality_7',
        'nationality_8',
        'nationality_9',
        'nationality_10',
        'number_of_shares_1',
        'number_of_shares_2',
        'number_of_shares_3',
        'number_of_shares_4',
        'number_of_shares_5',
        'number_of_shares_6',
        'number_of_shares_7',
        'number_of_shares_8',
        'number_of_shares_9',
        'number_of_shares_10',
        'share_value_1',
        'share_value_2',
        'share_value_3',
        'share_value_4',
        'share_value_5',
        'share_value_6',
        'share_value_7',
        'share_value_8',
        'share_value_9',
        'share_value_10',
    )
    def _onchange_sync_company_info(self):
        if not self.company_id:
            return
        vals = {
            'street': self.company_street or False,
            'city': self.company_city or False,
            'free_zone': self.company_free_zone or False,
            'company_license_number': self.company_license_number or False,
            'trade_license_activities': self.trade_license_activities or False,
            'incorporation_date': self.incorporation_date or False,
            'corporate_tax_registration_number': self.corporate_tax_registration_number or False,
            'vat_registration_number': self.vat_registration_number or False,
            'corporate_tax_start_date': self.corporate_tax_start_date or False,
            'corporate_tax_end_date': self.corporate_tax_end_date or False,
            'implementing_regulations_freezone': self.implementing_regulations_freezone or False,
            'shareholder_1': self.shareholder_1 or False,
            'shareholder_2': self.shareholder_2 or False,
            'shareholder_3': self.shareholder_3 or False,
            'shareholder_4': self.shareholder_4 or False,
            'shareholder_5': self.shareholder_5 or False,
            'shareholder_6': self.shareholder_6 or False,
            'shareholder_7': self.shareholder_7 or False,
            'shareholder_8': self.shareholder_8 or False,
            'shareholder_9': self.shareholder_9 or False,
            'shareholder_10': self.shareholder_10 or False,
            'nationality_1': self.nationality_1 or False,
            'nationality_2': self.nationality_2 or False,
            'nationality_3': self.nationality_3 or False,
            'nationality_4': self.nationality_4 or False,
            'nationality_5': self.nationality_5 or False,
            'nationality_6': self.nationality_6 or False,
            'nationality_7': self.nationality_7 or False,
            'nationality_8': self.nationality_8 or False,
            'nationality_9': self.nationality_9 or False,
            'nationality_10': self.nationality_10 or False,
            'number_of_shares_1': self.number_of_shares_1 or 0,
            'number_of_shares_2': self.number_of_shares_2 or 0,
            'number_of_shares_3': self.number_of_shares_3 or 0,
            'number_of_shares_4': self.number_of_shares_4 or 0,
            'number_of_shares_5': self.number_of_shares_5 or 0,
            'number_of_shares_6': self.number_of_shares_6 or 0,
            'number_of_shares_7': self.number_of_shares_7 or 0,
            'number_of_shares_8': self.number_of_shares_8 or 0,
            'number_of_shares_9': self.number_of_shares_9 or 0,
            'number_of_shares_10': self.number_of_shares_10 or 0,
            'share_value_1': self.share_value_1 or 0.0,
            'share_value_2': self.share_value_2 or 0.0,
            'share_value_3': self.share_value_3 or 0.0,
            'share_value_4': self.share_value_4 or 0.0,
            'share_value_5': self.share_value_5 or 0.0,
            'share_value_6': self.share_value_6 or 0.0,
            'share_value_7': self.share_value_7 or 0.0,
            'share_value_8': self.share_value_8 or 0.0,
            'share_value_9': self.share_value_9 or 0.0,
            'share_value_10': self.share_value_10 or 0.0,
        }
        self.company_id.write(vals)

    @api.onchange(*SHAREHOLDER_PREFERENCE_AUTOSAVE_FIELD_NAMES)
    def _onchange_autosave_shareholder_preferences(self):
        for wizard in self:
            if wizard.company_id and wizard.share_capital_paid_status:
                wizard.company_id.write({'company_share': wizard.share_capital_paid_status})
            wizard._store_previous_settings()

    def _resolve_soce_prior_opening_label_date(
        self,
        date_start=None,
        prior_date_start=None,
        prior_year_mode=None,
        show_prior_year=None,
    ):
        self.ensure_one()
        if show_prior_year is None:
            period_category = (self.audit_period_category or '').lower()
            show_prior_year = not period_category.endswith('_1y')
        if not show_prior_year:
            return False
        if self.soce_prior_opening_label_date:
            return fields.Date.to_date(self.soce_prior_opening_label_date)
        # Fallback: derive the prior period opening (start) date so downstream
        # calculations still have a usable date when the manual SOCE label date
        # is empty. The displayed first-balance label stays manual-only.
        if prior_year_mode is None:
            prior_year_mode = self.prior_year_mode
        if prior_year_mode == 'manual' and prior_date_start:
            return fields.Date.to_date(prior_date_start)
        effective_date_start = date_start or self.date_start
        if effective_date_start:
            return fields.Date.to_date(effective_date_start) - relativedelta(years=1)
        return False

    @api.depends(
        'audit_period_category',
        'soce_prior_opening_label_date',
    )
    def _compute_soce_warning_message(self):
        for record in self:
            period_category = (record.audit_period_category or '').lower()
            show_prior_year = not period_category.endswith('_1y')
            if not show_prior_year or record.soce_prior_opening_label_date:
                record.soce_warning_message = False
                continue

            record.soce_warning_message = _(
                "SOCE first balance date is empty; a fallback date (prior period opening) "
                "is used for calculations — set it manually to display the first balance label."
            )

    @api.depends(
        'audit_period_category',
        'prior_year_mode',
        'date_start',
        'date_end',
        'prior_date_start',
        'prior_date_end',
    )
    def _compute_prior_year_dates_warning_message(self):
        for record in self:
            record.prior_year_dates_warning_message = (
                record._get_prior_year_date_warning_message() or False
            )

    def _get_reporting_periods(self):
        self.ensure_one()
        date_start = self.date_start
        date_end = self.date_end
        period_category = (self.audit_period_category or '').lower()
        show_prior_year = not period_category.endswith('_1y')
        prior_year_mode = self.prior_year_mode
        prior_balance_sheet_date_mode = self.prior_balance_sheet_date_mode or 'end_only'
        prior_date_start_raw = self.prior_date_start
        prior_date_end_raw = self.prior_date_end
        soce_prior_opening_label_date = self._resolve_soce_prior_opening_label_date(
            date_start=date_start,
            prior_date_start=prior_date_start_raw,
            prior_year_mode=prior_year_mode,
            show_prior_year=show_prior_year,
        )

        if prior_year_mode == 'manual' and prior_date_start_raw and prior_date_end_raw:
            prior_date_start = fields.Date.to_date(prior_date_start_raw)
            prior_date_end = fields.Date.to_date(prior_date_end_raw)
        else:
            prior_date_start = date_start - relativedelta(years=1) if date_start else False
            prior_date_end = date_end - relativedelta(years=1) if date_end else False
        # Keep a label-only period range from raw wizard intent.
        # This preserves existing calculations while allowing dynamic year/period wording.
        prior_label_date_start = prior_date_start
        prior_label_date_end = prior_date_end

        prior_prior_date_start = (
            prior_date_start - relativedelta(years=1)
            if prior_date_start else False
        )
        prior_prior_date_end = (
            prior_date_end - relativedelta(years=1)
            if prior_date_end else False
        )

        # Balance-sheet figures now always come from the selected period's
        # closing balances in the native Odoo Trial Balance.
        balance_sheet_date_start = False
        prior_balance_sheet_date_start = False
        prior_prior_balance_sheet_date_start = False

        return {
            'date_start': date_start,
            'date_end': date_end,
            'period_category': period_category,
            'show_prior_year': show_prior_year,
            'prior_year_mode': prior_year_mode,
            'prior_balance_sheet_date_mode': prior_balance_sheet_date_mode,
            'prior_date_start': prior_date_start,
            'prior_date_end': prior_date_end,
            'prior_label_date_start': prior_label_date_start,
            'prior_label_date_end': prior_label_date_end,
            'prior_prior_date_start': prior_prior_date_start,
            'prior_prior_date_end': prior_prior_date_end,
            'balance_sheet_date_start': balance_sheet_date_start,
            'prior_balance_sheet_date_start': prior_balance_sheet_date_start,
            'prior_prior_balance_sheet_date_start': prior_prior_balance_sheet_date_start,
            'soce_prior_opening_label_date': soce_prior_opening_label_date,
        }

    def _fetch_grouped_account_rows(self, date_start, date_end):
        self.ensure_one()
        if not date_end:
            return []

        domain = [
            ('date', '<=', date_end),
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
        ]
        if date_start:
            domain.insert(0, ('date', '>=', date_start))

        move_line_env = self.env['account.move.line'].with_context(
            allowed_company_ids=[self.company_id.id]
        )
        grouped_rows = move_line_env._read_group(
            domain=domain,
            groupby=['account_id'],
            aggregates=['debit:sum', 'credit:sum', 'balance:sum'],
        )

        account_ids = [account.id for account, _debit, _credit, _balance in grouped_rows if account]
        account_env = self.env['account.account'].with_company(self.company_id).with_context(
            allowed_company_ids=[self.company_id.id]
        )
        account_map = {acc.id: acc for acc in account_env.browse(account_ids)}

        final_rows = []
        for account_row, debit_sum, credit_sum, balance_sum in grouped_rows:
            if not account_row:
                continue
            account_id = account_row.id
            account = account_map.get(account_id)
            if not account:
                continue
            code_raw = (account.code or account.code_store or '').strip()
            code = self._normalize_account_code(code_raw)
            if not code:
                continue
            debit_value = self._to_float(debit_sum)
            credit_value = self._to_float(credit_sum)
            balance_value = self._to_float(balance_sum)
            if not self._is_display_non_zero(balance_value, precision=2):
                balance_value = debit_value - credit_value
            final_rows.append({
                'id': account_id,
                'code': code,
                'code_raw': code_raw,
                'name': account.name,
                'type': account.account_type,
                'debit': debit_value,
                'credit': credit_value,
                'balance': balance_value,
            })

        return final_rows

    def _get_odoo_trial_balance_report(self):
        self.ensure_one()
        report = self.env.ref('account_reports.trial_balance_report', raise_if_not_found=False)
        if not report:
            return False
        return report.with_company(self.company_id).with_context(
            allowed_company_ids=[self.company_id.id]
        )

    def _build_tb_override_trial_balance_options(self, trial_balance_report, date_start, date_end):
        self.ensure_one()
        return trial_balance_report.get_options({
            'selected_variant_id': trial_balance_report.id,
            'date': {
                'date_from': date_start or False,
                'date_to': date_end,
                'mode': 'range',
                'filter': 'custom',
            },
            'unfold_all': True,
            'hierarchy': False,
            'show_account': True,
            'report_title': f"{self.display_name or self.company_id.name or 'Audit Report'} Trial Balance",
        })

    def _tb_browser_options_field_name(self, period_key):
        self.ensure_one()
        if period_key == 'prior':
            return 'tb_prior_report_options_json'
        return 'tb_current_report_options_json'

    def _tb_override_period_range_from_state(self, period_key, wizard_state=None):
        self.ensure_one()
        if not wizard_state:
            return self._tb_override_period_range(period_key)

        period_category = (wizard_state.get('audit_period_category') or self.audit_period_category or '').lower()
        show_prior_year = not period_category.endswith('_1y')
        date_start = fields.Date.to_date(wizard_state.get('date_start')) if wizard_state.get('date_start') else False
        date_end = fields.Date.to_date(wizard_state.get('date_end')) if wizard_state.get('date_end') else False

        if period_key == 'prior':
            if not show_prior_year:
                return False, False

            prior_year_mode = wizard_state.get('prior_year_mode') or self.prior_year_mode
            prior_date_start = (
                fields.Date.to_date(wizard_state.get('prior_date_start'))
                if wizard_state.get('prior_date_start') else False
            )
            prior_date_end = (
                fields.Date.to_date(wizard_state.get('prior_date_end'))
                if wizard_state.get('prior_date_end') else False
            )
            if prior_year_mode == 'manual' and prior_date_start and prior_date_end:
                return prior_date_start, prior_date_end
            if not date_start or not date_end:
                return False, False
            return (
                date_start - relativedelta(years=1),
                date_end - relativedelta(years=1),
            )

        return date_start, date_end

    def _tb_override_browser_anchor(self, period_key, wizard_state=None):
        self.ensure_one()
        period_start, period_end = self._tb_override_period_range_from_state(
            period_key,
            wizard_state=wizard_state,
        )
        return {
            'period_key': period_key,
            'date_from': fields.Date.to_string(period_start) if period_start else False,
            'date_to': fields.Date.to_string(period_end) if period_end else False,
        }

    def _stamp_tb_browser_options_anchor(self, period_key, options, wizard_state=None):
        self.ensure_one()
        stamped_options = dict(options or {})
        stamped_options['audit_tb_browser_anchor'] = self._tb_override_browser_anchor(
            period_key,
            wizard_state=wizard_state,
        )
        return stamped_options

    def _tb_browser_options_match_current_period(self, period_key, options, wizard_state=None):
        self.ensure_one()
        if not isinstance(options, dict):
            return False

        expected_anchor = self._tb_override_browser_anchor(period_key, wizard_state=wizard_state)
        if not expected_anchor.get('date_to'):
            return False

        option_anchor = (options or {}).get('audit_tb_browser_anchor') or {}
        if option_anchor:
            return (
                option_anchor.get('period_key') == expected_anchor['period_key']
                and (option_anchor.get('date_from') or False) == (expected_anchor.get('date_from') or False)
                and (option_anchor.get('date_to') or False) == (expected_anchor.get('date_to') or False)
            )

        option_start, option_end = self._tb_override_period_dates_from_options(options)
        return (
            (fields.Date.to_string(option_start) if option_start else False) == (expected_anchor.get('date_from') or False)
            and (fields.Date.to_string(option_end) if option_end else False) == (expected_anchor.get('date_to') or False)
        )

    def _get_tb_browser_options(self, period_key):
        self.ensure_one()
        raw = getattr(self, self._tb_browser_options_field_name(period_key)) or ''
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _set_tb_browser_options(self, period_key, options):
        self.ensure_one()
        field_name = self._tb_browser_options_field_name(period_key)
        serialized = json.dumps(options or {})
        if getattr(self, field_name) != serialized:
            setattr(self, field_name, serialized)

    def _tb_browser_context_payload(self, trial_balance_report, period_key):
        self.ensure_one()
        wizard_id = self.id if isinstance(self.id, int) and self.id > 0 else False
        return {
            'report_id': trial_balance_report.id,
            'allowed_company_ids': [self.company_id.id],
            'audit_tb_override_wizard_id': wizard_id,
            'audit_tb_override_period_key': period_key,
            'audit_tb_embedded': True,
        }

    def _normalize_tb_override_trial_balance_options(self, options, trial_balance_report=None):
        self.ensure_one()
        report = trial_balance_report or self._get_odoo_trial_balance_report()
        if not report:
            return {}

        previous_options = dict(options or {})
        previous_options.setdefault('report_id', report.id)
        previous_options.setdefault('selected_variant_id', report.id)
        previous_options.setdefault('unfold_all', True)
        previous_options.setdefault('hierarchy', False)
        previous_options.setdefault('show_account', True)

        normalized_options = report.get_options(previous_options)
        normalized_options.setdefault('report_id', report.id)
        normalized_options.setdefault('selected_variant_id', report.id)
        normalized_options.setdefault('unfold_all', True)
        return normalized_options

    def _tb_override_target_column_groups(self, options, date_start=False, date_end=False):
        self.ensure_one()
        normalized_start = fields.Date.to_string(fields.Date.to_date(date_start)) if date_start else False
        normalized_end = fields.Date.to_string(fields.Date.to_date(date_end)) if date_end else False

        ordered_period_identities = []
        period_groups_by_identity = {}
        for column in (options or {}).get('columns', []):
            column_group_key = column.get('column_group_key')
            if not column_group_key:
                continue
            column_group = (options or {}).get('column_groups', {}).get(column_group_key) or {}
            forced_options = column_group.get('forced_options') or {}
            if forced_options.get('trial_balance_column_type') != 'period':
                continue

            column_date = forced_options.get('date') or {}
            identity = (
                forced_options.get('trial_balance_column_block_id') or False,
                (column_date.get('mode') or 'range'),
                column_date.get('date_from') or False,
                column_date.get('date_to') or False,
            )
            if identity not in period_groups_by_identity:
                ordered_period_identities.append(identity)
                period_groups_by_identity[identity] = []
            if column_group_key not in period_groups_by_identity[identity]:
                period_groups_by_identity[identity].append(column_group_key)

        if not ordered_period_identities:
            return {}

        matching_identity = None
        for identity in ordered_period_identities:
            _block_id, mode, group_date_start, group_date_end = identity
            effective_group_start = group_date_start if mode == 'range' else False
            if (
                (effective_group_start or False) == (normalized_start or False)
                and (group_date_end or False) == (normalized_end or False)
            ):
                matching_identity = identity
                break

        target_identity = matching_identity or ordered_period_identities[-1]
        target_block_id = target_identity[0]
        target_groups = {
            'initial_balance': set(),
            'period': set(),
            'end_balance': set(),
        }
        for column in (options or {}).get('columns', []):
            column_group_key = column.get('column_group_key')
            if not column_group_key:
                continue
            column_group = (options or {}).get('column_groups', {}).get(column_group_key) or {}
            forced_options = column_group.get('forced_options') or {}
            column_type = forced_options.get('trial_balance_column_type')
            if column_type not in target_groups:
                continue
            if (forced_options.get('trial_balance_column_block_id') or False) != target_block_id:
                continue
            target_groups[column_type].add(column_group_key)
        return target_groups

    def _tb_override_period_column_group_keys(self, options, date_start=False, date_end=False):
        self.ensure_one()
        return list(
            self._tb_override_target_column_groups(
                options,
                date_start=date_start,
                date_end=date_end,
            ).get('period') or []
        )

    @api.model
    def _tb_override_collect_column_totals(self, line, target_group_keys):
        totals = {
            'debit': 0.0,
            'credit': 0.0,
            'balance': 0.0,
        }
        if not target_group_keys:
            return False, totals

        matched_column = False
        matched_balance_column = False
        for column in (line or {}).get('columns', []):
            if column.get('column_group_key') not in target_group_keys:
                continue
            matched_column = True
            expression_label = column.get('expression_label')
            value = self._to_float(column.get('no_format'))
            if expression_label == 'debit':
                totals['debit'] += value
            elif expression_label == 'credit':
                totals['credit'] += value
            elif expression_label == 'balance':
                totals['balance'] += value
                matched_balance_column = True

        if matched_column and not matched_balance_column:
            totals['balance'] = totals['debit'] - totals['credit']
        return matched_column, totals

    def _extract_native_tb_rows_from_odoo_trial_balance_lines(self, trial_balance_report, options, lines):
        self.ensure_one()
        target_date_start, target_date_end = self._tb_override_period_dates_from_options(options)
        if not target_date_end:
            return []

        target_column_groups = self._tb_override_target_column_groups(
            options,
            target_date_start,
            target_date_end,
        )
        if not target_column_groups.get('period'):
            return []

        account_ids = set()
        amounts_by_account = {}
        for line in lines:
            line_id = line.get('id')
            if not line_id:
                continue
            account_id = trial_balance_report._get_res_id_from_line_id(line_id, 'account.account')
            if not account_id:
                continue

            initial_matched, initial_totals = self._tb_override_collect_column_totals(
                line,
                target_column_groups.get('initial_balance') or set(),
            )
            period_matched, period_totals = self._tb_override_collect_column_totals(
                line,
                target_column_groups.get('period') or set(),
            )
            end_matched, end_totals = self._tb_override_collect_column_totals(
                line,
                target_column_groups.get('end_balance') or set(),
            )
            if not (initial_matched or period_matched or end_matched):
                continue

            initial_balance = initial_totals['balance']
            if not initial_matched and end_matched:
                initial_balance = end_totals['balance'] - period_totals['debit'] + period_totals['credit']

            movement_balance = period_totals['debit'] - period_totals['credit']
            end_balance = end_totals['balance']
            if not end_matched:
                end_balance = initial_balance + movement_balance

            account_ids.add(account_id)
            amounts_by_account[account_id] = {
                'initial_balance': initial_balance,
                'debit': period_totals['debit'],
                'credit': period_totals['credit'],
                'movement_balance': movement_balance,
                'end_balance': end_balance,
            }

        if not account_ids:
            return []

        account_env = self.env['account.account'].with_company(self.company_id).with_context(
            allowed_company_ids=[self.company_id.id]
        )
        account_map = {account.id: account for account in account_env.browse(list(account_ids))}

        rows = []
        for account_id, amounts in amounts_by_account.items():
            account = account_map.get(account_id)
            if not account:
                continue
            code_raw = (account.code or account.code_store or '').strip()
            code = self._normalize_account_code(code_raw)
            if not code:
                continue
            rows.append({
                'id': account.id,
                'code': code,
                'code_raw': code_raw,
                'name': account.name,
                'type': account.account_type,
                'initial_balance': self._to_float(amounts.get('initial_balance')),
                'debit': self._to_float(amounts.get('debit')),
                'credit': self._to_float(amounts.get('credit')),
                'movement_balance': self._to_float(amounts.get('movement_balance')),
                'end_balance': self._to_float(amounts.get('end_balance')),
                'balance_role': 'closing',
                'balance': self._to_float(amounts.get('end_balance')),
            })

        rows.sort(key=lambda row: (row.get('code') or '', row.get('id') or 0))
        return rows

    def _apply_tb_override_import_from_options(self, options, period_key='current'):
        self.ensure_one()
        if period_key not in ('current', 'prior'):
            raise ValidationError("Invalid trial balance override period selected.")
        if period_key == 'prior' and not self._tb_navigator_supports_prior():
            raise ValidationError("Prior-period overrides are available only for 2-year reports.")

        trial_balance_report = self._get_odoo_trial_balance_report()
        if not trial_balance_report:
            raise ValidationError("Odoo Trial Balance report is not available in this database.")

        normalized_options = self._normalize_tb_override_trial_balance_options(
            options,
            trial_balance_report=trial_balance_report,
        )
        target_date_start, target_date_end = self._tb_override_period_dates_from_options(
            normalized_options
        )
        if not target_date_end:
            raise ValidationError("The selected Odoo Trial Balance does not have a valid date range to import.")

        rows = self._extract_tb_override_rows_from_odoo_trial_balance_options(normalized_options)
        write_vals = {
            'tb_browser_active_period': period_key,
        }
        if period_key == 'current':
            write_vals.update({
                'date_start': target_date_start,
                'date_end': target_date_end,
            })
        else:
            write_vals.update({
                'prior_year_mode': 'manual',
                'prior_date_start': target_date_start,
                'prior_date_end': target_date_end,
            })

        self.write(write_vals)
        self._set_tb_browser_options(
            period_key,
            self._stamp_tb_browser_options_anchor(period_key, normalized_options),
        )
        self._replace_tb_override_lines_for_period(period_key, rows)
        return {
            'period_key': period_key,
            'date_start': fields.Date.to_string(target_date_start) if target_date_start else False,
            'date_end': fields.Date.to_string(target_date_end) if target_date_end else False,
            'line_count': len(rows),
        }

    def _tb_override_client_line_field_names(self):
        self.ensure_one()
        return [
            'account_code',
            'account_name',
            'system_initial_balance',
            'system_balance',
            'override_initial_balance',
            'override_debit',
            'override_credit',
            'override_balance',
            'is_overridden',
            'system_debit',
            'system_credit',
            'effective_initial_balance',
            'effective_debit',
            'effective_credit',
            'effective_balance',
        ]

    def _tb_override_client_commands(self, period_key):
        self.ensure_one()
        if period_key == 'prior':
            line_ids = self.tb_override_prior_line_ids.sorted(
                key=lambda line: ((line.account_code or ''), line.id)
            )
        else:
            line_ids = self.tb_override_current_line_ids.sorted(
                key=lambda line: ((line.account_code or ''), line.id)
            )

        if not line_ids:
            return [(5, 0, 0)]

        line_values = {
            row['id']: row
            for row in line_ids.read(['id', *self._tb_override_client_line_field_names()])
        }
        commands = [(5, 0, 0)]
        for line in line_ids:
            server_row = line_values.get(line.id, {'id': line.id})
            commands.append((4, line.id, server_row))
            commands.append((
                1,
                line.id,
                {key: value for key, value in server_row.items() if key != 'id'},
            ))
        return commands

    def _get_tb_override_client_server_values(self):
        self.ensure_one()
        return {
            'date_start': fields.Date.to_string(self.date_start) if self.date_start else False,
            'date_end': fields.Date.to_string(self.date_end) if self.date_end else False,
            'prior_year_mode': self.prior_year_mode,
            'prior_date_start': (
                fields.Date.to_string(self.prior_date_start) if self.prior_date_start else False
            ),
            'prior_date_end': (
                fields.Date.to_string(self.prior_date_end) if self.prior_date_end else False
            ),
            'soce_prior_opening_label_date': (
                fields.Date.to_string(self.soce_prior_opening_label_date)
                if self.soce_prior_opening_label_date else False
            ),
            'tb_browser_active_period': self.tb_browser_active_period or 'current',
            'tb_current_report_options_json': self.tb_current_report_options_json or False,
            'tb_prior_report_options_json': self.tb_prior_report_options_json or False,
            'tb_diff_current': self.tb_diff_current or 0.0,
            'tb_diff_prior': self.tb_diff_prior or 0.0,
            'tb_warning_current': self.tb_warning_current or False,
            'tb_warning_prior': self.tb_warning_prior or False,
            'tb_override_current_line_ids': self._tb_override_client_commands('current'),
            'tb_override_prior_line_ids': (
                self._tb_override_client_commands('prior')
                if self._tb_navigator_supports_prior()
                else [(5, 0, 0)]
            ),
        }

    def get_tb_browser_config(self, period_key='current', requested_options=None, wizard_state=None):
        self.ensure_one()
        if period_key not in ('current', 'prior'):
            raise ValidationError("Invalid embedded trial balance period selected.")
        if period_key == 'prior' and not self._tb_navigator_supports_prior():
            raise ValidationError("Prior-period trial balance is available only for 2-year reports.")

        trial_balance_report = self._get_odoo_trial_balance_report()
        if not trial_balance_report:
            raise ValidationError("Odoo Trial Balance report is not available in this database.")

        options = {}
        candidate_options = requested_options if isinstance(requested_options, dict) else {}
        saved_options = self._get_tb_browser_options(period_key)

        if self._tb_browser_options_match_current_period(
            period_key,
            candidate_options,
            wizard_state=wizard_state,
        ):
            options = self._normalize_tb_override_trial_balance_options(
                candidate_options,
                trial_balance_report=trial_balance_report,
            )
        elif self._tb_browser_options_match_current_period(
            period_key,
            saved_options,
            wizard_state=wizard_state,
        ):
            options = self._normalize_tb_override_trial_balance_options(
                saved_options,
                trial_balance_report=trial_balance_report,
            )

        if not options:
            period_start, period_end = self._tb_override_period_range_from_state(
                period_key,
                wizard_state=wizard_state,
            )
            if not period_end:
                return {
                    'report_id': trial_balance_report.id,
                    'period_key': period_key,
                    'period_label': 'Prior' if period_key == 'prior' else 'Current',
                    'options': False,
                    'missing_dates': True,
                    'message': "Set the report dates to load the embedded Trial Balance.",
                    'context': self._tb_browser_context_payload(trial_balance_report, period_key),
                }
            options = self._build_tb_override_trial_balance_options(
                trial_balance_report,
                period_start,
                period_end,
            )
        options = self._stamp_tb_browser_options_anchor(
            period_key,
            options,
            wizard_state=wizard_state,
        )
        options.setdefault('report_id', trial_balance_report.id)
        options.setdefault('selected_variant_id', trial_balance_report.id)

        return {
            'report_id': trial_balance_report.id,
            'period_key': period_key,
            'period_label': 'Prior' if period_key == 'prior' else 'Current',
            'options': options,
            'context': self._tb_browser_context_payload(trial_balance_report, period_key),
        }

    def save_tb_browser_options(self, period_key, options):
        self.ensure_one()
        if period_key not in ('current', 'prior'):
            raise ValidationError("Invalid embedded trial balance period selected.")
        if period_key == 'prior' and not self._tb_navigator_supports_prior():
            raise ValidationError("Prior-period trial balance is available only for 2-year reports.")
        self.write({'tb_browser_active_period': period_key})
        normalized_options = self._normalize_tb_override_trial_balance_options(options)
        self._set_tb_browser_options(
            period_key,
            self._stamp_tb_browser_options_anchor(period_key, normalized_options),
        )
        return True

    @api.model
    def get_tb_browser_preview_config(self, company_id, period_key='current', requested_options=None, wizard_state=None):
        company = self.env['res.company'].browse(int(company_id)) if company_id else self.env.company
        if not company or not company.exists():
            raise ValidationError("A company is required to preview the embedded Trial Balance.")

        preview_vals = {
            'company_id': company.id,
        }
        wizard_state = wizard_state if isinstance(wizard_state, dict) else {}
        for field_name in ('audit_period_category', 'prior_year_mode'):
            if wizard_state.get(field_name):
                preview_vals[field_name] = wizard_state[field_name]
        for field_name in ('date_start', 'date_end', 'prior_date_start', 'prior_date_end'):
            if wizard_state.get(field_name):
                preview_vals[field_name] = fields.Date.to_date(wizard_state[field_name])

        preview_wizard = self.new(preview_vals)
        return preview_wizard.get_tb_browser_config(
            period_key=period_key,
            requested_options=requested_options,
            wizard_state=wizard_state,
        )

    def apply_tb_browser_options(self, period_key, options):
        self.ensure_one()
        result = self._apply_tb_override_import_from_options(
            options,
            period_key=period_key,
        )
        result['server_values'] = self._get_tb_override_client_server_values()
        return result

    def _tb_override_period_dates_from_options(self, options):
        self.ensure_one()
        date_options = (options or {}).get('date') or {}
        date_to_raw = date_options.get('date_to')
        if not date_to_raw:
            return False, False

        mode = date_options.get('mode') or 'range'
        date_start = date_options.get('date_from') if mode == 'range' else False
        return (
            fields.Date.to_date(date_start) if date_start else False,
            fields.Date.to_date(date_to_raw),
        )

    def _extract_tb_override_rows_from_odoo_trial_balance_options(self, options):
        self.ensure_one()
        trial_balance_report = self._get_odoo_trial_balance_report()
        if not trial_balance_report:
            return []

        normalized_options = dict(options or {})
        normalized_options.setdefault('report_id', trial_balance_report.id)
        normalized_options.setdefault('selected_variant_id', trial_balance_report.id)
        normalized_options.setdefault('unfold_all', True)

        target_date_start, target_date_end = self._tb_override_period_dates_from_options(
            normalized_options
        )
        if not target_date_end:
            return []

        lines = trial_balance_report._get_lines(normalized_options)
        return self._extract_native_tb_rows_from_odoo_trial_balance_lines(
            trial_balance_report,
            normalized_options,
            lines,
        )

    def _fetch_grouped_account_rows_from_odoo_trial_balance(self, date_start, date_end):
        self.ensure_one()
        if not date_end:
            return []

        trial_balance_report = self._get_odoo_trial_balance_report()
        if not trial_balance_report:
            return None

        options = self._build_tb_override_trial_balance_options(
            trial_balance_report,
            date_start,
            date_end,
        )
        lines = trial_balance_report._get_lines(options)
        return self._extract_native_tb_rows_from_odoo_trial_balance_lines(
            trial_balance_report,
            options,
            lines,
        )

    def _fetch_native_style_account_rows_from_move_lines(self, date_start, date_end):
        self.ensure_one()
        if not date_end:
            return []

        opening_end = date_start - relativedelta(days=1) if date_start else False
        opening_rows = self._fetch_grouped_account_rows(False, opening_end) if opening_end else []
        period_rows = self._fetch_grouped_account_rows(date_start, date_end)
        closing_rows = self._fetch_grouped_account_rows(False, date_end)

        rows_by_identity = {}

        def _get_or_create_entry(row):
            identity_key = self._tb_identity_keys(row.get('id'), row.get('code'))[:1]
            identity_key = identity_key[0] if identity_key else False
            if not identity_key:
                return False
            entry = rows_by_identity.get(identity_key)
            if entry:
                return entry
            entry = {
                'id': row.get('id'),
                'code': row.get('code'),
                'code_raw': row.get('code_raw'),
                'name': row.get('name') or '',
                'type': row.get('type'),
                'initial_balance': 0.0,
                'debit': 0.0,
                'credit': 0.0,
                'movement_balance': 0.0,
                'end_balance': 0.0,
                'balance_role': 'closing',
                'balance': 0.0,
            }
            rows_by_identity[identity_key] = entry
            return entry

        for row in opening_rows:
            entry = _get_or_create_entry(row)
            if entry:
                entry['initial_balance'] = self._to_float(row.get('balance'))

        for row in period_rows:
            entry = _get_or_create_entry(row)
            if entry:
                entry['debit'] = self._to_float(row.get('debit'))
                entry['credit'] = self._to_float(row.get('credit'))

        for row in closing_rows:
            entry = _get_or_create_entry(row)
            if entry:
                entry['end_balance'] = self._to_float(row.get('balance'))

        rows = []
        for entry in rows_by_identity.values():
            entry['movement_balance'] = (
                self._to_float(entry.get('debit'))
                - self._to_float(entry.get('credit'))
            )
            if not self._is_display_non_zero(entry.get('end_balance'), precision=2):
                entry['end_balance'] = (
                    self._to_float(entry.get('initial_balance'))
                    + self._to_float(entry.get('movement_balance'))
                )
            entry['balance'] = self._to_float(entry.get('end_balance'))
            rows.append(self._normalize_account_row(entry, balance_role='closing'))

        rows.sort(key=lambda row: (row.get('code') or '', row.get('id') or 0))
        return rows

    def _replace_tb_override_lines_for_period(self, period_key, rows):
        self.ensure_one()
        if period_key not in ('current', 'prior'):
            raise ValidationError("Invalid trial balance override period selected.")

        existing_lines = self.tb_override_line_ids.filtered(
            lambda line: line.period_key == period_key
        )
        lines_by_identity = {}
        for line in existing_lines:
            for identity_key in self._tb_identity_keys(
                line.account_id.id if line.account_id else False,
                line.account_code,
            ):
                lines_by_identity[identity_key] = line

        seen_line_ids = set()
        for row in rows:
            account_id = row.get('id')
            account_code = row.get('code')
            account_name = row.get('name') or ''
            system_initial_balance = self._to_float(row.get('initial_balance'))
            system_debit = self._to_float(row.get('debit'))
            system_credit = self._to_float(row.get('credit'))
            system_balance = self._to_float(row.get('balance'))
            identity_keys = self._tb_identity_keys(account_id, account_code)
            line = next(
                (lines_by_identity.get(identity_key) for identity_key in identity_keys if lines_by_identity.get(identity_key)),
                False,
            )
            system_vals = {
                'account_id': account_id or False,
                'account_code': account_code,
                'account_name': account_name,
                'system_initial_balance': system_initial_balance,
                'system_debit': system_debit,
                'system_credit': system_credit,
                'system_balance': system_balance,
                'override_initial_balance': system_initial_balance,
                'override_debit': system_debit,
                'override_credit': system_credit,
                'override_balance': system_balance,
            }
            if line:
                line.write(system_vals)
                seen_line_ids.add(line.id)
                continue

            created_line = self.env['audit.report.tb.override.line'].create({
                'wizard_id': self.id,
                'period_key': period_key,
                **system_vals,
            })
            seen_line_ids.add(created_line.id)

        existing_lines.filtered(lambda line: line.id not in seen_line_ids).unlink()
        self._sync_tb_overrides_json()
        try:
            self._get_report_data()
        except Exception as err:
            _logger.debug(
                "Trial balance warning refresh skipped after Odoo TB import for wizard_id=%s due to: %s",
                self.id,
                err,
            )

    def action_import_tb_overrides_from_odoo_trial_balance_options(self, options, period_key='current'):
        self.ensure_one()
        self._apply_tb_override_import_from_options(options, period_key=period_key)
        return self._reopen_wizard_form()

    def _build_tb_override_native_action(self, period_key):
        self.ensure_one()
        if period_key not in ('current', 'prior'):
            raise ValidationError("Invalid trial balance override period selected.")
        if period_key == 'prior' and not self._tb_navigator_supports_prior():
            raise ValidationError("Prior-period overrides are available only for 2-year reports.")

        period_start, period_end = self._tb_override_period_range(period_key)
        if not period_end:
            raise ValidationError("Set the report dates before opening Odoo Trial Balance.")

        trial_balance_report = self._get_odoo_trial_balance_report()
        if not trial_balance_report:
            raise ValidationError("Odoo Trial Balance report is not available in this database.")

        options = self._build_tb_override_trial_balance_options(
            trial_balance_report,
            period_start,
            period_end,
        )
        action = self.env['ir.actions.actions']._for_xml_id(
            'account_reports.action_account_report_coa'
        )
        action['context'] = {
            **self.env.context,
            'report_id': trial_balance_report.id,
            'allowed_company_ids': [self.company_id.id],
            'audit_tb_override_wizard_id': self.id,
            'audit_tb_override_period_key': period_key,
        }
        action['params'] = {
            'options': options,
            'ignore_session': True,
        }
        action['target'] = 'current'
        return action

    def _get_tb_override_system_rows(self, date_start, date_end, include_zero_accounts=False):
        self.ensure_one()
        rows = []
        try:
            odoo_rows = self._fetch_grouped_account_rows_from_odoo_trial_balance(date_start, date_end)
            if odoo_rows is None:
                rows = self._fetch_native_style_account_rows_from_move_lines(date_start, date_end)
            else:
                rows = odoo_rows
        except Exception as err:
            _logger.exception(
                "Falling back to raw grouped move-line TB loader for audit report wizard_id=%s due to: %s",
                self.id,
                err,
            )
            rows = self._fetch_native_style_account_rows_from_move_lines(date_start, date_end)

        if not include_zero_accounts:
            rows = [
                row for row in rows
                if any(
                    self._is_display_non_zero(row.get(field_name), precision=2)
                    for field_name in ('initial_balance', 'debit', 'credit', 'balance')
                )
            ]
        return rows

    def _get_tb_override_system_row_for_account(self, period_start, period_end, account):
        self.ensure_one()
        account_code = self._normalize_account_code(account.code or account.code_store or '')
        account_name = account.name or ''
        if not period_end:
            return self._normalize_account_row({
                'id': account.id,
                'code': account_code,
                'name': account_name,
                'initial_balance': 0.0,
                'debit': 0.0,
                'credit': 0.0,
                'movement_balance': 0.0,
                'end_balance': 0.0,
                'balance': 0.0,
            }, balance_role='closing')

        rows = self._get_tb_override_system_rows(
            period_start,
            period_end,
            include_zero_accounts=True,
        )
        row = next(
            (item for item in rows if int(item.get('id') or 0) == account.id),
            None,
        )
        if row:
            return row
        return self._normalize_account_row({
            'id': account.id,
            'code': account_code,
            'name': account_name,
            'initial_balance': 0.0,
            'debit': 0.0,
            'credit': 0.0,
            'movement_balance': 0.0,
            'end_balance': 0.0,
            'balance': 0.0,
        }, balance_role='closing')

    def _tb_identity_keys(self, account_id=False, account_code=False):
        keys = []
        if account_id:
            keys.append(('id', int(account_id)))
        normalized_code = self._normalize_account_code(account_code)
        if normalized_code:
            keys.append(('code', normalized_code))
        return keys

    def _serialize_lor_extra_items_payload(self):
        self.ensure_one()
        payload = []
        ordered_lines = self.lor_extra_item_line_ids.sorted(
            key=lambda line: (
                line.sequence or 0,
                line.id,
            )
        )
        for line in ordered_lines:
            item_text = (line.item_text or '').strip()
            if not item_text:
                continue
            payload.append({
                'sequence': int(line.sequence or 0),
                'text': item_text,
            })
        return payload

    def _sync_lor_extra_items_json(self):
        self.ensure_one()
        payload = self._serialize_lor_extra_items_payload()
        serialized = json.dumps(payload, ensure_ascii=False)
        if (self.lor_extra_items_json or '') != serialized:
            self.lor_extra_items_json = serialized
        return serialized

    def _deserialize_lor_extra_items_payload(self, serialized_payload=None):
        self.ensure_one()
        raw = serialized_payload if serialized_payload is not None else (self.lor_extra_items_json or '')
        if not raw:
            return []
        if isinstance(raw, list):
            entries = raw
        else:
            try:
                entries = json.loads(raw)
            except (TypeError, ValueError):
                return []
        if not isinstance(entries, list):
            return []
        cleaned = []
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            text_value = str(entry.get('text') or '').strip()
            if not text_value:
                continue
            try:
                sequence_value = int(entry.get('sequence') or (idx + 1) * 10)
            except (TypeError, ValueError):
                sequence_value = (idx + 1) * 10
            cleaned.append({
                'sequence': sequence_value,
                'text': text_value,
            })
        return cleaned

    def _apply_lor_extra_items_from_serialized_payload(self, serialized_payload):
        self.ensure_one()
        payload = self._deserialize_lor_extra_items_payload(serialized_payload)
        commands = [(5, 0, 0)]
        for index, item in enumerate(payload):
            commands.append((0, 0, {
                'sequence': int(item.get('sequence') or ((index + 1) * 10)),
                'item_text': item.get('text') or '',
            }))
        self.lor_extra_item_line_ids = commands
        self._sync_lor_extra_items_json()

    def _get_lor_extra_item_texts(self):
        self.ensure_one()
        if self.lor_extra_item_line_ids:
            return [
                (line.item_text or '').strip()
                for line in self.lor_extra_item_line_ids.sorted(
                    key=lambda line: (line.sequence or 0, line.id)
                )
                if (line.item_text or '').strip()
            ]
        return [
            item.get('text')
            for item in self._deserialize_lor_extra_items_payload()
            if item.get('text')
        ]

    @api.model
    def _blank_related_party_row_payload(self, sequence=10):
        return {
            'sequence': int(sequence or 10),
            'name': '',
            'relationship': '',
            'transaction': '',
            'amount': 0.0,
            'amount_prior': 0.0,
        }

    @api.model
    def _legacy_related_party_row_from_mapping(self, data):
        if not isinstance(data, dict):
            return False
        row = {
            'sequence': 10,
            'name': str(data.get('related_party_name') or '').strip(),
            'relationship': str(data.get('related_party_relationship') or '').strip(),
            'transaction': str(data.get('related_party_transaction') or '').strip(),
            'amount': self._to_float(data.get('related_party_amount')),
            'amount_prior': self._to_float(data.get('related_party_amount_prior')),
        }
        if not any([
            row['name'],
            row['relationship'],
            row['transaction'],
            row['amount'],
            row['amount_prior'],
        ]):
            return False
        return row

    @api.model
    def _normalize_related_party_rows_payload(self, rows=None, include_blank=False):
        if isinstance(rows, str):
            try:
                entries = json.loads(rows)
            except (TypeError, ValueError):
                entries = []
        elif isinstance(rows, list):
            entries = rows
        else:
            entries = []

        cleaned = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            try:
                sequence = int(entry.get('sequence') or ((index + 1) * 10))
            except (TypeError, ValueError):
                sequence = (index + 1) * 10
            row = {
                'sequence': sequence,
                'name': str(entry.get('name') or '').strip(),
                'relationship': str(entry.get('relationship') or '').strip(),
                'transaction': str(entry.get('transaction') or '').strip(),
                'amount': self._to_float(entry.get('amount')),
                'amount_prior': self._to_float(entry.get('amount_prior')),
            }
            if any([
                row['name'],
                row['relationship'],
                row['transaction'],
                row['amount'],
                row['amount_prior'],
            ]):
                cleaned.append(row)
        if not cleaned and include_blank:
            cleaned.append(self._blank_related_party_row_payload())
        return cleaned

    @api.model
    def _resolve_related_party_rows_payload(self, data=None, include_blank=False):
        payload = self._normalize_related_party_rows_payload(
            (data or {}).get('related_party_rows')
        )
        if not payload:
            legacy_row = self._legacy_related_party_row_from_mapping(data or {})
            if legacy_row:
                payload = [legacy_row]
        if not payload and include_blank:
            payload = [self._blank_related_party_row_payload()]
        return payload

    @api.model
    def _related_party_rows_to_commands(self, rows=None, include_blank=False, clear_existing=False):
        payload = self._normalize_related_party_rows_payload(rows, include_blank=include_blank)
        commands = [(5, 0, 0)] if clear_existing else []
        for index, row in enumerate(payload):
            commands.append((0, 0, {
                'sequence': int(row.get('sequence') or ((index + 1) * 10)),
                'party_name': row.get('name') or '',
                'relationship': row.get('relationship') or '',
                'transaction': row.get('transaction') or '',
                'amount': self._to_float(row.get('amount')),
                'amount_prior': self._to_float(row.get('amount_prior')),
            }))
        return commands

    def _serialize_related_party_rows_payload(self):
        self.ensure_one()
        ordered_lines = self.related_party_line_ids.sorted(
            key=lambda line: (
                line.sequence or 0,
                str(line.id or ''),
            )
        )
        payload = []
        for line in ordered_lines:
            payload.append({
                'sequence': int(line.sequence or 0),
                'name': (line.party_name or '').strip(),
                'relationship': (line.relationship or '').strip(),
                'transaction': (line.transaction or '').strip(),
                'amount': self._to_float(line.amount),
                'amount_prior': self._to_float(line.amount_prior),
            })
        return self._normalize_related_party_rows_payload(payload)

    @api.model
    def _to_sentence_case(self, text):
        """Convert text to sentence case (first letter capitalized, rest lowercase)."""
        text = str(text or '').strip()
        if not text:
            return ''
        # Normalize whitespace
        text = ' '.join(text.split())
        # Capitalize first letter, keep rest as-is for the first word
        # then apply sentence case logic
        return text[0].upper() + text[1:] if text else ''

    def _get_render_related_party_rows(self):
        self.ensure_one()
        rows = self._normalize_related_party_rows_payload(
            self._serialize_related_party_rows_payload(),
            include_blank=True,
        )
        # Apply sentence case to relationship and transaction, keep name as entered
        for row in rows:
            row['relationship'] = self._to_sentence_case(row.get('relationship') or '')
            row['transaction'] = self._to_sentence_case(row.get('transaction') or '')
        return rows

    @api.model
    def _blank_correction_error_row_payload(self, sequence=10, row_type='line'):
        normalized_row_type = row_type if row_type in {'section', 'subheading', 'text', 'line'} else 'line'
        return {
            'sequence': int(sequence or 10),
            'row_type': normalized_row_type,
            'description': '',
            'amount_as_reported': 0.0,
            'amount_as_restated': 0.0,
            'amount_restatement': 0.0,
        }

    @api.model
    def _normalize_correction_error_rows_payload(self, rows=None):
        if isinstance(rows, str):
            try:
                entries = json.loads(rows)
            except (TypeError, ValueError):
                entries = []
        elif isinstance(rows, list):
            entries = rows
        else:
            entries = []

        cleaned = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            try:
                sequence = int(entry.get('sequence') or ((index + 1) * 10))
            except (TypeError, ValueError):
                sequence = (index + 1) * 10
            row_type = str(entry.get('row_type') or 'line').strip().lower()
            if row_type not in {'section', 'subheading', 'text', 'line'}:
                row_type = 'line'
            row = {
                'sequence': sequence,
                'row_type': row_type,
                'description': str(entry.get('description') or '').strip(),
                'amount_as_reported': self._to_float(entry.get('amount_as_reported')),
                'amount_as_restated': self._to_float(entry.get('amount_as_restated')),
                'amount_restatement': self._to_float(entry.get('amount_restatement')),
            }
            if row_type != 'line':
                row['amount_as_reported'] = 0.0
                row['amount_as_restated'] = 0.0
                row['amount_restatement'] = 0.0
            if any([
                row['description'],
                row['amount_as_reported'],
                row['amount_as_restated'],
                row['amount_restatement'],
            ]):
                cleaned.append(row)
        return cleaned

    @api.model
    def _resolve_correction_error_rows_payload(self, data=None):
        return self._normalize_correction_error_rows_payload(
            (data or {}).get('correction_error_rows')
        )

    @api.model
    def _correction_error_rows_to_commands(self, rows=None, clear_existing=False):
        payload = self._normalize_correction_error_rows_payload(rows)
        commands = [(5, 0, 0)] if clear_existing else []
        for index, row in enumerate(payload):
            commands.append((0, 0, {
                'sequence': int(row.get('sequence') or ((index + 1) * 10)),
                'row_type': row.get('row_type') or 'line',
                'description': row.get('description') or '',
                'amount_as_reported': self._to_float(row.get('amount_as_reported')),
                'amount_as_restated': self._to_float(row.get('amount_as_restated')),
                'amount_restatement': self._to_float(row.get('amount_restatement')),
            }))
        return commands

    def _serialize_correction_error_rows_payload(self):
        self.ensure_one()
        ordered_lines = self.correction_error_line_ids.sorted(
            key=lambda line: (
                line.sequence or 0,
                str(line.id or ''),
            )
        )
        payload = []
        for line in ordered_lines:
            payload.append({
                'sequence': int(line.sequence or 0),
                'row_type': (line.row_type or 'line').strip().lower(),
                'description': (line.description or '').strip(),
                'amount_as_reported': self._to_float(line.amount_as_reported),
                'amount_as_restated': self._to_float(line.amount_as_restated),
                'amount_restatement': self._to_float(line.amount_restatement),
            })
        return self._normalize_correction_error_rows_payload(payload)

    def _get_render_correction_error_rows(self):
        self.ensure_one()
        return self._normalize_correction_error_rows_payload(
            self._serialize_correction_error_rows_payload()
        )

    def _serialize_tb_overrides_payload(self):
        self.ensure_one()
        payload = []
        ordered_lines = self.tb_override_line_ids.sorted(
            key=lambda line: (
                line.period_key or '',
                line.account_code or '',
                line.id,
            )
        )
        for line in ordered_lines:
            if not line.is_overridden:
                continue
            payload.append({
                'period_key': line.period_key,
                'account_id': line.account_id.id if line.account_id else False,
                'account_code': self._normalize_account_code(line.account_code),
                'account_name': line.account_name or '',
                'system_initial_balance': self._to_float(line.system_initial_balance),
                'system_debit': self._to_float(line.system_debit),
                'system_credit': self._to_float(line.system_credit),
                'system_balance': self._to_float(line.system_balance),
                'override_initial_balance': self._to_float(line.override_initial_balance),
                'override_debit': self._to_float(line.override_debit),
                'override_credit': self._to_float(line.override_credit),
                'override_balance': self._to_float(line.override_balance),
            })
        return payload

    def _sync_tb_overrides_json(self):
        self.ensure_one()
        payload = self._serialize_tb_overrides_payload()
        serialized = json.dumps(payload)
        if (self.tb_overrides_json or '') != serialized:
            self.tb_overrides_json = serialized
        return serialized

    def _deserialize_tb_overrides_payload(self, serialized_payload=None):
        self.ensure_one()
        raw = serialized_payload if serialized_payload is not None else (self.tb_overrides_json or '')
        if not raw:
            return []
        if isinstance(raw, list):
            entries = raw
        else:
            try:
                entries = json.loads(raw)
            except (TypeError, ValueError):
                return []
        if not isinstance(entries, list):
            return []
        cleaned = []
        for entry in entries:
            if isinstance(entry, dict):
                cleaned.append(entry)
        return cleaned

    @api.model
    def _tb_override_payload_from_amounts(
        self,
        initial_balance,
        debit,
        credit,
        system_initial_balance,
        system_debit,
        system_credit,
        end_balance=None,
        system_end_balance=None,
    ):
        initial_balance = self._to_float(initial_balance)
        debit = self._to_float(debit)
        credit = self._to_float(credit)
        system_initial_balance = self._to_float(system_initial_balance)
        system_debit = self._to_float(system_debit)
        system_credit = self._to_float(system_credit)

        movement_balance = debit - credit
        system_movement_balance = system_debit - system_credit
        if end_balance is None:
            end_balance = initial_balance + movement_balance
        if system_end_balance is None:
            system_end_balance = system_initial_balance + system_movement_balance
        end_balance = self._to_float(end_balance)
        system_end_balance = self._to_float(system_end_balance)

        return {
            'initial_balance': initial_balance,
            'debit': debit,
            'credit': credit,
            'movement_balance': movement_balance,
            'end_balance': end_balance,
            'system_initial_balance': system_initial_balance,
            'system_debit': system_debit,
            'system_credit': system_credit,
            'system_movement_balance': system_movement_balance,
            'system_end_balance': system_end_balance,
            'delta_initial_balance': initial_balance - system_initial_balance,
            'delta_debit': debit - system_debit,
            'delta_credit': credit - system_credit,
            'delta_movement_balance': movement_balance - system_movement_balance,
            'delta_end_balance': end_balance - system_end_balance,
        }

    @api.model
    def _normalize_account_row(self, row, balance_role=None):
        normalized = dict(row or {})
        resolved_role = str(balance_role or normalized.get('balance_role') or '').strip().lower()
        if resolved_role not in ('opening', 'movement', 'closing'):
            resolved_role = (
                'closing'
                if any(key in normalized for key in ('initial_balance', 'end_balance', 'movement_balance'))
                else 'movement'
            )

        initial_balance = self._to_float(normalized.get('initial_balance'))
        debit = self._to_float(normalized.get('debit'))
        credit = self._to_float(normalized.get('credit'))
        movement_balance = self._to_float(
            normalized.get('movement_balance', debit - credit)
        )
        if 'end_balance' in normalized:
            end_balance = self._to_float(normalized.get('end_balance'))
        elif resolved_role == 'closing' and 'balance' in normalized:
            end_balance = self._to_float(normalized.get('balance'))
        else:
            end_balance = initial_balance + movement_balance

        normalized.update({
            'initial_balance': initial_balance,
            'debit': debit,
            'credit': credit,
            'movement_balance': movement_balance,
            'end_balance': end_balance,
            'balance_role': resolved_role,
        })
        if resolved_role == 'opening':
            normalized['balance'] = initial_balance
        elif resolved_role == 'movement':
            normalized['balance'] = movement_balance
        else:
            normalized['balance'] = end_balance
        return normalized

    def _project_account_rows(self, rows, balance_role='closing'):
        self.ensure_one()
        return [
            self._normalize_account_row(row, balance_role=balance_role)
            for row in (rows or [])
        ]

    def _build_tb_override_maps(self):
        self.ensure_one()
        override_maps = {
            'current': {},
            'prior': {},
        }
        serialized_payload = self._deserialize_tb_overrides_payload()
        for entry in serialized_payload:
            period_key = str(entry.get('period_key') or '').strip()
            if period_key not in override_maps:
                continue
            has_initial_keys = any(
                key in entry
                for key in ('override_initial_balance', 'initial_balance', 'system_initial_balance')
            )
            initial_balance_value = self._to_float(
                entry.get('override_initial_balance', entry.get('initial_balance', 0.0))
            )
            debit_value = self._to_float(
                entry.get('override_debit', entry.get('debit', 0.0))
            )
            if 'override_credit' in entry or 'credit' in entry:
                credit_value = self._to_float(
                    entry.get('override_credit', entry.get('credit', 0.0))
                )
            elif 'override_balance' in entry or 'balance' in entry:
                balance_value = self._to_float(
                    entry.get('override_balance', entry.get('balance', 0.0))
                )
                if has_initial_keys:
                    credit_value = initial_balance_value + debit_value - balance_value
                else:
                    credit_value = debit_value - balance_value
            else:
                credit_value = 0.0
            override_end_balance = (
                self._to_float(entry.get('override_balance', entry.get('balance')))
                if has_initial_keys and ('override_balance' in entry or 'balance' in entry)
                else initial_balance_value + debit_value - credit_value
            )
            system_initial_balance = self._to_float(entry.get('system_initial_balance'))
            system_debit = self._to_float(
                entry.get('system_debit', entry.get('debit', debit_value))
            )
            if 'system_credit' in entry:
                system_credit = self._to_float(entry.get('system_credit'))
            elif 'system_balance' in entry:
                system_balance = self._to_float(entry.get('system_balance'))
                if 'system_initial_balance' in entry:
                    system_credit = system_initial_balance + system_debit - system_balance
                else:
                    system_credit = system_debit - system_balance
            else:
                system_credit = self._to_float(
                    entry.get('credit', credit_value)
                )
            system_end_balance = (
                self._to_float(entry.get('system_balance'))
                if 'system_balance' in entry
                else system_initial_balance + system_debit - system_credit
            )
            payload = self._tb_override_payload_from_amounts(
                initial_balance_value,
                debit_value,
                credit_value,
                system_initial_balance,
                system_debit,
                system_credit,
                end_balance=override_end_balance,
                system_end_balance=system_end_balance,
            )
            account_id = entry.get('account_id')
            try:
                account_id = int(account_id) if account_id else False
            except (TypeError, ValueError):
                account_id = False
            for identity_key in self._tb_identity_keys(
                account_id,
                entry.get('account_code'),
            ):
                override_maps[period_key][identity_key] = payload

        for line in self.tb_override_line_ids:
            period_key = line.period_key
            if period_key not in override_maps:
                continue
            if not line.is_overridden:
                continue
            effective_initial_balance = self._to_float(line.override_initial_balance)
            effective_debit = self._to_float(line.override_debit)
            effective_credit = self._to_float(line.override_credit)
            effective_balance = self._to_float(line.override_balance)
            system_initial_balance = self._to_float(line.system_initial_balance)
            system_debit = self._to_float(line.system_debit)
            system_credit = self._to_float(line.system_credit)
            system_balance = self._to_float(line.system_balance)
            payload = self._tb_override_payload_from_amounts(
                effective_initial_balance,
                effective_debit,
                effective_credit,
                system_initial_balance,
                system_debit,
                system_credit,
                end_balance=effective_balance,
                system_end_balance=system_balance,
            )
            for identity_key in self._tb_identity_keys(
                line.account_id.id if line.account_id else False,
                line.account_code,
            ):
                override_maps[period_key][identity_key] = payload
        return override_maps

    def _apply_tb_overrides_from_serialized_payload(self, serialized_payload):
        self.ensure_one()
        payload = self._deserialize_tb_overrides_payload(serialized_payload)
        if not payload:
            return

        lines_by_period = {
            'current': {},
            'prior': {},
        }
        for line in self.tb_override_line_ids:
            period_key = line.period_key
            if period_key not in lines_by_period:
                continue
            for identity_key in self._tb_identity_keys(
                line.account_id.id if line.account_id else False,
                line.account_code,
            ):
                lines_by_period[period_key][identity_key] = line

        for entry in payload:
            period_key = str(entry.get('period_key') or '').strip()
            if period_key not in lines_by_period:
                continue

            account_id = entry.get('account_id')
            try:
                account_id = int(account_id) if account_id else False
            except (TypeError, ValueError):
                account_id = False
            account_code = entry.get('account_code')
            normalized_account_code = self._normalize_account_code(account_code)
            line = None
            for identity_key in self._tb_identity_keys(account_id, normalized_account_code):
                line = lines_by_period[period_key].get(identity_key)
                if line:
                    break

            has_initial_keys = any(
                key in entry
                for key in ('override_initial_balance', 'initial_balance')
            )
            initial_balance_value = self._to_float(
                entry.get(
                    'override_initial_balance',
                    entry.get('initial_balance', line.system_initial_balance if line else 0.0),
                )
            )
            debit_value = self._to_float(
                entry.get('override_debit', entry.get('debit', line.system_debit if line else 0.0))
            )
            if 'override_credit' in entry or 'credit' in entry:
                credit_value = self._to_float(
                    entry.get('override_credit', entry.get('credit', line.system_credit if line else 0.0))
                )
            elif 'override_balance' in entry or 'balance' in entry:
                balance_value = self._to_float(
                    entry.get('override_balance', entry.get('balance', line.system_balance if line else 0.0))
                )
                if has_initial_keys:
                    credit_value = initial_balance_value + debit_value - balance_value
                else:
                    credit_value = debit_value - balance_value
            else:
                credit_value = self._to_float(line.system_credit if line else 0.0)

            system_initial_balance = self._to_float(
                entry.get('system_initial_balance', line.system_initial_balance if line else 0.0)
            )
            system_debit = self._to_float(
                entry.get('system_debit', line.system_debit if line else 0.0)
            )
            if 'system_credit' in entry:
                system_credit = self._to_float(entry.get('system_credit'))
            elif 'system_balance' in entry:
                system_balance_value = self._to_float(entry.get('system_balance'))
                if 'system_initial_balance' in entry:
                    system_credit = system_initial_balance + system_debit - system_balance_value
                else:
                    system_credit = system_debit - system_balance_value
            else:
                system_credit = self._to_float(line.system_credit if line else 0.0)
            system_balance = self._to_float(
                entry.get(
                    'system_balance',
                    line.system_balance if line else (
                        system_initial_balance + system_debit - system_credit
                    ),
                )
            )

            line_vals = {
                'override_initial_balance': initial_balance_value,
                'override_debit': debit_value,
                'override_credit': credit_value,
                'override_balance': initial_balance_value + debit_value - credit_value,
            }

            if not line:
                if not normalized_account_code:
                    continue
                account = self.env['account.account'].browse(account_id).exists() if account_id else False
                create_vals = {
                    'wizard_id': self.id,
                    'period_key': period_key,
                    'account_id': account.id if account else False,
                    'account_code': normalized_account_code,
                    'account_name': entry.get('account_name') or (account.name if account else ''),
                    'system_initial_balance': system_initial_balance,
                    'system_debit': system_debit,
                    'system_credit': system_credit,
                    'system_balance': system_balance,
                    **line_vals,
                }
                line = self.env['audit.report.tb.override.line'].create(create_vals)
                for identity_key in self._tb_identity_keys(
                    line.account_id.id if line.account_id else False,
                    normalized_account_code,
                ):
                    lines_by_period[period_key][identity_key] = line
                continue

            line.write(line_vals)

    @api.model
    def _apply_tb_overrides_to_rows(self, rows, override_map, apply_mode='replace'):
        adjusted_rows = []
        for row in rows:
            adjusted_row = dict(row)
            override_payload = None
            row_id = adjusted_row.get('id')
            row_code = adjusted_row.get('code')
            balance_role = adjusted_row.get('balance_role')
            if row_id:
                override_payload = override_map.get(('id', int(row_id)))
            if not override_payload and row_code:
                override_payload = override_map.get(('code', row_code))
            if override_payload:
                if apply_mode == 'delta':
                    current_movement_balance = self._to_float(
                        adjusted_row.get(
                            'movement_balance',
                            self._to_float(adjusted_row.get('debit'))
                            - self._to_float(adjusted_row.get('credit')),
                        )
                    )
                    adjusted_row['debit'] = (
                        self._to_float(adjusted_row.get('debit'))
                        + self._to_float(override_payload.get('delta_debit'))
                    )
                    adjusted_row['credit'] = (
                        self._to_float(adjusted_row.get('credit'))
                        + self._to_float(override_payload.get('delta_credit'))
                    )
                    if 'initial_balance' in adjusted_row:
                        adjusted_row['initial_balance'] = (
                            self._to_float(adjusted_row.get('initial_balance'))
                            + self._to_float(override_payload.get('delta_initial_balance'))
                        )
                    if 'end_balance' in adjusted_row:
                        adjusted_row['end_balance'] = (
                            self._to_float(adjusted_row.get('end_balance'))
                            + self._to_float(override_payload.get('delta_end_balance'))
                        )
                    else:
                        adjusted_row['end_balance'] = (
                            self._to_float(adjusted_row.get('balance'))
                            + self._to_float(override_payload.get('delta_end_balance'))
                        )
                    adjusted_row['movement_balance'] = (
                        current_movement_balance
                        + self._to_float(override_payload.get('delta_movement_balance'))
                    )
                    balance_role = balance_role or 'closing'
                else:
                    adjusted_row['initial_balance'] = self._to_float(
                        override_payload.get('initial_balance')
                    )
                    adjusted_row['debit'] = self._to_float(override_payload.get('debit'))
                    adjusted_row['credit'] = self._to_float(override_payload.get('credit'))
                    adjusted_row['movement_balance'] = self._to_float(
                        override_payload.get('movement_balance')
                    )
                    adjusted_row['end_balance'] = self._to_float(
                        override_payload.get('end_balance')
                    )
                    balance_role = balance_role or 'movement'
            adjusted_rows.append(
                self._normalize_account_row(
                    adjusted_row,
                    balance_role=balance_role,
                )
            )
        return adjusted_rows

    @api.model
    def _is_display_non_zero(self, value, precision=2):
        return self._round_amount(value, digits=precision) != 0.0

    @api.model
    def _compose_tb_warning(self, label, diff_value):
        if not self._is_display_non_zero(diff_value, precision=2):
            return False
        return (
            f"{label} mismatch: Total assets differ from total equity and liabilities by "
            f"{diff_value:,.2f}."
        )

    @api.model
    def _compose_related_parties_checkbox_warning(self, label, director_salary_amount):
        return (
            f"{label}: Director salary account ({DIRECTOR_SALARY_ACCOUNT_CODE}) has "
            f"{director_salary_amount:,.2f}, but the related parties checkbox is not selected. "
            "Please check the checkbox for transactions with related party."
        )

    def _reopen_wizard_form(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('Audit_Report.audit_report_wizard_action')
        action_context = dict(self.env.context)
        target_revision_id = (
            self.audit_target_revision_id.id
            or action_context.get('audit_target_revision_id')
            or False
        )
        target_document_id = (
            self.audit_target_document_id.id
            or action_context.get('audit_target_document_id')
            or False
        )
        action_context.update({
            'dialog_size': 'extra-large',
            'form_view_initial_mode': 'edit',
            'audit_target_revision_id': target_revision_id,
            'audit_target_document_id': target_document_id,
        })
        action_flags = dict(action.get('flags') or {})
        action_flags['mode'] = 'edit'
        action.update({
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': action_context,
            'flags': action_flags,
        })
        return action

    def _load_tb_override_lines(self, preserve_overrides=False):
        self.ensure_one()
        periods = self._get_reporting_periods()
        date_start = periods['date_start']
        date_end = periods['date_end']
        show_prior_year = periods['show_prior_year']
        prior_label_date_start = periods.get('prior_label_date_start') or periods['prior_date_start']
        prior_date_end = periods['prior_date_end']
        include_zero_accounts = bool(self.tb_include_zero_accounts)

        target_periods = ['current']
        if show_prior_year:
            target_periods.append('prior')

        if not preserve_overrides:
            self.tb_override_line_ids.filtered(
                lambda line: line.period_key in target_periods
            ).unlink()

        existing_lines = self.tb_override_line_ids.filtered(
            lambda line: line.period_key in target_periods
        )
        lines_by_period = {period_key: {} for period_key in target_periods}
        for line in existing_lines:
            for identity_key in self._tb_identity_keys(
                line.account_id.id if line.account_id else False,
                line.account_code,
            ):
                lines_by_period.setdefault(line.period_key, {})
                lines_by_period[line.period_key][identity_key] = line

        period_specs = [
            ('current', date_start, date_end),
        ]
        if show_prior_year:
            period_specs.append(('prior', prior_label_date_start, prior_date_end))

        seen_line_ids = set()
        for period_key, period_start, period_end in period_specs:
            for row in self._get_tb_override_system_rows(
                period_start,
                period_end,
                include_zero_accounts=include_zero_accounts,
            ):
                account_id = row.get('id')
                account_code = row.get('code')
                account_name = row.get('name') or ''
                system_initial_balance = self._to_float(row.get('initial_balance'))
                system_debit = self._to_float(row.get('debit'))
                system_credit = self._to_float(row.get('credit'))
                system_balance = self._to_float(row.get('balance'))
                identity_keys = self._tb_identity_keys(account_id, account_code)
                line = None
                for identity_key in identity_keys:
                    line = lines_by_period.get(period_key, {}).get(identity_key)
                    if line:
                        break

                system_vals = {
                    'account_id': account_id or False,
                    'account_code': account_code,
                    'account_name': account_name,
                    'system_initial_balance': system_initial_balance,
                    'system_debit': system_debit,
                    'system_credit': system_credit,
                    'system_balance': system_balance,
                }

                if line:
                    line.write(system_vals)
                    if not preserve_overrides:
                        line.write({
                            'override_initial_balance': system_initial_balance,
                            'override_debit': system_debit,
                            'override_credit': system_credit,
                            'override_balance': system_balance,
                        })
                    seen_line_ids.add(line.id)
                    continue

                create_vals = {
                    'wizard_id': self.id,
                    'period_key': period_key,
                    **system_vals,
                    'override_initial_balance': system_initial_balance,
                    'override_debit': system_debit,
                    'override_credit': system_credit,
                    'override_balance': system_balance,
                }
                created_line = self.env['audit.report.tb.override.line'].create(create_vals)
                seen_line_ids.add(created_line.id)

        if preserve_overrides:
            stale_lines = self.tb_override_line_ids.filtered(
                lambda line: (
                    line.period_key in target_periods
                    and line.id not in seen_line_ids
                    and not line.is_overridden
                )
            )
            stale_lines.unlink()

        if not show_prior_year:
            self.tb_override_line_ids.filtered(lambda line: line.period_key == 'prior').unlink()

        self._sync_tb_overrides_json()
        try:
            self._get_report_data()
        except Exception as err:
            _logger.debug(
                "Trial balance warning refresh skipped for wizard_id=%s due to: %s",
                self.id,
                err,
            )

    def action_tb_load_lines(self):
        self.ensure_one()
        self._load_tb_override_lines(preserve_overrides=False)
        return self._reopen_wizard_form()

    def action_tb_reload_lines(self):
        self.ensure_one()
        self._load_tb_override_lines(preserve_overrides=True)
        return self._reopen_wizard_form()

    def action_open_odoo_tb_override_current(self):
        self.ensure_one()
        return self._build_tb_override_native_action('current')

    def action_open_odoo_tb_override_prior(self):
        self.ensure_one()
        return self._build_tb_override_native_action('prior')

    def action_tb_shift_current_previous(self):
        self.ensure_one()
        return self._action_tb_shift_period('current', 'previous')

    def action_tb_shift_current_next(self):
        self.ensure_one()
        return self._action_tb_shift_period('current', 'next')

    def action_tb_shift_prior_previous(self):
        self.ensure_one()
        return self._action_tb_shift_period('prior', 'previous')

    def action_tb_shift_prior_next(self):
        self.ensure_one()
        return self._action_tb_shift_period('prior', 'next')

    def _tb_override_period_range(self, period_key):
        self.ensure_one()
        periods = self._get_reporting_periods()
        if period_key == 'prior':
            if not periods.get('show_prior_year'):
                return False, False
            return (
                periods.get('prior_label_date_start') or periods.get('prior_date_start'),
                periods.get('prior_date_end'),
            )
        return (
            periods.get('date_start'),
            periods.get('date_end'),
        )

    def _open_tb_add_account_wizard(self, period_key):
        self.ensure_one()
        if period_key not in ('current', 'prior'):
            raise ValidationError("Invalid period selected for trial balance account override.")
        if period_key == 'prior':
            periods = self._get_reporting_periods()
            if not periods.get('show_prior_year'):
                raise ValidationError("Prior-period account overrides are available only for 2-year reports.")

        add_wizard = self.env['audit.report.tb.add.account.wizard'].create({
            'wizard_id': self.id,
            'period_key': period_key,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Trial Balance Account',
            'res_model': 'audit.report.tb.add.account.wizard',
            'view_mode': 'form',
            'res_id': add_wizard.id,
            'target': 'new',
        }

    def action_tb_add_current_account(self):
        self.ensure_one()
        return self._open_tb_add_account_wizard('current')

    def action_tb_add_prior_account(self):
        self.ensure_one()
        return self._open_tb_add_account_wizard('prior')

    def action_tb_reset_overrides(self):
        self.ensure_one()
        period_key = self.env.context.get('tb_period_key')
        target_lines = self.tb_override_line_ids
        if period_key in ('current', 'prior'):
            target_lines = target_lines.filtered(lambda line: line.period_key == period_key)
        for line in target_lines:
            line.write({
                'override_initial_balance': self._to_float(line.system_initial_balance),
                'override_debit': self._to_float(line.system_debit),
                'override_credit': self._to_float(line.system_credit),
                'override_balance': self._to_float(line.system_balance),
            })
        self._sync_tb_overrides_json()
        try:
            self._get_report_data()
        except Exception as err:
            _logger.debug(
                "Trial balance warning refresh skipped after reset for wizard_id=%s due to: %s",
                self.id,
                err,
            )
        return self._reopen_wizard_form()

    def _get_financial_review_net_display_data(
        self,
        revenue_total,
        net_profit_after_tax,
        net_profit_margin,
        prev_revenue_total=0.0,
        prev_net_profit_after_tax=0.0,
        prev_net_profit_margin=0.0,
        show_prior_year=False,
    ):
        def _uses_amount(revenue, net_amount, margin):
            revenue_zero = self._round_amount(revenue) == 0.0
            loss_margin_at_least_100 = (
                self._to_float(net_amount) < 0.0
                and abs(self._to_float(margin)) >= 100.0
            )
            return revenue_zero or loss_margin_at_least_100

        def _profit_or_loss_text(current, prev=None, use_comparative=False):
            current_is_loss = self._to_float(current) < 0.0
            if not use_comparative:
                return '(loss)' if current_is_loss else 'profit'

            prev_is_loss = self._to_float(prev) < 0.0
            if current_is_loss and prev_is_loss:
                return '(loss)'
            if (not current_is_loss) and (not prev_is_loss):
                return 'profit'
            if (not current_is_loss) and prev_is_loss:
                return 'profit / (loss)'
            return '(loss) / profit'

        current_uses_amount = _uses_amount(
            revenue_total,
            net_profit_after_tax,
            net_profit_margin,
        )
        prior_uses_amount = bool(show_prior_year) and _uses_amount(
            prev_revenue_total,
            prev_net_profit_after_tax,
            prev_net_profit_margin,
        )
        if show_prior_year and (current_uses_amount or prior_uses_amount):
            current_uses_amount = True
            prior_uses_amount = True

        display_mode = 'amount' if current_uses_amount else 'margin'
        label = f"Net {_profit_or_loss_text(net_profit_after_tax, prev_net_profit_after_tax, show_prior_year)}"
        if display_mode == 'margin':
            label = f"{label} margin"

        prior_display_mode = 'amount' if prior_uses_amount else 'margin'
        return {
            'financial_review_net_label': label,
            'financial_review_net_current_display_mode': display_mode,
            'financial_review_net_prior_display_mode': prior_display_mode,
            'financial_review_net_current_is_amount': current_uses_amount,
            'financial_review_net_prior_is_amount': prior_uses_amount,
        }

    def _get_report_data(self):
        """Get report data for the template"""
        self.ensure_one()
        self._validate_comparative_disclosure_options()
        periods = self._get_reporting_periods()
        date_start = periods['date_start']
        date_end = periods['date_end']
        period_category = periods['period_category']
        show_prior_year = periods['show_prior_year']
        prior_date_start = periods['prior_date_start']
        prior_date_end = periods['prior_date_end']
        prior_label_date_start = periods.get('prior_label_date_start') or prior_date_start
        prior_label_date_end = periods.get('prior_label_date_end') or prior_date_end
        prior_prior_date_start = periods['prior_prior_date_start']
        prior_prior_date_end = periods['prior_prior_date_end']
        balance_sheet_date_start = periods['balance_sheet_date_start']
        prior_balance_sheet_date_start = periods['prior_balance_sheet_date_start']
        prior_prior_balance_sheet_date_start = periods['prior_prior_balance_sheet_date_start']
        usd_statement_enabled = bool(self.usd_statement)
        convert_tb_to_usd = bool(self.tb_convert_balances_to_usd) or usd_statement_enabled
        usd_text_mode_enabled = (
            usd_statement_enabled
            or bool(self.tb_convert_balances_to_usd)
            or bool(self.replace_aed_text_with_usd)
        )
        replace_aed_text_with_usd = (
            bool(self.replace_aed_text_with_usd)
            or usd_statement_enabled
            or bool(self.tb_convert_balances_to_usd)
        )
        usd_conversion_rate = self._to_float(self.tb_usd_conversion_rate)
        if convert_tb_to_usd and usd_conversion_rate <= 0.0:
            raise ValidationError(
                "USD conversion rate must be greater than zero when trial balance conversion is enabled."
            )

        def _column_period_word(start_date, end_date):
            if not start_date or not end_date:
                return 'period'
            expected_year_end = start_date + relativedelta(years=1) - relativedelta(days=1)
            return 'year' if expected_year_end == end_date else 'period'

        current_column_period_word = _column_period_word(date_start, date_end)
        prior_column_period_word = _column_period_word(prior_label_date_start, prior_label_date_end)
        if not show_prior_year:
            comparative_period_word = 'period'
        elif current_column_period_word == prior_column_period_word:
            comparative_period_word = current_column_period_word
        else:
            comparative_period_word = f"{current_column_period_word} / {prior_column_period_word}"
        show_unaudited_prior_year = bool(self.show_unaudited_prior_year and show_prior_year)

        fetch_rows_cache = {}
        tb_override_maps = self._build_tb_override_maps()

        current_primary_override_range = (
            date_start or False,
            date_end or False,
        )
        prior_primary_override_range = (
            prior_label_date_start or False,
            prior_date_end or False,
        )

        def _tb_override_target_for_range(period_start, period_end):
            range_key = (period_start or False, period_end or False)
            if range_key == current_primary_override_range:
                return 'current', 'replace'
            if show_prior_year and range_key == prior_primary_override_range:
                return 'prior', 'replace'
            return None, None

        def _fetch_account_rows(period_start, period_end, balance_role='movement'):
            if not period_start or not period_end:
                return []
            cache_key = (period_start or False, period_end or False)
            cached_rows = fetch_rows_cache.get(cache_key)
            if cached_rows is not None:
                return self._project_account_rows(cached_rows, balance_role=balance_role)

            rows = self._fetch_grouped_account_rows_from_odoo_trial_balance(
                period_start,
                period_end,
            )
            if rows is None:
                raise ValidationError("Odoo Trial Balance report is not available in this database.")
            period_key, apply_mode = _tb_override_target_for_range(period_start, period_end)
            if period_key:
                rows = self._apply_tb_overrides_to_rows(
                    rows,
                    tb_override_maps.get(period_key) or {},
                    apply_mode=apply_mode,
                )
            else:
                rows = self._project_account_rows(rows, balance_role='closing')
            if convert_tb_to_usd:
                rows = [
                    self._convert_tb_row_to_usd(row, usd_conversion_rate)
                    for row in rows
                ]
            rows = self._round_account_rows_for_reporting(rows)
            cached_payload = [dict(row) for row in rows]
            fetch_rows_cache[cache_key] = cached_payload
            return self._project_account_rows(cached_payload, balance_role=balance_role)

        def _build_prefix_totals(rows):
            prefix_lengths = (1, 2, 4, 6, 8)
            totals = {length: {} for length in prefix_lengths}
            for row in rows:
                code = row.get('code') or ''
                if not code:
                    continue
                balance = row.get('balance', 0.0)
                code_length = len(code)
                for length in prefix_lengths:
                    if code_length < length:
                        continue
                    key = code[:length]
                    bucket = totals[length]
                    bucket[key] = bucket.get(key, 0.0) + balance
            return totals

        def _sum_exact_account_totals(prefix_totals, account_codes):
            account_totals = prefix_totals.get(8, {})
            return sum(account_totals.get(code, 0.0) for code in account_codes)

        def _sum_prefixed_account_totals(prefix_totals, prefix):
            account_totals = prefix_totals.get(len(prefix), {})
            return sum(
                value
                for code, value in account_totals.items()
                if code.startswith(prefix)
            )

        def _corporate_tax_liability_total(prefix_totals):
            return _sum_exact_account_totals(prefix_totals, CT_LIABILITY_ACCOUNT_CODES)


        def _build_section_totals(group_totals, mapping):
            totals = {}
            for label, codes in mapping.items():
                total = 0.0
                for code in codes:
                    total += group_totals.get(code, 0.0)
                totals[label] = total
            return totals

        def _build_group_label_map(mappings):
            labels = {}
            for mapping in mappings:
                for label, codes in mapping.items():
                    for code in codes:
                        labels[code] = label
            return labels

        def _annotate_rows(rows, group_labels):
            annotated = []
            for row in rows:
                code = row.get('code', '')
                group_code = code[:4] if len(code) >= 4 else ''
                data = dict(row)
                data['group_code'] = group_code
                data['sub_group_code'] = code[:6] if len(code) >= 6 else ''
                data['two_digit_code'] = code[:2] if len(code) >= 2 else ''
                data['one_digit_code'] = code[:1] if len(code) >= 1 else ''
                data['section'] = group_labels.get(group_code, 'Other')
                annotated.append(data)
            return annotated

        def _build_subhead_groups(prefix_totals, subhead_labels):
            grouped = {}
            for code in sorted(prefix_totals):
                name = subhead_labels.get(code)
                if not name:
                    continue
                group_code = code[:4]
                grouped.setdefault(group_code, []).append({
                    'code': code,
                    'name': name,
                    'balance': prefix_totals[code],
                })
            return grouped

        def _build_account_head_map(rows):
            accounts = {}
            for row in rows:
                code = row.get('code') or ''
                if len(code) < 8:
                    continue
                group_code = code[:4]
                accounts.setdefault(group_code, {})
                accounts[group_code][code] = {
                    'code': code,
                    'name': row.get('name') or '',
                    'balance': row.get('balance', 0.0),
                }
            return accounts

        def _account_head_balance(account_heads, account_code):
            group_code = account_code[:4]
            return account_heads.get(group_code, {}).get(account_code, {}).get('balance', 0.0)

        def _equity_head_balance(account_heads, account_code):
            # Equity accounts are credit-balanced in Odoo (negative); invert for display.
            return -_account_head_balance(account_heads, account_code)

        owner_current_account_code = '12040101'
        owner_current_account_group_code = owner_current_account_code[:4]
        equity_group_code = '3101'

        def _owner_account_balance(account_heads):
            return (
                account_heads.get(owner_current_account_group_code, {})
                .get(owner_current_account_code, {})
                .get('balance', 0.0)
            )

        def _reclassify_owner_account_group_total(group_totals, account_heads):
            adjusted = dict(group_totals)
            owner_balance = _owner_account_balance(account_heads)
            if not owner_balance:
                return adjusted
            adjusted[owner_current_account_group_code] = (
                adjusted.get(owner_current_account_group_code, 0.0) - owner_balance
            )
            adjusted[equity_group_code] = adjusted.get(equity_group_code, 0.0) + owner_balance
            return adjusted

        def _collect_note_lines(group_codes, current_map, prev_map):
            return self._collect_note_lines(
                group_codes,
                current_map,
                prev_map,
                owner_current_account_code=owner_current_account_code,
                equity_group_code=equity_group_code,
            )

        def _label_group_totals(group_totals, labels):
            totals = {}
            for code, label in labels.items():
                totals[label] = totals.get(label, 0.0) + group_totals.get(code, 0.0)
            return totals

        NON_CURRENT_ASSET_GROUPS = {
            'Property and equipment': ['1101'],
            'Right of use of assets': ['1102'],
            'Capital work in progress': ['1103'],
            'Long term investment': ['1104', '1108'],
            'Long term deposits': ['1105'],
            'Long term loans receivable': ['1106'],
            'Deferred tax': ['1109'],
            'Investing activities': ['1110'],
            'Non current assets': ['1111'],
        }
        CURRENT_ASSET_GROUPS = {
            'Inventory': ['1201'],
            'Stocks': ['1207'],
            'Accounts receivable': ['1202'],
            'Prepayment, deposits, advances and other receivables': ['1203', '1205'],
            'Cash and bank balances': ['1204'],
            'Interbank transfer': ['1206'],
        }
        NON_CURRENT_LIABILITY_GROUPS = {
            'Long term loan': ['2101'],
            'Loan from related party': ['2102'],
            'Deferred tax': ['2103'],
            'Employee benefits': ['2104'],
            'Financing activities': ['2105'],
            'Non current liabilities': ['2106'],
            'Deposit': ['2107'],
        }
        CURRENT_LIABILITY_GROUPS = {
            'Short term borrowings': ['2201'],
            'Trade payables': ['2202'],
            'Other payables': ['2203'],
            'Corporate tax liability': ['2204'],
        }
        EQUITY_GROUPS = {
            'Equity': ['3101'],
        }
        REVENUE_GROUPS = {
            'Revenue': ['4101', '4102'],
        }
        OTHER_INCOME_GROUPS = {
            'Other income': ['4103'],
        }
        COST_OF_REVENUE_GROUPS = {
            'Cost of revenue': ['5101'],
        }
        DEPRECIATION_GROUPS = {
            'Depreciation': ['5114'],
        }
        DEPRECIATION_EXPENSE_PREFIXES = ('511401',)
        AMORTIZATION_EXPENSE_PREFIXES = ('511402',)
        INVESTMENT_GAIN_LOSS_GROUPS = {
            'Gain / (loss) on investment': ['5201'],
        }

        def _prepare_direct_cost_note_data(current_map, prev_map):
            lines = _collect_note_lines(
                COST_OF_REVENUE_GROUPS['Cost of revenue'],
                current_map,
                prev_map,
            )
            lines = self._normalize_cost_of_revenue_note_lines(lines)
            return self._prepare_direct_cost_note(lines)

        MAIN_HEAD_LABELS = {
            '1101': 'Property, Plant And Equipment',
            '1102': 'Right of Use of Assets',
            '1103': 'Capital Work in Progress',
            '1104': 'Long Term Investment',
            '1105': 'Long Term Deposits',
            '1106': 'Long Term Loans Receivable',
            '1107': 'Intangible Assets',
            '1108': 'Long Term Investment',
            '1109': 'Deferred Tax',
            '1110': 'Investing Activities',
            '1111': 'Non Current Assets',
            '1201': 'Inventory',
            '1207': 'Stocks',
            '1202': 'Accounts Receivable',
            '1203': 'Prepayment, Deposits, Advances & Other Receivables',
            '1204': 'Cash And Bank Balances',
            '1205': 'Stripe & Other Wallets',
            '1206': 'Interbank Transfer',
            '2101': 'Long term loan',
            '2102': 'Loan from related party',
            '2103': 'Deferred Tax',
            '2104': 'Employee Benefits',
            '2105': 'Financing Activities',
            '2106': 'Non Current Liabilities',
            '2107': 'Deposit',
            '2201': 'Short Term Borrowings',
            '2202': 'Trade Payables',
            '2203': 'Other Payables',
            '2204': 'Corporate Tax Liability',
            '3101': 'Equity',
            '4101': 'Revenue',
            '4102': 'Revenue - Related Party',
            '4103': 'Other Income',
            '5101': 'Direct Cost',
            '5102': 'Marketing & Advertisement Expenses',
            '5103': 'IT Expenses',
            '5104': 'Telephone & Internet',
            '5105': 'Professional Fee & Consultancy',
            '5106': 'Legal & Government Fee',
            '5107': "Director's Salary",
            '5108': 'Salaries & Wages',
            '5109': 'Audit & Accounting Expense',
            '5110': 'Rent Expense',
            '5111': 'Utilities',
            '5112': 'Printing & Stationary Expense',
            '5113': 'Travel & Accommodation Expense',
            '5114': 'Depreciation & Amortization',
            '5115': 'Courier Expenses',
            '5116': 'Commission Expense',
            '5117': 'Cleaning Expense',
            '5118': 'Repair & Maintenance',
            '5119': 'Other expenses',
            '5120': 'Penalties & Fines',
            '5121': 'Donation & Charity',
            '5122': 'Other expenses',
            '5123': 'Bank Charges',
            '5124': 'Finance Cost',
            '5125': 'Insurance Expense',
            '5126': 'Fees & Subscriptions',
            '5127': 'Tax expense',
            '5128': 'Office Expense',
        }

        SUBHEAD_LABELS = {
            '110101': 'Land & Buildings',
            '110102': 'Furnitures & Fixtures',
            '110103': 'Leasehold Improvements',
            '110104': 'Vehicles',
            '110105': 'IT Equipments',
            '110106': 'Office Equipments',
            '110201': 'ROU Property',
            '110202': 'ROU Vehicles',
            '110203': 'ROU Equipment',
            '110204': 'ROU Property',
            '110205': 'ROU Vehicles',
            '110206': 'ROU Equipment',
            '110301': 'Capital Work in Progress',
            '110401': 'Investments in funds',
            '110501': 'Long Term Deposits',
            '110601': 'Related Parties',
            '110701': 'Software & Licences',
            '110702': 'Website & Blogs',
            '110703': 'Other Intangible Assets',
            '110801': 'Group Investments',
            '110901': 'Deferred Tax',
            '111001': 'Investing Activities',
            '111101': 'Non Current Assets',
            '120101': 'Inventory',
            '120201': 'Trade Receivables',
            '120202': 'Retention Receivables',
            '120301': 'Advances',
            '120302': 'Prepaid Expenses',
            '120303': 'Other Receivables',
            '120304': 'VAT Receivable',
            '120401': 'Cash',
            '120402': 'Bank Accounts',
            '120403': 'Monies in Transit',
            '120501': 'Payment Gateways',
            '120502': 'Other Wallet',
            '120601': 'Interbank Transfer',
            '210101': 'Bank Loans',
            '210102': 'Related Party Loan',
            '210103': 'Lease Liabilities',
            '210201': 'Loan from related party',
            '210301': 'Deferred Tax',
            '210401': 'End of Service Benefits',
            '210501': 'Financing Activities',
            '210601': 'Non Current Liabilities',
            '210701': 'Deposit',
            '220101': 'Bank Overdraft',
            '220102': 'Short term loan',
            '220103': 'Credit Card Payable',
            '220104': 'Lease Liability',
            '220201': 'Trade Payables',
            '220301': 'Other Payables',
            '220302': 'VAT Payable',
            '220303': 'Accrued Expenses',
            '220401': 'Corporate Tax Liability',
            '310101': 'Share Capital',
            '310102': 'Retained Earnings',
            '310103': 'Reserves',
            '310104': 'Fund Balances',
            '410101': 'Revenue',
            '410201': 'Revenue - Related Party',
            '410301': 'Interest income',
            '410302': 'Dividend income',
            '410303': 'Rental Income',
            '410304': 'Miscellaneous Income',
            '410305': 'Foreign Exchange Gain',
            '410306': 'Fair Value Gains',
            '410307': 'Endowment Income',
            '410308': 'Donations',
            '410309': 'Grants',
            '410310': 'Write Back',
            '510101': 'Cost of Sales',
            '510102': 'Cost of Goods',
            '510103': 'Cost of Sales',
            '510104': 'Event Fee',
            '510201': 'Marketing & Advertisement Expenses',
            '510301': 'IT & Software Expenses',
            '510401': 'Telephone & Internet',
            '510501': 'Professional Fee & Consultancy',
            '510601': 'Legal & Government Fee',
            '510701': "Director's Salary",
            '510801': 'Office Staff Salaries',
            '510802': 'Coaching Staff Salaries',
            '510803': 'Employee Benefits & Allowances',
            '510804': 'Bonus & Incentives',
            '510805': 'Staff Welfare',
            '510901': 'Audit Fee',
            '510902': 'Accounting & Bookkeeping Fee',
            '511001': 'Office Rent',
            '511002': 'Miscellaneous Rent',
            '511101': 'Office Utilities',
            '511201': 'Printing Cost',
            '511202': 'Stationary',
            '511301': 'Travel & Accommodation Expense',
            '511302': 'Local Accommodation Expense',
            '511401': 'Depreciation Expense',
            '511402': 'Amortization Expense',
            '511501': 'Courier Expenses',
            '511601': 'Commission Expense',
            '511701': 'Cleaning Expense',
            '511801': 'Repair & Maintenance',
            '511901': 'Other Expenses',
            '512001': 'Penalties & Fines',
            '512101': 'Donation & Charity',
            '512201': 'Other Expenses',
            '512202': 'Charitable Activities',
            '512301': 'Bank Charges & Fees',
            '512401': 'Interest Expense',
            '512501': 'Business Insurance',
            '512601': 'Trade License',
            '512602': 'Establishment Card',
            '512603': 'Visa Fee',
            '512701': 'Corporate Tax Expense',
            '512801': 'Office Expense',
        }

        group_labels = _build_group_label_map([
            NON_CURRENT_ASSET_GROUPS,
            CURRENT_ASSET_GROUPS,
            NON_CURRENT_LIABILITY_GROUPS,
            CURRENT_LIABILITY_GROUPS,
            EQUITY_GROUPS,
            REVENUE_GROUPS,
            OTHER_INCOME_GROUPS,
            COST_OF_REVENUE_GROUPS,
            DEPRECIATION_GROUPS,
        ])

        # Current year balances (as of date_end)
        current_rows = _fetch_account_rows(date_start, date_end, balance_role='closing')
        current_account_heads = _build_account_head_map(current_rows)
        current_prefix_totals = _build_prefix_totals(current_rows)
        current_group_totals = dict(
            _reclassify_owner_account_group_total(current_prefix_totals[4], current_account_heads)
        )
        current_group_totals['2204'] = _corporate_tax_liability_total(current_prefix_totals)
        current_group_totals['1105'] = _sum_prefixed_account_totals(
            current_prefix_totals,
            LONG_TERM_DEPOSITS_PREFIX,
        )
        current_main_heads = _label_group_totals(current_group_totals, MAIN_HEAD_LABELS)
        current_subheads_by_group = _build_subhead_groups(
            current_prefix_totals[6],
            SUBHEAD_LABELS,
        )
        current_ppe_subheads = {
            row['name']: row['balance']
            for row in current_subheads_by_group.get('1101', [])
        }
        current_ppe_total = sum(current_ppe_subheads.values())

        annotated_rows = _annotate_rows(current_rows, group_labels)
        balance_rows = [row for row in annotated_rows if row['one_digit_code'] in ('1', '2', '3')]
        period_rows = _fetch_account_rows(date_start, date_end, balance_role='movement')
        period_account_heads = _build_account_head_map(period_rows)
        period_prefix_totals = _build_prefix_totals(period_rows)
        period_group_totals = period_prefix_totals[4]
        period_annotated_rows = _annotate_rows(period_rows, group_labels)
        profit_loss_accounts = [
            row for row in period_annotated_rows
            if row['one_digit_code'] in ('4', '5')
        ]



        current_assets = _build_section_totals(current_group_totals, CURRENT_ASSET_GROUPS)
        non_current_assets = _build_section_totals(current_group_totals, NON_CURRENT_ASSET_GROUPS)
        current_liabilities = _build_section_totals(current_group_totals, CURRENT_LIABILITY_GROUPS)
        non_current_liabilities = _build_section_totals(current_group_totals, NON_CURRENT_LIABILITY_GROUPS)
        equity = _build_section_totals(current_group_totals, EQUITY_GROUPS)

        current_assets_total = sum(current_assets.values())
        non_current_assets_total = sum(non_current_assets.values())
        total_assets = current_assets_total + non_current_assets_total


        current_liabilities_total = sum(current_liabilities.values())
        non_current_liabilities_total = sum(non_current_liabilities.values())
        total_liabilities = -(current_liabilities_total + non_current_liabilities_total)

        total_equity = sum(equity.values())
        total_of_equity_and_liabilities = total_equity + total_liabilities

        # PnL (current year)
        revenue_total = sum(
            period_group_totals.get(code, 0.0)
            for code in REVENUE_GROUPS['Revenue']
        )
        revenue_total = -(revenue_total)
        other_income_total = sum(
            period_group_totals.get(code, 0.0)
            for code in OTHER_INCOME_GROUPS['Other income']
        )
        other_income_total = -(other_income_total)
        raw_cost_of_revenue_total = sum(
            period_group_totals.get(code, 0.0)
            for code in COST_OF_REVENUE_GROUPS['Cost of revenue']
        )
        cost_of_revenue_total = _prepare_direct_cost_note_data(
            period_account_heads,
            {},
        )['total_current']
        depreciation_total = sum(
            period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        investment_gain_loss_total = sum(
            period_group_totals.get(code, 0.0)
            for code in INVESTMENT_GAIN_LOSS_GROUPS['Gain / (loss) on investment']
        )
        expense_total = period_prefix_totals[2].get('51', 0.0)
        tax_expense_ledger = _sum_exact_account_totals(period_prefix_totals, CT_EXPENSE_ACCOUNT_CODES)
        operating_expenses_total = (
            expense_total - raw_cost_of_revenue_total - tax_expense_ledger
        )

        gross_profit = revenue_total - cost_of_revenue_total
        net_profit_before_tax = (
            gross_profit
            - operating_expenses_total
            - investment_gain_loss_total
            + other_income_total
        )
        tax_amount = tax_expense_ledger
        net_profit_after_tax = net_profit_before_tax - tax_amount

        def _calc_margin(amount, base):
            if not base:
                return 0.0
            return (amount / base) * 100.0

        def _profit_or_loss_text(current, prev=None, use_comparative=False):
            current_is_loss = (current or 0.0) < 0
            if not use_comparative:
                return '(loss)' if current_is_loss else 'profit'

            prev_is_loss = (prev or 0.0) < 0
            if current_is_loss and prev_is_loss:
                return '(loss)'
            if (not current_is_loss) and (not prev_is_loss):
                return 'profit'
            if (not current_is_loss) and prev_is_loss:
                return 'profit / (loss)'
            return '(loss) / profit'

        def _net_label(current, prev, period_word, suffix=None, use_comparative=False):
            label_base = f"Net {_profit_or_loss_text(current, prev, use_comparative)}"
            label = f"{label_base} for the {period_word}"
            if suffix:
                label = f"{label} {suffix}"
            return label

        gross_profit_margin = _calc_margin(gross_profit, revenue_total)
        net_profit_margin = _calc_margin(net_profit_after_tax, revenue_total)

        # Prior year balances (as of prior_date_end)
        prev_rows = _fetch_account_rows(prior_date_start, prior_date_end, balance_role='closing')
        prev_account_heads = _build_account_head_map(prev_rows)
        prev_prefix_totals = _build_prefix_totals(prev_rows)
        prev_group_totals = dict(
            _reclassify_owner_account_group_total(prev_prefix_totals[4], prev_account_heads)
        )
        prev_group_totals['2204'] = _corporate_tax_liability_total(prev_prefix_totals)
        prev_group_totals['1105'] = _sum_prefixed_account_totals(
            prev_prefix_totals,
            LONG_TERM_DEPOSITS_PREFIX,
        )

        def _sum_prefix_group(prefix_totals, prefixes):
            return sum(prefix_totals.get(code, 0.0) for code in prefixes)

        def _sum_other_receivables(prefix_totals):
            return sum(
                value
                for code, value in prefix_totals.items()
                if code.startswith('1203') and code not in ('120301', '120302')
            )

        def _sum_wallet_receivables(prefix_totals):
            return sum(
                value
                for code, value in prefix_totals.items()
                if code.startswith('1205')
            )

        def _has_amount(*values):
            return any(abs(value) > 0.0 for value in values)

        advances_current = _sum_prefix_group(current_prefix_totals[6], ['120301'])
        advances_prev = _sum_prefix_group(prev_prefix_totals[6], ['120301'])
        prepaid_current = _sum_prefix_group(current_prefix_totals[6], ['120302'])
        prepaid_prev = _sum_prefix_group(prev_prefix_totals[6], ['120302'])
        other_receivables_current = _sum_other_receivables(current_prefix_totals[6])
        other_receivables_prev = _sum_other_receivables(prev_prefix_totals[6])
        wallet_receivables_current = _sum_wallet_receivables(current_prefix_totals[6])
        wallet_receivables_prev = _sum_wallet_receivables(prev_prefix_totals[6])
        # Keep VAT balances available for note-specific exclusions.
        # Financial assets/liabilities note should exclude VAT receivable/payable
        # (including VAT input/output subaccounts under these prefixes).
        fa_note_vat_receivable_current = _sum_prefix_group(current_prefix_totals[6], ['120304'])
        fa_note_vat_receivable_prev = _sum_prefix_group(prev_prefix_totals[6], ['120304'])
        fa_note_vat_payable_current = _sum_prefix_group(current_prefix_totals[6], ['220302'])
        fa_note_vat_payable_prev = _sum_prefix_group(prev_prefix_totals[6], ['220302'])

        receivable_parts = []
        if _has_amount(prepaid_current, prepaid_prev):
            receivable_parts.append('Prepayment')
        if _has_amount(advances_current, advances_prev):
            receivable_parts.append('Advances')
        if _has_amount(
            other_receivables_current,
            other_receivables_prev,
            wallet_receivables_current,
            wallet_receivables_prev,
        ):
            receivable_parts.append('Other receivables')

        receivable_label = None
        if receivable_parts:
            if len(receivable_parts) == 1:
                receivable_label = receivable_parts[0]
            elif len(receivable_parts) == 2:
                receivable_label = f"{receivable_parts[0]} and {receivable_parts[1]}"
            else:
                receivable_label = f"{receivable_parts[0]}, {receivable_parts[1]} and {receivable_parts[2]}"
            MAIN_HEAD_LABELS['1203'] = receivable_label

        prev_prev_rows = _fetch_account_rows(
            prior_prior_date_start,
            prior_prior_date_end,
            balance_role='closing',
        )
        prev_prev_account_heads = _build_account_head_map(prev_prev_rows)
        prev_prev_prefix_totals = _build_prefix_totals(prev_prev_rows)
        prev_prev_group_totals = _reclassify_owner_account_group_total(
            prev_prev_prefix_totals[4],
            prev_prev_account_heads,
        )
        prev_period_rows = _fetch_account_rows(prior_date_start, prior_date_end, balance_role='movement')
        prev_period_account_heads = _build_account_head_map(prev_period_rows)
        prev_period_prefix_totals = _build_prefix_totals(prev_period_rows)
        prev_period_group_totals = prev_period_prefix_totals[4]
        prev_prev_period_rows = _fetch_account_rows(
            prior_prior_date_start,
            prior_prior_date_end,
            balance_role='movement',
        )
        prev_prev_period_account_heads = _build_account_head_map(prev_prev_period_rows)
        prev_prev_period_prefix_totals = _build_prefix_totals(prev_prev_period_rows)
        prev_prev_period_group_totals = prev_prev_period_prefix_totals[4]
        prev_main_heads = _label_group_totals(prev_group_totals, MAIN_HEAD_LABELS)
        prev_subheads_by_group = _build_subhead_groups(
            prev_prefix_totals[6],
            SUBHEAD_LABELS,
        )
        prev_ppe_subheads = {
            row['name']: row['balance']
            for row in prev_subheads_by_group.get('1101', [])
        }
        prev_ppe_total = sum(prev_ppe_subheads.values())

        prev_current_assets = _build_section_totals(prev_group_totals, CURRENT_ASSET_GROUPS)
        prev_non_current_assets = _build_section_totals(prev_group_totals, NON_CURRENT_ASSET_GROUPS)
        prev_current_liabilities = _build_section_totals(prev_group_totals, CURRENT_LIABILITY_GROUPS)
        prev_non_current_liabilities = _build_section_totals(prev_group_totals, NON_CURRENT_LIABILITY_GROUPS)
        prev_equity = _build_section_totals(prev_group_totals, EQUITY_GROUPS)
        prev_prev_current_assets = _build_section_totals(prev_prev_group_totals, CURRENT_ASSET_GROUPS)

        prev_current_assets_total = sum(prev_current_assets.values())
        prev_non_current_assets_total = sum(prev_non_current_assets.values())
        prev_total_assets = prev_current_assets_total + prev_non_current_assets_total

        prev_current_liabilities_total = sum(prev_current_liabilities.values())
        prev_non_current_liabilities_total = sum(prev_non_current_liabilities.values())
        prev_total_liabilities = -(prev_current_liabilities_total + prev_non_current_liabilities_total)

        prev_equity_total = sum(prev_equity.values())
        prev_total_equity = prev_equity_total
        prev_total_of_equity_and_liabilities = prev_total_equity + prev_total_liabilities

        prev_revenue_total = sum(
            prev_period_group_totals.get(code, 0.0)
            for code in REVENUE_GROUPS['Revenue']
        )
        prev_revenue_total = -(prev_revenue_total)
        prev_other_income_total = sum(
            prev_period_group_totals.get(code, 0.0)
            for code in OTHER_INCOME_GROUPS['Other income']
        )
        prev_other_income_total = -(prev_other_income_total)
        raw_prev_cost_of_revenue_total = sum(
            prev_period_group_totals.get(code, 0.0)
            for code in COST_OF_REVENUE_GROUPS['Cost of revenue']
        )
        prev_cost_of_revenue_total = _prepare_direct_cost_note_data(
            prev_period_account_heads,
            {},
        )['total_current']
        prev_depreciation_total = sum(
            prev_period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        prev_investment_gain_loss_total = sum(
            prev_period_group_totals.get(code, 0.0)
            for code in INVESTMENT_GAIN_LOSS_GROUPS['Gain / (loss) on investment']
        )
        prev_expense_total = prev_period_prefix_totals[2].get('51', 0.0)
        prev_tax_expense_ledger = _sum_exact_account_totals(
            prev_period_prefix_totals,
            CT_EXPENSE_ACCOUNT_CODES,
        )
        prev_operating_expenses_total = (
            prev_expense_total - raw_prev_cost_of_revenue_total - prev_tax_expense_ledger
        )

        prev_gross_profit = prev_revenue_total - prev_cost_of_revenue_total
        prev_net_profit_before_tax = (
            prev_gross_profit
            - prev_operating_expenses_total
            - prev_investment_gain_loss_total
            + prev_other_income_total
        )
        prev_tax_amount = prev_tax_expense_ledger
        prev_net_profit_after_tax = prev_net_profit_before_tax - prev_tax_amount

        prev_gross_profit_margin = _calc_margin(prev_gross_profit, prev_revenue_total)
        prev_net_profit_margin = _calc_margin(prev_net_profit_after_tax, prev_revenue_total)
        financial_review_net_display_data = self._get_financial_review_net_display_data(
            revenue_total,
            net_profit_after_tax,
            net_profit_margin,
            prev_revenue_total,
            prev_net_profit_after_tax,
            prev_net_profit_margin,
            show_prior_year,
        )

        label_prev_net_profit_before_tax = prev_net_profit_before_tax if show_prior_year else 0.0
        label_prev_net_profit_after_tax = prev_net_profit_after_tax if show_prior_year else 0.0
        period_word = comparative_period_word
        show_after_tax_line = bool(
            (tax_amount or (show_prior_year and prev_tax_amount))
            and (net_profit_after_tax or (show_prior_year and prev_net_profit_after_tax))
        )
        before_tax_suffix = "before tax" if show_after_tax_line else None
        net_profit_before_tax_label = _net_label(
            net_profit_before_tax,
            label_prev_net_profit_before_tax,
            period_word,
            before_tax_suffix,
            show_prior_year,
        )
        net_profit_after_tax_label = _net_label(
            net_profit_after_tax,
            label_prev_net_profit_after_tax,
            period_word,
            "after tax",
            show_prior_year,
        )
        oci_uses_after_tax_line = bool(tax_amount or (show_prior_year and prev_tax_amount))
        oci_profit_line_label = (
            net_profit_after_tax_label if oci_uses_after_tax_line else net_profit_before_tax_label
        )
        oci_profit_line_current = (
            net_profit_after_tax if oci_uses_after_tax_line else net_profit_before_tax
        )
        oci_profit_line_prior = (
            prev_net_profit_after_tax if oci_uses_after_tax_line else prev_net_profit_before_tax
        )
        oci_other_comprehensive_income_current = 0.0
        oci_other_comprehensive_income_prior = 0.0
        oci_total_comprehensive_current = (
            oci_profit_line_current + oci_other_comprehensive_income_current
        )
        oci_total_comprehensive_prior = (
            oci_profit_line_prior + oci_other_comprehensive_income_prior
        )
        oci_total_comprehensive_label = (
            f"Total comprehensive "
            f"{_profit_or_loss_text(oci_total_comprehensive_current, oci_total_comprehensive_prior, show_prior_year)} "
            f"for the {period_word}"
        )
        gross_profit_margin_label = (
            f"Gross {_profit_or_loss_text(gross_profit_margin, prev_gross_profit_margin, show_prior_year)} margin"
        )

        prev_prev_revenue_total = sum(
            prev_prev_period_group_totals.get(code, 0.0)
            for code in REVENUE_GROUPS['Revenue']
        )
        prev_prev_revenue_total = -(prev_prev_revenue_total)
        prev_prev_other_income_total = sum(
            prev_prev_period_group_totals.get(code, 0.0)
            for code in OTHER_INCOME_GROUPS['Other income']
        )
        prev_prev_other_income_total = -(prev_prev_other_income_total)
        raw_prev_prev_cost_of_revenue_total = sum(
            prev_prev_period_group_totals.get(code, 0.0)
            for code in COST_OF_REVENUE_GROUPS['Cost of revenue']
        )
        prev_prev_cost_of_revenue_total = _prepare_direct_cost_note_data(
            prev_prev_period_account_heads,
            {},
        )['total_current']
        prev_prev_depreciation_total = sum(
            prev_prev_period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        prev_prev_investment_gain_loss_total = sum(
            prev_prev_period_group_totals.get(code, 0.0)
            for code in INVESTMENT_GAIN_LOSS_GROUPS['Gain / (loss) on investment']
        )
        prev_prev_expense_total = prev_prev_period_prefix_totals[2].get('51', 0.0)
        prev_prev_tax_expense_ledger = _sum_exact_account_totals(
            prev_prev_period_prefix_totals,
            CT_EXPENSE_ACCOUNT_CODES,
        )
        prev_prev_operating_expenses_total = (
            prev_prev_expense_total
            - raw_prev_prev_cost_of_revenue_total
            - prev_prev_tax_expense_ledger
        )
        prev_prev_gross_profit = prev_prev_revenue_total - prev_prev_cost_of_revenue_total
        prev_prev_net_profit_before_tax = (
            prev_prev_gross_profit
            - prev_prev_operating_expenses_total
            - prev_prev_investment_gain_loss_total
            + prev_prev_other_income_total
        )
        prev_prev_tax_amount = prev_prev_tax_expense_ledger
        prev_prev_net_profit_after_tax = prev_prev_net_profit_before_tax - prev_prev_tax_amount

        note_number = 5
        note_numbers = {}
        note_sections = []
        show_shareholder_note = bool(self.show_shareholder_note)
        note_labels = dict(MAIN_HEAD_LABELS)
        note_labels['1201'] = 'Investments'
        def _format_long_date(date_value):
            return date_value.strftime('%d %B %Y') if date_value else ''

        correction_error_note_paragraphs = self._split_note_paragraphs(self.correction_error_note_body)
        correction_error_note_rows = (
            self._get_render_correction_error_rows()
            if self.emphasis_correction_error else []
        )
        correction_error_header_date = periods.get('prior_label_date_end') or date_end
        if receivable_label:
            note_labels['1203'] = receivable_label

        note_prev_account_heads = prev_account_heads if show_prior_year else {}
        note_prev_group_totals = prev_group_totals if show_prior_year else {}
        note_prev_period_account_heads = prev_period_account_heads if show_prior_year else {}
        note_prev_period_group_totals = prev_period_group_totals if show_prior_year else {}
        note_prev_period_prefix_totals = (
            prev_period_prefix_totals if show_prior_year else _build_prefix_totals([])
        )

        if self.emphasis_correction_error and (
            correction_error_note_paragraphs or correction_error_note_rows
        ):
            note_numbers['correction_error'] = note_number
            note_sections.append({
                'key': 'correction_error',
                'number': note_number,
                'label': 'Correction of Error',
                'paragraphs': correction_error_note_paragraphs,
                'correction_rows': correction_error_note_rows,
                'correction_header_date_display': _format_long_date(correction_error_header_date),
            })
            note_number += 1

        def _add_note(
            key,
            label,
            group_codes,
            current_total,
            prev_total,
            current_map=None,
            prev_map=None,
            paragraphs=None,
        ):
            nonlocal note_number
            lines = _collect_note_lines(
                group_codes,
                current_map or current_account_heads,
                prev_map or note_prev_account_heads,
            )
            if not lines:
                return
            if key == 'pl_revenue':
                # Revenue note should be presented as a single summarized line.
                lines = [{
                    'code': 'pl_revenue_total',
                    'name': 'Revenue',
                    'current': current_total,
                    'prev': prev_total,
                }]
            if key == 'pl_opex':
                lines = self._normalize_operating_expense_note_lines(lines)
            line_segments = False
            force_single_segment = False
            if key == 'pl_cost':
                direct_cost_note = self._prepare_direct_cost_note(
                    self._normalize_cost_of_revenue_note_lines(lines)
                )
                lines = direct_cost_note['lines']
                current_total = direct_cost_note['total_current']
                prev_total = direct_cost_note['total_prev']
                force_single_segment = bool(direct_cost_note.get('force_single_segment'))
                if force_single_segment:
                    line_segments = [{
                        'show_title': True,
                        'show_total': True,
                        'lines': lines,
                    }]
            preserve_sign = False
            if key == 'pl_investment_gain_loss':
                lines = self._invert_note_lines(lines)
                current_total = -(current_total or 0.0)
                prev_total = -(prev_total or 0.0)
                preserve_sign = True
            if not force_single_segment:
                line_segments = self._build_generic_note_render_segments(lines)
            note_numbers[key] = note_number
            note_sections.append({
                'key': key,
                'number': note_number,
                'label': label,
                'lines': lines,
                'line_segments': line_segments,
                'total_current': current_total,
                'total_prev': prev_total,
                'preserve_sign': preserve_sign,
                'is_investment_note': key in ('1201',),
                'paragraphs': paragraphs or [],
            })
            note_number += 1

        def _ensure_retained_earnings_note():
            nonlocal note_number
            if 'retained_earnings' in note_numbers:
                return
            note_numbers['retained_earnings'] = note_number
            note_sections.append({
                'number': note_number,
                'label': 'Retained earnings',
                'lines': [],
                'line_segments': self._build_generic_note_render_segments([]),
                'total_current': 0.0,
                'total_prev': 0.0,
            })
            note_number += 1

        def _add_equity_account_note(key, label, account_code):
            nonlocal note_number
            if key in note_numbers:
                return
            current_total = _equity_head_balance(current_account_heads, account_code)
            prev_total = _equity_head_balance(note_prev_account_heads, account_code)
            if not (current_total or prev_total):
                return
            group_code = account_code[:4]
            current_info = current_account_heads.get(group_code, {}).get(account_code, {})
            prev_info = note_prev_account_heads.get(group_code, {}).get(account_code, {})
            note_numbers[key] = note_number
            note_sections.append({
                'number': note_number,
                'label': label,
                'lines': [{
                    'code': account_code,
                    'name': current_info.get('name') or prev_info.get('name') or label,
                    'current': current_total,
                    'prev': prev_total,
                }],
                'line_segments': self._build_generic_note_render_segments([{
                    'code': account_code,
                    'name': current_info.get('name') or prev_info.get('name') or label,
                    'current': current_total,
                    'prev': prev_total,
                }]),
                'total_current': current_total,
                'total_prev': prev_total,
            })
            note_number += 1

        def _ensure_equity_detail_notes():
            _ensure_retained_earnings_note()
            note_numbers['statutory_reserves_equity'] = note_numbers.get('retained_earnings')

        non_current_codes = ['1101', '1102', '1103', '1104', '1105', '1106', '1107', '1108', '1109']
        current_codes = ['1201', '1202', '1203', '1204', '1206']
        equity_codes = ['3101']
        non_current_liability_codes = ['2101', '2102', '2103', '2104']
        current_liability_codes = ['2201', '2202', '2203', '2204']
        aggregated_payables_codes = set(current_liability_codes)
        for code in non_current_codes + current_codes + equity_codes + non_current_liability_codes + current_liability_codes:
            if code in aggregated_payables_codes:
                continue
            if code == '3101' and not show_shareholder_note:
                _ensure_equity_detail_notes()
                continue
            note_group_codes = [code]
            current_total = current_group_totals.get(code, 0.0)
            prev_total = note_prev_group_totals.get(code, 0.0)
            note_current_map = None
            note_prev_map = None
            if code == '1203':
                note_group_codes = ['1203', '1205']
                current_total += current_group_totals.get('1205', 0.0)
                prev_total += note_prev_group_totals.get('1205', 0.0)
            if code == '1105':
                note_current_map = {
                    '1105': {
                        account_code: info
                        for account_code, info in current_account_heads.get('1105', {}).items()
                        if account_code.startswith(LONG_TERM_DEPOSITS_PREFIX)
                    }
                }
                note_prev_map = {
                    '1105': {
                        account_code: info
                        for account_code, info in note_prev_account_heads.get('1105', {}).items()
                        if account_code.startswith(LONG_TERM_DEPOSITS_PREFIX)
                    }
                }
            if not (current_total or prev_total):
                if code == '3101':
                    if show_shareholder_note and code not in note_numbers:
                        note_numbers[code] = note_number
                        note_sections.append({
                            'number': note_number,
                            'label': note_labels.get(code, code),
                            'lines': [],
                            'line_segments': self._build_generic_note_render_segments([]),
                            'total_current': 0.0,
                            'total_prev': 0.0,
                        })
                        note_number += 1
                    _ensure_equity_detail_notes()
                continue
            _add_note(
                code,
                note_labels.get(code, code),
                note_group_codes,
                current_total,
                prev_total,
                current_map=note_current_map,
                prev_map=note_prev_map,
            )
            if code == '3101':
                _ensure_equity_detail_notes()

        aggregated_payables_current = sum(
            current_group_totals.get(code, 0.0)
            for code in aggregated_payables_codes
        )
        aggregated_payables_prev = sum(
            note_prev_group_totals.get(code, 0.0)
            for code in aggregated_payables_codes
        )
        if aggregated_payables_current or aggregated_payables_prev:
            _add_note(
                'other_payables',
                'Other payables',
                sorted(aggregated_payables_codes),
                aggregated_payables_current,
                aggregated_payables_prev,
            )

        expense_group_codes = sorted({
            code for code in current_group_totals
            if code.startswith('51')
        } | {
            code for code in note_prev_group_totals
            if code.startswith('51')
        })
        cost_codes = set(COST_OF_REVENUE_GROUPS['Cost of revenue'])
        depreciation_codes = set(DEPRECIATION_GROUPS['Depreciation'])
        tax_codes = {'5127'}
        operating_expense_codes = [
            code
            for code in expense_group_codes
            if code not in cost_codes | depreciation_codes | tax_codes
        ]
        depreciation_expense_current = sum(
            period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        depreciation_expense_prev = sum(
            note_prev_period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        amortization_expense_current = sum(
            period_prefix_totals[6].get(prefix, 0.0)
            for prefix in AMORTIZATION_EXPENSE_PREFIXES
        )
        amortization_expense_prev = sum(
            note_prev_period_prefix_totals[6].get(prefix, 0.0)
            for prefix in AMORTIZATION_EXPENSE_PREFIXES
        )
        operating_expense_note_codes = list(operating_expense_codes)
        if (
            depreciation_expense_current
            or depreciation_expense_prev
            or amortization_expense_current
            or amortization_expense_prev
        ):
            operating_expense_note_codes.append('5114')
            operating_expense_note_codes = sorted(set(operating_expense_note_codes))

        def _depreciation_amortization_note_map(depreciation_amount, amortization_amount):
            note_accounts = {}
            if depreciation_amount:
                note_accounts['511401'] = {
                    'name': 'Depreciation Expense',
                    'balance': depreciation_amount,
                }
            if amortization_amount:
                note_accounts['511402'] = {
                    'name': 'Amortization Expense',
                    'balance': amortization_amount,
                }
            return note_accounts

        operating_expense_current_map = dict(period_account_heads)
        operating_expense_prev_map = dict(note_prev_period_account_heads)
        if '5114' in operating_expense_note_codes:
            operating_expense_current_map['5114'] = _depreciation_amortization_note_map(
                depreciation_expense_current,
                amortization_expense_current,
            )
            operating_expense_prev_map['5114'] = _depreciation_amortization_note_map(
                depreciation_expense_prev,
                amortization_expense_prev,
            )

        note_prev_revenue_total = prev_revenue_total if show_prior_year else 0.0
        note_prev_cost_of_revenue_total = prev_cost_of_revenue_total if show_prior_year else 0.0
        note_prev_operating_expenses_total = prev_operating_expenses_total if show_prior_year else 0.0
        note_prev_investment_gain_loss_total = prev_investment_gain_loss_total if show_prior_year else 0.0
        if revenue_total or note_prev_revenue_total:
            _add_note(
                'pl_revenue',
                'Revenue',
                REVENUE_GROUPS['Revenue'],
                revenue_total,
                note_prev_revenue_total,
                current_map=period_account_heads,
                prev_map=note_prev_period_account_heads,
            )
        if cost_of_revenue_total or note_prev_cost_of_revenue_total:
            _add_note(
                'pl_cost',
                'Direct cost',
                COST_OF_REVENUE_GROUPS['Cost of revenue'],
                cost_of_revenue_total,
                note_prev_cost_of_revenue_total,
                current_map=period_account_heads,
                prev_map=note_prev_period_account_heads,
            )
        if operating_expenses_total or note_prev_operating_expenses_total:
            current_total = (
                sum(period_group_totals.get(code, 0.0) for code in operating_expense_codes)
                + depreciation_expense_current
                + amortization_expense_current
            )
            prev_total = (
                sum(note_prev_period_group_totals.get(code, 0.0) for code in operating_expense_codes)
                + depreciation_expense_prev
                + amortization_expense_prev
            )
            _add_note(
                'pl_opex',
                'Operating expenses',
                operating_expense_note_codes,
                current_total,
                prev_total,
                current_map=operating_expense_current_map,
                prev_map=operating_expense_prev_map,
            )
        if investment_gain_loss_total or note_prev_investment_gain_loss_total:
            _add_note(
                'pl_investment_gain_loss',
                'Gain / (loss) on investment',
                INVESTMENT_GAIN_LOSS_GROUPS['Gain / (loss) on investment'],
                investment_gain_loss_total,
                note_prev_investment_gain_loss_total,
                current_map=period_account_heads,
                prev_map=note_prev_period_account_heads,
            )

        post_table_note_keys = []
        if self.show_related_parties_note:
            post_table_note_keys.append('related_parties')
        if not period_category.startswith('cessation_'):
            post_table_note_keys.extend([
                'risk_management',
                'financial_assets_liabilities',
            ])
        post_table_note_keys.extend([
            'contingent_liabilities',
            'general_notes',
        ])
        for key in post_table_note_keys:
            note_numbers[key] = note_number
            note_number += 1
        last_note_number = note_number - 1

        opening_rows = _fetch_account_rows(date_start, date_end, balance_role='opening')
        opening_prefix_totals = _build_prefix_totals(opening_rows)
        opening_account_heads = _build_account_head_map(opening_rows)
        opening_group_totals = dict(
            _reclassify_owner_account_group_total(opening_prefix_totals[4], opening_account_heads)
        )
        opening_group_totals['2204'] = _corporate_tax_liability_total(opening_prefix_totals)

        if show_prior_year:
            prior_opening_rows = _fetch_account_rows(
                prior_date_start,
                prior_date_end,
                balance_role='opening',
            )
            prior_opening_prefix_totals = _build_prefix_totals(prior_opening_rows)
            prior_opening_account_heads = _build_account_head_map(prior_opening_rows)
        else:
            prior_opening_prefix_totals = _build_prefix_totals([])
            prior_opening_account_heads = {}
        prior_opening_group_totals = _reclassify_owner_account_group_total(
            prior_opening_prefix_totals[4],
            prior_opening_account_heads,
        )
        prior_opening_group_totals = dict(prior_opening_group_totals)
        prior_opening_group_totals['2204'] = _corporate_tax_liability_total(prior_opening_prefix_totals)
        # The first-balance label is manual-only: it uses the raw wizard date and
        # stays blank when unset, even though periods may carry a fallback date.
        soce_prior_opening_label_date = (
            self.soce_prior_opening_label_date if show_prior_year else False
        )

        ###### Variables for Cash Flow Statement ######
        eosb_liability_code = '21040101'
        dividend_paid_code = '31010202'

        def _liability_to_positive(value):
            return -value

        current_depreciation_total = sum(
            period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        prior_depreciation_total = sum(
            prev_period_prefix_totals[6].get(prefix, 0.0)
            for prefix in DEPRECIATION_EXPENSE_PREFIXES
        )
        cashflow_depreciation_lines = self._collect_note_lines(
            ['5114'],
            self._filter_account_head_map_by_prefixes(
                period_account_heads,
                DEPRECIATION_EXPENSE_PREFIXES,
            ),
            self._filter_account_head_map_by_prefixes(
                prev_period_account_heads if show_prior_year else {},
                DEPRECIATION_EXPENSE_PREFIXES,
            ),
        )
        current_amortization_total = sum(
            period_prefix_totals[6].get(prefix, 0.0)
            for prefix in AMORTIZATION_EXPENSE_PREFIXES
        )
        prior_amortization_total = sum(
            prev_period_prefix_totals[6].get(prefix, 0.0)
            for prefix in AMORTIZATION_EXPENSE_PREFIXES
        )

        eosb_movement = _liability_to_positive(period_prefix_totals[8].get(eosb_liability_code, 0.0))
        prior_eosb_movement = _liability_to_positive(prev_period_prefix_totals[8].get(eosb_liability_code, 0.0))

        end_service_benefits_adjustment = max(eosb_movement, 0.0)
        prior_end_service_benefits_adjustment = max(prior_eosb_movement, 0.0)
        end_service_benefits_paid = -max(-eosb_movement, 0.0)
        prior_end_service_benefits_paid = -max(-prior_eosb_movement, 0.0)
        cashflow_net_profit_amount = (
            net_profit_after_tax
            if self.cashflow_net_profit_use_after_tax
            else net_profit_before_tax
        )
        cashflow_prev_net_profit_amount = (
            prev_net_profit_after_tax
            if self.cashflow_net_profit_use_after_tax
            else prev_net_profit_before_tax
        )
        prior_year_adjustment = -period_prefix_totals[8].get(
            PRIOR_YEAR_ADJUSTMENT_ACCOUNT_CODE,
            0.0,
        )
        prev_prior_year_adjustment = -prev_period_prefix_totals[8].get(
            PRIOR_YEAR_ADJUSTMENT_ACCOUNT_CODE,
            0.0,
        )
        gain_on_disposal_adjustment = period_prefix_totals[8].get(
            GAIN_ON_DISPOSAL_ACCOUNT_CODE,
            0.0,
        )
        prior_gain_on_disposal_adjustment = prev_period_prefix_totals[8].get(
            GAIN_ON_DISPOSAL_ACCOUNT_CODE,
            0.0,
        )
        bad_debt_expense_addback = period_prefix_totals[8].get(
            BAD_DEBT_EXPENSE_ACCOUNT_CODE,
            0.0,
        )
        prior_bad_debt_expense_addback = prev_period_prefix_totals[8].get(
            BAD_DEBT_EXPENSE_ACCOUNT_CODE,
            0.0,
        )
        interest_paid_addback = _sum_prefixed_account_totals(
            period_prefix_totals,
            INTEREST_PAID_PREFIX,
        )
        prior_interest_paid_addback = _sum_prefixed_account_totals(
            prev_period_prefix_totals,
            INTEREST_PAID_PREFIX,
        )
        interest_paid = -interest_paid_addback
        prior_interest_paid = -prior_interest_paid_addback

        operating_cashflow_before_working_capital = (
            net_profit_before_tax
            + prior_year_adjustment
            + bad_debt_expense_addback
            + gain_on_disposal_adjustment
            + current_depreciation_total
            + current_amortization_total
            + end_service_benefits_adjustment
            + interest_paid_addback
        )
        prior_operating_cashflow_before_working_capital = (
            prev_net_profit_before_tax
            + prev_prior_year_adjustment
            + prior_bad_debt_expense_addback
            + prior_gain_on_disposal_adjustment
            + prior_depreciation_total
            + prior_amortization_total
            + prior_end_service_benefits_adjustment
            + prior_interest_paid_addback
        )

        current_wc_assets = (
            current_group_totals.get('1201', 0.0)
            + current_group_totals.get('1202', 0.0)
            + current_group_totals.get('1203', 0.0)
            + current_group_totals.get('1205', 0.0)
            + current_group_totals.get('1207', 0.0)
        )
        opening_wc_assets = (
            opening_group_totals.get('1201', 0.0)
            + opening_group_totals.get('1202', 0.0)
            + opening_group_totals.get('1203', 0.0)
            + opening_group_totals.get('1205', 0.0)
            + opening_group_totals.get('1207', 0.0)
        )
        prior_wc_assets = (
            prev_group_totals.get('1201', 0.0)
            + prev_group_totals.get('1202', 0.0)
            + prev_group_totals.get('1203', 0.0)
            + prev_group_totals.get('1205', 0.0)
            + prev_group_totals.get('1207', 0.0)
        )
        prior_opening_wc_assets = (
            prior_opening_group_totals.get('1201', 0.0)
            + prior_opening_group_totals.get('1202', 0.0)
            + prior_opening_group_totals.get('1203', 0.0)
            + prior_opening_group_totals.get('1205', 0.0)
            + prior_opening_group_totals.get('1207', 0.0)
        )

        change_in_current_assets = -(current_wc_assets - opening_wc_assets)
        prior_change_in_current_assets = -(prior_wc_assets - prior_opening_wc_assets)

        def _cashflow_current_liabilities_total(group_totals, prefix_totals):
            special_liability_total = sum(
                _sum_prefixed_account_totals(prefix_totals, prefix)
                for prefix in CASHFLOW_CURRENT_LIABILITY_PREFIXES
            )
            return _liability_to_positive(
                group_totals.get('2202', 0.0)
                + group_totals.get('2203', 0.0)
                + special_liability_total
            )

        current_wc_liabilities = _cashflow_current_liabilities_total(
            current_group_totals,
            current_prefix_totals,
        )
        opening_wc_liabilities = _cashflow_current_liabilities_total(
            opening_group_totals,
            opening_prefix_totals,
        )
        prior_wc_liabilities = _cashflow_current_liabilities_total(
            prev_group_totals,
            prev_prefix_totals,
        )
        prior_opening_wc_liabilities = _cashflow_current_liabilities_total(
            prior_opening_group_totals,
            prior_opening_prefix_totals,
        )

        change_in_current_liabilities = current_wc_liabilities - opening_wc_liabilities
        prior_change_in_current_liabilities = prior_wc_liabilities - prior_opening_wc_liabilities

        current_tax_liability = _liability_to_positive(
            _corporate_tax_liability_total(current_prefix_totals)
        )
        opening_tax_liability = _liability_to_positive(
            _corporate_tax_liability_total(opening_prefix_totals)
        )
        prior_tax_liability = _liability_to_positive(
            _corporate_tax_liability_total(prev_prefix_totals)
        )
        prior_opening_tax_liability = _liability_to_positive(
            _corporate_tax_liability_total(prior_opening_prefix_totals)
        )
        current_tax_expense = _sum_exact_account_totals(period_prefix_totals, CT_EXPENSE_ACCOUNT_CODES)
        prior_tax_expense = _sum_exact_account_totals(prev_period_prefix_totals, CT_EXPENSE_ACCOUNT_CODES)

        corporate_tax_paid = -(opening_tax_liability + current_tax_expense - current_tax_liability)
        prior_corporate_tax_paid = -(prior_opening_tax_liability + prior_tax_expense - prior_tax_liability)

        net_cash_generated_from_operations = (
            operating_cashflow_before_working_capital
            + change_in_current_assets
            + change_in_current_liabilities
            + corporate_tax_paid
            + end_service_benefits_paid
        )
        prior_net_cash_generated_from_operations = (
            prior_operating_cashflow_before_working_capital
            + prior_change_in_current_assets
            + prior_change_in_current_liabilities
            + prior_corporate_tax_paid
            + prior_end_service_benefits_paid
        )

        def _is_accumulated_depreciation_row(row):
            name = (row.get('name') or '').lower()
            return (
                'accumulated depreciation' in name
                or 'acc depreciation' in name
                or 'accumulated amortization' in name
                or 'acc amortization' in name
                or 'amortization' in name
            )

        def _sum_period_cost_balances(rows, group_code):
            return sum(
                (row.get('balance', 0.0) or 0.0)
                for row in rows
                if (row.get('code') or '').startswith(group_code)
                and not _is_accumulated_depreciation_row(row)
            )

        current_property = -(_sum_period_cost_balances(period_rows, '1101'))
        prior_property = -(_sum_period_cost_balances(prev_period_rows, '1101'))
        current_long_term_investments = -(period_group_totals.get('1104', 0.0))
        prior_long_term_investments = -(prev_period_group_totals.get('1104', 0.0))
        investing_activity_cashflow = -(period_group_totals.get('1110', 0.0))
        prior_investing_activity_cashflow = -(prev_period_group_totals.get('1110', 0.0))
        non_current_asset_cashflow = -(period_group_totals.get('1111', 0.0))
        prior_non_current_asset_cashflow = -(prev_period_group_totals.get('1111', 0.0))
        current_intangible_assets = -(_sum_period_cost_balances(period_rows, '1107'))
        prior_intangible_assets = -(_sum_period_cost_balances(prev_period_rows, '1107'))
        security_deposit = -_sum_exact_account_totals(
            period_prefix_totals,
            (SECURITY_DEPOSIT_ACCOUNT_CODE,),
        )
        prior_security_deposit = -_sum_exact_account_totals(
            prev_period_prefix_totals,
            (SECURITY_DEPOSIT_ACCOUNT_CODE,),
        )
        net_cash_generated_from_investing_activities = (
            current_property
            + current_long_term_investments
            + investing_activity_cashflow
            + non_current_asset_cashflow
            + current_intangible_assets
            + security_deposit
        )
        prior_net_cash_generated_from_investing_activities = (
            prior_property
            + prior_long_term_investments
            + prior_investing_activity_cashflow
            + prior_non_current_asset_cashflow
            + prior_intangible_assets
            + prior_security_deposit
        )

        company = self.company_id
        share_capital_account_code = '31010101'
        statement_share_capital_total = _equity_head_balance(current_account_heads, share_capital_account_code)
        statement_prev_share_capital_total = _equity_head_balance(prev_account_heads, share_capital_account_code)
        statement_prev_prev_share_capital_total = _equity_head_balance(
            prev_prev_account_heads,
            share_capital_account_code,
        )
        statement_prior_opening_share_capital_total = _equity_head_balance(
            prior_opening_account_heads,
            share_capital_account_code,
        )

        # Financial statement tables: pick share capital from GL account 31010101.
        if show_prior_year:
            # 2-year templates: show movement in paid-up capital instead of closing balance.
            paid_up_capital = statement_share_capital_total - statement_prev_share_capital_total
            prior_paid_up_capital = (
                statement_prev_share_capital_total - statement_prior_opening_share_capital_total
            )
        else:
            paid_up_capital = statement_share_capital_total
            prior_paid_up_capital = 0.0

        current_dividend = current_prefix_totals[8].get(dividend_paid_code, 0.0)
        opening_dividend = opening_prefix_totals[8].get(dividend_paid_code, 0.0)
        prior_dividend = prev_prefix_totals[8].get(dividend_paid_code, 0.0)
        prior_opening_dividend = prior_opening_prefix_totals[8].get(dividend_paid_code, 0.0)
        dividend_paid = -(current_dividend - opening_dividend)
        prior_dividend_paid = -(prior_dividend - prior_opening_dividend)

        owner_current_account = -period_prefix_totals[8].get(owner_current_account_code, 0.0)
        prior_owner_current_account = -prev_period_prefix_totals[8].get(owner_current_account_code, 0.0)
        related_party_loan = -_sum_prefixed_account_totals(
            period_prefix_totals,
            RELATED_PARTY_LOAN_PREFIX,
        )
        prior_related_party_loan = -_sum_prefixed_account_totals(
            prev_period_prefix_totals,
            RELATED_PARTY_LOAN_PREFIX,
        )
        financing_activity_cashflow = _liability_to_positive(
            period_group_totals.get('2105', 0.0)
        )
        prior_financing_activity_cashflow = _liability_to_positive(
            prev_period_group_totals.get('2105', 0.0)
        )
        non_current_liability_cashflow = _liability_to_positive(
            period_group_totals.get('2106', 0.0)
        )
        prior_non_current_liability_cashflow = _liability_to_positive(
            prev_period_group_totals.get('2106', 0.0)
        )
        deposit_cashflow = _liability_to_positive(period_group_totals.get('2107', 0.0))
        prior_deposit_cashflow = _liability_to_positive(prev_period_group_totals.get('2107', 0.0))

        net_cash_generated_from_financing_activities = (
            paid_up_capital
            + dividend_paid
            + owner_current_account
            + related_party_loan
            + financing_activity_cashflow
            + non_current_liability_cashflow
            + deposit_cashflow
            + interest_paid
        )
        prior_net_cash_generated_from_financing_activities = (
            prior_paid_up_capital
            + prior_dividend_paid
            + prior_owner_current_account
            + prior_related_party_loan
            + prior_financing_activity_cashflow
            + prior_non_current_liability_cashflow
            + prior_deposit_cashflow
            + prior_interest_paid
        )

        current_cash_and_bank = current_group_totals.get('1204', 0.0)
        current_interbank = current_group_totals.get('1206', 0.0)
        opening_cash_and_bank = opening_group_totals.get('1204', 0.0)
        opening_interbank = opening_group_totals.get('1206', 0.0)
        prior_cash_and_bank = prev_group_totals.get('1204', 0.0)
        prior_interbank = prev_group_totals.get('1206', 0.0)
        prior_opening_cash_and_bank = prior_opening_group_totals.get('1204', 0.0)
        prior_opening_interbank = prior_opening_group_totals.get('1206', 0.0)

        current_cash_equivalents = current_cash_and_bank - current_interbank
        opening_cash_equivalents = opening_cash_and_bank - opening_interbank
        prior_cash_equivalents = prior_cash_and_bank - prior_interbank
        prior_opening_cash_equivalents = prior_opening_cash_and_bank - prior_opening_interbank

        net_cash_and_cash_equivalents = (
            net_cash_generated_from_operations
            + net_cash_generated_from_investing_activities
            + net_cash_generated_from_financing_activities
        )
        cash_beginning_year = opening_cash_equivalents
        cash_end_of_year = current_cash_equivalents

        prior_net_cash_and_cash_equivalents = (
            prior_net_cash_generated_from_operations
            + prior_net_cash_generated_from_investing_activities
            + prior_net_cash_generated_from_financing_activities
        )
        prior_cash_beginning_year = prior_opening_cash_equivalents
        prior_cash_end_of_year = prior_cash_equivalents


        ##############################################################################################

        ############# Shareholders Section #############


        # Shareholders START #
        #########################################################################################################
        company = self.company_id

        def _format_shareholder_name(name):
            normalized = ' '.join((name or '').split())
            return normalized.title() if normalized else ''

        # Shareholders (explicit variables)
        sh_name_1 = _format_shareholder_name(company.shareholder_1)
        sh_nat_1 = company.nationality_1
        sh_shares_1 = company.number_of_shares_1
        sh_value_1 = company.share_value_1
        sh_total_1 = company.total_share_1

        sh_name_2 = _format_shareholder_name(company.shareholder_2)
        sh_nat_2 = company.nationality_2
        sh_shares_2 = company.number_of_shares_2
        sh_value_2 = company.share_value_2
        sh_total_2 = company.total_share_2

        sh_name_3 = _format_shareholder_name(company.shareholder_3)
        sh_nat_3 = company.nationality_3
        sh_shares_3 = company.number_of_shares_3
        sh_value_3 = company.share_value_3
        sh_total_3 = company.total_share_3

        sh_name_4 = _format_shareholder_name(company.shareholder_4)
        sh_nat_4 = company.nationality_4
        sh_shares_4 = company.number_of_shares_4
        sh_value_4 = company.share_value_4
        sh_total_4 = company.total_share_4

        sh_name_5 = _format_shareholder_name(company.shareholder_5)
        sh_nat_5 = company.nationality_5
        sh_shares_5 = company.number_of_shares_5
        sh_value_5 = company.share_value_5
        sh_total_5 = company.total_share_5

        sh_name_6 = _format_shareholder_name(company.shareholder_6)
        sh_nat_6 = company.nationality_6
        sh_shares_6 = company.number_of_shares_6
        sh_value_6 = company.share_value_6
        sh_total_6 = company.total_share_6

        sh_name_7 = _format_shareholder_name(company.shareholder_7)
        sh_nat_7 = company.nationality_7
        sh_shares_7 = company.number_of_shares_7
        sh_value_7 = company.share_value_7
        sh_total_7 = company.total_share_7

        sh_name_8 = _format_shareholder_name(company.shareholder_8)
        sh_nat_8 = company.nationality_8
        sh_shares_8 = company.number_of_shares_8
        sh_value_8 = company.share_value_8
        sh_total_8 = company.total_share_8

        sh_name_9 = _format_shareholder_name(company.shareholder_9)
        sh_nat_9 = company.nationality_9
        sh_shares_9 = company.number_of_shares_9
        sh_value_9 = company.share_value_9
        sh_total_9 = company.total_share_9

        sh_name_10 = _format_shareholder_name(company.shareholder_10)
        sh_nat_10 = company.nationality_10
        sh_shares_10 = company.number_of_shares_10
        sh_value_10 = company.share_value_10
        sh_total_10 = company.total_share_10

        share_rows = []
        for i in range(1, 11):
            name = getattr(company, f'shareholder_{i}', False)
            if not name:
                continue
            if not getattr(self, f'owner_include_{i}', False):
                continue
            share_rows.append({
                'name': _format_shareholder_name(name),
                'value': getattr(company, f'share_value_{i}', 0.0) or 0.0,
                'shares': getattr(company, f'number_of_shares_{i}', 0) or 0,
                'total': getattr(company, f'total_share_{i}', 0.0) or 0.0,
            })

        authorized_share_capital = sum(row['total'] for row in share_rows)
        total_shares_count = sum(row['shares'] for row in share_rows)
        share_value_default = share_rows[0]['value'] if share_rows else 0.0

        signature_entries = []
        for i in range(1, 11):
            name = getattr(company, f'shareholder_{i}', False)
            if not name or not name.strip():
                continue
            if not getattr(self, f'signature_include_{i}', False):
                continue
            role = (getattr(self, f'signature_role_{i}', 'secondary') or 'secondary').lower()
            is_primary = role == 'primary'
            nationality = getattr(company, f'nationality_{i}', False)
            display_name = f"{name} – {nationality}" if nationality else name
            signature_entries.append({
                'index': i,
                'name': name.strip(),
                'display_name': display_name,
                'is_primary': is_primary,
            })

        if signature_entries and not any(entry['is_primary'] for entry in signature_entries):
            signature_entries[0]['is_primary'] = True

        signature_entries.sort(key=lambda entry: (0 if entry['is_primary'] else 1, entry['index']))

        # Keep one "primary" signatory for existing template rendering.
        for idx, entry in enumerate(signature_entries):
            entry['is_primary'] = idx == 0

        signature_names = [entry['name'] for entry in signature_entries]
        signature_display_names = [entry['display_name'] for entry in signature_entries]

        owner_display_names = []
        for i in range(1, 11):
            name = getattr(company, f'shareholder_{i}', False)
            if not name:
                continue
            if not getattr(self, f'owner_include_{i}', False):
                continue
            formatted_name = _format_shareholder_name(name)
            nationality = getattr(company, f'nationality_{i}', False)
            if nationality:
                owner_display_names.append(f"{formatted_name} – {nationality}")
            else:
                owner_display_names.append(formatted_name)

        shareholder_display_names = []
        for i in range(1, 11):
            name = getattr(company, f'shareholder_{i}', False)
            if not name or not name.strip():
                continue
            if not getattr(self, f'director_include_{i}', False):
                continue
            formatted_name = _format_shareholder_name(name)
            nationality = getattr(company, f'nationality_{i}', False)
            if nationality:
                shareholder_display_names.append(f"{formatted_name} ({nationality})")
            else:
                shareholder_display_names.append(formatted_name)

        def _join_names(names):
            if not names:
                return ''
            if len(names) == 1:
                return names[0]
            if len(names) == 2:
                return f"{names[0]} and {names[1]}"
            return f"{', '.join(names[:-1])} and {names[-1]}"

        if not shareholder_display_names:
            fallback_name = _format_shareholder_name(company.shareholder_1)
            fallback_nationality = (company.nationality_1 or '').strip()
            if fallback_name:
                if fallback_nationality:
                    shareholder_display_names = [f"{fallback_name} ({fallback_nationality})"]
                else:
                    shareholder_display_names = [fallback_name]
        shareholder_display_text = _join_names(shareholder_display_names)
        management_director_names = []
        for i in range(1, 11):
            name = getattr(company, f'shareholder_{i}', False)
            if not name or not name.strip():
                continue
            if getattr(self, f'signature_include_{i}', False):
                management_director_names.append(_format_shareholder_name(name))
        if not management_director_names:
            fallback_director = _format_shareholder_name(company.shareholder_1)
            if fallback_director:
                management_director_names = [fallback_director]
        management_director_text = _join_names(management_director_names)
        management_director_title = 'Director' if len(management_director_names) <= 1 else 'Directors'
        signature_date_mode = (self.signature_date_mode or 'today').strip().lower()
        if signature_date_mode == 'manual' and self.signature_manual_date:
            generated_date = fields.Date.to_date(self.signature_manual_date)
        elif signature_date_mode == 'report_end' and self.date_end:
            generated_date = fields.Date.to_date(self.date_end)
        else:
            generated_date = fields.Date.context_today(self)
        generated_date_display = generated_date.strftime("%d/%m/%Y") if generated_date else ''

        emphasis_note_items = []
        emphasis_note_lines = []
        emphasis_sub_note = 6

        def _next_emphasis_note_ref():
            nonlocal emphasis_sub_note
            note_ref = f'1.{emphasis_sub_note}'
            emphasis_sub_note += 1
            return note_ref

        if self.emphasis_change_period:
            changed_from = _format_long_date(
                fields.Date.to_date(self.emphasis_change_from_date) if self.emphasis_change_from_date else None
            )
            changed_to = _format_long_date(
                fields.Date.to_date(self.emphasis_change_to_date) if self.emphasis_change_to_date else None
            )
            change_period_note_ref = _next_emphasis_note_ref()
            emphasis_note_items.append({
                'key': 'change_period',
                'label': 'Change in Financial Year/Period',
                'note_ref': change_period_note_ref,
                'matter_text': (
                    f"the change in the Entity’s financial reporting period from {changed_from} "
                    f"to {changed_to}"
                ),
            })
            emphasis_note_lines.append({
                'note_ref': change_period_note_ref,
                'note_text': (
                    f"The Entity previously issued audited financial statements for the period ended {changed_from}. "
                    f"To align with regulatory requirements, the Entity has revised its financial reporting period to "
                    f"{changed_to}, and this change has been applied retrospectively. Accordingly, the comparative "
                    f"information presented is for the period ended {changed_to}."
                ),
            })

        if self.additional_note_legal_status_change:
            legal_change_date = _format_long_date(
                fields.Date.to_date(self.emphasis_legal_change_date) if self.emphasis_legal_change_date else None
            )
            legal_status_from = (self.emphasis_legal_status_from or '').strip()
            legal_status_to = (self.emphasis_legal_status_to or '').strip()
            legal_registration_authority = (getattr(company, 'free_zone', '') or '').strip()
            if not legal_registration_authority:
                legal_registration_authority = 'Department of Economy and Tourism'
            emphasis_note_lines.append({
                'note_ref': _next_emphasis_note_ref(),
                'note_text': (
                    f'On {legal_change_date}, the Entity officially changed its legal status from "{legal_status_from}" '
                    f'to "{legal_status_to}". The change was approved by the Director and has been '
                    f'registered with the {legal_registration_authority}, Dubai, United Arab Emirates.'
                ),
            })

        if self.additional_note_no_active_bank_account:
            emphasis_note_lines.append({
                'note_ref': _next_emphasis_note_ref(),
                'note_text': (
                    f"{(self.company_name or 'The Entity').upper()} (the Entity) currently has no active bank account. "
                    f"All expenses were paid by the {management_director_title} from their personal resources."
                ),
            })

        if self.additional_note_business_bank_account_opened:
            emphasis_note_lines.append({
                'note_ref': _next_emphasis_note_ref(),
                'note_text': (
                    f"{self.company_name or 'The Entity'} (the Entity) initially conducted transactions using a "
                    'personal account instead of maintaining a dedicated business bank account. Subsequently, '
                    'post year-end, a business bank account has been opened and is now fully operational.'
                ),
            })

        if self.emphasis_correction_error:
            correction_note_ref = note_numbers.get('correction_error')
            if correction_note_ref:
                emphasis_note_items.append({
                    'key': 'correction_error',
                    'label': 'Correction of Error',
                    'note_ref': correction_note_ref,
                    'matter_text': "the correction of a prior period error",
                })

        show_emphasis_of_matter = bool(emphasis_note_items)
        show_other_matter = bool(show_unaudited_prior_year and prior_label_date_end)
        other_matter_paragraph = False
        other_matter_company_name = False
        other_matter_date_display = False
        other_matter_period_word = False
        if show_other_matter:
            other_matter_company_name = self.company_name or 'The Entity'
            other_matter_date_display = (
                prior_label_date_end.strftime('%d %B %Y')
                if prior_label_date_end else ''
            )
            other_matter_period_word = prior_column_period_word
            other_matter_paragraph = (
                f"The financial statements of {other_matter_company_name} (the Entity) "
                f"for the {other_matter_period_word} ended {other_matter_date_display} "
                "were unaudited. Our opinion does not extend to the comparative information."
            )



        # Shareholders END #
        #########################################################################################################

        # Changes in Equity START #
        #########################################################################################################
        total_shares = statement_share_capital_total
        prev_total_shares = statement_prev_share_capital_total
        prev_prev_total_shares = statement_prev_prev_share_capital_total
        prior_opening_total_shares = statement_prior_opening_share_capital_total

        retained_earnings_code = '31010203'
        statutory_reserves_code = '31010301'
        owner_current_account_equity = _equity_head_balance(current_account_heads, owner_current_account_code)
        prev_owner_current_account_equity = _equity_head_balance(prev_account_heads, owner_current_account_code)
        prev_prev_owner_current_account_equity = _equity_head_balance(prev_prev_account_heads, owner_current_account_code)
        prior_opening_owner_current_account_equity = _equity_head_balance(
            prior_opening_account_heads,
            owner_current_account_code,
        )
        share_capital_paid_status_for_report = self.share_capital_paid_status
        statutory_reserves_equity = _equity_head_balance(current_account_heads, statutory_reserves_code)
        prev_statutory_reserves_equity = _equity_head_balance(prev_account_heads, statutory_reserves_code)
        prev_prev_statutory_reserves_equity = _equity_head_balance(prev_prev_account_heads, statutory_reserves_code)
        # Notes should read directly from statutory reserve account balances,
        # independent from any SOCE row assembly.
        notes_statutory_reserves_equity = _equity_head_balance(
            current_account_heads,
            statutory_reserves_code,
        )
        notes_prev_statutory_reserves_equity = _equity_head_balance(
            note_prev_account_heads,
            statutory_reserves_code,
        )
        prior_opening_statutory_reserves_equity = _equity_head_balance(
            prior_opening_account_heads,
            statutory_reserves_code,
        )
        prior_retained_earnings_balance = _equity_head_balance(prev_account_heads, retained_earnings_code)
        prev_prev_retained_earnings_balance = _equity_head_balance(prev_prev_account_heads, retained_earnings_code)
        prior_opening_retained_earnings_balance = _equity_head_balance(
            prior_opening_account_heads,
            retained_earnings_code,
        )
        retained_earnings = net_profit_after_tax
        prev_retained_earnings = prev_net_profit_after_tax
        prev_prev_retained_earnings = prev_prev_net_profit_after_tax
        statutory_reserves_transfer = statutory_reserves_equity - prev_statutory_reserves_equity
        prior_statutory_reserves_transfer = (
            prev_statutory_reserves_equity - prior_opening_statutory_reserves_equity
        )
        notes_statutory_reserves_movement = statutory_reserves_transfer
        notes_prev_statutory_reserves_movement = prior_statutory_reserves_transfer
        if show_prior_year:
            # Keep first opening row on prior closing retained earnings.
            prior_opening_retained_earnings_balance = prior_retained_earnings_balance
            # Prior-year retained earnings equals the middle-row subtotal
            # carry-forward from prior opening plus comparative movements.
            prev_retained_earnings_balance = (
                prior_opening_retained_earnings_balance
                + prev_retained_earnings
                + oci_other_comprehensive_income_prior
                + prev_prior_year_adjustment
                - prior_statutory_reserves_transfer
                + prior_dividend_paid
            )
            retained_earnings_balance = (
                prev_retained_earnings_balance
                + retained_earnings
                + oci_other_comprehensive_income_current
                + prior_year_adjustment
                + dividend_paid
                - statutory_reserves_transfer
            )
        else:
            prev_retained_earnings_balance = prior_retained_earnings_balance
            retained_earnings_balance = (
                prior_retained_earnings_balance
                + retained_earnings
                + oci_other_comprehensive_income_current
                + prior_year_adjustment
                + dividend_paid
                - statutory_reserves_transfer
            )

        equity_total_display = (
            total_shares
            + owner_current_account_equity
            + retained_earnings_balance
            + statutory_reserves_equity
        )
        prev_equity_total_display = (
            prev_total_shares
            + prev_owner_current_account_equity
            + prev_retained_earnings_balance
            + prev_statutory_reserves_equity
        )
        prev_prev_equity_total_display = (
            prev_prev_total_shares
            + prev_prev_owner_current_account_equity
            + prev_prev_retained_earnings_balance
            + prev_prev_statutory_reserves_equity
        )
        prior_opening_equity_total_display = (
            prior_opening_total_shares
            + prior_opening_owner_current_account_equity
            + prior_opening_retained_earnings_balance
            + prior_opening_statutory_reserves_equity
        )
        balance_sheet_total_equity = equity_total_display
        prev_balance_sheet_total_equity = prev_equity_total_display

        # Total Equity to show on the statement of changes in equity
        total_soce = equity_total_display
        prev_total_soce = prev_equity_total_display
        prev_prev_total_soce = prev_prev_equity_total_display
        total_of_equity_and_liabilities = balance_sheet_total_equity + total_liabilities
        prev_total_of_equity_and_liabilities = prev_balance_sheet_total_equity + prev_total_liabilities
        show_current_year_profit_line = True

        def _is_non_zero(value):
            # Keep row/column visibility aligned with displayed amounts,
            # which are rounded to whole numbers in the templates.
            return self._round_amount(value) != 0.0

        def _format_date_label(date_value):
            return date_value.strftime('%d %B %Y') if date_value else ''

        def _total_comprehensive_label(amount, period_word):
            profit_or_loss = '(loss)' if (amount or 0.0) < 0 else 'profit'
            return f"Total comprehensive {profit_or_loss} for the {period_word}"

        def _period_word_for_range(start_date, end_date):
            if not start_date or not end_date:
                return 'period'
            expected_year_end = start_date + relativedelta(years=1) - relativedelta(days=1)
            return 'year' if expected_year_end == end_date else 'period'

        show_other_comprehensive_income_row = (
            self.show_other_comprehensive_income_page
            or _is_non_zero(oci_other_comprehensive_income_current)
            or (show_prior_year and _is_non_zero(oci_other_comprehensive_income_prior))
        )

        OWNED_PPE_SUBHEADS = [
            ('land', 'Land'),
            ('buildings', 'Building and Structures'),
            ('110102', 'Furnitures and fixtures'),
            ('110103', 'Leasehold improvements'),
            ('110104', 'Vehicles'),
            ('110105', 'Computer equipments'),
            ('110106', 'Office equipments'),
        ]
        INTANGIBLE_SUBHEADS = [
            ('110701', 'Software & Licences'),
            ('110702', 'Website & Blogs'),
            ('110703', 'Other Intangible Assets'),
        ]
        owned_ppe_subhead_labels = {code: label for code, label in OWNED_PPE_SUBHEADS}
        owned_ppe_subhead_codes = [code for code, _label in OWNED_PPE_SUBHEADS]
        intangible_subhead_labels = {code: label for code, label in INTANGIBLE_SUBHEADS}
        intangible_subhead_codes = [code for code, _label in INTANGIBLE_SUBHEADS]
        ppe_metric_keys = (
            'cost_opening',
            'cost_additions',
            'cost_disposals',
            'cost_closing',
            'acc_opening',
            'acc_charge',
            'acc_disposals',
            'acc_closing',
            'carrying_closing',
        )

        def _empty_ppe_metrics():
            return {
                'cost_opening': 0.0,
                'cost_additions': 0.0,
                'cost_disposals': 0.0,
                'cost_closing': 0.0,
                'acc_opening': 0.0,
                'acc_charge': 0.0,
                'acc_disposals': 0.0,
                'acc_closing': 0.0,
                'carrying_closing': 0.0,
            }

        def _owned_ppe_subhead_code(account_code):
            if not account_code or len(account_code) < 6:
                return None
            if account_code.startswith('11010101'):
                return 'land'
            if account_code.startswith(('11010102', '11010103')):
                return 'buildings'
            subhead_code = account_code[:6]
            if subhead_code not in owned_ppe_subhead_labels:
                return None
            return subhead_code

        def _build_ppe_schedule_data(start_date, end_date):
            metrics_by_subhead = {
                code: _empty_ppe_metrics()
                for code in owned_ppe_subhead_codes
            }
            opening_rows = _fetch_account_rows(start_date, end_date, balance_role='opening')
            period_rows = _fetch_account_rows(start_date, end_date, balance_role='movement')
            closing_rows = _fetch_account_rows(start_date, end_date, balance_role='closing')

            def _consume_rows(rows, value_loader):
                for row in rows:
                    subhead_code = _owned_ppe_subhead_code(row.get('code') or '')
                    if not subhead_code:
                        continue
                    subhead_metrics = metrics_by_subhead[subhead_code]
                    value_loader(subhead_metrics, row, _is_accumulated_depreciation_row(row))

            def _consume_opening(subhead_metrics, row, is_acc_dep):
                balance = row.get('balance', 0.0) or 0.0
                if is_acc_dep:
                    subhead_metrics['acc_opening'] += -balance
                else:
                    subhead_metrics['cost_opening'] += balance

            def _consume_period(subhead_metrics, row, is_acc_dep):
                debit = row.get('debit', 0.0) or 0.0
                credit = row.get('credit', 0.0) or 0.0
                if is_acc_dep:
                    subhead_metrics['acc_charge'] += credit
                    subhead_metrics['acc_disposals'] += -debit
                else:
                    subhead_metrics['cost_additions'] += debit
                    subhead_metrics['cost_disposals'] += -credit

            def _consume_closing(subhead_metrics, row, is_acc_dep):
                balance = row.get('balance', 0.0) or 0.0
                if is_acc_dep:
                    subhead_metrics['acc_closing'] += -balance
                else:
                    subhead_metrics['cost_closing'] += balance

            _consume_rows(opening_rows, _consume_opening)
            _consume_rows(period_rows, _consume_period)
            _consume_rows(closing_rows, _consume_closing)

            for code in owned_ppe_subhead_codes:
                subhead_metrics = metrics_by_subhead[code]
                subhead_metrics['carrying_closing'] = (
                    subhead_metrics['cost_closing'] - subhead_metrics['acc_closing']
                )

            return {
                'start_date': start_date,
                'end_date': end_date,
                'start_label': _format_date_label(start_date),
                'end_label': _format_date_label(end_date),
                'period_word': _period_word_for_range(start_date, end_date),
                'metrics': metrics_by_subhead,
            }

        ppe_schedule_data = []
        if date_start and date_end:
            # PPE notes should always show the current reporting schedule only.
            ppe_schedule_data.append(_build_ppe_schedule_data(date_start, date_end))

        ppe_visible_subheads = []
        for subhead_code in owned_ppe_subhead_codes:
            has_display_activity = any(
                _is_non_zero(
                    (schedule.get('metrics', {}).get(subhead_code, {}).get(metric_key, 0.0))
                )
                for schedule in ppe_schedule_data
                for metric_key in ppe_metric_keys
            )
            if has_display_activity:
                ppe_visible_subheads.append(subhead_code)

        if not ppe_visible_subheads:
            for subhead_code in owned_ppe_subhead_codes:
                has_raw_activity = any(
                    abs(schedule.get('metrics', {}).get(subhead_code, {}).get(metric_key, 0.0)) > 0.0
                    for schedule in ppe_schedule_data
                    for metric_key in ppe_metric_keys
                )
                if has_raw_activity:
                    ppe_visible_subheads.append(subhead_code)

        if not ppe_visible_subheads and ppe_schedule_data:
            ppe_visible_subheads = list(owned_ppe_subhead_codes)

        ppe_note_columns = [
            {'code': subhead_code, 'label': owned_ppe_subhead_labels[subhead_code]}
            for subhead_code in ppe_visible_subheads
        ]
        ppe_note_columns.append({'code': 'total', 'label': 'Total'})

        def _build_ppe_values(schedule_metrics, field_name):
            values = [schedule_metrics.get(code, {}).get(field_name, 0.0) for code in ppe_visible_subheads]
            total_value = sum(values)
            return values + [total_value]

        def _show_ppe_row(values):
            visible_values = values[:len(ppe_visible_subheads)]
            return any(_is_non_zero(value) for value in visible_values)

        ppe_note_schedules = []
        for schedule in ppe_schedule_data:
            schedule_metrics = schedule.get('metrics', {})
            schedule_rows = []
            section_values = [None] * len(ppe_note_columns)
            schedule_rows.append({
                'row_type': 'section',
                'label': 'Cost',
                'values': section_values,
            })
            schedule_rows.append({
                'row_type': 'line',
                'label': f"As at {schedule.get('start_label')}",
                'values': _build_ppe_values(schedule_metrics, 'cost_opening'),
            })
            additions_values = _build_ppe_values(schedule_metrics, 'cost_additions')
            if _show_ppe_row(additions_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': f"Additions during the {schedule.get('period_word')}",
                    'values': additions_values,
                })
            disposals_values = _build_ppe_values(schedule_metrics, 'cost_disposals')
            if _show_ppe_row(disposals_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': 'Disposals',
                    'values': disposals_values,
                })
            schedule_rows.append({
                'row_type': 'subtotal',
                'css_class': 'ppe-row-cost-subtotal',
                'label': f"As at {schedule.get('end_label')}",
                'values': _build_ppe_values(schedule_metrics, 'cost_closing'),
            })
            schedule_rows.append({
                'row_type': 'section',
                'label': 'Accumulated depreciation',
                'values': [None] * len(ppe_note_columns),
            })
            schedule_rows.append({
                'row_type': 'line',
                'label': f"As at {schedule.get('start_label')}",
                'values': _build_ppe_values(schedule_metrics, 'acc_opening'),
            })
            charge_values = _build_ppe_values(schedule_metrics, 'acc_charge')
            if _show_ppe_row(charge_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': f"Depreciation for the {schedule.get('period_word')}",
                    'values': charge_values,
                })
            acc_disposals_values = _build_ppe_values(schedule_metrics, 'acc_disposals')
            if _show_ppe_row(acc_disposals_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': 'Disposals',
                    'values': acc_disposals_values,
                })
            schedule_rows.append({
                'row_type': 'subtotal',
                'label': f"As at {schedule.get('end_label')}",
                'values': _build_ppe_values(schedule_metrics, 'acc_closing'),
            })
            schedule_rows.append({
                'row_type': 'final',
                'label': f"Carrying value as at {schedule.get('end_label')}",
                'values': _build_ppe_values(schedule_metrics, 'carrying_closing'),
            })
            ppe_note_schedules.append({
                'start_label': schedule.get('start_label'),
                'end_label': schedule.get('end_label'),
                'period_word': schedule.get('period_word'),
                'rows': schedule_rows,
            })

        ppe_note_number = note_numbers.get('1101')

        def _intangible_subhead_code(account_code):
            if not account_code or len(account_code) < 6:
                return None
            subhead_code = account_code[:6]
            if subhead_code not in intangible_subhead_labels:
                return None
            return subhead_code

        def _build_intangible_schedule_data(start_date, end_date):
            metrics_by_subhead = {
                code: _empty_ppe_metrics()
                for code in intangible_subhead_codes
            }
            opening_rows = _fetch_account_rows(start_date, end_date, balance_role='opening')
            period_rows = _fetch_account_rows(start_date, end_date, balance_role='movement')
            closing_rows = _fetch_account_rows(start_date, end_date, balance_role='closing')

            def _consume_rows(rows, value_loader):
                for row in rows:
                    subhead_code = _intangible_subhead_code(row.get('code') or '')
                    if not subhead_code:
                        continue
                    subhead_metrics = metrics_by_subhead[subhead_code]
                    value_loader(subhead_metrics, row, _is_accumulated_depreciation_row(row))

            def _consume_opening(subhead_metrics, row, is_acc_dep):
                balance = row.get('balance', 0.0) or 0.0
                if is_acc_dep:
                    subhead_metrics['acc_opening'] += -balance
                else:
                    subhead_metrics['cost_opening'] += balance

            def _consume_period(subhead_metrics, row, is_acc_dep):
                debit = row.get('debit', 0.0) or 0.0
                credit = row.get('credit', 0.0) or 0.0
                if is_acc_dep:
                    subhead_metrics['acc_charge'] += credit
                    subhead_metrics['acc_disposals'] += -debit
                else:
                    subhead_metrics['cost_additions'] += debit
                    subhead_metrics['cost_disposals'] += -credit

            def _consume_closing(subhead_metrics, row, is_acc_dep):
                balance = row.get('balance', 0.0) or 0.0
                if is_acc_dep:
                    subhead_metrics['acc_closing'] += -balance
                else:
                    subhead_metrics['cost_closing'] += balance

            _consume_rows(opening_rows, _consume_opening)
            _consume_rows(period_rows, _consume_period)
            _consume_rows(closing_rows, _consume_closing)

            for code in intangible_subhead_codes:
                subhead_metrics = metrics_by_subhead[code]
                subhead_metrics['carrying_closing'] = (
                    subhead_metrics['cost_closing'] - subhead_metrics['acc_closing']
                )

            return {
                'start_date': start_date,
                'end_date': end_date,
                'start_label': _format_date_label(start_date),
                'end_label': _format_date_label(end_date),
                'period_word': _period_word_for_range(start_date, end_date),
                'metrics': metrics_by_subhead,
            }

        intangible_schedule_data = []
        if date_start and date_end:
            # Intangible notes should always show the current reporting schedule only.
            intangible_schedule_data.append(_build_intangible_schedule_data(date_start, date_end))

        intangible_visible_subheads = []
        for subhead_code in intangible_subhead_codes:
            has_display_activity = any(
                _is_non_zero(
                    (schedule.get('metrics', {}).get(subhead_code, {}).get(metric_key, 0.0))
                )
                for schedule in intangible_schedule_data
                for metric_key in ppe_metric_keys
            )
            if has_display_activity:
                intangible_visible_subheads.append(subhead_code)

        if not intangible_visible_subheads:
            for subhead_code in intangible_subhead_codes:
                has_raw_activity = any(
                    abs(schedule.get('metrics', {}).get(subhead_code, {}).get(metric_key, 0.0)) > 0.0
                    for schedule in intangible_schedule_data
                    for metric_key in ppe_metric_keys
                )
                if has_raw_activity:
                    intangible_visible_subheads.append(subhead_code)

        if not intangible_visible_subheads and intangible_schedule_data:
            intangible_visible_subheads = list(intangible_subhead_codes)

        intangible_note_columns = [
            {'code': subhead_code, 'label': intangible_subhead_labels[subhead_code]}
            for subhead_code in intangible_visible_subheads
        ]
        intangible_note_columns.append({'code': 'total', 'label': 'Total'})

        def _build_intangible_values(schedule_metrics, field_name):
            values = [schedule_metrics.get(code, {}).get(field_name, 0.0) for code in intangible_visible_subheads]
            total_value = sum(values)
            return values + [total_value]

        def _show_intangible_row(values):
            visible_values = values[:len(intangible_visible_subheads)]
            return any(_is_non_zero(value) for value in visible_values)

        intangible_note_schedules = []
        for schedule in intangible_schedule_data:
            schedule_metrics = schedule.get('metrics', {})
            schedule_rows = []
            section_values = [None] * len(intangible_note_columns)
            schedule_rows.append({
                'row_type': 'section',
                'label': 'Cost',
                'values': section_values,
            })
            schedule_rows.append({
                'row_type': 'line',
                'label': f"As at {schedule.get('start_label')}",
                'values': _build_intangible_values(schedule_metrics, 'cost_opening'),
            })
            additions_values = _build_intangible_values(schedule_metrics, 'cost_additions')
            if _show_intangible_row(additions_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': f"Additions during the {schedule.get('period_word')}",
                    'values': additions_values,
                })
            disposals_values = _build_intangible_values(schedule_metrics, 'cost_disposals')
            if _show_intangible_row(disposals_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': 'Disposals',
                    'values': disposals_values,
                })
            schedule_rows.append({
                'row_type': 'subtotal',
                'css_class': 'ppe-row-cost-subtotal',
                'label': f"As at {schedule.get('end_label')}",
                'values': _build_intangible_values(schedule_metrics, 'cost_closing'),
            })
            schedule_rows.append({
                'row_type': 'section',
                'label': 'Accumulated amortization',
                'values': [None] * len(intangible_note_columns),
            })
            schedule_rows.append({
                'row_type': 'line',
                'label': f"As at {schedule.get('start_label')}",
                'values': _build_intangible_values(schedule_metrics, 'acc_opening'),
            })
            charge_values = _build_intangible_values(schedule_metrics, 'acc_charge')
            if _show_intangible_row(charge_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': f"Amortization for the {schedule.get('period_word')}",
                    'values': charge_values,
                })
            acc_disposals_values = _build_intangible_values(schedule_metrics, 'acc_disposals')
            if _show_intangible_row(acc_disposals_values):
                schedule_rows.append({
                    'row_type': 'line',
                    'label': 'Disposals',
                    'values': acc_disposals_values,
                })
            schedule_rows.append({
                'row_type': 'subtotal',
                'label': f"As at {schedule.get('end_label')}",
                'values': _build_intangible_values(schedule_metrics, 'acc_closing'),
            })
            schedule_rows.append({
                'row_type': 'final',
                'label': f"Carrying value as at {schedule.get('end_label')}",
                'values': _build_intangible_values(schedule_metrics, 'carrying_closing'),
            })
            intangible_note_schedules.append({
                'start_label': schedule.get('start_label'),
                'end_label': schedule.get('end_label'),
                'period_word': schedule.get('period_word'),
                'rows': schedule_rows,
            })

        intangible_note_number = note_numbers.get('1107')

        prior_share_capital_movement = prev_total_shares - prior_opening_total_shares
        current_opening_share_capital = prev_total_shares if show_prior_year else prior_opening_total_shares
        current_share_capital_movement = total_shares - current_opening_share_capital

        soce_rows = []
        if show_prior_year and prior_date_start:
            soce_rows.append({
                'label': f"Balance as at {_format_date_label(soce_prior_opening_label_date)}",
                'share_capital': prior_opening_total_shares,
                'owner_current_account': prior_opening_owner_current_account_equity,
                'retained_earnings': prior_opening_retained_earnings_balance,
                'statutory_reserves': prior_opening_statutory_reserves_equity,
                'total_equity': prior_opening_equity_total_display,
                'is_balance': True,
            })
            if _is_non_zero(prior_share_capital_movement):
                soce_rows.append({
                    'label': "Share capital",
                    'share_capital': prior_share_capital_movement,
                    'owner_current_account': None,
                    'retained_earnings': None,
                    'statutory_reserves': None,
                    'total_equity': prior_share_capital_movement,
                    'is_balance': False,
                })
            if _is_non_zero(prior_owner_current_account):
                soce_rows.append({
                    'label': "Net movement in owner current\xa0account",
                    'share_capital': None,
                    'owner_current_account': prior_owner_current_account,
                    'retained_earnings': None,
                    'statutory_reserves': None,
                    'total_equity': prior_owner_current_account,
                    'is_balance': False,
                })
        if prior_date_end:
            if show_prior_year:
                prior_period_word = prior_column_period_word
                soce_rows.append({
                    'label': _total_comprehensive_label(prev_retained_earnings, prior_period_word),
                    'share_capital': None,
                    'owner_current_account': None,
                    'retained_earnings': prev_retained_earnings,
                    'statutory_reserves': None,
                    'total_equity': prev_retained_earnings,
                    'period_word': prior_period_word,
                    'is_balance': False,
                })
                if _is_non_zero(prev_prior_year_adjustment):
                    soce_rows.append({
                        'label': "Prior year adjustment",
                        'share_capital': None,
                        'owner_current_account': None,
                        'retained_earnings': prev_prior_year_adjustment,
                        'statutory_reserves': None,
                        'total_equity': prev_prior_year_adjustment,
                        'is_balance': False,
                    })
                if show_other_comprehensive_income_row:
                    soce_rows.append({
                        'label': "Other comprehensive income",
                        'share_capital': None,
                        'owner_current_account': None,
                        'retained_earnings': oci_other_comprehensive_income_prior,
                        'statutory_reserves': None,
                        'total_equity': oci_other_comprehensive_income_prior,
                        'is_balance': False,
                        'use_amount_line': True,
                    })
                if _is_non_zero(prior_statutory_reserves_transfer):
                    soce_rows.append({
                        'label': "Transferred to statutory reserves",
                        'share_capital': None,
                        'owner_current_account': None,
                        'retained_earnings': -prior_statutory_reserves_transfer,
                        'statutory_reserves': prior_statutory_reserves_transfer,
                        'total_equity': 0.0,
                        'is_balance': False,
                    })
                if _is_non_zero(prior_dividend_paid):
                    soce_rows.append({
                        'label': "Dividend paid",
                        'share_capital': None,
                        'owner_current_account': None,
                        'retained_earnings': prior_dividend_paid,
                        'statutory_reserves': None,
                        'total_equity': prior_dividend_paid,
                        'is_balance': False,
                    })
            opening_current_date = date_start if not show_prior_year else prior_date_end
            if not opening_current_date:
                opening_current_date = prior_date_end
            if show_prior_year:
                # Middle opening balance is a subtotal carry-forward of
                # all above comparative movement rows.
                opening_share_capital = (
                    prior_opening_total_shares + prior_share_capital_movement
                )
                opening_owner_current_account = (
                    prior_opening_owner_current_account_equity + prior_owner_current_account
                )
                opening_retained_earnings = prev_retained_earnings_balance
                opening_statutory_reserves = (
                    prior_opening_statutory_reserves_equity + prior_statutory_reserves_transfer
                )
                opening_total_equity = (
                    opening_share_capital
                    + opening_owner_current_account
                    + opening_retained_earnings
                    + opening_statutory_reserves
                )
            else:
                opening_share_capital = None
                opening_owner_current_account = None
                opening_retained_earnings = None
                opening_statutory_reserves = None
                opening_total_equity = None
            soce_rows.append({
                'label': f"Balance as at {_format_date_label(opening_current_date)}",
                'share_capital': opening_share_capital,
                'owner_current_account': opening_owner_current_account,
                'retained_earnings': opening_retained_earnings,
                'statutory_reserves': opening_statutory_reserves,
                'total_equity': opening_total_equity,
                'is_balance': True,
            })
            if _is_non_zero(current_share_capital_movement):
                share_capital_value = current_share_capital_movement
                total_equity_value = current_share_capital_movement
                soce_rows.append({
                    'label': "Share capital",
                    'share_capital': share_capital_value,
                    'owner_current_account': None,
                    'retained_earnings': None,
                    'statutory_reserves': None,
                    'total_equity': total_equity_value,
                    'is_balance': False,
                })
            if _is_non_zero(owner_current_account):
                soce_rows.append({
                    'label': "Net movement in owner current\xa0account",
                    'share_capital': None,
                    'owner_current_account': owner_current_account,
                    'retained_earnings': None,
                    'statutory_reserves': None,
                    'total_equity': owner_current_account,
                    'is_balance': False,
                })
        if show_current_year_profit_line:
            period_word = current_column_period_word
            current_profit_label = _total_comprehensive_label(retained_earnings, period_word)
            soce_rows.append({
                'label': current_profit_label,
                'share_capital': None,
                'owner_current_account': None,
                'retained_earnings': retained_earnings,
                'statutory_reserves': None,
                'total_equity': retained_earnings,
                'period_word': period_word,
                'is_balance': False,
            })
            if _is_non_zero(prior_year_adjustment):
                soce_rows.append({
                    'label': "Prior year adjustment",
                    'share_capital': None,
                    'owner_current_account': None,
                    'retained_earnings': prior_year_adjustment,
                    'statutory_reserves': None,
                    'total_equity': prior_year_adjustment,
                    'is_balance': False,
                })
        if show_other_comprehensive_income_row:
            soce_rows.append({
                'label': "Other comprehensive income",
                'share_capital': None,
                'owner_current_account': None,
                'retained_earnings': oci_other_comprehensive_income_current,
                'statutory_reserves': None,
                'total_equity': oci_other_comprehensive_income_current,
                'is_balance': False,
                'use_amount_line': True,
            })
        if _is_non_zero(statutory_reserves_transfer):
            soce_rows.append({
                'label': "Transferred to statutory reserves",
                'share_capital': None,
                'owner_current_account': None,
                'retained_earnings': -statutory_reserves_transfer,
                'statutory_reserves': statutory_reserves_transfer,
                'total_equity': 0.0,
                'is_balance': False,
            })
        if _is_non_zero(dividend_paid):
            soce_rows.append({
                'label': "Dividend paid",
                'share_capital': None,
                'owner_current_account': None,
                'retained_earnings': dividend_paid,
                'statutory_reserves': None,
                'total_equity': dividend_paid,
                'is_balance': False,
            })
        if date_end:
            soce_rows.append({
                'label': f"Balance as at {date_end.strftime('%d %B %Y')}",
                'share_capital': total_shares,
                'owner_current_account': owner_current_account_equity,
                'retained_earnings': retained_earnings_balance,
                'statutory_reserves': statutory_reserves_equity,
                'total_equity': equity_total_display,
                'is_balance': True,
            })

        # Keep retained earnings note values aligned with SOCE rows.
        def _retained_amount_from_soce_row(row):
            if not row:
                return None
            value = row.get('retained_earnings')
            if value is None:
                return None
            return self._to_float(value)

        def _soce_rows_by_exact_label(label):
            return [
                row for row in soce_rows
                if (row.get('label') or '').strip() == label
            ]

        soce_balance_rows = [row for row in soce_rows if row.get('is_balance')]
        soce_opening_current_row = None
        soce_opening_prior_row = None
        soce_closing_current_row = soce_balance_rows[-1] if soce_balance_rows else None

        if show_prior_year:
            if len(soce_balance_rows) >= 2:
                soce_opening_current_row = soce_balance_rows[-2]
            if len(soce_balance_rows) >= 3:
                soce_opening_prior_row = soce_balance_rows[0]
        elif len(soce_balance_rows) >= 2:
            soce_opening_current_row = soce_balance_rows[-2]

        soce_total_comprehensive_rows = [
            row for row in soce_rows
            if (row.get('label') or '').startswith('Total comprehensive ')
        ]
        soce_current_total_comprehensive_row = (
            soce_total_comprehensive_rows[-1]
            if soce_total_comprehensive_rows else None
        )
        soce_prior_total_comprehensive_row = (
            soce_total_comprehensive_rows[0]
            if show_prior_year and len(soce_total_comprehensive_rows) > 1
            else None
        )

        retained_earnings_for_notes = _retained_amount_from_soce_row(soce_current_total_comprehensive_row)
        if retained_earnings_for_notes is None:
            retained_earnings_for_notes = retained_earnings
        prev_retained_earnings_for_notes = _retained_amount_from_soce_row(soce_prior_total_comprehensive_row)
        if prev_retained_earnings_for_notes is None:
            prev_retained_earnings_for_notes = prev_retained_earnings

        prev_retained_earnings_balance_for_notes = _retained_amount_from_soce_row(soce_opening_current_row)
        if prev_retained_earnings_balance_for_notes is None:
            prev_retained_earnings_balance_for_notes = prev_retained_earnings_balance
        prev_prev_retained_earnings_balance_for_notes = _retained_amount_from_soce_row(soce_opening_prior_row)
        if prev_prev_retained_earnings_balance_for_notes is None:
            prev_prev_retained_earnings_balance_for_notes = prev_prev_retained_earnings_balance
        retained_earnings_balance_for_notes = _retained_amount_from_soce_row(soce_closing_current_row)
        if retained_earnings_balance_for_notes is None:
            retained_earnings_balance_for_notes = retained_earnings_balance

        notes_statutory_reserves_movement_for_notes = notes_statutory_reserves_movement
        notes_prev_statutory_reserves_movement_for_notes = notes_prev_statutory_reserves_movement

        # Show SOCE columns only when they contain non-zero displayed values.
        show_share_capital_column = any(
            row.get('share_capital') is not None and _is_non_zero(row.get('share_capital'))
            for row in soce_rows
        )
        show_owner_current_account_column = any(
            row.get('owner_current_account') is not None and _is_non_zero(row.get('owner_current_account'))
            for row in soce_rows
        )
        show_statutory_reserves_column = any(
            row.get('statutory_reserves') is not None and _is_non_zero(row.get('statutory_reserves'))
            for row in soce_rows
        )
        soce_column_count = (
            3
            + int(show_share_capital_column)
            + int(show_owner_current_account_column)
            + int(show_statutory_reserves_column)
        )
        show_owner_current_account_equity_row = (
            _is_non_zero(owner_current_account_equity)
            or (show_prior_year and _is_non_zero(prev_owner_current_account_equity))
        )
        show_owner_current_account_cashflow_row = (
            _is_non_zero(owner_current_account)
            or (show_prior_year and _is_non_zero(prior_owner_current_account))
        )
        show_related_party_loan_cashflow_row = (
            _is_non_zero(related_party_loan)
            or (show_prior_year and _is_non_zero(prior_related_party_loan))
        )
        show_interest_paid_cashflow_row = (
            _is_non_zero(interest_paid)
            or (show_prior_year and _is_non_zero(prior_interest_paid))
        )
        show_security_deposit_cashflow_row = (
            _is_non_zero(security_deposit)
            or (show_prior_year and _is_non_zero(prior_security_deposit))
        )
        show_investing_activity_cashflow_row = (
            _is_non_zero(investing_activity_cashflow)
            or (show_prior_year and _is_non_zero(prior_investing_activity_cashflow))
        )
        show_non_current_asset_cashflow_row = (
            _is_non_zero(non_current_asset_cashflow)
            or (show_prior_year and _is_non_zero(prior_non_current_asset_cashflow))
        )
        show_intangible_asset_cashflow_row = (
            _is_non_zero(current_intangible_assets)
            or (show_prior_year and _is_non_zero(prior_intangible_assets))
        )
        show_financing_activity_cashflow_row = (
            _is_non_zero(financing_activity_cashflow)
            or (show_prior_year and _is_non_zero(prior_financing_activity_cashflow))
        )
        show_non_current_liability_cashflow_row = (
            _is_non_zero(non_current_liability_cashflow)
            or (show_prior_year and _is_non_zero(prior_non_current_liability_cashflow))
        )
        show_deposit_cashflow_row = (
            _is_non_zero(deposit_cashflow)
            or (show_prior_year and _is_non_zero(prior_deposit_cashflow))
        )

        # Changes in Equity END #
        #########################################################################################################

        # DMCC Supplementary Sheet START #
        #########################################################################################################
        dmcc_fixed_assets_net = sum(
            account.get('balance', 0.0)
            for account in current_account_heads.get('1101', {}).values()
            if 'accumulated depreciation' not in (account.get('name') or '').strip().lower()
        )
        dmcc_non_current_assets_excl_fixed_assets = non_current_assets_total - dmcc_fixed_assets_net
        dmcc_reserves = abs(current_prefix_totals[8].get('31010301', 0.0))
        dmcc_shareholders_current_account_loans = abs(
            current_prefix_totals[8].get(owner_current_account_code, 0.0)
        )
        dmcc_total_equity_system = balance_sheet_total_equity
        dmcc_total_salaries = (
            period_group_totals.get('5108', 0.0)
            + period_prefix_totals[8].get('51070101', 0.0)
        )
        dmcc_all_other_expenses = operating_expenses_total - dmcc_total_salaries
        dmcc_sheet_data = {
            'company_name': self.company_name or '',
            'portal_account_no': self.portal_account_no or '',
            'customer_license_no': self.company_license_number or '',
            'year_start_date': date_start.strftime('%d/%m/%Y') if date_start else '',
            'year_end_date': date_end.strftime('%d/%m/%Y') if date_end else '',
            'total_share_capital': total_shares,
            'reserves': dmcc_reserves,
            'retained_earnings': retained_earnings_balance,
            'shareholders_current_account_loans': dmcc_shareholders_current_account_loans,
            'total_equity_system': dmcc_total_equity_system,
            'fixed_assets_net': dmcc_fixed_assets_net,
            'total_depreciation': depreciation_total,
            'current_assets': current_assets_total,
            'non_current_assets_excl_fixed_assets': dmcc_non_current_assets_excl_fixed_assets,
            'total_assets_system': total_assets,
            'current_liabilities': abs(current_liabilities_total),
            'non_current_liabilities': abs(non_current_liabilities_total),
            'total_liabilities_system': total_liabilities,
            'annual_sales_turnover': revenue_total,
            'cost_of_revenue_goods_sold': cost_of_revenue_total,
            'total_salaries': dmcc_total_salaries,
            'all_other_expenses': dmcc_all_other_expenses,
            'all_other_income': other_income_total,
            'gross_profit_loss_system': gross_profit,
            'net_profit_loss_system': net_profit_after_tax,
            'audit_firm_name': 'Assurance Corp Audit and Accounting',
            'auditor_signature': '',
            'auditor_date': generated_date_display,
            'auditor_seal': '',
        }
        # DMCC Supplementary Sheet END #
        #########################################################################################################

        # Statement of Cash Flows START #
        #########################################################################################################


        


        # Statement of Cash Flows END #
        #########################################################################################################

        tb_diff_current = total_assets - total_of_equity_and_liabilities
        tb_diff_prior = prev_total_assets - prev_total_of_equity_and_liabilities if show_prior_year else 0.0
        tb_warning_current = self._compose_tb_warning('Current period', tb_diff_current)
        tb_warning_prior = (
            self._compose_tb_warning('Prior period', tb_diff_prior)
            if show_prior_year else False
        )

        # Dividend > Retained Earnings warning
        dividend_warning_current = False
        dividend_warning_prior = False
        if dividend_paid and retained_earnings_balance < dividend_paid:
            dividend_warning_current = (
                f"Current period: Dividend ({dividend_paid:,.2f}) exceeds retained earnings "
                f"({retained_earnings_balance:,.2f})."
            )
        if show_prior_year and prior_dividend_paid and prev_retained_earnings_balance < prior_dividend_paid:
            dividend_warning_prior = (
                f"Prior period: Dividend ({prior_dividend_paid:,.2f}) exceeds retained earnings "
                f"({prev_retained_earnings_balance:,.2f})."
            )

        # Director salary > 0 requires related party disclosure checkbox.
        related_party_checkbox_warning_current = False
        related_party_checkbox_warning_prior = False
        if not self.show_related_parties_note:
            director_salary_current = self._to_float(
                period_prefix_totals[8].get(DIRECTOR_SALARY_ACCOUNT_CODE)
            )
            if director_salary_current > 0.0:
                related_party_checkbox_warning_current = self._compose_related_parties_checkbox_warning(
                    'Current period',
                    director_salary_current,
                )
            if show_prior_year:
                director_salary_prior = self._to_float(
                    prev_period_prefix_totals[8].get(DIRECTOR_SALARY_ACCOUNT_CODE)
                )
                if director_salary_prior > 0.0:
                    related_party_checkbox_warning_prior = self._compose_related_parties_checkbox_warning(
                        'Prior period',
                        director_salary_prior,
                    )

        # Combine warnings
        if dividend_warning_current:
            tb_warning_current = (
                f"{tb_warning_current}\n{dividend_warning_current}"
                if tb_warning_current else dividend_warning_current
            )
        if dividend_warning_prior:
            tb_warning_prior = (
                f"{tb_warning_prior}\n{dividend_warning_prior}"
                if tb_warning_prior else dividend_warning_prior
            )
        if related_party_checkbox_warning_current:
            tb_warning_current = (
                f"{tb_warning_current}\n{related_party_checkbox_warning_current}"
                if tb_warning_current else related_party_checkbox_warning_current
            )
        if related_party_checkbox_warning_prior:
            tb_warning_prior = (
                f"{tb_warning_prior}\n{related_party_checkbox_warning_prior}"
                if tb_warning_prior else related_party_checkbox_warning_prior
            )

        self.tb_diff_current = tb_diff_current
        self.tb_diff_prior = tb_diff_prior
        self.tb_warning_current = tb_warning_current or False
        self.tb_warning_prior = tb_warning_prior or False
        self._sync_tb_overrides_json()
        if tb_warning_current or tb_warning_prior:
            _logger.warning(
                (
                    "AUDIT_TB_MISMATCH wizard_id=%s company_id=%s "
                    "current_diff=%.6f prior_diff=%.6f"
                ),
                self.id,
                self.company_id.id,
                tb_diff_current,
                tb_diff_prior,
            )
        related_party_rows = self._get_render_related_party_rows()
        first_related_party_row = related_party_rows[0]

        return {

            # Balance Sheet
            'balance_rows': balance_rows,
            'profit_loss_accounts': profit_loss_accounts,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': balance_sheet_total_equity,
            'current_assets': current_assets,
            'current_liabilities': current_liabilities,
            'equity': equity,
            'non_current_assets': non_current_assets,
            'non_current_liabilities': non_current_liabilities,
            'current_liabilities_total': current_liabilities_total,
            'non_current_liabilities_total': non_current_liabilities_total,
            'current_assets_total': current_assets_total,
            'non_current_assets_total': non_current_assets_total,
            'total_of_equity_and_liabilities': total_of_equity_and_liabilities,
            'tb_diff_current': tb_diff_current,
            'tb_warning_current': tb_warning_current,
            'prev_current_assets_total': prev_current_assets_total,
            'prev_non_current_assets_total': prev_non_current_assets_total,
            'prev_total_assets': prev_total_assets,
            'prev_current_liabilities_total': prev_current_liabilities_total,
            'prev_non_current_liabilities_total': prev_non_current_liabilities_total,
            'prev_total_liabilities': prev_total_liabilities,
            'prev_total_equity': prev_balance_sheet_total_equity,
            'prev_total_of_equity_and_liabilities': prev_total_of_equity_and_liabilities,
            'tb_diff_prior': tb_diff_prior,
            'tb_warning_prior': tb_warning_prior,

            # PnL
             'cost_of_revenue_total':cost_of_revenue_total,
             'depreciation_total':depreciation_total,
             'operating_expenses_total':operating_expenses_total,
             'revenue_total':revenue_total,
             'gross_profit':gross_profit,
             'net_profit_before_tax':net_profit_before_tax,
             'net_profit_after_tax':net_profit_after_tax,
             'other_income_total': other_income_total,
             'gross_profit_margin': gross_profit_margin,
             'gross_profit_margin_label': gross_profit_margin_label,
             'net_profit_margin': net_profit_margin,
             **financial_review_net_display_data,
             'tax_amount':tax_amount,
             'prev_revenue_total': prev_revenue_total,
             'prev_cost_of_revenue_total': prev_cost_of_revenue_total,
             'prev_gross_profit': prev_gross_profit,
             'prev_operating_expenses_total': prev_operating_expenses_total,
             'prev_net_profit_before_tax': prev_net_profit_before_tax,
             'prev_tax_amount': prev_tax_amount,
             'prev_net_profit_after_tax': prev_net_profit_after_tax,
             'prev_other_income_total': prev_other_income_total,
             'prev_gross_profit_margin': prev_gross_profit_margin,
             'prev_net_profit_margin': prev_net_profit_margin,
             'net_profit_before_tax_label': net_profit_before_tax_label,
             'net_profit_after_tax_label': net_profit_after_tax_label,
             'oci_profit_line_label': oci_profit_line_label,
             'oci_profit_line_current': oci_profit_line_current,
             'oci_profit_line_prior': oci_profit_line_prior if show_prior_year else 0.0,
             'oci_other_comprehensive_income_current': oci_other_comprehensive_income_current,
             'oci_other_comprehensive_income_prior': (
                 oci_other_comprehensive_income_prior if show_prior_year else 0.0
             ),
             'oci_total_comprehensive_label': oci_total_comprehensive_label,
             'oci_total_comprehensive_current': oci_total_comprehensive_current,
             'oci_total_comprehensive_prior': (
                 oci_total_comprehensive_prior if show_prior_year else 0.0
             ),

             # Statement of Changes in Equity
             'retained_earnings': retained_earnings_for_notes,
            'total_soce':total_soce,
            'prev_retained_earnings': prev_retained_earnings_for_notes,
            'prev_total_soce': prev_total_soce,
            'prev_prev_retained_earnings': prev_prev_retained_earnings,
            'prev_prev_total_soce': prev_prev_total_soce,
            'share_capital_total': total_shares,
            'prev_share_capital_total': prev_total_shares,
            'owner_current_account_equity': owner_current_account_equity,
            'prev_owner_current_account_equity': prev_owner_current_account_equity,
            'statutory_reserves_equity': statutory_reserves_equity,
            'prev_statutory_reserves_equity': prev_statutory_reserves_equity,
            'notes_statutory_reserves_equity': notes_statutory_reserves_equity,
            'notes_prev_statutory_reserves_equity': notes_prev_statutory_reserves_equity,
            'notes_statutory_reserves_movement': notes_statutory_reserves_movement_for_notes,
            'notes_prev_statutory_reserves_movement': notes_prev_statutory_reserves_movement_for_notes,
            'retained_earnings_balance': retained_earnings_balance_for_notes,
            'prev_retained_earnings_balance': prev_retained_earnings_balance_for_notes,
            'prev_prev_retained_earnings_balance': prev_prev_retained_earnings_balance_for_notes,
            'equity_total_display': equity_total_display,
            'prev_equity_total_display': prev_equity_total_display,
            'prev_prev_equity_total_display': prev_prev_equity_total_display,
            'soce_rows': soce_rows,
            'show_share_capital_column': show_share_capital_column,
            'show_owner_current_account_column': show_owner_current_account_column,
            'show_statutory_reserves_column': show_statutory_reserves_column,
            'soce_column_count': soce_column_count,
            'show_owner_current_account_equity_row': show_owner_current_account_equity_row,
            'show_owner_current_account_cashflow_row': show_owner_current_account_cashflow_row,
            'show_related_party_loan_cashflow_row': show_related_party_loan_cashflow_row,
            'show_interest_paid_cashflow_row': show_interest_paid_cashflow_row,
            'show_security_deposit_cashflow_row': show_security_deposit_cashflow_row,
            'show_investing_activity_cashflow_row': show_investing_activity_cashflow_row,
            'show_non_current_asset_cashflow_row': show_non_current_asset_cashflow_row,
            'show_intangible_asset_cashflow_row': show_intangible_asset_cashflow_row,
            'show_financing_activity_cashflow_row': show_financing_activity_cashflow_row,
            'show_non_current_liability_cashflow_row': show_non_current_liability_cashflow_row,
            'show_deposit_cashflow_row': show_deposit_cashflow_row,
            'comparative_period_word': comparative_period_word,
            'report_period_word': current_column_period_word,
            'signature_names': signature_names,
            'signature_display_names': signature_display_names,
            'signature_entries': signature_entries,
            'owner': '',
            'owner_display_names': owner_display_names,
            'shareholder_display_text': shareholder_display_text,
            'management_director_text': management_director_text,
            'management_director_title': management_director_title,
            'generated_date_display': generated_date_display,
            'share_rows': share_rows,
            'authorized_share_capital': authorized_share_capital,
            'total_shares_count': total_shares_count,
            'share_value_default': share_value_default,
            'share_capital_paid_status': share_capital_paid_status_for_report,
            'show_share_capital_conversion_note': self.show_share_capital_conversion_note,
            'share_conversion_currency': (self.share_conversion_currency or '').strip(),
            'share_conversion_original_value': self.share_conversion_original_value or 0.0,
            'share_conversion_exchange_rate': self.share_conversion_exchange_rate or 0.0,
            'show_share_capital_transfer_note': self.show_share_capital_transfer_note,
            'share_transfer_date': self.share_transfer_date,
            'share_transfer_from': (self.share_transfer_from or '').strip(),
            'share_transfer_shares': self.share_transfer_shares or 0,
            'share_transfer_percentage': self.share_transfer_percentage or 0.0,
            'share_transfer_to': (self.share_transfer_to or '').strip(),
            'related_party_rows': related_party_rows,
            'related_party_name': first_related_party_row.get('name') or False,
            'related_party_relationship': first_related_party_row.get('relationship') or False,
            'related_party_transaction': first_related_party_row.get('transaction') or False,
            'related_party_amount': self._to_float(first_related_party_row.get('amount')),
            'related_party_amount_prior': self._to_float(first_related_party_row.get('amount_prior')),
            'show_related_parties_note': self.show_related_parties_note,
            'show_shareholder_note': self.show_shareholder_note,
            'show_other_comprehensive_income_page': self.show_other_comprehensive_income_page,
            'business_activity_services_suffix': (
                ' services' if self.business_activity_include_services else ''
            ),
            'business_activity_providing_prefix': (
                'providing ' if self.business_activity_include_providing else ''
            ),
            'show_ct_first_tax_year_line': self.show_ct_first_tax_year_line,
            'cashflow_net_profit_use_after_tax': self.cashflow_net_profit_use_after_tax,
            'replace_going_concern_paragraph': self.replace_going_concern_paragraph,
            'replace_going_concern_year': self.replace_going_concern_year,
            'liquidation_going_concern_paragraphs': self._get_liquidation_going_concern_paragraphs(),
            'ignore_notes_last_page_margins': self.ignore_notes_last_page_margins,
            'show_investment_note_schedule': self.show_investment_note_schedule,
            'gap_report_of_directors': self.gap_report_of_directors,
            'gap_independent_auditor_report': self.gap_independent_auditor_report,
            'gap_notes_to_financial_statements': self.gap_notes_to_financial_statements,
            'signature_break_lines_report_of_directors': max(
                int(self.signature_break_lines_report_of_directors or 0), 0
            ),
            'signature_break_lines_balance_sheet': max(int(self.signature_break_lines_balance_sheet or 0), 0),
            'signature_break_lines_profit_loss': max(int(self.signature_break_lines_profit_loss or 0), 0),
            'signature_break_lines_changes_in_equity': max(
                int(self.signature_break_lines_changes_in_equity or 0), 0
            ),
            'signature_break_lines_cash_flows': max(int(self.signature_break_lines_cash_flows or 0), 0),
            'signature_break_lines_notes': max(int(self.signature_break_lines_notes or 0), 0),

            # Shareholders
            'sh_name_1':sh_name_1,
             'sh_nat_1':sh_nat_1,
             'sh_shares_1':sh_shares_1,
             'sh_value_1':sh_value_1,
             'sh_total_1':sh_total_1,
             'sh_name_2':sh_name_2,
             'sh_nat_2':sh_nat_2,
             'sh_shares_2':sh_shares_2,
             'sh_value_2':sh_value_2,
             'sh_total_2':sh_total_2,
             'sh_name_3':sh_name_3,
             'sh_nat_3':sh_nat_3,
             'sh_shares_3':sh_shares_3,
             'sh_value_3':sh_value_3,
             'sh_total_3':sh_total_3,

             # Property and equipment subheads
             'current_ppe_subheads': current_ppe_subheads,
             'current_ppe_total': current_ppe_total,
             'prev_ppe_subheads': prev_ppe_subheads,
             'prev_ppe_total': prev_ppe_total,
             'current_subheads_by_group': current_subheads_by_group,
             'prev_subheads_by_group': prev_subheads_by_group,
             'current_main_heads': current_main_heads,
             'prev_main_heads': prev_main_heads,
            'main_head_labels': MAIN_HEAD_LABELS,
            'current_group_totals': current_group_totals,
            'prev_group_totals': prev_group_totals,
            'show_prior_year': show_prior_year,
            'show_unaudited_prior_year': show_unaudited_prior_year,
            'show_prior_year_marker': bool(
                show_prior_year and (self.emphasis_correction_error or show_unaudited_prior_year)
            ),
            'prior_year_marker_label': (
                'Re-stated'
                if self.emphasis_correction_error and show_prior_year
                else 'Unaudited'
                if show_unaudited_prior_year
                else False
            ),
            'show_restated_headers': bool(self.emphasis_correction_error and show_prior_year),
            'prior_date_end': prior_date_end,
            'prior_label_date_end': prior_label_date_end,
            'audit_period_category': period_category,
            'usd_statement': usd_text_mode_enabled,
            'usd_statement_master': usd_statement_enabled,
            'tb_convert_balances_to_usd': convert_tb_to_usd,
            'tb_usd_conversion_rate': usd_conversion_rate,
            'replace_aed_text_with_usd': replace_aed_text_with_usd,
            'balance_sheet_date_mode': 'end_only',
            'prior_balance_sheet_date_mode': 'end_only',
            'is_dormant_period': period_category.startswith('dormant_'),
            'is_cessation_period': period_category.startswith('cessation_'),
            'fa_other_receivables_current': other_receivables_current,
            'fa_other_receivables_prev': other_receivables_prev,
            'fa_note_vat_receivable_current': fa_note_vat_receivable_current,
            'fa_note_vat_receivable_prev': fa_note_vat_receivable_prev,
             'fa_note_vat_payable_current': fa_note_vat_payable_current,
             'fa_note_vat_payable_prev': fa_note_vat_payable_prev,
            'investment_gain_loss_total': investment_gain_loss_total,
            'prev_investment_gain_loss_total': prev_investment_gain_loss_total,

            # Cash flow
            'current_depreciation_total': current_depreciation_total,
            'prior_depreciation_total': prior_depreciation_total,
            'cashflow_depreciation_lines': cashflow_depreciation_lines,
            'current_amortization_total': current_amortization_total,
            'prior_amortization_total': prior_amortization_total,
            'end_service_benefits_adjustment': end_service_benefits_adjustment,
            'prior_end_service_benefits_adjustment': prior_end_service_benefits_adjustment,
            'prior_year_adjustment': prior_year_adjustment,
            'prev_prior_year_adjustment': prev_prior_year_adjustment,
            'bad_debt_expense_addback': bad_debt_expense_addback,
            'prior_bad_debt_expense_addback': prior_bad_debt_expense_addback,
            'gain_on_disposal_adjustment': gain_on_disposal_adjustment,
            'prior_gain_on_disposal_adjustment': prior_gain_on_disposal_adjustment,
            'interest_paid_addback': interest_paid_addback,
            'prior_interest_paid_addback': prior_interest_paid_addback,
            'cashflow_net_profit_amount': cashflow_net_profit_amount,
            'cashflow_prev_net_profit_amount': cashflow_prev_net_profit_amount,
            'operating_cashflow_before_working_capital': operating_cashflow_before_working_capital,
            'prior_operating_cashflow_before_working_capital': prior_operating_cashflow_before_working_capital,
            'change_in_current_assets': change_in_current_assets,
            'prior_change_in_current_assets': prior_change_in_current_assets,
            'change_in_current_liabilities': change_in_current_liabilities,
            'prior_change_in_current_liabilities': prior_change_in_current_liabilities,
            'corporate_tax_paid': corporate_tax_paid,
            'prior_corporate_tax_paid': prior_corporate_tax_paid,
            'end_service_benefits_paid': end_service_benefits_paid,
            'prior_end_service_benefits_paid': prior_end_service_benefits_paid,
            'net_cash_generated_from_operations': net_cash_generated_from_operations,
            'prior_net_cash_generated_from_operations': prior_net_cash_generated_from_operations,
            'current_property': current_property,
            'prior_property': prior_property,
            'current_long_term_investments': current_long_term_investments,
            'prior_long_term_investments': prior_long_term_investments,
            'investing_activity_cashflow': investing_activity_cashflow,
            'prior_investing_activity_cashflow': prior_investing_activity_cashflow,
            'non_current_asset_cashflow': non_current_asset_cashflow,
            'prior_non_current_asset_cashflow': prior_non_current_asset_cashflow,
            'current_intangible_assets': current_intangible_assets,
            'prior_intangible_assets': prior_intangible_assets,
            'net_cash_generated_from_investing_activities': net_cash_generated_from_investing_activities,
            'prior_net_cash_generated_from_investing_activities': prior_net_cash_generated_from_investing_activities,
            'paid_up_capital': paid_up_capital,
            'prior_paid_up_capital': prior_paid_up_capital,
            'dividend_paid': dividend_paid,
            'prior_dividend_paid': prior_dividend_paid,
            'owner_current_account': owner_current_account,
            'prior_owner_current_account': prior_owner_current_account,
            'related_party_loan': related_party_loan,
            'prior_related_party_loan': prior_related_party_loan,
            'financing_activity_cashflow': financing_activity_cashflow,
            'prior_financing_activity_cashflow': prior_financing_activity_cashflow,
            'non_current_liability_cashflow': non_current_liability_cashflow,
            'prior_non_current_liability_cashflow': prior_non_current_liability_cashflow,
            'deposit_cashflow': deposit_cashflow,
            'prior_deposit_cashflow': prior_deposit_cashflow,
            'interest_paid': interest_paid,
            'prior_interest_paid': prior_interest_paid,
            'security_deposit': security_deposit,
            'prior_security_deposit': prior_security_deposit,
            'net_cash_generated_from_financing_activities': net_cash_generated_from_financing_activities,
            'prior_net_cash_generated_from_financing_activities': prior_net_cash_generated_from_financing_activities,
            'net_cash_and_cash_equivalents': net_cash_and_cash_equivalents,
            'prior_net_cash_and_cash_equivalents': prior_net_cash_and_cash_equivalents,
            'cash_beginning_year': cash_beginning_year,
            'cash_end_of_year': cash_end_of_year,
            'prior_cash_beginning_year': prior_cash_beginning_year,
            'prior_cash_end_of_year': prior_cash_end_of_year,

            # Notes
            'show_other_matter': show_other_matter,
            'other_matter_paragraph': other_matter_paragraph,
            'other_matter_company_name': other_matter_company_name,
            'other_matter_date_display': other_matter_date_display,
            'other_matter_period_word': other_matter_period_word,
            'show_emphasis_of_matter': show_emphasis_of_matter,
            'emphasis_note_items': emphasis_note_items,
            'emphasis_note_lines': emphasis_note_lines,
            'ppe_note_number': ppe_note_number,
            'ppe_note_columns': ppe_note_columns,
            'ppe_note_schedules': ppe_note_schedules,
            'intangible_note_number': intangible_note_number,
            'intangible_note_columns': intangible_note_columns,
            'intangible_note_schedules': intangible_note_schedules,
            'note_numbers': note_numbers,
            'note_sections': note_sections,
            'last_note_number': last_note_number,
            'dmcc_sheet_data': dmcc_sheet_data,
            }


    @staticmethod
    def _normalize_account_code(code):
        return ''.join(ch for ch in (code or '') if ch.isdigit())

    @staticmethod
    def _to_float(value):
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _get_liquidation_going_concern_paragraphs(self):
        self.ensure_one()
        year = int(
            self.replace_going_concern_year
            or (LEGACY_LIQUIDATION_GOING_CONCERN_YEAR if self.replace_going_concern_paragraph else 0)
        )
        return tuple(
            paragraph.format(year=year)
            for paragraph in LIQUIDATION_GOING_CONCERN_PARAGRAPH_TEMPLATES
        )

    @staticmethod
    def _round_half_up_down(value, digits=0):
        # Custom "half_up_down" rule:
        # fraction < 0.5 => round down, fraction >= 0.5 => round up.
        # Applied on absolute value and sign restored.
        try:
            decimal_value = Decimal(str(value or 0.0))
        except (TypeError, ValueError, ArithmeticError):
            decimal_value = Decimal('0')
        precision = max(int(digits or 0), 0)
        factor = Decimal('1').scaleb(precision)
        scaled_abs = abs(decimal_value) * factor
        whole_part = Decimal(int(scaled_abs))
        fraction_part = scaled_abs - whole_part
        if fraction_part >= Decimal('0.5'):
            whole_part += Decimal('1')
        rounded_abs = whole_part / factor
        return float(-rounded_abs if decimal_value < 0 else rounded_abs)

    @classmethod
    def _round_amount(cls, value, digits=0):
        return cls._round_half_up_down(value, digits=digits)

    def _round_account_row_amounts(self, row):
        rounded = self._normalize_account_row(row)
        rounded['initial_balance'] = self._round_amount(rounded.get('initial_balance'))
        rounded['debit'] = self._round_amount(rounded.get('debit'))
        rounded['credit'] = self._round_amount(rounded.get('credit'))
        rounded['movement_balance'] = self._round_amount(rounded.get('movement_balance'))
        rounded['end_balance'] = self._round_amount(rounded.get('end_balance'))
        return self._normalize_account_row(
            rounded,
            balance_role=rounded.get('balance_role'),
        )

    def _round_account_rows_for_reporting(self, rows):
        self.ensure_one()
        # Round each source account row before building prefix/group totals so
        # subtotals follow the displayed account figures instead of raw floats.
        return [
            self._round_account_row_amounts(row)
            for row in (rows or [])
        ]

    def _convert_tb_row_to_usd(self, row, conversion_rate):
        converted = self._normalize_account_row(row)
        rate = self._to_float(conversion_rate)
        if rate <= 0.0:
            return converted
        converted['initial_balance'] = self._to_float(converted.get('initial_balance')) / rate
        converted['debit'] = self._to_float(converted.get('debit')) / rate
        converted['credit'] = self._to_float(converted.get('credit')) / rate
        converted['movement_balance'] = self._to_float(converted.get('movement_balance')) / rate
        converted['end_balance'] = self._to_float(converted.get('end_balance')) / rate
        return self._normalize_account_row(
            converted,
            balance_role=converted.get('balance_role'),
        )

    @staticmethod
    def _sum_prefix_balances(balance_by_code, *prefixes):
        return sum(
            amount
            for code, amount in (balance_by_code or {}).items()
            if any((code or '').startswith(prefix) for prefix in prefixes)
        )

    @staticmethod
    def _clear_rows(ws, start_row, end_row, min_col, max_col):
        for row in range(start_row, end_row + 1):
            for col in range(min_col, max_col + 1):
                ws.cell(row=row, column=col, value=None)

    def action_print_account_report_lines(self):
        """Generate and display report"""
        self.ensure_one()
        self._validate_emphasis_options()

        if self.use_previous_settings:
            self._store_previous_settings()

        # report_data = self._get_report_data()
        # You can now pass `report_data` to your Word/PDF renderer

        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/view/{self.id}',
            'target': 'new',
        } 

    def _get_saved_document_name(self):
        self.ensure_one()
        report_type_label = dict(self._fields['report_type'].selection).get(self.report_type, self.report_type or '')
        company_name = self.company_id.name or 'Company'
        end_date_label = self.date_end.strftime('%d %B %Y') if self.date_end else ''
        name = f"{company_name} - {report_type_label} {end_date_label}".strip()
        return name or f"Audit Report {self.id}"

    def _get_wizard_snapshot_json(self):
        self.ensure_one()
        tb_overrides_json = self._sync_tb_overrides_json()
        lor_extra_items_json = self._sync_lor_extra_items_json()
        related_party_rows = self._serialize_related_party_rows_payload()
        correction_error_rows = self._serialize_correction_error_rows_payload()
        first_related_party_row = (
            related_party_rows[0]
            if related_party_rows
            else self._blank_related_party_row_payload()
        )
        snapshot = {
            'wizard_id': self.id,
            'company_id': self.company_id.id,
            'date_start': self.date_start.isoformat() if self.date_start else False,
            'date_end': self.date_end.isoformat() if self.date_end else False,
            'balance_sheet_date_mode': self.balance_sheet_date_mode,
            'prior_balance_sheet_date_mode': self.prior_balance_sheet_date_mode,
            'report_type': self.report_type,
            'audit_period_category': self.audit_period_category,
            'portal_account_no': self.portal_account_no or False,
            'prior_year_mode': self.prior_year_mode,
            'prior_date_start': self.prior_date_start.isoformat() if self.prior_date_start else False,
            'prior_date_end': self.prior_date_end.isoformat() if self.prior_date_end else False,
            'soce_prior_opening_label_date': (
                self.soce_prior_opening_label_date.isoformat()
                if self.soce_prior_opening_label_date else False
            ),
            'show_related_parties_note': self.show_related_parties_note,
            'show_shareholder_note': self.show_shareholder_note,
            'show_other_comprehensive_income_page': self.show_other_comprehensive_income_page,
            'business_activity_include_services': self.business_activity_include_services,
            'business_activity_include_providing': self.business_activity_include_providing,
            'show_ct_first_tax_year_line': self.show_ct_first_tax_year_line,
            'show_unaudited_prior_year': bool(self.show_unaudited_prior_year),
            'usd_statement': bool(self.usd_statement),
            'draft_watermark': bool(self.draft_watermark),
            'ignore_notes_last_page_margins': bool(self.ignore_notes_last_page_margins),
            'show_investment_note_schedule': bool(self.show_investment_note_schedule),
            'signature_date_mode': self.signature_date_mode,
            'signature_manual_date': (
                self.signature_manual_date.isoformat() if self.signature_manual_date else False
            ),
            'share_capital_paid_status': self.share_capital_paid_status,
            'show_share_capital_conversion_note': self.show_share_capital_conversion_note,
            'share_conversion_currency': self.share_conversion_currency,
            'share_conversion_original_value': self.share_conversion_original_value,
            'share_conversion_exchange_rate': self.share_conversion_exchange_rate,
            'show_share_capital_transfer_note': self.show_share_capital_transfer_note,
            'share_transfer_date': self.share_transfer_date.isoformat() if self.share_transfer_date else False,
            'share_transfer_from': self.share_transfer_from,
            'share_transfer_shares': self.share_transfer_shares,
            'share_transfer_percentage': self.share_transfer_percentage,
            'share_transfer_to': self.share_transfer_to,
            'related_party_rows': related_party_rows,
            'related_party_name': first_related_party_row.get('name') or False,
            'related_party_relationship': first_related_party_row.get('relationship') or False,
            'related_party_transaction': first_related_party_row.get('transaction') or False,
            'related_party_amount': self._to_float(first_related_party_row.get('amount')),
            'related_party_amount_prior': self._to_float(first_related_party_row.get('amount_prior')),
            'correction_error_note_body': self.correction_error_note_body or False,
            'correction_error_rows': correction_error_rows,
            'emphasis_change_period': bool(self.emphasis_change_period),
            'emphasis_correction_error': bool(self.emphasis_correction_error),
            'emphasis_change_from_date': (
                self.emphasis_change_from_date.isoformat() if self.emphasis_change_from_date else False
            ),
            'emphasis_change_to_date': (
                self.emphasis_change_to_date.isoformat() if self.emphasis_change_to_date else False
            ),
            'additional_note_legal_status_change': bool(self.additional_note_legal_status_change),
            'additional_note_no_active_bank_account': bool(self.additional_note_no_active_bank_account),
            'additional_note_business_bank_account_opened': bool(self.additional_note_business_bank_account_opened),
            'emphasis_legal_change_date': (
                self.emphasis_legal_change_date.isoformat() if self.emphasis_legal_change_date else False
            ),
            'emphasis_legal_status_from': self.emphasis_legal_status_from or False,
            'emphasis_legal_status_to': self.emphasis_legal_status_to or False,
            'tb_include_zero_accounts': bool(self.tb_include_zero_accounts),
            'tb_enable_date_navigator': bool(self.tb_enable_date_navigator),
            'tb_browser_active_period': self.tb_browser_active_period or 'current',
            'tb_current_report_options_json': self.tb_current_report_options_json or False,
            'tb_prior_report_options_json': self.tb_prior_report_options_json or False,
            'tb_convert_balances_to_usd': bool(self.tb_convert_balances_to_usd),
            'tb_usd_conversion_rate': self.tb_usd_conversion_rate,
            'replace_aed_text_with_usd': bool(self.replace_aed_text_with_usd),
            'replace_going_concern_paragraph': bool(self.replace_going_concern_paragraph),
            'replace_going_concern_year': self.replace_going_concern_year or False,
            'tb_overrides_json': tb_overrides_json,
            'lor_extra_items_json': lor_extra_items_json,
            'tb_diff_current': self._to_float(self.tb_diff_current),
            'tb_diff_prior': self._to_float(self.tb_diff_prior),
            'tb_warning_current': self.tb_warning_current or False,
            'tb_warning_prior': self.tb_warning_prior or False,
            'generated_by_user_id': self.env.user.id,
        }
        for i in range(1, 11):
            snapshot[f'signature_include_{i}'] = bool(getattr(self, f'signature_include_{i}'))
            snapshot[f'signature_role_{i}'] = getattr(self, f'signature_role_{i}') or (
                'primary' if i == 1 else 'secondary'
            )
            snapshot[f'director_include_{i}'] = bool(getattr(self, f'director_include_{i}'))
            snapshot[f'owner_include_{i}'] = bool(getattr(self, f'owner_include_{i}'))
        return json.dumps(snapshot)

    @api.model
    def _build_wizard_vals_from_snapshot(self, snapshot_data):
        snapshot = snapshot_data if isinstance(snapshot_data, dict) else {}
        if not snapshot:
            return {}

        field_names = [
            'company_id',
            'date_start',
            'date_end',
            'balance_sheet_date_mode',
            'prior_year_mode',
            'prior_balance_sheet_date_mode',
            'prior_date_start',
            'prior_date_end',
            'soce_prior_opening_label_date',
            'report_type',
            'audit_period_category',
            'portal_account_no',
            'show_related_parties_note',
            'show_shareholder_note',
            'show_other_comprehensive_income_page',
            'business_activity_include_services',
            'business_activity_include_providing',
            'show_ct_first_tax_year_line',
            'show_unaudited_prior_year',
            'usd_statement',
            'draft_watermark',
            'ignore_notes_last_page_margins',
            'show_investment_note_schedule',
            'share_capital_paid_status',
            'show_share_capital_conversion_note',
            'share_conversion_currency',
            'share_conversion_original_value',
            'share_conversion_exchange_rate',
            'show_share_capital_transfer_note',
            'share_transfer_date',
            'share_transfer_from',
            'share_transfer_shares',
            'share_transfer_percentage',
            'share_transfer_to',
            'tb_include_zero_accounts',
            'tb_enable_date_navigator',
            'tb_browser_active_period',
            'tb_current_report_options_json',
            'tb_prior_report_options_json',
            'tb_convert_balances_to_usd',
            'tb_usd_conversion_rate',
            'replace_aed_text_with_usd',
            'lor_extra_items_json',
            'gap_report_of_directors',
            'gap_independent_auditor_report',
            'gap_notes_to_financial_statements',
            'signature_break_lines_report_of_directors',
            'signature_break_lines_balance_sheet',
            'signature_break_lines_profit_loss',
            'signature_break_lines_changes_in_equity',
            'signature_break_lines_cash_flows',
            'signature_break_lines_notes',
            'signature_date_mode',
            'signature_manual_date',
            'related_party_name',
            'related_party_relationship',
            'related_party_transaction',
            'related_party_amount',
            'related_party_amount_prior',
            'correction_error_note_body',
            'emphasis_change_period',
            'emphasis_correction_error',
            'replace_going_concern_paragraph',
            'replace_going_concern_year',
            'emphasis_change_from_date',
            'emphasis_change_to_date',
            'additional_note_legal_status_change',
            'additional_note_no_active_bank_account',
            'additional_note_business_bank_account_opened',
            'emphasis_legal_change_date',
            'emphasis_legal_status_from',
            'emphasis_legal_status_to',
        ]
        for idx in range(1, 11):
            field_names.extend([
                f'signature_include_{idx}',
                f'signature_role_{idx}',
                f'director_include_{idx}',
                f'owner_include_{idx}',
            ])

        vals = {}
        for field_name in field_names:
            if field_name not in snapshot or field_name not in self._fields:
                continue
            field = self._fields[field_name]
            raw_value = snapshot.get(field_name)
            if field.type == 'date':
                vals[field_name] = fields.Date.to_date(raw_value) if raw_value else False
            elif field.type == 'many2one':
                try:
                    vals[field_name] = int(raw_value) if raw_value else False
                except (TypeError, ValueError):
                    vals[field_name] = False
            elif field.type == 'boolean':
                vals[field_name] = bool(raw_value)
            elif field.type == 'integer':
                try:
                    vals[field_name] = int(raw_value or 0)
                except (TypeError, ValueError):
                    vals[field_name] = 0
            elif field.type == 'float':
                vals[field_name] = self._to_float(raw_value)
            else:
                vals[field_name] = raw_value if raw_value is not None else False
        vals['related_party_line_ids'] = self._related_party_rows_to_commands(
            self._resolve_related_party_rows_payload(
                snapshot,
                include_blank=True,
            )
        )
        vals['correction_error_line_ids'] = self._correction_error_rows_to_commands(
            self._resolve_correction_error_rows_payload(snapshot)
        )

        if vals.get('replace_going_concern_paragraph') and not vals.get('replace_going_concern_year'):
            vals['replace_going_concern_year'] = LEGACY_LIQUIDATION_GOING_CONCERN_YEAR
        return vals

    def _get_target_revision_for_apply(self):
        self.ensure_one()
        revision_id = self.env.context.get('audit_target_revision_id') or self.audit_target_revision_id.id
        if not revision_id:
            raise ValidationError("No target revision selected.")

        revision = self.env['audit.report.revision'].browse(int(revision_id))
        if not revision.exists():
            raise ValidationError("The selected revision no longer exists.")
        revision._ensure_active_company()
        if revision.company_id != self.company_id:
            raise ValidationError("Wizard company must match the target revision company.")
        return revision

    def _persist_revision_settings_changes(self, revision, force_new_revision=False):
        self.ensure_one()

        self._validate_emphasis_options()
        if self.use_previous_settings:
            self._store_previous_settings()

        from ..controllers.main import AuditReportController

        controller = AuditReportController()
        templates_path = controller._templates_path()
        template_env = controller._get_template_env(templates_path)
        css_content = controller._get_cached_css_content(controller._css_path())

        report_data = self._get_report_data()
        try:
            toc_entries = controller._compute_toc_entries(
                self,
                report_data=report_data,
                template_env=template_env,
                css_content=css_content,
            )
        except Exception:
            toc_entries = None

        html_with_style = controller._render_report_html(
            self,
            toc_entries=toc_entries,
            report_data=report_data,
            template_env=template_env,
            css_content=css_content,
        )
        if not html_with_style:
            raise ValidationError("Unable to render report HTML while applying revision changes.")

        prepared_html = revision.prepare_edited_html_for_storage(html_with_style)
        tb_overrides_json = self._sync_tb_overrides_json()
        lor_extra_items_json = self._sync_lor_extra_items_json()
        target_revision, _save_state = revision.persist_session_revision_changes(
            prepared_html,
            tb_overrides_json=tb_overrides_json,
            lor_extra_items_json=lor_extra_items_json,
            wizard_snapshot_json=self._get_wizard_snapshot_json(),
            force_new_revision=force_new_revision,
        )
        return target_revision

    def action_apply_revision_changes_to_revision(self):
        self.ensure_one()
        revision = self._get_target_revision_for_apply()
        target_revision = self._persist_revision_settings_changes(revision, force_new_revision=False)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Report Revision',
            'res_model': 'audit.report.revision',
            'view_mode': 'form',
            'res_id': target_revision.id,
            'target': 'current',
        }

    def action_apply_revision_changes_as_new_revision(self):
        self.ensure_one()
        revision = self._get_target_revision_for_apply()
        target_revision = self._persist_revision_settings_changes(revision, force_new_revision=True)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Report Revision',
            'res_model': 'audit.report.revision',
            'view_mode': 'form',
            'res_id': target_revision.id,
            'target': 'current',
        }

    def action_apply_tb_overrides_to_revision(self):
        return self.action_apply_revision_changes_to_revision()

    def action_save_editable_report(self):
        """Create a company-scoped saved report document and initial revision."""
        self.ensure_one()
        self._validate_emphasis_options()
        flow_started = time.perf_counter()

        if self.use_previous_settings:
            self._store_previous_settings()

        from ..controllers.main import AuditReportController

        controller = AuditReportController()
        templates_path = controller._templates_path()
        template_env = controller._get_template_env(templates_path)
        css_content = controller._get_cached_css_content(controller._css_path())

        report_data_started = time.perf_counter()
        report_data = self._get_report_data()
        _logger.debug(
            "AUDIT_PERF action_save_editable_report wizard_id=%s stage=report_data elapsed_ms=%.2f",
            self.id,
            (time.perf_counter() - report_data_started) * 1000.0,
        )

        toc_started = time.perf_counter()
        try:
            toc_entries = controller._compute_toc_entries(
                self,
                report_data=report_data,
                template_env=template_env,
                css_content=css_content,
            )
        except Exception:
            toc_entries = None
        _logger.debug(
            "AUDIT_PERF action_save_editable_report wizard_id=%s stage=toc elapsed_ms=%.2f",
            self.id,
            (time.perf_counter() - toc_started) * 1000.0,
        )

        html_started = time.perf_counter()
        html_with_style = controller._render_report_html(
            self,
            toc_entries=toc_entries,
            report_data=report_data,
            template_env=template_env,
            css_content=css_content,
        )
        _logger.debug(
            "AUDIT_PERF action_save_editable_report wizard_id=%s stage=html elapsed_ms=%.2f",
            self.id,
            (time.perf_counter() - html_started) * 1000.0,
        )
        if not html_with_style:
            raise ValidationError("Unable to render report HTML for saving.")
        tb_overrides_json = self._sync_tb_overrides_json()
        lor_extra_items_json = self._sync_lor_extra_items_json()

        wizard_snapshot_json = self._get_wizard_snapshot_json()
        document = self.env['audit.report.document'].create({
            'name': self._get_saved_document_name(),
            'company_id': self.company_id.id,
            'date_start': self.date_start,
            'date_end': self.date_end,
            'report_type': self.report_type,
            'audit_period_category': self.audit_period_category,
            'source_wizard_json': wizard_snapshot_json,
            'tb_overrides_json': tb_overrides_json,
            'lor_extra_items_json': lor_extra_items_json,
        })
        revision = document.create_revision_from_html(
            html_with_style,
            tb_overrides_json=tb_overrides_json,
            lor_extra_items_json=lor_extra_items_json,
            wizard_snapshot_json=wizard_snapshot_json,
        )
        pdf_started = time.perf_counter()
        generate_initial_pdf = bool(self.env.context.get('audit_generate_initial_pdf'))
        if generate_initial_pdf:
            revision._get_pdf_content(pre_rendered_html=html_with_style, refresh_toc=False)
        pdf_elapsed_ms = (time.perf_counter() - pdf_started) * 1000.0
        _logger.debug(
            "AUDIT_PERF action_save_editable_report wizard_id=%s stage=pdf elapsed_ms=%.2f skipped=%s total_elapsed_ms=%.2f",
            self.id,
            pdf_elapsed_ms,
            not generate_initial_pdf,
            (time.perf_counter() - flow_started) * 1000.0,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Saved Audit Report',
            'res_model': 'audit.report.document',
            'view_mode': 'form',
            'res_id': document.id,
            'target': 'current',
        }

    def action_print_account_report_pdf(self):
        """Generate and display report as server-side PDF (headless Chrome)."""
        self.ensure_one()
        self._validate_emphasis_options()

        period_category = (self.audit_period_category or '').lower()
        if not period_category.endswith('_1y'):
            return self._action_open_soce_pdf_confirmation()

        if self.use_previous_settings:
            self._store_previous_settings()

        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/pdf/{self.id}',
            'target': 'new',
        }


class AuditReportSocePdfConfirmation(models.TransientModel):
    _name = 'audit.report.soce.pdf.confirmation'
    _description = 'Review SOCE Date Before PDF Generation'

    report_id = fields.Many2one(
        'audit.report',
        string='Audit Report',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    soce_prior_opening_label_date = fields.Date(
        string='SOCE First Balance Date',
        related='report_id.soce_prior_opening_label_date',
        readonly=True,
    )
    confirmation_message = fields.Text(
        string='Confirmation',
        compute='_compute_confirmation_message',
        readonly=True,
    )

    @api.depends('soce_prior_opening_label_date')
    def _compute_confirmation_message(self):
        for wizard in self:
            date_label = (
                fields.Date.to_string(wizard.soce_prior_opening_label_date)
                if wizard.soce_prior_opening_label_date else ''
            )
            wizard.confirmation_message = _(
                "Please review the SOCE first balance date before generating the PDF.\n\n"
                "The Statement of Changes in Equity will use this date for the first "
                "balance label: %(date_label)s\n\n"
                "Click Generate PDF only if this date is correct."
            ) % {'date_label': date_label}

    def action_confirm_print_pdf(self):
        self.ensure_one()
        report = self.report_id
        report._validate_emphasis_options()

        if report.use_previous_settings:
            report._store_previous_settings()

        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/pdf/{report.id}',
            'target': 'new',
        }

    def action_back_to_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Account Report'),
            'res_model': 'audit.report',
            'res_id': self.report_id.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'dialog_size': 'extra-large',
                'form_view_initial_mode': 'edit',
            },
        }
