from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    use_bank_label_in_gl = fields.Boolean(
        string='Use Bank Transaction Label in GL',
        default=False,
        help=(
            "When enabled, all statement-linked General Ledger journal item labels on this bank or cash journal "
            "are automatically replaced with the bank transaction label (payment_ref)."
        ),
    )

    def _sync_statement_gl_labels_from_payment_ref(self):
        statement_line_model = self.env['account.bank.statement.line']
        enabled_journals = self.filtered(lambda journal: journal.type in ('bank', 'cash') and journal.use_bank_label_in_gl)
        if not enabled_journals:
            return

        domain = [
            ('journal_id', 'in', enabled_journals.ids),
            ('move_id', '!=', False),
            ('payment_ref', '!=', False),
        ]
        last_id = 0

        while True:
            statement_lines = statement_line_model.search(domain + [('id', '>', last_id)], order='id', limit=1000)
            if not statement_lines:
                break
            statement_lines._apply_bank_label_sync()
            last_id = statement_lines[-1].id

    def write(self, vals):
        result = super().write(vals)
        if 'use_bank_label_in_gl' in vals:
            self._sync_statement_gl_labels_from_payment_ref()
        return result
