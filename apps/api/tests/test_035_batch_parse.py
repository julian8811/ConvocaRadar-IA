"""035 parse fixtures for global funding+training batch. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "commonwealth-scholarships": {
        "url": "https://cscuk.fcdo.gov.uk/scholarships/",
        "entity": "CSC",
        "country": "United Kingdom",
        "html": """<html><body>
<article><h2><a href="/scholarships/commonwealth-fellowships-information-for-candidates/">
Commonwealth Fellowships – information for candidates</a></h2></article>
<article><h2><a href="/scholarships/commonwealth-startup-fellowships-information-for-candidates/">
Commonwealth Startup Fellowships – information for candidates</a></h2></article>
</body></html>""",
        "titles": (
            "Commonwealth Fellowships – information for candidates",
            "Commonwealth Startup Fellowships",
        ),
    },
    "unitar-courses": {
        "url": "https://www.unitar.org/courses",
        "entity": "UNITAR",
        "country": "International",
        "html": """<html><body>
<article><h2><a href="https://event.unitar.org/full-catalog/online-diploma-multilateral-diplomacy">
Online Diploma in Multilateral Diplomacy 2026</a></h2></article>
<article><h2><a href="https://event.unitar.org/full-catalog/climate-change-diplomacy">
Climate Change Diplomacy: Advanced Negotiation Skills</a></h2></article>
</body></html>""",
        "titles": (
            "Online Diploma in Multilateral Diplomacy 2026",
            "Climate Change Diplomacy",
        ),
    },
    "educationusa-scholarships": {
        "url": "https://educationusa.state.gov/find-financial-aid",
        "entity": "EducationUSA",
        "country": "United States",
        "html": """<html><body><main>
<h3><a href="/scholarships/nonresident-tuition-waiver-ntw-scholarships">
Nonresident Tuition Waiver (NTW) Scholarships</a></h3>
<h3><a href="/scholarships/aadf-scholarship-program">AADF Scholarship Program</a></h3>
</main></body></html>""",
        "titles": ("Nonresident Tuition Waiver", "AADF Scholarship Program"),
    },
    "iie-programs": {
        "url": "https://www.iie.org/programs/",
        "entity": "IIE",
        "country": "United States",
        "html": """<html><body><main>
<h2><a href="/programs/the-language-flagship-2/">The Language Flagship</a></h2>
<h2><a href="/programs/fulbright/">Fulbright Programs</a></h2>
</main></body></html>""",
        "titles": ("The Language Flagship", "Fulbright Programs"),
    },
    "macarthur-programs": {
        "url": "https://www.macfound.org/programs/",
        "entity": "MacArthur Foundation",
        "country": "United States",
        "html": """<html><body><main>
<a href="/programs/bigbets/ai-opportunity/">AI Opportunity</a>
<a href="/programs/bigbets/climate-solutions/">Climate Solutions</a>
</main></body></html>""",
        "titles": ("AI Opportunity", "Climate Solutions"),
    },
    "mext-scholarships": {
        "url": "https://www.studyinjapan.go.jp/en/planning/scholarship/",
        "entity": "MEXT",
        "country": "Japan",
        "html": """<html><body><main>
<a href="/en/planning/scholarships/about-scholarships/">Overview of Scholarships in Japan</a>
<a href="/en/planning/scholarships/mext-scholarships/">Japanese Government (MEXT) Scholarship</a>
</main></body></html>""",
        "titles": (
            "Overview of Scholarships in Japan",
            "Japanese Government (MEXT) Scholarship",
        ),
    },
    "worldbank-scholarships": {
        "url": "https://www.worldbank.org/en/programs/scholarships",
        "entity": "World Bank",
        "country": "International",
        "html": """<html><body><main>
<a href="/en/programs/scholarships/jj-wbgsp">JJ/WBGSP</a>
<a href="/en/programs/scholarships/japanese-nationals">Japanese Nationals</a>
</main></body></html>""",
        "titles": ("JJ/WBGSP", "Japanese Nationals"),
    },
    "amazon-research-awards": {
        "url": "https://www.amazon.science/research-awards",
        "entity": "Amazon Science",
        "country": "United States",
        "html": """<html><body><main>
<a href="/research-awards/call-for-proposals">Call for proposals</a>
<a href="/research-awards/program-rules">Program rules</a>
</main></body></html>""",
        "titles": ("Call for proposals", "Program rules"),
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
async def test_035_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
