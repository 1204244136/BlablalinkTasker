"""Logging setup helpers."""

from __future__ import annotations

import logging
import sys


def configure_logging(verbose: bool = False) -> None:
    """Configure console logging for CLI execution."""

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    if not verbose:
        logging.getLogger("asyncio").setLevel(logging.WARNING)
