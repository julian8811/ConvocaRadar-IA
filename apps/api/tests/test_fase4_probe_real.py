"""Fase 4 (issue #58): F1 precision historica, F2 probe real opt-in, F3 seguridad offline.

TDD RED: estos tests definen el contrato exigido. Cero red, cero DB, cero mutaciones.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.history import audit_source, meets_live_certification
from app.audit.types import CheckStatus, Verdict

NOW = datetime.now(UTC).replace(tzinfo=None)


def _src(**kw):
    base = {
        "id": "s1", "key": "test-source", "name": "Test Source", "enabled": True,
        "source_type": "html", "base_url": "https://example.com/convocatorias",
        "auto_paused": False, "consecutive_empty_runs": 0,
    }
    base.update(kw)
    return base


def _run(status="success", age_h=1, **kw):
    ts = NOW - timedelta(hours=age_h)
    base = {
        "id": f"r-{age_h}-{status}", "status": status,
        "started_at": ts, "finished_at": ts,
        "items_found": 5, "items_created": 5, "items_updated": 0,
        "items_failed": 0, "error_message": None, "logs": [],
    }
    base.update(kw)
    return base


def _opp(**kw):
    base = {
        "id": "o1", "source_id": "s1", "external_id": "ext-1",
        "title": "Convocatoria de investigacion 2026", "entity": "Entidad X",
        "status": "open", "official_url": "https://example.com/conv/1",
        "close_date": (NOW + timedelta(days=30)).isoformat(),
    }
    base.update(kw)
    return base


def _qlogs(n):
    return [{"level": "quarantine", "reason": "ruido", "title": f"n{i}"} for i in range(n)]


def _healthy(n_runs=3, n_opps=5):
    runs = [_run(status="success", age_h=h) for h in range(1, n_runs + 1)]
    opps = [_opp(id=f"o{i}", external_id=f"e{i}", title=f"Convocatoria {i} tema {i}",
                 official_url=f"https://example.com/conv/{i}") for i in range(n_opps)]
    return runs, opps


# ── F1: cuarentena por-run ────────────────────────────────────────────

def test_quarantine_sum_60_40_is_not_censored():
    runs = [_run(age_h=1, logs=_qlogs(60)), _run(age_h=2, logs=_qlogs(40))]
    res = audit_source(_src(), runs, [_opp()])
    c = res.checks["persistencia"].evidence.counters
    assert c["quarantine_censored"] is False
    assert c["quarantine_max_per_run"] == 60
    assert c["quarantine_per_run"] == [60, 40]


def test_quarantine_single_run_100_is_censored():
    res = audit_source(_src(), [_run(logs=_qlogs(100))], [_opp()])
    c = res.checks["persistencia"].evidence.counters
    assert c["quarantine_censored"] is True
    assert c["quarantine_max_per_run"] == 100


def test_quarantine_per_run_counts_visible():
    runs = [_run(age_h=1, logs=_qlogs(10)), _run(age_h=2, logs=_qlogs(3))]
    res = audit_source(_src(), runs, [_opp()])
    c = res.checks["persistencia"].evidence.counters
    assert c["quarantine_per_run"] == [10, 3]
    assert c["quarantine_max_per_run"] == 10
    assert c["quarantine_censored"] is False


# ── F1: certificacion viva separada ───────────────────────────────────

def test_historical_operativa_is_never_live_certified():
    runs, opps = _healthy()
    res = audit_source(_src(), runs, opps)
    assert res.verdict == Verdict.OPERATIVA
    assert res.verification_scope == "historical_only"
    assert res.live_certified is False


def test_conectividad_unknown_gives_historical_operativa_but_never_live():
    runs, opps = _healthy()
    res = audit_source(_src(), runs, opps)
    assert res.checks["conectividad"].status == CheckStatus.UNKNOWN
    assert res.verdict == Verdict.OPERATIVA  # historico: permitido
    assert meets_live_certification(res) is False  # viva: nunca


def test_live_certification_criteria_exact():
    from app.audit.history import LIVE_CERTIFICATION_CRITERIA
    assert LIVE_CERTIFICATION_CRITERIA["requires_live_conectividad_pass"] is True
    assert LIVE_CERTIFICATION_CRITERIA["requires_scope_live_checked"] is True
    assert "extraccion" in LIVE_CERTIFICATION_CRITERIA["requires_pass"]
    # Nada historico preexistente puede certificar: sin retro-certificacion.
    runs, opps = _healthy()
    res = audit_source(_src(), runs, opps)
    assert meets_live_certification(res) is False


# ── F2/F3: probe real opt-in + seguridad offline ──────────────────────

from app.audit.live_probe import (  # noqa: E402
    PROBE_BUDGET_DEFAULTS,
    adapt_connector,
    build_dry_run_plan,
    classify_http,
    ip_is_private,
    is_prohibited_host,
    run_live_probe,
    sanitize_url,
)


def test_no_requests_on_import_or_by_default():
    # Sin flags: el probe se niega sin tocar red (transport=None => sin sockets).
    outcome = asyncio.run(run_live_probe("ascun-convocatorias"))
    assert outcome.status == "refused_missing_flags"
    assert outcome.requests_made == 0


def test_dry_run_plan_zero_network():
    plan = build_dry_run_plan("ascun-convocatorias",
                              ["https://ascun.org.co/wp-json/wp/v2/posts?search=convocatoria"])
    assert plan["estimated_requests"] >= 1
    assert "ascun.org.co" in plan["hosts"]
    assert plan["risks"], "el plan debe listar riesgos"
    assert plan["network_used"] is False


def test_ssrf_private_hosts_blocked():
    for host in ("localhost", "127.0.0.1", "10.0.0.5", "192.168.1.1",
                 "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1"):
        assert is_prohibited_host(host) is True, host
    assert is_prohibited_host("ascun.org.co") is False


def test_private_ips_blocked():
    assert ip_is_private("127.0.0.1") is True
    assert ip_is_private("10.1.2.3") is True
    assert ip_is_private("192.168.0.1") is True
    assert ip_is_private("8.8.8.8") is False


def test_redirect_to_private_is_blocked_by_policy():
    async def transport(url, timeout_s):
        if "public.example" in url:
            return {"status": 301, "headers": {"location": "http://169.254.169.254/meta"},
                    "body": "", "latency_ms": 5}
        raise AssertionError(f"no debe seguir redirect a privado: {url}")
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=["https://public.example/feed"],
        transport=transport, authorized_hosts=["public.example"]))
    assert outcome.status == "blocked_by_policy"
    assert outcome.requests_made == 1


def test_redirect_cross_host_unauthorized_stops():
    async def transport(url, timeout_s):
        return {"status": 302, "headers": {"location": "https://evil.example/x"},
                "body": "", "latency_ms": 5}
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=["https://public.example/feed"],
        transport=transport, authorized_hosts=["public.example"]))
    assert outcome.status == "blocked_by_policy"


def test_dns_private_ip_blocked():
    async def transport(url, timeout_s):
        raise AssertionError("no debe pedir si el DNS resuelve a privada")
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=["https://public.example/feed"],
        transport=transport, authorized_hosts=["public.example"],
        resolve=lambda host: ["10.9.9.9"]))
    assert outcome.status == "blocked_by_policy"
    assert outcome.requests_made == 0


def test_429_with_retry_after_is_transient():
    status, ttl, review = classify_http(429, None, retry_after_s=30)
    assert status == "live_transient"
    assert review is True  # backoff + revision


def test_timeout_is_transient_not_dead():
    status, ttl, review = classify_http(None, "timeout")
    assert status == "live_transient"


def test_404_is_dead_with_negative_ttl():
    status, ttl, review = classify_http(404, None)
    assert status == "live_dead"


def test_403_stops_with_manual_review():
    status, ttl, review = classify_http(403, "captcha detectado")
    assert status == "live_blocked"
    assert review is True


def test_200_ok_positive_ttl_differs_from_negative():
    s_ok, ttl_ok, _ = classify_http(200, None)
    s_dead, ttl_dead, _ = classify_http(404, None)
    assert s_ok == "live_ok"
    assert ttl_ok != ttl_dead and ttl_ok > ttl_dead


def test_oversize_response_truncated_and_flagged():
    big = "x" * (PROBE_BUDGET_DEFAULTS["max_bytes_per_page"] + 1000)
    async def transport(url, timeout_s):
        return {"status": 200, "headers": {}, "body": big, "latency_ms": 5}
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=["https://public.example/feed"],
        transport=transport, authorized_hosts=["public.example"]))
    assert outcome.bytes_truncated is True
    assert outcome.requests_made == 1


def test_over_budget_stops_with_error():
    async def transport(url, timeout_s):
        return {"status": 301, "headers": {"location": url + "/next"},
                "body": "", "latency_ms": 1}
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://public.example/p0"],
        transport=transport, authorized_hosts=["public.example"],
        max_requests=3))
    assert outcome.status == "over_budget"
    assert outcome.requests_made == 3


def test_budgets_are_auditable_and_bounded():
    b = PROBE_BUDGET_DEFAULTS
    assert b["max_requests_per_source"] <= 10
    assert b["timeout_s"] <= 15
    assert b["total_budget_s"] <= 60
    assert b["max_concurrency_global"] <= 2
    assert b["max_concurrency_per_host"] <= 1


def test_wordpress_paginated_plan_counts_pages():
    plan = build_dry_run_plan("wp-demo", [
        "https://public.example/wp-json/wp/v2/posts?per_page=20&page=1",
        "https://public.example/wp-json/wp/v2/posts?per_page=20&page=2"])
    assert plan["estimated_requests"] == 2


def test_rss_single_fetch_ok_with_stub():
    async def transport(url, timeout_s):
        return {"status": 200,
                "headers": {"content-type": "application/rss+xml"},
                "body": "<rss><channel><item><title>x</title></item></channel></rss>",
                "latency_ms": 12}
    outcome = asyncio.run(run_live_probe(
        "generic-rss-sample", allow_network=True,
        start_urls=["https://public.example/feed.xml"],
        transport=transport, authorized_hosts=["public.example"]))
    assert outcome.status == "live_ok"
    assert outcome.evidence["requests_made"] == 1
    assert outcome.evidence["urls"][0].startswith("https://public.example/")
    assert "policy" in outcome.evidence


def test_ascun_dry_run_plan_shape():
    plan = build_dry_run_plan("ascun-convocatorias",
                              ["https://ascun.org.co/wp-json/wp/v2/posts?search=convocatoria"])
    assert plan["source_key"] == "ascun-convocatorias"
    assert plan["estimated_requests"] <= 10
    assert plan["network_used"] is False


def test_non_instrumentable_connector_is_safe_error():
    class LegacyConnector:
        source_key = "legacy-demo"
        async def fetch(self):
            return object()  # hace red sin control granular
    adapter = adapt_connector(LegacyConnector())
    assert adapter.instrumented is False
    outcome = asyncio.run(adapter.run(allow_network=True, transport=None))
    assert outcome.status == "blocked_by_policy"


def test_evidence_has_source_duration_sanitized_urls_and_policy():
    async def transport(url, timeout_s):
        return {"status": 200, "headers": {},
                "body": "<html>ok</html>?token=SECRET-should-not-appear",
                "latency_ms": 20}
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://public.example/conv?token=SECRET-should-not-appear"],
        transport=transport, authorized_hosts=["public.example"]))
    ev = outcome.evidence
    assert ev["source_key"] == "demo"
    assert ev["duration_ms"] >= 0
    assert all("SECRET" not in u for u in ev["urls"])
    assert ev["policy"]["max_requests_per_source"] <= 10
    assert "pending_manual_review" in ev


def test_no_db_mutations_json_roundtrip(tmp_path):
    runs, opps = _healthy()
    before = json.dumps({"runs": len(runs), "opps": len(opps)}, sort_keys=True)
    res = audit_source(_src(), runs, opps)
    res.model_dump(mode="json")
    after = json.dumps({"runs": len(runs), "opps": len(opps)}, sort_keys=True)
    assert before == after
    assert len(runs) == 3 and len(opps) == 5  # entradas intactas, sin fusion
