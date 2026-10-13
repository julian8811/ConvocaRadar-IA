"""Contrato tipado del auditor de fuentes (Fase 0).

Toda valoracion es PASS, FAIL o UNKNOWN con evidencia obligatoria.
Una dimension sin datos nunca da PASS. Sin red, sin DB, sin mutaciones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

DIMENSIONS: tuple[str, ...] = (
    "conectividad",
    "extraccion",
    "pertinencia",
    "enlaces",
    "fechas",
    "duplicados",
    "persistencia",
    "estabilidad",
)

#: Dimensiones criticas: deben estar verificadas (PASS) para `operativa`.
CRITICAL_DIMENSIONS: tuple[str, ...] = ("extraccion", "persistencia", "estabilidad")


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class Verdict(StrEnum):
    OPERATIVA = "operativa"
    DEGRADADA = "degradada"
    FALLIDA = "fallida"
    PENDIENTE = "pendiente"


Severity = Literal["P0", "P1", "P2", "P3"]
DataState = Literal["ok", "blocked_by_source", "not_applicable", "not_checked"]


class AuditEvidence(BaseModel):
    """Evidencia obligatoria de cada chequeo: contadores, ejemplos, errores."""

    counters: dict[str, Any] = Field(default_factory=dict)
    examples: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    data_state: DataState = "ok"
    notes: list[str] = Field(default_factory=list)


class AuditCheckResult(BaseModel):
    dimension: str
    status: CheckStatus
    evidence: AuditEvidence
    detail: str = ""


class SourceAuditResult(BaseModel):
    source_id: str
    source_key: str
    name: str
    enabled: bool
    source_type: str
    verdict: Verdict
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    checks: dict[str, AuditCheckResult]
    reasons: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    git_version: str = "unknown"
    limitations: list[str] = Field(default_factory=list)
    counters: dict[str, Any] = Field(default_factory=dict)
