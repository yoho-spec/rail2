"""
utils/logger.py
Centralized logging configuration.
In production: INFO level, structured format.
In development: DEBUG level, verbose.
"""
import logging
import os
import sys


def setup_logging():
    env = os.environ.get("ENVIRONMENT", "production")
    level = logging.DEBUG if env == "development" else logging.INFO

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=date_fmt,
        stream=sys.stdout,
    )

    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
