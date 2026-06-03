from odoo import _, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_check_missing_customer_invoice_serials(self):
        missing_serial_moves = self.env['account.move'].search(
            self._get_missing_customer_invoice_serial_domain(),
            order='sequence_prefix, sequence_number, date, id',
            limit=1,
        )
        if not missing_serial_moves:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Missing Serials'),
                    'message': _('No missing posted customer invoice serials were found.'),
                    'type': 'success',
                    'sticky': False,
                },
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Missing Customer Invoice Serials'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('account.view_out_invoice_tree').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': (self.env.ref('account.view_account_invoice_filter').id, 'search'),
            'domain': self._get_missing_customer_invoice_serial_domain(),
            'context': {
                'default_move_type': 'out_invoice',
                'search_default_out_invoice': 1,
                'search_default_group_by_sequence_prefix': 1,
                'expand': 1,
            },
        }

    def _get_missing_customer_invoice_serial_domain(self):
        return [
            ('company_id', 'in', self.env.companies.ids),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('made_sequence_gap', '=', True),
            ('sequence_number', '!=', 0),
            ('name', 'not in', [False, '/']),
        ]
