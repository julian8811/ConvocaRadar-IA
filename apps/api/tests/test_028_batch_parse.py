"""028 parse fixtures for six new global HTML sources. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector
from app.connectors.factory import connector_for

BATCH = {
    "usa-gov-challenges": {
        "url": "https://www.usa.gov/find-active-challenge",
        "country": "United States",
        "entity": "USA.gov",
        "html": """<html><body><main>
<ul class="navigation__items children">
  <li class="navigation__item child">
    <a href="/challenges/nasa-techrise-student-challenge">
      2026-27 NASA TechRise Student Challenge</a>
  </li>
  <li class="navigation__item child">
    <a href="/challenges/acl-caregiver-ai-prize">ACL Caregiver AI Prize</a>
  </li>
</ul>
</main></body></html>""",
        "titles": (
            "2026-27 NASA TechRise Student Challenge",
            "ACL Caregiver AI Prize",
        ),
    },
    "fogarty-funding-opps": {
        "url": "https://www.fic.nih.gov/Funding/Pages/Fogarty-Funding-Opps.aspx",
        "country": "International",
        "entity": "Fogarty International Center",
        "html": """<html><body><table><tbody>
<tr>
  <td class="ms-vb fic-fo">December 3, 2026</td>
  <td class="ms-vb fic-fo fic-award-title">
    <a href="https://grants.nih.gov/grants/guide/pa-files/PAR-24-295.html">
      Emerging Global Leader Award (K43) (PAR-24-295)</a>
  </td>
</tr>
<tr>
  <td class="ms-vb fic-fo">December 3, 2026</td>
  <td class="ms-vb fic-fo fic-award-title">
    <a href="https://grants.nih.gov/grants/guide/pa-files/PAR-24-296.html">
      Emerging Global Leader Award Not Allowed (PAR-24-296)</a>
  </td>
</tr>
</tbody></table></body></html>""",
        "titles": (
            "Emerging Global Leader Award (K43) (PAR-24-295)",
            "Emerging Global Leader Award Not Allowed (PAR-24-296)",
        ),
    },
    "embo-fellowships": {
        "url": "https://www.embo.org/funding/fellowships-grants-and-career-support/",
        "country": "International",
        "entity": "EMBO",
        "html": """<html><body><main>
<ul>
  <li>
    <a href="https://www.embo.org/funding/fellowships-grants-and-career-support/postdoctoral-fellowships/">
      Postdoctoral Fellowships</a>
  </li>
  <li>
    <a href="https://www.embo.org/funding/fellowships-grants-and-career-support/young-investigator-programme/">
      Young Investigator Programme</a>
  </li>
</ul>
</main></body></html>""",
        "titles": ("Postdoctoral Fellowships", "Young Investigator Programme"),
    },
    "msca-funding": {
        "url": "https://marie-sklodowska-curie-actions.ec.europa.eu/funding",
        "country": "European Union",
        "entity": "MSCA",
        "html": """<html><body><main>
<ul>
  <li>
    <a href="/actions/postdoctoral-fellowships">Postdoctoral Fellowships</a>
  </li>
  <li>
    <a href="/actions/doctoral-networks">Doctoral Networks</a>
  </li>
</ul>
</main></body></html>""",
        "titles": ("Postdoctoral Fellowships", "Doctoral Networks"),
    },
    "open-society-grants": {
        "url": "https://www.opensocietyfoundations.org/grants",
        "country": "International",
        "entity": "Open Society Foundations",
        "html": """<html><body><ul class="m-cardsList__list">
<li class="m-cardsList__item">
  <a class="a-grantsCard"
     href="https://www.opensocietyfoundations.org/grants/open-society-fellowship">
    <h2 class="a-grantsCard__title">Open Society Fellowship</h2>
    <footer class="a-grantsCard__footer">DEADLINE: Rolling</footer>
  </a>
</li>
</ul></body></html>""",
        "titles": ("Open Society Fellowship",),
    },
    "who-tdr-grants": {
        "url": "https://tdr.who.int/grants",
        "country": "International",
        "entity": "WHO TDR",
        "html": """<html><body><main>
<div class="list-view--item">
  <h2>
    <a href="https://tdr.who.int/home/our-work/global-engagement/tdr-impact-research-grants-scheme">
      TDR Impact Research Grants Scheme</a>
  </h2>
</div>
<div class="list-view--item">
  <h3>
    <a href="https://tdr.who.int/home/our-work/strengthening-research-capacity/clinical-research-and-development-fellowship">
      Clinical Research and Development Fellowship</a>
  </h3>
</div>
</main></body></html>""",
        "titles": (
            "TDR Impact Research Grants Scheme",
            "Clinical Research and Development Fellowship",
        ),
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
                    for item in ast.literal_eval(stmt.value):
                        if item["key"] == key:
                            return item["connector_config"]
    raise AssertionError(f"connector_config missing for {key}")


@pytest.mark.parametrize("key", list(BATCH))
def test_connector_for_returns_configurable_html(key: str):
    meta = BATCH[key]
    connector = connector_for(
        key,
        meta["url"],
        "html",
        entity_name=meta["entity"],
        default_country=meta["country"],
        connector_config=_seed_config(key),
    )
    assert isinstance(connector, ConfigurableHtmlConnector)
    assert connector.source_key == key


@pytest.mark.asyncio
@pytest.mark.parametrize("key", list(BATCH))
async def test_parse_fixture_yields_candidates(key: str, monkeypatch: pytest.MonkeyPatch):
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
    assert any(expected in titles for expected in meta["titles"])
    assert mock.await_count >= 1
