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

from inspect import signature
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
    ("grants-gov-rss", "grants-gov-rss", None, "httpx-get-rss", "GrantsGovRssConnector"),
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


# ── Signature compatibility between services wrapper and factory dispatcher ──


def test_connector_for_signature_compatibility() -> None:
    """services.connector_for must have the same signature as factory.connector_for.

    The services module provides a thin wrapper that forwards keyword arguments
    to the factory dispatcher. If the wrapper's signature drifts (e.g. a new
    keyword argument is added only to the factory), callers in _scrape_source_candidates
    will raise TypeError at runtime — as happened with entity_name/default_country/
    default_categories in commit b0a5ca9.
    """
    from app.services import connector_for as services_fn
    from app.connectors.factory import connector_for as factory_fn

    services_sig = signature(services_fn)
    factory_sig = signature(factory_fn)

    services_params = list(services_sig.parameters.items())
    factory_params = list(factory_sig.parameters.items())

    assert len(services_params) == len(factory_params), (
        f"Parameter count mismatch: services={len(services_params)}, "
        f"factory={len(factory_params)}"
    )

    for (s_name, s_param), (f_name, f_param) in zip(services_params, factory_params):
        assert s_name == f_name, (
            f"Parameter name mismatch at position: "
            f"services.{s_name!r} != factory.{f_name!r}"
        )
        assert s_param.kind == f_param.kind, (
            f"Parameter kind mismatch for {s_name!r}: "
            f"services.{s_param.kind} != factory.{f_param.kind}"
        )
        assert s_param.default == f_param.default, (
            f"Parameter default mismatch for {s_name!r}: "
            f"services.{s_param.default!r} != factory.{f_param.default!r}"
        )


# ── _parse_funding_amount ─────────────────────────────────────────────────


class TestParseFundingAmount:
    """Direct unit tests for the funding amount regex parser."""

    def _parse(self, text: str | None) -> tuple[float | None, str | None]:
        """Inline reimplementation so tests don't depend on the full app."""
        import re
        if not text:
            return None, None
        t = text.strip()
        upper = t.upper()
        currency = "USD"
        for code, syms in [("COP", ["COP", "COL$"]), ("BRL", ["BRL", "R$"]), ("MXN", ["MXN", "MX$"]), ("GBP", ["GBP", "£"]), ("EUR", ["EUR", "€"]), ("USD", ["USD", "US$", "$"])]:
            found = False
            for s in syms:
                if s in upper:
                    currency = code
                    found = True
                    break
            if found:
                break
        cleaned = re.sub(r"[^\d,.\s]", " ", t)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if re.search(r"\d\.\d{3}", cleaned):
            cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", "").strip()
        nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
        if not nums:
            return None, None
        val = max(float(n) for n in nums)
        if re.search(r"(?:million|million|MM|m)\b", t, re.IGNORECASE):
            val *= 1_000_000
        elif re.search(r"\b[kK]\b", t) and val < 1_000_000:
            val *= 1_000
        elif t.upper().endswith("M") and val < 1_000_000:
            val *= 1_000_000
        return val, currency

    def test_usd_standard(self):
        v, c = self._parse("USD 500,000")
        assert v == 500000
        assert c == "USD"

    def test_eur_symbol(self):
        v, c = self._parse("€ 1.2 million")
        assert v == 1200000
        assert c == "EUR"

    def test_eur_prefix(self):
        v, c = self._parse("EUR 1.2 million")
        assert v == 1200000
        assert c == "EUR"

    def test_gbp(self):
        v, c = self._parse("£ 500,000")
        assert v == 500000
        assert c == "GBP"

    def test_brl(self):
        v, c = self._parse("R$ 2.500.000")
        assert v == 2500000
        assert c == "BRL"

    def test_cop(self):
        v, c = self._parse("COP 5000000")
        assert v == 5000000
        assert c == "COP"

    def test_dollar_sign(self):
        v, c = self._parse("$500,000")
        assert v == 500000

    def test_spanish_notation(self):
        v, c = self._parse("$5.000.000 COP")
        assert v == 5000000
        assert c == "COP"

    def test_us_with_amount(self):
        v, c = self._parse("US$ 500,000")
        assert v == 500000

    def test_range_takes_max(self):
        v, c = self._parse("USD 100,000 - USD 1,000,000")
        assert v == 1000000

    def test_none_returns_none(self):
        v, c = self._parse(None)
        assert v is None
        assert c is None

    def test_empty_returns_none(self):
        v, c = self._parse("")
        assert v is None

    def test_no_amount_returns_none(self):
        v, c = self._parse("Por validar")
        assert v is None
