from odoo import _, api, fields, models


LAKH_CURRENCIES = {'AFN', 'BDT', 'INR', 'MMK', 'NPR', 'PKR', 'LKR'}


class AccountReport(models.Model):
    _inherit = 'account.report'

    def _init_options_display_currency(self, options, previous_options):
        company = self._get_sender_company_for_export(options)
        company_currency = company.currency_id
        currencies = self.env['res.currency'].search([('active', '=', True)], order='name')
        if company_currency not in currencies:
            currencies |= company_currency

        selected_currency = self.env['res.currency'].browse(previous_options.get('display_currency_id')).exists()
        if selected_currency not in currencies:
            selected_currency = company_currency

        options['display_currency_id'] = selected_currency.id
        options['display_currency_name'] = selected_currency.name
        options['display_currency_options'] = [
            {'id': currency.id, 'name': currency.name}
            for currency in currencies
        ]

    def _init_options_rounding_unit(self, options, previous_options):
        super()._init_options_rounding_unit(options, previous_options)
        options['rounding_unit_names'] = self._get_rounding_unit_names(
            self._get_selected_display_currency(options)
        )

    def _get_rounding_unit_names(self, currency=None):
        currency = currency or self.env.company.currency_id
        rounding_unit_names = [
            ('decimals', (f'.{currency.symbol}', '')),
            ('units', (f'{currency.symbol}', '')),
            ('thousands', (f'K{currency.symbol}', _('Amounts in Thousands'))),
            ('millions', (f'M{currency.symbol}', _('Amounts in Millions'))),
        ]
        if currency.name in LAKH_CURRENCIES:
            rounding_unit_names.insert(3, ('lakhs', (f'L{currency.symbol}', _('Amounts in Lakhs'))))
        return dict(rounding_unit_names)

    @api.model
    def _get_selected_display_currency(self, options):
        company_currency = self._get_sender_company_for_export(options).currency_id
        currency = self.env['res.currency'].browse(options.get('display_currency_id')).exists()
        return currency or company_currency

    @api.model
    def _get_display_currency_date(self, options, column_group_key=None):
        group_options = options.get('column_groups', {}).get(column_group_key, {}).get('forced_options', {})
        date_options = group_options.get('date') or options.get('date') or {}
        return fields.Date.to_date(
            date_options.get('date_to')
            or date_options.get('date_from')
            or self.env.context.get('date')
            or fields.Date.context_today(self)
        )

    @api.model
    def _convert_display_currency_amount(self, amount, from_currency, to_currency, company, conversion_date, rate_cache):
        if not amount or not to_currency or from_currency == to_currency:
            return amount

        cache_key = (
            company.id,
            from_currency.id,
            to_currency.id,
            fields.Date.to_string(conversion_date),
        )
        rate = rate_cache.get(cache_key)
        if rate is None:
            try:
                rate = from_currency._convert(1.0, to_currency, company, conversion_date, round=False)
            except TypeError:
                rate = self.env['res.currency']._get_conversion_rate(
                    from_currency, to_currency, company, conversion_date
                )
            rate_cache[cache_key] = rate

        return to_currency.round(amount * rate)

    @api.model
    def _get_display_currency_source_currency(self, column_dict, company_currency):
        format_params = column_dict.get('format_params') or {}
        currency_id = format_params.get('currency_id')
        if not currency_id and getattr(column_dict.get('currency'), 'id', False):
            currency_id = column_dict['currency'].id
        if not currency_id:
            return company_currency

        currency = self.env['res.currency'].browse(currency_id).exists()
        if not currency:
            return company_currency
        if currency != company_currency:
            return None
        return currency

    @api.model
    def _apply_display_currency_to_columns(self, options, line_dict_list):
        company = self._get_sender_company_for_export(options)
        company_currency = company.currency_id
        display_currency = self._get_selected_display_currency(options)
        if display_currency == company_currency:
            return

        rate_cache = {}
        for line_dict in line_dict_list:
            for column_dict in line_dict.get('columns', []):
                if column_dict.get('figure_type') != 'monetary':
                    continue

                source_currency = self._get_display_currency_source_currency(column_dict, company_currency)
                if not source_currency:
                    continue
                if (
                    column_dict.get('_display_currency_id') == display_currency.id
                    and column_dict.get('_display_currency_source_currency_id') == source_currency.id
                ):
                    continue

                amount = column_dict.get('no_format')
                if amount is None:
                    continue

                format_params = dict(column_dict.get('format_params') or {})
                format_params['currency_id'] = display_currency.id
                column_dict['format_params'] = format_params
                column_dict['digits'] = display_currency.decimal_places
                if options.get('multi_currency'):
                    column_dict['currency_symbol'] = display_currency.symbol

                if amount:
                    conversion_date = self._get_display_currency_date(
                        options, column_dict.get('column_group_key')
                    )
                    column_dict['no_format'] = self._convert_display_currency_amount(
                        amount,
                        source_currency,
                        display_currency,
                        company,
                        conversion_date,
                        rate_cache,
                    )

                if isinstance(column_dict.get('no_format'), (int, float)):
                    column_dict['is_zero'] = display_currency.is_zero(column_dict['no_format'])

                column_dict['_display_currency_id'] = display_currency.id
                column_dict['_display_currency_source_currency_id'] = source_currency.id
                column_dict.pop('name', None)

    def _format_column_values(self, options, line_dict_list, force_format=False):
        self._apply_display_currency_to_columns(options, line_dict_list)
        return super()._format_column_values(options, line_dict_list, force_format=force_format)

    def _inject_report_options_into_xlsx_sheet(self, options, sheet, y_offset, options_to_print=None):
        y_offset = super()._inject_report_options_into_xlsx_sheet(
            options, sheet, y_offset, options_to_print=options_to_print
        )
        if options.get('display_currency_name') and (
            not options_to_print
            or 'display_currency' in options_to_print
            or 'display_currency_id' in options_to_print
        ):
            sheet.write(y_offset, 0, _('Display Currency'))
            sheet.write(y_offset, 1, options['display_currency_name'])
            y_offset += 1
        return y_offset
