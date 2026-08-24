"""Guard tests for the semantic scoring path (REQ-CI-SCORING-1).

Audit regression: ``_semantic_score`` called the async ``build_embedding``
from sync context and inspected the result with an unimported
``asyncio.iscoroutine``. The NameError was swallowed by the broad except
clause, so the semantic contribution was silently pinned to 0.0 on every
call while a never-awaited coroutine leaked each time.
"""

from __future__ import annotations

import pytest

import app.services.scoring as scoring_module
from app.services.scoring import _semantic_score


def test_semantic_score_positive_with_local_hash_embeddings() -> None:
    """Scenario: embedding available — semantic score must be > 0."""
    text = (
        "Convocatoria de fondos para proyectos de inteligencia artificial "
        "y machine learning en America Latina"
    )
    profile_text = "inteligencia artificial machine learning fondos proyectos innovacion"
    score = _semantic_score(text, profile_text)
    assert score > 0


def test_semantic_score_degrades_to_zero_when_backend_fails(monkeypatch) -> None:
    """Scenario: embedding unavailable — degrade to 0.0 without crashing."""

    def _raise(text: str, *, dimensions: int | None = None) -> list[float]:
        raise RuntimeError("embedding backend down")

    monkeypatch.setattr(scoring_module, "build_embedding_sync", _raise)
    assert _semantic_score("opportunity text", "profile text") == 0.0


def test_semantic_score_runs_sync_wrapper_and_returns_float(monkeypatch) -> None:
    """Both texts go through the sync wrapper and a plain float similarity
    comes back — never a coroutine object."""
    calls: list[str] = []

    def _fake_sync(text: str, *, dimensions: int | None = None) -> list[float]:
        calls.append(text)
        return [1.0, 0.0] if "opportunity" in text else [0.5, 0.5]

    monkeypatch.setattr(scoring_module, "build_embedding_sync", _fake_sync)
    result = _semantic_score("opportunity description", "profile areas")
    assert len(calls) == 2
    assert isinstance(result, float)
    # cos([1, 0], [0.5, 0.5]) = 0.5 / (1 * 0.7071) ≈ 0.7071
    assert result == pytest.approx(0.7071, abs=1e-3)


def test_semantic_score_empty_input_returns_zero() -> None:
    """Empty input short-circuits to 0.0 before touching the backend."""
    assert _semantic_score("", "") == 0.0
