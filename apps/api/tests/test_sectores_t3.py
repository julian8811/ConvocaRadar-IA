"""T3 embedding fallback layer — TDD tests.

``classify_by_embedding`` rescues rows where the T2 rules layer yields
``otros`` or low confidence, via cosine similarity against one textual
prototype per sector. ``embed_fn`` is injectable: tests use a
deterministic hashing stub with zero network access.

Real-model wiring (``build_embedding_sync`` from ``app.core.ai``) needs
server-side infra and is pinned as pending-verify; see
``test_real_wiring_is_documented_not_executed``.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from app.core.sectors import (
    EMBEDDING_SIMILARITY_THRESHOLD,
    SECTOR_PROTOTYPES,
    SECTOR_TAXONOMY_V1,
    classify_by_embedding,
    classify_with_fallback,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sectores_eval.json"

# Measured 2026-10-11 with the deterministic hashing surrogate stub
# (see _surrogate_embed): combined rules→embeddings accuracy must not
# regress below the T2 rules baseline pin (0.85). The stub is a lexical
# lower bound — real-model lift is verified server-side (T4 era).
COMBINED_BASELINE_ACCURACY = 0.85

_STUB_DIMENSIONS = 256


def _surrogate_embed(text: str) -> list[float]:
    """Deterministic hashing embedding stub (zero network).

    Token-bucket vector over accent-folded tokens, L2-normalized, so
    cosine similarity reflects lexical overlap. Stable across runs
    (md5, no hash randomization).
    """
    import re
    import unicodedata

    folded = unicodedata.normalize("NFKD", (text or "").lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", folded)
    vector = [0.0] * _STUB_DIMENSIONS
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:2], "big") % _STUB_DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if not norm:
        return vector
    return [v / norm for v in vector]


def _load_eval_rows() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_prototype_covers_every_non_otros_sector() -> None:
    expected = [s for s in SECTOR_TAXONOMY_V1 if s != "otros"]
    assert sorted(SECTOR_PROTOTYPES.keys()) == sorted(expected)
    for sector, prototype in SECTOR_PROTOTYPES.items():
        assert isinstance(prototype, str)
        assert len(prototype) >= 50, f"prototype for {sector!r} too short"


def test_exact_prototype_text_returns_sector_with_high_confidence() -> None:
    for sector, prototype in SECTOR_PROTOTYPES.items():
        predicted, confidence = classify_by_embedding(
            prototype, "", _surrogate_embed
        )
        assert predicted == sector
        assert confidence >= 0.9


def test_empty_input_returns_otros_with_zero_confidence() -> None:
    assert classify_by_embedding("", "", _surrogate_embed) == ("otros", 0.0)


def test_gibberish_returns_otros_with_zero_confidence() -> None:
    sector, confidence = classify_by_embedding(
        "xqzt blorpt", "wobble fnord zzx", _surrogate_embed
    )
    assert (sector, confidence) == ("otros", 0.0)


def test_threshold_filters_weak_matches() -> None:
    sector, confidence = classify_by_embedding(
        "Convocatoria de becas",
        "apoyo general sin detalles",
        _surrogate_embed,
        threshold=0.99,
    )
    assert (sector, confidence) == ("otros", 0.0)


def test_classifier_is_deterministic() -> None:
    args = ("Becas de diploma y cursos", "educación superior e-learning")
    assert classify_by_embedding(*args, _surrogate_embed) == classify_by_embedding(
        *args, _surrogate_embed
    )


def test_embed_fn_receives_combined_title_and_description() -> None:
    seen: list[str] = []

    def spy(text: str) -> list[float]:
        seen.append(text)
        return _surrogate_embed(text)

    classify_by_embedding("becas diploma", "cursos e-learning", spy)
    assert seen, "embed_fn was never called"
    assert "becas diploma" in seen[0]
    assert "cursos e-learning" in seen[0]


def test_prototype_vectors_are_cached() -> None:
    calls: list[str] = []

    def counting_spy(text: str) -> list[float]:
        calls.append(text)
        return _surrogate_embed(text)

    classify_by_embedding("becas", "cursos", counting_spy)
    first_run = len(calls)
    classify_by_embedding("becas", "cursos", counting_spy)
    # Second call reuses cached prototypes: only the input text is embedded.
    assert len(calls) == first_run + 1


def test_hybrid_keeps_confident_rules_result_without_embedding() -> None:
    calls: list[str] = []

    def spy(text: str) -> list[float]:
        calls.append(text)
        return _surrogate_embed(text)

    sector, confidence, source = classify_with_fallback(
        "Convocatoria jóvenes emprendedores",
        "planes de negocio y mipymes",
        spy,
    )
    assert sector == "emprendimiento"
    assert source == "rules"
    assert calls == []
    assert confidence > 0.0


def test_hybrid_keeps_low_confidence_rules_label_without_embedding() -> None:
    """Low-confidence non-otros rules labels stay with rules (no-regression
    guard): rerouting them measured 0.63 vs 0.867 baseline with the
    surrogate stub — they are T4 (LLM judge) candidates, not T3."""
    calls: list[str] = []

    def spy(text: str) -> list[float]:
        calls.append(text)
        return _surrogate_embed(text)

    # Rules yields salud @0.33 here; hybrid must keep it untouched.
    sector, _, source = classify_with_fallback(
        "Programa contra la obesidad",
        "apoyo general sin detalles",
        spy,
    )
    assert source == "rules"
    assert calls == []


def test_hybrid_falls_back_to_embeddings_on_otros() -> None:
    # Delegating stub: prototypes embed normally, any other text maps to
    # the transferencia prototype vector (no ties).
    target = _surrogate_embed(SECTOR_PROTOTYPES["transferencia tecnológica"])

    def fixed_stub(text: str) -> list[float]:
        if text in SECTOR_PROTOTYPES.values():
            return _surrogate_embed(text)
        return list(target)

    sector, confidence, source = classify_with_fallback(
        "PQRSDF", "Peticiones, quejas y reclamos", fixed_stub
    )
    assert source == "embeddings"
    assert sector == "transferencia tecnológica"
    assert confidence > 0.0


def test_hybrid_combined_accuracy_does_not_regress() -> None:
    rows = _load_eval_rows()
    assert len(rows) == 90
    hits = 0
    for row in rows:
        predicted, _, _ = classify_with_fallback(
            row["title"], row["description"], _surrogate_embed
        )
        if predicted == row["sector"]:
            hits += 1
    accuracy = hits / len(rows)
    print(f"\ncombined accuracy: {accuracy:.3f} ({hits}/{len(rows)})")
    print(f"threshold: {EMBEDDING_SIMILARITY_THRESHOLD}")
    assert accuracy >= COMBINED_BASELINE_ACCURACY


def test_embedding_predictions_use_closed_taxonomy() -> None:
    rows = _load_eval_rows()
    for row in rows:
        sector, _ = classify_by_embedding(
            row["title"], row["description"], _surrogate_embed
        )
        assert sector in SECTOR_TAXONOMY_V1


def test_embedding_confidence_always_in_unit_interval() -> None:
    rows = _load_eval_rows()
    for row in rows:
        _, confidence = classify_by_embedding(
            row["title"], row["description"], _surrogate_embed
        )
        assert 0.0 <= confidence <= 1.0


def test_real_wiring_is_documented_not_executed() -> None:
    """Pin: production wiring is ``build_embedding_sync`` (app.core.ai),
    which needs server infra — intentionally NOT called here (zero network).
    """
    assert 0.0 < EMBEDDING_SIMILARITY_THRESHOLD < 1.0
