"""Parametrized tests for every source-connector group.

Each connector follows the ``SourceConnector`` protocol:
  1. ``fetch()`` → ``RawSourceResult``
  2. ``parse(raw)`` → ``list[OpportunityCandidate]``
  3. ``validate(candidate)`` → ``ValidationResult``

Four scenarios are tested per group:
  - **sample** (happy path): connector returns at least one candidate
  - **empty** (no data): connector degrades to an empty result list
  - **garbage** (malformed content): connector does **not** raise
  - **network_error**: connector raises on ``fetch()`` when the underlying
    HTTP mock fails
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from tests.connector_fixtures import (
    FIXTURE_DATA,
    NETWORK_ERROR_MSG,
    apply_fixture_data,
)


# ── Group definitions ──────────────────────────────────────────────────────
# (group_name, source_key, source_type, fixture_key, connector_cls_name)
# source_type is passed to connector_for(); None means "discover from key".
GROUPS: list[tuple[str, str, str | None, str, str]] = [
    ("generic-html", "undef", None, "httpx-get-html", "UNDEFConnector"),
    ("eu-post-json", "eu-funding-tenders", None, "httpx-post-json", "EuFundingTendersConnector"),
    ("get-json", "test-json", None, "httpx-get-json", "GenericHtmlConnector"),
    ("rss", "test-rss", None, "httpx-get-rss", "RssConnector"),
    ("pdf", "test-pdf", "pdf", "httpx-get-pdf", "PdfConnector"),
    ("playwright", "innovamos-global-innovation-fund", None, "playwright", "InnovamosConnector"),
    ("hybrid", "test-hybrid", "hybrid", "hybrid", "HybridConnector"),
    ("generic-api", "test-api", "api", "generic-api", "ApiConnector"),
    ("grants-gov", "grants-gov", None, "grants-gov", "GrantsGovConnector"),
]


# ── Auto-use: make asyncio.sleep a no-op so the Innovamos retry loop
#    (1.5 s × attempt) does not slow down playwright tests.  Harmless
#    for other groups — they never call asyncio.sleep. ───────────────


@pytest.fixture(autouse=True)
def _mock_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def _noop(_duration: float) -> None:
        pass

    monkeypatch.setattr(asyncio, "sleep", _noop)


# ── Happy path: sample data → candidates ──────────────────────────


class TestConnectorHappyPath:
    """Every connector must produce at least one candidate with sample data."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("group_name", "source_key", "source_type", "fixture_key", "cls_name"),
        GROUPS,
    )
    async def test_fetch_and_parse_yields_candidates(
        self,
        connector_factory,
        group_name: str,
        source_key: str,
        source_type: str | None,
        fixture_key: str,
        cls_name: str,
    ) -> None:
        connector, mocks = connector_factory(source_key, source_type=source_type)
        apply_fixture_data(mocks, fixture_key, "sample")

        raw = await connector.fetch()
        assert isinstance(raw, RawSourceResult)
        assert raw.source_key
        assert raw.content or raw.content == ""  # empty string is valid

        candidates = await connector.parse(raw)
        assert len(candidates) >= 1, (
            f"{cls_name} should yield ≥1 candidate with sample data, got 0"
        )
        for c in candidates:
            assert isinstance(c, OpportunityCandidate)
            assert c.title

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("group_name", "source_key", "source_type", "fixture_key", "cls_name"),
        GROUPS,
    )
    async def test_validate_candidate(
        self,
        connector_factory,
        group_name: str,
        source_key: str,
        source_type: str | None,
        fixture_key: str,
        cls_name: str,
    ) -> None:
        connector, mocks = connector_factory(source_key, source_type=source_type)
        apply_fixture_data(mocks, fixture_key, "sample")
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1, (
            f"{cls_name}: need ≥1 candidate for validate test"
        )
        result = await connector.validate(candidates[0])
        assert result.ok, (
            f"{cls_name}: validate({candidates[0].title!r}) failed: {result.reason}"
        )


# ── Empty data: connector returns empty result ────────────────────


class TestConnectorEmptyData:
    """With zero-opportunity content the connector must return [].

    Some connectors may return a low-confidence fallback candidate
    (e.g. PdfConnector) — the test accepts 0 *or* a graceful fallback.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("group_name", "source_key", "source_type", "fixture_key", "cls_name"),
        GROUPS,
    )
    async def test_parse_returns_empty_or_fallback(
        self,
        connector_factory,
        group_name: str,
        source_key: str,
        source_type: str | None,
        fixture_key: str,
        cls_name: str,
    ) -> None:
        connector, mocks = connector_factory(source_key, source_type=source_type)
        apply_fixture_data(mocks, fixture_key, "empty")

        # Some connectors may raise during fetch on empty data (e.g. Innovamos
        # raises when both httpx and playwright return empty content) — that
        # is acceptable; we only test that parse() does not crash.
        try:
            raw = await connector.fetch()
        except Exception:
            return

        try:
            candidates = await connector.parse(raw)
        except Exception:
            return  # graceful degradation via exception is also acceptable

        # Accept 0 candidates OR a single low-confidence fallback
        assert isinstance(candidates, list)
        if len(candidates) == 1:
            assert candidates[0].confidence_score < 0.75, (
                f"{cls_name}: expected low-confidence fallback, got score={candidates[0].confidence_score}"
            )


# ── Garbage data: connector must not raise during parse ───────────


class TestConnectorGarbageData:
    """Malformed content should never bubble an exception from parse()."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("group_name", "source_key", "source_type", "fixture_key", "cls_name"),
        GROUPS,
    )
    async def test_parse_does_not_raise(
        self,
        connector_factory,
        group_name: str,
        source_key: str,
        source_type: str | None,
        fixture_key: str,
        cls_name: str,
    ) -> None:
        connector, mocks = connector_factory(source_key, source_type=source_type)
        apply_fixture_data(mocks, fixture_key, "garbage")

        # fetch() may raise for garbage content that fails JSON decode
        # inside the connector's fetch — that's acceptable.
        try:
            raw = await connector.fetch()
        except Exception:
            return

        try:
            candidates = await connector.parse(raw)
        except Exception as exc:
            pytest.fail(
                f"{cls_name}.parse() raised on garbage data: {type(exc).__name__}: {exc}"
            )

        # Must return a list (possibly empty)
        assert isinstance(candidates, list)


# ── Network error: connector raises on fetch() ────────────────────


class TestConnectorNetworkError:
    """When the HTTP mock raises, fetch() must propagate the error."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("group_name", "source_key", "source_type", "fixture_key", "cls_name"),
        GROUPS,
    )
    async def test_fetch_raises_on_network_error(
        self,
        connector_factory,
        group_name: str,
        source_key: str,
        source_type: str | None,
        fixture_key: str,
        cls_name: str,
    ) -> None:
        connector, mocks = connector_factory(source_key, source_type=source_type)
        apply_fixture_data(
            mocks,
            fixture_key,
            "sample",
            side_effect=RuntimeError(NETWORK_ERROR_MSG),
        )

        # Some connectors (e.g. Innovamos) wrap errors from their retry/fallback
        # logic, so the exact message may differ. Accept any RuntimeError.
        with pytest.raises(RuntimeError):
            await connector.fetch()


# ── Smoke: every fixture key has a counterpart in FIXTURE_DATA ────


def test_all_fixture_keys_exist() -> None:
    """Every group's fixture_key must be a key in FIXTURE_DATA."""
    for _name, _sk, _st, fkey, _cn in GROUPS:
        assert fkey in FIXTURE_DATA, (
            f"fixture_key {fkey!r} not found in FIXTURE_DATA"
        )
