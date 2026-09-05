"""039 Next 8-source expansion: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "eu-creative-europe-calls",
    "eu-eacea-grants",
    "eu-culture-moves-europe",
    "sicon-bogota-estimulos",
    "ibermedia-convocatorias",
    "ibermusicas-convocatorias",
    "eurimages-council-europe",
    "erasmus-plus-opportunities",
)

BATCH_URLS = {
    "eu-creative-europe-calls": "https://culture.ec.europa.eu/calls",
    "eu-eacea-grants": "https://www.eacea.ec.europa.eu/grants_en",
    "eu-culture-moves-europe": (
        "https://culture.ec.europa.eu/creative-europe/creative-europe-culture-strand/culture-moves-europe"
    ),
    "sicon-bogota-estimulos": "https://sicon.scrd.gov.co/",
    "ibermedia-convocatorias": "https://www.programaibermedia.com/convocatorias/",
    "ibermusicas-convocatorias": "https://ibermusicas.org/",
    "eurimages-council-europe": "https://www.coe.int/en/web/eurimages",
    "erasmus-plus-opportunities": (
        "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-organisations"
    ),
}

BATCH_COUNTRIES = {
    "eu-creative-europe-calls": "European Union",
    "eu-eacea-grants": "European Union",
    "eu-culture-moves-europe": "European Union",
    "sicon-bogota-estimulos": "Colombia",
    "ibermedia-convocatorias": "International",
    "ibermusicas-convocatorias": "International",
    "eurimages-council-europe": "International",
    "erasmus-plus-opportunities": "European Union",
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


def test_039_keys_enabled_and_configurable():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} not enabled"
        assert definition["connector_type"] == "configurable_html" if "connector_type" in definition else definition["source_type"] == "html"
        assert definition["source_type"] == "html"
        assert definition["scraping_frequency"] == "weekly"
        assert definition["base_url"] == BATCH_URLS[key]
        assert definition["country"] == BATCH_COUNTRIES[key]
        # connector_config must have required selectors
        cfg = definition.get("connector_config")
        assert cfg is not None, f"{key} missing connector_config"
        assert "list_selectors" in cfg and cfg["list_selectors"]
        assert "title_selectors" in cfg and cfg["title_selectors"]
        assert "link_selectors" in cfg and cfg["link_selectors"]
        assert "content_selectors" in cfg
        assert "date_labels" in cfg
        assert "detail_enrichment" in cfg
        HtmlConnectorConfig.from_dict(cfg)


def test_039_catalog_count_and_uniqueness():
    defs = _seed_definitions_by_key()
    # 185 -> 193
    assert len(defs) == 193, f"expected 193 keys, got {len(defs)}"
    # uniqueness via keys already dict, also check no dup via Counter logic
    from collections import Counter

    seed_path = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.py"
    text = seed_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    keys = []
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


def test_039_sicon_allowed_domain():
    defs = _seed_definitions_by_key()
    sicon = defs["sicon-bogota-estimulos"]
    assert "sicon.scrd.gov.co" in sicon["allowed_domains"]
    # Also check factory
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"


def test_039_tier_experimental():
    defs = _seed_definitions_by_key()
    # _assign_tier returns experimental for these 8 (not in strategic/complementary)
    from app.db.seed import seed_default_sources

    # Verify via direct call of internal logic by inspecting file tiers sets
    seed_path = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.py"
    text = seed_path.read_text(encoding="utf-8")
    # Ensure none of the 039 keys are in strategic/complementary explicit sets
    for key in BATCH_KEYS:
        # If key appears inside strategic = { ... } block, it would be strategic
        # We just ensure the key string does not appear in those blocks incorrectly
        pass
    # Runtime check: create org and seed, verify tier
    import uuid

    from sqlalchemy import select

    from app.db.session import SessionLocal, create_all
    from app.models import Organization, Source

    create_all()
    db = SessionLocal()
    try:
        slug = f"pr039-tier-{uuid.uuid4().hex[:6]}"
        org = Organization(slug=slug, name="Tier Check", type="university", country="Colombia")
        db.add(org)
        db.commit()
        db.refresh(org)
        seed_default_sources(db, org)
        db.commit()
        for key in BATCH_KEYS:
            src = db.scalar(select(Source).where(Source.key == key))
            assert src is not None, f"source {key} not in DB after seed"
            assert src.tier == "experimental", f"{key} tier {src.tier} != experimental"
        # cleanup
        db.execute(Source.__table__.delete().where(Source.key.in_(list(BATCH_KEYS))))
        db.delete(org)
        db.commit()
    finally:
        db.close()
