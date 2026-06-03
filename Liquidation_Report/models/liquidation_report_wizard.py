from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LiquidationReportWizard(models.TransientModel):
    _name = 'liquidation.report.wizard'
    _description = 'Liquidation Report Wizard'

    REPORT_TYPE_SELECTION = [
        ('ifza', 'IFZA'),
        ('all_freezones', 'All Freezones'),
    ]
    IFZA_FREE_ZONE_VALUES = {
        'Dubai Integrated Economic Zones Authority',
        'Meydan Free Zone',
    }

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
    report_type = fields.Selection(
        REPORT_TYPE_SELECTION,
        string='Liquidation Report Type',
        required=True,
        default=lambda self: self._default_report_type(),
    )
    liquidation_date = fields.Date(
        string='Liquidation Date',
        required=True,
        default=lambda self: self._default_liquidation_date(),
    )
    letter_date = fields.Date(
        string='Letter Date',
        required=True,
        default=lambda self: fields.Date.context_today(self),
    )
    contact_person = fields.Char(
        string='Contact Person',
        default=lambda self: self._default_contact_person(),
    )

    company_name = fields.Char(related='company_id.name', readonly=False)
    company_street = fields.Char(related='company_id.street', readonly=False)
    company_street2 = fields.Char(related='company_id.street2', readonly=False)
    company_city = fields.Char(related='company_id.city', readonly=False)
    company_state_id = fields.Many2one(related='company_id.state_id', readonly=False)
    company_zip = fields.Char(related='company_id.zip', readonly=False)
    company_country_id = fields.Many2one(related='company_id.country_id', readonly=False)
    company_free_zone = fields.Selection(related='company_id.free_zone', readonly=False)
    company_license_number = fields.Char(
        related='company_id.company_license_number',
        readonly=False,
    )

    @api.model
    def _default_company_id(self):
        return self.env.context.get('default_company_id') or self.env.company.id

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
    def _default_liquidation_date(self):
        audit_report = self.env['audit.report'].browse(
            self.env.context.get('default_audit_report_id')
        ).exists()
        if not audit_report:
            company = self.env['res.company'].browse(self._default_company_id()).exists()
            audit_report = self._find_latest_audit_report(company)
        return audit_report.date_end if audit_report and audit_report.date_end else fields.Date.context_today(self)

    @api.model
    def _normalize_free_zone(self, company, free_zone):
        if company and hasattr(company, '_normalize_free_zone'):
            return company._normalize_free_zone(free_zone)
        return free_zone

    @api.model
    def _report_type_for_company(self, company):
        normalized_free_zone = self._normalize_free_zone(
            company,
            getattr(company, 'free_zone', False),
        )
        if normalized_free_zone in self.IFZA_FREE_ZONE_VALUES:
            return 'ifza'
        return 'all_freezones'

    @api.model
    def _default_report_type(self):
        company = self.env['res.company'].browse(self._default_company_id()).exists()
        return self._report_type_for_company(company)

    @api.model
    def _join_names(self, names):
        normalized_names = [str(name or '').strip() for name in names if str(name or '').strip()]
        if not normalized_names:
            return ''
        if len(normalized_names) == 1:
            return normalized_names[0]
        if len(normalized_names) == 2:
            return f'{normalized_names[0]} and {normalized_names[1]}'
        return f"{', '.join(normalized_names[:-1])} and {normalized_names[-1]}"

    @api.model
    def _contact_person_from_sources(self, audit_report, company):
        manager_names = []
        if audit_report:
            for index in range(1, 11):
                if not getattr(audit_report, f'signature_include_{index}', False):
                    continue
                name = (getattr(audit_report, f'shareholder_{index}', '') or '').strip()
                if name:
                    manager_names.append(name)
        joined_names = self._join_names(manager_names)
        if joined_names:
            return joined_names

        if company:
            return (getattr(company, 'shareholder_1', '') or '').strip()
        return ''

    @api.model
    def _default_contact_person(self):
        audit_report = self.env['audit.report'].browse(
            self.env.context.get('default_audit_report_id')
        ).exists()
        company = self.env['res.company'].browse(
            self.env.context.get('default_company_id') or getattr(audit_report.company_id, 'id', False)
        ).exists()
        if not audit_report and company:
            audit_report = self._find_latest_audit_report(company)
        return self._contact_person_from_sources(audit_report, company)

    @api.model
    def _prepare_defaults_from_sources(self, vals):
        current_vals = dict(vals)
        audit_report = self.env['audit.report'].browse(
            current_vals.get('audit_report_id') or self.env.context.get('default_audit_report_id')
        ).exists()
        company = self.env['res.company'].browse(
            current_vals.get('company_id') or self.env.context.get('default_company_id')
        ).exists()

        if audit_report and audit_report.company_id:
            company = audit_report.company_id
            current_vals['company_id'] = company.id
        elif not audit_report and company:
            audit_report = self._find_latest_audit_report(company)
            if audit_report:
                current_vals.setdefault('audit_report_id', audit_report.id)

        if not company:
            company = self.env['res.company'].browse(self._default_company_id()).exists()
            if company:
                current_vals.setdefault('company_id', company.id)

        if not current_vals.get('liquidation_date'):
            current_vals['liquidation_date'] = (
                audit_report.date_end
                if audit_report and audit_report.date_end
                else fields.Date.context_today(self)
            )
        current_vals.setdefault('letter_date', fields.Date.context_today(self))
        current_vals.setdefault('report_type', self._report_type_for_company(company))
        current_vals.setdefault(
            'contact_person',
            self._contact_person_from_sources(audit_report, company),
        )
        return current_vals

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        prepared_defaults = self._prepare_defaults_from_sources(defaults)
        return {
            field_name: value
            for field_name, value in prepared_defaults.items()
            if not fields_list or field_name in fields_list
        }

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([
            self._prepare_defaults_from_sources(vals)
            for vals in vals_list
        ])

    @api.onchange('company_id')
    def _onchange_company_id(self):
        for wizard in self:
            if not wizard.company_id:
                continue
            audit_report = (
                wizard.audit_report_id
                if wizard.audit_report_id and wizard.audit_report_id.company_id == wizard.company_id
                else wizard._find_latest_audit_report(wizard.company_id)
            )
            wizard.audit_report_id = audit_report
            wizard.report_type = wizard._report_type_for_company(wizard.company_id)
            if audit_report and audit_report.date_end:
                wizard.liquidation_date = audit_report.date_end
            wizard.contact_person = wizard._contact_person_from_sources(
                audit_report,
                wizard.company_id,
            )

    @api.onchange('audit_report_id')
    def _onchange_audit_report_id(self):
        for wizard in self:
            if not wizard.audit_report_id:
                continue
            wizard.company_id = wizard.audit_report_id.company_id
            wizard.report_type = wizard._report_type_for_company(wizard.company_id)
            if wizard.audit_report_id.date_end:
                wizard.liquidation_date = wizard.audit_report_id.date_end
            wizard.contact_person = wizard._contact_person_from_sources(
                wizard.audit_report_id,
                wizard.company_id,
            )

    def _validate_liquidation_settings(self):
        self.ensure_one()
        if not self.company_id:
            raise ValidationError("Please select a company for the liquidation report.")
        if not (self.company_name or '').strip():
            raise ValidationError("Please provide the company name.")
        if not self.liquidation_date:
            raise ValidationError("Please provide the liquidation date.")
        if not (self.company_license_number or '').strip():
            raise ValidationError("Please provide the company license number.")
        if not any(
            (value or '').strip()
            for value in (self.company_street, self.company_street2, self.company_city)
        ):
            raise ValidationError("Please provide the company address for the liquidation report.")
        if self.report_type == 'all_freezones' and not self.letter_date:
            raise ValidationError("Please provide the letter date.")
        if self.report_type == 'all_freezones' and not self.company_free_zone:
            raise ValidationError("Please provide the company free zone.")
        if self.report_type == 'ifza' and not (self.contact_person or '').strip():
            raise ValidationError("Please provide the IFZA contact person.")

    def action_generate_docx(self):
        self.ensure_one()
        self._validate_liquidation_settings()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/liquidation_report/docx/{self.id}',
            'target': 'new',
        }

    @api.model
    def _sync_generate_liquidation_menu_parent(self):
        generate_menu = self.env.ref(
            'Liquidation_Report.liquidation_report_generate_menu',
            raise_if_not_found=False,
        )
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
        if generate_menu.sequence != 120:
            vals['sequence'] = 120
        if vals:
            generate_menu.write(vals)
        return True
