"""034 LatAm sources batch: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "secihti-mexico-ciencias",
    "secihti-mexico-becas-extranjero",
    "segib-noticias",
    "oas-scholarships",
    "fundacion-carolina-becas",
    "clacso-concursos",
    "agencia-id-argentina",
    "senacyt-panama",
)

BATCH_URLS = {
    "secihti-mexico-ciencias": (
        "https://secihti.mx/convocatoria_categoria/ciencias-y-humanidades/"
    ),
    "secihti-mexico-becas-extranjero": (
        "https://secihti.mx/convocatoria_categoria/becas-al-extranjero/"
    ),
    "segib-noticias": "https://www.segib.org/",
    "oas-scholarships": "https://www.oas.org/en/scholarships/",
    "fundacion-carolina-becas": "https://fundacioncarolina.es/",
    "clacso-concursos": "https://www.clacso.org/becas/concursos/",
    "agencia-id-argentina": "https://www.argentina.gob.ar/ciencia/agencia",
    "senacyt-panama": "https://www.senacyt.gob.pa/convocatoriassenacyt/",
}

BATCH_COUNTRIES = {
    "secihti-mexico-ciencias": "Mexico",
    "secihti-mexico-becas-extranjero": "Mexico",
    "segib-noticias": "International",
    "oas-scholarships": "International",
    "fundacion-carolina-becas": "Spain",
    "clacso-concursos": "International",
    "agencia-id-argentina": "Argentina",
    "senacyt-panama": "Panama",
}

# Acuerdo sólo-convocatorias 2026-10-15: segib-noticias trae eventos/foros
# (33 filas en prod, cero llamadas) y cnpq-brasil apunta a un noticiero con
# solo basura de navegación (3 filas). Ninguna de las dos se elimina del
# catálogo para no perder trazabilidad; quedan deshabilitadas.
EXPECTED_DISABLED_BY_POLICY = ("segib-noticias", "cnpq-brasil")


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


def test_034_keys_enabled_latam():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        expected = key not in EXPECTED_DISABLED_BY_POLICY
        assert definition.get("enabled", True) is expected, f"{key} enabled={not expected}"
        assert definition["country"] == BATCH_COUNTRIES[key]
        assert definition["region"] == "LatAm"
        assert definition["base_url"] == BATCH_URLS[key]
        HtmlConnectorConfig.from_dict(definition["connector_config"])


def test_noticias_disabled_newsroom_policy():
    defs = _seed_definitions_by_key()
    assert defs["segib-noticias"].get("enabled", True) is False
    assert defs["cnpq-brasil"].get("enabled", True) is False


def test_catalog_fully_enabled():
    defs = _seed_definitions_by_key()
    # Deshabilitadas por dictamen: 5 de la tanda 041 (gate X3, issue #62) +
    # idt-noticias (E13) + segib-noticias y cnpq-brasil (auditoría noticieros 2026-10-15; ver test_038/test_034).
    assert {k for k, d in defs.items() if d.get("enabled", True) is False} == {
        "idt-noticias",
        "fontagro-convocatorias",
        "fundacion-biodiversidad-convocatorias",
        "eu-life-calls-cinea",
        "biodiversa-calls",
        "fondo-accion-convocatorias",
        "segib-noticias",
        "cnpq-brasil",
        "grants-gov-rss",
    }
    assert len(defs) >= 152


def test_factory_configurable_html_for_034():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
