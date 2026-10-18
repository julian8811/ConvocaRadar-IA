"""T4: Novo Nordisk grants must enrich funding/dates from detail pages.

Prod evidence 2026-10-18: novo-nordisk-grants holds 111 rows with 89
missing funding. The WP JSON list always carries ``acf: []`` (E18
forensic) while detail fichas render Amount (DKK) plus Call opens/closes
(E19 ``extract_novo_detail_fields``). The ingest path never fetches
details, so funding stays missing forever. Detail enrichment is opt-in
per source (novo only) so ascun and other WP-routed sources keep legacy
behavior untouched.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch


def _grant_item():
    return {
        "status": "publish",
        "title": {"rendered": "PREPARE educational grant"},
        "link": "https://novonordiskfonden.dk/en/prepare-grant",
        "acf": {},
        "date": "2026-10-01T00:00:00",
    }


def _raw(items):
    from app.connectors.base import RawSourceResult

    return RawSourceResult(
        source_key="novo-nordisk-grants",
        url="https://novonordiskfonden.dk/wp-json/wp/v2/grant",
        content=json.dumps(items),
        content_type="application/json",
        metadata={},
    )


def _novo_connector(**kwargs):
    from app.connectors.wordpress_grants import WordPressGrantsConnector

    kwargs.setdefault("source_key", "novo-nordisk-grants")
    kwargs.setdefault("base_url", "https://novonordiskfonden.dk/wp-json/wp/v2/grant")
    kwargs.setdefault("entity_name", "Novo Nordisk Foundation")
    kwargs.setdefault("default_country", "Denmark")
    kwargs.setdefault("allowed_domains", ["novonordiskfonden.dk"])
    return WordPressGrantsConnector(**kwargs)


_DETAIL_FIELDS = {
    "title": "PREPARE educational grant",
    "funding_amount_raw": "DKK 10 million per grant",
    "funding_amount_value": 10_000_000.0,
    "funding_amount_currency": "DKK",
    "close_date": datetime(2027, 1, 25),
}


class TestNovoDetailEnrichment:
    async def test_parse_enriches_missing_funding_from_detail(self):
        """Opt-in connector fills funding + close from the detail ficha."""
        connector = _novo_connector(detail_enrichment=True)
        with patch(
            "app.connectors.wordpress_grants.enrich_from_detail_page",
            new_callable=AsyncMock,
        ) as mock_detail:
            mock_detail.return_value = dict(_DETAIL_FIELDS)
            candidates = await connector.parse(_raw([_grant_item()]))

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.funding_amount_value == 10_000_000.0
        assert candidate.funding_amount_currency == "DKK"
        assert candidate.close_date == datetime(2027, 1, 25)
        mock_detail.assert_awaited_once()

    async def test_gap_fill_never_overwrites_list_fields(self):
        """A close date from the list survives a conflicting detail date."""
        item = _grant_item()
        item["acf"] = {"deadline": "2026-12-31T00:00:00"}
        connector = _novo_connector(detail_enrichment=True)
        detail = dict(_DETAIL_FIELDS)
        detail["close_date"] = datetime(2027, 6, 30)
        with patch(
            "app.connectors.wordpress_grants.enrich_from_detail_page",
            new_callable=AsyncMock,
        ) as mock_detail:
            mock_detail.return_value = detail
            candidates = await connector.parse(_raw([item]))

        assert candidates[0].close_date == datetime(2026, 12, 31)
        assert candidates[0].funding_amount_value == 10_000_000.0

    async def test_off_by_default_skips_detail_fetch(self):
        """Legacy behavior: no flag means no detail HTTP, funding stays None."""
        connector = _novo_connector()
        assert connector.detail_enrichment is False
        candidates = await connector.parse(_raw([_grant_item()]))

        assert len(candidates) == 1
        assert candidates[0].funding_amount_value is None
        assert candidates[0].funding_amount_currency is None


class TestNovoDetailFactory:
    def test_factory_enables_detail_for_novo_only(self):
        from app.connectors.factory import connector_for

        novo = connector_for(
            "novo-nordisk-grants",
            "https://novonordiskfonden.dk/wp-json/wp/v2/grant?per_page=100&status=publish",
        )
        assert novo.detail_enrichment is True

        ascun = connector_for(
            "ascun-convocatorias",
            "https://ascun.org.co/wp-json/wp/v2/posts",
        )
        assert ascun.detail_enrichment is False
