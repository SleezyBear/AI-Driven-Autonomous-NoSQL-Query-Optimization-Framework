"""Secret-safe structured logging and bounded operational metrics."""

from __future__ import annotations

import logging
import sys
from typing import Any, MutableMapping

import structlog
from prometheus_client import Counter, Histogram

from app.security.redaction import redact_value


HTTP_REQUESTS = Counter(
    "nosql_optimizer_http_requests_total",
    "Completed HTTP requests.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "nosql_optimizer_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
READINESS_FAILURES = Counter(
    "nosql_optimizer_readiness_failures_total",
    "Control-plane readiness dependency failures.",
    ("service",),
)


def _redact_event(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    redacted = redact_value(dict(event_dict))
    assert isinstance(redacted, dict)
    return redacted


def configure_logging() -> None:
    """Emit one JSON object per event without interpolating exception bodies."""
    logging.basicConfig(stream=sys.stdout, format="%(message)s", level=logging.INFO, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
