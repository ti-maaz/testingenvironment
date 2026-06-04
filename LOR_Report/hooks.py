import logging


_logger = logging.getLogger(__name__)


def post_init_hook(env):
    try:
        env['res.company']._sync_lor_template_defaults_to_latest_source()
    except Exception:  # pragma: no cover
        # Never block module install/upgrade for a non-critical template sync.
        _logger.exception("LOR_Report post-init sync failed; install/upgrade continues")
