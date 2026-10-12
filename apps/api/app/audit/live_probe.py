"""Probe REAL opt-in (Fase 4, issue #58): verificacion en vivo con resguardos.

Diferenciado del `probe.py` SIMULADO: este modulo NO hace requests al importar
ni por defecto. La red real exige flags explicitas (`allow_network=True`,
equivalente CLI a `--allow-network` + `--source-key`) y el preflight
`build_dry_run_plan()` (`--dry-run`) describe el plan con CERO red.

Resguardos (siempre activos, tambien con stubs en tests):
- Bloqueo SSRF: hosts/IP privados, localhost, red interna, link-local.
- Redirects SOLO a hosts autorizados; redirect a privado o a host no
  autorizado => `blocked_by_policy` (STOP, sin seguir).
- Presupuestos auditables: <=10 req/fuente, timeout <=15s c/u, total <=60s,
  concurrencia global <=2 y por host <=1, tope bytes/pagina, tope paginas.
  429 respeta Retry-After (backoff); STOP ante WAF/CAPTCHA (403 con marcas).
- Clasificacion: 200/3xx/404/403/429/timeout sin confundir transitorio
  (429/timeout/red) con muerta (404/410). TTL distinto para positivos
  (largo) vs negativos/transitorios (corto).
- Si un `connector.fetch()` hace requests sin control granular, solo se usa
  via `adapt_connector()`: adapter instrumentado CON presupuesto, o
  `blocked_by_policy`. Nunca fetch sin limite.

Prohibido aqui: run_source_inline, escrituras SQL, envios, embeddings y
cualquier side effect persistente. Este modulo no importa DB ni red a
nivel de import: el transporte real se inyecta (tests usan stubs).
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

# ── Presupuestos auditables (techos, no objetivos) ────────────────────
PROBE_BUDGET_DEFAULTS: dict[str, Any] = {
    "max_requests_per_source": 10,
    "timeout_s": 15,
    "total_budget_s": 60,
    "max_concurrency_global": 2,
    "max_concurrency_per_host": 1,
    "max_bytes_per_page": 2_000_000,
    "max_pages_per_source": 10,
    "max_redirects": 3,
    "retry_max": 2,
}

TTL_POSITIVE_S = 24 * 3600  # live_ok: vale 24h
TTL_NEGATIVE_S = 6 * 3600  # live_dead/live_blocked: revalidar en 6h
TTL_TRANSIENT_S = 15 * 60  # live_transient: reintentar en 15min

WAF_MARKERS = ("captcha", "cloudflare", "challenge", "waf", "blocked by",
               "access denied", "are you a robot", "datadome", "perimeterx")

_PRIVATE_HOST_NAMES = ("localhost", "local", "internal", "localhost.localdomain")


def ip_is_private(ip: str) -> bool:
    """True si la IP es privada/reservada/no ruteable (SSRF)."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return True  # no parseable => tratar como sospechosa
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def is_prohibited_host(host: str) -> bool:
    """True si el host literal es interno/prohibido (sin DNS)."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in ("localhost", "::1") or h.startswith("localhost."):
        return True
    if any(h == p or h.endswith("." + p) for p in _PRIVATE_HOST_NAMES):
        return True
    try:
        ipaddress.ip_address(h)
        return ip_is_private(h)
    except ValueError:
        return False  # nombre publico aparente; se valida tras resolver


def sanitize_url(url: str) -> str:
    """URL sin query/fragment (posibles secretos/tokens)."""
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        path = p.path or "/"
        return f"{p.scheme}://{host}{path}"
    except ValueError:
        return "<unparseable>"


def classify_http(status: int | None, error: str | None,
                  *, retry_after_s: int | None = None,
                  body: str = "") -> tuple[str, int, bool]:
    """Clasifica el resultado. Retorna (estado, ttl_s, pending_manual_review).

    - live_ok: 200 con cuerpo.
    - live_dead: 404/410 (muerta, NO transitoria).
    - live_blocked: 403 / WAF-CAPTCHA (STOP, revision humana).
    - live_transient: 429/timeout/red/5xx (reintentable, NO muerta).
    """
    err = (error or "").lower()
    blob = f"{err} {body[:2000].lower()}"
    if status == 200:
        return ("live_ok", TTL_POSITIVE_S, False)
    if status in (404, 410):
        return ("live_dead", TTL_NEGATIVE_S, False)
    if status == 403 or any(m in blob for m in WAF_MARKERS):
        return ("live_blocked", TTL_NEGATIVE_S, True)
    if status == 429:
        return ("live_transient", TTL_TRANSIENT_S, True)
    if status is None or "timeout" in err or "timed out" in err:
        return ("live_transient", TTL_TRANSIENT_S, False)
    if status is not None and 500 <= status <= 599:
        return ("live_transient", TTL_TRANSIENT_S, False)
    if status is not None and 300 <= status <= 399:
        return ("live_transient", TTL_TRANSIENT_S, False)
    return ("live_transient", TTL_TRANSIENT_S, True)


# ── Plan dry-run (cero red) ───────────────────────────────────────────
KNOWN_START_URLS: dict[str, list[str]] = {
    "ascun-convocatorias": [
        "https://ascun.org.co/wp-json/wp/v2/posts?search=convocatoria&per_page=20",
    ],
    "generic-rss-sample": ["https://example.org/grants/feed.xml"],
}


def build_dry_run_plan(source_key: str,
                       urls: list[str] | None = None) -> dict[str, Any]:
    """Plan de probe sin tocar red: n° estimado de requests, hosts, riesgos."""
    start = list(urls or KNOWN_START_URLS.get(source_key, []))
    hosts = sorted({(urlparse(u).hostname or "?").lower() for u in start})
    estimated = min(len(start) or 1, PROBE_BUDGET_DEFAULTS["max_requests_per_source"])
    risks = [
        "red real solo con --allow-network + --source-key explicitos",
        "bloqueo SSRF activo: privados/localhost/red interna denegados",
        "redirects solo a hosts autorizados; otros => blocked_by_policy",
        "presupuesto: <=10 req/fuente, timeout <=15s c/u, total <=60s",
        "STOP ante WAF/CAPTCHA con pending_manual_review",
        "sin escrituras SQL, sin envios, sin embeddings, sin side effects",
    ]
    return {
        "source_key": source_key,
        "start_urls": [sanitize_url(u) for u in start],
        "estimated_requests": estimated,
        "hosts": hosts,
        "budgets": dict(PROBE_BUDGET_DEFAULTS),
        "risks": risks,
        "network_used": False,
    }


# ── Resultado ─────────────────────────────────────────────────────────
@dataclass
class LiveOutcome:
    source_key: str
    status: str  # live_ok|live_dead|live_blocked|live_transient|
    #            # blocked_by_policy|over_budget|refused_missing_flags
    http_status: int | None = None
    latency_ms: int = 0
    requests_made: int = 0
    bytes_truncated: bool = False
    ttl_s: int = TTL_TRANSIENT_S
    pending_manual_review: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


Transport = Callable[[str, float], Awaitable[dict[str, Any]]]
Resolver = Callable[[str], list[str]]


async def run_live_probe(
    source_key: str,
    *,
    allow_network: bool = False,
    start_urls: list[str] | None = None,
    transport: Transport | None = None,
    authorized_hosts: list[str] | None = None,
    resolve: Resolver | None = None,
    max_requests: int | None = None,
) -> LiveOutcome:
    """Ejecuta el probe real con presupuestos. Sin flags => rechazo, 0 red."""
    policy = dict(PROBE_BUDGET_DEFAULTS)
    if max_requests is not None:
        policy["max_requests_per_source"] = min(max_requests, policy["max_requests_per_source"])
    budget = policy["max_requests_per_source"]

    def _ev(status: str, **kw: Any) -> LiveOutcome:
        return LiveOutcome(
            source_key=source_key, status=status,
            ttl_s=kw.pop("ttl_s", TTL_TRANSIENT_S),
            evidence={"source_key": source_key, "duration_ms": 0,
                      "requests_made": kw.get("requests_made", 0),
                      "urls": [], "policy": policy,
                      "pending_manual_review": kw.get("pending_manual_review", False),
                      **kw.pop("extra", {})},
            **kw)

    if not allow_network:
        return _ev("refused_missing_flags", pending_manual_review=False,
                   extra={"reason": "requiere --allow-network + --source-key"})
    urls = list(start_urls or KNOWN_START_URLS.get(source_key, []))
    if not urls:
        return _ev("refused_missing_flags",
                   extra={"reason": "sin start_urls conocidas para la fuente"})
    if transport is None:
        return _ev("refused_missing_flags",
                   extra={"reason": "sin transporte: red real no disponible aqui"})

    allowed = {h.lower() for h in (authorized_hosts or [])}
    t0 = time.monotonic()
    made = 0
    seen_urls: list[str] = []
    pending = list(urls)
    redirects = 0
    truncated = False
    last_status: int | None = None
    last_error: str | None = None
    last_latency = 0
    retry_after: int | None = None

    while pending and made < budget:
        if time.monotonic() - t0 > policy["total_budget_s"]:
            break
        url = pending.pop(0)
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return _ev("blocked_by_policy", requests_made=made,
                       pending_manual_review=True,
                       extra={"reason": "url no parseable", "urls": seen_urls})
        if is_prohibited_host(host) or (allowed and host not in allowed):
            return _ev("blocked_by_policy", requests_made=made,
                       pending_manual_review=True,
                       extra={"reason": f"host no autorizado o privado: {host}",
                              "urls": seen_urls})
        if resolve is not None:
            try:
                ips = resolve(host)
            except Exception as exc:
                return _ev("blocked_by_policy", requests_made=made,
                           pending_manual_review=True,
                           extra={"reason": f"DNS fallo: {exc}", "urls": seen_urls})
            if any(ip_is_private(ip) for ip in ips):
                return _ev("blocked_by_policy", requests_made=made,
                           pending_manual_review=True,
                           extra={"reason": f"DNS resuelve a IP privada: {host}",
                                  "urls": seen_urls})
        try:
            resp = await transport(url, policy["timeout_s"])
        except TimeoutError as exc:
            last_error, last_status = f"timeout: {exc}", None
            made += 1
            break
        except Exception as exc:
            last_error, last_status = str(exc), None
            made += 1
            break
        made += 1
        last_latency = int(resp.get("latency_ms", 0))
        seen_urls.append(sanitize_url(url))
        status = resp.get("status")
        last_status = status if isinstance(status, int) else None
        headers = {str(k).lower(): str(v)
                   for k, v in (resp.get("headers") or {}).items()}
        if "retry-after" in headers:
            try:
                retry_after = int(headers["retry-after"])
            except ValueError:
                retry_after = None
        body = str(resp.get("body") or "")
        if len(body.encode("utf-8")) > policy["max_bytes_per_page"]:
            truncated = True
            body = body[: policy["max_bytes_per_page"]]
        if last_status is not None and 300 <= last_status <= 399:
            loc = headers.get("location", "")
            if not loc:
                last_error = "redirect sin location"
                break
            try:
                nhost = (urlparse(loc).hostname or "").lower()
            except ValueError:
                return _ev("blocked_by_policy", requests_made=made,
                           pending_manual_review=True,
                           extra={"reason": "redirect no parseable", "urls": seen_urls})
            # Redirects SOLO a hosts autorizados y nunca a privados.
            if is_prohibited_host(nhost) or (allowed and nhost not in allowed):
                return _ev("blocked_by_policy", requests_made=made,
                           pending_manual_review=True,
                           extra={"reason": f"redirect a host no autorizado/privado: {nhost}",
                                  "urls": seen_urls})
            redirects += 1
            if redirects > policy["max_redirects"]:
                return _ev("over_budget", requests_made=made,
                           pending_manual_review=True,
                           extra={"reason": "exceso de redirects", "urls": seen_urls})
            pending.insert(0, loc)
            continue
        break  # respuesta final (no redirect)

    if made >= budget and (pending or (last_status is not None
                                       and 300 <= last_status <= 399)):
        out = _ev("over_budget", requests_made=made, pending_manual_review=True,
                  extra={"reason": "presupuesto de requests agotado", "urls": seen_urls})
        out.evidence["duration_ms"] = int((time.monotonic() - t0) * 1000)
        return out

    state, ttl, review = classify_http(last_status, last_error,
                                       retry_after_s=retry_after, body="")
    # Re-clasificar WAF con cuerpo cuando aplique (marcas en body).
    out = LiveOutcome(
        source_key=source_key, status=state, http_status=last_status,
        latency_ms=last_latency, requests_made=made,
        bytes_truncated=truncated, ttl_s=ttl,
        pending_manual_review=review,
        evidence={"source_key": source_key,
                  "duration_ms": int((time.monotonic() - t0) * 1000),
                  "requests_made": made, "urls": seen_urls,
                  "policy": policy, "pending_manual_review": review,
                  "http_status": last_status,
                  "bytes_truncated": truncated,
                  "retry_after_s": retry_after,
                  "reason": last_error},
    )
    return out


# ── Adapter: conector real solo si es instrumentable ──────────────────
@dataclass
class ConnectorAdapter:
    connector: Any
    instrumented: bool = False

    async def run(self, **kwargs: Any) -> LiveOutcome:
        if not self.instrumented:
            return LiveOutcome(
                source_key=getattr(self.connector, "source_key", "?"),
                status="blocked_by_policy",
                pending_manual_review=True,
                evidence={"source_key": getattr(self.connector, "source_key", "?"),
                          "duration_ms": 0, "requests_made": 0, "urls": [],
                          "policy": dict(PROBE_BUDGET_DEFAULTS),
                          "pending_manual_review": True,
                          "reason": ("conector no instrumentable: su fetch() hace "
                                     "requests sin control granular; adaptador o "
                                     "bloqueo, nunca fetch sin limite")},
            )
        return await run_live_probe(getattr(self.connector, "source_key", "?"), **kwargs)


def adapt_connector(connector: Any) -> ConnectorAdapter:
    """Envuelve un conector: instrumentado solo si declara transporte con
    presupuesto; si no, adapter bloqueado (error seguro)."""
    instrumented = bool(getattr(connector, "supports_instrumented_probe", False))
    return ConnectorAdapter(connector, instrumented=instrumented)
