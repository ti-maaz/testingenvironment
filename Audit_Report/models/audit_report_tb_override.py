import logging
from decimal import Decimal

from odoo import api, fields, models
from odoo.exceptions import ValidationError


TB_PERIOD_SELECTION = [
    ('current', 'Current'),
    ('prior', 'Prior'),
]

ROUNDED_TB_BALANCE_DIGITS = (16, 0)

_logger = logging.getLogger(__name__)


def _tb_round_half_up_down(value, digits=0):
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


class AuditReportTbOverrideLine(models.TransientModel):
    _name = 'audit.report.tb.override.line'
    _description = 'Audit Report Trial Balance Override Line'
    _order = 'period_key, account_code, id'

    wizard_id = fields.Many2one(
        'audit.report',
        required=True,
        ondelete='cascade',
        index=True,
    )
    period_key = fields.Selection(
        TB_PERIOD_SELECTION,
        required=True,
        index=True,
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        readonly=True,
        index=True,
    )
    account_code = fields.Char(
        string='Code',
        required=True,
        readonly=True,
    )
    account_name = fields.Char(
        string='Name',
        readonly=True,
    )

    system_initial_balance = fields.Float(
        string='System Initial Balance',
        digits='Account',
        readonly=True,
    )
    system_debit = fields.Float(string='System Debit', digits='Account', readonly=True)
    system_credit = fields.Float(string='System Credit', digits='Account', readonly=True)
    system_balance = fields.Float(string='System Balance', digits=ROUNDED_TB_BALANCE_DIGITS, readonly=True)

    override_initial_balance = fields.Float(string='Override Initial Balance', digits='Account')
    override_debit = fields.Float(string='Override Debit', digits='Account')
    override_credit = fields.Float(string='Override Credit', digits='Account')
    override_balance = fields.Float(string='Override Balance', digits=ROUNDED_TB_BALANCE_DIGITS)

    effective_initial_balance = fields.Float(
        string='Effective Initial Balance',
        digits='Account',
        compute='_compute_effective_amounts',
        store=True,
        readonly=True,
    )
    effective_debit = fields.Float(
        string='Effective Debit',
        digits='Account',
        compute='_compute_effective_amounts',
        store=True,
        readonly=True,
    )
    effective_credit = fields.Float(
        string='Effective Credit',
        digits='Account',
        compute='_compute_effective_amounts',
        store=True,
        readonly=True,
    )
    effective_balance = fields.Float(
        string='Effective Balance',
        digits=ROUNDED_TB_BALANCE_DIGITS,
        compute='_compute_effective_amounts',
        store=True,
        readonly=True,
    )
    is_overridden = fields.Boolean(
        string='Overridden',
        compute='_compute_is_overridden',
        store=True,
        readonly=True,
    )

    @staticmethod
    def _to_float(value):
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _round_balance_amount(value):
        return _tb_round_half_up_down(value, digits=0)

    @staticmethod
    def _is_different(left, right):
        return abs((left or 0.0) - (right or 0.0)) > 1e-6

    def _override_value_changed(self, normalized_vals, record, field_name):
        if not record or field_name not in normalized_vals:
            return False
        return self._is_different(
            self._to_float(normalized_vals.get(field_name)),
            self._to_float(getattr(record, field_name)),
        )

    @api.model
    def _normalize_override_vals(self, vals, record=None):
        normalized = dict(vals or {})

        if 'system_balance' in normalized:
            normalized['system_balance'] = self._round_balance_amount(
                normalized.get('system_balance')
            )

        default_initial_balance = self._to_float(
            normalized.get(
                'system_initial_balance',
                record.system_initial_balance if record else 0.0,
            )
        )
        default_debit = self._to_float(
            normalized.get('system_debit', record.system_debit if record else 0.0)
        )
        default_credit = self._to_float(
            normalized.get('system_credit', record.system_credit if record else 0.0)
        )

        if 'override_initial_balance' not in normalized:
            normalized['override_initial_balance'] = self._to_float(
                record.override_initial_balance if record else default_initial_balance
            )
        if 'override_debit' not in normalized:
            normalized['override_debit'] = self._to_float(
                record.override_debit if record else default_debit
            )
        if 'override_credit' not in normalized:
            normalized['override_credit'] = self._to_float(
                record.override_credit if record else default_credit
            )

        balance_changed = self._override_value_changed(
            normalized, record, 'override_balance'
        )
        initial_changed = self._override_value_changed(
            normalized, record, 'override_initial_balance'
        )
        debit_changed = self._override_value_changed(
            normalized, record, 'override_debit'
        )
        balance_driven_edit = (
            'override_balance' in normalized
            and 'override_credit' not in vals
            and (
                not record
                or (
                    balance_changed
                    and not initial_changed
                    and not debit_changed
                )
            )
        )

        if balance_driven_edit:
            initial_balance_value = self._to_float(normalized.get('override_initial_balance'))
            debit_value = self._to_float(normalized.get('override_debit'))
            balance_value = self._round_balance_amount(normalized.get('override_balance'))
            normalized['override_credit'] = initial_balance_value + debit_value - balance_value

        initial_balance_value = self._to_float(normalized.get('override_initial_balance'))
        debit_value = self._to_float(normalized.get('override_debit'))
        credit_value = self._to_float(normalized.get('override_credit'))
        normalized['override_balance'] = self._round_balance_amount(
            initial_balance_value + debit_value - credit_value
        )

        return normalized

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = [self._normalize_override_vals(vals) for vals in vals_list]
        return super().create(normalized_vals_list)

    def write(self, vals):
        if not any(
            key in vals
            for key in (
                'override_initial_balance',
                'override_debit',
                'override_credit',
                'override_balance',
                'system_initial_balance',
                'system_debit',
                'system_credit',
                'system_balance',
            )
        ):
            return super().write(vals)

        if len(self) == 1:
            normalized_vals = self._normalize_override_vals(vals, record=self)
            return super().write(normalized_vals)

        for record in self:
            normalized_vals = self._normalize_override_vals(vals, record=record)
            super(AuditReportTbOverrideLine, record).write(normalized_vals)
        return True

    @api.onchange('override_initial_balance', 'override_debit', 'override_credit')
    def _onchange_override_amounts(self):
        for record in self:
            record.override_balance = record._round_balance_amount(
                self._to_float(record.override_initial_balance)
                + self._to_float(record.override_debit)
                - self._to_float(record.override_credit)
            )

    @api.onchange('override_balance')
    def _onchange_override_balance(self):
        for record in self:
            initial_balance_value = self._to_float(record.override_initial_balance)
            debit_value = self._to_float(record.override_debit)
            balance_value = record._round_balance_amount(record.override_balance)
            # Ending balance edit keeps opening and debit as source and auto-adjusts credit.
            record.override_credit = initial_balance_value + debit_value - balance_value
            record.override_balance = record._round_balance_amount(
                initial_balance_value
                + self._to_float(record.override_debit)
                - self._to_float(record.override_credit)
            )

    @api.depends('override_initial_balance', 'override_debit', 'override_credit')
    def _compute_effective_amounts(self):
        for record in self:
            initial_balance_value = self._to_float(record.override_initial_balance)
            debit_value = self._to_float(record.override_debit)
            credit_value = self._to_float(record.override_credit)
            record.effective_initial_balance = initial_balance_value
            record.effective_debit = debit_value
            record.effective_credit = credit_value
            record.effective_balance = record._round_balance_amount(
                initial_balance_value + debit_value - credit_value
            )

    @api.depends(
        'effective_initial_balance',
        'effective_debit',
        'effective_credit',
        'effective_balance',
        'system_initial_balance',
        'system_debit',
        'system_credit',
        'system_balance',
    )
    def _compute_is_overridden(self):
        for record in self:
            record.is_overridden = any([
                self._is_different(record.effective_initial_balance, record.system_initial_balance),
                self._is_different(record.effective_debit, record.system_debit),
                self._is_different(record.effective_credit, record.system_credit),
                self._is_different(record.effective_balance, record.system_balance),
            ])


class AuditReportTbAddAccountWizard(models.TransientModel):
    _name = 'audit.report.tb.add.account.wizard'
    _description = 'Audit Report Add Trial Balance Override Account'

    wizard_id = fields.Many2one(
        'audit.report',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        related='wizard_id.company_id',
        readonly=True,
    )
    period_key = fields.Selection(
        TB_PERIOD_SELECTION,
        required=True,
        readonly=True,
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=False,
        domain="[('company_ids', 'in', [company_id])]",
    )
    account_code = fields.Char(
        string='Code',
        readonly=True,
    )
    account_name = fields.Char(
        string='Name',
        readonly=True,
    )
    system_initial_balance = fields.Float(string='System Initial Balance', digits='Account', readonly=True)
    system_debit = fields.Float(string='System Debit', digits='Account', readonly=True)
    system_credit = fields.Float(string='System Credit', digits='Account', readonly=True)
    system_balance = fields.Float(string='System Balance', digits=ROUNDED_TB_BALANCE_DIGITS, readonly=True)
    override_initial_balance = fields.Float(string='Override Initial Balance', digits='Account')
    override_debit = fields.Float(string='Override Debit', digits='Account')
    override_credit = fields.Float(string='Override Credit', digits='Account')
    override_balance = fields.Float(string='Override Balance', digits=ROUNDED_TB_BALANCE_DIGITS)

    @staticmethod
    def _to_float(value):
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _round_balance_amount(value):
        return _tb_round_half_up_down(value, digits=0)

    def _compute_system_amounts_for_account(self):
        self.ensure_one()
        report = self.wizard_id
        account = self.account_id
        if not report or not account:
            return {
                'account_code': '',
                'account_name': '',
                'system_initial_balance': 0.0,
                'system_debit': 0.0,
                'system_credit': 0.0,
                'system_balance': 0.0,
            }

        period_start, period_end = report._tb_override_period_range(self.period_key)
        account_code = report._normalize_account_code(account.code or account.code_store or '')
        account_name = account.name or ''
        if not period_end:
            return {
                'account_code': account_code,
                'account_name': account_name,
                'system_initial_balance': 0.0,
                'system_debit': 0.0,
                'system_credit': 0.0,
                'system_balance': 0.0,
            }

        row = report._get_tb_override_system_row_for_account(period_start, period_end, account)
        system_initial_balance = self._to_float(row.get('initial_balance'))
        system_debit = self._to_float(row.get('debit'))
        system_credit = self._to_float(row.get('credit'))
        return {
            'account_code': row.get('code') or account_code,
            'account_name': row.get('name') or account_name,
            'system_initial_balance': system_initial_balance,
            'system_debit': system_debit,
            'system_credit': system_credit,
            'system_balance': self._round_balance_amount(row.get('balance')),
        }

    @api.onchange('account_id')
    def _onchange_account_id(self):
        for record in self:
            payload = record._compute_system_amounts_for_account()
            record.account_code = payload.get('account_code') or ''
            record.account_name = payload.get('account_name') or ''
            record.system_initial_balance = record._to_float(payload.get('system_initial_balance'))
            record.system_debit = record._to_float(payload.get('system_debit'))
            record.system_credit = record._to_float(payload.get('system_credit'))
            record.system_balance = record._round_balance_amount(payload.get('system_balance'))
            record.override_initial_balance = record.system_initial_balance
            record.override_debit = record.system_debit
            record.override_credit = record.system_credit
            record.override_balance = record.system_balance

    @api.onchange('override_initial_balance', 'override_debit', 'override_credit')
    def _onchange_override_amounts(self):
        for record in self:
            record.override_balance = record._round_balance_amount(
                record._to_float(record.override_initial_balance)
                + record._to_float(record.override_debit)
                - record._to_float(record.override_credit)
            )

    @api.onchange('override_balance')
    def _onchange_override_balance(self):
        for record in self:
            initial_balance_value = record._to_float(record.override_initial_balance)
            debit_value = record._to_float(record.override_debit)
            balance_value = record._round_balance_amount(record.override_balance)
            record.override_credit = initial_balance_value + debit_value - balance_value
            record.override_balance = record._round_balance_amount(
                initial_balance_value
                + record._to_float(record.override_debit)
                - record._to_float(record.override_credit)
            )

    def action_add_account_override(self):
        self.ensure_one()
        report = self.wizard_id
        report.ensure_one()
        if self.period_key == 'prior':
            periods = report._get_reporting_periods()
            if not periods.get('show_prior_year'):
                raise ValidationError("Prior-period account overrides are available only for 2-year reports.")
        if not self.account_id:
            raise ValidationError("Please select an account.")

        payload = self._compute_system_amounts_for_account()
        account_code = payload.get('account_code') or ''
        if not account_code:
            raise ValidationError("Selected account does not have a valid account code.")

        line_vals = {
            'account_id': self.account_id.id,
            'account_code': account_code,
            'account_name': payload.get('account_name') or self.account_id.name or '',
            'system_initial_balance': self._to_float(payload.get('system_initial_balance')),
            'system_debit': self._to_float(payload.get('system_debit')),
            'system_credit': self._to_float(payload.get('system_credit')),
            'system_balance': self._round_balance_amount(payload.get('system_balance')),
            'override_initial_balance': self._to_float(self.override_initial_balance),
            'override_debit': self._to_float(self.override_debit),
            'override_credit': self._to_float(self.override_credit),
            'override_balance': self._round_balance_amount(
                self._to_float(self.override_initial_balance)
                + self._to_float(self.override_debit)
                - self._to_float(self.override_credit)
            ),
        }

        existing_line = report.tb_override_line_ids.filtered(
            lambda line: (
                line.period_key == self.period_key
                and (
                    (line.account_id and line.account_id.id == self.account_id.id)
                    or report._normalize_account_code(line.account_code) == account_code
                )
            )
        )[:1]
        if existing_line:
            existing_line.write(line_vals)
        else:
            report.env['audit.report.tb.override.line'].create({
                'wizard_id': report.id,
                'period_key': self.period_key,
                **line_vals,
            })

        report._sync_tb_overrides_json()
        try:
            report._get_report_data()
        except Exception as err:
            _logger.debug(
                "Trial balance warning refresh skipped after manual account add for wizard_id=%s due to: %s",
                report.id,
                err,
            )
        return report._reopen_wizard_form()
