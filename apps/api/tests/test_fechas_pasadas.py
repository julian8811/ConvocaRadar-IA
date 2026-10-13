"""Past close dates: live year-guard pin + merge-path backfill.

Forensic: "La convocatoria estara abierta hasta el 17 de julio de 2020"
matches the ``extract_close_date`` "hasta el <date>" tier, but
``_year_guard`` (window 2024-2028, ``common.py``) discards it, so the row
stays open with no close forever instead of recalculating to closed.

Contract:
- Live scraping keeps the guard (default ``allow_past=False``): bare
  date mentions from other years stay noise, never fabricated closes.
- The merge path (``_update_opportunity``) re-extracts with
  ``allow_past=True`` when both stored and incoming closes are missing,
  so a genuinely extracted past close persists and the status
  recalculates to closed. Existing closes are never overwritten.

All fixtures are inline — zero network.
"""

from __future__ import annotations

from datetime import datetime

from app.models import Opportunity, OpportunityStatus
from app.schemas import OpportunityCreate


PAST_TEXT = "La convocatoria estara abierta hasta el 17 de julio de 2020"
PAST_CLOSE = datetime(2020, 7, 17)

NOISE_TEXT = ".box-address { color: white; display: flex; } budgetyearscolumns 12345"


def _data(**overrides) -> OpportunityCreate:
    base = {
        "title": "Convocatoria Uniandes",
        "entity": "Universidad de los Andes",
        "country": "Colombia",
        "summary": "Convocatoria Uniandes",
        "raw_text": "Convocatoria Uniandes",
    }
    base.update(overrides)
    return OpportunityCreate(**base)


def _row(**overrides) -> Opportunity:
    base = {
        "title": "Convocatoria Uniandes",
        "slug": "convocatoria-uniandes",
        "entity": "Universidad de los Andes",
        "country": "Colombia",
        "summary": "Convocatoria Uniandes",
        "raw_text": "Convocatoria Uniandes",
        "status": OpportunityStatus.unknown.value,
    }
    base.update(overrides)
    return Opportunity(**base)


class TestLiveGuardKeepsPastOut:
    def test_extract_close_date_discards_past_by_default(self):
        """RED fix 1: live path still guards the 2020 close out."""
        from app.connectors.common import extract_close_date

        assert extract_close_date(PAST_TEXT) is None

    def test_parse_date_text_discards_past_by_default(self):
        """Pin: the parser itself guards past years unless opted in."""
        from app.connectors.common import parse_date_text

        assert parse_date_text("17 de julio de 2020") is None

    def test_allow_past_returns_the_extracted_close(self):
        """RED fix 1: opt-in lets the genuinely extracted 2020 date through."""
        from app.connectors.common import extract_close_date

        assert extract_close_date(PAST_TEXT, allow_past=True) == PAST_CLOSE

    def test_allow_past_still_rejects_absurd_future(self):
        """Pin: opt-in only opens the past side; far-future noise stays out."""
        from app.connectors.common import extract_close_date

        assert extract_close_date("cierre: 30 de junio de 2099", allow_past=True) is None

    def test_allow_past_never_raises_on_garbage(self):
        """Never-raise contract holds with the opt-in flag too."""
        from app.connectors.common import extract_close_date

        assert extract_close_date("", allow_past=True) is None
        assert extract_close_date(NOISE_TEXT, allow_past=True) is None


class TestMergeBackfillsPastClose:
    def test_past_close_persists_and_status_recalculates_to_closed(self):
        """RED fix 1: merge backfills the 2020 close and closes the row."""
        from app.services.opportunity import _update_opportunity

        row = _row(close_date=None, status=OpportunityStatus.open.value)
        incoming = _data(close_date=None, raw_text=PAST_TEXT)

        _update_opportunity(row, incoming, "Convocatoria Uniandes")

        assert row.close_date == PAST_CLOSE
        assert row.status == OpportunityStatus.closed.value

    def test_future_close_intact_through_normal_path(self):
        """Pin: a future close still merges via the normal path, never closed."""
        from app.services.opportunity import _update_opportunity

        future = datetime(2027, 12, 31)
        row = _row(close_date=None)
        incoming = _data(close_date=future, raw_text="Some call text")

        _update_opportunity(row, incoming, "Convocatoria Uniandes")

        assert row.close_date == future
        assert row.status == OpportunityStatus.open.value

    def test_existing_close_never_overwritten_by_past_mention(self):
        """Gap-fill only: a stored close wins over a past date in new text."""
        from app.services.opportunity import _update_opportunity

        stored = datetime(2027, 3, 15)
        row = _row(close_date=stored)
        incoming = _data(close_date=None, raw_text=PAST_TEXT)

        _update_opportunity(row, incoming, "Convocatoria Uniandes")

        assert row.close_date == stored

    def test_noise_without_date_stays_datelss(self):
        """Pin: text with no date still yields no close on merge."""
        from app.services.opportunity import _update_opportunity

        row = _row(close_date=None)
        incoming = _data(close_date=None, raw_text=NOISE_TEXT, summary="n")

        _update_opportunity(row, incoming, "Convocatoria Uniandes")

        assert row.close_date is None
