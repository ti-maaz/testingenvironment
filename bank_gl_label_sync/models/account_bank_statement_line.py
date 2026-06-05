from odoo import api, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    def _is_bank_label_sync_enabled(self):
        self.ensure_one()
        return self.journal_id.type in ('bank', 'cash') and self.journal_id.use_bank_label_in_gl

    def _get_bank_transaction_label(self):
        self.ensure_one()
        label = (self.payment_ref or '').strip()
        return label or False

    def _apply_bank_label_sync(self):
        for statement_line in self:
            if not statement_line._is_bank_label_sync_enabled():
                continue

            bank_label = statement_line._get_bank_transaction_label()
            if not bank_label or not statement_line.move_id:
                continue

            lines_to_update = statement_line.move_id.line_ids.filtered(
                lambda line: line.statement_line_id == statement_line and line.name != bank_label
            )
            if lines_to_update:
                lines_to_update.with_context(
                    skip_account_move_synchronization=True,
                    tracking_disable=True,
                ).write({'name': bank_label})

        return True

    @api.model_create_multi
    def create(self, vals_list):
        statement_lines = super().create(vals_list)
        statement_lines._apply_bank_label_sync()
        return statement_lines

    def _synchronize_to_moves(self, changed_fields):
        result = super()._synchronize_to_moves(changed_fields)
        if (
            not self.env.context.get('skip_account_move_synchronization')
            and any(
                field_name in changed_fields
                for field_name in (
                    'payment_ref',
                    'amount',
                    'amount_currency',
                    'foreign_currency_id',
                    'currency_id',
                    'partner_id',
                )
            )
        ):
            self._apply_bank_label_sync()
        return result

    def _synchronize_from_moves(self, changed_fields):
        enabled_statement_lines = self.filtered(lambda statement_line: statement_line._is_bank_label_sync_enabled())
        payment_ref_by_statement = {
            statement_line.id: statement_line.payment_ref
            for statement_line in enabled_statement_lines
        }

        result = super()._synchronize_from_moves(changed_fields)
        if (
            not self.env.context.get('skip_account_move_synchronization')
            and 'line_ids' in changed_fields
        ):
            statements_to_restore = self.browse(list(payment_ref_by_statement)).filtered(
                lambda statement_line: statement_line.payment_ref != payment_ref_by_statement[statement_line.id]
            )

            for statement_line in statements_to_restore:
                statement_line.with_context(
                    skip_account_move_synchronization=True,
                    tracking_disable=True,
                ).write({'payment_ref': payment_ref_by_statement[statement_line.id]})

            enabled_statement_lines._apply_bank_label_sync()
        return result

    def _set_move_line_to_statement_line_move(self, lines_to_set, lines_to_add):
        result = super()._set_move_line_to_statement_line_move(lines_to_set, lines_to_add)
        self._apply_bank_label_sync()
        return result

    def action_undo_reconciliation(self):
        result = super().action_undo_reconciliation()
        self._apply_bank_label_sync()
        return result
