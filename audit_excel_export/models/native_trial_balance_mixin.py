import logging

from odoo import fields


_logger = logging.getLogger(__name__)


class NativeTrialBalanceMixin:
    """Local native Trial Balance extraction helpers for audit Excel export."""

    @staticmethod
    def _tb_to_float(value):
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(',', '').strip()
            if not cleaned:
                return 0.0
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        return 0.0

    def _tb_normalize_account_row(self, row, balance_role=None):
        normalized = dict(row or {})
        resolved_role = str(balance_role or normalized.get('balance_role') or '').strip().lower()
        if resolved_role not in ('opening', 'movement', 'closing'):
            resolved_role = (
                'closing'
                if any(key in normalized for key in ('initial_balance', 'end_balance', 'movement_balance'))
                else 'movement'
            )

        initial_balance = self._tb_to_float(normalized.get('initial_balance'))
        debit = self._tb_to_float(normalized.get('debit'))
        credit = self._tb_to_float(normalized.get('credit'))
        movement_balance = self._tb_to_float(
            normalized.get('movement_balance', debit - credit)
        )
        if 'end_balance' in normalized:
            end_balance = self._tb_to_float(normalized.get('end_balance'))
        elif resolved_role == 'closing' and 'balance' in normalized:
            end_balance = self._tb_to_float(normalized.get('balance'))
        else:
            end_balance = initial_balance + movement_balance

        normalized.update({
            'initial_balance': initial_balance,
            'debit': debit,
            'credit': credit,
            'movement_balance': movement_balance,
            'end_balance': end_balance,
            'balance_role': resolved_role,
        })
        if resolved_role == 'opening':
            normalized['balance'] = initial_balance
        elif resolved_role == 'movement':
            normalized['balance'] = movement_balance
        else:
            normalized['balance'] = end_balance
        return normalized

    def _tb_project_account_rows(self, rows, balance_role='closing'):
        return [
            self._tb_normalize_account_row(row, balance_role=balance_role)
            for row in (rows or [])
        ]

    def _tb_get_odoo_trial_balance_report(self, company):
        report = self.env.ref('account_reports.trial_balance_report', raise_if_not_found=False)
        if not report:
            return False
        return report.with_company(company).with_context(
            allowed_company_ids=[company.id]
        )

    def _tb_build_trial_balance_options(self, trial_balance_report, company, date_start, date_end):
        return trial_balance_report.get_options({
            'selected_variant_id': trial_balance_report.id,
            'date': {
                'date_from': date_start or False,
                'date_to': date_end,
                'mode': 'range',
                'filter': 'custom',
            },
            'unfold_all': True,
            'hierarchy': False,
            'show_account': True,
            'report_title': (
                f"{getattr(self, 'display_name', False) or company.name or 'Audit Excel Export'} Trial Balance"
            ),
        })

    def _tb_period_dates_from_options(self, options):
        date_options = (options or {}).get('date') or {}
        date_to_raw = date_options.get('date_to')
        if not date_to_raw:
            return False, False

        mode = date_options.get('mode') or 'range'
        date_start = date_options.get('date_from') if mode == 'range' else False
        return (
            fields.Date.to_date(date_start) if date_start else False,
            fields.Date.to_date(date_to_raw),
        )

    def _tb_target_column_groups(self, options, date_start=False, date_end=False):
        normalized_start = fields.Date.to_string(fields.Date.to_date(date_start)) if date_start else False
        normalized_end = fields.Date.to_string(fields.Date.to_date(date_end)) if date_end else False

        ordered_period_identities = []
        period_groups_by_identity = {}
        for column in (options or {}).get('columns', []):
            column_group_key = column.get('column_group_key')
            if not column_group_key:
                continue
            column_group = (options or {}).get('column_groups', {}).get(column_group_key) or {}
            forced_options = column_group.get('forced_options') or {}
            if forced_options.get('trial_balance_column_type') != 'period':
                continue

            column_date = forced_options.get('date') or {}
            identity = (
                forced_options.get('trial_balance_column_block_id') or False,
                (column_date.get('mode') or 'range'),
                column_date.get('date_from') or False,
                column_date.get('date_to') or False,
            )
            if identity not in period_groups_by_identity:
                ordered_period_identities.append(identity)
                period_groups_by_identity[identity] = []
            if column_group_key not in period_groups_by_identity[identity]:
                period_groups_by_identity[identity].append(column_group_key)

        if not ordered_period_identities:
            return {}

        matching_identity = None
        for identity in ordered_period_identities:
            _block_id, mode, group_date_start, group_date_end = identity
            effective_group_start = group_date_start if mode == 'range' else False
            if (
                (effective_group_start or False) == (normalized_start or False)
                and (group_date_end or False) == (normalized_end or False)
            ):
                matching_identity = identity
                break

        target_identity = matching_identity or ordered_period_identities[-1]
        target_block_id = target_identity[0]
        target_groups = {
            'initial_balance': set(),
            'period': set(),
            'end_balance': set(),
        }
        for column in (options or {}).get('columns', []):
            column_group_key = column.get('column_group_key')
            if not column_group_key:
                continue
            column_group = (options or {}).get('column_groups', {}).get(column_group_key) or {}
            forced_options = column_group.get('forced_options') or {}
            column_type = forced_options.get('trial_balance_column_type')
            if column_type not in target_groups:
                continue
            if (forced_options.get('trial_balance_column_block_id') or False) != target_block_id:
                continue
            target_groups[column_type].add(column_group_key)
        return target_groups

    def _tb_collect_column_totals(self, line, target_group_keys):
        totals = {
            'debit': 0.0,
            'credit': 0.0,
            'balance': 0.0,
        }
        if not target_group_keys:
            return False, totals

        matched_column = False
        matched_balance_column = False
        for column in (line or {}).get('columns', []):
            if column.get('column_group_key') not in target_group_keys:
                continue
            matched_column = True
            expression_label = column.get('expression_label')
            value = self._tb_to_float(column.get('no_format'))
            if expression_label == 'debit':
                totals['debit'] += value
            elif expression_label == 'credit':
                totals['credit'] += value
            elif expression_label == 'balance':
                totals['balance'] += value
                matched_balance_column = True

        if matched_column and not matched_balance_column:
            totals['balance'] = totals['debit'] - totals['credit']
        return matched_column, totals

    def _tb_extract_native_rows_from_trial_balance_lines(self, company, trial_balance_report, options, lines):
        target_date_start, target_date_end = self._tb_period_dates_from_options(options)
        if not target_date_end:
            return []

        target_column_groups = self._tb_target_column_groups(
            options,
            target_date_start,
            target_date_end,
        )
        if not target_column_groups.get('period'):
            return []

        account_ids = set()
        amounts_by_account = {}
        for line in lines:
            line_id = line.get('id')
            if not line_id:
                continue
            account_id = trial_balance_report._get_res_id_from_line_id(line_id, 'account.account')
            if not account_id:
                continue

            initial_matched, initial_totals = self._tb_collect_column_totals(
                line,
                target_column_groups.get('initial_balance') or set(),
            )
            period_matched, period_totals = self._tb_collect_column_totals(
                line,
                target_column_groups.get('period') or set(),
            )
            end_matched, end_totals = self._tb_collect_column_totals(
                line,
                target_column_groups.get('end_balance') or set(),
            )
            if not (initial_matched or period_matched or end_matched):
                continue

            initial_balance = initial_totals['balance']
            if not initial_matched and end_matched:
                initial_balance = end_totals['balance'] - period_totals['debit'] + period_totals['credit']

            movement_balance = period_totals['debit'] - period_totals['credit']
            end_balance = end_totals['balance']
            if not end_matched:
                end_balance = initial_balance + movement_balance

            account_ids.add(account_id)
            amounts_by_account[account_id] = {
                'initial_balance': initial_balance,
                'debit': period_totals['debit'],
                'credit': period_totals['credit'],
                'movement_balance': movement_balance,
                'end_balance': end_balance,
            }

        if not account_ids:
            return []

        account_env = self.env['account.account'].with_company(company).with_context(
            allowed_company_ids=[company.id]
        )
        account_map = {account.id: account for account in account_env.browse(list(account_ids))}

        rows = []
        for account_id, amounts in amounts_by_account.items():
            account = account_map.get(account_id)
            if not account:
                continue
            code_raw = (account.code or account.code_store or '').strip()
            code = self._normalize_account_code(code_raw)
            if not code:
                continue
            rows.append({
                'id': account.id,
                'code': code,
                'code_raw': code_raw,
                'name': account.name,
                'type': account.account_type,
                'initial_balance': self._tb_to_float(amounts.get('initial_balance')),
                'debit': self._tb_to_float(amounts.get('debit')),
                'credit': self._tb_to_float(amounts.get('credit')),
                'movement_balance': self._tb_to_float(amounts.get('movement_balance')),
                'end_balance': self._tb_to_float(amounts.get('end_balance')),
                'balance_role': 'closing',
                'balance': self._tb_to_float(amounts.get('end_balance')),
            })

        rows.sort(key=lambda row: (row.get('code') or '', row.get('id') or 0))
        return rows

    def _tb_fetch_rows_from_odoo_trial_balance(self, company, date_start, date_end):
        if not date_end:
            return []

        trial_balance_report = self._tb_get_odoo_trial_balance_report(company)
        if not trial_balance_report:
            return None

        options = self._tb_build_trial_balance_options(
            trial_balance_report,
            company,
            date_start,
            date_end,
        )
        lines = trial_balance_report._get_lines(options)
        return self._tb_extract_native_rows_from_trial_balance_lines(
            company,
            trial_balance_report,
            options,
            lines,
        )

    def _tb_fetch_grouped_move_line_rows(self, company, date_start, date_end):
        if not date_end:
            return []

        domain = [
            ('date', '<=', date_end),
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
        ]
        if date_start:
            domain.insert(0, ('date', '>=', date_start))

        move_line_env = self.env['account.move.line'].with_context(
            allowed_company_ids=[company.id]
        )
        grouped_rows = move_line_env._read_group(
            domain=domain,
            groupby=['account_id'],
            aggregates=['debit:sum', 'credit:sum', 'balance:sum'],
        )

        account_ids = [account.id for account, _debit, _credit, _balance in grouped_rows if account]
        account_env = self.env['account.account'].with_company(company).with_context(
            allowed_company_ids=[company.id]
        )
        account_map = {account.id: account for account in account_env.browse(account_ids)}

        final_rows = []
        for account_row, debit_sum, credit_sum, _balance_sum in grouped_rows:
            if not account_row:
                continue
            account = account_map.get(account_row.id)
            if not account:
                continue
            code_raw = (account.code or account.code_store or '').strip()
            code = self._normalize_account_code(code_raw)
            if not code:
                continue
            debit_value = self._tb_to_float(debit_sum)
            credit_value = self._tb_to_float(credit_sum)
            final_rows.append({
                'id': account.id,
                'code': code,
                'code_raw': code_raw,
                'name': account.name,
                'type': account.account_type,
                'debit': debit_value,
                'credit': credit_value,
                'balance': debit_value - credit_value,
            })

        final_rows.sort(key=lambda row: (row.get('code') or '', row.get('id') or 0))
        return final_rows

    def _tb_fetch_movement_rows(self, company, date_start, date_end):
        if not date_end:
            return []

        try:
            rows = self._tb_fetch_rows_from_odoo_trial_balance(
                company,
                date_start,
                date_end,
            )
            if rows is None:
                rows = self._tb_fetch_grouped_move_line_rows(
                    company,
                    date_start,
                    date_end,
                )
        except Exception as err:
            _logger.exception(
                "Falling back to raw grouped move-line TB rows for %s id=%s due to: %s",
                getattr(self, '_name', self.__class__.__name__),
                getattr(self, 'id', False),
                err,
            )
            rows = self._tb_fetch_grouped_move_line_rows(
                company,
                date_start,
                date_end,
            )

        return self._tb_project_account_rows(rows, balance_role='movement')
