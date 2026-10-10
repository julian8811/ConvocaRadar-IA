"""F1 fuentes-cirugia-mayor: unified F&T search-API v2 connector (4 programmes).

TDD: written before ``app.connectors.ft_search_v2`` existed (RED = ImportError).
Fixtures are trimmed real v2 payloads captured 2026-10-10 via respectful
pageSize=3 probes (POST empty body to
``.../rest/search?apiKey=SEDIA&text={term}&pageSize=..&pageNumber=1``).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import RawSourceResult

V2_KEYS = (
    "erc-calls",
    "horizon-europe-sedia",
    "msca-funding",
    "eu-creative-europe-calls",
)

FT_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"

# ── Real-shape fixtures (trimmed probe payloads) ─────────────────────────────

ERC_OPEN_ITEM = {
    "summary": "ERC Starting Grant",
    "reference": "31086861StartingGrant1501718400000sl",
    "metadata": {
        "callTitle": ["Call for proposals for ERC Starting Grant"],
        "callIdentifier": ["ERC-2026-STG"],
        "identifier": ["ERC-2026-STG"],
        "status": ["Ongoing"],
        "keywords": ["Excellent Science", "European Research Council", "Starting Grant"],
        "actions": [
            json.dumps(
                [
                    {
                        "status": {"id": 31094501, "abbreviation": "Open"},
                        "plannedOpeningDate": "03 July 2025",
                        "deadlineDates": ["15 October 2026"],
                    }
                ]
            )
        ],
        "startDate": ["2025-07-03T00:00:00.000+0000"],
        "deadlineDate": ["2026-10-15T00:00:00.000+0000"],
    },
}

# Real probe shape: closed ERC call (status id 31094503, past deadline).
ERC_CLOSED_ITEM = {
    "summary": "ERC Starting Grant",
    "reference": "31062482StartingGrant1412640000000sl",
    "metadata": {
        "callTitle": ["Call for proposals for ERC Starting Grant"],
        "callIdentifier": ["ERC-2015-STG"],
        "identifier": ["ERC-StG-2015"],
        "status": ["31094503"],
        "keywords": ["European Research Council", "Starting Grant"],
        "actions": [
            json.dumps(
                [
                    {
                        "status": {"id": 31094503, "abbreviation": "Closed"},
                        "plannedOpeningDate": "07 October 2014",
                        "deadlineDates": ["2015-02-03T00:00:00.000+0000"],
                    }
                ]
            )
        ],
        "startDate": ["2014-10-07T00:00:00.000+0000"],
        "deadlineDate": ["2015-02-03T00:00:00.000+0000"],
    },
}

# Real probe shape: MSCA topic (callTitle null, title falls back to summary,
# identifier falls back to callIdentifier, +0100 date offset).
MSCA_ITEM = {
    "summary": "MSCA-GLOPOL: MSCA Global Cooperation: Policy Enhancement",
    "reference": "43108390101202507mt",
    "metadata": {
        "callTitle": None,
        "callIdentifier": ["HORIZON-MSCA-2024-INCO-01"],
        "identifier": None,
        "status": ["Ongoing"],
        "keywords": None,
        "actions": None,
        "startDate": ["2025-06-01T00:00:00.000+0100"],
        "deadlineDate": None,
    },
}

CREA_ITEM = {
    "summary": "Creative Europe networks: CREA-CULT-2026-NET",
    "reference": "crea-cult-2026-net",
    "metadata": {
        "callTitle": ["Creative Europe — European Networks of cultural organisations"],
        "callIdentifier": ["CREA-CULT-2026-NET"],
        "identifier": ["CREA-CULT-2026-NET"],
        "status": ["Ongoing"],
        "keywords": ["Creative Europe", "culture", "networks"],
        "actions": None,
        "startDate": ["2025-10-01T00:00:00.000+0000"],
        "deadlineDate": ["2027-01-15T00:00:00.000+0000"],
    },
}

# Generic Horizon framework call: no ERC/MSCA/CREA markers.
HORIZON_ITEM = {
    "summary": "HORIZON-CL2-2026-DEMOCRACY call topic",
    "reference": "horizon-cl2-2026",
    "metadata": {
        "callTitle": ["Call for proposals for HORIZON-CL2-2026-DEMOCRACY"],
        "callIdentifier": ["HORIZON-CL2-2026-DEMOCRACY-01"],
        "identifier": ["HORIZON-CL2-2026-DEMOCRACY-01"],
        "status": ["Ongoing"],
        "keywords": ["Horizon Europe", "democracy", "research"],
        "actions": None,
        "startDate": ["2025-09-01T00:00:00.000+0000"],
        "deadlineDate": ["2027-03-01T00:00:00.000+0000"],
    },
}

ALL_ITEMS = [ERC_OPEN_ITEM, ERC_CLOSED_ITEM, MSCA_ITEM, CREA_ITEM, HORIZON_ITEM]


def _raw_for(key: str, items: list[dict]) -> RawSourceResult:
    return RawSourceResult(
        source_key=key,
        url=FT_SEARCH_URL,
        content=json.dumps({"results": items}, ensure_ascii=False),
        content_type="application/json",
    )


def _connector(key: str):
    from app.connectors.factory import connector_for

    return connector_for(key, FT_SEARCH_URL, "api")


# ── Registration / factory ──────────────────────────────────────────────────


def test_v2_all_four_keys_registered():
    from app.connectors import factory  # noqa: F401 — side-effect registrations
    from app.connectors.registry import registered_keys

    keys = registered_keys()
    for key in V2_KEYS:
        assert key in keys, f"{key} not registered"


@pytest.mark.parametrize("key", V2_KEYS)
def test_v2_factory_resolves_dedicated_connector(key: str):
    from app.connectors import factory  # noqa: F401 — ensure side-effect imports

    connector = _connector(key)
    assert connector.source_key == key
    assert connector.__class__.__name__.endswith("V2Connector")


def test_v2_four_connectors_share_base_but_differ_in_program():
    conns = [_connector(key) for key in V2_KEYS]
    programs = {c.PROGRAM.key for c in conns}
    assert programs == set(V2_KEYS)
    bases = {c.__class__.__base__.__name__ for c in conns}
    assert bases == {"FtSearchV2Connector"}


# ── Programme filter (disjointness) ─────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected_titles"),
    [
        ("erc-calls", ["Call for proposals for ERC Starting Grant"]),
        ("horizon-europe-sedia", []),
        ("msca-funding", []),
        ("eu-creative-europe-calls", []),
    ],
)
async def test_v2_erc_open_item_only_claimed_by_erc(key: str, expected_titles: list[str]):
    candidates = await _connector(key).parse(_raw_for(key, [ERC_OPEN_ITEM]))
    assert [c.title for c in candidates] == expected_titles


@pytest.mark.asyncio
async def test_v2_erc_closed_item_yields_no_candidates():
    candidates = await _connector("erc-calls").parse(_raw_for("erc-calls", [ERC_CLOSED_ITEM]))
    assert candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected_count"),
    [
        ("erc-calls", 0),
        ("horizon-europe-sedia", 0),
        ("msca-funding", 1),
        ("eu-creative-europe-calls", 0),
    ],
)
async def test_v2_msca_item_only_claimed_by_msca(key: str, expected_count: int):
    candidates = await _connector(key).parse(_raw_for(key, [MSCA_ITEM]))
    assert len(candidates) == expected_count
    if expected_count:
        assert "MSCA" in candidates[0].title
        assert "HORIZON-MSCA-2024-INCO-01" in candidates[0].official_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected_count"),
    [
        ("erc-calls", 0),
        ("horizon-europe-sedia", 0),
        ("msca-funding", 0),
        ("eu-creative-europe-calls", 1),
    ],
)
async def test_v2_crea_item_only_claimed_by_creative(key: str, expected_count: int):
    candidates = await _connector(key).parse(_raw_for(key, [CREA_ITEM]))
    assert len(candidates) == expected_count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected_count"),
    [
        ("erc-calls", 0),
        ("horizon-europe-sedia", 1),
        ("msca-funding", 0),
        ("eu-creative-europe-calls", 0),
    ],
)
async def test_v2_horizon_item_only_claimed_by_horizon(key: str, expected_count: int):
    candidates = await _connector(key).parse(_raw_for(key, [HORIZON_ITEM]))
    assert len(candidates) == expected_count


@pytest.mark.asyncio
async def test_v2_mixed_payload_disjoint_across_programmes():
    counts = {}
    for key in V2_KEYS:
        candidates = await _connector(key).parse(_raw_for(key, ALL_ITEMS))
        counts[key] = len(candidates)
    assert counts == {
        "erc-calls": 1,
        "horizon-europe-sedia": 1,
        "msca-funding": 1,
        "eu-creative-europe-calls": 1,
    }


@pytest.mark.asyncio
async def test_v2_parse_garbage_returns_empty_list():
    raw = RawSourceResult(
        source_key="erc-calls",
        url=FT_SEARCH_URL,
        content="not json",
        content_type="application/json",
    )
    with pytest.raises(Exception):
        await _connector("erc-calls").parse(raw)


# ── _is_openish (reused semantics) ───────────────────────────────────────────


def test_v2_is_openish_closed_id():
    from app.connectors.ft_search_v2 import _is_openish

    assert _is_openish(["31094503"], None) is False
    assert _is_openish(["closed"], None) is False
    assert _is_openish(["Ongoing"], None) is True
    assert _is_openish([], None) is True


def test_v2_is_openish_past_deadline_always_closed():
    from datetime import datetime

    from app.connectors.ft_search_v2 import _is_openish

    assert _is_openish(["Ongoing"], datetime(2020, 1, 1)) is False


# ── Fetch (mocked transport, eic-style POST with empty body) ─────────────────


@pytest.mark.asyncio
async def test_v2_fetch_posts_empty_body_with_apikey_param(monkeypatch: pytest.MonkeyPatch):
    from app.connectors import ft_search_v2

    seen: list[tuple[str, dict]] = []

    async def fake_fetch(url: str, **kwargs):
        seen.append((url, kwargs))
        return (url, json.dumps({"results": [MSCA_ITEM]}), "application/json")

    monkeypatch.setattr(ft_search_v2, "fetch_httpx_text", AsyncMock(side_effect=fake_fetch))
    connector = _connector("msca-funding")
    raw = await connector.fetch()
    assert raw.source_key == "msca-funding"
    assert seen, "fetch must hit the network once per term"
    assert all("apiKey=" in url for url, _ in seen)
    assert all(kw.get("method") == "POST" for _, kw in seen)
    payload = json.loads(raw.content)
    # Programme filter applies at fetch: MSCA term payload keeps the MSCA item.
    assert len(payload["results"]) == 1


@pytest.mark.asyncio
async def test_v2_fetch_applies_programme_filter(monkeypatch: pytest.MonkeyPatch):
    from app.connectors import ft_search_v2

    async def fake_fetch(url: str, **kwargs):
        return (url, json.dumps({"results": ALL_ITEMS}), "application/json")

    monkeypatch.setattr(ft_search_v2, "fetch_httpx_text", AsyncMock(side_effect=fake_fetch))
    raw = await _connector("eu-creative-europe-calls").fetch()
    payload = json.loads(raw.content)
    assert {i["reference"] for i in payload["results"]} == {"crea-cult-2026-net"}


# ── Seeds: the 4 keys are api-type F&T sources ───────────────────────────────


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


@pytest.mark.parametrize("key", V2_KEYS)
def test_v2_seeds_are_ft_api_sources(key: str):
    defs = _seed_definitions_by_key()
    assert key in defs, f"missing seed {key}"
    definition = defs[key]
    assert definition.get("enabled", True) is True
    assert definition["source_type"] == "api"
    assert definition["base_url"] == FT_SEARCH_URL
    assert "connector_config" not in definition, f"{key} must not carry html config"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", V2_KEYS)
async def test_v2_validate_ok(key: str):
    from app.connectors.base import OpportunityCandidate

    connector = _connector(key)
    result = await connector.validate(
        OpportunityCandidate(
            title="Test call",
            entity="EU",
            country="European Union",
            official_url="https://ec.europa.eu/test",
        )
    )
    assert result.ok is True
