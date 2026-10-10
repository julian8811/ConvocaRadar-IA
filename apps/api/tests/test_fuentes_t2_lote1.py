"""T2 fuentes-todas-on lote 1: FAPERJ selectores + Findeter challenge detection.

RED-first regression tests built from real DOM captured 2026-10-10
(respectful single GET per page, repo User-Agent):

- FAPERJ (https://www.faperj.br/?id=28.5.7): the edital list lives in
  ``<div class="data">`` with ``<a href="...Edital...">`` links. There is
  NO ``<main>`` and NO ``<article>`` on the page, so the seed
  ``list_selectors`` (all ``article``/``main``-scoped) match nothing → 0 items.
- Findeter (https://www.findeter.gov.co/convocatorias): healthy listing pages
  embed a PerfDrive *analytics* snippet (``validate.perfdrive.com, ssc`` in
  ``ssConf``). The connector treated any ``"perfdrive"`` substring as a bot
  challenge, mislabelling healthy pages and hiding the real diagnosis.

No live HTTP in these tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.connectors.base import RawSourceResult
from app.connectors.configurable_html import ConfigurableHtmlConnector

# ── Seed helpers (same AST pattern as test_026_batch1_seeds.py) ──────────────


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
        definition["connector_config"],
        entity_name=entity,
        default_country=country,
    )


# ── FAPERJ fixtures (structure observed 2026-10-10) ──────────────────────────

_FAPERJ_HTML = """<html><head><title>FAPERJ</title></head><body>
<section class="container-interna"><section class="container"><section class="row">
<section class="col-lg-12"><section class="corpo-interna">
<div class="data">Atualizado em: 09/10/2026</div>
<div class="tamanho-fonte"><p><strong>
<a href="rp/downloads/Edital_FAPERJ_N01_2026_Apoio.pdf">Edital FAPERJ N 01/2026 - Apoio a Recuperacao e Modernizacao</a>
</strong></p><p><strong>
<a href="rp/downloads/Edital_FAPERJ_N02_2026_Inovacao.pdf">Edital FAPERJ N 02/2026 - Programa de Apoio a Projetos de Inovacao</a>
</strong></p><p>
<a href="rp/downloads/Resultado_Final_Edital_FAPERJ_N01_2026.pdf">confira a listagem dos projetos aprovados</a>
</p></div>
</section></section></section></section></section>
</body></html>"""


def test_faperj_seed_list_selectors_cover_data_div():
    """Seed list_selectors must match the observed edital container.

    RED: current seed only has article/main-scoped selectors, but the page
    has no <main> and no <article> — the editais live under
    section.corpo-interna > div.tamanho-fonte.
    """
    config = _seed_definitions_by_key()["faperj-brasil"]["connector_config"]
    joined = " ".join(config["list_selectors"])
    assert ("corpo-interna" in joined or "tamanho-fonte" in joined) and "Edital" in joined, (
        "faperj-brasil list_selectors must cover corpo-interna/tamanho-fonte Edital links "
        f"(have: {config['list_selectors']})"
    )


@pytest.mark.asyncio
async def test_faperj_parse_extracts_editais_from_captured_structure():
    """Seed-configured connector must extract editais from real DOM shape.

    RED: parses 0 candidates with the current seed selectors.
    GREEN: >= 2 edital candidates with official faperj.br PDF urls.
    """
    connector = _seed_connector("faperj-brasil", "FAPERJ", "Brazil")
    raw = RawSourceResult(
        source_key="faperj-brasil",
        url="https://www.faperj.br/?id=28.5.7",
        content=_FAPERJ_HTML,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    titles = [c.title for c in candidates]
    assert len(candidates) >= 2, f"expected >=2 editais, got {titles}"
    assert any("01/2026" in t for t in titles)
    assert any("02/2026" in t for t in titles)
    for c in candidates:
        assert "faperj.br" in c.official_url


# ── Findeter fixtures ────────────────────────────────────────────────────────

_FINDETER_HEALTHY_HTML = """<html><head>
<script>ssConf("c1", "https://www.findeter.gov.co"); ssConf("cu", "validate.perfdrive.com, ssc");</script>
<title>FINDETER : Convocatorias | Findeter</title></head>
<body class="path-convocatorias">
<a href="/convocatorias/paf-atmindeporte-o-052-2026">PAF-ATMINDEPORTE-O-052-2026</a>
<a href="/convocatorias/paf-viassantander-o-032-2026">PAF-VIASSANTANDER-O-032-2026</a>
</body></html>"""

_FINDETER_CHALLENGE_HTML = """<html><head><title>Validating...</title></head><body>
<p>checking if the site connection is secure</p>
<form action="/validate" method="post"><input type="hidden" name="token" value="x"/></form>
</body></html>"""


def test_findeter_healthy_page_with_perfdrive_snippet_is_not_a_challenge():
    """Healthy listings embed a PerfDrive analytics snippet — not a challenge.

    RED: _is_challenge_page does not exist yet (ImportError); the old inline
    ``"perfdrive" in content`` check misfires on this exact page.
    """
    from app.connectors.findeter import _is_challenge_page

    assert _is_challenge_page(_FINDETER_HEALTHY_HTML) is False


def test_findeter_real_challenge_page_is_detected():
    from app.connectors.findeter import _is_challenge_page

    assert _is_challenge_page(_FINDETER_CHALLENGE_HTML) is True


@pytest.mark.asyncio
async def test_findeter_parse_healthy_page_yields_convocatorias():
    """Regression guard: healthy page keeps yielding candidates after the fix."""
    from app.connectors.findeter import FindeterConnector

    connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
    raw = RawSourceResult(
        source_key="findeter-convocatorias",
        url="https://www.findeter.gov.co/convocatorias",
        content=_FINDETER_HEALTHY_HTML,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    assert len(candidates) == 2
    assert candidates[0].title == "PAF-ATMINDEPORTE-O-052-2026"


@pytest.mark.asyncio
async def test_findeter_parse_challenge_page_yields_empty():
    """Regression guard: a real challenge page yields 0 (silent-zero, not crash)."""
    from app.connectors.findeter import FindeterConnector

    connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
    raw = RawSourceResult(
        source_key="findeter-convocatorias",
        url="https://www.findeter.gov.co/convocatorias",
        content=_FINDETER_CHALLENGE_HTML,
        content_type="text/html",
    )
    assert await connector.parse(raw) == []
