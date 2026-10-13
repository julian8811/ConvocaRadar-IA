"""041 agro/biodiversity expansion: five ConfigurableHtml seeds. AST only.

Tanda reducida 8->5 con justificacion (issue #62, X1): de 15 candidatos,
solo 5 portales publican convocatorias externas accionables verificadas;
el resto cae en dedup (NIH->grants-gov, LIFE/F&T, Innovate UK->UKRI,
SENNOVA->sena-convocatorias parcial) o no-financiacion (IICA/AGROSAVIA/
CGIAR/EMBRAPA/CABI/FAO-tenders/SENNOVA-timeout).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "fontagro-convocatorias",
    "fundacion-biodiversidad-convocatorias",
    "eu-life-calls-cinea",
    "biodiversa-calls",
    "fondo-accion-convocatorias",
)

BATCH_URLS = {
    "fontagro-convocatorias": "https://fontagro.org/es/iniciativas/convocatorias",
    "fundacion-biodiversidad-convocatorias": "https://fundacion-biodiversidad.es/buscador-de-convocatorias/",
    "eu-life-calls-cinea": "https://cinea.ec.europa.eu/life-calls-proposals-2026_en",
    "biodiversa-calls": "https://www.biodiversa.eu/research-funding/upcoming-calls",
    "fondo-accion-convocatorias": "https://fondoaccion.org/convocatorias/",
}

BATCH_ALLOWED_FAMILIES = {
    "fontagro-convocatorias": "fontagro.org",
    "fundacion-biodiversidad-convocatorias": "fundacion-biodiversidad.es",
    "eu-life-calls-cinea": "cinea.ec.europa.eu",
    "biodiversa-calls": "biodiversa.eu",
    "fondo-accion-convocatorias": "fondoaccion.org",
}

ALL_FAMILIES = set(BATCH_ALLOWED_FAMILIES.values())


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


def test_041_keys_enabled_and_configurable():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} not enabled"
        if "connector_type" in definition:
            assert definition["connector_type"] == "configurable_html"
        assert definition["source_type"] == "html"
        assert definition["scraping_frequency"] == "weekly"
        assert definition["base_url"] == BATCH_URLS[key]
        cfg = definition.get("connector_config")
        assert cfg is not None, f"{key} missing connector_config"
        assert "list_selectors" in cfg and cfg["list_selectors"]
        assert "title_selectors" in cfg and cfg["title_selectors"]
        assert "link_selectors" in cfg and cfg["link_selectors"]
        assert "content_selectors" in cfg
        assert "date_labels" in cfg
        assert "detail_enrichment" in cfg
        assert cfg["detail_enrichment"] is False
        HtmlConnectorConfig.from_dict(cfg)


def test_041_catalog_count_and_uniqueness():
    defs = _seed_definitions_by_key()
    # 203 (040/F3) + 5 (041) = 208
    assert len(defs) == 208, f"expected 208 keys, got {len(defs)}"
    from collections import Counter

    seed_path = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.py"
    text = seed_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    keys: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "seed_default_sources":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name) and t.id == "source_definitions":
                            for item in ast.literal_eval(stmt.value):
                                keys.append(item["key"])
    dupes = [k for k, c in Counter(keys).items() if c > 1]
    assert dupes == [], f"duplicate keys {dupes}"
    for k in BATCH_KEYS:
        assert k in keys


def test_041_allowed_domains_families():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert BATCH_ALLOWED_FAMILIES[key] in defs[key]["allowed_domains"], (
            f"{key} missing {BATCH_ALLOWED_FAMILIES[key]}"
        )
    all_domains = set()
    for key in BATCH_KEYS:
        all_domains.update(defs[key]["allowed_domains"])
    for fam in ALL_FAMILIES:
        assert fam in all_domains, f"family {fam} not in any allowed_domains"
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"


def test_041_tier_experimental():
    import uuid

    from sqlalchemy import select

    from app.db.seed import seed_default_sources
    from app.db.session import SessionLocal, create_all
    from app.models import Organization, Source

    create_all()
    db = SessionLocal()
    try:
        slug = f"pr041-tier-{uuid.uuid4().hex[:6]}"
        org = Organization(slug=slug, name="Tier Check 041", type="university", country="Colombia")
        db.add(org)
        db.commit()
        db.refresh(org)
        seed_default_sources(db, org)
        db.commit()
        for key in BATCH_KEYS:
            src = db.scalar(select(Source).where(Source.key == key))
            assert src is not None, f"source {key} not in DB after seed"
            assert src.tier == "experimental", f"{key} tier {src.tier} != experimental"
        db.execute(Source.__table__.delete().where(Source.key.in_(list(BATCH_KEYS))))
        db.delete(org)
        db.commit()
    finally:
        db.close()


def test_041_no_semantic_duplicates():
    """Dedup cases from issue #62 must hold: no NIH key, no Innovate UK key,
    no SENNOVA key, LIFE key distinct from eu-funding-portal aggregator."""
    defs = _seed_definitions_by_key()
    for forbidden in ("nih-funding", "nih-grants", "innovate-uk", "innovate-uk-competitions", "sena-sennova"):
        assert forbidden not in defs, f"semantic duplicate {forbidden} must not exist"
    life = defs["eu-life-calls-cinea"]
    agg = defs["eu-funding-portal-international"]
    assert life["base_url"] != agg["base_url"]
    assert not (set(life["allowed_domains"]) & set(agg["allowed_domains"])), "LIFE must not share domains with aggregator"
