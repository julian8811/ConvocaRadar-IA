"""036 parse fixtures for more global sources. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "nuffic-scholarships": {
        "url": "https://www.nuffic.nl/en/subjects/scholarships",
        "entity": "Nuffic",
        "country": "Netherlands",
        "html": """<html><body><main>
<a href="/en/international/mena-scholarship-programme-msp">Mena Scholarship Programme</a>
<a href="/en/international/nl-scholarship">NL Scholarship Programme</a>
</main></body></html>""",
        "titles": ("Mena Scholarship Programme", "NL Scholarship Programme"),
    },
    "nz-manaaki-scholarships": {
        "url": "https://www.mfat.govt.nz/en/aid-and-development/new-zealand-government-scholarships",
        "entity": "MFAT",
        "country": "New Zealand",
        "html": """<html><body><main>
<a href="/types-of-manaaki-scholarships/">Types of Scholarships</a>
<a href="/thematic-short-term-training-scholarships/">Thematic Short Term Training Scholarships</a>
</main></body></html>""",
        "titles": ("Types of Scholarships", "Thematic Short Term Training Scholarships"),
    },
    "owsd-fellowships": {
        "url": "https://owsd.net/career-development/phd-fellowship",
        "entity": "OWSD",
        "country": "International",
        "html": """<html><body><main>
<a href="/phd-fellowships">PhD Fellowships</a>
<a href="/early-career-fellowship">Early Career Fellowship</a>
</main></body></html>""",
        "titles": ("PhD Fellowships", "Early Career Fellowship"),
    },
    "ashoka-fellowship": {
        "url": "https://www.ashoka.org/en-us/program/ashoka-fellowship",
        "entity": "Ashoka",
        "country": "International",
        "html": """<html><body><main>
<a href="/en-us/ashoka-fellows">Ashoka Fellows</a>
<a href="/en-us/program/venture-selecting-our-ashoka-fellows">Selecting Ashoka Fellows</a>
</main></body></html>""",
        "titles": ("Ashoka Fellows", "Selecting Ashoka Fellows"),
    },
    "erc-grants": {
        "url": "https://erc.europa.eu/apply-grant",
        "entity": "ERC",
        "country": "European Union",
        "html": """<html><body><main>
<a href="/apply-grant/starting-grant">Starting Grant</a>
<a href="/apply-grant/consolidator-grant">Consolidator Grant</a>
</main></body></html>""",
        "titles": ("Starting Grant", "Consolidator Grant"),
    },
    "simons-funding": {
        "url": "https://www.simonsfoundation.org/funding-opportunities/",
        "entity": "Simons Foundation",
        "country": "United States",
        "html": """<html><body><main>
<a href="/funding-opportunities/math-rfa">Mathematics and Physical Sciences RFA</a>
<a href="/funding-opportunities/neuroscience">Neuroscience Collaborations</a>
</main></body></html>""",
        "titles": ("Mathematics and Physical Sciences RFA", "Neuroscience Collaborations"),
    },
    "sloan-grants": {
        "url": "https://sloan.org/grants/apply",
        "entity": "Sloan Foundation",
        "country": "United States",
        "html": """<html><body><main>
<a href="/grants/open-calls">Open Calls</a>
<a href="/grants/grantees">For Grantees</a>
</main></body></html>""",
        "titles": ("Open Calls", "For Grantees"),
    },
    "climateworks-programs": {
        "url": "https://www.climateworks.org/programs/",
        "entity": "ClimateWorks",
        "country": "International",
        "html": """<html><body><main>
<a href="/programs/adaptation-and-resilience/">Adaptation &amp; Resilience</a>
<a href="/programs/aviation/">Aviation</a>
</main></body></html>""",
        "titles": ("Adaptation & Resilience", "Aviation"),
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
async def test_036_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = BATCH[key]
    mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        key,
        meta["url"],
        _seed_config(key),
        entity_name=meta["entity"],
        default_country=meta["country"],
    )
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    assert len(candidates) >= 1
    titles = {c.title for c in candidates}
    assert any(
        any(expected.lower() in title.lower() for title in titles)
        for expected in meta["titles"]
    ), titles
