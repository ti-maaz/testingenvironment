import logging
import re

from odoo import models


_logger = logging.getLogger(__name__)


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    def _prepare_reconciliation_rule_data(self, statement_lines, account_id):
        rule_data = super()._prepare_reconciliation_rule_data(statement_lines, account_id)
        if not rule_data:
            return rule_data

        pattern = rule_data.get('common_substring')
        if not pattern:
            return rule_data

        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error:
            _logger.warning(
                "Skipping auto reconciliation rule creation due to invalid generated regex: %r (statement_line_ids=%s)",
                pattern,
                statement_lines.ids,
            )
            return {}

        return rule_data
