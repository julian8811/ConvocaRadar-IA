"""E14: enrichment batch 4 — secihti-mexico-ciencias + universidad-nacional-colombia.

- Both detail pages are full SSR text (parent live-verified) and the
  deterministic extractors already yield dates from them, so each key joins
  the runner-level pilot gate and the existing SSR batch path covers them
  (no dedicated connector file, no generic-path change).
- Funding for both: DICTAMEN (no code) — proven absent from detail text, so
  no funding path is built; enrichment is dates-only gap-fill.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate


def _secihti_candidate(**overrides) -> OpportunityCandidate:
    base = {
        "title": "Convocatoria SECIHTI Ciencias 2026",
        "entity": "SECIHTI",
        "country": "Mexico",
        "official_url": "https://secihti.mx/convocatorias/ciencias-2026/",
        "summary": "Convocatoria SECIHTI Ciencias 2026",
        "raw_text": "Convocatoria SECIHTI Ciencias 2026",
        "confidence_score": 0.55,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


def _unal_candidate(**overrides) -> OpportunityCandidate:
    base = {
        "title": "Convocatoria UNAL 2026",
        "entity": "Universidad Nacional de Colombia",
        "country": "Colombia",
        "official_url": "https://unal.edu.co/convocatorias/convocatoria-2026/",
        "summary": "Convocatoria UNAL 2026",
        "raw_text": "Convocatoria UNAL 2026",
        "confidence_score": 0.55,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


# SSR detail bodies in the shape parent verified live (full text, dates, no funding).
_SECIHTI_DETAIL_HTML = """<html><body><main>
<h1>Convocatoria SECIHTI Ciencias 2026</h1>
<div class="content">
<p>Apertura: 23/02/2026</p>
<p>Fecha de cierre: 24/07/2026</p>
<p>Consulta las bases de la convocatoria en este portal.</p>
</div>
</main></body></html>"""

_UNAL_DETAIL_HTML = """<html><body><main>
<h1>Convocatoria UNAL 2026</h1>
<div class="content">
<p>Fecha de cierre: 15/12/2026</p>
<p>Consulta los terminos de referencia en este portal.</p>
</div>
</main></body></html>"""


class TestPilotGateBatch4:
    def test_gate_holds_secihti_and_unal(self):
        """RED E14: secihti-mexico-ciencias + universidad-nacional-colombia join the gate."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        assert "secihti-mexico-ciencias" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "universidad-nacional-colombia" in DETAIL_ENRICHMENT_PILOT_KEYS
        # Earlier pilots unchanged.
        assert "fapesp-brasil" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "developmentaid-tenders" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "grants-gov" in DETAIL_ENRICHMENT_PILOT_KEYS

    @pytest.mark.asyncio
    async def test_secihti_candidate_gains_dates_from_ssr_batch(self, monkeypatch):
        """RED E14: secihti-mexico-ciencias enriches through the existing SSR batch path."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(
            return_value=(
                "https://secihti.mx/convocatorias/ciencias-2026/",
                _SECIHTI_DETAIL_HTML,
                "text/html",
            )
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "secihti-mexico-ciencias", [_secihti_candidate()]
        )

        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (
            2026,
            7,
            24,
        )
        assert result.open_date is not None
        assert (result.open_date.year, result.open_date.month, result.open_date.day) == (
            2026,
            2,
            23,
        )
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    async def test_unal_candidate_gains_close_date_from_ssr_batch(self, monkeypatch):
        """RED E14: universidad-nacional-colombia enriches through the existing SSR batch path."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(
            return_value=(
                "https://unal.edu.co/convocatorias/convocatoria-2026/",
                _UNAL_DETAIL_HTML,
                "text/html",
            )
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "universidad-nacional-colombia", [_unal_candidate()]
        )

        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (
            2026,
            12,
            15,
        )
        mock_fetch.assert_awaited()
