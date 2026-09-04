"""037 parse fixtures for more sources batch. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "rhodes-scholarship": {
        "url": "https://www.rhodeshouse.ox.ac.uk/apply/",
        "entity": "Rhodes Trust",
        "country": "United Kingdom",
        "html": """<html><body><main>
<a href="/scholarships/the-rhodes-scholarship/">The Rhodes Scholarship</a>
<a href="/scholarships/selection-criteria/">Selection Criteria</a>
</main></body></html>""",
        "titles": ("The Rhodes Scholarship", "Selection Criteria"),
    },
    "knight-hennessy-scholars": {
        "url": "https://knight-hennessy.stanford.edu/admission",
        "entity": "Knight-Hennessy",
        "country": "United States",
        "html": """<html><body><main>
<a href="/admission/before-you-apply">Before You Apply</a>
<a href="/admission/why-khs">Why KHS</a>
</main></body></html>""",
        "titles": ("Before You Apply", "Why KHS"),
    },
    "gates-cambridge": {
        "url": "https://www.gatescambridge.org/apply/",
        "entity": "Gates Cambridge",
        "country": "United Kingdom",
        "html": """<html><body><main>
<a href="/apply/eligibility">Eligibility</a>
<a href="/apply/how-to-apply">How to Apply</a>
</main></body></html>""",
        "titles": ("Eligibility", "How to Apply"),
    },
    "acumen-fellowship": {
        "url": "https://acumen.org/fellowship/",
        "entity": "Acumen",
        "country": "International",
        "html": """<html><body><main>
<a href="https://acumenacademy.org/fellowship">Fellowship</a>
<a href="https://acumenacademy.org/">Acumen Academy Training Leaders</a>
</main></body></html>""",
        "titles": ("Fellowship", "Acumen Academy"),
    },
    "vliruos-scholarships": {
        "url": "https://www.vliruos.be/en/scholarships",
        "entity": "VLIR-UOS",
        "country": "Belgium",
        "html": """<html><body><main>
<a href="/get-funded">Get Funded</a>
<a href="/en/scholarships/framework">Scholarship framework</a>
</main></body></html>""",
        "titles": ("Get Funded", "Scholarship framework"),
    },
    "twas-opportunities": {
        "url": "https://twas.org/opportunities",
        "entity": "TWAS",
        "country": "International",
        "html": """<html><body><main>
<a href="/opportunity/twas-sissa-lincei">TWAS-SISSA-Lincei Research Cooperation Visits Programme</a>
<a href="/opportunity/climate-change">Climate change and environment</a>
</main></body></html>""",
        "titles": (
            "TWAS-SISSA-Lincei Research Cooperation Visits Programme",
            "Climate change and environment",
        ),
    },
    "schmidt-sciences": {
        "url": "https://www.schmidtsciences.org/opportunities",
        "entity": "Schmidt Sciences",
        "country": "United States",
        "html": """<html><body><main>
<a href="/opportunities">Opportunities for Funding</a>
<a href="/focus-area-ai">AI &amp; Advanced Computing</a>
</main></body></html>""",
        "titles": ("Opportunities for Funding", "AI & Advanced Computing"),
    },
    "echoing-green-fellowship": {
        "url": "https://echoinggreen.org/fellowship/",
        "entity": "Echoing Green",
        "country": "United States",
        "html": """<html><body><main>
<a href="/fellowship/apply">Apply to the Fellowship</a>
<a href="/fellowship/fellows">Meet Our Newest Fellows!</a>
</main></body></html>""",
        "titles": ("Apply to the Fellowship", "Meet Our Newest Fellows"),
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
async def test_037_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
