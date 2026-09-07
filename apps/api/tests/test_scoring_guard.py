"""Guard tests for the synchronous semantic-scoring fallback.

The current implementation computes deterministic local hash embeddings in
sync code and delegates only cosine similarity. These tests ensure it returns
plain floats, degrades safely when the similarity backend fails, and never
requires an async wrapper from synchronous request code.
"""

from __future__ import annotations

import pytest

import app.services.scoring as scoring_module
from app.services.scoring import _semantic_score


def test_semantic_score_positive_with_local_hash_embeddings() -> None:
    text = (
        "Convocatoria de fondos para proyectos de inteligencia artificial "
        "y machine learning en America Latina"
    )
    profile_text = "inteligencia artificial machine learning fondos proyectos innovacion"
    score = _semantic_score(text, profile_text)
    assert score > 0


def test_semantic_score_degrades_to_zero_when_similarity_backend_fails(monkeypatch) -> None:
    def _raise(_left: list[float], _right: list[float]) -> float:
        raise RuntimeError("similarity backend down")

    monkeypatch.setattr(scoring_module, "cosine_similarity", _raise)
    assert _semantic_score("opportunity text", "profile text") == 0.0


def test_semantic_score_returns_plain_float_from_local_vectors(monkeypatch) -> None:
    calls: list[tuple[list[float], list[float]]] = []

    def _fake_similarity(left: list[float], right: list[float]) -> float:
        calls.append((left, right))
        return 0.7071

    monkeypatch.setattr(scoring_module, "cosine_similarity", _fake_similarity)
    result = _semantic_score("opportunity description", "profile areas")
    assert len(calls) == 1
    assert calls[0][0]
    assert calls[0][1]
    assert isinstance(result, float)
    assert result == pytest.approx(0.7071, abs=1e-4)


def test_semantic_score_empty_input_returns_zero() -> None:
    assert _semantic_score("", "") == 0.0
