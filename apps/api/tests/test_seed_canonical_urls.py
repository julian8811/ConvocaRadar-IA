"""Canonical seed URLs: forensic re-mapping of 16 stale seeds (AST only).

Zero network. Discovers nothing live; it pins the outcome of a
courtesy-capped forensic pass (<=2 GETs per source, repo User-Agent,
30s timeout, 32 total):
- Old path -> HTTP status recorded per source (all 404 except
  medellin-desarrollo-economico, which returned 200 and stays intact).
- A replacement is pinned ONLY when the canonical path appeared
  verbatim in the source's own live home HTML (navigation links for
  convocatorias / opportunities / editais / calls) or in live code
  already used by the repo (giz_funding.py).
- Otherwise the seed is left intact and recorded as PENDING-discovery
  (never guess URLs).

Decisions pinned here:
- sgc-convocatorias: the key/name point at SGC (Servicio Geologico
  Colombiano; geothermal is its mandate) but base_url points at
  segib.org (Ibero-American General Secretariat, no geothermal
  mandate, no calls hub on its live home, already covered by the
  segib-noticias seed). Real source is SGC; no verified canonical
  path on sgc.gov.co within budget, so the URL stays intact as
  PENDING-discovery with the mismatch documented.
- universidad-nacional-colombia: DO NOT TOUCH (renders in prod).
- medellin-desarrollo-economico: old URL verified live (HTTP 200),
  so the stale verdict is refuted for this exact URL; kept intact.
"""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import urlparse

# key -> (expected base_url, expected allowed_domains or None to skip check)
CANONICAL_SEEDS = {
    "inct-brasil": (
        "https://www.gov.br/cnpq/pt-br/chamadas/abertas-para-submissao",
        ["gov.br", "www.gov.br"],
    ),
    "cepal-convocatorias": (
        "https://www.cepal.org/es",
        ["cepal.org", "www.cepal.org"],
    ),
    "finagro-lec-2026": (
        "https://www.finagro.com.co/",
        ["finagro.com.co", "www.finagro.com.co"],
    ),
    "green-climate-fund": (
        "https://www.greenclimate.fund/access-funding",
        ["greenclimate.fund", "www.greenclimate.fund"],
    ),
    "supersolidaria-convocatorias": (
        "https://www.supersolidaria.gov.co/es/content/convocatorias-superintendencias",
        ["supersolidaria.gov.co", "www.supersolidaria.gov.co"],
    ),
    "oei-convocatorias": (
        "https://oei.int/licitaciones-y-convocatorias/",
        ["oei.int", "www.oei.int"],
    ),
    "global-environment-facility": (
        "https://www.thegef.org/who-we-are/funding",
        ["thegef.org", "www.thegef.org"],
    ),
    "giz-alemania": (
        # Aligned with GIZ_FUNDING_URL in app/connectors/giz_funding.py.
        "https://www.giz.de/en/partner/funding",
        ["giz.de", "www.giz.de", "ausschreibungen.giz.de"],
    ),
}

# Seeds left intact because no canonical path surfaced within budget.
PENDING_SEEDS = {
    "anp-brasil": "https://www.gov.br/anp/pt-br/assuntos/pesquisa-desenvolvimento-e-inovacao",
    "camara-comercio-cali": "https://www.ccc.org.co/convocatorias/",
    "flacso-convocatorias": "https://www.flacso.org/convocatorias",
    "rutann-convocatorias": "https://www.rutanmedellin.org/convocatorias",
    "procolombia-inversion": "https://investincolombia.com.co/es/convocatorias",
    # SGC decision: real source is Servicio Geologico Colombiano, but the
    # seed URL points at segib.org (wrong org). No verified sgc.gov.co
    # canonical path within budget, so it stays intact as PENDING.
    "sgc-convocatorias": "https://www.segib.org/convocatorias/",
}

# Verified live during discovery; must not be touched.
UNAL_SEED = {
    "universidad-nacional-colombia": (
        "https://investigacion.unal.edu.co/convocatorias/",
        ["unal.edu.co", "investigacion.unal.edu.co"],
    ),
}

# Old URL verified HTTP 200 live; stale verdict refuted, kept intact.
MEDELLIN_SEED = {
    "medellin-desarrollo-economico": (
        "https://www.medellin.gov.co/es/secretaria-desarrollo-economico/",
        ["medellin.gov.co", "www.medellin.gov.co"],
    ),
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


def _host_coherent(base_url: str, allowed_domains: list[str]) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    wanted = [d.lower() for d in allowed_domains]
    return any(host == d or host.endswith("." + d) or d.endswith("." + host) for d in wanted)


def test_canonical_base_urls_pinned():
    defs = _seed_definitions_by_key()
    for key, (expected_url, _domains) in CANONICAL_SEEDS.items():
        assert key in defs, f"missing seed {key}"
        assert defs[key]["base_url"] == expected_url, f"{key} not remapped"


def test_canonical_allowed_domains_coherent():
    defs = _seed_definitions_by_key()
    for key, (expected_url, expected_domains) in CANONICAL_SEEDS.items():
        definition = defs[key]
        assert definition["allowed_domains"] == expected_domains, f"{key} domains drifted"
        assert _host_coherent(expected_url, expected_domains), f"{key} host/domain mismatch"


def test_pending_seeds_unchanged():
    defs = _seed_definitions_by_key()
    for key, old_url in PENDING_SEEDS.items():
        assert key in defs, f"missing seed {key}"
        assert defs[key]["base_url"] == old_url, f"{key} must stay intact (PENDING-discovery)"


def test_sgc_decision_documented():
    """SGC is the Colombian Geological Survey, not SEGIB.

    The seed key/name describe SGC geothermal calls while base_url
    points at segib.org (wrong organization, no calls hub, already
    covered by segib-noticias). Until a verified sgc.gov.co calls path
    is discovered, the URL stays intact and PENDING.
    """
    defs = _seed_definitions_by_key()
    definition = defs["sgc-convocatorias"]
    assert definition["base_url"] == PENDING_SEEDS["sgc-convocatorias"]
    assert "SGC" in definition["name"]
    assert "segib.org" in definition["base_url"]
    assert definition["allowed_domains"] == ["segib.org", "www.segib.org"]


def test_unal_seed_untouched():
    defs = _seed_definitions_by_key()
    for key, (expected_url, expected_domains) in UNAL_SEED.items():
        assert defs[key]["base_url"] == expected_url
        assert defs[key]["allowed_domains"] == expected_domains


def test_medellin_live_url_kept():
    defs = _seed_definitions_by_key()
    for key, (expected_url, expected_domains) in MEDELLIN_SEED.items():
        assert defs[key]["base_url"] == expected_url
        assert defs[key]["allowed_domains"] == expected_domains
