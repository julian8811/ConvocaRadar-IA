"""040 Next 8-source expansion: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "jsps-kakenhi-grants",
    "jsps-fellowships",
    "rwjf-grants-funding",
    "czi-science-grants",
    "kellogg-foundation-grants",
    "hewlett-foundation-grants",
    "carnegie-foundation-grants",
    "nrf-south-africa-bursaries",
)

BATCH_URLS = {
    "jsps-kakenhi-grants": "https://www.jsps.go.jp/english/e-grants/",
    "jsps-fellowships": "https://www.jsps.go.jp/english/e-fellow/",
    "rwjf-grants-funding": "https://www.rwjf.org/en/grants.html",
    "czi-science-grants": "https://chanzuckerberg.com/grants-ventures/grants/",
    "kellogg-foundation-grants": "https://www.wkkf.org/grantseekers/",
    "hewlett-foundation-grants": "https://hewlett.org/grants/",
    "carnegie-foundation-grants": "https://www.carnegie.org/grants/",
    "nrf-south-africa-bursaries": "https://www.nrf.ac.za/bursaries/",
}

BATCH_ALLOWED_FAMILIES = {
    "jsps-kakenhi-grants": "jsps.go.jp",
    "jsps-fellowships": "jsps.go.jp",
    "rwjf-grants-funding": "rwjf.org",
    "czi-science-grants": "chanzuckerberg.com",
    "kellogg-foundation-grants": "wkkf.org",
    "hewlett-foundation-grants": "hewlett.org",
    "carnegie-foundation-grants": "carnegie.org",
    "nrf-south-africa-bursaries": "nrf.ac.za",
}

ALL_FAMILIES = {"jsps.go.jp", "rwjf.org", "chanzuckerberg.com", "wkkf.org", "hewlett.org", "carnegie.org", "nrf.ac.za"}


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


def test_040_keys_enabled_and_configurable():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} not enabled"
        # connector_type or source_type check
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


def test_040_catalog_count_and_uniqueness():
    defs = _seed_definitions_by_key()
    assert len(defs) == 201, f"expected 201 keys, got {len(defs)}"
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


def test_040_allowed_domains_families():
    defs = _seed_definitions_by_key()
    # Each key's allowed_domains contains its family
    for key in BATCH_KEYS:
        assert BATCH_ALLOWED_FAMILIES[key] in defs[key]["allowed_domains"], f"{key} missing {BATCH_ALLOWED_FAMILIES[key]}"
    # All 7 families present across batch
    all_domains = set()
    for key in BATCH_KEYS:
        all_domains.update(defs[key]["allowed_domains"])
    for fam in ALL_FAMILIES:
        assert fam in all_domains, f"family {fam} not in any allowed_domains"
    # jsps.go.jp deduplicated — both JSPS keys share same family, only one distinct family entry
    jsps_keys = [k for k in BATCH_KEYS if BATCH_ALLOWED_FAMILIES[k] == "jsps.go.jp"]
    assert len(jsps_keys) == 2
    # Factory produces ConfigurableHtmlConnector
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"


def test_040_tier_experimental():
    import uuid

    from sqlalchemy import select

    from app.db.seed import seed_default_sources
    from app.db.session import SessionLocal, create_all
    from app.models import Organization, Source

    create_all()
    db = SessionLocal()
    try:
        slug = f"pr040-tier-{uuid.uuid4().hex[:6]}"
        org = Organization(slug=slug, name="Tier Check 040", type="university", country="Colombia")
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
