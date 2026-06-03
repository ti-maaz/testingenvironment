from collections import OrderedDict

from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError


CUSTOMER_ALLOCATION = 'customer_invoice'
VENDOR_ALLOCATION = 'vendor_bill'
RECEIVABLE_ACCOUNT_TYPE = 'asset_receivable'
PAYABLE_ACCOUNT_TYPE = 'liability_payable'
CUSTOMER_SIDE_MOVE_TYPES = ('out_invoice', 'entry')
VENDOR_SIDE_MOVE_TYPES = ('in_invoice', 'entry')


class AccountKnockoffSettlement(models.Model):
    _name = 'account.knockoff.settlement'
    _description = 'AR/AP Knock-Off Settlement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'settlement_date desc, id desc'
    _rec_name = 'name'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='New',
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    settlement_type = fields.Selection(
        [
            ('same_partner', 'Same Partner AR/AP Knock-Off'),
            ('third_party', 'Third-Party / Contra Settlement'),
        ],
        string='Settlement Type',
        required=True,
        default='same_partner',
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        tracking=True,
    )
    customer_partner_id = fields.Many2one(
        'res.partner',
        string='Customer Partner',
        tracking=True,
    )
    vendor_partner_id = fields.Many2one(
        'res.partner',
        string='Vendor Partner',
        tracking=True,
    )
    customer_invoice_ids = fields.Many2many(
        'account.move',
        'account_knockoff_settlement_customer_invoice_rel',
        'settlement_id',
        'move_id',
        string='Customer-Side Documents',
        domain=[
            ('state', '=', 'posted'),
            '|',
            '&',
            ('move_type', '=', 'out_invoice'),
            ('payment_state', 'not in', ('paid', 'reversed')),
            '&',
            ('move_type', '=', 'entry'),
            ('journal_id.type', 'not in', ('bank', 'cash')),
        ],
        check_company=True,
    )
    vendor_bill_ids = fields.Many2many(
        'account.move',
        'account_knockoff_settlement_vendor_bill_rel',
        'settlement_id',
        'move_id',
        string='Vendor-Side Documents',
        domain=[
            ('state', '=', 'posted'),
            '|',
            '&',
            ('move_type', '=', 'in_invoice'),
            ('payment_state', 'not in', ('paid', 'reversed')),
            '&',
            ('move_type', '=', 'entry'),
            ('journal_id.type', 'not in', ('bank', 'cash')),
        ],
        check_company=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Knock-Off Journal',
        required=True,
        domain=[('type', '=', 'general')],
        check_company=True,
        tracking=True,
    )
    settlement_date = fields.Date(
        string='Settlement Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    amount = fields.Monetary(
        string='Knock-Off Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
        default=0.0,
    )
    customer_residual_total = fields.Monetary(
        string='Customer Residual Total',
        compute='_compute_residual_totals',
        currency_field='currency_id',
    )
    vendor_residual_total = fields.Monetary(
        string='Vendor Residual Total',
        compute='_compute_residual_totals',
        currency_field='currency_id',
    )
    max_settlement_amount = fields.Monetary(
        string='Maximum Settlement Amount',
        compute='_compute_residual_totals',
        currency_field='currency_id',
    )
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
        check_company=True,
        tracking=True,
    )
    journal_entry_count = fields.Integer(
        string='Journal Entry Count',
        compute='_compute_journal_entry_count',
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
    )
    reason = fields.Text(
        string='Third-Party Settlement Reason',
        tracking=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'account_knockoff_settlement_ir_attachment_rel',
        'settlement_id',
        'attachment_id',
        string='Supporting Attachments',
        copy=False,
    )
    approval_user_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
        copy=False,
    )
    approval_date = fields.Datetime(
        string='Approval Date',
        readonly=True,
        copy=False,
    )
    note = fields.Text(string='Notes')
    line_ids = fields.One2many(
        'account.knockoff.settlement.line',
        'settlement_id',
        string='Allocation Lines',
        copy=False,
    )
    warning_message = fields.Char(
        string='Warning',
        compute='_compute_warning_message',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.knockoff.settlement') or 'New'
        settlements = super().create(vals_list)
        settlements._sync_currency_from_documents()
        settlements._sync_partner_fields_from_documents()
        settlements.filtered(lambda settlement: settlement.state == 'draft')._sync_amount_from_documents()
        return settlements

    def write(self, vals):
        workflow_fields = {'state', 'move_id', 'approval_user_id', 'approval_date'}
        if workflow_fields.intersection(vals) and not self.env.context.get('knockoff_workflow_write'):
            raise UserError(_('Please use the settlement workflow buttons.'))

        if not self.env.user.has_group('account_ar_ap_knockoff.group_knockoff_manager'):
            locked_records = self.filtered(lambda settlement: settlement.state not in ('draft', 'submitted'))
            if locked_records:
                raise AccessError(_('Only knock-off managers can modify approved, posted, or cancelled settlements.'))

        result = super().write(vals)
        if {'customer_invoice_ids', 'vendor_bill_ids', 'company_id', 'currency_id', 'settlement_type'}.intersection(vals):
            draft_settlements = self.filtered(lambda settlement: settlement.state == 'draft')
            draft_settlements._sync_currency_from_documents()
            draft_settlements._sync_partner_fields_from_documents()
            draft_settlements._sync_amount_from_documents()
        return result

    def unlink(self):
        if self.filtered('move_id'):
            raise UserError(_('Settlements linked to a journal entry cannot be deleted.'))
        return super().unlink()

    @api.depends(
        'currency_id',
        'customer_invoice_ids',
        'customer_invoice_ids.line_ids.amount_residual',
        'customer_invoice_ids.line_ids.amount_residual_currency',
        'vendor_bill_ids',
        'vendor_bill_ids.line_ids.amount_residual',
        'vendor_bill_ids.line_ids.amount_residual_currency',
    )
    def _compute_residual_totals(self):
        for settlement in self:
            currency = settlement.currency_id or settlement.company_id.currency_id
            customer_total = settlement._get_side_open_amount(CUSTOMER_ALLOCATION)
            vendor_total = settlement._get_side_open_amount(VENDOR_ALLOCATION)
            settlement.customer_residual_total = currency.round(customer_total) if currency else customer_total
            settlement.vendor_residual_total = currency.round(vendor_total) if currency else vendor_total
            settlement.max_settlement_amount = min(
                settlement.customer_residual_total,
                settlement.vendor_residual_total,
            )

    @api.depends('move_id')
    def _compute_journal_entry_count(self):
        for settlement in self:
            settlement.journal_entry_count = 1 if settlement.move_id else 0

    @api.depends(
        'settlement_type',
        'partner_id',
        'customer_partner_id',
        'vendor_partner_id',
        'customer_invoice_ids',
        'vendor_bill_ids',
        'currency_id',
        'amount',
        'max_settlement_amount',
        'reason',
        'attachment_ids',
    )
    def _compute_warning_message(self):
        for settlement in self:
            messages = []
            documents = settlement.customer_invoice_ids | settlement.vendor_bill_ids
            if documents.filtered(lambda move: move.state != 'posted'):
                messages.append(_('Only posted customer-side and vendor-side documents can be knocked off.'))
            if settlement.customer_invoice_ids.filtered(
                lambda move: move.move_type not in CUSTOMER_SIDE_MOVE_TYPES
            ):
                messages.append(_('Customer-side documents must be customer invoices or journal entries.'))
            if settlement.vendor_bill_ids.filtered(
                lambda move: move.move_type not in VENDOR_SIDE_MOVE_TYPES
            ):
                messages.append(_('Vendor-side documents must be vendor bills or journal entries.'))
            if settlement.customer_invoice_ids and not settlement._get_side_open_lines(CUSTOMER_ALLOCATION):
                messages.append(_('Selected customer-side documents must have open receivable lines.'))
            if settlement.vendor_bill_ids and not settlement._get_side_open_lines(VENDOR_ALLOCATION):
                messages.append(_('Selected vendor-side documents must have open payable lines.'))

            currencies = documents.mapped('currency_id')
            if len(currencies) > 1:
                # Removed multi-currency restriction warning
                pass

            currency = settlement.currency_id or settlement.company_id.currency_id
            if currency and settlement.amount:
                if currency.compare_amounts(settlement.amount, settlement.max_settlement_amount) > 0:
                    messages.append(_('The settlement amount cannot exceed the available residual amount.'))

            if settlement.settlement_type == 'third_party':
                if not settlement.reason or not settlement.attachment_ids:
                    messages.append(_('Third-party settlement requires a reason and supporting attachment.'))
                customer_resolution = settlement._get_side_partner_resolution(CUSTOMER_ALLOCATION)
                vendor_resolution = settlement._get_side_partner_resolution(VENDOR_ALLOCATION)
                if (
                    customer_resolution['unique_partner']
                    and vendor_resolution['unique_partner']
                    and customer_resolution['unique_partner'] == vendor_resolution['unique_partner']
                ):
                    messages.append(_('Customer and vendor partners are the same in third-party mode.'))
            else:
                overall_resolution = settlement._get_overall_partner_resolution()
                if documents and (
                    overall_resolution['has_partnerless']
                    or len(overall_resolution['partners']) != 1
                ):
                    messages.append(_('Same-partner knock-off requires all qualifying open lines to resolve to one common non-empty partner.'))

            settlement.warning_message = ' '.join(messages)

    @api.onchange('settlement_type')
    def _onchange_settlement_type(self):
        for settlement in self:
            if settlement.settlement_type == 'same_partner':
                settlement.customer_partner_id = False
                settlement.vendor_partner_id = False
            else:
                settlement.partner_id = False
            settlement.customer_invoice_ids = False
            settlement.vendor_bill_ids = False
            settlement.amount = 0.0
            settlement.line_ids = [Command.clear()]
        return {'domain': self._get_onchange_domains()}

    @api.onchange('company_id')
    def _onchange_company_id(self):
        for settlement in self:
            settlement.currency_id = settlement.company_id.currency_id
            settlement.journal_id = False
            settlement.customer_invoice_ids = False
            settlement.vendor_bill_ids = False
            settlement.amount = 0.0
            settlement.line_ids = [Command.clear()]
        return {'domain': self._get_onchange_domains()}

    @api.onchange('partner_id', 'customer_partner_id', 'vendor_partner_id')
    def _onchange_partner_fields(self):
        for settlement in self:
            settlement.line_ids = [Command.clear()]
        return {'domain': self._get_onchange_domains()}

    @api.onchange('customer_invoice_ids', 'vendor_bill_ids')
    def _onchange_documents(self):
        for settlement in self:
            settlement._sync_currency_from_documents()
            settlement._sync_partner_fields_from_documents()
            settlement._compute_residual_totals()
            settlement._sync_amount_from_documents()
            settlement.line_ids = [Command.clear()]
        return {'domain': self._get_onchange_domains()}

    @api.onchange('amount')
    def _onchange_amount(self):
        for settlement in self:
            currency = settlement.currency_id or settlement.company_id.currency_id
            if currency and settlement.amount and currency.compare_amounts(settlement.amount, settlement.max_settlement_amount) > 0:
                return {
                    'warning': {
                        'title': _('Settlement amount'),
                        'message': _('The settlement amount cannot exceed the available residual amount.'),
                    }
                }
        return {}

    def _sync_currency_from_documents(self):
        for settlement in self:
            documents = settlement.customer_invoice_ids | settlement.vendor_bill_ids
            currencies = documents.mapped('currency_id')
            if len(currencies) == 1 and settlement.currency_id != currencies:
                settlement.currency_id = currencies.id
            elif not settlement.currency_id:
                settlement.currency_id = settlement.company_id.currency_id.id

    def _get_allowed_move_types(self, allocation_type):
        self.ensure_one()
        if allocation_type == CUSTOMER_ALLOCATION:
            return CUSTOMER_SIDE_MOVE_TYPES
        if allocation_type == VENDOR_ALLOCATION:
            return VENDOR_SIDE_MOVE_TYPES
        raise UserError(_('Invalid allocation type.'))

    def _summarize_line_partners(self, lines):
        self.ensure_one()
        partners = self.env['res.partner']
        has_partnerless = False
        for line in lines:
            if line.partner_id:
                partners |= line.partner_id.commercial_partner_id
            else:
                has_partnerless = True
        unique_partner = partners[0] if len(partners) == 1 and not has_partnerless else False
        return {
            'partners': partners,
            'has_partnerless': has_partnerless,
            'unique_partner': unique_partner,
        }

    def _get_side_open_lines(self, allocation_type):
        self.ensure_one()
        lines = self.env['account.move.line']
        for move in self._get_moves_for_allocation_type(allocation_type):
            lines |= self._get_open_lines(move, allocation_type)
        return lines

    def _get_move_partner_resolution(self, move, allocation_type):
        self.ensure_one()
        return self._summarize_line_partners(
            self._get_open_lines(move, allocation_type)
        )

    def _get_side_partner_resolution(self, allocation_type):
        self.ensure_one()
        return self._summarize_line_partners(
            self._get_side_open_lines(allocation_type)
        )

    def _get_overall_partner_resolution(self):
        self.ensure_one()
        return self._summarize_line_partners(
            self._get_side_open_lines(CUSTOMER_ALLOCATION)
            | self._get_side_open_lines(VENDOR_ALLOCATION)
        )

    def _sync_partner_fields_from_documents(self):
        for settlement in self:
            if settlement.settlement_type == 'same_partner':
                settlement.customer_partner_id = False
                settlement.vendor_partner_id = False
                settlement.partner_id = settlement._get_overall_partner_resolution()['unique_partner'] or False
                continue

            settlement.partner_id = False
            settlement.customer_partner_id = (
                settlement._get_side_partner_resolution(CUSTOMER_ALLOCATION)['unique_partner'] or False
            )
            settlement.vendor_partner_id = (
                settlement._get_side_partner_resolution(VENDOR_ALLOCATION)['unique_partner'] or False
            )

    def _sync_amount_from_documents(self):
        for settlement in self:
            max_amount = settlement.max_settlement_amount or 0.0
            if not settlement.customer_invoice_ids or not settlement.vendor_bill_ids:
                settlement.amount = 0.0
                continue
            settlement.amount = max_amount

    def _get_onchange_domains(self):
        self.ensure_one()
        return {
            'customer_invoice_ids': self._get_document_domain(CUSTOMER_ALLOCATION),
            'vendor_bill_ids': self._get_document_domain(VENDOR_ALLOCATION),
            'journal_id': [('type', '=', 'general'), ('company_id', '=', self.company_id.id)],
        }

    def _get_document_domain(self, allocation_type):
        self.ensure_one()
        if allocation_type == CUSTOMER_ALLOCATION:
            domain = [
                ('state', '=', 'posted'),
                '|',
                '&',
                ('move_type', '=', 'out_invoice'),
                ('payment_state', 'not in', ('paid', 'reversed')),
                '&',
                ('move_type', '=', 'entry'),
                ('journal_id.type', 'not in', ('bank', 'cash')),
            ]
        else:
            domain = [
                ('state', '=', 'posted'),
                '|',
                '&',
                ('move_type', '=', 'in_invoice'),
                ('payment_state', 'not in', ('paid', 'reversed')),
                '&',
                ('move_type', '=', 'entry'),
                ('journal_id.type', 'not in', ('bank', 'cash')),
            ]
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        return domain

    def _document_matches_selected_partner(self, move, allocation_type):
        self.ensure_one()
        if not move:
            return False
        if self.settlement_type == 'same_partner':
            partner = self.partner_id
        elif allocation_type == CUSTOMER_ALLOCATION:
            partner = self.customer_partner_id
        else:
            partner = self.vendor_partner_id
        if not partner:
            return True
        return self._get_move_partner_resolution(move, allocation_type)['unique_partner'] == partner.commercial_partner_id

    def _get_documents(self):
        self.ensure_one()
        return self.customer_invoice_ids | self.vendor_bill_ids

    def _get_account_type(self, allocation_type):
        if allocation_type == CUSTOMER_ALLOCATION:
            return RECEIVABLE_ACCOUNT_TYPE
        if allocation_type == VENDOR_ALLOCATION:
            return PAYABLE_ACCOUNT_TYPE
        raise UserError(_('Invalid allocation type.'))

    def _get_moves_for_allocation_type(self, allocation_type):
        self.ensure_one()
        if allocation_type == CUSTOMER_ALLOCATION:
            return self.customer_invoice_ids
        if allocation_type == VENDOR_ALLOCATION:
            return self.vendor_bill_ids
        return self.env['account.move']

    def _get_open_lines(self, move, allocation_type):
        self.ensure_one()
        account_type = self._get_account_type(allocation_type)
        return move.line_ids.filtered(
            lambda line: (
                line.account_id.account_type == account_type
                and line.parent_state == 'posted'
                and not line.reconciled
                and self._line_has_open_amount(line)
            )
        ).sorted(key=lambda line: (line.date_maturity or line.date or fields.Date.context_today(self), line.id))

    def _line_has_open_amount(self, line):
        company_currency = line.company_currency_id or line.company_id.currency_id
        if not company_currency.is_zero(line.amount_residual):
            return True
        if line.currency_id and not line.currency_id.is_zero(line.amount_residual_currency):
            return True
        return False

    def _get_line_open_amount(self, line):
        self.ensure_one()
        settlement_currency = self.currency_id or self.company_id.currency_id
        if line.currency_id == settlement_currency:
            return abs(line.amount_residual_currency)
        
        company_currency = line.company_currency_id or line.company_id.currency_id
        # amount_residual is always in company currency
        return company_currency._convert(
            abs(line.amount_residual),
            settlement_currency,
            self.company_id,
            self.settlement_date or fields.Date.context_today(self)
        )

    def _get_move_open_amount(self, move, allocation_type):
        self.ensure_one()
        return sum(self._get_line_open_amount(line) for line in self._get_open_lines(move, allocation_type))

    def _get_side_open_amount(self, allocation_type):
        self.ensure_one()
        return sum(
            self._get_move_open_amount(move, allocation_type)
            for move in self._get_moves_for_allocation_type(allocation_type)
        )

    def _validate_base_data(self, require_third_party_documents=True, enforce_mode_rules=True):
        self.ensure_one()
        self._sync_currency_from_documents()
        currency = self.currency_id or self.company_id.currency_id

        if not self.customer_invoice_ids:
            raise UserError(_('Please select at least one customer-side document.'))
        if not self.vendor_bill_ids:
            raise UserError(_('Please select at least one vendor-side document.'))
        if not self.journal_id:
            raise UserError(_('Please select a general journal.'))
        if self.journal_id.type != 'general' or self.journal_id.company_id != self.company_id:
            raise UserError(_('The selected journal must be a general journal for the settlement company.'))
        if not currency or currency.compare_amounts(self.amount, 0.0) <= 0:
            raise UserError(_('The settlement amount must be greater than zero.'))

        documents = self._get_documents()
        if documents.filtered(lambda move: move.state != 'posted'):
            raise UserError(_('Only posted customer-side and vendor-side documents can be knocked off.'))
        if documents.filtered(lambda move: move.company_id != self.company_id):
            raise UserError(_('The selected documents must belong to the same company.'))
        if self.customer_invoice_ids.filtered(
            lambda move: move.move_type not in CUSTOMER_SIDE_MOVE_TYPES
        ):
            raise UserError(_('Customer-side documents must be customer invoices or journal entries.'))
        if self.vendor_bill_ids.filtered(
            lambda move: move.move_type not in VENDOR_SIDE_MOVE_TYPES
        ):
            raise UserError(_('Vendor-side documents must be vendor bills or journal entries.'))

        document_currencies = documents.mapped('currency_id')
        if document_currencies and self.currency_id not in document_currencies and self.currency_id != self.company_id.currency_id:
            # If settlement currency is not one of document currencies and not company currency,
            # we just ensure it is set. No restriction needed anymore.
            pass

        self._sync_partner_fields_from_documents()
        self._validate_partner_selection(
            require_third_party_documents=require_third_party_documents,
            enforce_mode_rules=enforce_mode_rules,
        )
        self._validate_open_account_lines()

        max_amount = min(
            self._get_side_open_amount(CUSTOMER_ALLOCATION),
            self._get_side_open_amount(VENDOR_ALLOCATION),
        )
        if currency.compare_amounts(self.amount, max_amount) > 0:
            raise UserError(_('The settlement amount cannot exceed the available residual amount.'))

    def _validate_partner_selection(self, require_third_party_documents=True, enforce_mode_rules=True):
        self.ensure_one()
        if self.settlement_type == 'same_partner':
            resolution = self._get_overall_partner_resolution()
            self.partner_id = resolution['unique_partner'] or False
            self.customer_partner_id = False
            self.vendor_partner_id = False
            if enforce_mode_rules and (resolution['has_partnerless'] or len(resolution['partners']) != 1):
                raise UserError(_(
                    'Same-partner knock-off requires all qualifying open lines on the selected '
                    'customer-side and vendor-side documents to resolve to one common non-empty partner.'
                ))
            return

        customer_resolution = self._get_side_partner_resolution(CUSTOMER_ALLOCATION)
        vendor_resolution = self._get_side_partner_resolution(VENDOR_ALLOCATION)
        self.customer_partner_id = customer_resolution['unique_partner'] or False
        self.vendor_partner_id = vendor_resolution['unique_partner'] or False
        if require_third_party_documents and (not self.reason or not self.attachment_ids):
            raise UserError(_('Third-party settlement requires a reason and supporting attachment.'))
        if enforce_mode_rules and (
            customer_resolution['unique_partner']
            and vendor_resolution['unique_partner']
            and customer_resolution['unique_partner'] == vendor_resolution['unique_partner']
        ):
            raise UserError(_('Customer and vendor partners are the same in third-party mode.'))

    def _validate_open_account_lines(self):
        self.ensure_one()
        for move in self.customer_invoice_ids:
            receivable_lines = move.line_ids.filtered(
                lambda line: line.account_id.account_type == RECEIVABLE_ACCOUNT_TYPE and line.parent_state == 'posted'
            )
            if not receivable_lines:
                raise UserError(_('No receivable line was found on %(move)s.', move=move.display_name))
            if not self._get_open_lines(move, CUSTOMER_ALLOCATION):
                raise UserError(_('This customer-side document has no open receivable balance and cannot be used for knock-off.'))
        for move in self.vendor_bill_ids:
            payable_lines = move.line_ids.filtered(
                lambda line: line.account_id.account_type == PAYABLE_ACCOUNT_TYPE and line.parent_state == 'posted'
            )
            if not payable_lines:
                raise UserError(_('No payable line was found on %(move)s.', move=move.display_name))
            if not self._get_open_lines(move, VENDOR_ALLOCATION):
                raise UserError(_('This vendor-side document has no open payable balance and cannot be used for knock-off.'))

    def action_compute_allocation(self):
        for settlement in self:
            if settlement.state != 'draft':
                raise UserError(_('Allocation can only be computed in draft state.'))
            settlement._validate_base_data(
                require_third_party_documents=False,
                enforce_mode_rules=False,
            )
            commands = [Command.clear()]
            commands += settlement._prepare_allocation_commands(CUSTOMER_ALLOCATION)
            commands += settlement._prepare_allocation_commands(VENDOR_ALLOCATION)
            settlement.line_ids = commands
        return True

    def _prepare_allocation_commands(self, allocation_type):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        remaining_amount = currency.round(self.amount)
        commands = []
        moves = self._get_moves_for_allocation_type(allocation_type).sorted(
            key=lambda move: (move.invoice_date or move.date or fields.Date.context_today(self), move.id)
        )
        for move in moves:
            if currency.is_zero(remaining_amount):
                break
            residual_amount = currency.round(self._get_move_open_amount(move, allocation_type))
            if currency.is_zero(residual_amount):
                continue
            allocated_amount = min(remaining_amount, residual_amount)
            if currency.is_zero(allocated_amount):
                continue
            partner = self._get_move_partner_resolution(move, allocation_type)['unique_partner']
            commands.append(Command.create({
                'move_id': move.id,
                'move_type': allocation_type,
                'partner_id': partner.id if partner else False,
                'residual_amount': residual_amount,
                'allocated_amount': currency.round(allocated_amount),
            }))
            remaining_amount = currency.round(remaining_amount - allocated_amount)

        if currency.compare_amounts(remaining_amount, 0.0) > 0:
            raise UserError(_('The settlement amount cannot exceed the available residual amount.'))
        return commands

    def action_submit(self):
        for settlement in self:
            if settlement.state != 'draft':
                raise UserError(_('Only draft settlements can be submitted.'))
            settlement._validate_base_data(require_third_party_documents=True)
            settlement.with_context(knockoff_workflow_write=True).write({'state': 'submitted'})
            settlement.message_post(body=_('Settlement submitted for approval.'))
        return True

    def action_approve(self):
        self._ensure_manager()
        for settlement in self:
            if settlement.state != 'submitted':
                raise UserError(_('Only submitted settlements can be approved.'))
            settlement._validate_base_data(require_third_party_documents=True)
            settlement.with_context(knockoff_workflow_write=True).write({
                'state': 'approved',
                'approval_user_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            settlement.message_post(body=_('Settlement approved by %(user)s.', user=self.env.user.display_name))
        return True

    def action_create_knockoff_entry(self):
        self._ensure_manager()
        for settlement in self:
            if settlement.state != 'approved':
                raise UserError(_('Only approved settlements can create knock-off entries.'))
            if settlement.move_id:
                raise UserError(_('A journal entry has already been created for this settlement.'))

            settlement._validate_base_data(require_third_party_documents=True)
            settlement._validate_allocation_lines()
            move_groups = settlement._prepare_knockoff_move_groups()
            move = settlement._create_knockoff_move(move_groups)
            settlement._reconcile_knockoff_move(move, move_groups)
            settlement.with_context(knockoff_workflow_write=True).write({
                'move_id': move.id,
                'state': 'posted',
            })
            settlement.message_post(body=_('Knock-off journal entry %(move)s was posted and reconciled.', move=move.display_name))
        return True

    def _validate_allocation_lines(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        if not self.line_ids:
            raise UserError(_('Please compute or enter allocation lines before posting.'))

        customer_lines = self.line_ids.filtered(lambda line: line.move_type == CUSTOMER_ALLOCATION)
        vendor_lines = self.line_ids.filtered(lambda line: line.move_type == VENDOR_ALLOCATION)
        if not customer_lines:
            raise UserError(_('Please allocate the settlement amount to at least one customer-side document.'))
        if not vendor_lines:
            raise UserError(_('Please allocate the settlement amount to at least one vendor-side document.'))

        customer_total = sum(customer_lines.mapped('allocated_amount'))
        vendor_total = sum(vendor_lines.mapped('allocated_amount'))
        if currency.compare_amounts(customer_total, self.amount) != 0:
            raise UserError(_('Customer allocation total must equal the settlement amount.'))
        if currency.compare_amounts(vendor_total, self.amount) != 0:
            raise UserError(_('Vendor allocation total must equal the settlement amount.'))

        for line in self.line_ids:
            if currency.compare_amounts(line.allocated_amount, 0.0) <= 0:
                raise UserError(_('Allocation amounts must be greater than zero.'))
            if line.move_type == CUSTOMER_ALLOCATION and line.move_id not in self.customer_invoice_ids:
                raise UserError(_('Customer-side allocation lines must reference selected customer-side documents.'))
            if line.move_type == VENDOR_ALLOCATION and line.move_id not in self.vendor_bill_ids:
                raise UserError(_('Vendor-side allocation lines must reference selected vendor-side documents.'))

            current_residual = self._get_move_open_amount(line.move_id, line.move_type)
            if currency.compare_amounts(line.allocated_amount, current_residual) > 0:
                raise UserError(_(
                    'The allocated amount for %(move)s cannot exceed its current residual amount.',
                    move=line.move_id.display_name,
                ))

        allocation_totals = {}
        for line in self.line_ids:
            key = (line.move_type, line.move_id.id)
            allocation_totals.setdefault(key, {
                'move': line.move_id,
                'move_type': line.move_type,
                'allocated_amount': 0.0,
            })
            allocation_totals[key]['allocated_amount'] += line.allocated_amount

        for allocation in allocation_totals.values():
            current_residual = self._get_move_open_amount(
                allocation['move'],
                allocation['move_type'],
            )
            if currency.compare_amounts(allocation['allocated_amount'], current_residual) > 0:
                raise UserError(_(
                    'The total allocated amount for %(move)s cannot exceed its current residual amount.',
                    move=allocation['move'].display_name,
                ))

    def _prepare_knockoff_move_groups(self):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        settlement_currency = self.currency_id or company_currency
        groups = OrderedDict()

        for allocation_line in self.line_ids:
            for source_line, allocated_amount in self._iter_source_line_allocations(allocation_line):
                balance, amount_currency = self._get_counterpart_amounts(source_line, allocated_amount)
                if company_currency.is_zero(balance):
                    continue
                partner = source_line.partner_id
                debit_credit_key = 'debit' if balance > 0.0 else 'credit'
                key = (
                    allocation_line.move_type,
                    source_line.account_id.id,
                    partner.id,
                    settlement_currency.id,
                    debit_credit_key,
                )
                if key not in groups:
                    side_label = _('Payable') if allocation_line.move_type == VENDOR_ALLOCATION else _('Receivable')
                    groups[key] = {
                        'allocation_type': allocation_line.move_type,
                        'side_label': side_label,
                        'account_id': source_line.account_id,
                        'partner_id': partner,
                        'currency_id': settlement_currency,
                        'balance': 0.0,
                        'amount_currency': 0.0,
                        'source_lines': self.env['account.move.line'],
                    }
                groups[key]['balance'] += balance
                groups[key]['amount_currency'] += amount_currency
                groups[key]['source_lines'] |= source_line

        move_groups = list(groups.values())
        total_balance = company_currency.round(sum(group['balance'] for group in move_groups))
        if not company_currency.is_zero(total_balance):
            if move_groups and abs(total_balance) <= company_currency.rounding:
                largest_group = max(move_groups, key=lambda group: abs(group['balance']))
                largest_group['balance'] = company_currency.round(largest_group['balance'] - total_balance)
            else:
                raise UserError(_(
                    'The selected document types do not produce a balanced knock-off entry. '
                    'Please pair customer-side documents with vendor-side documents.'
                ))

        for index, group in enumerate(move_groups, start=1):
            group['name'] = '%s - %s %s' % (self.name, group['side_label'], index)
            group['line_vals'] = self._prepare_move_line_vals(group)
        return move_groups

    def _iter_source_line_allocations(self, allocation_line):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        remaining_amount = currency.round(allocation_line.allocated_amount)
        source_lines = self._get_open_lines(allocation_line.move_id, allocation_line.move_type)

        for source_line in source_lines:
            if currency.is_zero(remaining_amount):
                break
            open_amount = currency.round(self._get_line_open_amount(source_line))
            if currency.is_zero(open_amount):
                continue
            allocated_amount = currency.round(min(remaining_amount, open_amount))
            if currency.is_zero(allocated_amount):
                continue
            yield source_line, allocated_amount
            remaining_amount = currency.round(remaining_amount - allocated_amount)

        if currency.compare_amounts(remaining_amount, 0.0) > 0:
            raise UserError(_(
                'The allocated amount for %(move)s cannot exceed its current residual amount.',
                move=allocation_line.move_id.display_name,
            ))

    def _get_counterpart_amounts(self, source_line, allocated_amount):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        settlement_currency = self.currency_id or company_currency
        if settlement_currency == company_currency:
            company_amount = company_currency.round(allocated_amount)
            amount_currency = 0.0
        else:
            company_amount = settlement_currency._convert(
                allocated_amount,
                company_currency,
                self.company_id,
                self.settlement_date,
            )
            amount_currency = settlement_currency.round(allocated_amount)

        residual_for_sign = source_line.amount_residual
        if company_currency.is_zero(residual_for_sign) and source_line.currency_id:
            residual_for_sign = source_line.amount_residual_currency
        source_sign = 1.0 if residual_for_sign > 0.0 else -1.0
        balance = company_currency.round(-source_sign * company_amount)
        amount_currency = -source_sign * amount_currency if settlement_currency != company_currency else 0.0
        return balance, amount_currency

    def _prepare_move_line_vals(self, group):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        settlement_currency = group['currency_id']
        balance = company_currency.round(group['balance'])
        vals = {
            'name': group['name'],
            'account_id': group['account_id'].id,
            'partner_id': group['partner_id'].id if group['partner_id'] else False,
            'debit': balance if balance > 0.0 else 0.0,
            'credit': -balance if balance < 0.0 else 0.0,
        }
        if settlement_currency != company_currency:
            vals.update({
                'currency_id': settlement_currency.id,
                'amount_currency': settlement_currency.round(group['amount_currency']),
            })
        return vals

    def _create_knockoff_move(self, move_groups):
        self.ensure_one()
        move = self.env['account.move'].with_company(self.company_id).create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.settlement_date,
            'ref': self.name,
            'company_id': self.company_id.id,
            'line_ids': [Command.create(group['line_vals']) for group in move_groups],
        })
        move.with_context(disable_abnormal_invoice_detection=True).action_post()
        return move

    def _reconcile_knockoff_move(self, move, move_groups):
        self.ensure_one()
        for group in move_groups:
            knockoff_line = move.line_ids.filtered(lambda line: line.name == group['name'])
            if len(knockoff_line) != 1:
                raise UserError(_('Unable to identify the knock-off journal line for reconciliation.'))
            lines_to_reconcile = (group['source_lines'] | knockoff_line).filtered(lambda line: not line.reconciled)
            if len(lines_to_reconcile.mapped('account_id')) != 1:
                raise UserError(_('Only lines on the same receivable/payable account can be reconciled together.'))
            lines_to_reconcile.reconcile()

    def action_cancel(self):
        self._ensure_manager()
        for settlement in self:
            if settlement.move_id:
                raise UserError(_('Posted settlements cannot be cancelled directly. Please reverse the journal entry using standard accounting reversal.'))
            if settlement.state == 'cancelled':
                continue
            settlement.with_context(knockoff_workflow_write=True).write({'state': 'cancelled'})
            settlement.message_post(body=_('Settlement cancelled.'))
        return True

    def action_reset_to_draft(self):
        self._ensure_manager()
        for settlement in self:
            if settlement.move_id:
                raise UserError(_('Settlements linked to a journal entry cannot be reset to draft.'))
            if settlement.state not in ('submitted', 'cancelled'):
                raise UserError(_('Only submitted or cancelled settlements can be reset to draft.'))
            settlement.with_context(knockoff_workflow_write=True).write({
                'state': 'draft',
                'approval_user_id': False,
                'approval_date': False,
            })
            settlement.message_post(body=_('Settlement reset to draft.'))
        return True

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No journal entry has been created for this settlement.'))
        return {
            'name': _('Journal Entry'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _ensure_manager(self):
        if not self.env.user.has_group('account_ar_ap_knockoff.group_knockoff_manager'):
            raise AccessError(_('Only knock-off managers can perform this action.'))
    

class AccountKnockoffSettlementLine(models.Model):
    _name = 'account.knockoff.settlement.line'
    _description = 'AR/AP Knock-Off Settlement Line'
    _order = 'move_type, id'
    _check_company_auto = True

    settlement_id = fields.Many2one(
        'account.knockoff.settlement',
        string='Settlement',
        required=True,
        ondelete='cascade',
    )
    move_id = fields.Many2one(
        'account.move',
        string='Document',
        required=True,
        check_company=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        compute='_compute_move_values',
        store=True,
        readonly=False,
    )
    move_type = fields.Selection(
        [
            (CUSTOMER_ALLOCATION, 'Customer Side'),
            (VENDOR_ALLOCATION, 'Vendor Side'),
        ],
        string='Allocation Type',
        required=True,
    )
    residual_amount = fields.Monetary(
        string='Current Residual',
        compute='_compute_move_values',
        store=True,
        readonly=False,
        currency_field='currency_id',
    )
    allocated_amount = fields.Monetary(
        string='Allocated Amount',
        required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='settlement_id.currency_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='settlement_id.company_id',
        store=True,
        readonly=True,
    )

    @api.depends(
        'settlement_id.currency_id',
        'move_id',
        'move_id.line_ids.amount_residual',
        'move_id.line_ids.amount_residual_currency',
        'move_type',
    )
    def _compute_move_values(self):
        for line in self:
            if not line.move_id:
                line.partner_id = False
                line.residual_amount = 0.0
                continue
            line.partner_id = (
                line.settlement_id._get_move_partner_resolution(line.move_id, line.move_type)['unique_partner']
                if line.settlement_id and line.move_type
                else False
            )
            if line.settlement_id and line.move_type:
                line.residual_amount = line.settlement_id._get_move_open_amount(line.move_id, line.move_type)
            else:
                line.residual_amount = abs(line.move_id.amount_residual)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_editable_settlements()
        return lines

    def write(self, vals):
        self._check_editable_settlements()
        return super().write(vals)

    def unlink(self):
        self._check_editable_settlements()
        return super().unlink()

    def _check_editable_settlements(self):
        locked_lines = self.filtered(lambda line: line.settlement_id and line.settlement_id.state != 'draft')
        if locked_lines:
            raise UserError(_('Allocation lines can only be edited while the settlement is in draft.'))
