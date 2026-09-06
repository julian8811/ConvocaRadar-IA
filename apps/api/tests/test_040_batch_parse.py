"""040 parse fixtures for 8-source expansion. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "jsps-kakenhi-grants": {
        "url": "https://www.jsps.go.jp/english/e-grants/",
        "entity": "JSPS",
        "html": """<html><body><main>
<article><h2><a href="/english/e-grants/grant-2026-1">KAKENHI Grant-in-Aid for Scientific Research 2026</a></h2></article>
<article><h2><a href="/english/e-grants/grant-2026-2">JSPS Bilateral Joint Research Grant</a></h2></article>
</main></body></html>""",
        "titles": ("KAKENHI Grant-in-Aid", "Bilateral Joint Research Grant"),
    },
    "jsps-fellowships": {
        "url": "https://www.jsps.go.jp/english/e-fellow/",
        "entity": "JSPS",
        "html": """<html><body><main>
<article><h2><a href="/english/e-fellow/fellowship-2026">JSPS Postdoctoral Fellowship for Research in Japan 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Postdoctoral Fellowship",),
    },
    "rwjf-grants-funding": {
        "url": "https://www.rwjf.org/en/grants.html",
        "entity": "RWJF",
        "html": """<html><body><main>
<article><h2><a href="/en/grants/grant-pioneering-2026">RWJF Pioneering Ideas Grant 2026</a></h2></article>
<article><h2><a href="/en/grants/funding-culture-health">RWJF Culture of Health Funding Opportunity</a></h2></article>
</main></body></html>""",
        "titles": ("Pioneering Ideas Grant", "Culture of Health"),
    },
    "czi-science-grants": {
        "url": "https://chanzuckerberg.com/grants-ventures/grants/",
        "entity": "CZI",
        "html": """<html><body><main>
<article><h2><a href="/grants-ventures/grants/grant-single-cell-2026">CZI Single-Cell Biology Grant 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Single-Cell Biology Grant",),
    },
    "kellogg-foundation-grants": {
        "url": "https://www.wkkf.org/grantseekers/",
        "entity": "Kellogg Foundation",
        "html": """<html><body><main>
<article><h2><a href="/grantseekers/grant-2026-1">WKKF Racial Equity Grant Opportunity 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Racial Equity Grant",),
    },
    "hewlett-foundation-grants": {
        "url": "https://hewlett.org/grants/",
        "entity": "Hewlett Foundation",
        "html": """<html><body><main>
<article><h2><a href="/grants/grant-education-2026">Hewlett Foundation Education Grant 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Hewlett Foundation Education Grant",),
    },
    "carnegie-foundation-grants": {
        "url": "https://www.carnegie.org/grants/",
        "entity": "Carnegie",
        "html": """<html><body><main>
<article><h2><a href="/grants/grant-democracy-2026">Carnegie Democracy and Education Grant 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Carnegie Democracy",),
    },
    "nrf-south-africa-bursaries": {
        "url": "https://www.nrf.ac.za/bursaries/",
        "entity": "NRF",
        "html": """<html><body><main>
<article><h2><a href="/bursaries/bursary-masters-2026">NRF Masters Bursary Programme 2026</a></h2></article>
<article><h2><a href="/bursaries/funding-doctoral-2026">NRF Doctoral Funding Opportunity</a></h2></article>
</main></body></html>""",
        "titles": ("Masters Bursary", "Doctoral Funding"),
    },
}


def _seed_config(key: str) -> dict:
    seed_path = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "seed_default_sources":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "source_definitions":
                    defs = {item["key"]: item for item in ast.literal_eval(stmt.value)}
                    return defs[key]["connector_config"]
    raise AssertionError(f"config missing for {key}")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", list(BATCH))
async def test_040_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = BATCH[key]
    mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        key,
        meta["url"],
        _seed_config(key),
        entity_name=meta["entity"],
        default_country="International",
    )
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    assert len(candidates) >= 1, f"{key} yielded 0 candidates"
    titles = {c.title for c in candidates}
    assert any(
        any(expected.lower() in title.lower() for title in titles)
        for expected in meta["titles"]
    ), titles


@pytest.mark.asyncio
async def test_040_probe_batch_total_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe batch 32 analog: total titles >0 across all 8 seeds mocked."""
    total = 0
    for key, meta in BATCH.items():
        mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(key, meta["url"], _seed_config(key), entity_name=meta["entity"], default_country="International")
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1, f"{key} smoke 0"
        total += len(candidates)
    assert total >= 8, f"probe total {total} < 8"
    # budget invariant: 8 weekly = 8/7 ≈1.14/day → 27.6→28.7/day
    assert total > 0


@pytest.mark.asyncio
async def test_040_smoke_per_seed_ge_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live-smoke batch 20 analog: each enabled seed ≥1 opportunity."""
    for key, meta in BATCH.items():
        mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(key, meta["url"], _seed_config(key), entity_name=meta["entity"], default_country="International")
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        # validate candidate shape
        c = candidates[0]
        assert c.title and len(c.title) >= 4
        assert c.official_url.startswith("http")
