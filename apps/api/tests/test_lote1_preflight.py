"""Lote 1 preflight (issue #59): L1 transporte + 1-GET reutilizado.

TDD: estos tests definen el contrato exigido. Cero red real, cero DB.
Stubs en memoria unicamente. Conservar los 54 previos verdes.
"""

from __future__ import annotations

import asyncio

from app.audit.cli import main as cli_main
from app.audit.live_probe import (
    classify_http,
    default_resolve,
    extract_titles,
    run_live_probe,
)

PUB = "https://public.example/feed"


def _ok_transport(body: str, status: int = 200, headers: dict | None = None):
    async def transport(url, timeout_s):
        return {"status": status, "headers": headers or {},
                "body": body, "latency_ms": 9}
    return transport


def _rss_titles(n: int) -> str:
    items = "".join(f"<item><title>Convocatoria {i}</title></item>" for i in range(n))
    return f"<rss><channel>{items}</channel></rss>"


# ── dry-run: 0 requests por construccion ─────────────────────────────

def test_cli_dry_run_makes_zero_requests(tmp_path, monkeypatch):
    import httpx
    def _boom(*a, **k):
        raise AssertionError("dry-run no debe construir transporte/cliente HTTP")
    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    rc = cli_main(["--mode", "live-probe", "--source-key", "grants-gov-forecast",
                   "--dry-run", "--output", str(tmp_path)])
    assert rc == 0
    plan_file = tmp_path / "live-probe-plan.json"
    assert plan_file.exists()


def test_cli_live_probe_requires_source_key(tmp_path):
    rc = cli_main(["--mode", "live-probe", "--allow-network",
                   "--output", str(tmp_path)])
    assert rc == 2


# ── 1 GET reutilizado: conectividad + parse + titulos + metricas ─────

def test_single_get_reused_for_titles_and_metrics():
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport(_rss_titles(12)),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert outcome.requests_made == 1
    assert outcome.status == "live_ok"
    assert len(outcome.evidence["titles_sample"]) == 10
    assert outcome.evidence["titles_count"] == 12
    assert outcome.evidence["bytes_received"] > 0


def test_extract_titles_wp_json_and_html():
    wp = ('[{"title": {"rendered": "Grant A"}}, '
          '{"title": {"rendered": "Grant B"}}]')
    assert extract_titles(wp, "application/json") == ["Grant A", "Grant B"]
    html = ("<html><body><article><h2>Convocatoria X</h2></article>"
            "<h2>Beca Y</h2></body></html>")
    titles = extract_titles(html, "text/html")
    assert "Convocatoria X" in titles and "Beca Y" in titles


# ── STOP: WAF aunque sea 200 ─────────────────────────────────────────

def test_200_with_challenge_body_is_blocked():
    status, _, review = classify_http(
        200, None, body="<html>challenge: verify you are a robot captcha</html>")
    assert status == "live_blocked"
    assert review is True


def test_200_challenge_via_probe_is_blocked():
    outcome = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport("<html>cloudflare challenge captcha</html>"),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert outcome.status == "live_blocked"
    assert outcome.requests_made == 1
    assert outcome.pending_manual_review is True


# ── STOP: resto de la matriz ─────────────────────────────────────────

def test_403_stops_blocked():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport("denied", status=403),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_blocked" and out.requests_made == 1


def test_429_is_transient_never_dead():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport("slow", status=429,
                                headers={"retry-after": "30"}),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_transient"
    assert out.evidence["retry_after_s"] == 30


def test_404_is_dead():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport("no", status=404),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_dead"


def test_timeout_is_transient():
    async def transport(url, timeout_s):
        raise TimeoutError("se acabo el tiempo simulado")
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_transient" and out.requests_made == 1


def test_redirect_cross_host_stops_without_following():
    seen: list[str] = []
    async def transport(url, timeout_s):
        seen.append(url)
        return {"status": 301, "headers": {"location": "https://other.example/x"},
                "body": "", "latency_ms": 1}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy"
    assert seen == [PUB]


def test_redirect_same_host_is_followed_within_budget():
    async def transport(url, timeout_s):
        if url.endswith("/feed"):
            return {"status": 302,
                    "headers": {"location": "https://public.example/final"},
                    "body": "", "latency_ms": 1}
        return {"status": 200, "headers": {},
                "body": _rss_titles(3), "latency_ms": 2}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_dns_private_ip_blocks_before_request():
    async def transport(url, timeout_s):
        raise AssertionError("no debe pedir si el DNS resuelve a privada")
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"], resolve=lambda h: ["10.9.9.9"]))
    assert out.status == "blocked_by_policy" and out.requests_made == 0


def test_authorized_hosts_required():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport("x"),
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy"
    assert out.requests_made == 0


def test_dns_always_resolved_no_silent_skip(monkeypatch):
    import app.audit.live_probe as lp
    monkeypatch.setattr(lp, "default_resolve", lambda host: ["10.9.9.9"])
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport("x"),
        authorized_hosts=["public.example"]))
    assert out.status == "blocked_by_policy"
    assert out.requests_made == 0


def test_default_resolve_returns_ips():
    ips = default_resolve("localhost")
    assert isinstance(ips, list) and ips  # 127.0.0.1 / ::1, sin red externa


# ── politica de URL: credenciales / http plano / puerto no estandar ──

def test_url_with_credentials_rejected():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://user:secret@public.example/feed"],
        transport=_ok_transport("x"),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy" and out.requests_made == 0


def test_plain_http_rejected():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=["http://public.example/feed"],
        transport=_ok_transport("x"),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy" and out.requests_made == 0


def test_nonstandard_port_rejected():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://public.example:8443/feed"],
        transport=_ok_transport("x"),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy" and out.requests_made == 0


# ── tamanio verificado ANTES de completar + limite global ────────────

def test_oversize_body_flagged_and_stopped():
    from app.audit.live_probe import PROBE_BUDGET_DEFAULTS
    big = "y" * (PROBE_BUDGET_DEFAULTS["max_bytes_per_page"] + 100)
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_ok_transport(big),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.bytes_truncated is True
    assert out.requests_made == 1


def test_body_too_large_stream_abort_is_over_budget():
    from app.audit.live_probe import BodyTooLargeError
    async def transport(url, timeout_s):
        raise BodyTooLargeError(2_000_001)
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "over_budget"
    assert out.pending_manual_review is True


def test_global_request_limit_stops():
    async def transport(url, timeout_s):
        return {"status": 302,
                "headers": {"location": "https://public.example/n1"},
                "body": "", "latency_ms": 1}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://public.example/p0"], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"], max_requests=1))
    assert out.status == "over_budget" and out.requests_made == 1
