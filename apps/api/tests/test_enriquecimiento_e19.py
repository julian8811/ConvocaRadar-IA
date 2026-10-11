"""E19: implement the 3 E18 forensic fixes with strict TDD.

Fix 1 (novo-nordisk-grants): WP JSON always carries ``acf: []``, so the
list parse never yields a deadline. The SSR detail page does: header
label/paragraph pairs (``Call opens`` / ``Call closes``) and a sidebar
``Amount`` row (``DKK 10 million per grant``). ``parse_date_text`` fails
on the ``2:00pm (Copenhagen time)`` suffix, and ``extract_funding_details``
returns ``(None, None, None)`` for DKK.

Fix 2 (fondo-emprender-sena): detail pages carry an ``h2`` ``Fechas``
block with ``Apertura:`` / ``Cierre:`` rows and a ``Recursos Asignados``
sibling row with the amount (``$1.050.000.000``, currency None is
acceptable — Colombia resolves downstream).

Fix 3 (fapesp-brasil): open bolsas carry a monthly stipend
(``Valor da bolsa: R$ 12.570,00``); the SSR batch must apply funding
from the detail text via gap-fill only.

All fixtures below are inline real-shape HTML/text from the E18
forensic evidence — no network fetches in tests.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate


# ── Forensic fixtures (inline, no fetches) ───────────────────────────────────

NOVO_DETAIL_HTML = """<html><body><main>
<h1>Project Grant in Clinical Research</h1>
<div class="nnf-grant-header">
<div class="nnf-grant-header__label">Call opens</div>
<div class="nnf-grant-header__paragraph">8 October 2026</div>
<div class="nnf-grant-header__label">Call closes</div>
<div class="nnf-grant-header__paragraph">25 January 2027 2:00pm (Copenhagen time)</div>
</div>
<div class="nnf-project-sidebar">
<div class="nnf-project-sidebar__label">Amount</div>
<div class="nnf-project-sidebar__data">DKK 10 million per grant</div>
</div>
</main></body></html>"""

NOVO_DETAIL_NO_AMOUNT_HTML = """<html><body><main>
<h1>Project Grant without Amount</h1>
<div class="nnf-grant-header">
<div class="nnf-grant-header__label">Call opens</div>
<div class="nnf-grant-header__paragraph">8 October 2026</div>
<div class="nnf-grant-header__label">Call closes</div>
<div class="nnf-grant-header__paragraph">25 January 2027 2:00pm (Copenhagen time)</div>
</div>
</main></body></html>"""

FONDO_DETAIL_HTML = """<html><body><main>
<h1>Convocatoria Fondo Emprender 2026</h1>
<h2>Fechas</h2>
<h2 style="font-size:23px">Apertura: 20 de mayo de 2026</h2>
<h2 style="font-size:23px">Cierre: 19 de junio de 2026</h2>
<h2>Recursos Asignados</h2>
<h2 style="font-size:23px">$1.050.000.000</h2>
</main></body></html>"""

FAPESP_DETAIL_HTML = """<html><body><main>
<h1>Bolsa de pesquisa FAPESP 2026</h1>
<div class="content">
<p>Inscrições até 07/10/2026</p>
<p>Valor da bolsa: R$ 12.570,00 mensais</p>
<p>Value: R$ 12.570,00 per month</p>
</div>
</main></body></html>"""

NOVO_URL = "https://novonordiskfonden.dk/en/project-grant-2026"
FONDO_URL = "https://www.fondoemprender.com/SitePages/Convocatoria2026.aspx"
FAPESP_URL = "https://fapesp.br/oportunidades/bolsa-12345/"


def _candidate(url: str, **overrides) -> OpportunityCandidate:
    base = {
        "title": "Test call",
        "entity": "Test entity",
        "country": "Por validar",
        "official_url": url,
        "summary": "Test call",
        "raw_text": "Test call",
        "confidence_score": 0.55,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


# ── Fix 1: novo-nordisk-grants ────────────────────────────────────────────────


class TestNovoDateSuffix:
    def test_time_suffixed_deadline_parses_to_date_only(self):
        """RED E19: the NNF close line carries a time suffix dateparser chokes on."""
        from app.connectors.common import parse_date_text

        parsed = parse_date_text("25 January 2027 2:00pm (Copenhagen time)")

        assert parsed is not None
        assert (parsed.year, parsed.month, parsed.day) == (2027, 1, 25)

    def test_pure_english_date_still_parses(self):
        """Pin: the suffix fallback must not disturb plain dates."""
        from app.connectors.common import parse_date_text

        parsed = parse_date_text("8 October 2026")

        assert parsed is not None
        assert (parsed.year, parsed.month, parsed.day) == (2026, 10, 8)


class TestNovoDkkFunding:
    def test_dkk_amount_yields_value_and_currency(self):
        """RED E19: DKK is absent from currency detection, so NNF funding is lost."""
        from app.connectors.common import extract_funding_details

        raw, value, currency = extract_funding_details("DKK 10 million per grant")

        assert raw is not None and "DKK" in raw
        assert value == 10000000.0
        assert currency == "DKK"


class TestNovoDetailFields:
    def test_header_and_sidebar_yield_dates_and_funding(self):
        """RED E19: NNF header labels + sidebar amount parse into fields."""
        from app.connectors.wordpress_grants import extract_novo_detail_fields

        fields = extract_novo_detail_fields(NOVO_DETAIL_HTML)

        assert fields["open_date"] is not None
        assert (fields["open_date"].year, fields["open_date"].month, fields["open_date"].day) == (
            2026, 10, 8,
        )
        assert fields["close_date"] is not None
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2027, 1, 25,
        )
        assert fields["funding_amount_value"] == 10000000.0
        assert fields["funding_amount_currency"] == "DKK"

    def test_missing_amount_yields_dates_without_funding(self):
        """Some NNF fichas carry no Amount row: pure gap-fill, no fabrication."""
        from app.connectors.wordpress_grants import extract_novo_detail_fields

        fields = extract_novo_detail_fields(NOVO_DETAIL_NO_AMOUNT_HTML)

        assert fields["open_date"] is not None
        assert fields["close_date"] is not None
        assert fields["funding_amount_raw"] is None
        assert fields["funding_amount_value"] is None
        assert fields["funding_amount_currency"] is None

    @pytest.mark.asyncio
    async def test_empty_acf_list_parse_still_emits_undated_candidate(self):
        """Pin: WP JSON with ``acf: []`` never crashes and yields no phantom dates."""
        import json

        from app.connectors.base import RawSourceResult
        from app.connectors.wordpress_grants import WordPressGrantsConnector

        payload = [
            {
                "status": "publish",
                "title": {"rendered": "NNF Project Grant"},
                "link": NOVO_URL,
                "date": "2026-10-08T09:00:00",
                "acf": [],
            }
        ]
        raw = RawSourceResult(
            source_key="novo-nordisk-grants",
            url="https://novonordiskfonden.dk/wp-json/wp/v2/grant",
            content=json.dumps(payload),
            content_type="application/json",
        )

        (candidate,) = await WordPressGrantsConnector(
            source_key="novo-nordisk-grants", base_url=raw.url
        ).parse(raw)

        assert candidate.title == "NNF Project Grant"
        assert candidate.close_date is None


class TestNovoPilotGate:
    def test_novo_key_joins_pilot_gate(self):
        """RED E19: novo detail enrichment runs through the runner-level SSR batch."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        assert "novo-nordisk-grants" in DETAIL_ENRICHMENT_PILOT_KEYS

    @pytest.mark.asyncio
    async def test_pilot_batch_gap_fills_novo_dates_and_funding(self, monkeypatch):
        """RED E19: an undated NNF candidate gains open/close + DKK funding."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(NOVO_URL, NOVO_DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "novo-nordisk-grants", [_candidate(NOVO_URL, entity="Novo Nordisk Foundation", country="Denmark")]
        )

        assert result.open_date is not None
        assert (result.open_date.year, result.open_date.month, result.open_date.day) == (2026, 10, 8)
        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (2027, 1, 25)
        assert result.funding_amount_value == 10000000.0
        assert result.funding_amount_currency == "DKK"
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    async def test_pilot_batch_preserves_existing_novo_close(self, monkeypatch):
        """Gap-fill only (mirror of _update_opportunity): existing dates win."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(NOVO_URL, NOVO_DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        existing_close = datetime(2027, 2, 1)

        (result,) = await enrich_pilot_candidates(
            "novo-nordisk-grants",
            [_candidate(NOVO_URL, entity="Novo Nordisk Foundation", country="Denmark", close_date=existing_close)],
        )

        assert result.close_date == existing_close


# ── Fix 2: fondo-emprender-sena ───────────────────────────────────────────────


class TestFondoDetailFields:
    def test_h2_fechas_block_yields_open_close_and_funding(self):
        """RED E19: Apertura/Cierre h2 rows + Recursos Asignados sibling parse."""
        from app.connectors.common import extract_fondo_detail_fields

        fields = extract_fondo_detail_fields(FONDO_DETAIL_HTML)

        assert fields["open_date"] is not None
        assert (fields["open_date"].year, fields["open_date"].month, fields["open_date"].day) == (
            2026, 5, 20,
        )
        assert fields["close_date"] is not None
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2026, 6, 19,
        )
        assert fields["funding_amount_value"] == 1050000000.0
        # Bare "$" stays currency-None: Colombia resolves it downstream.
        assert fields["funding_amount_currency"] is None

    def test_page_fields_fill_from_fondo_detail_url(self):
        """RED E19: the detail-page path applies the h2 block via page_url."""
        from app.connectors.common import extract_page_fields

        result = extract_page_fields(html=FONDO_DETAIL_HTML, page_url=FONDO_URL)

        assert result["open_date"] is not None
        assert (result["open_date"].year, result["open_date"].month, result["open_date"].day) == (
            2026, 5, 20,
        )
        assert result["close_date"] is not None
        assert result["funding_amount_value"] == 1050000000.0

    def test_unrelated_host_skips_fondo_block(self):
        """Pin: the h2 heuristic is host-gated and never fires elsewhere."""
        from app.connectors.common import extract_page_fields

        result = extract_page_fields(html=FONDO_DETAIL_HTML, page_url="https://example.com/call")

        assert result["funding_amount_value"] == 1050000000.0
        # Generic sweep still finds the dates from the same text.
        assert result["close_date"] is not None


class TestFondoSeed:
    def test_seed_declares_apertura_label(self):
        """RED E19: the ficha opens with 'Apertura:' — the seed must name it."""
        import re
        from pathlib import Path

        seed_text = (Path(__file__).resolve().parent.parent / "app" / "db" / "seed.py").read_text()
        block = re.search(
            r'"key": "fondo-emprender-sena".*?connector_config": \{(.*?)\},',
            seed_text,
            flags=re.DOTALL,
        )
        assert block is not None
        config = block.group(1)
        assert '"detail_enrichment": True' in config
        assert "Apertura" in config


# ── Fix 3: fapesp-brasil monthly stipend ──────────────────────────────────────


class TestFapespStipend:
    def test_stipend_triple_from_detail_text(self):
        """Pin the forensic triple: bolsa value parses to (raw, 12570.0, BRL)."""
        from app.connectors.common import extract_funding_details

        raw, value, currency = extract_funding_details("Valor da bolsa: R$ 12.570,00")

        assert raw == "R$ 12.570,00"
        assert value == 12570.0
        assert currency == "BRL"

    @pytest.mark.asyncio
    async def test_pilot_batch_applies_stipend_funding(self, monkeypatch):
        """The SSR batch gap-fills the monthly stipend onto an unfunded bolsa."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(FAPESP_URL, FAPESP_DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "fapesp-brasil",
            [_candidate(FAPESP_URL, title="Bolsa FAPESP", entity="FAPESP", country="Brazil")],
        )

        assert result.funding_amount_value == 12570.0
        assert result.funding_amount_currency == "BRL"
        assert result.close_date is not None
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    async def test_existing_stipend_funding_never_overwritten(self, monkeypatch):
        """Gap-fill only: an already-funded bolsa keeps its figures."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(FAPESP_URL, FAPESP_DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "fapesp-brasil",
            [
                _candidate(
                    FAPESP_URL,
                    title="Bolsa FAPESP",
                    entity="FAPESP",
                    country="Brazil",
                    funding_amount_raw="R$ 9.000,00",
                    funding_amount_value=9000.0,
                    funding_amount_currency="BRL",
                )
            ],
        )

        assert result.funding_amount_value == 9000.0
        assert result.funding_amount_raw == "R$ 9.000,00"
