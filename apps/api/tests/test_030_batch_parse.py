"""030 parse fixtures for plan-completion sources. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector
from app.connectors.factory import connector_for

BATCH = {
    "adaptation-fund-apply": {
        "url": "https://www.adaptation-fund.org/apply-funding/",
        "country": "International",
        "entity": "Adaptation Fund",
        "html": """<html><body><main>
<ul>
  <li class="wp-block-navigation-item">
    <a href="https://www.adaptation-fund.org/apply-funding/locally-led-adaptation/lla-single-country-grants/">
      LLA Single Country Grants</a>
  </li>
  <li class="wp-block-navigation-item">
    <a href="https://www.adaptation-fund.org/apply-funding/accreditation/accreditation-application/">
      Accreditation Application</a>
  </li>
</ul>
</main></body></html>""",
        "titles": ("LLA Single Country Grants", "Accreditation Application"),
    },
    "unicef-venture-fund": {
        "url": "https://www.unicefventurefund.org/apply-funding",
        "country": "International",
        "entity": "UNICEF Venture Fund",
        "html": """<html><body><main>
<div class="call-application-banner">
  <div class="call_title">Funding Opportunity for FemTech Solutions</div>
  <a href="/call/funding-opportunity-femtech-solutions">view call details</a>
</div>
<div class="call-application-banner">
  <div class="call_title">AI and Blockchain for Data and Trust</div>
  <a href="/call/ai-and-blockchain-data-and-trust">view call details</a>
</div>
</main></body></html>""",
        "titles": (
            "Funding Opportunity for FemTech Solutions",
            "AI and Blockchain for Data and Trust",
        ),
    },
    "volkswagenstiftung-funding": {
        "url": "https://www.volkswagenstiftung.de/en/our-funding-portfolio",
        "country": "Germany",
        "entity": "Volkswagen Foundation",
        "html": """<html><body><ul class="list-grant__items">
<li class="list-grant__item">
  <div class="list-item-grant">
    <h3>Transatlantic Bridge Professorships</h3>
    <a class="cta-link" href="/en/funding/funding-offer/transatlantic-bridge-professorships">Learn more</a>
  </div>
</li>
<li class="list-grant__item">
  <div class="list-item-grant">
    <h3>Opus Magnum</h3>
    <a class="cta-link" href="/en/funding/funding-offer/opus-magnum">Learn more</a>
  </div>
</li>
</ul></body></html>""",
        "titles": ("Transatlantic Bridge Professorships", "Opus Magnum"),
    },
    "sdde-bogota-convocatorias": {
        "url": "https://desarrolloeconomico.gov.co/convocatorias/",
        "country": "Colombia",
        "entity": "SDDE Bogotá",
        "html": """<html><body><main><table><tbody>
<tr><td><a href="https://desarrolloeconomico.gov.co/documento/43668">
  AVISO DE CONVOCATORIA SDDE-SASI-001-2026</a></td></tr>
<tr><td><a href="https://desarrolloeconomico.gov.co/documento/39224">
  Primer Aviso de Convocatoria SDDE-LP-009-2025</a></td></tr>
</tbody></table></main></body></html>""",
        "titles": (
            "AVISO DE CONVOCATORIA SDDE-SASI-001-2026",
            "Primer Aviso de Convocatoria SDDE-LP-009-2025",
        ),
    },
    "eafit-becas-financiacion": {
        "url": "https://www.eafit.edu.co/becas-y-financiacion",
        "country": "Colombia",
        "entity": "EAFIT",
        "html": """<html><body><main>
<div class="cards-cuadradas">
  <h3 class="coh-heading">Fondo Futuro</h3>
  <a href="/becas-y-financiacion/fondo-futuro">Conoce el Fondo Futuro</a>
</div>
<div class="cards-cuadradas">
  <h3 class="coh-heading">EAFIT a tu alcance</h3>
  <a href="/becas-y-financiacion/eafit-a-tu-alcance">Conoce esta oportunidad</a>
</div>
</main></body></html>""",
        "titles": ("Fondo Futuro", "EAFIT a tu alcance"),
    },
    "hubbog-aceleracion": {
        "url": "https://www.hubbog.com/",
        "country": "Colombia",
        "entity": "HubBOG",
        "html": """<html><body>
<div class="feature-card">
  <a href="/aceleracion-e-innovacion">Programa de Aceleración e Innovación</a>
</div>
</body></html>""",
        "titles": ("Programa de Aceleración e Innovación",),
    },
    "urosario-fondos-concursables": {
        "url": "https://urosario.edu.co/investigacion/formas-de-incentivos-y-convocatorias",
        "country": "Colombia",
        "entity": "Universidad del Rosario",
        "html": """<html><body><main>
<div class="card-hover-button">
  <h5 class="card-hover-button__content-title">FONDOS CONCURSABLES UR</h5>
  <a href="/investigacion/servicios-y-oportunidades/fondos-concursables-ur">VER MÁS</a>
</div>
<div class="card-hover-button">
  <h5 class="card-hover-button__content-title">CONVOCATORIAS Y FONDOS EXTERNOS</h5>
  <a href="/investigacion/Servicios-al-investigador">Ver más</a>
</div>
</main></body></html>""",
        "titles": (
            "FONDOS CONCURSABLES UR",
            "CONVOCATORIAS Y FONDOS EXTERNOS",
        ),
    },
    "hhmi-programs": {
        "url": "https://www.hhmi.org/programs",
        "country": "United States",
        "entity": "HHMI",
        "html": """<html><body>
<a href="/programs/freeman-hrabowski-scholars">Freeman Hrabowski Scholars</a>
<a href="/programs/gilliam-fellows">Gilliam Fellows</a>
</body></html>""",
        "titles": ("Freeman Hrabowski Scholars", "Gilliam Fellows"),
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
    candidates = await connector.parse(await connector.fetch())
    assert len(candidates) >= 1
    titles = {c.title for c in candidates}
    assert any(expected in titles for expected in meta["titles"])
