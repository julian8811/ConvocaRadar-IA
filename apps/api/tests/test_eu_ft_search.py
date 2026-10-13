"""EU F&T search-API POST connector surface (4 programme keys).

Regression lock for the finding that ``erc-calls``,
``eu-creative-europe-calls``, ``horizon-europe-sedia`` and ``msca-funding``
share the POST-only endpoint
``https://api.tech.ec.europa.eu/search-api/prod/rest/search``
(GET answers 405). The shared implementation lives in
``app.connectors.ft_search_v2``; this module asserts the wiring from the
``eu_ft_search`` alias surface so the four fichas cannot silently drift back
to a GET/HTML connector. Zero network: transport is mocked.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import RawSourceResult

EU_FT_KEYS = (
    "erc-calls",
    "horizon-europe-sedia",
    "msca-funding",
    "eu-creative-europe-calls",
)

EU_FT_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"


def _raw_for(key: str, items: list[dict]) -> RawSourceResult:
    return RawSourceResult(
        source_key=key,
        url=EU_FT_SEARCH_URL,
        content=json.dumps({"results": items}, ensure_ascii=False),
        content_type="application/json",
    )


def _connector(key: str):
    from app.connectors.factory import connector_for

    return connector_for(key, EU_FT_SEARCH_URL, "api")


# ── Alias surface ──────────────────────────────────────────────────────────


def test_eu_ft_search_module_exposes_shared_endpoint():
    from app.connectors import eu_ft_search

    assert eu_ft_search.FT_SEARCH_URL == EU_FT_SEARCH_URL
    assert eu_ft_search.EU_FT_KEYS == EU_FT_KEYS


def test_eu_ft_search_reexports_programme_specs():
    from app.connectors import eu_ft_search

    assert eu_ft_search.ERC_PROGRAM.key == "erc-calls"
    assert eu_ft_search.HORIZON_PROGRAM.key == "horizon-europe-sedia"
    assert eu_ft_search.MSCA_PROGRAM.key == "msca-funding"
    assert eu_ft_search.CREATIVE_PROGRAM.key == "eu-creative-europe-calls"


# ── Factory wiring (the 4 keys share the POST endpoint) ────────────────────


def test_eu_ft_all_four_keys_registered():
    from app.connectors import factory  # noqa: F401 — side-effect registrations
    from app.connectors.registry import registered_keys

    keys = registered_keys()
    for key in EU_FT_KEYS:
        assert key in keys, f"{key} not registered"


@pytest.mark.parametrize("key", EU_FT_KEYS)
def test_eu_ft_factory_resolves_post_connector(key: str):
    from app.connectors import factory  # noqa: F401 — ensure side-effect imports

    connector = _connector(key)
    assert connector.source_key == key
    assert connector.base_url == EU_FT_SEARCH_URL


# ── POST-only transport (endpoint answers 405 to GET) ──────────────────────


async def test_eu_ft_fetch_uses_post_with_apikey(monkeypatch: pytest.MonkeyPatch):
    from app.connectors import eu_ft_search

    seen: list[tuple[str, dict]] = []

    async def fake_fetch(url: str, **kwargs):
        seen.append((url, kwargs))
        return (url, json.dumps({"results": []}), "application/json")

    monkeypatch.setattr(
        eu_ft_search.ft_search_v2, "fetch_httpx_text", AsyncMock(side_effect=fake_fetch)
    )
    raw = await _connector("erc-calls").fetch()
    assert raw.source_key == "erc-calls"
    assert seen, "fetch must hit the endpoint once per term"
    assert all(url.startswith(EU_FT_SEARCH_URL) for url, _ in seen)
    assert all("apiKey=" in url for url, _ in seen)
    # POST-only endpoint: a GET would answer 405, so every call must be POST.
    assert all(kw.get("method") == "POST" for _, kw in seen)


# ── Open-calls filtering (full-text returns Ended projects, must be cut) ────


def _open_item(identifier: str, title: str) -> dict:
    return {
        "summary": title,
        "reference": identifier.lower(),
        "metadata": {
            "callTitle": [title],
            "callIdentifier": [identifier],
            "identifier": [identifier],
            "status": ["Ongoing"],
            "keywords": ["Horizon Europe"],
            "actions": None,
            "startDate": ["2025-09-01T00:00:00.000+0000"],
            "deadlineDate": ["2027-03-01T00:00:00.000+0000"],
        },
    }


CLOSED_ITEM = {
    "summary": "ERC Starting Grant",
    "reference": "31062482StartingGrant1412640000000sl",
    "metadata": {
        "callTitle": ["Call for proposals for ERC Starting Grant"],
        "callIdentifier": ["ERC-2015-STG"],
        "identifier": ["ERC-StG-2015"],
        "status": ["31094503"],
        "keywords": ["European Research Council"],
        "actions": None,
        "startDate": ["2014-10-07T00:00:00.000+0000"],
        "deadlineDate": ["2015-02-03T00:00:00.000+0000"],
    },
}


async def test_eu_ft_closed_call_yields_no_candidates():
    candidates = await _connector("erc-calls").parse(
        _raw_for("erc-calls", [CLOSED_ITEM])
    )
    assert candidates == []


async def test_eu_ft_mixed_payload_disjoint_across_programmes():
    items = [
        _open_item("ERC-2026-STG", "Call for proposals for ERC Starting Grant"),
        _open_item("HORIZON-MSCA-2026-PF-01", "MSCA Postdoctoral Fellowships 2026"),
        _open_item("CREA-CULT-2026-NET", "Creative Europe networks call"),
        _open_item("HORIZON-CL2-2026-DEMOCRACY-01", "HORIZON-CL2-2026-DEMOCRACY call"),
        CLOSED_ITEM,
    ]
    counts = {}
    for key in EU_FT_KEYS:
        candidates = await _connector(key).parse(_raw_for(key, items))
        counts[key] = len(candidates)
    assert counts == {
        "erc-calls": 1,
        "horizon-europe-sedia": 1,
        "msca-funding": 1,
        "eu-creative-europe-calls": 1,
    }


# ── Seeds: the 4 keys are api-type F&T sources ──────────────────────────────


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


@pytest.mark.parametrize("key", EU_FT_KEYS)
def test_eu_ft_seeds_are_ft_api_sources(key: str):
    defs = _seed_definitions_by_key()
    assert key in defs, f"missing seed {key}"
    definition = defs[key]
    assert definition.get("enabled", True) is True
    assert definition["source_type"] == "api"
    assert definition["base_url"] == EU_FT_SEARCH_URL
    assert "connector_config" not in definition, f"{key} must not carry html config"
