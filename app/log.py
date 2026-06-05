"""
Logger estructurado (structlog) + helper JSON-lines para runs persistentes.
"""
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

import structlog

from .config import get_settings

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "automiq") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def write_run_log(filename: str, payload: Dict[str, Any]) -> Path:
    """Persiste un JSON-line en logs/<filename>.jsonl (útil para auditoría de runs)."""
    target = LOG_DIR / f"{filename}.jsonl"
    payload = {"ts": int(time.time() * 1000), **payload}
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target
