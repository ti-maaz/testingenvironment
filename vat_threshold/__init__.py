# -*- coding: utf-8 -*-

from . import models
import logging
from datetime import datetime, time, timedelta

_logger = logging.getLogger(__name__)


def _next_run_at(target_time):
    now = datetime.now()
    today_target = datetime.combine(now.date(), target_time)
    if now < today_target:
        return today_target
    return datetime.combine(now.date() + timedelta(days=1), target_time)


def post_init_setup(env):
    """
    Post-init hook to create VAT threshold records for existing companies.
    This ensures all existing companies have a VAT threshold record after module install.
    """
    # Get all companies
    companies = env['res.company'].search([])
    
    # Get existing threshold records
    existing_thresholds = env['vat.threshold'].search([])
    existing_company_ids = existing_thresholds.mapped('company_id.id')
    
    # Create threshold records for companies that don't have one
    for company in companies:
        if company.id not in existing_company_ids:
            env['vat.threshold'].create({
                'company_id': company.id,
            })
            _logger.info("Created VAT threshold record for existing company: %s", company.name)

    cron_schedule = {
        'vat_threshold.cron_recompute_revenue_daily': time(7, 0),
        'vat_threshold.cron_check_vat_threshold': time(7, 0),
        'vat_threshold.cron_send_daily_report': time(7, 5),
    }
    for xmlid, run_time in cron_schedule.items():
        cron = env.ref(xmlid, raise_if_not_found=False)
        if cron:
            cron.nextcall = _next_run_at(run_time)
    
    _logger.info("VAT Threshold post-init setup completed. Total companies: %d", len(companies))
