"""Visible quarantine for discarded ingestion candidates (T4 fortalecer-201).

Candidates dropped as noise or low-confidence duplicates used to vanish
without a trace — only aggregate counters survived in ``SourceRun`` stats.
This module persists each discarded candidate as a structured
``{"level": "quarantine", ...}`` entry in the existing ``SourceRun.logs``
JSON column (no new tables, no migration) and exposes helpers to read
them back per source.

Reason taxonomy (stable, filterable via the endpoint):
- ``ruido``: title/summary matched the noise heuristics.
- ``duplicado``: candidate merged into an already-known opportunity.
- ``validacion``: connector validation rejected the candidate.
- ``url_muerta``: official/application URL unreachable (validation or HEAD).
- ``sin_fecha``: validation rejected for a missing/unparseable close date.
- ``idioma``: validation rejected for an unsupported language.
- ``error``: persistence raised for any other reason.
"""

from __future__ import annotations

from app.models import SourceRun

QUARANTINE_LEVEL = "quarantine"

QUARANTINE_REASONS: tuple[str, ...] = (
    "ruido",
    "duplicado",
    "validacion",
    "url_muerta",
    "sin_fecha",
    "idioma",
    "error",
)

#: Bound per run so a pathological page cannot bloat the JSON column.
QUARANTINE_CAP_PER_RUN = 100


def quarantine_entry(
    reason: str,
    title: str,
    *,
    url: str | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    """Build a single quarantine log entry for ``SourceRun.logs``."""
    if reason not in QUARANTINE_REASONS:
        reason = "error"
    entry: dict[str, object] = {
        "level": QUARANTINE_LEVEL,
        "reason": reason,
        "title": (title or "")[:200],
    }
    if url:
        entry["url"] = url[:500]
    if detail:
        entry["detail"] = detail[:500]
    return entry


def classify_validation_reason(reason: str | None) -> str:
    """Map a free-text connector validation reason to the taxonomy."""
    text = (reason or "").lower()
    if any(
        marker in text
        for marker in ("url", "unreachable", "muerta", "timeout", "timed out", "404", "dead")
    ):
        return "url_muerta"
    if any(marker in text for marker in ("idioma", "language", "langue", "língua")):
        return "idioma"
    if any(
        marker in text
        for marker in ("close_date", "fecha de cierre", "fecha cierre", "sin fecha", "deadline")
    ):
        return "sin_fecha"
    return "validacion"


def is_quarantine_log(entry: object) -> bool:
    """Check whether a ``SourceRun.logs`` entry is a quarantine record."""
    return isinstance(entry, dict) and entry.get("level") == QUARANTINE_LEVEL


def extract_quarantine_items(
    runs: list[SourceRun],
    *,
    reason: str | None = None,
    limit: int = 100,
) -> tuple[int, list[dict[str, object]]]:
    """Flatten quarantine entries from recent runs, newest run first.

    Returns ``(total, items)`` where ``total`` counts all matching entries
    and ``items`` is capped at ``limit``. Each item carries ``run_id``,
    ``reason``, ``title``, optional ``url``/``detail`` and the run's
    ``created_at`` ISO timestamp.
    """
    matched: list[dict[str, object]] = []
    for run in runs:
        for raw in run.logs or []:
            if not is_quarantine_log(raw):
                continue
            entry = dict(raw)
            if reason and entry.get("reason") != reason:
                continue
            created = run.created_at
            matched.append(
                {
                    "run_id": run.id,
                    "reason": entry.get("reason"),
                    "title": entry.get("title", ""),
                    "url": entry.get("url"),
                    "detail": entry.get("detail"),
                    "created_at": created.isoformat() if created else None,
                }
            )
    return len(matched), matched[: max(limit, 0)]
