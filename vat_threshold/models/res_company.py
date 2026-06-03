# -*- coding: utf-8 -*-

from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)

#iansdsajdfaskjdfagkjf
class ResCompany(models.Model):
    _inherit = 'res.company'

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
