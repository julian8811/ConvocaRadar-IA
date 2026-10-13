"""Lote 1 preflight (issue #59): L1 transporte + 1-GET reutilizado.

TDD: estos tests definen el contrato exigido. Cero red real, cero DB.
Stubs en memoria unicamente. Conservar los 54 previos verdes.
"""

from __future__ import annotations

import asyncio

from app.audit import live_probe
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


# ── R-A: redirects mismo-dueño (issue remediacion-post-certificacion) ──
# Cero red: stubs en memoria. Origenes tomados del seed (app/db/seed.py).

RSS_1 = "<rss><channel><item><title>Convocatoria T</title></item></channel></rss>"


def _chain_transport(route: dict[str, str], final_body: str = RSS_1):
    """Stub: URLs en `route` responden 302 a su destino; el resto 200."""
    async def transport(url, timeout_s):
        if url in route:
            return {"status": 302, "headers": {"location": route[url]},
                    "body": "", "latency_ms": 1}
        return {"status": 200, "headers": {}, "body": final_body,
                "latency_ms": 2}
    return transport


def test_same_owner_registrable_detected():
    assert live_probe.same_owner_reason(
        "www.uniandes.edu.co", "uniandes.edu.co") is not None


def test_same_owner_subdomain_detected():
    assert live_probe.same_owner_reason(
        "www.sena.edu.co", "betowa.sena.edu.co") is not None


def test_same_owner_explicit_mapping_conahcyt_secihti():
    assert live_probe.same_owner_reason("conahcyt.mx", "secihti.mx") is not None


def test_same_owner_explicit_mapping_mozilla():
    assert live_probe.same_owner_reason(
        "mozilla.org", "mozillafoundation.org") is not None


def test_same_owner_explicit_mapping_colombiaproductiva_innpulsa():
    assert live_probe.same_owner_reason(
        "www.colombiaproductiva.com",
        "convocatorias.innpulsacolombia.com") is not None


def test_same_owner_explicit_mapping_proinnovate_cdn_gobpe():
    assert live_probe.same_owner_reason(
        "calendario.proinnovate.gob.pe", "cdn.gob.pe") is not None


def test_same_owner_external_returns_none():
    assert live_probe.same_owner_reason(
        "public.example", "evil.com") is None


def test_same_owner_shared_tenant_drive_returns_none():
    assert live_probe.same_owner_reason(
        "www.procolombia.co", "drive.google.com") is None


def test_redirect_same_registrable_followed_uniandes_style():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.uniandes.edu.co/sitemap.xml"],
        transport=_chain_transport(
            {"https://www.uniandes.edu.co/sitemap.xml":
             "https://uniandes.edu.co/sitemap.xml"}),
        authorized_hosts=["www.uniandes.edu.co"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_redirect_subdomain_followed_sena_style():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.sena.edu.co/convocatorias"],
        transport=_chain_transport(
            {"https://www.sena.edu.co/convocatorias":
             "https://betowa.sena.edu.co/oferta"}),
        authorized_hosts=["www.sena.edu.co"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_redirect_explicit_mapping_followed_conahcyt_secihti():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://conahcyt.mx/convocatorias/"],
        transport=_chain_transport(
            {"https://conahcyt.mx/convocatorias/":
             "https://secihti.mx/convocatorias/"}),
        authorized_hosts=["conahcyt.mx"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_redirect_explicit_mapping_followed_mozilla():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://mozilla.org/fellowships"],
        transport=_chain_transport(
            {"https://mozilla.org/fellowships":
             "https://mozillafoundation.org/fellowships"}),
        authorized_hosts=["mozilla.org"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_redirect_explicit_mapping_followed_innpulsa():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.colombiaproductiva.com/convocatorias"],
        transport=_chain_transport(
            {"https://www.colombiaproductiva.com/convocatorias":
             "https://convocatorias.innpulsacolombia.com/api/convocatorias"}),
        authorized_hosts=["www.colombiaproductiva.com"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_redirect_external_still_blocked():
    seen: list[str] = []

    async def transport(url, timeout_s):
        seen.append(url)
        return {"status": 302, "headers": {"location": "https://evil.com/x"},
                "body": "", "latency_ms": 1}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy"
    assert seen == [PUB]


def test_redirect_private_ip_literal_blocked():
    seen: list[str] = []

    async def transport(url, timeout_s):
        seen.append(url)
        return {"status": 302, "headers": {"location": "https://10.0.0.9/admin"},
                "body": "", "latency_ms": 1}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB], transport=transport,
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy"
    assert seen == [PUB]


def test_redirect_shared_tenant_drive_blocked():
    seen: list[str] = []

    async def transport(url, timeout_s):
        seen.append(url)
        return {"status": 302, "headers": {
            "location": "https://drive.google.com/drive/folders/xyz"},
            "body": "", "latency_ms": 1}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.procolombia.co/convocatorias"],
        transport=transport,
        authorized_hosts=["www.procolombia.co"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "blocked_by_policy"
    assert len(seen) == 1


def test_redirect_chain_over_limit_is_over_budget():
    base = "https://public.example"
    route = {f"{base}/p{i}": f"{base}/p{i + 1}" for i in range(5)}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[f"{base}/p0"],
        transport=_chain_transport(route),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "over_budget"
    assert out.requests_made == 4  # 1 inicial + 3 redirects (tope max_redirects)


def test_redirect_target_dns_revalidated_per_hop():
    def resolve(host):
        if host == "uniandes.edu.co":
            return ["10.9.9.9"]  # el destino se volvio privado: STOP
        return ["93.184.216.34"]
    seen: list[str] = []

    async def transport(url, timeout_s):
        seen.append(url)
        if url == "https://www.uniandes.edu.co/sitemap.xml":
            return {"status": 302,
                    "headers": {"location": "https://uniandes.edu.co/sitemap.xml"},
                    "body": "", "latency_ms": 1}
        raise AssertionError(f"no debe pedir al destino con DNS privada: {url}")
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.uniandes.edu.co/sitemap.xml"],
        transport=transport,
        authorized_hosts=["www.uniandes.edu.co"], resolve=resolve))
    assert out.status == "blocked_by_policy"
    assert seen == ["https://www.uniandes.edu.co/sitemap.xml"]


def test_redirect_relative_location_followed():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[PUB],
        transport=_chain_transport({PUB: "/final"}),
        authorized_hosts=["public.example"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


# ── Post re-probe 2026-10-12 (stubs, cero red) ───────────────────────
# Pares reales observados: proinnovate -> cdn.www.gob.pe (registrable
# www.gob.pe) y mfat.govt.nz -> www.nzscholarships.govt.nz.

def test_same_owner_proinnovate_real_cdn_www_gob_pe():
    assert live_probe.same_owner_reason(
        "calendario.proinnovate.gob.pe", "cdn.www.gob.pe") is not None


def test_same_owner_nz_mfat_scholarships():
    assert live_probe.same_owner_reason(
        "www.mfat.govt.nz", "www.nzscholarships.govt.nz") is not None


def test_redirect_followed_proinnovate_real_cdn():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://calendario.proinnovate.gob.pe/"],
        transport=_chain_transport(
            {"https://calendario.proinnovate.gob.pe/":
             "https://cdn.www.gob.pe/portal/"}),
        authorized_hosts=["calendario.proinnovate.gob.pe"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_redirect_followed_nz_scholarships():
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.mfat.govt.nz/scholarships"],
        transport=_chain_transport(
            {"https://www.mfat.govt.nz/scholarships":
             "https://www.nzscholarships.govt.nz/scholarships"}),
        authorized_hosts=["www.mfat.govt.nz"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2


def test_explicit_allowlist_beats_shared_tenant_veto_drive():
    """Pin decision procolombia: veto multi-tenant solo rige inferencia.

    `drive.google.com` en `authorized_hosts` (allowlist explicita del
    seed) => "host autorizado", se sigue. 0 titulos (pagina Drive JS) es
    PERTINENCIA para revision humana, no bloqueo de politica.
    """
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True,
        start_urls=["https://www.procolombia.co/convocatorias-exportaciones"],
        transport=_chain_transport(
            {"https://www.procolombia.co/convocatorias-exportaciones":
             "https://drive.google.com/drive/folders/xyz"},
            final_body="<html><body><script>drive js</script></body></html>"),
        authorized_hosts=["www.procolombia.co", "drive.google.com"],
        resolve=lambda h: ["93.184.216.34"]))
    assert out.status == "live_ok" and out.requests_made == 2
    assert out.evidence["titles_count"] == 0
    assert out.evidence["redirect_chain"][0]["reason"] == "host autorizado"


def test_over_budget_includes_redirect_chain_rebuilt_from_urls():
    """Pin gap re-probe: cadenas > cap (mintic-style) sin subir el cap.

    `over_budget` por presupuesto agotado debe incluir `redirect_chain`
    (saltos verificados + siguiente salto pendiente no seguido).
    """
    u1 = "https://www.mintic.gov.co/portal/inicio/Convocatorias/"
    u2 = "https://www.mintic.gov.co/portal/715/w3-propertyvalue-111099.html"
    u3 = "https://www.mintic.gov.co/portal/715/otro.html"

    async def transport(url, timeout_s):
        if url == u1:
            return {"status": 302, "headers": {"location": u2},
                    "body": "", "latency_ms": 1}
        return {"status": 302, "headers": {"location": u3},
                "body": "", "latency_ms": 1}
    out = asyncio.run(run_live_probe(
        "demo", allow_network=True, start_urls=[u1], transport=transport,
        authorized_hosts=["www.mintic.gov.co"],
        resolve=lambda h: ["93.184.216.34"], max_requests=2))
    assert out.status == "over_budget" and out.requests_made == 2
    chain = out.evidence["redirect_chain"]
    assert [(c["from"], c["to"]) for c in chain] == [(u1, u2), (u2, u3)]
    assert chain[0]["reason"] == "host autorizado"
    assert "presupuesto agotado" in chain[1]["reason"]
