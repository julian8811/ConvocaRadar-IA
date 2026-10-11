"""T2 rules-based sector classifier — TDD tests.

Baseline is pinned honestly against
``tests/fixtures/sectores_eval.json`` (90 rows, T1 eval set): the
accuracy threshold below is the measured rules-layer baseline, not a
target. T3 (embeddings) and T4 (LLM judge) are expected to lift it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.sectors import SECTOR_TAXONOMY_V1, classify_by_rules

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sectores_eval.json"

# Measured 2026-10-11 on the 90-row T1 eval set: 0.867 (78/90).
# Pinned at 0.85 to allow minor wobble while catching regressions.
# Rules-layer baseline; do not inflate — T3/T4 own the lift to the
# >=90% hybrid goal.
RULES_BASELINE_ACCURACY = 0.85


def _load_eval_rows() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_accuracy_against_eval_fixture() -> None:
    rows = _load_eval_rows()
    assert len(rows) == 90
    hits = 0
    misses: list[tuple[str, str, str]] = []
    for row in rows:
        predicted, _ = classify_by_rules(row["title"], row["description"])
        if predicted == row["sector"]:
            hits += 1
        else:
            misses.append((row["id"], row["sector"], predicted))
    accuracy = hits / len(rows)
    print(f"\nrules accuracy: {accuracy:.3f} ({hits}/{len(rows)})")
    for row_id, expected, predicted in misses:
        print(f"  MISS {row_id} expected={expected!r} predicted={predicted!r}")
    assert accuracy >= RULES_BASELINE_ACCURACY


def test_per_sector_accuracy_report() -> None:
    """Informational per-sector breakdown for T3 (embeddings) handoff."""
    from collections import Counter

    rows = _load_eval_rows()
    total: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    for row in rows:
        total[row["sector"]] += 1
        predicted, _ = classify_by_rules(row["title"], row["description"])
        if predicted == row["sector"]:
            ok[row["sector"]] += 1
    print("\nper-sector rules accuracy:")
    for sector in SECTOR_TAXONOMY_V1:
        line = f"  {sector}: {ok[sector]}/{total[sector]}"
        print(line)
        assert total[sector] > 0


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        # turismo (ES/EN/PT)
        ("Convocatoria de turismo sostenible", "apoyo a hoteles y ecoturismo", "turismo"),
        ("Blue economy grants", "underwater museum and tourism", "turismo"),
        ("Edital de turismo", "apoio a viagens e hotelaria", "turismo"),
        # investigación (ES/EN/PT)
        ("Convocatoria de investigación científica", "proyectos de ciencia y laboratorio", "investigación"),
        ("Research grants 2026", "funding for researchers and science", "investigación"),
        ("Bolsa de doutorado em física", "pesquisa e pesquisadores", "investigación"),
        # emprendimiento (ES/EN/PT)
        ("Convocatoria jóvenes emprendedores", "planes de negocio y mipymes", "emprendimiento"),
        ("Startup funding", "business plan and incubator support", "emprendimiento"),
        ("Edital de empreendimentos inovadores", "apoio a incubadoras", "emprendimiento"),
        # innovación (ES/EN/PT)
        ("Ayudas a la innovación", "proyectos de innovación tecnológica", "innovación"),
        ("Innovation grants", "artificial intelligence and innovation", "innovación"),
        ("Chamada de inovação", "inovação tecnológica em empresas", "innovación"),
        # transferencia tecnológica (ES/EN/PT)
        ("Transferencia tecnológica", "apropiación tecnológica en regiones", "transferencia tecnológica"),
        ("Technology transfer call", "technology transfer to industry", "transferencia tecnológica"),
        ("Transferência de tecnologia", "apropriação tecnológica", "transferencia tecnológica"),
        # educación (ES/EN/PT)
        ("Becas de educación superior", "diploma y cursos e-learning", "educación"),
        ("Education grants", "schools, teachers and diploma courses", "educación"),
        ("Bolsas de educação", "cursos e escolas públicas", "educación"),
        # salud (ES/EN/PT)
        ("Salud pública 2026", "hospitales y atención primaria", "salud"),
        ("Health services research", "hospitals and nursing care", "salud"),
        ("Saúde pública", "hospitais e vacinação", "salud"),
        # ambiente (ES/EN/PT)
        ("Convocatoria de medio ambiente", "sostenibilidad y biodiversidad", "ambiente"),
        ("Climate action fund", "green climate and sustainability", "ambiente"),
        ("Edital de meio ambiente", "sustentabilidade e biodiversidade", "ambiente"),
        # cultura (ES/EN/PT)
        ("Beca de circulación de música en vivo", "todas las culturas cuentan", "cultura"),
        ("Music festival grants", "theatre, dance and heritage", "cultura"),
        ("Edital de cultura", "música, dança e patrimônio", "cultura"),
        # infraestructura (ES/EN/PT)
        ("Obras de infraestructura vial", "construcción e instalación", "infraestructura"),
        ("Irrigation infrastructure works", "construction and installation of pumps", "infraestructura"),
        ("Obras de infraestrutura", "construção e instalação", "infraestructura"),
    ],
)
def test_keyword_spot_checks(title: str, description: str, expected: str) -> None:
    sector, confidence = classify_by_rules(title, description)
    assert sector == expected
    assert 0.0 < confidence <= 1.0


def test_empty_input_returns_otros_with_zero_confidence() -> None:
    assert classify_by_rules("", "") == ("otros", 0.0)
    assert classify_by_rules("   ", "  ") == ("otros", 0.0)


def test_no_signal_returns_otros_with_zero_confidence() -> None:
    sector, confidence = classify_by_rules("PQRSDF", "Peticiones, quejas y reclamos")
    assert (sector, confidence) == ("otros", 0.0)


def test_closed_taxonomy() -> None:
    rows = _load_eval_rows()
    for row in rows:
        sector, _ = classify_by_rules(row["title"], row["description"])
        assert sector in SECTOR_TAXONOMY_V1


def test_confidence_always_in_unit_interval() -> None:
    rows = _load_eval_rows()
    for row in rows:
        _, confidence = classify_by_rules(row["title"], row["description"])
        assert 0.0 <= confidence <= 1.0


def test_classifier_is_pure_and_deterministic() -> None:
    first = classify_by_rules("Innovation call", "research and innovation ecosystems")
    second = classify_by_rules("Innovation call", "research and innovation ecosystems")
    assert first == second
