"""T3 fuentes-todas-on lote 2: fixes jsps-fellowships, jsps-kakenhi,
rockefeller-foundation, proinnovate-calendario y urosario-fondos-concursables.

RED-first regression tests built from real DOM captured 2026-10-10
(respectful sequential GETs, repo User-Agent, no live HTTP in tests):

- JSPS (e-fellow/ + e-grants/): no <article>, no <main>. Program links live
  in content units ``div.copy-0002 > div.ww-text``. Seed list_selectors are
  all article/main-scoped -> 0 items (silent-zero, same class as T2 FAPERJ).
- Rockefeller (/grants/ -> /our-grants/): seed has NO connector_config, so
  GenericHtml extracts nav junk ("Our Grants | RF", home) -> quarantined as
  ruido. Real programs: residency-program, big-bets-fellowships, /convenings/.
- ProInnovate (calendario.proinnovate.gob.pe/): 302 to
  calendario-de-concursos-2026.pdf; source_type html parses PDF bytes -> 0.
  PdfConnector yields 9 candidates from the live PDF.
- URosario: base redirects to a landing whose <article> yields 0; the 2026
  calls live in the fondos-concursables subpage as tab blocks
  ``div[id*='tab-convocatoria']`` (title heading + doc links).

No live HTTP in these tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.connectors.base import RawSourceResult
from app.connectors.configurable_html import ConfigurableHtmlConnector


def _seed_definitions_by_key() -> dict[str, dict]:
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
                    items = list(ast.literal_eval(stmt.value))
                    return {item["key"]: item for item in items}
    raise AssertionError("source_definitions not found in seed_default_sources")


def _seed_connector(key: str, entity: str, country: str) -> ConfigurableHtmlConnector:
    definition = _seed_definitions_by_key()[key]
    return ConfigurableHtmlConnector(
        key,
        definition["base_url"],
        dict(definition["connector_config"]),
        entity_name=entity,
        default_country=country,
    )


# ── JSPS fellowships fixture (content units observed 2026-10-10) ────────────

_JSPS_FELLOW_HTML = """<html><head><title>Postdoctoral Fellowships for Research in Japan</title></head><body>
<div id="container" class="container"><div id="content" class="content">
<div class="unit-wrapper bg-color-0"><div class="unit-base"><div class="copy-0002">
<div class="ww-text copy-0002__column"><p><strong><u>
<a href="https://www.jsps.go.jp/english/e-fellow/e-ippan/index.html">Standard Program</a>
</u></strong></p><p><strong><u>
<a href="https://www.jsps.go.jp/english/e-fellow/e-oubei-s/index.html">Short-term Program (PE)</a>
</u></strong></p><p><strong><u>
<a href="https://www.jsps.go.jp/english/e-fellow/e-asean-africa-s/index.html">Short-term Program (PA)</a>
</u></strong></p><p><strong><u>
<a href="https://www.jsps.go.jp/english/e-fellow/e-summer/index.html">Summer Program</a>
</u></strong></p></div></div></div></div>
<nav class="localNav"><ul class="localNav-list first">
<li class="list-item"><a href="/english/e-fellow/index.html">Top</a></li>
<li class="list-item"><a href="/english/e-fellow/faq.html">FAQ</a></li>
</ul></nav>
</div></div></body></html>"""


def test_jsps_fellowships_seed_covers_content_programs():
    """Seed list_selectors must reach the ww-text program links.

    RED: all selectors are article/main-scoped but the page has neither.
    """
    config = _seed_definitions_by_key()["jsps-fellowships"]["connector_config"]
    joined = " ".join(config["list_selectors"])
    assert "ww-text" in joined and "/e-fellow/e-" in joined, (
        "jsps-fellowships list_selectors must cover div.ww-text program links "
        f"(have: {config['list_selectors']})"
    )


@pytest.mark.asyncio
async def test_jsps_fellowships_parse_extracts_programs():
    """Seed-configured connector extracts the 4 fellowship programs.

    RED: 0 candidates with the current seed selectors.
    GREEN: >= 3 program candidates (Standard/PE/PA/Summer).
    """
    connector = _seed_connector("jsps-fellowships", "JSPS", "Japan")
    raw = RawSourceResult(
        source_key="jsps-fellowships",
        url="https://www.jsps.go.jp/english/e-fellow/",
        content=_JSPS_FELLOW_HTML,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    titles = [c.title for c in candidates]
    assert len(candidates) >= 3, f"expected >=3 programs, got {titles}"
    assert any("Standard Program" in t for t in titles)
    assert any("Summer Program" in t for t in titles)
    for c in candidates:
        assert "jsps.go.jp" in c.official_url


# ── JSPS KAKENHI fixture ─────────────────────────────────────────────────────

_JSPS_KAKENHI_HTML = """<html><head><title>Grants-in-Aid for Scientific Research | KAKENHI | JSPS</title></head><body>
<div id="container" class="container"><div id="content" class="content">
<div class="unit-base"><div class="copy-0002"><div class="ww-text copy-0002__column"><p><u>
<a href="https://www.jsps.go.jp/english/e-grants/grants01.html">Types of Grants Programs</a>
</u></p><p><u>
<a href="https://www.jsps.go.jp/english/e-grants/lsrp/index.html">Abstracts of Large-scale Research Projects</a>
</u></p><p><u>
<a href="https://www.jsps.go.jp/english/e-grants/multi-year_fund/index.html">Introduction of Multi-year Fund</a>
</u></p><p><u>
<a href="https://www.jsps.go.jp/english/e-grants/howtoapply.html">How to apply</a>
</u></p><p><u>
<a href="https://www.jsps.go.jp/english/e-grants/inquiries.html">Inquiries</a>
</u></p></div></div></div>
</div></div></body></html>"""


def test_jsps_kakenhi_seed_covers_content_programs():
    """Seed list_selectors must reach the ww-text grant section links.

    RED: all selectors are article/main-scoped but the page has neither.
    """
    config = _seed_definitions_by_key()["jsps-kakenhi-grants"]["connector_config"]
    joined = " ".join(config["list_selectors"])
    assert "ww-text" in joined and "grants01" in joined, (
        "jsps-kakenhi-grants list_selectors must cover div.ww-text section links "
        f"(have: {config['list_selectors']})"
    )


@pytest.mark.asyncio
async def test_jsps_kakenhi_parse_extracts_sections_without_utility_junk():
    """Seed-configured connector extracts program sections, not utility pages.

    RED: 0 candidates with the current seed selectors.
    GREEN: Types/LSRP/Multi-year present; How to apply/Inquiries absent.
    """
    connector = _seed_connector("jsps-kakenhi-grants", "JSPS", "Japan")
    raw = RawSourceResult(
        source_key="jsps-kakenhi-grants",
        url="https://www.jsps.go.jp/english/e-grants/",
        content=_JSPS_KAKENHI_HTML,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    titles = [c.title for c in candidates]
    assert len(candidates) >= 3, f"expected >=3 sections, got {titles}"
    assert any("Types of Grants Programs" in t for t in titles)
    assert any("Multi-year Fund" in t for t in titles)
    assert not any("How to apply" in t for t in titles)
    assert not any("Inquiries" in t for t in titles)


# ── Rockefeller fixture (/our-grants/ program links observed 2026-10-10) ────

_ROCKEFELLER_HTML = """<html><head><title>Our Grants | RF</title></head><body>
<header><nav><a href="https://www.rockefellerfoundation.org/">The Rockefeller Foundation</a>
<a href="https://www.rockefellerfoundation.org/our-grants/">Our Grants</a></nav></header>
<main><section><div class="programs">
<a href="https://www.rockefellerfoundation.org/fellowships-convenings/bellagio-center/residency-program/">Residencies</a>
<a href="https://www.rockefellerfoundation.org/fellowships-convenings/big-bets-fellowships/">Big Bets Fellowships</a>
<a href="https://www.rockefellerfoundation.org/fellowships-convenings/convenings/">RF Convenings</a>
<a href="https://www.rockefellerfoundation.org/fellowships-convenings/bellagio-center/convenings/">Group Convenings</a>
<a href="https://www.rockefellerfoundation.org/fellowships-convenings/bellagio-news-and-stories/">Bellagio News and Stories</a>
<a href="https://www.rockefellerfoundation.org/grantee-impact-stories/">Grantee Impact Stories</a>
</div></section></main>
</body></html>"""


def test_rockefeller_seed_has_program_connector_config():
    """Rockefeller needs a dedicated connector_config (GenericHtml = ruido).

    RED: seed has no connector_config, so the factory falls back to
    GenericHtml, which extracts nav junk quarantined as noise.
    """
    definition = _seed_definitions_by_key()["rockefeller-foundation"]
    config = definition.get("connector_config")
    assert config, "rockefeller-foundation needs connector_config (program links)"
    joined = " ".join(config["list_selectors"])
    assert "residency-program" in joined and "big-bets-fellowships" in joined


@pytest.mark.asyncio
async def test_rockefeller_parse_extracts_programs_not_stories():
    """Program links extracted; stories/nav junk excluded per-source.

    GREEN: Residencies/Big Bets/Convenings present; Stories/home absent.
    The global `eventos`-style noise rule is untouched (per-source scoping).
    """
    connector = _seed_connector("rockefeller-foundation", "Rockefeller", "International")
    raw = RawSourceResult(
        source_key="rockefeller-foundation",
        url="https://www.rockefellerfoundation.org/grants/",
        content=_ROCKEFELLER_HTML,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    titles = [c.title for c in candidates]
    assert len(candidates) >= 3, f"expected >=3 programs, got {titles}"
    assert any("Residencies" in t for t in titles)
    assert any("Big Bets Fellowships" in t for t in titles)
    assert any("Convenings" in t for t in titles)
    assert not any("Stories" in t for t in titles)
    assert not any(t.strip() in {"Our Grants | RF", "The Rockefeller Foundation"} for t in titles)


# ── ProInnovate: PDF-backed calendar ─────────────────────────────────────────

def test_proinnovate_seed_uses_pdf_connector():
    """The calendar base URL 302s to calendario-de-concursos-2026.pdf.

    RED: source_type html makes the HTML parser chew PDF bytes -> 0 items.
    GREEN: source_type pdf routes to PdfConnector (9 candidates on live PDF).
    """
    definition = _seed_definitions_by_key()["proinnovate-calendario"]
    assert definition.get("source_type") == "pdf", (
        f"proinnovate-calendario must be source_type pdf (have: {definition.get('source_type')})"
    )
    assert "connector_config" not in definition, (
        "HTML connector_config is dead weight once source_type is pdf"
    )


def test_proinnovate_factory_resolves_pdf_connector():
    """Factory must return PdfConnector for the pdf source_type."""
    from app.connectors.factory import connector_for
    from app.connectors.pdf import PdfConnector

    definition = _seed_definitions_by_key()["proinnovate-calendario"]
    connector = connector_for(
        "proinnovate-calendario",
        definition["base_url"],
        source_type=definition.get("source_type"),
        connector_config=definition.get("connector_config"),
    )
    assert isinstance(connector, PdfConnector)


# ── URosario fondos concursables (tab blocks observed 2026-10-10) ───────────

_UROSARIO_HTML = """<html><head><title>Fondos Concursables UR</title></head><body>
<main class="main-content"><article><div><h1>Fondos Concursables UR</h1>
<div><h2>CONVOCATORIAS 2026</h2>
<div id="tab-convocatoria-conjunta-conectando-territorios">
<h3>CONVOCATORIA CONJUNTA Conectando Territorios: Caminos para el Desarrollo</h3>
<p>Objetivo: proyectos conjuntos de investigacion.</p>
<a href="/sites/default/files/2026-02/tdr-convproyectos-uj-ur-unab-final.pdf">Terminos de referencia</a>
</div>
<div id="tab-convocatoria-acelerador-de-la-investigacion">
<h3>CONVOCATORIA ACELERADOR DE LA INVESTIGACION HACIA LA FRONTERA</h3>
<p>Objetivo: investigacion de frontera.</p>
<a href="/sites/default/files/2026-02/tdr-acelerador.pdf">Terminos de referencia</a>
</div>
<div id="tab-convocatoria-ecosistema-semilleros">
<h3>CONVOCATORIA ECOSISTEMA SEMILLEROS: CONOCIMIENTO PARA EL FUTURO</h3>
<p>Objetivo: semilleros de investigacion.</p>
<a href="/sites/default/files/2026-03/tdr-semilleros.pdf">Terminos de referencia</a>
</div>
<div id="tab-convocatoria-one-lab-ur-conecta-2026">
<h3>CONVOCATORIA ONE LAB UR CONECTA 2026</h3>
<p>Objetivo: laboratorios conjuntos.</p>
<a href="/sites/default/files/2026-03/tdr-onelab.pdf">Terminos de referencia</a>
</div>
</div></div></article></main></body></html>"""

_UROSARIO_SUBPAGE = "https://urosario.edu.co/investigacion-y-extension/apoyo-e-infraestructura/fondos-concursables"


def test_urosario_seed_points_to_fondos_subpage_with_tab_selector():
    """Base must be the fondos-concursables listing; tab blocks must match.

    RED: base is the landing (redirects away) and selectors miss the tabs.
    """
    definition = _seed_definitions_by_key()["urosario-fondos-concursables"]
    assert definition["base_url"].rstrip("/").endswith("fondos-concursables"), (
        f"urosario base must be the fondos-concursables listing (have: {definition['base_url']})"
    )
    joined = " ".join(definition["connector_config"]["list_selectors"])
    assert "tab-convocatoria" in joined, (
        "urosario list_selectors must cover div[id*='tab-convocatoria'] blocks "
        f"(have: {definition['connector_config']['list_selectors']})"
    )


@pytest.mark.asyncio
async def test_urosario_parse_extracts_tab_calls():
    """Seed-configured connector extracts the tabbed 2026 calls.

    RED: 0 candidates (landing article yields nothing).
    GREEN: >= 3 calls with real convocatoria titles on urosario.edu.co urls.
    """
    connector = _seed_connector("urosario-fondos-concursables", "URosario", "Colombia")
    raw = RawSourceResult(
        source_key="urosario-fondos-concursables",
        url=_UROSARIO_SUBPAGE,
        content=_UROSARIO_HTML,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    titles = [c.title for c in candidates]
    assert len(candidates) >= 3, f"expected >=3 calls, got {titles}"
    assert any("Conectando Territorios" in t for t in titles)
    assert any("SEMILLEROS" in t for t in titles)
    for c in candidates:
        assert "urosario.edu.co" in c.official_url
