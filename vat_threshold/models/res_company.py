# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Self-defined so this module is standalone. If another module (e.g.
    # company_exte) also declares this field, Odoo merges the two definitions
    # onto the same column with no conflict.
    vat_registration_number = fields.Char(string="VAT Registration Number")

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-create VAT threshold record for new companies"""
        companies = super(ResCompany, self).create(vals_list)

        # Auto-create VAT threshold record for each new company
        threshold_model = self.env['vat.threshold'].sudo()
        for company in companies:
            if not threshold_model.search([('company_id', '=', company.id)], limit=1):
                threshold_model.create({
                    'company_id': company.id,
                })
                _logger.info("Auto-created VAT threshold record for company: %s", company.name)

        return companies
