from . import models
from .hooks import post_init_hook

import logging

_logger = logging.getLogger(__name__)

try:
	from . import controllers
except Exception:  # pragma: no cover
	# Keep the module loadable even if HTTP route imports fail in one environment.
	_logger.exception("LOR_Report controllers failed to load; continuing without HTTP routes")
