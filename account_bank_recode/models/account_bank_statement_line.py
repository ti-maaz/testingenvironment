from odoo import _, api, fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    reconciled_account_ids = fields.Many2many(
        'account.account',
        string='Counterpart Accounts',
        compute='_compute_reconciled_account_ids',
        search='_search_reconciled_account_ids',
        help='Counterpart accounts on the statement entry, excluding liquidity and suspense lines.',
    )

    @api.depends(
        'move_id.line_ids.account_id',
        'journal_id.default_account_id',
        'journal_id.suspense_account_id',
        'is_reconciled',
    )
    def _compute_reconciled_account_ids(self):
        empty_accounts = self.env['account.account']
        for statement_line in self:
            if not statement_line.move_id:
                statement_line.reconciled_account_ids = empty_accounts
                continue
            _liquidity_lines, _suspense_lines, other_lines = statement_line._seek_for_lines()
            statement_line.reconciled_account_ids = other_lines.account_id

    @api.model
    def _search_reconciled_account_ids(self, operator, value):
        positive_ops = {'=', 'in', 'like', 'ilike', '=like', '=ilike', 'child_of'}
        negative_ops = {'!=', 'not in'}
        all_ops = positive_ops | negative_ops
        if operator not in all_ops:
            return [('id', '=', 0)]

        account_model = self.env['account.account']
        if operator in {'like', 'ilike', '=like', '=ilike'}:
            account_ids = account_model.search([('display_name', operator, value)]).ids
        elif operator == 'child_of':
            values = value if isinstance(value, list) else [value]
            account_ids = account_model.search([('id', 'child_of', values)]).ids
        elif operator in {'=', '!='}:
            if not value:
                return [] if operator == '!=' else [('id', '=', 0)]
            account_ids = [value] if isinstance(value, int) else list(value)
        else:
            account_ids = list(value or [])

        if not account_ids:
            return [('id', '=', 0)] if operator in positive_ops else []

        self.env.cr.execute("""
            SELECT DISTINCT st.id
            FROM account_bank_statement_line st
            JOIN account_move_line aml ON aml.move_id = st.move_id
            JOIN account_journal j ON j.id = st.journal_id
            WHERE aml.account_id = ANY(%s)
              AND aml.account_id != j.default_account_id
              AND (j.suspense_account_id IS NULL OR aml.account_id != j.suspense_account_id)
        """, [account_ids])
        statement_line_ids = [row[0] for row in self.env.cr.fetchall()]

        if operator in positive_ops:
            return [('id', 'in', statement_line_ids or [0])]
        return [('id', 'not in', statement_line_ids or [0])]

    def action_open_recode_wizard(self):
        if not self:
            return False
        default_transaction_state = self._get_recode_default_transaction_state()
        context = {
            'active_model': 'account.bank.statement.line',
            'active_ids': self.ids,
        }
        if default_transaction_state:
            context['default_transaction_state'] = default_transaction_state
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recode Transactions'),
            'res_model': 'account.bank.recode.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }

    def _get_recode_default_transaction_state(self):
        if not self:
            return False
        if all(self.mapped('is_reconciled')):
            return 'reconciled'
        if not any(self.mapped('is_reconciled')):
            return 'unreconciled'
        return False
