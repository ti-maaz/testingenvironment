from collections import defaultdict

from odoo import _, Command, api, fields, models
from odoo.exceptions import UserError


class AccountBankRecodeWizard(models.TransientModel):
    _name = 'account.bank.recode.wizard'
    _description = 'Bank Transaction Recode Wizard'

    statement_line_ids = fields.Many2many(
        'account.bank.statement.line',
        string='Selected Transactions',
        readonly=True,
    )
    line_ids = fields.One2many(
        'account.bank.recode.wizard.line',
        'wizard_id',
        string='Counterpart Journal Items',
    )
    target_account_id = fields.Many2one(
        'account.account',
        string='Replacement Account',
        domain="[('active', '=', True), ('company_ids', 'parent_of', company_id)]",
    )
    recode_target = fields.Selection(
        [
            ('account', 'Account'),
            ('label', 'Label'),
            ('unreconcile', 'Unreconcile'),
        ],
        string='Update',
        default='account',
        required=True,
    )
    transaction_state = fields.Selection(
        [
            ('reconciled', 'Reconciled'),
            ('unreconciled', 'Unreconciled'),
        ],
        string='Transaction State',
        default='reconciled',
        required=True,
    )
    mode = fields.Selection(
        [
            ('all', 'Recode All'),
            ('per_line', 'Per Line'),
        ],
        string='Account Update Mode',
        default='all',
        required=True,
    )
    line_count = fields.Integer(
        string='Selected Transactions',
        compute='_compute_line_count',
    )
    applicable_count = fields.Integer(
        string='Matching Transactions',
        compute='_compute_selection_counts',
    )
    ignored_count = fields.Integer(
        string='Skipped Transactions',
        compute='_compute_selection_counts',
    )
    selection_note = fields.Char(
        string='Selection Note',
        compute='_compute_selection_counts',
    )
    new_label = fields.Char(
        string='Replacement Label',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )

    @api.depends('statement_line_ids')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.statement_line_ids)

    @api.depends('statement_line_ids', 'statement_line_ids.is_reconciled', 'transaction_state')
    def _compute_selection_counts(self):
        for wizard in self:
            applicable_lines = wizard._get_applicable_statement_lines()
            wizard.applicable_count = len(applicable_lines)
            wizard.ignored_count = len(wizard.statement_line_ids) - wizard.applicable_count
            if wizard.ignored_count:
                if wizard.transaction_state == 'reconciled':
                    wizard.selection_note = _(
                        '%(count)s selected transactions are ignored because they are unreconciled.',
                        count=wizard.ignored_count,
                    )
                else:
                    wizard.selection_note = _(
                        '%(count)s selected transactions are ignored because they are already reconciled.',
                        count=wizard.ignored_count,
                    )
            else:
                wizard.selection_note = False

    @api.model
    def _prepare_wizard_line_commands(self, statement_lines):
        commands = []
        for statement_line in statement_lines:
            _liquidity_lines, _suspense_lines, other_lines = statement_line._seek_for_lines()
            for move_line in other_lines:
                commands.append(Command.create({
                    'statement_line_id': statement_line.id,
                    'move_line_id': move_line.id,
                }))
        return commands

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        active_model = self.env.context.get('active_model')

        if active_model != 'account.bank.statement.line' or not active_ids:
            return defaults

        statement_lines = self.env['account.bank.statement.line'].browse(active_ids).exists()
        if not statement_lines:
            return defaults
        if len(statement_lines.company_id) > 1:
            raise UserError(_('Please select transactions from a single company.'))

        defaults['company_id'] = statement_lines.company_id.id
        defaults['statement_line_ids'] = [Command.set(statement_lines.ids)]
        if not self.env.context.get('default_transaction_state'):
            default_transaction_state = statement_lines._get_recode_default_transaction_state()
            if default_transaction_state:
                defaults['transaction_state'] = default_transaction_state
        return defaults

    def _get_applicable_statement_lines(self):
        self.ensure_one()
        if self.transaction_state == 'reconciled':
            return self.statement_line_ids.filtered('is_reconciled')
        return self.statement_line_ids.filtered(lambda line: not line.is_reconciled)

    def _uses_line_mode(self):
        self.ensure_one()
        return self.recode_target == 'account' and self.transaction_state == 'reconciled'

    def _get_required_state_label(self):
        self.ensure_one()
        return _('reconciled') if self.transaction_state == 'reconciled' else _('unreconciled')

    @api.onchange('mode', 'recode_target', 'transaction_state')
    def _onchange_recode_options(self):
        for wizard in self:
            if wizard._uses_line_mode() and wizard.mode == 'per_line':
                wizard.line_ids = [
                    Command.clear(),
                    *wizard._prepare_wizard_line_commands(wizard._get_applicable_statement_lines()),
                ]
            else:
                wizard.line_ids = [Command.clear()]

    def _collect_reconciled_account_changes(self, statement_lines):
        line_changes = []
        if self.mode == 'all':
            if not self.target_account_id:
                raise UserError(_('Select a target account before recoding.'))
            for statement_line in statement_lines:
                _liquidity_lines, _suspense_lines, other_lines = statement_line._seek_for_lines()
                for move_line in other_lines:
                    if move_line.account_id == self.target_account_id:
                        continue
                    line_changes.append({
                        'statement_line': statement_line,
                        'move_line': move_line,
                        'old_account': move_line.account_id,
                        'new_account': self.target_account_id,
                        'label': move_line.name or statement_line.display_name,
                    })
        else:
            valid_wizard_lines = self.line_ids.filtered(
                lambda line: line.statement_line_id in statement_lines and line.move_line_id
            )
            if not valid_wizard_lines:
                raise UserError(_('No counterpart journal items were found for the selected transactions.'))
            missing_targets = valid_wizard_lines.filtered(lambda line: not line.new_account_id)
            if missing_targets:
                raise UserError(_('Set a new account on every line before recoding.'))
            for wizard_line in valid_wizard_lines:
                if wizard_line.new_account_id == wizard_line.current_account_id:
                    continue
                line_changes.append({
                    'statement_line': wizard_line.statement_line_id,
                    'move_line': wizard_line.move_line_id,
                    'old_account': wizard_line.current_account_id,
                    'new_account': wizard_line.new_account_id,
                    'label': wizard_line.label or wizard_line.statement_line_id.display_name,
                })
        return line_changes

    def _apply_reconciled_account_changes(self, statement_lines):
        line_changes = self._collect_reconciled_account_changes(statement_lines)
        if not line_changes:
            raise UserError(_('Nothing to recode. The selected accounts are already set.'))

        changes_by_statement_line = defaultdict(list)
        moves = self.env['account.move']
        for change in line_changes:
            moves |= change['move_line'].move_id
            changes_by_statement_line[change['statement_line'].id].append({
                'label': change['label'],
                'old_account': change['old_account'].display_name,
                'new_account': change['new_account'].display_name,
            })

        posted_moves = moves.filtered(lambda move: move.state == 'posted')
        if posted_moves:
            posted_moves.button_draft()

        for change in line_changes:
            change['move_line'].with_context(skip_readonly_check=True).write({
                'account_id': change['new_account'].id,
            })

        if posted_moves:
            posted_moves.action_post()

        self._message_account_changes(changes_by_statement_line)

    def _apply_unreconciled_account_changes(self, statement_lines):
        if not self.target_account_id:
            raise UserError(_('Select a target account before recoding.'))

        changes_by_statement_line = defaultdict(list)
        for statement_line in statement_lines:
            _liquidity_lines, suspense_lines, _other_lines = statement_line._seek_for_lines()
            if not suspense_lines:
                continue
            if len(suspense_lines) != 1:
                raise UserError(_(
                    'Transaction %(transaction)s is in an invalid state because it has %(count)s suspense lines.',
                    transaction=statement_line.display_name,
                    count=len(suspense_lines),
                ))
            suspense_line = suspense_lines
            if suspense_line.account_id == self.target_account_id:
                continue
            changes_by_statement_line[statement_line.id].append({
                'label': suspense_line.name or statement_line.display_name,
                'old_account': suspense_line.account_id.display_name,
                'new_account': self.target_account_id.display_name,
            })
            statement_line.set_account_bank_statement_line(suspense_line.id, self.target_account_id.id)

        if not changes_by_statement_line:
            raise UserError(_('Nothing to recode. The selected accounts are already set.'))

        self._message_account_changes(changes_by_statement_line)

    def _get_label_move_lines(self, statement_line):
        self.ensure_one()
        liquidity_lines, suspense_lines, _other_lines = statement_line._seek_for_lines()
        if self.transaction_state == 'unreconciled':
            return liquidity_lines | suspense_lines
        return liquidity_lines

    def _apply_label_changes(self, statement_lines):
        new_label = (self.new_label or '').strip()
        if not new_label:
            raise UserError(_('Enter a new label before recoding.'))

        statement_lines_to_update = self.env['account.bank.statement.line']
        move_lines_to_update = self.env['account.move.line']
        label_changes = {}

        for statement_line in statement_lines:
            move_lines = self._get_label_move_lines(statement_line)
            current_label = statement_line.payment_ref or ''
            if current_label == new_label and all(move_line.name == new_label for move_line in move_lines):
                continue

            statement_lines_to_update |= statement_line
            move_lines_to_update |= move_lines.filtered(lambda line: line.name != new_label)
            label_changes[statement_line.id] = {
                'old_label': current_label,
                'new_label': new_label,
            }

        if not label_changes:
            raise UserError(_('Nothing to recode. The selected labels are already set.'))

        posted_moves = move_lines_to_update.move_id.filtered(lambda move: move.state == 'posted')
        if posted_moves:
            posted_moves.button_draft()

        # Avoid rebuilding counterpart lines when only the bank transaction label changes.
        statement_lines_to_update.with_context(
            skip_account_move_synchronization=True,
            skip_readonly_check=True,
        ).write({
            'payment_ref': new_label,
        })
        if move_lines_to_update:
            move_lines_to_update.with_context(skip_readonly_check=True).write({
                'name': new_label,
            })

        if posted_moves:
            posted_moves.action_post()

        self._message_label_changes(label_changes)

    def _message_account_changes(self, changes_by_statement_line):
        timestamp = fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now()))
        statement_lines = self.env['account.bank.statement.line'].browse(list(changes_by_statement_line.keys()))
        for statement_line in statement_lines:
            changes = changes_by_statement_line[statement_line.id]
            changes_text = '\n'.join(
                _('%(label)s: %(old)s -> %(new)s',
                  label=change['label'],
                  old=change['old_account'],
                  new=change['new_account'])
                for change in changes
            )
            statement_line.message_post(body=_(
                'Recoded by %(user)s on %(date)s\n%(changes)s',
                user=self.env.user.display_name,
                date=timestamp,
                changes=changes_text,
            ))

    def _message_label_changes(self, label_changes):
        timestamp = fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now()))
        statement_lines = self.env['account.bank.statement.line'].browse(list(label_changes.keys()))
        for statement_line in statement_lines:
            change = label_changes[statement_line.id]
            old_label = change['old_label'] or _('(empty)')
            statement_line.message_post(body=_(
                'Label recoded by %(user)s on %(date)s\n%(old)s -> %(new)s',
                user=self.env.user.display_name,
                date=timestamp,
                old=old_label,
                new=change['new_label'],
            ))

    def _message_unreconcile_changes(self, unreconcile_changes):
        """Post chatter messages for unreconcile operations."""
        timestamp = fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now()))
        statement_lines = self.env['account.bank.statement.line'].browse(list(unreconcile_changes.keys()))
        for statement_line in statement_lines:
            change = unreconcile_changes[statement_line.id]
            statement_line.message_post(body=_(
                'Unreconciled by %(user)s on %(date)s\n'
                'Previous account: %(old_account)s\n'
                'Moved to suspense account: %(suspense_account)s',
                user=self.env.user.display_name,
                date=timestamp,
                old_account=change['old_account'],
                suspense_account=change['suspense_account'],
            ))

    def _apply_unreconcile_changes(self, statement_lines):
        """Unreconcile transactions by moving counterpart lines back to suspense account."""
        unreconcile_changes = {}
        moves_to_draft = self.env['account.move']

        for statement_line in statement_lines:
            liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()

            # Skip if no counterpart lines (nothing to unreconcile)
            if not other_lines:
                continue

            # Get the journal's suspense account
            suspense_account = statement_line.journal_id.suspense_account_id
            if not suspense_account:
                raise UserError(_(
                    'Journal %(journal)s does not have a suspense account configured.',
                    journal=statement_line.journal_id.display_name,
                ))

            # Collect moves to draft
            moves_to_draft |= other_lines.move_id

            # Store change info for chatter
            unreconcile_changes[statement_line.id] = {
                'old_account': ', '.join(other_lines.account_id.mapped('display_name')),
                'suspense_account': suspense_account.display_name,
            }

        if not unreconcile_changes:
            raise UserError(_('Nothing to unreconcile. No counterpart accounts found on the selected transactions.'))

        # Move posted moves to draft
        posted_moves = moves_to_draft.filtered(lambda move: move.state == 'posted')
        if posted_moves:
            posted_moves.button_draft()

        # Move counterpart lines to suspense account
        for statement_line in statement_lines:
            liquidity_lines, suspense_lines, other_lines = statement_line._seek_for_lines()
            suspense_account = statement_line.journal_id.suspense_account_id

            for move_line in other_lines:
                move_line.with_context(skip_readonly_check=True).write({
                    'account_id': suspense_account.id,
                })

        # Re-post moves that were posted
        if posted_moves:
            posted_moves.action_post()

        # Post chatter messages
        self._message_unreconcile_changes(unreconcile_changes)

    def action_recode(self):
        self.ensure_one()

        if not self.statement_line_ids:
            raise UserError(_('No transactions were selected.'))
        if len(self.statement_line_ids.company_id) > 1:
            raise UserError(_('Please select transactions from a single company.'))

        # For unreconcile, only reconciled transactions are valid
        if self.recode_target == 'unreconcile':
            statement_lines = self.statement_line_ids.filtered('is_reconciled')
            if not statement_lines:
                raise UserError(_('No reconciled transactions are available in the current selection.'))
            self._apply_unreconcile_changes(statement_lines)
        else:
            statement_lines = self._get_applicable_statement_lines()
            if not statement_lines:
                raise UserError(_(
                    'No %(state)s transactions are available in the current selection.',
                    state=self._get_required_state_label(),
                ))

            if self.recode_target == 'account':
                if self.transaction_state == 'reconciled':
                    self._apply_reconciled_account_changes(statement_lines)
                else:
                    self._apply_unreconciled_account_changes(statement_lines)
            else:
                self._apply_label_changes(statement_lines)

        return {'type': 'ir.actions.act_window_close'}


class AccountBankRecodeWizardLine(models.TransientModel):
    _name = 'account.bank.recode.wizard.line'
    _description = 'Bank Transaction Recode Wizard Line'

    wizard_id = fields.Many2one(
        'account.bank.recode.wizard',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        related='wizard_id.company_id',
        store=False,
        readonly=True,
    )
    statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Transaction',
        required=True,
        readonly=True,
    )
    move_line_id = fields.Many2one(
        'account.move.line',
        string='Journal Item',
        required=True,
        readonly=True,
    )
    date = fields.Date(
        related='statement_line_id.date',
        store=False,
        readonly=True,
    )
    label = fields.Char(
        related='move_line_id.name',
        store=False,
        readonly=True,
    )
    current_account_id = fields.Many2one(
        'account.account',
        string='Current Account',
        related='move_line_id.account_id',
        store=False,
        readonly=True,
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='move_line_id.company_currency_id',
        store=False,
        readonly=True,
    )
    amount = fields.Monetary(
        related='move_line_id.balance',
        currency_field='company_currency_id',
        store=False,
        readonly=True,
    )
    new_account_id = fields.Many2one(
        'account.account',
        string='New Account',
        domain="[('active', '=', True), ('company_ids', 'parent_of', company_id)]",
    )
