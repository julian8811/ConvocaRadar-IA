"""Error classification for the scraper pipeline.

Provides a ``classify_error`` pure function that maps exceptions to
``ErrorType`` values, enabling structured error handling in the runner.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum

import httpx


class ErrorType(StrEnum):
    """Categorised error types for scraper operations.

    Members
    -------
    TIMEOUT
        `asyncio.TimeoutError` / `TimeoutError` — the scrape exceeded the
        per-source time budget.
    NETWORK
        `httpx.HTTPError` / `ConnectionError` — network-level failures
        (DNS, connection refused, TLS, HTTP 4xx/5xx).
    PARSE
        Connector-level parse / validation failures — the data was fetched
        but could not be understood.
    UNKNOWN
        Anything that doesn't match the above categories.
    """

    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    PARSE = "PARSE"
    UNKNOWN = "UNKNOWN"


def classify_error(exc: Exception) -> ErrorType:
    """Classify a scrape exception into an ``ErrorType``.

    Parameters
    ----------
    exc : Exception
        The exception raised during scraping.

    Returns
    -------
    ErrorType
        The matching error category.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return ErrorType.TIMEOUT
    if isinstance(exc, httpx.HTTPError) or isinstance(exc, ConnectionError):
        return ErrorType.NETWORK
    return ErrorType.UNKNOWN
