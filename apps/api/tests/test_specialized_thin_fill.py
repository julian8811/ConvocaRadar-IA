"""Specialized connectors must thin-fill with text= after construct (no list html=)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.simpler_grants import SimplerGrantsConnector
from app.connectors.world_bank import WorldBankConnector

CONNECTORS_DIR = Path(__file__).resolve().parents[1] / "app" / "connectors"

ALREADY_WIRED = frozenset(
    {
        "generic_html.py",
        "configurable_html.py",
        "rss.py",
        "api.py",
        "grants_gov.py",
    }
)

SKIP_MODULES = frozenset(
    {
        "common.py",
        "base.py",
        "registry.py",
        "factory.py",
        "__init__.py",
        "health_check.py",
        "manual.py",
        "hybrid.py",
    }
)

THIN_FILL_MARKERS = ("thin_fill_candidate", "thin_fill_candidates")


def _specialized_connector_modules() -> list[Path]:
    modules: list[Path] = []
    for path in sorted(CONNECTORS_DIR.glob("*.py")):
        if path.name in ALREADY_WIRED or path.name in SKIP_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        if "OpportunityCandidate(" not in source:
            continue
        modules.append(path)
    return modules


def test_specialized_modules_inventory_is_non_empty():
    modules = _specialized_connector_modules()
    assert len(modules) >= 30
    names = {p.name for p in modules}
    assert "simpler_grants.py" in names
    assert "world_bank.py" in names
    assert "apc_colombia.py" in names
    assert "generic_html.py" not in names
    assert "rss.py" not in names


def test_thin_fill_candidate_passes_text_not_html(monkeypatch):
    """Helper must call fill with candidate text only — never html=."""
    from app.connectors.common import thin_fill_candidate

    captured: list[dict] = []

    def _capture(candidate, *, html=None, text=None, page_url=None):
        captured.append({"html": html, "text": text, "page_url": page_url})
        return candidate

    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _capture)

    cand = OpportunityCandidate(
        title="Grant with funding USD 50,000 deadline 15 March 2026",
        entity="Test",
        country="Colombia",
        official_url="https://example.org/grant/1",
        summary="Short summary",
        raw_text="Eligible applicants: universities. Funding: USD 50,000. Close: 15 March 2026.",
    )
    out = thin_fill_candidate(cand)
    assert out is cand or out.title == cand.title
    assert len(captured) == 1
    assert captured[0]["html"] is None
    assert captured[0]["text"]
    assert "USD 50,000" in captured[0]["text"]
    assert captured[0]["page_url"] == cand.official_url


def test_thin_fill_candidate_falls_back_to_summary(monkeypatch):
    from app.connectors.common import thin_fill_candidate

    captured: list[dict] = []

    def _capture(candidate, *, html=None, text=None, page_url=None):
        captured.append({"html": html, "text": text})
        return candidate

    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _capture)

    cand = OpportunityCandidate(
        title="Summary-only row",
        entity="Test",
        country="Spain",
        official_url="https://example.org/g/2",
        summary="Deadline 1 April 2026 for research consortia",
        raw_text="",
    )
    thin_fill_candidate(cand)
    assert len(captured) == 1
    assert captured[0]["html"] is None
    assert captured[0]["text"] == cand.summary


def test_thin_fill_candidate_signature_has_no_html():
    from app.connectors import common as common_mod

    assert hasattr(common_mod, "thin_fill_candidate")
    tree = ast.parse(Path(common_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "thin_fill_candidate":
            arg_names = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            assert "html" not in arg_names
            return
    pytest.fail("thin_fill_candidate definition not found")


def test_every_specialized_module_calls_thin_fill_helper():
    missing: list[str] = []
    for path in _specialized_connector_modules():
        source = path.read_text(encoding="utf-8")
        if not any(marker in source for marker in THIN_FILL_MARKERS):
            missing.append(path.name)
    assert missing == [], f"Specialized modules missing thin-fill helper: {missing}"


@pytest.mark.asyncio
async def test_simpler_grants_thin_fills_with_text(monkeypatch):
    calls: list[dict] = []

    def _spy(candidate, *, html=None, text=None, page_url=None):
        calls.append({"html": html, "text": text, "url": page_url})
        return candidate

    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _spy)

    content = (
        r'href\":\"/opportunity/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\",'
        r'\"children\":\"Climate Innovation Grant\"'
    )
    raw = RawSourceResult(
        source_key="simpler-grants",
        url="https://simpler.grants.gov/search",
        content=content,
        content_type="text/html",
    )
    candidates = await SimplerGrantsConnector().parse(raw)
    assert len(candidates) >= 1
    assert calls, "parse must invoke fill_candidate_from_content via thin fill"
    for call in calls:
        assert call["html"] is None
        assert call["text"]


@pytest.mark.asyncio
async def test_world_bank_thin_fills_with_text_not_list_html(monkeypatch):
    calls: list[dict] = []

    def _spy(candidate, *, html=None, text=None, page_url=None):
        calls.append({"html": html, "text": text})
        return candidate

    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _spy)

    payload = {
        "procnotices": {
            "WB-1": {
                "id": "WB-1",
                "bid_description": "Procurement for research labs",
                "project_name": "Lab upgrade",
                "notice_text": "Award ceiling USD 100000. Submission deadline 2026-06-01.",
                "submission_date": "2026-06-01T00:00:00",
                "project_ctry_name": "Colombia",
            }
        }
    }
    raw = RawSourceResult(
        source_key="world-bank-procurement",
        url="https://search.worldbank.org/api/v2/procnotices",
        content=json.dumps(payload),
        content_type="application/json",
    )
    candidates = await WorldBankConnector().parse(raw)
    assert len(candidates) >= 1
    assert calls, "parse must invoke fill_candidate_from_content via thin fill"
    for call in calls:
        assert call["html"] is None
        assert call["text"]
        assert "<html" not in (call["text"] or "").lower()
