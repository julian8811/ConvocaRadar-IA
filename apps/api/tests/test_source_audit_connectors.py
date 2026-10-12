"""Regresion Fase 3: auditor vs conectores REALES en memoria.

Sin red, sin DB, sin mutaciones. Ejercita `parse`/`validate` de los
conectores reales (ASCUN + 2 genericos: RSS y WordPress) sobre fixtures
en memoria y verifica que `audit_source` clasifica sin mutar entradas.

No duplica ni altera PR #56 (tests unitarios del conector ASCUN):
aqui el objeto bajo prueba es el AUDITOR frente a candidatos reales.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.history import audit_source
from app.audit.types import CheckStatus, Verdict
from app.connectors.base import RawSourceResult

NOW = datetime.now(UTC).replace(tzinfo=None)
FUTURE = (NOW + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")


# ── Fixtures en memoria ──────────────────────────────────────────────

ASCUN_PAYLOAD = [
    {
        "id": 11,
        "date": "2026-09-01T10:00:00",
        "link": "https://ascun.org.co/convocatoria-movilidad-2026/",
        "title": {"rendered": "Convocatoria de movilidad academica 2026"},
        "excerpt": {"rendered": "<p>Movilidad para investigadores.</p>"},
        "content": {"rendered": "<p>Detalle.</p>"},
    },
    {
        "id": 12,
        "date": "2026-09-05T10:00:00",
        "link": "https://ascun.org.co/beca-posgrado-2026/",
        "title": {"rendered": "Beca de posgrado universitario 2026"},
        "excerpt": {"rendered": ""},
        "content": {"rendered": "<p>Beca completa.</p>"},
    },
]

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Grants feed</title><link>https://example.org/grants</link>
<item><title>Research grant for health innovation 2026</title>
<link>https://example.org/grants/health-2026</link>
<description>Funding for health research teams.</description>
<pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Open call for education cooperation 2026</title>
<link>https://example.org/grants/edu-2026</link>
<description>Cooperation grants for universities.</description>
<pubDate>Tue, 02 Sep 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

WORDPRESS_PAYLOAD = [
    {
        "id": 21,
        "status": "publish",
        "date": "2026-09-01T10:00:00",
        "link": "https://novonordiskfonden.dk/grant-health-2026/",
        "title": {"rendered": "Health research grant 2026"},
        "acf": {"summary": "Grants for health research.",
                "deadline": "2027-06-30T23:59:59"},
    },
    {
        "id": 22,
        "status": "publish",
        "date": "2026-09-03T10:00:00",
        "link": "https://novonordiskfonden.dk/grant-edu-2026/",
        "title": {"rendered": "Education cooperation grant 2026"},
        "acf": {"summary": "Grants for education projects.",
                "deadline": "2027-08-31T23:59:59"},
    },
]


def _src(key: str, **kw):
    base = {"id": f"src-{key}", "key": key, "name": key,
            "enabled": True, "source_type": "api",
            "base_url": "https://example.org", "auto_paused": False,
            "consecutive_empty_runs": 0}
    base.update(kw)
    return base


def _run(status="success", age_h=1, **kw):
    ts = NOW - timedelta(hours=age_h)
    base = {"id": f"r-{age_h}-{status}", "status": status,
            "started_at": ts, "finished_at": ts,
            "items_found": 2, "items_created": 2, "items_updated": 0,
            "items_failed": 0, "error_message": None, "logs": []}
    base.update(kw)
    return base


def _opp_from_candidate(cand, source_id: str, idx: int) -> dict:
    return {"id": f"o-{idx}", "source_id": source_id,
            "external_id": f"ext-{idx}",
            "title": cand.title, "entity": cand.entity,
            "status": "open", "official_url": cand.official_url,
            "summary": cand.summary,
            "close_date": FUTURE}


def _guard_no_fetch(monkeypatch, module_attr: str):
    """Hace que `fetch` explote si el test tocara red por error."""
    from unittest.mock import AsyncMock

    async def _boom(self):  # pragma: no cover
        raise AssertionError(f"red tocada via {module_attr}.fetch")
    monkeypatch.setattr(module_attr + ".fetch", _boom)


# ── ASCUN real ───────────────────────────────────────────────────────

class TestAuditorVsAscunReal:
    @pytest.mark.asyncio
    async def test_ascun_sano_clasifica_y_no_muta(self, monkeypatch):
        from app.connectors.ascun import AscunConnector

        _guard_no_fetch(monkeypatch, "app.connectors.ascun.AscunConnector")
        connector = AscunConnector()
        raw = RawSourceResult(
            source_key="ascun-convocatorias",
            url="https://ascun.org.co/wp-json/wp/v2/posts?search=convocatoria",
            content=json.dumps(ASCUN_PAYLOAD),
            content_type="application/json")

        before = copy.deepcopy(ASCUN_PAYLOAD)
        candidates = await connector.parse(raw)
        assert len(candidates) == 2
        validations = [await connector.validate(c) for c in candidates]
        assert all(v.ok for v in validations)
        assert json.loads(raw.content) == before  # parse no muta el raw
        assert ASCUN_PAYLOAD == before

        source = _src("ascun-convocatorias")
        runs = [_run(age_h=h) for h in (1, 2, 3)]
        opps = [_opp_from_candidate(c, source["id"], i)
                for i, c in enumerate(candidates)]
        frozen = (copy.deepcopy(source), copy.deepcopy(runs),
                  copy.deepcopy(opps))
        res = audit_source(source, runs, opps)
        assert (source, runs, opps) == frozen  # auditor no muta
        assert res.verdict == Verdict.OPERATIVA
        assert res.checks["conectividad"].status == CheckStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_ascun_basura_clasifica_sin_caer(self, monkeypatch):
        from app.connectors.ascun import AscunConnector

        _guard_no_fetch(monkeypatch, "app.connectors.ascun.AscunConnector")
        raw = RawSourceResult(
            source_key="ascun-convocatorias",
            url="https://ascun.org.co/wp-json/wp/v2/posts",
            content="<html>no es json</html>", content_type="text/html")
        candidates = await AscunConnector().parse(raw)
        assert candidates == []
        res = audit_source(_src("ascun-convocatorias"), [_run()], [])
        assert res.verdict != Verdict.OPERATIVA


# ── RSS generico real ────────────────────────────────────────────────

class TestAuditorVsRssReal:
    @pytest.mark.asyncio
    async def test_rss_sano_clasifica_y_no_muta(self, monkeypatch):
        from app.connectors.rss import RssConnector

        _guard_no_fetch(monkeypatch, "app.connectors.rss.RssConnector")
        connector = RssConnector("demo-rss", "https://example.org/grants.xml")
        raw = RawSourceResult(source_key="demo-rss",
                              url="https://example.org/grants.xml",
                              content=RSS_FEED,
                              content_type="application/rss+xml")
        snapshot = raw.content
        candidates = await connector.parse(raw)
        assert len(candidates) == 2
        validations = [await connector.validate(c) for c in candidates]
        assert all(v.ok for v in validations)
        assert raw.content == snapshot

        source = _src("demo-rss", source_type="rss")
        runs = [_run(age_h=h) for h in (1, 2, 3)]
        opps = [_opp_from_candidate(c, source["id"], i)
                for i, c in enumerate(candidates)]
        frozen = (copy.deepcopy(source), copy.deepcopy(runs),
                  copy.deepcopy(opps))
        res = audit_source(source, runs, opps)
        assert (source, runs, opps) == frozen
        assert res.verdict == Verdict.OPERATIVA

    @pytest.mark.asyncio
    async def test_rss_vencido_falla_fechas(self, monkeypatch):
        from app.connectors.rss import RssConnector

        _guard_no_fetch(monkeypatch, "app.connectors.rss.RssConnector")
        connector = RssConnector("demo-rss", "https://example.org/grants.xml")
        raw = RawSourceResult(source_key="demo-rss",
                              url="https://example.org/grants.xml",
                              content=RSS_FEED,
                              content_type="application/rss+xml")
        candidates = await connector.parse(raw)
        source = _src("demo-rss", source_type="rss")
        runs = [_run(age_h=h) for h in (1, 2, 3)]
        opps = [_opp_from_candidate(c, source["id"], i)
                for i, c in enumerate(candidates)]
        opps[0]["close_date"] = (NOW - timedelta(days=3)).isoformat()
        res = audit_source(source, runs, opps)
        assert res.checks["fechas"].status == CheckStatus.FAIL


# ── WordPress generico real ──────────────────────────────────────────

class TestAuditorVsWordpressReal:
    @pytest.mark.asyncio
    async def test_wordpress_sano_clasifica_y_no_muta(self, monkeypatch):
        from app.connectors.wordpress_grants import WordPressGrantsConnector

        _guard_no_fetch(
            monkeypatch,
            "app.connectors.wordpress_grants.WordPressGrantsConnector")
        connector = WordPressGrantsConnector(
            "novo-nordisk-grants", "https://novonordiskfonden.dk/wp-json/",
            entity_name="Novo Nordisk Foundation",
            default_country="Denmark",
            allowed_domains=["novonordiskfonden.dk"])
        raw = RawSourceResult(
            source_key="novo-nordisk-grants",
            url="https://novonordiskfonden.dk/wp-json/wp/v2/grants",
            content=json.dumps(WORDPRESS_PAYLOAD),
            content_type="application/json")
        before = copy.deepcopy(WORDPRESS_PAYLOAD)
        candidates = await connector.parse(raw)
        assert len(candidates) == 2
        validations = [await connector.validate(c) for c in candidates]
        assert all(v.ok for v in validations)
        assert WORDPRESS_PAYLOAD == before

        source = _src("novo-nordisk-grants")
        runs = [_run(age_h=h) for h in (1, 2, 3)]
        opps = [_opp_from_candidate(c, source["id"], i)
                for i, c in enumerate(candidates)]
        frozen = (copy.deepcopy(source), copy.deepcopy(runs),
                  copy.deepcopy(opps))
        res = audit_source(source, runs, opps)
        assert (source, runs, opps) == frozen
        assert res.verdict == Verdict.OPERATIVA


# ── Factory en memoria (sin red) ─────────────────────────────────────

class TestAuditorConnectorFactory:
    def test_factory_resuelve_sin_red(self):
        from app.connectors.ascun import AscunConnector
        from app.connectors.factory import connector_for
        from app.connectors.rss import RssConnector

        ascun = connector_for("ascun-convocatorias")
        assert isinstance(ascun, AscunConnector)
        rss = connector_for("demo-rss", "https://example.org/x.xml",
                            source_type="rss")
        assert isinstance(rss, RssConnector)
