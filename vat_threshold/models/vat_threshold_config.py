# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VatThresholdConfig(models.TransientModel):
    _description = 'VAT Threshold Settings'
    _inherit = 'res.config.settings'

    _THRESHOLD_PARAM_FIELDS = {
        'cancel_threshold': 'vat_threshold.cancel_threshold',
        'voluntary_threshold': 'vat_threshold.voluntary_threshold',
        'mandatory_threshold': 'vat_threshold.mandatory_threshold',
        'mandatory_warning_threshold': 'vat_threshold.mandatory_warning_threshold',
        'cancellation_warning_threshold': 'vat_threshold.cancellation_warning_threshold',
    }

    cancel_threshold = fields.Float(
        string='Cancellation Threshold (AED)',
        config_parameter='vat_threshold.cancel_threshold',
        default=187500.0,
        help='If a company is already VAT registered and rolling sales fall below this amount, the system marks it for VAT cancellation.',
    )
    voluntary_threshold = fields.Float(
        string='Voluntary Registration Threshold (AED)',
        config_parameter='vat_threshold.voluntary_threshold',
        default=210000.0,
        help='If a company is not VAT registered and rolling sales reach this amount, the system marks it as eligible for voluntary VAT registration.',
    )
    mandatory_threshold = fields.Float(
        string='Mandatory Registration Threshold (AED)',
        config_parameter='vat_threshold.mandatory_threshold',
        default=375000.0,
        help='If a company is not VAT registered and rolling sales exceed this amount, the system marks it for mandatory VAT registration.',
    )
    mandatory_warning_threshold = fields.Float(
        string='Mandatory Registration Warning Threshold (AED)',
        config_parameter='vat_threshold.mandatory_warning_threshold',
        default=350000.0,
        help='If a company is not VAT registered and rolling sales reach this amount before the mandatory threshold, the system sends an early warning.',
    )
    cancellation_warning_threshold = fields.Float(
        string='Cancellation Warning Threshold (AED)',
        config_parameter='vat_threshold.cancellation_warning_threshold',
        default=200000.0,
        help='If a company is VAT registered and rolling sales fall below this amount before the cancellation threshold, the system sends an early warning.',
    )
    daily_report_user_ids = fields.Many2many(
        'res.users',
        string='VAT Report Users',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Only these users will receive VAT threshold emails, filtered by the companies assigned to them.',
    )
    daily_report_recipients = fields.Char(
        string='Additional Report Email Recipients',
        config_parameter='vat_threshold.daily_report_recipients',
        help='Comma-separated email addresses that should always receive the full VAT threshold report for all companies.'
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        param_value = self.env['ir.config_parameter'].sudo().get_param(
            'vat_threshold.daily_report_user_ids',
            '',
        )
        user_ids = [
            int(raw_id)
            for raw_id in param_value.split(',')
            if raw_id.strip().isdigit()
        ]
        res.update({
            'daily_report_user_ids': [(6, 0, user_ids)],
        })
        return res

    @api.model
    def _get_stored_threshold_values(self):
        ir_config_parameter = self.env['ir.config_parameter'].sudo()
        values = {}
        for field_name, param_key in self._THRESHOLD_PARAM_FIELDS.items():
            field = self._fields[field_name]
            raw_value = ir_config_parameter.get_param(
                param_key,
                field.default(self) if field.default else 0.0,
            )
            try:
                values[field_name] = float(raw_value)
            except (TypeError, ValueError):
                values[field_name] = float(field.default(self) if field.default else 0.0)
        return values

    def set_values(self):
        self.ensure_one()
        if (
            self.cancel_threshold < 0
            or self.voluntary_threshold < 0
            or self.mandatory_threshold < 0
            or self.mandatory_warning_threshold < 0
            or self.cancellation_warning_threshold < 0
        ):
            raise ValidationError('VAT threshold values cannot be negative.')
        if self.voluntary_threshold > self.mandatory_threshold:
            raise ValidationError(
                'The voluntary registration threshold cannot be greater than the mandatory registration threshold.'
            )
        if self.mandatory_warning_threshold < self.voluntary_threshold:
            raise ValidationError(
                'The mandatory registration warning threshold cannot be less than the voluntary registration threshold.'
            )
        if self.mandatory_warning_threshold >= self.mandatory_threshold:
            raise ValidationError(
                'The mandatory registration warning threshold must be less than the mandatory registration threshold.'
            )
        if self.cancellation_warning_threshold <= self.cancel_threshold:
            raise ValidationError(
                'The cancellation warning threshold must be greater than the cancellation threshold.'
            )

        ir_config_parameter = self.env['ir.config_parameter'].sudo()
        stored_threshold_values = self._get_stored_threshold_values()
        thresholds_changed = any(
            self[field_name] != stored_threshold_values[field_name]
            for field_name in self._THRESHOLD_PARAM_FIELDS
        )

        for field_name, param_key in self._THRESHOLD_PARAM_FIELDS.items():
            ir_config_parameter.set_param(param_key, repr(self[field_name]))
        ir_config_parameter.set_param(
            'vat_threshold.daily_report_recipients',
            (self.daily_report_recipients or '').strip(),
        )
        ir_config_parameter.set_param(
            'vat_threshold.daily_report_user_ids',
            ','.join(str(user_id) for user_id in self.daily_report_user_ids.ids),
        )
        if thresholds_changed:
            self.env['vat.threshold'].sudo().search([])._refresh_threshold_decisions()

    def action_save_settings(self):
        """Persist settings and close the popup using the standard client flow."""
        self.ensure_one()
        self.set_values()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': 'VAT threshold settings saved.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
