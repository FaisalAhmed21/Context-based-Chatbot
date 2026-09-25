

from __future__ import annotations

import logging
import sys

def setup_logging(level: str = "INFO") -> None:

    root = logging.getLogger()
    if getattr(root, "_rag_configured", False):
        return

    numeric = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)

    for name in ("httpx", "httpcore", "urllib3", "qdrant_client", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("app").setLevel(numeric)
    root._rag_configured = True  
