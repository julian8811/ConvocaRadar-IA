"""Auditoria HISTORICA por fuente (Fase 1): 8 dimensiones sobre datos almacenados.

Entradas: dicts planos (source, runs, opportunities) — serializables a JSON,
cargables desde snapshot sanitizado o desde sesion SQL de solo lectura.
No hay red, no hay mutaciones, no hay imports de DB aqui.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.audit.types import (
    CRITICAL_DIMENSIONS,
    AuditCheckResult,
    AuditEvidence,
    CheckStatus,
    SourceAuditResult,
    Verdict,
)

QUARANTINE_CAP = 100  # runner registra como maximo 100 (censurado, no total)
PERSIST_COUNT_CAP = 50  # PERSIST_MAX_ITEMS_PER_RUN en app/scraper/runner.py
STABILITY_WINDOW = 10
FAILURE_RATE_FAIL = 0.5
EMPTY_RUNS_FAIL = 3
MISSING_URL_FAIL_RATIO = 0.2
UNKNOWN_CLOSE_FAIL_RATIO = 0.8
NEWS_RATIO_FAIL = 0.4

NETWORK_MARKERS = (
    "timeout", "timed out", "connection", "network", "dns",
    "unreachable", "refused", "reset", "ssl", "temporarily",
)
NEWS_MARKERS = ("noticia", "news", "empleo", "oferta laboral", "vacante", "partido",
                "deporte", "farandula", "editorial", "opinion")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1]
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _norm_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    try:
        p = urlparse(str(url).strip().lower())
        if not p.scheme or not p.netloc:
            return None
        return f"{p.netloc}{p.path.rstrip('/')}"
    except ValueError:
        return None


def _git_version() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _mk(dimension: str, status: CheckStatus, detail: str = "",
        **kw) -> AuditCheckResult:
    return AuditCheckResult(
        dimension=dimension, status=status, detail=detail,
        evidence=AuditEvidence(**kw),
    )


# ── 1. Conectividad ──────────────────────────────────────────────────
def check_conectividad(source: dict, runs: list[dict]) -> AuditCheckResult:
    if not runs:
        return _mk("conectividad", CheckStatus.UNKNOWN,
                   "sin ejecuciones: disponibilidad HTTP actual no medible",
                   data_state="not_checked",
                   notes=["el historico no verifica disponibilidad HTTP actual"])
    net_errors = [str(r.get("error_message") or "") for r in runs
                  if any(m in str(r.get("error_message") or "").lower()
                          for m in NETWORK_MARKERS)]
    failed = sum(1 for r in runs if r.get("status") == "failed")
    if net_errors or failed == len(runs):
        return _mk("conectividad", CheckStatus.FAIL,
                   f"{failed}/{len(runs)} runs fallidos; errores de red observados",
                   counters={"runs": len(runs), "failed": failed,
                             "network_errors": len(net_errors)},
                   errors=net_errors[:5])
    # Historico exitoso no prueba disponibilidad actual: nunca PASS.
    return _mk("conectividad", CheckStatus.UNKNOWN,
               "historico sin medicion directa valida (requiere probe)",
               counters={"runs": len(runs), "failed": failed},
               data_state="not_checked",
               notes=["el historico no verifica disponibilidad HTTP actual"])


# ── 2. Extraccion ────────────────────────────────────────────────────
def check_extraccion(source: dict, runs: list[dict]) -> AuditCheckResult:
    if not runs:
        return _mk("extraccion", CheckStatus.UNKNOWN, "sin ejecuciones",
                   data_state="not_checked")
    empties = sum(1 for r in runs
                  if (r.get("items_found") or 0) == 0 and r.get("status") != "failed")
    consec = int(source.get("consecutive_empty_runs") or 0)
    errors = [str(r.get("error_message") or "") for r in runs if r.get("error_message")]
    counters = {"runs": len(runs), "empty_runs": empties,
                "consecutive_empty_runs": consec}
    if consec >= EMPTY_RUNS_FAIL or empties >= EMPTY_RUNS_FAIL:
        return _mk("extraccion", CheckStatus.FAIL,
                   f"vacios recurrentes: {empties}/{len(runs)} (consec={consec})",
                   counters=counters, errors=errors[:5])
    if empties == len(runs) and len(runs) == 1:
        return _mk("extraccion", CheckStatus.UNKNOWN,
                   "unico run vacio: cero legitimo posible, sin tendencia",
                   counters=counters, data_state="blocked_by_source")
    found = sum(int(r.get("items_found") or 0) for r in runs)
    return _mk("extraccion", CheckStatus.PASS,
               f"cobertura ok: {found} items en {len(runs)} runs",
               counters={**counters, "items_found_total": found})


# ── 3. Pertinencia ───────────────────────────────────────────────────
def check_pertinencia(runs: list[dict], opps: list[dict]) -> AuditCheckResult:
    if not opps:
        if not runs:
            return _mk("pertinencia", CheckStatus.UNKNOWN, "sin oportunidades ni runs",
                       data_state="not_checked")
        return _mk("pertinencia", CheckStatus.UNKNOWN,
                   "sin oportunidades almacenadas: pertinencia no evaluable",
                   data_state="blocked_by_source")
    news = [o for o in opps if any(
        m in f"{o.get('title') or ''} {o.get('summary') or ''}".lower()
        for m in NEWS_MARKERS)]
    ratio = len(news) / len(opps)
    counters = {"opportunities": len(opps), "news_like": len(news),
                "news_ratio": round(ratio, 3)}
    examples = [str(o.get("official_url") or o.get("title")) for o in news[:5]]
    if ratio >= NEWS_RATIO_FAIL:
        return _mk("pertinencia", CheckStatus.FAIL,
                   f"posible ruido editorial: {ratio:.0%} con pinta de noticia/empleo",
                   counters=counters, examples=examples,
                   notes=["heuristica: marcar para revision, no borrar"])
    return _mk("pertinencia", CheckStatus.PASS,
               f"pertinencia razonable: {ratio:.0%} ruido aparente",
               counters=counters, examples=examples)


# ── 4. Enlaces ───────────────────────────────────────────────────────
def check_enlaces(opps: list[dict], runs: list[dict]) -> AuditCheckResult:
    if not opps:
        return _mk("enlaces", CheckStatus.UNKNOWN, "sin oportunidades",
                   data_state="not_checked" if not runs else "blocked_by_source")
    missing = sum(1 for o in opps if not (o.get("official_url") or "").strip())
    invalid = sum(1 for o in opps
                  if (o.get("official_url") or "").strip()
                  and _norm_url(o.get("official_url")) is None)
    ratio = (missing + invalid) / len(opps)
    counters = {"opportunities": len(opps), "missing_url": missing,
                "invalid_url": invalid, "bad_ratio": round(ratio, 3)}
    examples = [str(o.get("title")) for o in opps
                if not (o.get("official_url") or "").strip()][:5]
    if ratio >= MISSING_URL_FAIL_RATIO:
        return _mk("enlaces", CheckStatus.FAIL,
                   f"{missing + invalid}/{len(opps)} sin URL valida",
                   counters=counters, examples=examples)
    return _mk("enlaces", CheckStatus.PASS,
               f"enlaces ok: {len(opps) - missing - invalid}/{len(opps)} validas",
               counters=counters)


# ── 5. Fechas y vigencia ─────────────────────────────────────────────
def check_fechas(opps: list[dict], runs: list[dict], now: datetime) -> AuditCheckResult:
    if not opps:
        return _mk("fechas", CheckStatus.UNKNOWN, "sin oportunidades",
                   data_state="not_checked" if not runs else "blocked_by_source")
    unknown_close = sum(1 for o in opps if _parse_dt(o.get("close_date")) is None)
    expired_open = sum(
        1 for o in opps
        if str(o.get("status") or "").lower() == "open"
        and (cd := _parse_dt(o.get("close_date"))) is not None and cd < now)
    ratio = unknown_close / len(opps)
    counters = {"opportunities": len(opps), "unknown_close_date": unknown_close,
                "unknown_ratio": round(ratio, 3), "expired_open": expired_open}
    examples = [f"{o.get('title')} (cerro {o.get('close_date')})" for o in opps
                if str(o.get("status") or "").lower() == "open"
                and (cd := _parse_dt(o.get("close_date"))) is not None
                and cd < now][:5]
    if expired_open > 0 or ratio >= UNKNOWN_CLOSE_FAIL_RATIO:
        return _mk("fechas", CheckStatus.FAIL,
                   f"{expired_open} abiertas vencidas; {ratio:.0%} sin cierre",
                   counters=counters, examples=examples)
    return _mk("fechas", CheckStatus.PASS,
               f"vigencia ok: {expired_open} vencidas abiertas",
               counters=counters)


# ── 6. Duplicados ────────────────────────────────────────────────────
def check_duplicados(opps: list[dict], runs: list[dict]) -> AuditCheckResult:
    if len(opps) < 2:
        return _mk("duplicados", CheckStatus.UNKNOWN, "muestra insuficiente (<2)",
                   data_state="not_checked" if not runs else "blocked_by_source",
                   counters={"opportunities": len(opps)})
    seen_ext: dict[str, str] = {}
    seen_url: dict[str, str] = {}
    seen_title: dict[str, str] = {}
    dups = 0
    examples: list[str] = []
    for o in opps:
        key_ext = str(o.get("external_id") or "").strip()
        key_url = _norm_url(o.get("official_url")) or ""
        key_t = (f"{str(o.get('title') or '').strip().lower()}|"
                 f"{str(o.get('entity') or '').strip().lower()}|"
                 f"{str(o.get('close_date') or '')[:10]}")
        dup = ((key_ext and key_ext in seen_ext)
               or (key_url and key_url in seen_url)
               or (key_t.strip("|") and key_t in seen_title))
        if dup:
            dups += 1
            if len(examples) < 5:
                examples.append(f"{o.get('title')} [{o.get('official_url')}]")
        if key_ext:
            seen_ext.setdefault(key_ext, str(o.get("id")))
        if key_url:
            seen_url.setdefault(key_url, str(o.get("id")))
        if key_t.strip("|"):
            seen_title.setdefault(key_t, str(o.get("id")))
    counters = {"opportunities": len(opps), "duplicate_candidates": dups}
    if dups > 0:
        return _mk("duplicados", CheckStatus.FAIL,
                   f"{dups} candidatos a duplicado (reportar, no fusionar)",
                   counters=counters, examples=examples,
                   notes=["reportar candidatos con muestras, sin fusionar registros"])
    return _mk("duplicados", CheckStatus.PASS, "sin duplicados aparentes",
               counters=counters)


# ── 7. Persistencia ──────────────────────────────────────────────────
def check_persistencia(runs: list[dict]) -> AuditCheckResult:
    if not runs:
        return _mk("persistencia", CheckStatus.UNKNOWN, "sin ejecuciones",
                   data_state="not_checked")
    skipped = 0
    cap_reason: str | None = None
    per_run: list[int] = []
    failed_items = 0
    for r in runs:
        failed_items += int(r.get("items_failed") or 0)
        n_q = 0
        for log in r.get("logs") or []:
            if not isinstance(log, dict):
                continue
            if log.get("message") == "persist capped":
                skipped += int(log.get("items_skipped") or 0)
                cap_reason = str(log.get("reason") or cap_reason or "unknown")
            if log.get("level") == "quarantine":
                n_q += 1
        per_run.append(n_q)
    # Censura SOLO si alguna ejecucion INDIVIDUAL alcanzo el tope: el runner
    # topa por run (QUARANTINE_CAP_PER_RUN=100), nunca por suma acumulada.
    max_per_run = max(per_run) if per_run else 0
    censored = max_per_run >= QUARANTINE_CAP
    counters = {"runs": len(runs), "items_skipped": skipped,
                "cap_reason": cap_reason, "quarantine_entries": sum(per_run),
                "quarantine_per_run": per_run,
                "quarantine_max_per_run": max_per_run,
                "quarantine_censored": censored,
                "quarantine_cap": QUARANTINE_CAP,
                "items_failed": failed_items}
    if skipped > 0:
        return _mk("persistencia", CheckStatus.FAIL,
                   f"persistencia truncada: {skipped} omitidos ({cap_reason}); "
                   f"cuarentena {'censurada (un run alcanzo el tope 100: total real desconocido)' if censored else f'max {max_per_run}/run'}",
                   counters=counters,
                   examples=["cuarentena truncada a 100: el total real es desconocido"]
                   if censored else [])
    if censored:
        return _mk("persistencia", CheckStatus.FAIL,
                   "cuarentena en tope 100: total real desconocido (censurado)",
                   counters=counters,
                   examples=["cuarentena truncada a 100: el total real es desconocido"])
    if failed_items > 0:
        return _mk("persistencia", CheckStatus.FAIL,
                   f"{failed_items} items fallidos en persistencia",
                   counters=counters)
    created = sum(int(r.get("items_created") or 0) + int(r.get("items_updated") or 0)
                  for r in runs)
    return _mk("persistencia", CheckStatus.PASS,
               f"persistencia completa: {created} items, 0 omitidos",
               counters=counters)


# ── 8. Estabilidad ───────────────────────────────────────────────────
def check_estabilidad(source: dict, runs: list[dict]) -> AuditCheckResult:
    if not runs:
        return _mk("estabilidad", CheckStatus.UNKNOWN, "sin ejecuciones",
                   data_state="not_checked")
    window = runs[:STABILITY_WINDOW]
    failed = sum(1 for r in window if r.get("status") == "failed")
    rate = failed / len(window)
    counters = {"runs_window": len(window), "failed": failed,
                "failure_rate": round(rate, 3),
                "auto_paused": bool(source.get("auto_paused")),
                "consecutive_empty_runs": int(source.get("consecutive_empty_runs") or 0)}
    if bool(source.get("auto_paused")):
        return _mk("estabilidad", CheckStatus.FAIL, "fuente auto-pausada",
                   counters=counters)
    if rate >= FAILURE_RATE_FAIL:
        return _mk("estabilidad", CheckStatus.FAIL,
                   f"tasa de fallos {rate:.0%} en ultimos {len(window)}",
                   counters=counters)
    if len(window) == 1:
        return _mk("estabilidad", CheckStatus.UNKNOWN,
                   "un solo run: sin tendencia (no fallida por un puntual)",
                   counters=counters, data_state="blocked_by_source")
    return _mk("estabilidad", CheckStatus.PASS,
               f"estable: {rate:.0%} fallos en {len(window)} runs",
               counters=counters)


# ── Certificacion viva (separada del historico) ───────────────────────
#: Criterios EXACTOS de certificacion viva. Ningun resultado history los
#: cumple (conectividad nunca es PASS sin probe): no hay retro-certificacion.
LIVE_CERTIFICATION_CRITERIA: dict[str, object] = {
    "requires_scope_live_checked": True,
    "requires_live_conectividad_pass": True,
    "requires_pass": ("extraccion", "persistencia", "estabilidad"),
    "requires_live_probe_evidence": True,
    "max_probe_age_hours": 72,
}


def meets_live_certification(result: SourceAuditResult) -> bool:
    """True solo si el resultado trae verificacion en vivo valida.

    Exige: scope live_checked + conectividad PASS con evidencia de probe
    real (no simulado) + dimensiones criticas en PASS. Todo lo historico
    (scope historical_only) devuelve False: sin retro-certificacion.
    """
    if result.verification_scope != "live_checked":
        return False
    conn = result.checks.get("conectividad")
    if conn is None or conn.status != CheckStatus.PASS:
        return False
    for dim in ("extraccion", "persistencia", "estabilidad"):
        c = result.checks.get(dim)
        if c is None or c.status != CheckStatus.PASS:
            return False
    ev = conn.evidence
    return bool(ev.counters.get("live_probe") is True
                and ev.counters.get("simulated") is not True)


# ── Veredicto global ─────────────────────────────────────────────────
def _verdict(source: dict, checks: dict[str, AuditCheckResult]) -> tuple[Verdict, str, list[str], bool]:
    reasons: list[str] = []
    if not source.get("enabled", True):
        return (Verdict.PENDIENTE, "P3",
                ["fuente deshabilitada: incluida en inventario, no auditada"], True)
    fails = [c for c in checks.values() if c.status == CheckStatus.FAIL]
    unknowns = [c for c in checks.values() if c.status == CheckStatus.UNKNOWN]
    crit_fail = [c for c in fails if c.dimension in CRITICAL_DIMENSIONS]
    if bool(source.get("auto_paused")) or any(
            c.dimension == "estabilidad" and "auto-pausada" in c.detail for c in fails):
        return (Verdict.FALLIDA, "P0", ["auto-pausada"] + [c.detail for c in fails], True)
    if crit_fail:
        reasons = [f"{c.dimension}: {c.detail}" for c in fails]
        sev = "P0" if checks.get("estabilidad", _mk("x", CheckStatus.PASS)).status == CheckStatus.FAIL \
            and checks["estabilidad"].evidence.counters.get("failure_rate", 0) >= FAILURE_RATE_FAIL \
            else "P1"
        if any(c.dimension == "estabilidad" for c in crit_fail):
            sev = "P0"
        return (Verdict.FALLIDA, sev, reasons, True)
    if fails:
        return (Verdict.DEGRADADA, "P1" if len(fails) > 1 else "P2",
                [f"{c.dimension}: {c.detail}" for c in fails], True)
    crit_unknown = [c for c in unknowns if c.dimension in CRITICAL_DIMENSIONS]
    if crit_unknown or not checks:
        return (Verdict.PENDIENTE, "P3",
                [f"{c.dimension}: {c.detail}" for c in unknowns], True)
    if unknowns:
        # UNKNOWN no critico (p. ej. conectividad sin probe): limitacion
        # informativa, no degrada. No convertir UNKNOWN en PASS.
        return (Verdict.OPERATIVA, "P3",
                [f"{c.dimension}: sin medicion directa (limitacion) "
                 for c in unknowns] or ["dimensiones criticas verificadas"], False)
    return (Verdict.OPERATIVA, "P3", ["dimensiones criticas verificadas"], False)


def audit_source(source: dict, runs: list[dict], opps: list[dict],
                 *, now: datetime | None = None) -> SourceAuditResult:
    """Audita una fuente. Ordena runs por fecha desc antes de evaluar."""
    now = now or _now()
    ordered = sorted(runs, key=lambda r: str(r.get("finished_at")
                                             or r.get("started_at") or ""),
                     reverse=True)
    checks = {
        "conectividad": check_conectividad(source, ordered),
        "extraccion": check_extraccion(source, ordered),
        "pertinencia": check_pertinencia(ordered, opps),
        "enlaces": check_enlaces(opps, ordered),
        "fechas": check_fechas(opps, ordered, now),
        "duplicados": check_duplicados(opps, ordered),
        "persistencia": check_persistencia(ordered),
        "estabilidad": check_estabilidad(source, ordered),
    }
    verdict, severity, reasons, review = _verdict(source, checks)
    fails = sum(1 for c in checks.values() if c.status == CheckStatus.FAIL)
    unknowns = sum(1 for c in checks.values() if c.status == CheckStatus.UNKNOWN)
    confidence = round(max(0.0, min(1.0, 1.0 - 0.15 * unknowns - 0.05 * fails)), 2)
    return SourceAuditResult(
        source_id=str(source.get("id") or ""),
        source_key=str(source.get("key") or ""),
        name=str(source.get("name") or ""),
        enabled=bool(source.get("enabled", True)),
        source_type=str(source.get("source_type") or "unknown"),
        verdict=verdict, severity=severity, confidence=confidence,
        checks=checks, reasons=reasons, needs_human_review=review,
        evaluated_at=now, git_version=_git_version(),
        limitations=["modo history: sin medicion directa de red; "
                     "conectividad nunca PASS sin probe",
                     "cuarentena topada a 100: total real desconocido"],
        counters={"runs": len(ordered), "opportunities": len(opps),
                  "checks_fail": fails, "checks_unknown": unknowns},
    )


def audit_all(sources: list[dict], runs_by_source: dict[str, list[dict]],
              opps_by_source: dict[str, list[dict]],
              *, now: datetime | None = None) -> list[SourceAuditResult]:
    return [audit_source(s, runs_by_source.get(str(s.get("id")), []),
                         opps_by_source.get(str(s.get("id")), []), now=now)
            for s in sources]
