"""042 X4 batch sources (issue #62): EU LIFE (CINEA) + Fundacion Biodiversidad.

Offline total: parse contra HTML versionado en
`docs/expansion-catalogo-041/piloto-041/fixture-*.html` (etapa 0: fechas
sinteticas eliminadas; cierres no documentados declarados `unknown`, SIN
fetch real — ver `piloto-041/README.md`). Cero red, cero escrituras DB
(pines por AST sobre `seed.py`, solo lectura).

Reglas del gate (etapa 0):
- Sin fechas inventadas: ningun fixture/doc/test presenta un cierre no
  documentado como real; lo desconocido es `close_date None` + marca
  explicita `unknown` (nunca `open` por defecto).
- Dedup por oportunidad: (titulo normalizado, organismo, fecha), no solo
  dominio/URL; intra-pagina y contra snapshot offline del catalogo.
"""

from __future__ import annotations

import ast
import json
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


def test_042_life_parse_marks_unknown_close_not_open() -> None:
    """Fixture LIFE etapa 0: la card Circular vencida (2026-09-22 real
    documentada) se filtra; la card Nature declara cierre `unknown` (el
    piloto la marco unknown y la etapa 0 elimino la fecha sintetica):
    se emite con close_date None + marca unknown, NUNCA como abierta."""
    connector = EuLifeCineaConnector()
    candidates = connector.parse_html(LIFE_HTML, EuLifeCineaConnector.BASE_URL)
    assert len(candidates) == 1, [c.title for c in candidates]
    cand = candidates[0]
    assert "nature and biodiversity" in cand.title.lower()
    assert cand.official_url.endswith("/sap-nature-biodiversity")
    assert cand.close_date is None
    assert "close-date-unknown" in (cand.topics or [])
    assert "unknown" in cand.summary.lower()


def test_042_fb_parse_marks_unknown_close_not_open() -> None:
    """Fixture FB etapa 0: ambas cards relevantes declaran cierre `unknown`
    (matriz: `2026 (ver BOE/bases)`; fechas sinteticas eliminadas). Empleo
    y noticia siguen filtradas."""
    connector = FundacionBiodiversidadConnector()
    candidates = connector.parse_html(FB_HTML, FundacionBiodiversidadConnector.BASE_URL)
    assert len(candidates) == 2, [c.title for c in candidates]
    for cand in candidates:
        assert cand.close_date is None
        assert "close-date-unknown" in (cand.topics or [])
        assert "unknown" in cand.summary.lower()


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


@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
def test_042_unknown_close_never_published_as_open(connector_cls) -> None:
    """Sin evidencia de vigencia: el parse emite UN candidato marcado
    unknown/sin-fecha (no se inventa `open`), y `validate` lo rechaza para
    que el runner jamas lo publique como abierto. La razon NO debe contener
    'closed'/'cerrad' (el runner hace soft-pass de esos a publicado)."""
    connector = connector_cls()
    html = (
        "<html><body><main><article><h2>"
        f"<a href='{connector.BASE_URL}/convocatoria-ejemplo-sin-fecha'>Convocatoria ejemplo call for proposals</a>"
        "</h2><p>Texto sin fecha de cierre. Ver bases en la pagina oficial.</p></article></main></body></html>"
    )
    candidates = connector.parse_html(html, connector.BASE_URL)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.close_date is None
    assert "close-date-unknown" in (cand.topics or [])
    assert "unknown" in cand.summary.lower()
    assert "abierta" not in cand.summary.lower() and "open" not in cand.summary.lower().replace("unknown", "")


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
async def test_042_validate_rejects_unknown_close(connector_cls) -> None:
    from app.connectors.base import OpportunityCandidate

    connector = connector_cls()
    cand = OpportunityCandidate(
        title="Convocatoria ejemplo call for proposals",
        entity="X",
        country="Y",
        official_url=f"{connector.BASE_URL}/convocatoria-ejemplo-sin-fecha",
        close_date=None,
    )
    result = await connector.validate(cand)
    assert result.ok is False
    assert "unknown" in result.reason.lower()
    # Pin anti-soft-pass: el runner publica los rechazos cuya razon menciona
    # cierre ("closed"/"cerrad"); un cierre desconocido no debe colarse ahi.
    assert "closed" not in result.reason.lower()
    assert "cerrad" not in result.reason.lower()


@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
def test_042_opp_key_unit(connector_cls) -> None:
    """La llave de oportunidad distingue (titulo, organismo, fecha):
    normaliza mayusculas/espacios y agrupa lo sin-fecha en 'unknown'."""
    assert connector_cls.opp_key("  LIFE 2026 — Nature! ", "CINEA / EC", None) == connector_cls.opp_key(
        "life 2026 nature", "cinea / ec", None
    )
    dated = connector_cls.opp_key("T", "E", datetime(2027, 1, 20))
    assert dated != connector_cls.opp_key("T", "E", None)
    assert dated != connector_cls.opp_key("T", "E", datetime(2027, 1, 21))
    assert dated != connector_cls.opp_key("T", "Otra Entidad", datetime(2027, 1, 20))
    assert connector_cls.opp_key("T", "E", None)[2] == "unknown"


@pytest.mark.parametrize("connector_cls", [EuLifeCineaConnector, FundacionBiodiversidadConnector])
def test_042_opp_dedup_intra_page_per_opportunity(connector_cls) -> None:
    """Dedup por oportunidad, no solo por URL: misma card republicada bajo
    dos paths distintos (sin fecha) colapsa a 1 candidato."""
    connector = connector_cls()
    html = (
        "<html><body><main>"
        "<article><h2>"
        f"<a href='{connector.BASE_URL}/convocatoria-ejemplo'>Convocatoria ejemplo call for proposals</a>"
        "</h2><p>Ver bases en la pagina oficial.</p></article>"
        "<article><h2>"
        f"<a href='{connector.BASE_URL}/convocatoria-ejemplo-duplicada'>Convocatoria ejemplo call for proposals</a>"
        "</h2><p>Ver bases en la pagina oficial.</p></article>"
        "</main></body></html>"
    )
    candidates = connector.parse_html(html, connector.BASE_URL)
    assert len(candidates) == 1, [(c.title, c.official_url) for c in candidates]


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


def _opp_keys(connector, html: str) -> set[tuple[str, str, str]]:
    """Llaves de oportunidad (titulo, organismo, fecha) vía el helper del
    propio conector — la misma funcion que usa el parse para dedup."""
    return {
        connector.opp_key(c.title, c.entity, c.close_date)
        for c in connector.parse_html(html, connector.BASE_URL)
    }


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

    # Títulos de los fixtures: sin solapamiento entre fuentes — ahora a
    # nivel oportunidad (titulo + organismo + fecha), no solo texto.
    life_keys = _opp_keys(EuLifeCineaConnector(), LIFE_HTML)
    fb_keys = _opp_keys(FundacionBiodiversidadConnector(), FB_HTML)
    assert life_keys and fb_keys
    assert life_keys.isdisjoint(fb_keys)
    life_titles = {key[0] for key in life_keys}
    fb_titles = {key[0] for key in fb_keys}
    assert life_titles.isdisjoint(fb_titles)

    # Snapshot offline del catalogo (matriz X1, solo lectura): ningun
    # ejemplo documentado de otra fuente colisiona con las oportunidades
    # parseadas. Limite documentado: la matriz trae titulos, no llaves
    # completas, asi que se compara la parte titulo de la llave.
    matriz = json.loads((REPO_ROOT / "docs" / "expansion-catalogo-041" / "matriz-041-candidatos.json").read_text(encoding="utf-8"))
    catalog_titles = {
        EuLifeCineaConnector.title_key(fila["ejemplo_titulo"])
        for fila in matriz["filas"]
        if fila.get("ejemplo_titulo") not in (None, "", "n/a")
    }
    assert catalog_titles, "el snapshot offline no debe estar vacio"
    parsed_titles = life_titles | fb_titles
    assert not (parsed_titles & catalog_titles), (
        "colision de oportunidad contra el snapshot del catalogo: "
        f"{parsed_titles & catalog_titles}"
    )

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
