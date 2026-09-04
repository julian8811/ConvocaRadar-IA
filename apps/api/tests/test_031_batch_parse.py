"""031 parse fixtures for foundation/global sources. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "moore-grant-opportunities": {
        "url": "https://www.moore.org/grant-opportunities",
        "country": "United States",
        "entity": "Gordon and Betty Moore Foundation",
        "html": """<html><body><ul class="program-sub-items">
<li><a href="/initiative-strategy-detail?initiativeId=andes-amazon-initiative">
  Andes-Amazon Initiative</a></li>
<li><a href="/initiative-strategy-detail?initiativeId=moore-inventor-fellows">
  Moore Inventor Fellows</a></li>
</ul></body></html>""",
        "titles": ("Andes-Amazon Initiative", "Moore Inventor Fellows"),
    },
    "mitacs-programs": {
        "url": "https://www.mitacs.ca/en/programs",
        "country": "Canada",
        "entity": "Mitacs",
        "html": """<html><body>
<div class="loop-program">
  <h3>Accelerate</h3>
  <a href="https://www.mitacs.ca/our-programs/accelerate/">Learn more</a>
</div>
<div class="loop-program">
  <h3>Globalink Research Award</h3>
  <a href="https://www.mitacs.ca/our-programs/globalink-research-award/">Learn more</a>
</div>
</body></html>""",
        "titles": ("Accelerate", "Globalink Research Award"),
    },
    "templeton-funding-areas": {
        "url": "https://www.templeton.org/funding-areas",
        "country": "United States",
        "entity": "John Templeton Foundation",
        "html": """<html><body><main>
<a href="/funding-areas/life-sciences">Explore</a>
<a href="/funding-areas/character-virtue-development">Character Virtue Development</a>
</main></body></html>""",
        "titles": ("Life Sciences", "Character Virtue Development"),
    },
    "mellon-grant-programs": {
        "url": "https://www.mellon.org/grant-programs",
        "country": "United States",
        "entity": "Mellon Foundation",
        "html": """<html><body>
<div class="grantmakingAreasGrid_card__lfea1">
  Arts and Culture Art and artists are essential to human connection.
  <a href="/grant-programs/arts-and-culture">Learn more</a>
</div>
<div class="grantmakingAreasGrid_card__lfea1">
  Higher Learning Knowledge is produced everywhere.
  <a href="/grant-programs/higher-learning">Learn more</a>
</div>
</body></html>""",
        "titles": ("Arts and Culture", "Higher Learning"),
    },
    "humboldt-sponsorship-programmes": {
        "url": "https://www.humboldt-foundation.de/en/apply/sponsorship-programmes",
        "country": "Germany",
        "entity": "Alexander von Humboldt Foundation",
        "html": """<html><body>
<div class="article-teaser">
  <h2 class="article-teaser__headline">Humboldt Research Fellowship</h2>
  <a href="/en/apply/sponsorship-programmes/humboldt-research-fellowship">More</a>
</div>
<a href="/en/apply/sponsorship-programmes/alexander-von-humboldt-professorship">
  Alexander von Humboldt Professorship</a>
</body></html>""",
        "titles": (
            "Humboldt Research Fellowship",
            "Alexander von Humboldt Professorship",
        ),
    },
    "boell-scholarships": {
        "url": "https://www.boell.de/en/applying-scholarship",
        "country": "Germany",
        "entity": "Heinrich Böll Foundation",
        "html": """<html><body><main>
<a href="https://www.boell.de/de/stipendium-studium">
  Application for a graduate scholarship</a>
<a href="https://stipendium.boell.de/Default.aspx">To the application portal</a>
</main></body></html>""",
        "titles": (
            "Application for a graduate scholarship",
            "To the application portal",
        ),
    },
    "fes-studienfoerderung": {
        "url": "https://www.fes.de/studienfoerderung",
        "country": "Germany",
        "entity": "Friedrich-Ebert-Stiftung",
        "html": """<html><body>
<div class="teaser">
  <div class="teaser-content-title">Ideelle Förderung</div>
  <a href="/studienfoerderung/ideelle-foerderung">Mehr</a>
</div>
<div class="teaser">
  <div class="teaser-content-title">Stipendien-Botschafter:innen</div>
  <a href="/studienfoerderung/stipendien-botschafter">Mehr</a>
</div>
</body></html>""",
        "titles": ("Ideelle Förderung", "Stipendien-Botschafter:innen"),
    },
    "pronabec-becas": {
        "url": "https://www.pronabec.gob.pe/concursos-becas-creditos/",
        "country": "Peru",
        "entity": "PRONABEC",
        "html": """<html><body><main>
<a href="https://www.pronabec.gob.pe/beca-18/">Beca 18</a>
<a href="https://www.pronabec.gob.pe/beca-permanencia/">Beca Permanencia</a>
</main></body></html>""",
        "titles": ("Beca 18", "Beca Permanencia"),
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
async def test_031_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
        any(expected in title for title in titles) for expected in meta["titles"]
    ), titles
    assert mock.await_count >= 1
