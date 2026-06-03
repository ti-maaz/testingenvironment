from odoo import api, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _get_lines_to_sync_bank_label(self):
        return self.filtered(
            lambda line:
                line.statement_line_id
                and line.statement_line_id.journal_id.type in ('bank', 'cash')
                and line.statement_line_id.journal_id.use_bank_label_in_gl
                and line.statement_line_id.payment_ref
                and line.name != line.statement_line_id.payment_ref
        )

    def _enforce_payment_ref_label(self):
        if self.env.context.get('skip_bank_label_sync_enforcement'):
            return

        lines_to_sync = self._get_lines_to_sync_bank_label()
        if not lines_to_sync:
            return

        lines_by_label = {}
        line_model = self.env['account.move.line']
        for line in lines_to_sync:
            label = line.statement_line_id.payment_ref
            lines_by_label.setdefault(label, line_model)
            lines_by_label[label] |= line

        for label, lines in lines_by_label.items():
            lines.with_context(
                skip_account_move_synchronization=True,
                skip_bank_label_sync_enforcement=True,
                tracking_disable=True,
            ).write({'name': label})

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._enforce_payment_ref_label()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'account_id'} & set(vals):
            self._enforce_payment_ref_label()
        return result
