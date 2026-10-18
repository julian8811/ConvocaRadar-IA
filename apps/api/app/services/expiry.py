"""T3 (vigencia S4): sweeper diario de vencidas con backup rotativo.

Corre dentro del loop del scheduler (hook junto al nightly en main.py).
Reglas de seguridad, en este orden:

1. Solo ``close_date`` pasada (nunca unknown sin fecha).
2. Backup verificado ANTES de borrar: si el put falla, aborta con
   rollback y no toca ninguna fila.
3. Dependientes primero (precedente purge-trio), luego opportunities.
4. Retención rotativa de backups (``backup_retain`` días, default 7);
   la poda es best-effort y nunca bloquea la purga.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.storage import delete_object as storage_delete_object
from app.core.storage import put_bytes as storage_put_bytes
from app.models import (
    Alert,
    Opportunity,
    OpportunityAxisMatch,
    OpportunityDocument,
    OpportunityEmbedding,
    OpportunityScore,
)

_DEPENDENTS = (
    OpportunityDocument,
    OpportunityScore,
    OpportunityEmbedding,
    OpportunityAxisMatch,
    Alert,
)

_BACKUP_PREFIX = "expiry-sweeps"
_PRUNE_LOOKBACK_DAYS = 60


def _row_to_json_dict(opportunity: Opportunity) -> dict[str, object]:
    table = Opportunity.__table__
    values: dict[str, object] = {}
    for column in table.columns:
        value = getattr(opportunity, column.name, None)
        if isinstance(value, (str, int, float, bool)) or value is None:
            values[column.name] = value
        else:
            values[column.name] = str(value)
    values["id"] = str(values.get("id"))
    return values


def purge_expired_opportunities(
    db,
    *,
    today: date | None = None,
    backup_retain: int = 7,
) -> dict[str, object]:
    """Purge opportunities with ``close_date`` before ``today`` (naive UTC).

    Returns ``{"expired_found", "deleted", "backup_key", "pruned",
    "aborted_reason"}``. Never raises for expected failure modes: backup
    errors and delete errors both roll back and report ``aborted_reason``.
    """
    day = today or datetime.now(UTC).date()
    result: dict[str, object] = {
        "expired_found": 0,
        "deleted": 0,
        "backup_key": None,
        "pruned": [],
        "aborted_reason": None,
    }
    cutoff = datetime(day.year, day.month, day.day)
    expired = list(
        db.scalars(
            select(Opportunity).where(
                Opportunity.close_date.is_not(None),
                Opportunity.close_date < cutoff,
            )
        )
    )
    result["expired_found"] = len(expired)
    if not expired:
        return result

    backup_key = f"{_BACKUP_PREFIX}/{day.isoformat()}.json"
    payload = json.dumps(
        {
            "purged_at": day.isoformat(),
            "reason": "sweeper diario de vencidas (vigencia S4)",
            "opportunities": [_row_to_json_dict(o) for o in expired],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        storage_put_bytes(backup_key, payload, "application/json")
    except Exception as exc:
        db.rollback()
        result["aborted_reason"] = f"backup failed, nothing deleted: {exc}"
        return result
    result["backup_key"] = backup_key

    ids = [o.id for o in expired]
    try:
        for model in _DEPENDENTS:
            db.execute(
                model.__table__.delete().where(model.opportunity_id.in_(ids))
            )
        deleted = db.execute(
            Opportunity.__table__.delete().where(Opportunity.id.in_(ids))
        ).rowcount
        db.commit()
    except Exception as exc:
        db.rollback()
        result["aborted_reason"] = f"delete failed, rolled back: {exc}"
        return result
    result["deleted"] = deleted or 0

    pruned: list[str] = []
    for offset in range(backup_retain + 1, _PRUNE_LOOKBACK_DAYS + 1):
        old = day - timedelta(days=offset)
        old_key = f"{_BACKUP_PREFIX}/{old.isoformat()}.json"
        try:
            storage_delete_object(old_key)
        except Exception:
            continue
        pruned.append(old_key)
    result["pruned"] = pruned
    return result
