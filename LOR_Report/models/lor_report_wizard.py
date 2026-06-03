from datetime import date as datetime_date

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LorReportWizard(models.TransientModel):
    _name = 'lor.report.wizard'
    _description = 'Letter of Representation Wizard'

    SIGNATURE_INCLUDE_FIELD_NAMES = [f'signature_include_{index}' for index in range(1, 11)]
    SHAREHOLDER_FIELD_NAMES = [f'shareholder_{index}' for index in range(1, 11)]
    NATIONALITY_FIELD_NAMES = [f'nationality_{index}' for index in range(1, 11)]
    NUMBER_OF_SHARES_FIELD_NAMES = [f'number_of_shares_{index}' for index in range(1, 11)]
    SHARE_VALUE_FIELD_NAMES = [f'share_value_{index}' for index in range(1, 11)]
    INSTANT_SHAREHOLDER_SYNC_FIELD_NAMES = [
        'share_capital_paid_status',
        *SIGNATURE_INCLUDE_FIELD_NAMES,
        *SHAREHOLDER_FIELD_NAMES,
        *NATIONALITY_FIELD_NAMES,
        *NUMBER_OF_SHARES_FIELD_NAMES,
        *SHARE_VALUE_FIELD_NAMES,
    ]

    SHARE_CAPITAL_PAID_STATUS_SELECTION = [
        ('paid', 'Paid'),
        ('unpaid', 'Unpaid'),
    ]
    SIGNATURE_DATE_MODE_SELECTION = [
        ('auto', 'Auto (generation day)'),
        ('manual', 'Manual date'),
    ]

    audit_report_id = fields.Many2one(
        'audit.report',
        string='Audit Report',
        default=lambda self: self._default_audit_report_id(),
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self._default_company_id(),
    )
    company_name = fields.Char(related='company_id.name', readonly=False)
    company_street = fields.Char(related='company_id.street', readonly=False)
    company_street2 = fields.Char(related='company_id.street2', readonly=False)
    company_city = fields.Char(related='company_id.city', readonly=False)
    company_state_id = fields.Many2one(related='company_id.state_id', readonly=False)
    company_zip = fields.Char(related='company_id.zip', readonly=False)
    company_country_id = fields.Many2one(related='company_id.country_id', readonly=False)
    company_free_zone = fields.Selection(related='company_id.free_zone', readonly=False)
    share_capital_paid_status = fields.Selection(
        SHARE_CAPITAL_PAID_STATUS_SELECTION,
        string='Share capital status',
        default='paid',
    )
    company_license_number = fields.Char(
        related='company_id.company_license_number',
        readonly=False,
    )
    trade_license_activities = fields.Text(
        related='company_id.trade_license_activities',
        readonly=False,
    )
    incorporation_date = fields.Date(related='company_id.incorporation_date', readonly=False)
    corporate_tax_registration_number = fields.Char(
        related='company_id.corporate_tax_registration_number',
        readonly=False,
    )
    vat_registration_number = fields.Char(
        related='company_id.vat_registration_number',
        readonly=False,
    )
    corporate_tax_start_date = fields.Date(
        related='company_id.corporate_tax_start_date',
        readonly=False,
    )
    corporate_tax_end_date = fields.Date(
        related='company_id.corporate_tax_end_date',
        readonly=False,
    )
    implementing_regulations_freezone = fields.Text(
        related='company_id.implementing_regulations_freezone',
        readonly=False,
    )
    shareholder_1 = fields.Char(related='company_id.shareholder_1', readonly=False)
    shareholder_2 = fields.Char(related='company_id.shareholder_2', readonly=False)
    shareholder_3 = fields.Char(related='company_id.shareholder_3', readonly=False)
    shareholder_4 = fields.Char(related='company_id.shareholder_4', readonly=False)
    shareholder_5 = fields.Char(related='company_id.shareholder_5', readonly=False)
    shareholder_6 = fields.Char(related='company_id.shareholder_6', readonly=False)
    shareholder_7 = fields.Char(related='company_id.shareholder_7', readonly=False)
    shareholder_8 = fields.Char(related='company_id.shareholder_8', readonly=False)
    shareholder_9 = fields.Char(related='company_id.shareholder_9', readonly=False)
    shareholder_10 = fields.Char(related='company_id.shareholder_10', readonly=False)
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
    nationality_1 = fields.Selection(related='company_id.nationality_1', readonly=False)
    nationality_2 = fields.Selection(related='company_id.nationality_2', readonly=False)
    nationality_3 = fields.Selection(related='company_id.nationality_3', readonly=False)
    nationality_4 = fields.Selection(related='company_id.nationality_4', readonly=False)
    nationality_5 = fields.Selection(related='company_id.nationality_5', readonly=False)
    nationality_6 = fields.Selection(related='company_id.nationality_6', readonly=False)
    nationality_7 = fields.Selection(related='company_id.nationality_7', readonly=False)
    nationality_8 = fields.Selection(related='company_id.nationality_8', readonly=False)
    nationality_9 = fields.Selection(related='company_id.nationality_9', readonly=False)
    nationality_10 = fields.Selection(related='company_id.nationality_10', readonly=False)
    number_of_shares_1 = fields.Integer(related='company_id.number_of_shares_1', readonly=False)
    number_of_shares_2 = fields.Integer(related='company_id.number_of_shares_2', readonly=False)
    number_of_shares_3 = fields.Integer(related='company_id.number_of_shares_3', readonly=False)
    number_of_shares_4 = fields.Integer(related='company_id.number_of_shares_4', readonly=False)
    number_of_shares_5 = fields.Integer(related='company_id.number_of_shares_5', readonly=False)
    number_of_shares_6 = fields.Integer(related='company_id.number_of_shares_6', readonly=False)
    number_of_shares_7 = fields.Integer(related='company_id.number_of_shares_7', readonly=False)
    number_of_shares_8 = fields.Integer(related='company_id.number_of_shares_8', readonly=False)
    number_of_shares_9 = fields.Integer(related='company_id.number_of_shares_9', readonly=False)
    number_of_shares_10 = fields.Integer(related='company_id.number_of_shares_10', readonly=False)
    share_value_1 = fields.Float(related='company_id.share_value_1', readonly=False)
    share_value_2 = fields.Float(related='company_id.share_value_2', readonly=False)
    share_value_3 = fields.Float(related='company_id.share_value_3', readonly=False)
    share_value_4 = fields.Float(related='company_id.share_value_4', readonly=False)
    share_value_5 = fields.Float(related='company_id.share_value_5', readonly=False)
    share_value_6 = fields.Float(related='company_id.share_value_6', readonly=False)
    share_value_7 = fields.Float(related='company_id.share_value_7', readonly=False)
    share_value_8 = fields.Float(related='company_id.share_value_8', readonly=False)
    share_value_9 = fields.Float(related='company_id.share_value_9', readonly=False)
    share_value_10 = fields.Float(related='company_id.share_value_10', readonly=False)
    total_share_1 = fields.Float(related='company_id.total_share_1', readonly=True)
    total_share_2 = fields.Float(related='company_id.total_share_2', readonly=True)
    total_share_3 = fields.Float(related='company_id.total_share_3', readonly=True)
    total_share_4 = fields.Float(related='company_id.total_share_4', readonly=True)
    total_share_5 = fields.Float(related='company_id.total_share_5', readonly=True)
    total_share_6 = fields.Float(related='company_id.total_share_6', readonly=True)
    total_share_7 = fields.Float(related='company_id.total_share_7', readonly=True)
    total_share_8 = fields.Float(related='company_id.total_share_8', readonly=True)
    total_share_9 = fields.Float(related='company_id.total_share_9', readonly=True)
    total_share_10 = fields.Float(related='company_id.total_share_10', readonly=True)
    date_start = fields.Date(string='Date Start')
    manager_name_display = fields.Char(
        string='Manager Names',
        compute='_compute_manager_name_display',
    )
    date_end = fields.Date(
        string='Date End',
        required=True,
        default=lambda self: self._default_date_end(),
    )
    signature_date_mode = fields.Selection(
        SIGNATURE_DATE_MODE_SELECTION,
        string='Signature placeholder date',
        required=True,
        default='auto',
    )
    signature_manual_date = fields.Date(string='Manual signature date')
    extra_item_line_ids = fields.One2many(
        'lor.report.extra.line',
        'wizard_id',
        string='Append Main List Items at End',
        copy=False,
    )

    @api.model
    def _default_company_id(self):
        return self.env.context.get('default_company_id') or self.env.company.id

    @api.model
    def _default_date_end(self):
        audit_report = self.env['audit.report'].browse(
            self.env.context.get('default_audit_report_id')
        ).exists()
        if audit_report and audit_report.date_end:
            return audit_report.date_end
        return fields.Date.context_today(self)

    @api.model
    def _find_latest_audit_report(self, company):
        if not company:
            return self.env['audit.report']
        return self.env['audit.report'].search(
            [('company_id', '=', company.id)],
            order='write_date desc, create_date desc, id desc',
            limit=1,
        )

    @api.model
    def _default_audit_report_id(self):
        audit_report = self.env['audit.report'].browse(
            self.env.context.get('default_audit_report_id')
        ).exists()
        if audit_report:
            return audit_report.id

        company = self.env['res.company'].browse(self._default_company_id()).exists()
        return self._find_latest_audit_report(company).id or False

    @api.model
    def _map_audit_signature_date_mode(self, mode):
        return 'manual' if (mode or '').strip().lower() == 'manual' else 'auto'

    @staticmethod
    def _signature_field_names():
        return list(LorReportWizard.SIGNATURE_INCLUDE_FIELD_NAMES)

    @staticmethod
    def _company_text_shareholder_field_names():
        return (
            list(LorReportWizard.SHAREHOLDER_FIELD_NAMES)
            + list(LorReportWizard.NATIONALITY_FIELD_NAMES)
        )

    @staticmethod
    def _company_integer_shareholder_field_names():
        return list(LorReportWizard.NUMBER_OF_SHARES_FIELD_NAMES)

    @staticmethod
    def _company_float_shareholder_field_names():
        return list(LorReportWizard.SHARE_VALUE_FIELD_NAMES)

    @api.model
    def _default_date_start_for_end_date(self, end_date):
        end_date = fields.Date.to_date(end_date) if end_date else fields.Date.context_today(self)
        if not end_date:
            return False
        return datetime_date(end_date.year, 1, 1)

    def _get_lor_defaults_from_audit_report(self, audit_report):
        values = {}
        if not audit_report:
            return values

        values.update({
            'date_start': audit_report.date_start or self._default_date_start_for_end_date(audit_report.date_end),
            'date_end': audit_report.date_end or fields.Date.context_today(self),
            'share_capital_paid_status': audit_report.share_capital_paid_status or 'paid',
            'signature_date_mode': self._map_audit_signature_date_mode(audit_report.signature_date_mode),
            'signature_manual_date': audit_report.signature_manual_date,
        })
        for field_name in self._signature_field_names():
            values[field_name] = getattr(audit_report, field_name, False)
        return values

    def _apply_audit_report_defaults(self, audit_report):
        self.ensure_one()
        self.audit_report_id = audit_report
        values = self._get_lor_defaults_from_audit_report(audit_report)
        if values:
            for field_name, value in values.items():
                setattr(self, field_name, value)
        else:
            if not self.date_end:
                self.date_end = fields.Date.context_today(self)
            if not self.date_start and self.date_end:
                self.date_start = self._default_date_start_for_end_date(self.date_end)
            if not self.share_capital_paid_status:
                self.share_capital_paid_status = getattr(self.company_id, 'company_share', False) or 'paid'
            if not self.signature_date_mode:
                self.signature_date_mode = 'auto'
            if self.signature_date_mode != 'manual':
                self.signature_manual_date = False

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)

        audit_report = self.env['audit.report'].browse(
            defaults.get('audit_report_id') or self.env.context.get('default_audit_report_id')
        ).exists()
        company_id = defaults.get('company_id') or self._default_company_id()

        if audit_report and audit_report.company_id:
            company_id = audit_report.company_id.id
        elif company_id:
            company = self.env['res.company'].browse(company_id).exists()
            audit_report = self._find_latest_audit_report(company)

        if company_id:
            defaults['company_id'] = company_id
        if audit_report:
            defaults['audit_report_id'] = audit_report.id
            for field_name, value in self._get_lor_defaults_from_audit_report(audit_report).items():
                if not fields_list or field_name in fields_list:
                    defaults[field_name] = value
        else:
            defaults.setdefault(
                'date_end',
                fields.Date.context_today(self),
            )
            defaults.setdefault(
                'date_start',
                self._default_date_start_for_end_date(defaults.get('date_end')),
            )
            defaults.setdefault(
                'share_capital_paid_status',
                (
                    self.env['res.company'].browse(company_id).exists().company_share
                    if company_id and self.env['res.company'].browse(company_id).exists()
                    else 'paid'
                ) or 'paid',
            )
            defaults.setdefault('signature_date_mode', 'auto')
        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            current_vals = dict(vals)

            audit_report = self.env['audit.report'].browse(
                current_vals.get('audit_report_id') or self.env.context.get('default_audit_report_id')
            ).exists()
            company = self.env['res.company'].browse(
                current_vals.get('company_id') or self.env.context.get('default_company_id')
            ).exists()

            if audit_report and audit_report.company_id and not company:
                company = audit_report.company_id
                current_vals['company_id'] = company.id

            if not audit_report:
                company = company or self.env['res.company'].browse(self._default_company_id()).exists()
                audit_report = self._find_latest_audit_report(company)
                if audit_report:
                    current_vals.setdefault('audit_report_id', audit_report.id)
                    current_vals.setdefault('company_id', audit_report.company_id.id)
            if audit_report:
                for field_name, value in self._get_lor_defaults_from_audit_report(audit_report).items():
                    current_vals.setdefault(field_name, value)
            else:
                date_end = current_vals.get('date_end') or fields.Date.context_today(self)
                current_vals.setdefault('date_end', date_end)
                current_vals.setdefault(
                    'date_start',
                    self._default_date_start_for_end_date(date_end),
                )
                current_vals.setdefault(
                    'share_capital_paid_status',
                    (getattr(company, 'company_share', False) or 'paid') if company else 'paid',
                )
                current_vals.setdefault('signature_date_mode', 'auto')

            if current_vals.get('signature_date_mode') != 'manual':
                current_vals['signature_manual_date'] = False

            prepared_vals_list.append(current_vals)

        return super().create(prepared_vals_list)

    @api.onchange('company_id')
    def _onchange_company_id(self):
        for wizard in self:
            if not wizard.company_id:
                wizard._apply_audit_report_defaults(self.env['audit.report'])
                continue
            wizard._apply_audit_report_defaults(
                wizard.audit_report_id
                if wizard.audit_report_id and wizard.audit_report_id.company_id == wizard.company_id
                else wizard._find_latest_audit_report(wizard.company_id)
            )

    @api.onchange('date_end')
    def _onchange_date_end(self):
        for wizard in self:
            if wizard.audit_report_id:
                continue
            if wizard.date_end:
                wizard.date_start = wizard._default_date_start_for_end_date(wizard.date_end)

    @api.onchange('signature_date_mode')
    def _onchange_signature_date_mode(self):
        if self.signature_date_mode != 'manual':
            self.signature_manual_date = False

    @api.onchange(*INSTANT_SHAREHOLDER_SYNC_FIELD_NAMES)
    def _onchange_instant_sync_shareholder_info(self):
        self._sync_lor_fields_to_linked_records()

    def _company_shareholder_sync_vals(self):
        self.ensure_one()
        vals = {}

        for field_name in self._company_text_shareholder_field_names():
            vals[field_name] = getattr(self, field_name, False) or False
        for field_name in self._company_integer_shareholder_field_names():
            vals[field_name] = getattr(self, field_name, 0) or 0
        for field_name in self._company_float_shareholder_field_names():
            vals[field_name] = getattr(self, field_name, 0.0) or 0.0

        if self.share_capital_paid_status:
            vals['company_share'] = self.share_capital_paid_status
        return vals

    def _sync_lor_fields_to_linked_records(self):
        for wizard in self:
            if wizard.company_id:
                wizard.company_id.write(wizard._company_shareholder_sync_vals())

            if not wizard.audit_report_id:
                continue

            audit_vals = {
                'share_capital_paid_status': wizard.share_capital_paid_status or 'paid',
            }
            for field_name in wizard._signature_field_names():
                audit_vals[field_name] = getattr(wizard, field_name, False)
            wizard.audit_report_id.write(audit_vals)

    def write(self, vals):
        result = super().write(vals)
        if {
            'share_capital_paid_status',
            *self._signature_field_names(),
        }.intersection(vals):
            self._sync_lor_fields_to_linked_records()
        return result

    @api.depends(
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
        'signature_include_1',
        'signature_include_2',
        'signature_include_3',
        'signature_include_4',
        'signature_include_5',
        'signature_include_6',
        'signature_include_7',
        'signature_include_8',
        'signature_include_9',
        'signature_include_10',
    )
    def _compute_manager_name_display(self):
        for wizard in self:
            wizard.manager_name_display = wizard._get_lor_manager_names()

    @staticmethod
    def _join_lor_names(names):
        normalized_names = [str(name or '').strip() for name in names if str(name or '').strip()]
        if not normalized_names:
            return ''
        if len(normalized_names) == 1:
            return normalized_names[0]
        if len(normalized_names) == 2:
            return f'{normalized_names[0]} and {normalized_names[1]}'
        return f"{', '.join(normalized_names[:-1])} and {normalized_names[-1]}"

    def _get_lor_manager_names(self):
        self.ensure_one()
        manager_names = []
        for index in range(1, 11):
            if not getattr(self, f'signature_include_{index}', False):
                continue
            manager_name = (getattr(self, f'shareholder_{index}', '') or '').strip()
            if manager_name:
                manager_names.append(manager_name)
        if manager_names:
            return self._join_lor_names(manager_names)
        return ''

    def _validate_lor_settings(self):
        self.ensure_one()
        if not self.date_end:
            raise ValidationError("Please provide Date End for the LOR.")
        if self.signature_date_mode == 'manual' and not self.signature_manual_date:
            raise ValidationError(
                "Please provide Manual Signature Date when signature placeholder date mode is set to Manual date."
            )

    def _get_lor_extra_item_texts(self):
        self.ensure_one()
        return [
            (line.item_text or '').strip()
            for line in self.extra_item_line_ids.sorted(
                key=lambda line: (line.sequence or 0, line.id)
            )
            if (line.item_text or '').strip()
        ]

    def action_generate_docx(self):
        self.ensure_one()
        self._validate_lor_settings()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/lor_report/docx/{self.id}',
            'target': 'new',
        }

    @api.model
    def _sync_generate_lor_menu_parent(self):
        generate_menu = self.env.ref('LOR_Report.lor_report_generate_menu', raise_if_not_found=False)
        if not generate_menu:
            return True

        custom_modules_menu = self.env.ref(
            'Audit_Report.menu_custom_modules',
            raise_if_not_found=False,
        )
        if not custom_modules_menu:
            return True

        vals = {}
        if generate_menu.parent_id != custom_modules_menu:
            vals['parent_id'] = custom_modules_menu.id
        if generate_menu.sequence != 110:
            vals['sequence'] = 110
        if vals:
            generate_menu.write(vals)
        return True


class LorReportExtraLine(models.TransientModel):
    _name = 'lor.report.extra.line'
    _description = 'LOR Extra Main Item'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'lor.report.wizard',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    item_text = fields.Text(required=True, string='Main List Item')
