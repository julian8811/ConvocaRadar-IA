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
        assert definition.get("enabled", True) is True
        assert definition["country"] == BATCH_COUNTRIES[key]
        assert definition["region"] == "LatAm"
        assert definition["base_url"] == BATCH_URLS[key]
        HtmlConnectorConfig.from_dict(definition["connector_config"])


def test_catalog_fully_enabled():
    defs = _seed_definitions_by_key()
    assert [k for k, d in defs.items() if d.get("enabled", True) is False] == []
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
