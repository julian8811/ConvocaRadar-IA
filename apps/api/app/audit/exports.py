"""Exports reproducibles: CSV, JSON, XLSX y resumen Markdown. Sin secretos/PII."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook

from app.audit.types import DIMENSIONS, SourceAuditResult

COLUMNS = (["source_key", "name", "enabled", "source_type", "verdict", "severity",
            "confidence", "evaluated_at", "needs_human_review",
            "verification_scope", "live_certified"]
           + list(DIMENSIONS) + ["reasons"])


def _row(r: SourceAuditResult) -> dict:
    row = {"source_key": r.source_key, "name": r.name, "enabled": r.enabled,
           "source_type": r.source_type, "verdict": r.verdict.value,
           "severity": r.severity, "confidence": r.confidence,
           "evaluated_at": r.evaluated_at.isoformat(),
           "needs_human_review": r.needs_human_review,
           "verification_scope": r.verification_scope,
           "live_certified": r.live_certified}
    for d in DIMENSIONS:
        c = r.checks.get(d)
        row[d] = c.status.value if c else "UNKNOWN"
    row["reasons"] = " | ".join(r.reasons)
    return row


def write_csv(results: list[SourceAuditResult], path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in results:
            w.writerow(_row(r))
    return path


def write_json(results: list[SourceAuditResult], path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps([r.model_dump(mode="json") for r in results],
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_xlsx(results: list[SourceAuditResult], path: str | Path) -> Path:
    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "auditoria"
    ws.append(COLUMNS)
    for r in results:
        row = _row(r)
        ws.append([row[c] for c in COLUMNS])
    wb.save(path)
    return path


def write_markdown(results: list[SourceAuditResult], path: str | Path,
                   *, mode: str = "history") -> Path:
    """Resumen: inventario completo (incl. deshabilitadas), P0-P3, por conector."""
    path = Path(path)
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    by_verdict = Counter(r.verdict.value for r in results)
    by_sev = Counter(r.severity for r in results)
    by_type = Counter(r.source_type for r in results)
    disabled = [r for r in results if not r.enabled]
    lines = [
        "# Auditoria de fuentes (modo %s)" % mode,
        "",
        f"Generado: {now} UTC. Fuentes: {len(results)} "
        f"(habilitadas {len(results) - len(disabled)}, deshabilitadas {len(disabled)}).",
        "",
        "## Veredictos",
        "",
        "".join(f"- {v}: {by_verdict.get(v, 0)}\n"
                for v in ("operativa", "degradada", "fallida", "pendiente")),
        "## Severidad",
        "",
        "".join(f"- {s}: {by_sev.get(s, 0)}\n" for s in ("P0", "P1", "P2", "P3")),
        "## Por tipo de conector",
        "",
        "".join(f"- {t or '?'}: {n}\n" for t, n in sorted(by_type.items())),
        "",
        "## Problemas priorizados (P0 primero)",
        "",
    ]
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    flagged = sorted((r for r in results if r.verdict != "operativa"),
                     key=lambda r: (order.get(r.severity, 9), r.source_key))
    if not flagged:
        lines.append("Sin problemas: todas las fuentes auditadas estan operativas.\n")
    for r in flagged:
        lines.append(f"### [{r.severity}] {r.source_key} — {r.verdict.value}")
        lines.append("")
        lines.append(f"Habilitada: {r.enabled}. Confianza: {r.confidence}. "
                     f"Revision humana: {r.needs_human_review}. "
                     f"Alcance: {r.verification_scope}. "
                     f"Certificada en vivo: {r.live_certified}.")
        for reason in r.reasons:
            lines.append(f"- {reason}")
        for dim, c in r.checks.items():
            if c.status.value != "PASS":
                ex = f" Ejemplos: {'; '.join(c.evidence.examples[:3])}" \
                    if c.evidence.examples else ""
                lines.append(f"- {dim}: {c.status.value} — {c.detail}.{ex}")
        lines.append("")
    lines += [
        "## Inventario completo",
        "",
        "| key | habilitada | veredicto | severidad |",
        "| --- | --- | --- | --- |",
    ]
    for r in sorted(results, key=lambda r: r.source_key):
        lines.append(f"| {r.source_key} | {r.enabled} | {r.verdict.value} | {r.severity} |")
    lines += [
        "",
        "## Limitaciones",
        "",
        "- Modo history: sin medicion directa de red; conectividad nunca PASS sin probe.",
        "- Alcance history: historical_only, live_certified=false (nunca viva sin probe real).",
        "- Cuarentena topada a 100 por run: el total real es desconocido (censurado).",
        "- Heuristicas de pertinencia/duplicados marcan revision, no borran ni fusionan.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
