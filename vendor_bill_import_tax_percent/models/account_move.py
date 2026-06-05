import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo import _, api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    _VENDOR_IMPORT_MOVE_TYPES = {'in_invoice', 'in_refund'}
    _TAX_PERCENT_QUANT = Decimal('0.0001')
    _SINGLE_PERCENT_TOKEN_RE = re.compile(
        r'^\s*(?P<number>(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<percent>%)?\s*$'
    )

    @api.model
    def _convert_records(self, records, *, log=lambda a: None, savepoint):
        """Normalize vendor bill line tax percentages before ORM conversion.

        Odoo's import engine has already extracted the file into nested raw
        records at this point, but many2many relational values have not yet
        been resolved. Rewriting only numeric invoice_line_ids/tax_ids values
        to database-id references lets the standard converter, create pipeline,
        onchange/recompute logic, and tax computation continue unchanged.
        """
        if not self.env.context.get('import_file'):
            return super()._convert_records(records, log=log, savepoint=savepoint)

        return super()._convert_records(
            self._iter_records_with_vendor_tax_percent_refs(records, log),
            log=log,
            savepoint=savepoint,
        )

    @api.model
    def _iter_records_with_vendor_tax_percent_refs(self, records, log):
        for stream_index, (record, extras) in enumerate(records):
            self._normalize_vendor_bill_import_tax_refs(record, extras, stream_index, log)
            yield record, extras

    @api.model
    def _normalize_vendor_bill_import_tax_refs(self, record, extras, stream_index, log):
        if self._get_import_move_type(record) not in self._VENDOR_IMPORT_MOVE_TYPES:
            return

        invoice_lines = record.get('invoice_line_ids') or []
        if not invoice_lines:
            return

        company = self._get_import_company(record)
        for line in invoice_lines:
            tax_refs = line.get('tax_ids')
            if not tax_refs:
                continue
            normalized_refs = self._get_normalized_tax_refs(
                tax_refs,
                company,
                extras,
                stream_index,
                log,
            )
            if normalized_refs is not None:
                line['tax_ids'] = normalized_refs

    @api.model
    def _get_normalized_tax_refs(self, tax_refs, company, extras, stream_index, log):
        """Return .id refs for numeric percentage tokens, or None to keep Odoo behavior."""
        if not isinstance(tax_refs, list) or len(tax_refs) != 1:
            return None

        [tax_ref] = tax_refs
        if not isinstance(tax_ref, dict) or set(tax_ref) != {None}:
            return None

        raw_value = tax_ref.get(None)
        if self._is_empty_import_value(raw_value):
            return None

        unsupported_message = self._get_unsupported_multi_tax_message(raw_value)
        if unsupported_message:
            self._log_import_tax_error(log, extras, stream_index, unsupported_message)
            return []

        percentage = self._parse_percentage_like_token(raw_value)
        if percentage is None:
            return None

        if not company:
            self._log_import_tax_error(
                log,
                extras,
                stream_index,
                _(
                    "Unable to resolve the bill company before converting numeric tax value '%(value)s'. "
                    "Import a resolvable Company or Journal, or import the tax by name/external ID.",
                    value=raw_value,
                ),
            )
            return []

        tax = self._find_unique_purchase_tax_by_percentage(percentage, company, raw_value, extras, stream_index, log)
        if not tax:
            return []

        return [{'.id': str(tax.id)}]

    @api.model
    def _get_unsupported_multi_tax_message(self, value):
        if not isinstance(value, str) or ',' not in value:
            return False

        tokens = [token.strip() for token in value.split(',') if token.strip()]
        if not any(self._parse_percentage_like_token(token) is not None for token in tokens):
            return False

        return _(
            "Multiple or mixed numeric percentage tax values are not supported in one import cell: '%(value)s'. "
            "Use one numeric percentage value per imported bill line, or import existing taxes by name/external ID.",
            value=value,
        )

    @api.model
    def _parse_percentage_like_token(self, value):
        """Convert 5, 5%, and 0.05 style values to a tax amount percentage."""
        if isinstance(value, bool) or value is None:
            return None

        has_percent_sign = False
        if isinstance(value, (int, float, Decimal)):
            number_text = str(value)
        elif isinstance(value, str):
            match = self._SINGLE_PERCENT_TOKEN_RE.match(value)
            if not match:
                return None
            number_text = match.group('number')
            has_percent_sign = bool(match.group('percent'))
        else:
            return None

        try:
            number = Decimal(number_text)
        except InvalidOperation:
            return None

        if number < 0:
            return None

        if not has_percent_sign and Decimal('0') < number < Decimal('1'):
            number *= Decimal('100')

        return number.quantize(self._TAX_PERCENT_QUANT, rounding=ROUND_HALF_UP)

    @api.model
    def _find_unique_purchase_tax_by_percentage(self, percentage, company, raw_value, extras, stream_index, log):
        Tax = self.env['account.tax'].with_company(company).with_context(
            allowed_company_ids=[company.id],
            active_test=False,
        )
        taxes = Tax.search([
            ('amount', '=', float(percentage)),
            ('amount_type', 'in', ('percent', 'division')),
            ('type_tax_use', '=', 'purchase'),
            ('active', '=', True),
            ('company_id', '=', company.id),
        ])

        if not taxes:
            self._log_import_tax_error(
                log,
                extras,
                stream_index,
                _(
                    "No active purchase percentage tax with amount %(amount)s%% was found for company '%(company)s' "
                    "while converting imported tax value '%(value)s'.",
                    amount=self._format_decimal_percentage(percentage),
                    company=company.display_name,
                    value=raw_value,
                ),
            )
            return self.env['account.tax']

        if len(taxes) > 1:
            preferred_tax = self._select_plain_percentage_tax(taxes, percentage)
            if preferred_tax:
                return preferred_tax

            tax_names = ', '.join("%s (ID %s)" % (tax.display_name, tax.id) for tax in taxes[:5])
            self._log_import_tax_error(
                log,
                extras,
                stream_index,
                _(
                    "Multiple active purchase percentage taxes with amount %(amount)s%% were found for company "
                    "'%(company)s': %(taxes)s. Import the tax by name/external ID or make the tax setup unique.",
                    amount=self._format_decimal_percentage(percentage),
                    company=company.display_name,
                    taxes=tax_names,
                ),
            )
            return self.env['account.tax']

        return taxes

    @api.model
    def _select_plain_percentage_tax(self, taxes, percentage):
        """Prefer the unique tax whose own label is only the imported rate.

        Localizations can contain several purchase taxes with the same amount
        for special treatments such as reverse charge or exempt purchases. A
        tax named exactly "5%" is a deterministic plain-rate match, while names
        like "5% R C" remain explicit relation values for Odoo's standard parser.
        """
        plain_taxes = taxes.filtered(
            lambda tax: self._is_plain_percentage_tax_label(tax.name, percentage)
        )
        return plain_taxes if len(plain_taxes) == 1 else self.env['account.tax']

    @api.model
    def _is_plain_percentage_tax_label(self, label, percentage):
        return self._parse_percentage_like_token(label) == percentage

    @api.model
    def _get_import_move_type(self, record):
        raw_move_type = record.get('move_type') or self.env.context.get('default_move_type')
        if raw_move_type:
            return self._normalize_move_type_value(raw_move_type)

        default_move_type = self.default_get(['move_type']).get('move_type')
        return self._normalize_move_type_value(default_move_type)

    @api.model
    def _normalize_move_type_value(self, value):
        if not isinstance(value, str):
            return False

        value = value.strip()
        if not value:
            return False

        selection = self._fields['move_type']._description_selection(self.env)
        values_by_key = {key: label for key, label in selection}
        if value in values_by_key:
            return value

        value_casefold = value.casefold()
        for key, label in selection:
            if value_casefold in {str(key).casefold(), str(label).casefold()}:
                return key
        return False

    @api.model
    def _get_import_company(self, record):
        explicit_company = record.get('company_id')
        if explicit_company:
            company = self._resolve_import_many2one(explicit_company, 'res.company')
            return company if company else self.env['res.company']

        journal = self._resolve_import_many2one(record.get('journal_id'), 'account.journal')
        if journal and journal.company_id:
            return journal.company_id

        default_company_id = self.env.context.get('default_company_id')
        if default_company_id:
            company = self.env['res.company'].browse(default_company_id).exists()
            if company:
                return company

        return self.env.company

    @api.model
    def _resolve_import_many2one(self, value, model_name):
        if not value:
            return self.env[model_name]

        subfield = None
        reference = value
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict) or len(value[0]) != 1:
                return self.env[model_name]
            subfield, reference = next(iter(value[0].items()))

        if self._is_empty_import_value(reference):
            return self.env[model_name]

        Model = self.env[model_name]
        if subfield == '.id':
            try:
                return Model.browse(int(reference)).exists()
            except (TypeError, ValueError):
                return Model

        if subfield == 'id':
            xmlid = str(reference).strip()
            if '.' not in xmlid:
                xmlid = "%s.%s" % (self.env.context.get('_import_current_module', '__import__'), xmlid)
            record = self.env.ref(xmlid, raise_if_not_found=False)
            return record if record and record._name == model_name else Model

        if subfield is None and isinstance(reference, str):
            matches = Model.name_search(name=reference.strip(), operator='=', limit=2)
            return Model.browse(matches[0][0]) if len(matches) == 1 else Model

        return Model

    @api.model
    def _is_empty_import_value(self, value):
        return value is None or value is False or (isinstance(value, str) and not value.strip())

    @api.model
    def _log_import_tax_error(self, log, extras, stream_index, message):
        log(dict(
            extras,
            type='error',
            record=stream_index,
            field='invoice_line_ids/tax_ids',
            message=message,
        ))

    @api.model
    def _format_decimal_percentage(self, value):
        text = format(value.normalize(), 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return text or '0'
