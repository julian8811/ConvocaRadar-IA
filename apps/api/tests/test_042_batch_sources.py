"""042 X4 batch sources (issue #62): EU LIFE (CINEA) + Fundacion Biodiversidad.

Offline total: parse contra HTML versionado en
`docs/expansion-catalogo-041/piloto-041/fixture-*.html` (reconstruidos desde lo
documentado, SIN fetch real — ver `piloto-041/README.md`). Cero red, cero
escrituras DB (pines por AST sobre `seed.py`, solo lectura).
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.connectors.eu_life_cinea import EuLifeCineaConnector
from app.connectors.fundacion_biodiversidad import FundacionBiodiversidadConnector

LIFE_KEY = "eu-life-calls-cinea"
FB_KEY = "fundacion-biodiversidad-convocatorias"

REPO_ROOT = Path(__file__).resolve().parents[3]
PILOTO_DIR = REPO_ROOT / "docs" / "expansion-catalogo-041" / "piloto-041"
LIFE_HTML = (PILOTO_DIR / "fixture-eu-life-calls-cinea.html").read_text(encoding="utf-8")
FB_HTML = (PILOTO_DIR / "fixture-fundacion-biodiversidad.html").read_text(encoding="utf-8")


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
                    return {item["key"]: item for item in ast.literal_eval(stmt.value)}
    raise AssertionError("source_definitions not found")


def test_042_life_parse_real_html_yields_only_open_call() -> None:
    """Fixture LIFE: 1 abierta (Nature, 2027-01-20); SAP Circular vencida,
    vacante y noticia filtradas."""
    connector = EuLifeCineaConnector()
    candidates = connector.parse_html(LIFE_HTML, EuLifeCineaConnector.BASE_URL)
    assert len(candidates) == 1, [c.title for c in candidates]
    cand = candidates[0]
    assert "nature and biodiversity" in cand.title.lower()
    assert cand.official_url.endswith("/sap-nature-biodiversity")
    assert cand.close_date is not None and cand.close_date.date() >= datetime.now(UTC).date()
    assert cand.close_date.date().isoformat() == "2027-01-20"


def test_042_fb_parse_real_html_yields_only_open_call() -> None:
    """Fixture FB: 1 abierta (Educacion Ambiental, 2026-12-15); ciudades
    vencida, empleo y noticia filtradas."""
    connector = FundacionBiodiversidadConnector()
    candidates = connector.parse_html(FB_HTML, FundacionBiodiversidadConnector.BASE_URL)
    assert len(candidates) == 1, [c.title for c in candidates]
    cand = candidates[0]
    assert "educacion ambiental" in cand.title.lower()
    assert "desinformacion-climatica" in cand.official_url
    assert cand.close_date is not None and cand.close_date.date() >= datetime.now(UTC).date()
    assert cand.close_date.date().isoformat() == "2026-12-15"


@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
def test_042_expired_close_date_discarded(connector_cls) -> None:
    """close_date pasado → descartada en parse y rechazada en validate."""
    connector = connector_cls()
    html = (
        "<html><body><main><article><h2>"
        f"<a href='{connector.BASE_URL}/convocatoria-ejemplo-2024'>Convocatoria ejemplo 2024 call for proposals</a>"
        "</h2><p>Deadline: 15 March 2024. Closed call.</p></article></main></body></html>"
    )
    assert connector.parse_html(html, connector.BASE_URL) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
async def test_042_validate_rejects_expired(connector_cls) -> None:
    from app.connectors.base import OpportunityCandidate

    connector = connector_cls()
    expired = OpportunityCandidate(
        title="Convocatoria ejemplo call for proposals",
        entity="X",
        country="Y",
        official_url=f"{connector.BASE_URL}/convocatoria-ejemplo",
        close_date=datetime(2024, 3, 15),
    )
    result = await connector.validate(expired)
    assert result.ok is False


@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
@pytest.mark.parametrize(
    "noise_title",
    [
        "Oferta de empleo: tecnico de proyectos",
        "CINEA is hiring: Project Officer (job vacancy)",
        "Noticia: memoria anual 2025",
        "News: LIFE Awards winners announced",
    ],
)
def test_042_pertinencia_rejects_employment_and_news(connector_cls, noise_title: str) -> None:
    """Anti empleo/noticias: el ruido documentado en X3 nunca es candidato."""
    connector = connector_cls()
    html = (
        "<html><body><main><article><h2>"
        f"<a href='{connector.BASE_URL}/ruido-ejemplo'>{noise_title}</a>"
        "</h2><p>Texto de relleno sin fecha.</p></article></main></body></html>"
    )
    assert connector.parse_html(html, connector.BASE_URL) == []


@pytest.mark.asyncio
async def test_042_validate_open_candidate_ok() -> None:
    from app.connectors.base import OpportunityCandidate

    connector = EuLifeCineaConnector()
    cand = OpportunityCandidate(
        title="LIFE 2026 Nature and Biodiversity call for proposals",
        entity="CINEA",
        country="European Union",
        official_url=f"{connector.BASE_URL}/sap-nature-biodiversity",
        close_date=datetime(2027, 1, 20),
    )
    assert (await connector.validate(cand)).ok is True
    missing = OpportunityCandidate(title="", entity="X", country="Y", official_url="")
    assert (await connector.validate(missing)).ok is False


def test_042_semantic_dedup_against_catalog_203() -> None:
    """Dedup semántica contra el catálogo: dominios/URLs/títulos disjuntos;
    pin LIFE vs agregador eu-funding-portal (X1/X3)."""
    defs = _seed_definitions_by_key()
    life = defs[LIFE_KEY]
    fb = defs[FB_KEY]
    agg = defs["eu-funding-portal-international"]

    # Dominios allowlist disjuntos entre LIFE y el agregador (pin X4).
    assert not (set(life["allowed_domains"]) & set(agg["allowed_domains"]))
    assert "cinea.ec.europa.eu" in life["allowed_domains"]
    # base_url exactas distintas.
    assert life["base_url"] != agg["base_url"]
    assert life["base_url"] != fb["base_url"]
    # Hosts disjuntos entre las dos prioritarias.
    assert urlparse(life["base_url"]).netloc != urlparse(fb["base_url"]).netloc

    # Títulos de los fixtures: sin solapamiento entre fuentes.
    life_titles = {c.title.lower() for c in EuLifeCineaConnector().parse_html(LIFE_HTML, EuLifeCineaConnector.BASE_URL)}
    fb_titles = {c.title.lower() for c in FundacionBiodiversidadConnector().parse_html(FB_HTML, FundacionBiodiversidadConnector.BASE_URL)}
    assert life_titles and fb_titles
    assert life_titles.isdisjoint(fb_titles)

    # Helpers de dedup: misma URL con/sin barra y mayúsculas normaliza igual.
    assert EuLifeCineaConnector.normalize_url("https://CINEA.ec.europa.eu/a/b/") == EuLifeCineaConnector.normalize_url(
        "https://cinea.ec.europa.eu/a/b"
    )
    assert EuLifeCineaConnector.title_key("  LIFE 2026 — Nature! ") == EuLifeCineaConnector.title_key("life 2026 nature")


def test_042_pins_no_activation_enabled_false_intact() -> None:
    """Pines de no-activación X4 (AST, sin DB): ambas keys con `enabled False`
    literal; los módulos dedicados NO se auto-registran (pin X3 intacto)."""
    defs = _seed_definitions_by_key()
    for key in (LIFE_KEY, FB_KEY):
        assert key in defs, f"missing {key}"
        assert defs[key].get("enabled") is False, f"GATE: {key} debe seguir deshabilitado"

    for module_path in (
        Path(__file__).resolve().parents[1] / "app" / "connectors" / "eu_life_cinea.py",
        Path(__file__).resolve().parents[1] / "app" / "connectors" / "fundacion_biodiversidad.py",
    ):
        text = module_path.read_text(encoding="utf-8")
        assert re.search(r"^@register", text, re.M) is None, (
            f"{module_path.name} no debe auto-registrarse (X3 intacto)"
        )
        assert "from app.connectors.registry import" not in text, (
            f"{module_path.name} no debe importar el registry"
        )
        assert "from app.connectors.factory import" not in text, (
            f"{module_path.name} no debe tocar factory"
        )


def test_042_no_db_writes_in_this_module() -> None:
    """Cero escrituras DB en X4: este módulo no invoca ORM/seed en runtime
    (la referencia por nombre en el helper AST es solo lectura)."""
    text = Path(__file__).read_text(encoding="utf-8")
    # Tokens construidos por concatenacion: el fuente nunca contiene la forma
    # de llamada contigua, asi el pin no se dispara a si mismo.
    for forbidden_call in (
        "SessionLocal" + "(",
        "seed_default_sources" + "(",
        "create_all" + "(",
        "db.add" + "(",
        "db.commit" + "(",
    ):
        assert forbidden_call not in text, f"{forbidden_call} prohibido en test_042"
