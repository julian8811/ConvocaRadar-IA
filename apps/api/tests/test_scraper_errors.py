"""Tests for app.scraper.errors — error classification for scraper pipeline.

TDD Cycle: tests written FIRST, then errors.py implementation.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.scraper.errors import ErrorType, classify_error


class TestClassifyErrorTimeout:
    """ERR-2: asyncio.TimeoutError → TIMEOUT."""

    def test_asyncio_timeout(self) -> None:
        """asyncio.TimeoutError should classify as TIMEOUT."""
        result = classify_error(asyncio.TimeoutError("simulated timeout"))
        assert result == ErrorType.TIMEOUT

    def test_bare_timeout_error(self) -> None:
        """TimeoutError (base of asyncio.TimeoutError) should classify as TIMEOUT."""
        result = classify_error(TimeoutError("simulated timeout"))
        assert result == ErrorType.TIMEOUT


class TestClassifyErrorNetwork:
    """ERR-2: httpx.HTTPError / ConnectionError → NETWORK."""

    def test_httpx_http_error(self) -> None:
        """httpx.HTTPError should classify as NETWORK."""
        result = classify_error(httpx.HTTPError("HTTP error"))
        assert result == ErrorType.NETWORK

    def test_httpx_request_error(self) -> None:
        """httpx.RequestError (subclass of HTTPError) should classify as NETWORK."""
        result = classify_error(httpx.RequestError("connection refused"))
        assert result == ErrorType.NETWORK

    def test_connection_error(self) -> None:
        """ConnectionError should classify as NETWORK."""
        result = classify_error(ConnectionError("connection refused"))
        assert result == ErrorType.NETWORK

    def test_connection_refused_error(self) -> None:
        """ConnectionRefusedError (subclass of ConnectionError) should classify as NETWORK."""
        result = classify_error(ConnectionRefusedError("connection refused"))
        assert result == ErrorType.NETWORK


class TestClassifyErrorUnknown:
    """ERR-2: Anything else → UNKNOWN."""

    def test_value_error(self) -> None:
        """ValueError should classify as UNKNOWN."""
        result = classify_error(ValueError("invalid value"))
        assert result == ErrorType.UNKNOWN

    def test_runtime_error(self) -> None:
        """RuntimeError should classify as UNKNOWN."""
        result = classify_error(RuntimeError("unexpected error"))
        assert result == ErrorType.UNKNOWN

    def test_type_error(self) -> None:
        """TypeError should classify as UNKNOWN."""
        result = classify_error(TypeError("bad type"))
        assert result == ErrorType.UNKNOWN

    def test_parse_error_placeholder(self) -> None:
        """A generic Exception from connector parse/validate should be UNKNOWN
        until we add connector-specific subclasses."""
        result = classify_error(Exception("parse failed"))
        assert result == ErrorType.UNKNOWN


class TestErrorTypeEnum:
    """Verify ErrorType enum values and behavior."""

    def test_string_values(self) -> None:
        """ErrorType members should have expected string values."""
        assert ErrorType.TIMEOUT.value == "TIMEOUT"
        assert ErrorType.NETWORK.value == "NETWORK"
        assert ErrorType.PARSE.value == "PARSE"
        assert ErrorType.UNKNOWN.value == "UNKNOWN"

    def test_str_representation(self) -> None:
        """str(ErrorType.X) should return the value string."""
        assert str(ErrorType.TIMEOUT) == "TIMEOUT"
        assert str(ErrorType.NETWORK) == "NETWORK"
        assert str(ErrorType.PARSE) == "PARSE"
        assert str(ErrorType.UNKNOWN) == "UNKNOWN"

    def test_all_members_covered(self) -> None:
        """All four error types from ERR-1 must exist."""
        expected = {"TIMEOUT", "NETWORK", "PARSE", "UNKNOWN"}
        actual = {m.value for m in ErrorType}
        assert actual == expected
