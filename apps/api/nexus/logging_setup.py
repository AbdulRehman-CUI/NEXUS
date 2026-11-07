"""Console JSON limited to application-generated safe fields; third-party logs remain separate."""

import json
import logging
from datetime import datetime, timezone


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "event": record.getMessage(),
            },
            ensure_ascii=True,
        )


def configure_logging():
    logger = logging.getLogger("nexus")
    if not any(getattr(handler, "nexus_safe", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.nexus_safe = True
        handler.setFormatter(SafeFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
