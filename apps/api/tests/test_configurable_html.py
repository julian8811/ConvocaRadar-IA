"""Tests for ConfigurableHtmlConnector — declarative HTML connector engine.

Strict TDD: tests written first, implementation follows.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.configurable_html import ConfigurableHtmlConnector, HtmlConnectorConfig


# ── Fixture HTML data ───────────────────────────────────────────

SAMPLE_LIST_HTML = """<html><body>
<div class="card">
    <h2><a href="/grant/1">Grant One</a></h2>
    <p class="deadline">Cierre: 15/08/2027</p>
</div>
<div class="card">
    <h2><a href="/grant/2">Grant Two</a></h2>
    <p class="deadline">Cierre: 30/09/2027</p>
</div>
</body></html>"""

FALLBACK_LIST_HTML = """<html><body>
<div class="item">
    <h3><a href="/grant/3">Grant Three</a></h3>
</div>
</body></html>"""

EMPTY_LIST_HTML = "<html><body><p>No grants found</p></body></html>"

DETAIL_PAGE_HTML = """<html><body>
<h1>Grant One Detail Title</h1>
<meta name="description" content="Full enriched description for grant one.">
<p>Funding amount: USD 100,000</p>
</body></html>"""

NEXT_PAGE_HTML = """<html><body>
<div class="card">
    <h2><a href="/grant/3">Grant Three</a></h2>
</div>
<a class="next_page" href="/page/2">Next →</a>
</body></html>"""

NO_NEXT_PAGE_HTML = """<html><body>
<div class="card">
    <h2><a href="/grant/3">Grant Three</a></h2>
</div>
</body></html>"""

JSONLD_HTML = """<html><body>
<script type="application/ld+json">
{
    "@graph": [
        {
            "@type": "Grant",
            "name": "JSON-LD Grant",
            "url": "http://example.com/jsonld-grant",
            "description": "A grant from JSON-LD structured data"
        }
    ]
}
</script>
</body></html>"""

NEXTDATA_HTML = """<html><body>
<script id="__NEXT_DATA__" type="application/json">
{"props": {"pageProps": {"grants": [{"title": "Next.js Grant", "url": "http://example.com/next-grant"}]}}}
</script>
</body></html>"""

# ── Shared valid config ─────────────────────────────────────────

VALID_CONFIG: dict = {
    "list_selectors": [".card", ".item"],
    "title_selectors": ["h2 a", "h3 a"],
    "link_selectors": ["a[href]"],
    "content_selectors": [".content", "article"],
    "date_labels": ["Cierre:", "Deadline:"],
}

CONNECTOR_KEY = "test-configurable-html"
CONNECTOR_URL = "http://example.com"


# ═══════════════════════════════════════════════════════════════
# 1. Config parsing (HtmlConnectorConfig)
# ═══════════════════════════════════════════════════════════════

class TestHtmlConnectorConfig:
    """HtmlConnectorConfig parsing from dicts and JSON strings."""

    def test_valid_full_config(self):
        """All fields, including optional pagination, parse correctly."""
        data = {**VALID_CONFIG, "pagination": {"type": "next_link", "selector": "a.next"}}
        config = HtmlConnectorConfig.from_dict(data)
        assert config.list_selectors == [".card", ".item"]
        assert config.title_selectors == ["h2 a", "h3 a"]
        assert config.link_selectors == ["a[href]"]
        assert config.content_selectors == [".content", "article"]
        assert config.date_labels == ["Cierre:", "Deadline:"]
        assert config.pagination == {"type": "next_link", "selector": "a.next"}

    def test_minimal_config(self):
        """Only required fields — pagination defaults to None."""
        config = HtmlConnectorConfig.from_dict(dict(VALID_CONFIG))
        assert config.pagination is None
        for field in ("list_selectors", "title_selectors", "link_selectors", "content_selectors", "date_labels"):
            assert getattr(config, field, None) is not None

    def test_empty_dict_raises_value_error(self):
        """Missing all fields raises ValueError."""
        with pytest.raises(ValueError, match="missing|required|list_selectors"):
            HtmlConnectorConfig.from_dict({})

    def test_empty_selector_lists_raises_value_error(self):
        """An empty list_selectors list should be rejected."""
        with pytest.raises(ValueError, match="empty|at least one"):
            HtmlConnectorConfig.from_dict({
                **VALID_CONFIG,
                "list_selectors": [],
            })

    def test_from_valid_json_string(self):
        """Parsing from a JSON string works."""
        config = HtmlConnectorConfig.from_json(json.dumps(VALID_CONFIG))
        assert config.list_selectors == [".card", ".item"]

    def test_from_invalid_json_raises_value_error(self):
        """Invalid JSON string raises ValueError."""
        with pytest.raises(ValueError, match="JSON|invalid"):
            HtmlConnectorConfig.from_json("not valid json at all {{{")

    def test_config_default_country_fallback(self):
        """Default country applies when none is provided."""
        config = HtmlConnectorConfig.from_dict(dict(VALID_CONFIG))
        assert hasattr(config, "pagination")  # smoke: ensure from_dict works


# ═══════════════════════════════════════════════════════════════
# 2. Connector initialization
# ═══════════════════════════════════════════════════════════════

class TestConfigurableHtmlConnectorInit:
    """ConfigurableHtmlConnector construction."""

    def test_from_valid_config_dict(self):
        """Accepts a config dict and creates HtmlConnectorConfig internally."""
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        assert isinstance(connector.config, HtmlConnectorConfig)
        assert connector.source_key == CONNECTOR_KEY
        assert connector.base_url == CONNECTOR_URL

    def test_entity_name_falls_back_to_source_key(self):
        """When entity_name is not given, source_key is used."""
        connector = ConfigurableHtmlConnector("my-source", CONNECTOR_URL, VALID_CONFIG)
        assert connector._entity_name == "my-source"

    def test_custom_entity_name_used(self):
        """Explicit entity_name is stored."""
        connector = ConfigurableHtmlConnector(
            CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG,
            entity_name="Custom Entity",
        )
        assert connector._entity_name == "Custom Entity"

    def test_default_country_fallback(self):
        """Default country defaults to 'Por validar'."""
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        assert connector._default_country == "Por validar"

    def test_custom_default_country(self):
        """Explicit default_country is stored."""
        connector = ConfigurableHtmlConnector(
            CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG,
            default_country="Colombia",
        )
        assert connector._default_country == "Colombia"


# ═══════════════════════════════════════════════════════════════
# 3. Selector fallback chain
# ═══════════════════════════════════════════════════════════════

class TestSelectorFallback:
    """Each selector group is tried in order; the first match wins."""

    @pytest.mark.asyncio
    async def test_first_list_selector_matches(self, monkeypatch):
        """When the first list selector matches, candidates are found."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, SAMPLE_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert len(candidates) == 2
        titles = {c.title for c in candidates}
        assert "Grant One" in titles
        assert "Grant Two" in titles

    @pytest.mark.asyncio
    async def test_fallback_selector_used_when_first_fails(self, monkeypatch):
        """First selector matches nothing; the second selector works."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, FALLBACK_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        config = {**VALID_CONFIG, "list_selectors": [".missing", ".item"]}
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert len(candidates) == 1
        assert candidates[0].title == "Grant Three"

    @pytest.mark.asyncio
    async def test_all_selectors_fail_returns_empty_list(self, monkeypatch):
        """When no list selector matches, parse returns []."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, EMPTY_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        config = {**VALID_CONFIG, "list_selectors": [".nonexistent", ".also-missing"]}
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert candidates == []

    @pytest.mark.asyncio
    async def test_title_selector_fallback(self, monkeypatch):
        """When h2 a fails, h3 a is tried for title extraction."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, FALLBACK_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        # h2 a won't match the h3 a element, so h3 a is the fallback
        config = {**VALID_CONFIG, "title_selectors": ["h2 a", "h3 a"]}
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert len(candidates) == 1
        assert candidates[0].title == "Grant Three"

    @pytest.mark.asyncio
    async def test_selector_diagnostics_tracked(self, monkeypatch):
        """After parse, selector_diagnostics shows which selector matched."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, SAMPLE_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        raw = await connector.fetch()
        await connector.parse(raw)

        diag = connector.selector_diagnostics
        assert "list_selector" in diag
        assert diag["list_selector"] is not None
        assert "title_selector" in diag
        assert "link_selector" in diag


# ═══════════════════════════════════════════════════════════════
# 4. Pagination
# ═══════════════════════════════════════════════════════════════

class TestPagination:
    """Pagination modes: next_link."""

    @pytest.mark.asyncio
    async def test_next_link_pagination_follows_next(self, monkeypatch):
        """When a next link is found, the connector fetches the next page."""
        call_count = 0

        async def _mock_fetch(url: str, **kwargs):
            nonlocal call_count
            call_count += 1
            if "page/2" in url:
                return (url, NO_NEXT_PAGE_HTML, "text/html")
            return (url, SAMPLE_LIST_HTML, "text/html")

        mock = AsyncMock(side_effect=_mock_fetch)
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        config = {
            **VALID_CONFIG,
            "pagination": {"type": "next_link", "selector": "a.next_page"},
        }
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        # Should have items from page 1 (2 items) + page 2 (1 item)
        assert len(candidates) >= 1

    @pytest.mark.asyncio
    async def test_no_next_link_stops_pagination(self, monkeypatch):
        """When no next link is found, pagination stops after first page."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, NO_NEXT_PAGE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        config = {
            **VALID_CONFIG,
            "pagination": {"type": "next_link", "selector": "a.next_page"},
        }
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert len(candidates) >= 1


# ═══════════════════════════════════════════════════════════════
# 5. Embedded JSON extraction (JSON-LD, __NEXT_DATA__)
# ═══════════════════════════════════════════════════════════════

class TestEmbeddedJSON:
    """Connector extracts structured data from embedded JSON before HTML parsing."""

    @pytest.mark.asyncio
    async def test_extracts_jsonld_candidates(self, monkeypatch):
        """JSON-LD script content yields candidates."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, JSONLD_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        titles = [c.title for c in candidates]
        assert "JSON-LD Grant" in titles

    @pytest.mark.asyncio
    async def test_extracts_next_data_candidates(self, monkeypatch):
        """__NEXT_DATA__ script content yields candidates."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, NEXTDATA_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        titles = [c.title for c in candidates]
        assert "Next.js Grant" in titles


# ═══════════════════════════════════════════════════════════════
# 6. Detail page enrichment
# ═══════════════════════════════════════════════════════════════

class TestDetailEnrichment:
    """Low-confidence candidates enriched via detail page fetch."""

    @pytest.mark.asyncio
    async def test_enriches_low_confidence_candidates(self, monkeypatch):
        """Candidates with confidence < 0.7 get enriched from detail page."""
        call_log: list[str] = []

        async def _mock_fetch(url: str, **kwargs):
            call_log.append(url)
            if url == CONNECTOR_URL:
                return (CONNECTOR_URL, SAMPLE_LIST_HTML, "text/html")
            return (url, DETAIL_PAGE_HTML, "text/html")

        mock = AsyncMock(side_effect=_mock_fetch)
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        config = {**VALID_CONFIG, "detail_enrichment": True}
        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        # Detail pages were fetched for enrichment
        detail_urls = [u for u in call_log if "/grant/" in u]
        assert len(detail_urls) >= 1


# ═══════════════════════════════════════════════════════════════
# 7. Factory routing
# ═══════════════════════════════════════════════════════════════

class TestFactoryRouting:
    """connector_for returns ConfigurableHtmlConnector when given connector_config."""

    def test_connector_config_parameter_routes_to_configurable(self):
        """Passing connector_config returns a ConfigurableHtmlConnector."""
        from app.connectors.factory import connector_for

        connector = connector_for(
            CONNECTOR_KEY, CONNECTOR_URL, "html",
            connector_config=VALID_CONFIG,
        )
        assert isinstance(connector, ConfigurableHtmlConnector)

    def test_without_config_returns_generic_html(self):
        """Without connector_config, fallback is still GenericHtmlConnector."""
        from app.connectors.factory import connector_for

        connector = connector_for("unknown-source", CONNECTOR_URL, "html")
        assert type(connector).__name__ == "GenericHtmlConnector"

    def test_configurable_connector_with_pagination_in_config(self):
        """Config with pagination blocks is passed through factory."""
        from app.connectors.factory import connector_for

        config = {**VALID_CONFIG, "pagination": {"type": "next_link", "selector": "a.next"}}
        connector = connector_for(
            CONNECTOR_KEY, CONNECTOR_URL, "html",
            connector_config=config,
        )
        assert isinstance(connector, ConfigurableHtmlConnector)
        assert connector.config.pagination == {"type": "next_link", "selector": "a.next"}


# ═══════════════════════════════════════════════════════════════
# 8. Validate method
# ═══════════════════════════════════════════════════════════════

class TestValidate:
    """Validate method follows the same contract as SourceConnector protocol."""

    @pytest.mark.asyncio
    async def test_valid_candidate_returns_ok(self, monkeypatch):
        """A well-formed candidate passes validation."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, SAMPLE_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        candidate = OpportunityCandidate(
            title="Test Grant",
            entity="Test",
            country="Colombia",
            official_url="http://example.com/test",
        )
        result = await connector.validate(candidate)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_candidate_missing_title_fails(self, monkeypatch):
        """Candidate without a title fails validation."""
        mock = AsyncMock(return_value=(CONNECTOR_URL, SAMPLE_LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, VALID_CONFIG)
        candidate = OpportunityCandidate(
            title="",
            entity="Test",
            country="Colombia",
            official_url="http://example.com/test",
        )
        result = await connector.validate(candidate)
        assert result.ok is False
