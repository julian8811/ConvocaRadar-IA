"""Tests for DevelopmentAid.org tender connector.

Covers the full two-phase sitemap-driven extraction:
  1. fetch() discovers URLs from sitemaps
  2. parse() fetches detail pages and extracts structured metadata
  3. validate() enforces title + official_url presence
  4. dedup key integration
  5. Protocol contract
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.development_aid import (
    DevelopmentAidConnector,
    SITEMAP_INDEX_URL,
    MAX_DETAIL_PAGES,
)


# ── Mini HTML fixtures (mimic Angular SSR row markup) ───────────────────

_TENDER_HTML_OPEN = """<html>
<body>
<div class="main-content">
  <h1 class="name" data-id="item_title">Solar Energy Tender</h1>
  <div class="item-info">
    <span>Location:</span>
    <span class="tag">Kenya</span>
    <span>Status:</span>
    <span class="tag">Open</span>
    <span>Sectors:</span>
    <span class="tag">Energy, Renewable Energy</span>
    <span>Category:</span>
    <span class="tag">Infrastructure</span>
    <span>Funding Agency:</span>
    <a href="/org/123">World Bank</a>
    <span>Posted:</span>
    <span class="tag">2025-06-15</span>
  </div>
  <div class="injected-content view-excerpt ng-star-inserted">This tender is for solar energy infrastructure development in rural Kenya.</div>
</div>
</body>
</html>"""

_TENDER_HTML_FORECAST = """<html>
<body>
<div class="main-content">
  <h1 class="name" data-id="item_title">Water Management Tender</h1>
  <div class="item-info">
    <span>Location:</span>
    <span class="tag">Ethiopia</span>
    <span>Status:</span>
    <span class="tag">Forecast</span>
    <span>Sectors:</span>
    <span class="tag">Water &amp; Sanitation</span>
    <span>Category:</span>
    <span class="tag">Environment</span>
    <span>Funding Agency:</span>
    <a href="/org/456">African Development Bank</a>
    <span>Posted:</span>
    <span class="tag">2025-07-01</span>
  </div>
  <div class="injected-content view-excerpt">Water resource management and sanitation improvement project.</div>
</div>
</body>
</html>"""

_TENDER_HTML_CLOSED = """<html>
<body>
<div class="main-content">
  <h1 class="name" data-id="item_title">Expired Health Tender</h1>
  <div class="item-info">
    <span>Location:</span>
    <span class="tag">Nigeria</span>
    <span>Status:</span>
    <span class="tag">Closed</span>
    <span>Sectors:</span>
    <span class="tag">Health</span>
    <span>Category:</span>
    <span class="tag">Social Services</span>
    <span>Funding Agency:</span>
    <a href="/org/789">WHO</a>
  </div>
  <div class="injected-content view-excerpt">Already closed health tender.</div>
</div>
</body>
</html>"""

_TENDER_HTML_MINIMAL = """<html>
<body>
<div class="main-content">
  <h1 class="name" data-id="item_title">Minimal Tender</h1>
  <div class="item-info">
    <span>Status:</span>
    <span class="tag">Open</span>
  </div>
</div>
</body>
</html>"""

_TENDER_HTML_NO_TITLE = """<html>
<body>
<div class="main-content">
  <p>No tender title here</p>
  <div class="item-info">
    <span>Status:</span>
    <span class="tag">Open</span>
    <span>Location:</span>
    <span class="tag">Kenya</span>
  </div>
</div>
</body>
</html>"""

_TENDER_HTML_OPEN_RESTRICTED = """<html>
<body>
<div class="main-content">
  <h1 class="name" data-id="item_title">Restricted Tender</h1>
  <div class="item-info">
    <span>Location:</span>
    <span class="tag">Uganda</span>
    <span>Status:</span>
    <span class="tag">Open (Restricted)</span>
    <span>Sectors:</span>
    <span class="tag">Agriculture</span>
  </div>
</div>
</body>
</html>"""

# ── Sitemap XML fixtures ──────────────────────────────────────────────

_SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://www.developmentaid.org/tenders_sitemap_1.xml</loc>
    <lastmod>2025-07-01T00:00:00Z</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://www.developmentaid.org/tenders_sitemap_2.xml</loc>
    <lastmod>2025-07-01T00:00:00Z</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://www.developmentaid.org/tenders_sitemap_3.xml</loc>
    <lastmod>2025-07-01T00:00:00Z</lastmod>
  </sitemap>
</sitemapindex>"""

_SITEMAP_EMPTY_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</sitemapindex>"""

_SITEMAP_SUB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.developmentaid.org/tenders/view/123</loc>
    <lastmod>2025-06-15T00:00:00Z</lastmod>
  </url>
  <url>
    <loc>https://www.developmentaid.org/tenders/view/456</loc>
    <lastmod>2025-07-01T00:00:00Z</lastmod>
  </url>
  <url>
    <loc>https://www.developmentaid.org/tenders/view/789</loc>
    <lastmod>2025-06-20T00:00:00Z</lastmod>
  </url>
</urlset>"""

_SITEMAP_SUB_XML_LARGE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
"""
# Generate 10 entries
for i in range(1000, 1010):
    _SITEMAP_SUB_XML_LARGE += f"""  <url>
    <loc>https://www.developmentaid.org/tenders/view/{i}</loc>
    <lastmod>2025-07-{i % 28 + 1:02d}T00:00:00Z</lastmod>
  </url>
"""
_SITEMAP_SUB_XML_LARGE += "</urlset>"


# ── Helpers ───────────────────────────────────────────────────────────

def _make_connector(connector_config=None):
    """Create a DevelopmentAidConnector instance with defaults."""
    return DevelopmentAidConnector(
        "developmentaid-tenders",
        SITEMAP_INDEX_URL,
        connector_config=connector_config,
    )


def _mock_fetch_side_effect(urls_map: dict[str, tuple[str, str, str]]):
    """Build an async side_effect that returns content based on URL."""
    async def _side_effect(url, **kwargs):
        if url in urls_map:
            return urls_map[url]
        raise RuntimeError(f"Unexpected URL: {url}")
    return _side_effect


# ═══════════════════════════════════════════════════════════════════════
# Unit Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSitemapParsing:
    """T4.1: Unit tests for sitemap URL discovery."""

    def test_fetch_sitemap_urls_happy_path(self):
        """Parse a sitemap index with 3 sub-sitemap entries."""
        connector = _make_connector()
        from app.connectors.development_aid import _parse_sitemap_index
        urls = _parse_sitemap_index(_SITEMAP_INDEX_XML)
        assert len(urls) == 3
        assert urls[0] == "https://www.developmentaid.org/tenders_sitemap_1.xml"
        assert urls[1] == "https://www.developmentaid.org/tenders_sitemap_2.xml"
        assert urls[2] == "https://www.developmentaid.org/tenders_sitemap_3.xml"

    def test_fetch_sitemap_urls_empty(self):
        """Empty sitemap index returns empty list."""
        connector = _make_connector()
        from app.connectors.development_aid import _parse_sitemap_index
        urls = _parse_sitemap_index(_SITEMAP_EMPTY_INDEX_XML)
        assert urls == []

    def test_parse_sitemap_entries(self):
        """Extract loc + lastmod from a sub-sitemap."""
        connector = _make_connector()
        from app.connectors.development_aid import _parse_sitemap_entries
        entries = _parse_sitemap_entries(_SITEMAP_SUB_XML)
        assert len(entries) == 3
        assert entries[0]["loc"] == "https://www.developmentaid.org/tenders/view/123"
        assert entries[0]["lastmod"] == "2025-06-15T00:00:00Z"
        assert entries[1]["loc"] == "https://www.developmentaid.org/tenders/view/456"
        assert entries[2]["loc"] == "https://www.developmentaid.org/tenders/view/789"

    def test_parse_sitemap_entries_empty(self):
        """Empty sub-sitemap returns empty list."""
        empty_xml = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        connector = _make_connector()
        from app.connectors.development_aid import _parse_sitemap_entries
        entries = _parse_sitemap_entries(empty_xml)
        assert entries == []

    def test_parse_sitemap_entries_malformed(self):
        """Malformed XML returns empty list (S1.4 — graceful degradation)."""
        connector = _make_connector()
        from app.connectors.development_aid import _parse_sitemap_entries
        entries = _parse_sitemap_entries("not valid xml at all <<<>>>")
        assert entries == []


class TestFieldExtraction:
    """T4.2: Unit tests for _extract_fields_from_html()."""

    def test_extract_full_fields(self):
        """Extract all fields from a rich HTML fixture."""
        from app.connectors.development_aid import _extract_fields_from_html
        fields = _extract_fields_from_html(
            _TENDER_HTML_OPEN,
            "https://www.developmentaid.org/tenders/view/123"
        )
        assert fields is not None
        assert fields["title"] == "Solar Energy Tender"
        assert fields["country"] == "Kenya"
        assert fields["status"] == "Open"
        assert "Energy" in fields["sectors"]
        assert fields["category"] == "Infrastructure"
        assert fields["funding_agency"] == "World Bank"
        assert "solar energy" in fields["excerpt"].lower()

    def test_extract_minimal_fields(self):
        """Extract from HTML with only title and status."""
        from app.connectors.development_aid import _extract_fields_from_html
        fields = _extract_fields_from_html(
            _TENDER_HTML_MINIMAL,
            "https://www.developmentaid.org/tenders/view/999"
        )
        assert fields is not None
        assert fields["title"] == "Minimal Tender"
        assert fields["status"] == "Open"
        # Missing fields should default to empty
        assert fields["country"] == ""
        assert fields["sectors"] == ""

    def test_extract_missing_title_returns_none(self):
        """HTML without <h1 class="name"> returns None."""
        from app.connectors.development_aid import _extract_fields_from_html
        fields = _extract_fields_from_html(
            _TENDER_HTML_NO_TITLE,
            "https://www.developmentaid.org/tenders/view/555"
        )
        assert fields is None

    def test_extract_open_restricted_status(self):
        """Prefix match: "Open (Restricted)" is captured as "Open (Restricted)"."""
        from app.connectors.development_aid import _extract_fields_from_html
        fields = _extract_fields_from_html(
            _TENDER_HTML_OPEN_RESTRICTED,
            "https://www.developmentaid.org/tenders/view/777"
        )
        assert fields is not None
        assert fields["title"] == "Restricted Tender"
        assert "Open" in fields["status"]


class TestStatusFilter:
    """T4.3: Unit tests for status filtering."""

    def test_accepts_open(self):
        """Status "Open" is accepted (case-insensitive)."""
        from app.connectors.development_aid import _status_is_accepted
        assert _status_is_accepted("Open") is True
        assert _status_is_accepted("open") is True
        assert _status_is_accepted("OPEN") is True

    def test_accepts_forecast(self):
        """Status "Forecast" is accepted."""
        from app.connectors.development_aid import _status_is_accepted
        assert _status_is_accepted("Forecast") is True
        assert _status_is_accepted("forecast") is True

    def test_accepts_open_prefix(self):
        """Status strings starting with "Open" are accepted."""
        from app.connectors.development_aid import _status_is_accepted
        assert _status_is_accepted("Open (Restricted)") is True
        assert _status_is_accepted("Open - Limited") is True

    def test_rejects_closed(self):
        """"Closed" status is rejected."""
        from app.connectors.development_aid import _status_is_accepted
        assert _status_is_accepted("Closed") is False
        assert _status_is_accepted("Awarded") is False
        assert _status_is_accepted("Evaluation") is False
        assert _status_is_accepted("Shortlisted") is False
        assert _status_is_accepted("Cancelled") is False

    def test_rejects_empty(self):
        """Empty status is rejected."""
        from app.connectors.development_aid import _status_is_accepted
        assert _status_is_accepted("") is False
        assert _status_is_accepted("   ") is False


class TestValidate:
    """T4.4: Unit tests for validate()."""

    @pytest.mark.asyncio
    async def test_valid_candidate(self):
        """Candidate with title and official_url passes validation."""
        connector = _make_connector()
        candidate = OpportunityCandidate(
            title="Solar Energy Tender",
            entity="World Bank",
            country="Kenya",
            official_url="https://www.developmentaid.org/tenders/view/123",
            summary="Test summary",
        )
        result = await connector.validate(candidate)
        assert isinstance(result, ValidationResult)
        assert result.ok is True
        assert result.reason == ""

    @pytest.mark.asyncio
    async def test_invalid_empty_title(self):
        """Candidate with empty title fails validation."""
        connector = _make_connector()
        candidate = OpportunityCandidate(
            title="",
            entity="World Bank",
            country="Kenya",
            official_url="https://www.developmentaid.org/tenders/view/123",
        )
        result = await connector.validate(candidate)
        assert result.ok is False
        assert "title" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_missing_url(self):
        """Candidate with empty official_url fails validation."""
        connector = _make_connector()
        candidate = OpportunityCandidate(
            title="Some Tender",
            entity="World Bank",
            country="Kenya",
            official_url="",
        )
        result = await connector.validate(candidate)
        assert result.ok is False
        assert "url" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_both_missing(self):
        """Candidate with empty title AND url fails validation."""
        connector = _make_connector()
        candidate = OpportunityCandidate(
            title="",
            entity="",
            country="",
            official_url="",
        )
        result = await connector.validate(candidate)
        assert result.ok is False


# ═══════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════


# ── Helper for patching fetch_httpx_text at the module that uses it ────


def _patch_fetch(monkeypatch, mock_fetch):
    """Patch fetch_httpx_text in both common and development_aid modules."""
    from app.connectors import common as common_mod
    from app.connectors import development_aid as devaid_mod

    monkeypatch.setattr(common_mod, "fetch_httpx_text", mock_fetch)
    monkeypatch.setattr(devaid_mod, "fetch_httpx_text", mock_fetch)


class TestFetchIntegration:
    """T4.5: Integration tests for fetch()."""

    @pytest.mark.asyncio
    async def test_fetch_sitemaps(self, monkeypatch):
        """Fetch sitemap index + sub-sitemaps → metadata with urls."""
        async def mock_fetch(url, **kwargs):
            if url == SITEMAP_INDEX_URL:
                return (url, _SITEMAP_INDEX_XML, "text/xml")
            return (url, _SITEMAP_SUB_XML, "text/xml")

        _patch_fetch(monkeypatch, mock_fetch)

        connector = _make_connector()
        raw = await connector.fetch()

        assert isinstance(raw, RawSourceResult)
        assert raw.source_key == "developmentaid-tenders"
        assert "sitemap_fetch_time" in raw.metadata
        assert "urls" in raw.metadata
        urls = raw.metadata["urls"]
        assert isinstance(urls, list)
        assert len(urls) == 9  # 3 sub-sitemaps x 3 urls each
        for entry in urls:
            assert "loc" in entry
            assert "lastmod" in entry

    @pytest.mark.asyncio
    async def test_fetch_empty_sitemap(self, monkeypatch):
        """Empty sitemap → empty urls list."""
        async def mock_fetch(url, **kwargs):
            if url == SITEMAP_INDEX_URL:
                return (url, _SITEMAP_EMPTY_INDEX_XML, "text/xml")
            return (url, "", "text/xml")

        _patch_fetch(monkeypatch, mock_fetch)

        connector = _make_connector()
        raw = await connector.fetch()

        urls = raw.metadata.get("urls", [])
        assert urls == [] or len(urls) == 0

    @pytest.mark.asyncio
    async def test_fetch_sub_sitemap_failure_continues(self, monkeypatch):
        """A failed sub-sitemap doesn't abort the whole fetch."""
        async def mock_fetch(url, **kwargs):
            if url == SITEMAP_INDEX_URL:
                return (url, _SITEMAP_INDEX_XML, "text/xml")
            if "tenders_sitemap_2.xml" in url:
                raise RuntimeError("HTTP 500 from sub-sitemap 2")
            return (url, _SITEMAP_SUB_XML, "text/xml")

        _patch_fetch(monkeypatch, mock_fetch)

        connector = _make_connector()
        raw = await connector.fetch()

        urls = raw.metadata.get("urls", [])
        # 2 working sub-sitemaps × 3 urls each = 6
        assert len(urls) == 6


class TestParseIntegration:
    """T4.6: Integration tests for parse() pipeline (sitemap-only)."""

    @pytest.mark.asyncio
    async def test_parse_extracts_from_slugs(self):
        """parse() extracts candidates from sitemap URL slugs."""
        connector = _make_connector()
        raw = RawSourceResult(
            source_key="developmentaid-tenders",
            url=SITEMAP_INDEX_URL,
            content="",
            content_type="text/xml",
            metadata={
                "sitemap_fetch_time": "2025-07-01T00:00:00Z",
                "urls": [
                    {"loc": "https://www.developmentaid.org/tenders/view/123/caribbean-efficient-and-green-energy-buildings-project", "lastmod": "2025-06-15T00:00:00Z"},
                    {"loc": "https://www.developmentaid.org/tenders/view/456/solar-energy-infrastructure-tender", "lastmod": "2025-07-01T00:00:00Z"},
                    {"loc": "https://www.developmentaid.org/tenders/view/789/water-management-project", "lastmod": "2025-06-20T00:00:00Z"},
                ],
            },
        )

        candidates = await connector.parse(raw)
        assert len(candidates) == 3
        titles = {c.title for c in candidates}
        assert "Caribbean Efficient And Green Energy Buildings Project" in titles
        assert "Solar Energy Infrastructure Tender" in titles
        assert "Water Management Project" in titles

        for c in candidates:
            assert isinstance(c, OpportunityCandidate)
            assert c.title
            assert c.official_url.startswith("https://www.developmentaid.org/tenders/view/")
            assert c.confidence_score == 0.45

    @pytest.mark.asyncio
    async def test_parse_skips_missing_slug(self):
        """URLs without /tenders/view/ID/slug pattern are skipped."""
        connector = _make_connector()
        raw = RawSourceResult(
            source_key="developmentaid-tenders",
            url=SITEMAP_INDEX_URL,
            content="",
            content_type="text/xml",
            metadata={
                "sitemap_fetch_time": "2025-07-01T00:00:00Z",
                "urls": [
                    {"loc": "https://www.developmentaid.org/other-page", "lastmod": "2025-07-01T00:00:00Z"},
                    {"loc": "https://www.developmentaid.org/tenders/view/123/solar-tender", "lastmod": "2025-06-15T00:00:00Z"},
                ],
            },
        )
        candidates = await connector.parse(raw)
        assert len(candidates) == 1
        assert candidates[0].title == "Solar Tender"

    @pytest.mark.asyncio
    async def test_parse_respects_max_cap(self):
        """parse() caps at MAX_DETAIL_PAGES."""
        urls = [
            {"loc": f"https://www.developmentaid.org/tenders/view/{i}/project-{i}", "lastmod": "2025-07-01T00:00:00Z"}
            for i in range(100)
        ]

        connector = _make_connector()
        raw = RawSourceResult(
            source_key="developmentaid-tenders",
            url=SITEMAP_INDEX_URL,
            content="",
            content_type="text/xml",
            metadata={"sitemap_fetch_time": "2025-07-01T00:00:00Z", "urls": urls},
        )

        candidates = await connector.parse(raw)
        assert len(candidates) == MAX_DETAIL_PAGES

    @pytest.mark.asyncio
    async def test_parse_incremental_state(self):
        """Incremental state: processed_urls skip already-seen URLs."""
        import hashlib
        hash_123 = hashlib.sha256("https://www.developmentaid.org/tenders/view/123/solar-project".encode()).hexdigest()[:16]

        connector = _make_connector(connector_config={
            "last_sitemap_fetch": "2025-06-01T00:00:00Z",
            "processed_urls": {hash_123: "https://www.developmentaid.org/tenders/view/123/solar-project"},
        })

        raw = RawSourceResult(
            source_key="developmentaid-tenders",
            url=SITEMAP_INDEX_URL,
            content="",
            content_type="text/xml",
            metadata={
                "sitemap_fetch_time": "2025-07-01T00:00:00Z",
                "urls": [
                    {"loc": "https://www.developmentaid.org/tenders/view/123/solar-project", "lastmod": "2025-06-15T00:00:00Z"},
                    {"loc": "https://www.developmentaid.org/tenders/view/456/water-project", "lastmod": "2025-07-01T00:00:00Z"},
                ],
            },
        )

        candidates = await connector.parse(raw)
        # 123 already processed → skipped; only 456 returned
        assert len(candidates) == 1
        assert candidates[0].title == "Water Project"


class TestGetUpdatedConfig:
    """T4.X: State management tests."""

    @pytest.mark.asyncio
    async def test_get_updated_config_first_run(self):
        """get_updated_config() returns dict with empty processed_urls on first run."""
        connector = _make_connector()
        config = connector.get_updated_config()
        assert "processed_urls" in config
        assert config["processed_urls"] == {}

    @pytest.mark.asyncio
    async def test_get_updated_config_after_parse(self):
        """get_updated_config() reflects processed URLs after parse."""
        connector = _make_connector()
        raw = RawSourceResult(
            source_key="developmentaid-tenders",
            url=SITEMAP_INDEX_URL,
            content="",
            content_type="text/xml",
            metadata={
                "sitemap_fetch_time": "2025-07-01T00:00:00Z",
                "urls": [
                    {"loc": "https://www.developmentaid.org/tenders/view/123/solar-tender", "lastmod": "2025-07-01T00:00:00Z"},
                ],
            },
        )

        await connector.parse(raw)
        config = connector.get_updated_config()
        assert len(config["processed_urls"]) == 1


class TestDedupKey:
    """T4.7: Integration test for dedup key."""

    def test_dedup_key_extracts_id(self):
        """URL /tenders/view/123 → dedup key developmentaid:123."""
        from app.services.dedup import opportunity_dedup_key
        key = opportunity_dedup_key(
            "https://www.developmentaid.org/tenders/view/123",
            "Some Title",
        )
        assert key == "developmentaid:123"

    def test_dedup_key_with_query_params(self):
        """URL with query params still extracts the numeric ID."""
        from app.services.dedup import opportunity_dedup_key
        key = opportunity_dedup_key(
            "https://www.developmentaid.org/tenders/view/456?source=search",
            "Some Title",
        )
        assert key == "developmentaid:456"


class TestProtocolContract:
    """T4.8: Contract test — class satisfies SourceConnector Protocol."""

    def test_class_has_source_key(self):
        """DevelopmentAidConnector has source_key attribute."""
        connector = _make_connector()
        assert connector.source_key == "developmentaid-tenders"

    def test_fetch_method_signature(self):
        """fetch() is an async method returning RawSourceResult."""
        import inspect
        connector = _make_connector()
        assert hasattr(connector, "fetch")
        assert inspect.iscoroutinefunction(connector.fetch)

    def test_parse_method_signature(self):
        """parse() is an async method accepting RawSourceResult."""
        import inspect
        connector = _make_connector()
        assert hasattr(connector, "parse")
        assert inspect.iscoroutinefunction(connector.parse)

    def test_validate_method_signature(self):
        """validate() is an async method accepting OpportunityCandidate."""
        import inspect
        connector = _make_connector()
        assert hasattr(connector, "validate")
        assert inspect.iscoroutinefunction(connector.validate)


class TestSitemapIndexFetchError:
    """T4.X: Error handling for sitemap index."""

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_index_failure(self, monkeypatch):
        """fetch() returns empty result gracefully when sitemap index fails."""
        async def mock_fetch(url, **kwargs):
            if url == SITEMAP_INDEX_URL:
                raise RuntimeError("HTTP 500 from sitemap index")
            return (url, "", "text/xml")

        _patch_fetch(monkeypatch, mock_fetch)

        connector = _make_connector()
        result = await connector.fetch()
        assert result.metadata.get("urls") == []
        assert "error" in result.metadata

    @pytest.mark.asyncio
    async def test_corrupted_config_reset(self):
        """Corrupted connector_config is treated as first run."""
        connector = _make_connector(connector_config="not-a-dict")
        raw = RawSourceResult(
            source_key="developmentaid-tenders",
            url=SITEMAP_INDEX_URL,
            content="",
            content_type="text/xml",
            metadata={
                "sitemap_fetch_time": "2025-07-01T00:00:00Z",
                "urls": [
                    {"loc": "https://www.developmentaid.org/tenders/view/123/solar-tender", "lastmod": "2025-07-01T00:00:00Z"},
                ],
            },
        )
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
