"""Tests for the Findeter sitemap-based connector."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.findeter import FindeterConnector
from app.connectors.registry import get_connector, registered_keys


FINDETER_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.findeter.gov.co/</loc>
    <lastmod>2025-01-15</lastmod>
  </url>
  <url>
    <loc>https://www.findeter.gov.co/convocatorias/ICBFGS/Convocatoria/001-2025</loc>
    <lastmod>2025-02-01</lastmod>
  </url>
  <url>
    <loc>https://www.findeter.gov.co/convocatorias/ICBFGS/Convocatoria/002-2025</loc>
    <lastmod>2025-02-10</lastmod>
  </url>
  <url>
    <loc>https://www.findeter.gov.co/convocatorias/ANSPE/Convocatoria/001-2025</loc>
    <lastmod>2025-03-01</lastmod>
  </url>
  <url>
    <loc>https://www.findeter.gov.co/convocatorias/FNG/Convocatoria/003-2026</loc>
    <lastmod>2026-01-15</lastmod>
  </url>
  <url>
    <loc>https://www.findeter.gov.co/convocatorias/ICBFGS/Licitacion/001-2024</loc>
    <lastmod>2024-06-01</lastmod>
  </url>
</urlset>
"""


@pytest.fixture
def connector() -> FindeterConnector:
    return FindeterConnector(_skip_enrichment=True)


@pytest.fixture
def mock_fetch(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr("app.connectors.findeter.fetch_httpx_text", mock)
    return mock


# ── fetch tests ────────────────────────────────────────────────────────────


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_raw_source_result(self, connector, mock_fetch):
        mock_fetch.return_value = (
            "https://www.findeter.gov.co/sitemap.xml",
            FINDETER_SITEMAP_XML,
            "application/xml",
        )

        result = await connector.fetch()

        assert isinstance(result, RawSourceResult)
        assert result.source_key == "findeter-convocatorias"
        assert result.content_type == "application/xml"
        assert result.content
        assert "sitemaps.org" in result.content

    @pytest.mark.asyncio
    async def test_fetch_uses_sitemap_url(self, connector, mock_fetch):
        mock_fetch.return_value = ("https://www.findeter.gov.co/sitemap.xml", "", "text/plain")

        await connector.fetch()

        mock_fetch.assert_awaited_once()
        call_url = mock_fetch.await_args[0][0]
        assert "sitemap.xml" in call_url
        assert "findeter.gov.co" in call_url


# ── parse tests ────────────────────────────────────────────────────────────


class TestParse:
    @pytest.mark.asyncio
    async def test_parse_extracts_convocatorias_urls(self, connector):
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content=FINDETER_SITEMAP_XML,
            content_type="application/xml",
        )

        candidates = await connector.parse(raw)

        # All 5 convocatorias URLs are included (2024 is now allowed)
        assert len(candidates) == 5

    @pytest.mark.asyncio
    async def test_parse_maps_entity_codes_to_names(self, connector):
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content=FINDETER_SITEMAP_XML,
            content_type="application/xml",
        )

        candidates = await connector.parse(raw)

        # Entity should always be "Findeter"
        assert all(c.entity == "Findeter" for c in candidates)
        # At least one candidate should have ICBF in the title
        assert any("ICBF" in c.title for c in candidates)

    @pytest.mark.asyncio
    async def test_parse_candidates_have_correct_structure(self, connector):
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content=FINDETER_SITEMAP_XML,
            content_type="application/xml",
        )

        candidates = await connector.parse(raw)

        assert all(isinstance(c, OpportunityCandidate) for c in candidates)
        for c in candidates:
            assert c.country == "Colombia"
            assert c.entity == "Findeter"
            assert c.confidence_score == 0.45
            assert c.official_url
            assert "Findeter" in c.title

    @pytest.mark.asyncio
    async def test_parse_includes_all_years(self, connector):
        """2024, 2025 and 2026 URLs should all be included."""
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content=FINDETER_SITEMAP_XML,
            content_type="application/xml",
        )

        candidates = await connector.parse(raw)

        years_found = set()
        for c in candidates:
            if "-2024" in c.official_url:
                years_found.add("2024")
            if "-2025" in c.official_url:
                years_found.add("2025")
            if "-2026" in c.official_url:
                years_found.add("2026")

        assert "2024" in years_found, "2024 entries should be included"
        assert "2025" in years_found, "2025 entries should be included"
        assert "2026" in years_found, "2026 entries should be included"

    @pytest.mark.asyncio
    async def test_parse_respects_max_candidates(self, connector):
        """Should limit to 100 candidates."""
        # Generate a sitemap with 150 entries
        urls = []
        for i in range(1, 151):
            seq = f"{i:03d}"
            urls.append(
                f"""  <url>
    <loc>https://www.findeter.gov.co/convocatorias/ICBFGS/Convocatoria/{seq}-2025</loc>
    <lastmod>2025-01-01</lastmod>
  </url>"""
            )
        big_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content=big_xml,
            content_type="application/xml",
        )

        candidates = await connector.parse(raw)
        assert len(candidates) <= 100

    @pytest.mark.asyncio
    async def test_parse_handles_empty_sitemap(self, connector):
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
            content_type="application/xml",
        )

        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_handles_garbage_content(self, connector, mock_fetch):
        # Garbage (non-XML, non-HTML) also consults the sitemap fallback;
        # an empty sitemap keeps the result empty without raising.
        mock_fetch.return_value = (
            "https://www.findeter.gov.co/sitemap.xml",
            '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
            "application/xml",
        )
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/sitemap.xml",
            content="not xml at all",
            content_type="text/plain",
        )

        candidates = await connector.parse(raw)
        assert candidates == []


# ── sitemap fallback when the HTML listing yields nothing ──────────────
# Server evidence 2026-10-10: seed base_url is the /convocatorias HTML
# listing (SSR 15KB, 0 links — list is JS-rendered) while sitemap.xml holds
# 3351 locs / 2869 /convocatorias/ with recent years. parse() must fall back
# to the canonical sitemap when the HTML listing yields 0 candidates.


FINDETER_SITEMAP_REAL_SHAPE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.findeter.gov.co/</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-icbfgs-i-001-2026</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-icbfgs-o-001-2026</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-dps-i-002-2025</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-atsed-o-001-2025</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-menpnie-i-002-2024</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-atf-o-045-2020</loc></url>
  <url><loc>https://www.findeter.gov.co/convocatorias/paf-atf-124-2015</loc></url>
</urlset>
"""

FINDETER_HTML_LISTING_WITHOUT_LINKS = """<!DOCTYPE html>
<html><head><title>Convocatorias - Findeter</title></head>
<body><div id="app"></div><p>Cargando convocatorias...</p></body></html>
"""


class TestSitemapFallbackWhenHtmlYieldsNothing:
    @pytest.mark.asyncio
    async def test_html_listing_without_links_falls_back_to_sitemap(
        self, mock_fetch
    ):
        """RED: HTML listing (seed base_url) with 0 SSR links -> sitemap cands."""
        mock_fetch.return_value = (
            "https://www.findeter.gov.co/sitemap.xml",
            FINDETER_SITEMAP_REAL_SHAPE_XML,
            "application/xml",
        )
        connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/convocatorias",
            content=FINDETER_HTML_LISTING_WITHOUT_LINKS,
            content_type="text/html",
        )

        candidates = await connector.parse(raw)

        assert len(candidates) == 5
        assert all("/convocatorias/" in c.official_url for c in candidates)

    @pytest.mark.asyncio
    async def test_fallback_excludes_old_years(self, mock_fetch):
        mock_fetch.return_value = (
            "https://www.findeter.gov.co/sitemap.xml",
            FINDETER_SITEMAP_REAL_SHAPE_XML,
            "application/xml",
        )
        connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/convocatorias",
            content=FINDETER_HTML_LISTING_WITHOUT_LINKS,
            content_type="text/html",
        )

        candidates = await connector.parse(raw)
        urls = [c.official_url for c in candidates]

        assert not any(u.endswith("-2020") for u in urls)
        assert not any(u.endswith("-2015") for u in urls)
        assert any(u.endswith("-2026") for u in urls)

    @pytest.mark.asyncio
    async def test_fallback_fetch_failure_returns_empty(self, mock_fetch):
        """Triangulation: sitemap unreachable -> [] (no crash, no raise)."""
        mock_fetch.side_effect = RuntimeError("boom")
        connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/convocatorias",
            content=FINDETER_HTML_LISTING_WITHOUT_LINKS,
            content_type="text/html",
        )

        assert await connector.parse(raw) == []

    @pytest.mark.asyncio
    async def test_fallback_respects_max_candidates(self, mock_fetch):
        """Triangulation: fallback path caps at _MAX_CANDIDATES (100)."""
        urls = "\n".join(
            f"  <url><loc>https://www.findeter.gov.co/convocatorias/paf-dps-i-{i:03d}-2025</loc></url>"
            for i in range(1, 121)
        )
        big_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n</urlset>"
        )
        mock_fetch.return_value = (
            "https://www.findeter.gov.co/sitemap.xml",
            big_xml,
            "application/xml",
        )
        connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/convocatorias",
            content=FINDETER_HTML_LISTING_WITHOUT_LINKS,
            content_type="text/html",
        )

        candidates = await connector.parse(raw)

        assert len(candidates) == 100

    @pytest.mark.asyncio
    async def test_html_with_links_does_not_hit_sitemap(self, mock_fetch):
        """Triangulation: HTML listing WITH links never fetches the sitemap."""
        connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/convocatorias",
            content="""<html><body><main>
<a href="https://www.findeter.gov.co/convocatorias/paf-dps-i-002-2025">Convocatoria DPS 002 de 2025 para infraestructura</a>
</main></body></html>""",
            content_type="text/html",
        )

        candidates = await connector.parse(raw)

        assert len(candidates) == 1
        mock_fetch.assert_not_awaited()


# ── validate tests ────────────────────────────────────────────────────────


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_passes_valid_candidate(self, connector):
        candidate = OpportunityCandidate(
            title="Convocatoria ICBF Convocatoria 001-2025",
            entity="Findeter",
            country="Colombia",
            official_url="https://www.findeter.gov.co/convocatorias/ICBFGS/Convocatoria/001-2025",
        )

        result = await connector.validate(candidate)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector):
        candidate = OpportunityCandidate(
            title="",
            entity="Findeter",
            country="Colombia",
            official_url="https://www.findeter.gov.co/convocatorias/ICBFGS/Convocatoria/001-2025",
        )

        result = await connector.validate(candidate)
        assert result.ok is False
        assert "Missing title" in result.reason

    @pytest.mark.asyncio
    async def test_validate_rejects_bad_url(self, connector):
        candidate = OpportunityCandidate(
            title="Test Title",
            entity="Findeter",
            country="Colombia",
            official_url="https://evil.com/scam",
        )

        result = await connector.validate(candidate)
        assert result.ok is False
        assert "URL" in result.reason or "url" in result.reason


# ── Registration tests ────────────────────────────────────────────────────


class TestRegistration:
    def test_connector_is_registered(self):
        assert "findeter-convocatorias" in registered_keys()

    def test_get_connector_returns_findeter_instance(self):
        connector = get_connector("findeter-convocatorias")
        assert isinstance(connector, FindeterConnector)
        assert connector.source_key == "findeter-convocatorias"

    def test_connector_for_uses_registry(self):
        from app.connectors.factory import connector_for

        connector = connector_for("findeter-convocatorias", "http://example.com")
        assert isinstance(connector, FindeterConnector)
