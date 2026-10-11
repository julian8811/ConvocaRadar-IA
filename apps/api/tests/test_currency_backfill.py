"""E24: currency backfill on re-scrape with strict TDD.

Server evidence: rows stuck with ``funding_amount_value=600.0`` and
``funding_amount_currency=None`` never receive the ``USD`` the extractor
already returns, because ``_update_opportunity`` only backfills funding
when the stored value is None.

Product rule: a missing currency is also missing data — when the stored
currency is None and the extraction brings a non-None currency, fill it,
but ONLY when the incoming value is None or matches the stored one
(never mix a new raw/currency with a different stored value; never
overwrite a stored value or currency). Raw fills only when the stored
raw is None and the values coincide.

All fixtures below are inline — zero network.
"""

from __future__ import annotations

from app.models import Opportunity
from app.schemas import OpportunityCreate
from app.services.opportunity import _update_opportunity


def _make_opp(**kwargs) -> Opportunity:
    defaults = dict(
        title="Test course",
        slug="test-course",
        entity="UNITAR",
        country="International",
        categories=[],
        topics=[],
        description="Base description",
        summary="Base summary with enough substance to survive re-scrapes intact here.",
        raw_text="Base raw text",
        language="en",
        confidence_score=0.8,
        status="open",
        user_status="none",
    )
    defaults.update(kwargs)
    return Opportunity(**defaults)


def _make_data(**kwargs) -> OpportunityCreate:
    base = dict(
        title="Test course",
        entity="UNITAR",
        country="International",
        official_url="https://event.unitar.org/full-catalog/test-course",
        summary="Incoming summary with enough substance to survive the merge intact.",
        description="Incoming description",
        raw_text="Incoming raw text",
        confidence_score=0.82,
    )
    base.update(kwargs)
    return OpportunityCreate(**base)


class TestCurrencyBackfill:
    def test_currency_backfills_when_values_match(self):
        """RED E24: stored (600, None) + extraction (600, USD) gains USD."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency=None,
            funding_amount_raw="$600.00",
        )
        data = _make_data(
            funding_amount_value=600.0,
            funding_amount_currency="USD",
            funding_amount_raw="$600.00",
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_value == 600.0
        assert opp.funding_amount_currency == "USD"

    def test_currency_backfills_when_incoming_value_is_none(self):
        """Stored (600, None) + currency-only extraction (None, USD) gains USD."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency=None,
            funding_amount_raw="$600.00",
        )
        data = _make_data(
            funding_amount_value=None,
            funding_amount_currency="USD",
            funding_amount_raw=None,
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_value == 600.0
        assert opp.funding_amount_currency == "USD"

    def test_raw_backfills_when_values_match(self):
        """Stored raw None + matching values fills raw alongside currency."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency=None,
            funding_amount_raw=None,
        )
        data = _make_data(
            funding_amount_value=600.0,
            funding_amount_currency="USD",
            funding_amount_raw="$600.00",
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_value == 600.0
        assert opp.funding_amount_currency == "USD"
        assert opp.funding_amount_raw == "$600.00"


class TestCurrencyBackfillPins:
    def test_existing_currency_never_overwritten(self):
        """Pin: stored EUR + extraction USD keeps EUR."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency="EUR",
            funding_amount_raw="600 EUR",
        )
        data = _make_data(
            funding_amount_value=600.0,
            funding_amount_currency="USD",
            funding_amount_raw="$600.00",
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_value == 600.0
        assert opp.funding_amount_currency == "EUR"
        assert opp.funding_amount_raw == "600 EUR"

    def test_mismatched_value_never_mixes_currency(self):
        """Pin: stored 600 + extraction (700, USD) leaves currency None."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency=None,
            funding_amount_raw="$600.00",
        )
        data = _make_data(
            funding_amount_value=700.0,
            funding_amount_currency="USD",
            funding_amount_raw="$700.00",
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_value == 600.0
        assert opp.funding_amount_currency is None
        assert opp.funding_amount_raw == "$600.00"

    def test_existing_value_never_overwritten(self):
        """Pin: stored 600 is never replaced by an incoming 700."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency=None,
            funding_amount_raw="$600.00",
        )
        data = _make_data(
            funding_amount_value=700.0,
            funding_amount_currency="USD",
            funding_amount_raw="$700.00",
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_value == 600.0

    def test_existing_raw_never_overwritten(self):
        """Pin: stored raw stays even when values coincide."""
        opp = _make_opp(
            funding_amount_value=600.0,
            funding_amount_currency=None,
            funding_amount_raw="$600.00",
        )
        data = _make_data(
            funding_amount_value=600.0,
            funding_amount_currency="USD",
            funding_amount_raw="USD 600",
        )

        _update_opportunity(opp, data, opp.title)

        assert opp.funding_amount_currency == "USD"
        assert opp.funding_amount_raw == "$600.00"
