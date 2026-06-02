import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Configure document layout for all companies that have not been set up yet."""
    companies = env['res.company'].search([])
    _logger.info("document_layout_defaults: applying layout defaults to %d company(ies).", len(companies))
    for company in companies:
        company._apply_document_layout_defaults()
