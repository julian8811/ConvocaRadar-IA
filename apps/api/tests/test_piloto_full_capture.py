"""Piloto full-capture harness: dry-run default, limit 20, filler preference."""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PILOTO_PATH = REPO_ROOT / "scripts" / "piloto_full_capture.py"


def _load_piloto():
    spec = importlib.util.spec_from_file_location("piloto_full_capture", PILOTO_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class FakeSource:
    key: str
    source_type: str
    connector_config: dict | None = None


@dataclass
class FakeOpp:
    id: str
    official_url: str | None
    source: FakeSource
    funding_amount_value: float | None = None
    open_date: datetime | None = None
    close_date: datetime | None = None
    application_url: str | None = None
    summary: str = ""
    description: str = ""
    raw_text: str = ""
    eligible_applicants: list[str] = field(default_factory=list)
    evaluation_criteria: list[str] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    documents_required: list[str] = field(default_factory=list)
    funding_amount_raw: str | None = None
    funding_amount_currency: str | None = None


class TestPilotoDefaults:
    def test_default_limit_is_20(self):
        mod = _load_piloto()
        assert mod.DEFAULT_LIMIT == 20
        args = mod.parse_args([])
        assert args.limit == 20
        assert args.execute is False

    def test_execute_requires_explicit_flag(self):
        mod = _load_piloto()
        args = mod.parse_args(["--execute"])
        assert args.execute is True
        assert args.limit == 20

    def test_custom_limit_override(self):
        mod = _load_piloto()
        args = mod.parse_args(["--limit", "5"])
        assert args.limit == 5
        assert args.execute is False


class TestPilotoSelection:
    def test_prefers_filler_sources_and_caps_at_limit(self):
        mod = _load_piloto()
        rows = [
            FakeOpp("f1", "https://a.example/1", FakeSource("grants-gov", "api")),
            FakeOpp("f2", "https://b.example/2", FakeSource("rss-feed", "rss")),
            FakeOpp(
                "f3",
                "https://c.example/3",
                FakeSource("cfg-portal", "html", connector_config={"list_selectors": [".card"]}),
            ),
            FakeOpp("f4", "https://d.example/4", FakeSource("generic-portal", "html")),
            FakeOpp("n1", "https://e.example/5", FakeSource("minciencias", "html")),
            FakeOpp("n2", "https://f.example/6", FakeSource("heading_list", "html")),
        ]
        # Inflate with more fillers so preference is visible at limit 3
        selected = mod.select_piloto_rows(rows, limit=3)
        assert len(selected) == 3
        keys = {r.source.key for r in selected}
        assert "minciencias" not in keys
        assert "heading_list" not in keys
        assert keys <= {"grants-gov", "rss-feed", "cfg-portal", "generic-portal"}

    def test_pads_from_non_filler_when_pool_short(self):
        mod = _load_piloto()
        rows = [
            FakeOpp("f1", "https://a.example/1", FakeSource("grants-gov", "api")),
            FakeOpp("n1", "https://b.example/2", FakeSource("minciencias", "html")),
            FakeOpp("n2", "https://c.example/3", FakeSource("wordpress-portal", "html")),
        ]
        selected = mod.select_piloto_rows(rows, limit=3)
        assert len(selected) == 3
        ids = [r.id for r in selected]
        assert ids[0] == "f1"
        assert set(ids[1:]) == {"n1", "n2"}

    def test_skips_rows_without_official_url(self):
        mod = _load_piloto()
        rows = [
            FakeOpp("f1", None, FakeSource("grants-gov", "api")),
            FakeOpp("f2", "https://ok.example/2", FakeSource("rss-feed", "rss")),
            FakeOpp("f3", "   ", FakeSource("api-x", "api")),
        ]
        selected = mod.select_piloto_rows(rows, limit=20)
        assert [r.id for r in selected] == ["f2"]


class TestPilotoMerge:
    def test_merge_fills_null_scalars_and_empty_lists(self):
        mod = _load_piloto()
        existing = FakeOpp(
            "x",
            "https://x.example",
            FakeSource("grants-gov", "api"),
            summary="Number: FOO | Status: posted",
        )
        extracted = {
            "funding_amount_value": 1000.0,
            "funding_amount_currency": "USD",
            "funding_amount_raw": "USD 1,000",
            "open_date": datetime(2026, 3, 15),
            "close_date": datetime(2026, 9, 30),
            "application_url": "https://x.example/apply",
            "eligible_applicants": ["SMEs"],
            "evaluation_criteria": ["Impact"],
            "restrictions": ["No sanctions"],
            "summary": (
                "This is a substantive summary about the grant opportunity for "
                "innovation projects across the region with clear goals."
            ),
            "description": "Longer description text for the opportunity detail page.",
            "raw_text": "raw body " * 20,
        }
        deltas = mod.compute_merge_deltas(existing, extracted)
        assert deltas["funding_amount_value"] == 1000.0
        assert deltas["application_url"] == "https://x.example/apply"
        assert deltas["eligible_applicants"] == ["SMEs"]
        assert "summary" in deltas
        assert len(deltas["summary"]) > len(existing.summary)

    def test_merge_does_not_overwrite_populated_scalars(self):
        mod = _load_piloto()
        existing = FakeOpp(
            "x",
            "https://x.example",
            FakeSource("grants-gov", "api"),
            funding_amount_value=500.0,
            application_url="https://x.example/old",
            eligible_applicants=["Already set"],
            summary=(
                "A substantive existing summary that should not be replaced by shorter junk."
            ),
        )
        extracted = {
            "funding_amount_value": 9999.0,
            "application_url": "https://x.example/new",
            "eligible_applicants": ["New list"],
            "summary": "short junk",
        }
        deltas = mod.compute_merge_deltas(existing, extracted)
        assert "funding_amount_value" not in deltas
        assert "application_url" not in deltas
        assert "eligible_applicants" not in deltas
        assert "summary" not in deltas


class TestPilotoConcurrencyAndDryRun:
    @pytest.mark.asyncio
    async def test_semaphore_bound_is_at_most_two(self):
        mod = _load_piloto()
        assert mod.MAX_CONCURRENCY == 2
        assert mod.MAX_CONCURRENCY <= 2

        current = 0
        peak = 0
        lock = asyncio.Lock()

        async def fake_fetch(url: str, **kwargs: Any):
            nonlocal current, peak
            async with lock:
                current += 1
                peak = max(peak, current)
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1
            return (url, "<html><body><p>Fecha de cierre: 30 de septiembre de 2026</p></body></html>", "text/html")

        rows = [
            FakeOpp(f"r{i}", f"https://ex.example/{i}", FakeSource("grants-gov", "api"))
            for i in range(6)
        ]
        commits: list[str] = []

        def fake_commit(opp_id: str, deltas: dict) -> None:
            commits.append(opp_id)

        report = await mod.run_piloto(
            rows,
            limit=6,
            execute=False,
            fetch=fake_fetch,
            commit_fn=fake_commit,
        )
        assert peak <= 2
        assert commits == []
        assert report["processed"] == 6
        assert report["dry_run"] is True

    @pytest.mark.asyncio
    async def test_execute_commits_deltas(self):
        mod = _load_piloto()
        commits: list[tuple[str, dict]] = []

        async def fake_fetch(url: str, **kwargs: Any):
            html = (
                "<html><body><article>"
                "<p>Fecha de cierre: 30 de septiembre de 2026. Monto: USD 50,000.</p>"
                "<p>¿Quién puede participar?</p><ul><li>Startups</li></ul>"
                "</article></body></html>"
            )
            return (url, html, "text/html")

        row = FakeOpp("e1", "https://ex.example/1", FakeSource("grants-gov", "api"))
        await mod.run_piloto(
            [row],
            limit=1,
            execute=True,
            fetch=fake_fetch,
            commit_fn=lambda oid, d: commits.append((oid, d)),
        )
        assert len(commits) == 1
        assert commits[0][0] == "e1"
        assert commits[0][1]  # non-empty deltas

    @pytest.mark.asyncio
    async def test_piloto_never_calls_llm_enrich(self, monkeypatch):
        mod = _load_piloto()
        called = {"llm": False}

        async def boom(*args, **kwargs):
            called["llm"] = True
            raise AssertionError("LLM must not be called")

        monkeypatch.setattr(
            "app.services.opportunity.enrich_opportunity_payload",
            boom,
            raising=False,
        )
        monkeypatch.setattr(
            "app.core.ai.create_ai_extraction",
            boom,
            raising=False,
        )

        async def fake_fetch(url: str, **kwargs: Any):
            return (url, "<html><body><p>Deadline: June 30, 2027</p></body></html>", "text/html")

        await mod.run_piloto(
            [FakeOpp("e1", "https://ex.example/1", FakeSource("rss-x", "rss"))],
            limit=1,
            execute=False,
            fetch=fake_fetch,
            commit_fn=lambda *_: None,
        )
        assert called["llm"] is False
