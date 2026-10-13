"""E21/E22: UNITAR courses detail enrichment with strict TDD.

Forensic E21: the ``event.unitar.org/full-catalog/<slug>`` ficha (SSR 200,
stable across sampled fichas) carries flat label/value pairs —
``Type Course``, ``Deadline 7 Oct 2026``,
``Date 12 Oct 2026 - 1 Nov 2026``, ``Duration 3 Weeks``,
``Price $600.00``. ``parse_date_text`` handles the English dates and
``extract_funding_details`` handles ``$600.00`` → (600.0, currency None —
bare ``$`` stays unresolved, same precedent as fondo E19).

Fix (mirrors E19 ``extract_fondo_detail_fields`` + E20 gate lesson):
``extract_unitar_detail_fields`` (host-gated on ``event.unitar.org`` in
``extract_page_fields``) maps Deadline→close_date, the Date range
start/end→open_date/close_date (gap-fill only — an explicit Deadline
keeps close_date), Price→funding; plus the ``unitar-courses`` key joins
``DETAIL_ENRICHMENT_PILOT_KEYS`` so the runner-level SSR batch actually
fetches the fichas. Self-paced courses may carry no Deadline at all:
keys then stay None (pure gap-fill, never fabricated).

All fixtures below are inline real-shape HTML from the E21 forensic
evidence — no network fetches in tests.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate


# ── Forensic fixtures (inline, no fetches) ───────────────────────────────────

UNITAR_DETAIL_HTML = """<html><body><main>
<h1>International Law and Diplomacy Course</h1>
<div class="course-info">
<p><strong>Type</strong> Course</p>
<p><strong>Deadline</strong> 7 Oct 2026</p>
<p><strong>Date</strong> 12 Oct 2026 - 1 Nov 2026</p>
<p><strong>Duration</strong> 3 Weeks</p>
<p><strong>Price</strong> $600.00</p>
</div>
</main></body></html>"""

UNITAR_DATE_ONLY_HTML = """<html><body><main>
<h1>Self-Paced Online Course</h1>
<div class="course-info">
<p><strong>Type</strong> Course</p>
<p><strong>Date</strong> 12 Oct 2026 - 1 Nov 2026</p>
<p><strong>Duration</strong> 3 Weeks</p>
</div>
</main></body></html>"""

UNITAR_NO_DATES_HTML = """<html><body><main>
<h1>Self-Paced Open Course</h1>
<div class="course-info">
<p><strong>Type</strong> Course</p>
<p><strong>Duration</strong> Self-paced</p>
</div>
</main></body></html>"""

UNITAR_URL = "https://event.unitar.org/full-catalog/international-law-2026"

# ── field-event-deadline-regist container (Drupal field markup) ──────────────
# Older event.unitar.org fichas carry the deadline in a dedicated container
# (field-event-deadline-regist) whose label/value live in separate divs, so
# the flat "Deadline <date>" sweep misses it and past values (e.g. 2020)
# fall outside the default extraction year window.

UNITAR_DEADLINE_REGIST_HTML = """<html><body><main>
<h1>Trade Policy Course</h1>
<div class="field field-name-field-event-deadline-regist field-type-datetime field-label-inline clearfix">
<div class="field-label">Deadline:&nbsp;</div>
<div class="field-items"><div class="field-item even">27 Apr 2020</div></div>
</div>
</main></body></html>"""

UNITAR_DEADLINE_REGIST_TIME_HTML = """<html><body><main>
<h1>Trade Policy Course</h1>
<div class="field field-name-field-event-deadline-regist field-type-datetime field-label-inline clearfix">
<div class="field-label">Deadline:&nbsp;</div>
<div class="field-items"><div class="field-item even">27 Apr 2020 18:00</div></div>
</div>
</main></body></html>"""

UNITAR_DEADLINE_REGIST_GARBAGE_HTML = """<html><body><main>
<h1>Trade Policy Course</h1>
<div class="field field-name-field-event-deadline-regist field-type-datetime field-label-inline clearfix">
<div class="field-label">Deadline:&nbsp;</div>
<div class="field-items"><div class="field-item even">To be announced</div></div>
</div>
</main></body></html>"""


def _candidate(url: str, **overrides) -> OpportunityCandidate:
    base = {
        "title": "Test course",
        "entity": "UNITAR",
        "country": "International",
        "official_url": url,
        "summary": "Test course",
        "raw_text": "Test course",
        "confidence_score": 0.55,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


# ── Extractor ─────────────────────────────────────────────────────────────────


class TestUnitarDetailFields:
    def test_deadline_maps_to_close(self):
        """RED E22: the ficha Deadline parses into close_date."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DETAIL_HTML)

        assert fields["close_date"] is not None
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2026, 10, 7,
        )

    def test_date_range_maps_to_open_and_close(self):
        """RED E22: the Date range start/end fill open/close when no Deadline."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DATE_ONLY_HTML)

        assert fields["open_date"] is not None
        assert (fields["open_date"].year, fields["open_date"].month, fields["open_date"].day) == (
            2026, 10, 12,
        )
        assert fields["close_date"] is not None
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2026, 11, 1,
        )

    def test_full_ficha_deadline_keeps_close(self):
        """Gap-fill inside the extractor: an explicit Deadline wins close_date."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DETAIL_HTML)

        assert (fields["open_date"].year, fields["open_date"].month, fields["open_date"].day) == (
            2026, 10, 12,
        )
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2026, 10, 7,
        )

    def test_price_maps_to_funding(self):
        """RED E23: Price $600.00 parses to (raw, 600.0, USD).

        Product decision (strictly scoped to event.unitar.org): UNITAR
        bills in dollars, so a bare-$ Price on a UNITAR ficha records
        as USD. The global E19 rule (no persisting currency-less
        amounts) stays intact elsewhere — see the global pin below.
        """
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DETAIL_HTML)

        assert fields["funding_amount_raw"] is not None and "600" in str(fields["funding_amount_raw"])
        assert fields["funding_amount_value"] == 600.0
        assert fields["funding_amount_currency"] == "USD"

    def test_global_bare_dollar_stays_currency_none(self):
        """Pin E23: outside UNITAR the global E19 rule holds — a bare-$

        amount parses with currency None (no persistence default)."""
        from app.connectors.common import extract_funding_details

        _, value, currency = extract_funding_details("Price $600.00")

        assert value == 600.0
        assert currency is None

    def test_self_paced_without_dates_yields_empty(self):
        """Self-paced fichas carry no Deadline/Date: pure gap-fill, no fabrication."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_NO_DATES_HTML)

        assert fields["open_date"] is None
        assert fields["close_date"] is None
        assert fields["funding_amount_raw"] is None
        assert fields["funding_amount_value"] is None
        assert fields["funding_amount_currency"] is None

    def test_never_raises_on_garbage(self):
        """Never-raise contract: None/empty/junk yield the five-key default."""
        from app.connectors.common import extract_unitar_detail_fields

        for junk in (None, "", "<html><body>%%%</body></html>"):
            fields = extract_unitar_detail_fields(junk)  # type: ignore[arg-type]

            assert fields["open_date"] is None
            assert fields["close_date"] is None
            assert fields["funding_amount_value"] is None


class TestUnitarDeadlineRegistContainer:
    def test_regist_container_maps_to_close(self):
        """RED: the field-event-deadline-regist value parses into close_date."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DEADLINE_REGIST_HTML)

        assert fields["close_date"] is not None
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2020, 4, 27,
        )

    def test_regist_container_with_time_maps_to_close(self):
        """RED: a trailing hour on the container value still parses the date."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DEADLINE_REGIST_TIME_HTML)

        assert fields["close_date"] is not None
        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2020, 4, 27,
        )

    def test_regist_container_garbage_yields_none(self):
        """Non-date container values stay None (gap-fill, never fabricated)."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DEADLINE_REGIST_GARBAGE_HTML)

        assert fields["close_date"] is None
        assert fields["open_date"] is None

    def test_regist_container_does_not_overwrite_explicit_deadline(self):
        """Gap-fill pin: an explicit flat Deadline keeps close_date."""
        from app.connectors.common import extract_unitar_detail_fields

        fields = extract_unitar_detail_fields(UNITAR_DETAIL_HTML)

        assert (fields["close_date"].year, fields["close_date"].month, fields["close_date"].day) == (
            2026, 10, 7,
        )


# ── Dispatch (host-gated in extract_page_fields) ──────────────────────────────


class TestUnitarDispatch:
    def test_page_fields_fill_from_unitar_detail_url(self):
        """RED E22: the detail-page path applies the ficha via page_url."""
        from app.connectors.common import extract_page_fields

        result = extract_page_fields(html=UNITAR_DETAIL_HTML, page_url=UNITAR_URL)

        assert result["open_date"] is not None
        assert (result["open_date"].year, result["open_date"].month, result["open_date"].day) == (
            2026, 10, 12,
        )
        assert result["close_date"] is not None
        assert (result["close_date"].year, result["close_date"].month, result["close_date"].day) == (
            2026, 10, 7,
        )
        assert result["funding_amount_value"] == 600.0

    def test_unrelated_host_skips_unitar_block(self):
        """Pin: the label mapping is host-gated — elsewhere the generic
        sweep fires instead (Deadline label→close via the labelled tier,
        earliest→open), proving the targeted range-start→open mapping
        did not run (it would yield open 12 Oct)."""
        from app.connectors.common import extract_page_fields

        result = extract_page_fields(html=UNITAR_DETAIL_HTML, page_url="https://example.com/call")

        # Generic path: labelled "Deadline" tier pins close to 7 Oct while
        # the untargeted sweep leaves open at the earliest date (7 Oct).
        assert result["open_date"] is not None
        assert (result["open_date"].year, result["open_date"].month, result["open_date"].day) == (
            2026, 10, 7,
        )
        assert result["close_date"] is not None
        assert (result["close_date"].year, result["close_date"].month, result["close_date"].day) == (
            2026, 10, 7,
        )


# ── Runner gate + batch ───────────────────────────────────────────────────────


class TestUnitarPilotGate:
    def test_unitar_key_joins_pilot_gate(self):
        """RED E22 (E20 lesson): without the key, fichas never fetch via runner."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        assert "unitar-courses" in DETAIL_ENRICHMENT_PILOT_KEYS

    @pytest.mark.asyncio
    async def test_pilot_batch_gap_fills_unitar_dates_and_funding(self, monkeypatch):
        """RED E22: an undated UNITAR candidate gains close/open + funding."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(UNITAR_URL, UNITAR_DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "unitar-courses",
            [_candidate(UNITAR_URL, entity="UNITAR", country="International")],
        )

        assert result.open_date is not None
        assert (result.open_date.year, result.open_date.month, result.open_date.day) == (2026, 10, 12)
        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (2026, 10, 7)
        assert result.funding_amount_value == 600.0
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    async def test_pilot_batch_preserves_existing_unitar_close(self, monkeypatch):
        """Gap-fill only: an already-dated ficha keeps its dates."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(UNITAR_URL, UNITAR_DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        existing_close = datetime(2026, 10, 5)

        (result,) = await enrich_pilot_candidates(
            "unitar-courses",
            [_candidate(UNITAR_URL, entity="UNITAR", country="International", close_date=existing_close)],
        )

        assert result.close_date == existing_close


class TestUnitarSeed:
    def test_seed_enables_detail_enrichment(self):
        """RED E22: the connector-level deep fetch must cover UNITAR fichas
        (mirror of the fondo E19 seed pin)."""
        import re
        from pathlib import Path

        seed_text = (Path(__file__).resolve().parent.parent / "app" / "db" / "seed.py").read_text()
        block = re.search(
            r'"key": "unitar-courses".*?connector_config": \{(.*?)\},',
            seed_text,
            flags=re.DOTALL,
        )
        assert block is not None
        config = block.group(1)
        assert '"detail_enrichment": True' in config
