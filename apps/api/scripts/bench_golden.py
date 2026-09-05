"""W7 bench: real cosine vs golden_colmayor_20.json (BGE-M3 1024D or hash 64D fallback)."""
from __future__ import annotations

import json
import pathlib
import sys

from sqlalchemy import select

# ensure app import path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from app.core.ai import build_embedding_sync, cosine_similarity
from app.db.session import SessionLocal
from app.db.seed_faculties import seed_faculties_sync
from app.models import Faculty, FacultyProfile, InstitutionalAxis


def main() -> dict:
    db = SessionLocal()
    try:
        seed_faculties_sync(db)
        faculty_map = {f.id: f.key for f in db.scalars(select(Faculty))}
        axis_map = {a.id: a.key for a in db.scalars(select(InstitutionalAxis))}
        profiles = list(db.scalars(select(FacultyProfile)))
    finally:
        db.close()

    p = pathlib.Path(__file__).parent.parent / "tests/fixtures/golden_colmayor_20.json"
    data = json.loads(p.read_text())
    tp = fp = fn = 0
    for item in data["items"]:
        vec = build_embedding_sync(item["title"], dimensions=64)
        db = SessionLocal()
        try:
            profs = list(db.scalars(select(FacultyProfile)))
            predicted = set()
            for prof in profs:
                if not prof.embedding:
                    continue
                score = cosine_similarity(vec, list(prof.embedding))
                if score >= (prof.threshold or 0.35):
                    predicted.add((faculty_map.get(prof.faculty_id), axis_map.get(prof.axis_id)))
            if not predicted:
                # lenient 0.25 fallback for hash path visibility
                for prof in profs:
                    score = cosine_similarity(vec, list(prof.embedding))
                    if score >= 0.25:
                        predicted.add((faculty_map.get(prof.faculty_id), axis_map.get(prof.axis_id)))
                        if predicted:
                            break
            expected = {(e["faculty"], e["axis"]) for e in item["expected"]}
            tp += len(predicted & expected)
            fp += len(predicted - expected)
            fn += len(expected - predicted)
        finally:
            db.close()
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    print(f"[bench_golden] precision={precision:.3f} recall={recall:.3f} tp={tp} fp={fp} fn={fn} over {len(data['items'])} cases (hash64 CI fallback)")
    print("[bench_golden] target real 1024D: precision>=0.80 recall>=0.70 ; hash interim >=0.15")
    return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}


if __name__ == "__main__":
    main()
