"""E4 enrichment round 2: innpulsa API-payload fields, grants-gov pilot swap, minciencias triage.

- innpulsa detail pages are JS shells in SSR, so open/close/funding must be
  read from the API payload keys, not from HTML.
- ascun-convocatorias feed returns NEWS posts, not calls: dropped from the
  pilot gate, replaced by grants-gov (JSON API, stable detail URLs, explicit
  date/funding fields).
- minciencias runs degraded (0 found): triage pins the degraded mode and the
  gate stays with a documented dictamen (no verified fix without live HTML).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult


def _innpulsa_item(**overrides):
    base = {
        "id": "zasca-2026",
        "slug": "zasca-2026",
        "title": "Zasca 2026",
        "description": "Convocatoria para emprendedores",
        "status": "abierta",
        "category": "emprendimiento",
        "start_date": "2026-08-01",
        "end_date": "2026-10-31",
    }
    base.update(overrides)
    return base


class TestInnpulsaApiPayloadFunding:
    def test_structured_budget_key_yields_funding(self):
        """RED E4: numeric/string budget payload keys must surface funding."""
        from app.connectors.innpulsa import InnpulsaConnector

        item = _innpulsa_item(budget="COP 500.000.000")
        candidate = InnpulsaConnector()._candidate_from_api_item(item)

        assert candidate is not None
        assert candidate.funding_amount_raw is not None
        assert candidate.funding_amount_value is not None
        assert candidate.funding_amount_value >= 1000

    def test_plain_numeric_amount_key_yields_funding_value(self):
        """RED E4: a bare numeric amount (no $/keyword in list text) must count."""
        from app.connectors.innpulsa import InnpulsaConnector

        item = _innpulsa_item(amount=250000000)
        candidate = InnpulsaConnector()._candidate_from_api_item(item)

        assert candidate is not None
        assert candidate.funding_amount_raw is not None
        assert candidate.funding_amount_value == 250000000.0

    def test_item_without_funding_keys_stays_unfunded(self):
        """Triangulation: no funding keys -> no funding (no hallucination)."""
        from app.connectors.innpulsa import InnpulsaConnector

        candidate = InnpulsaConnector()._candidate_from_api_item(_innpulsa_item())

        assert candidate is not None
        assert candidate.funding_amount_raw is None
        assert candidate.funding_amount_value is None


class TestInnpulsaApiPayloadDates:
    def test_alternate_date_keys_are_read(self):
        """RED E4: payloads using fecha_inicio/fecha_cierre must date the candidate."""
        from app.connectors.innpulsa import InnpulsaConnector

        item = _innpulsa_item(start_date=None, end_date=None)
        item.pop("start_date")
        item.pop("end_date")
        item["fecha_inicio"] = "2026-08-01"
        item["fecha_cierre"] = "2026-10-31"
        candidate = InnpulsaConnector()._candidate_from_api_item(item)

        assert candidate is not None
        assert candidate.open_date is not None
        assert (candidate.open_date.year, candidate.open_date.month, candidate.open_date.day) == (
            2026,
            8,
            1,
        )
        assert candidate.close_date is not None
        assert (candidate.close_date.year, candidate.close_date.month, candidate.close_date.day) == (
            2026,
            10,
            31,
        )

    def test_legacy_start_end_keys_still_win(self):
        """Triangulation: existing start_date/end_date behavior is unchanged."""
        from app.connectors.innpulsa import InnpulsaConnector

        candidate = InnpulsaConnector()._candidate_from_api_item(_innpulsa_item())

        assert candidate is not None
        assert (candidate.open_date.year, candidate.open_date.month) == (2026, 8)
        assert (candidate.close_date.year, candidate.close_date.month) == (2026, 10)


class TestPilotGateSwap:
    def test_gate_holds_grants_gov_not_ascun(self):
        """RED E4: ascun dropped (news feed), grants-gov verified as replacement."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        assert "grants-gov" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "ascun-convocatorias" not in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "innpulsa" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "minciencias" in DETAIL_ENRICHMENT_PILOT_KEYS

    @pytest.mark.asyncio
    async def test_ascun_passthrough_makes_no_fetch(self, monkeypatch):
        """RED E4: ascun candidates must skip detail fetch entirely."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock()
        mock_fetch.return_value = ("https://detail.example/item", "<html></html>", "text/html")
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        candidate = OpportunityCandidate(
            title="Noticia ASCUN",
            entity="ASCUN Colombia",
            country="Colombia",
            official_url="https://ascun.org.co/noticias-ies/nota-1/",
            summary="Noticia",
            raw_text="Noticia",
            confidence_score=0.55,
        )

        result = await enrich_pilot_candidates("ascun-convocatorias", [candidate])

        assert result == [candidate]
        mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_grants_gov_candidate_gains_fields_from_detail(self, monkeypatch):
        """Grants-gov pilot candidates enrich through the existing batch path."""
        from app.connectors.common import enrich_pilot_candidates

        html = """<html><body>
          <h1>Grants.gov Test Opportunity</h1>
          <div class="content">
            <p>Posted date: March 15, 2026</p>
            <p>Closing date: September 30, 2026</p>
            <p>Award ceiling: USD 500,000</p>
          </div>
        </body></html>"""
        mock_fetch = AsyncMock()
        mock_fetch.return_value = ("https://www.grants.gov/x", html, "text/html")
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        candidate = OpportunityCandidate(
            title="Test Opportunity",
            entity="Grants.gov",
            country="United States",
            official_url="https://www.grants.gov/search-results-detail/12345",
            summary="Test Opportunity",
            raw_text="Test Opportunity",
            confidence_score=0.82,
        )

        result = await enrich_pilot_candidates("grants-gov", [candidate])

        assert len(result) == 1
        assert result[0].close_date is not None
        assert result[0].funding_amount_raw is not None
        mock_fetch.assert_awaited()


class TestGrantsGovReplacementEvidence:
    @pytest.mark.asyncio
    async def test_parse_yields_stable_detail_urls_dates_and_funding(self):
        """Replacement evidence: JSON API parse gives detail URLs + dates + funding."""
        from app.connectors.grants_gov import GrantsGovConnector

        payload = {
            "data": {
                "oppHits": [
                    {
                        "id": "12345",
                        "title": "Test Innovation Grant",
                        "agencyName": "National Science Foundation",
                        "number": "NSF-26-001",
                        "oppStatus": "posted",
                        "synopsis": "Funding for innovation projects.",
                        "openDate": "03/15/2026",
                        "closeDate": "09/30/2026",
                        "awardCeiling": "500000",
                    }
                ]
            }
        }
        raw = RawSourceResult(
            source_key="grants-gov",
            url="https://api.grants.gov/v1/api/search2",
            content=json.dumps(payload),
            content_type="application/json",
        )

        candidates = await GrantsGovConnector().parse(raw)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.official_url == "https://www.grants.gov/search-results-detail/12345"
        assert candidate.open_date is not None and candidate.close_date is not None
        assert (candidate.close_date.year, candidate.close_date.month, candidate.close_date.day) == (
            2026,
            9,
            30,
        )
        assert candidate.funding_amount_raw is not None


class TestMincienciasTriage:
    @pytest.mark.asyncio
    async def test_empty_listing_yields_zero_candidates(self):
        """Dictamen evidence: a changed/empty listing parses to 0 (degraded mode)."""
        from app.connectors.minciencias import MincienciasConnector

        raw = RawSourceResult(
            source_key="minciencias",
            url="https://minciencias.gov.co/convocatorias/todas",
            content="<html><body><main><p>No hay convocatorias disponibles.</p></main></body></html>",
            content_type="text/html",
        )

        assert await MincienciasConnector().parse(raw) == []

    @pytest.mark.asyncio
    async def test_valid_listing_row_still_parses(self):
        """Triangulation: the parser itself works when /convocatorias/ anchors exist."""
        from app.connectors.minciencias import MincienciasConnector

        raw = RawSourceResult(
            source_key="minciencias",
            url="https://minciencias.gov.co/convocatorias/todas",
            content=(
                "<html><body><ul>"
                '<li><a href="/convocatorias/convocatoria-ciencia-2026">'
                "Convocatoria de ciencia e innovacion 2026</a>"
                "<span>Cierre: 30 de septiembre de 2026</span></li>"
                "</ul></body></html>"
            ),
            content_type="text/html",
        )

        candidates = await MincienciasConnector().parse(raw)

        assert len(candidates) == 1
        assert candidates[0].official_url.endswith("/convocatorias/convocatoria-ciencia-2026")
