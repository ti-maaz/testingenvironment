from odoo import _, fields, models


class AuditInvoiceBillReportHandler(models.AbstractModel):
    _name = 'audit.invoice.bill.report.handler'
    _inherit = ['account.report.custom.handler']
    _description = 'Audit Invoice/Bill Report Custom Handler'

    _LINE_VISIBLE_EXPRESSION_LABELS = (
        'line_label',
        'line_account',
        'line_analytic',
        'line_start_date',
        'line_end_date',
        'line_quantity',
        'line_price',
        'line_taxes',
        'line_vat_amount',
        'line_amount',
    )
    _NON_AMOUNT_DISPLAY_TYPES = {
        'line_section',
        'line_subsection',
        'line_note',
    }

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options=previous_options)

        options['invoice_bill_report_kind'] = self._get_report_kind(report, previous_options)
        options['invoice_bill_scope'] = self._sanitize_invoice_bill_scope(previous_options.get('invoice_bill_scope'))
        options['include_refunds'] = bool(previous_options.get('include_refunds', True))
        options['include_dynamic_columns'] = bool(previous_options.get('include_dynamic_columns', True))
        self._apply_invoice_line_layout(options)

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        moves = self._query_moves(report, options)
        if not moves:
            return []

        lines = []

        for move in moves:
            move_name = move.name or move.payment_reference or '/'
            parent_line_id = report._get_generic_line_id('account.move', move.id)

            lines.append((0, {
                'id': parent_line_id,
                'name': _('-------- %(invoice)s --------', invoice=move_name),
                'level': 2,
                'columns': self._build_columns_from_values(report, options, self._build_parent_values()),
            }))

            for move_line in move.invoice_line_ids.sorted(lambda line: (line.sequence, line.id)):
                move_line_values = self._build_move_line_values(move_line)
                lines.append((0, {
                    'id': report._get_generic_line_id('account.move.line', move_line.id, parent_line_id=parent_line_id),
                    'parent_id': parent_line_id,
                    'name': '',
                    'level': 3,
                    'columns': self._build_columns_from_values(report, options, move_line_values),
                }))

        return lines

    def _build_columns_from_values(self, report, options, value_map):
        columns = []
        for column in options['columns']:
            value = value_map.get(column['expression_label'])
            columns.append(report._build_column_dict(value, column, options=options))
        return columns

    def _query_moves(self, report, options):
        company_ids = report.get_report_company_ids(options)
        date_options = options.get('date', {}) or {}
        date_from = fields.Date.to_date(date_options.get('date_from')) if date_options.get('date_from') else False
        date_to = fields.Date.to_date(date_options.get('date_to')) if date_options.get('date_to') else False

        domain = [
            ('move_type', 'in', self._get_move_types(options)),
            ('company_id', 'in', company_ids),
        ]
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))

        state_scope = self._get_state_scope(options)
        if state_scope:
            domain.append(('state', 'in', state_scope))

        selected_journal_ids = self._get_selected_journal_ids(options)
        if selected_journal_ids:
            domain.append(('journal_id', 'in', selected_journal_ids))

        partner_ids = [int(partner_id) for partner_id in options.get('partner_ids', [])]
        if partner_ids:
            domain.append(('partner_id', 'in', partner_ids))

        search_term = (options.get('filter_search_bar') or '').strip()
        if search_term:
            domain.extend([
                '|', '|', '|',
                ('name', 'ilike', search_term),
                ('ref', 'ilike', search_term),
                ('partner_id.name', 'ilike', search_term),
                ('journal_id.name', 'ilike', search_term),
            ])

        return self.env['account.move'].with_context(
            allowed_company_ids=company_ids,
            active_test=False,
        ).search(domain, order='invoice_date, id')

    def _build_parent_values(self):
        return {
            'line_label': '',
            'line_account': '',
            'line_analytic': '',
            'line_start_date': None,
            'line_end_date': None,
            'line_quantity': None,
            'line_price': None,
            'line_taxes': '',
            'line_vat_amount': None,
            'line_amount': None,
        }

    def _build_move_line_values(self, move_line):
        line_is_amount_line = move_line.display_type not in self._NON_AMOUNT_DISPLAY_TYPES
        line_subtotal = move_line.price_subtotal if line_is_amount_line else None
        line_total = move_line.price_total if line_is_amount_line else None
        line_vat_amount = (line_total - line_subtotal) if line_is_amount_line else None

        return {
            'line_label': move_line.name or move_line.product_id.display_name or '',
            'line_account': move_line.account_id.display_name or '',
            'line_analytic': self._format_analytic_distribution(move_line),
            'line_start_date': getattr(move_line, 'deferred_start_date', False) or None,
            'line_end_date': getattr(move_line, 'deferred_end_date', False) or None,
            'line_quantity': move_line.quantity if line_is_amount_line else None,
            'line_price': move_line.price_unit if line_is_amount_line else None,
            'line_taxes': ', '.join(move_line.tax_ids.mapped('name')),
            'line_vat_amount': line_vat_amount,
            'line_amount': line_total,
        }

    def _format_analytic_distribution(self, move_line):
        distribution = move_line.analytic_distribution or {}
        if not distribution:
            return ''

        account_ids = []
        for account_ids_key in distribution:
            for account_id in str(account_ids_key).split(','):
                with_value = account_id.strip()
                if with_value.isdigit():
                    account_ids.append(int(with_value))

        if not account_ids:
            return ''

        analytic_accounts = self.env['account.analytic.account'].browse(account_ids)
        name_by_id = {str(account.id): account.display_name for account in analytic_accounts}
        analytic_chunks = []
        for account_ids_key, percent in distribution.items():
            account_names = [
                name_by_id.get(account_id.strip())
                for account_id in str(account_ids_key).split(',')
            ]
            account_names = [name for name in account_names if name]
            if not account_names:
                continue
            account_name = ' + '.join(account_names)
            if percent not in (None, 100, 100.0):
                analytic_chunks.append(_('%(name)s (%(percent)s%%)', name=account_name, percent=percent))
            else:
                analytic_chunks.append(account_name)
        return ', '.join(analytic_chunks)

    def _apply_invoice_line_layout(self, options):
        columns_by_label = {}
        for column in options.get('columns', []):
            expression_label = column.get('expression_label')
            if expression_label in self._LINE_VISIBLE_EXPRESSION_LABELS:
                columns_by_label.setdefault(expression_label, []).append(column)

        line_columns = []
        for expression_label in self._LINE_VISIBLE_EXPRESSION_LABELS:
            line_columns.extend(columns_by_label.get(expression_label, []))

        if line_columns:
            options['columns'] = line_columns

    def _get_move_types(self, options):
        report_kind = options.get('invoice_bill_report_kind')
        include_refunds = bool(options.get('include_refunds', True))

        if report_kind == 'vendor':
            move_types = ['in_invoice']
            if include_refunds:
                move_types.append('in_refund')
            return move_types

        move_types = ['out_invoice']
        if include_refunds:
            move_types.append('out_refund')
        return move_types

    def _sanitize_invoice_bill_scope(self, scope):
        if scope in ('all_states', 'posted_only', 'posted_cancelled'):
            return scope
        return 'all_states'

    def _get_state_scope(self, options):
        scope = self._sanitize_invoice_bill_scope(options.get('invoice_bill_scope'))
        if scope == 'posted_only':
            return ['posted']
        if scope == 'posted_cancelled':
            return ['posted', 'cancel']
        return ['draft', 'posted', 'cancel']

    def _get_selected_journal_ids(self, options):
        selected_journal_ids = []
        for journal_option in options.get('journals', []):
            if journal_option.get('model') != 'account.journal':
                continue
            if not journal_option.get('selected'):
                continue
            journal_id = journal_option.get('id')
            if isinstance(journal_id, int):
                selected_journal_ids.append(journal_id)
        return selected_journal_ids

    def _get_report_kind(self, report, previous_options):
        report_kind = previous_options.get('invoice_bill_report_kind')
        if report_kind in ('customer', 'vendor'):
            return report_kind

        report_xmlid = report.get_external_id().get(report.id)
        if report_xmlid == 'audit_excel_export.audit_vendor_bills_report':
            return 'vendor'
        return 'customer'
