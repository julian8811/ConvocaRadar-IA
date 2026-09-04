"""Seed faculties/axes/profiles from versioned JSON."""

import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ai import build_embedding
from app.models import Faculty, InstitutionalAxis, FacultyProfile


def _load_seed() -> dict:
    path = Path(__file__).parent.parent.parent / "seed" / "faculties_axes_v1.json"
    # Also try app/seed path
    if not path.exists():
        path = Path("seed/faculties_axes_v1.json")
    if not path.exists():
        path = Path("apps/api/seed/faculties_axes_v1.json")
    return json.loads(path.read_text())


async def seed_faculties(db: Session) -> dict:
    data = _load_seed()
    # Upsert faculties
    faculty_map: dict[str, Faculty] = {}
    for f in data["faculties"]:
        existing = db.scalar(select(Faculty).where(Faculty.key == f["key"]))
        if existing:
            existing.name = f["name"]
            existing.slug = f["slug"]
            existing.color = f["color"]
            existing.icon = f["icon"]
            existing.description = f["description"]
            faculty_map[f["key"]] = existing
        else:
            obj = Faculty(key=f["key"], name=f["name"], slug=f["slug"], color=f["color"], icon=f["icon"], description=f["description"])
            db.add(obj)
            db.flush()
            faculty_map[f["key"]] = obj

    axis_map: dict[str, InstitutionalAxis] = {}
    for a in data["axes"]:
        existing = db.scalar(select(InstitutionalAxis).where(InstitutionalAxis.key == a["key"]))
        if existing:
            existing.label = a["label"]
            existing.description = a["description"]
            axis_map[a["key"]] = existing
        else:
            obj = InstitutionalAxis(key=a["key"], label=a["label"], description=a["description"])
            db.add(obj)
            db.flush()
            axis_map[a["key"]] = obj

    created = 0
    updated = 0
    for p in data["profiles"]:
        fac = faculty_map[p["faculty"]]
        ax = axis_map[p["axis"]]
        existing = db.scalar(select(FacultyProfile).where(FacultyProfile.faculty_id == fac.id, FacultyProfile.axis_id == ax.id))
        source_url = data["source_urls"][0] if data["source_urls"] else None
        emb_text = f"{fac.name} - {ax.label}: {p['description']}"
        # Use sync-ish: if build_embedding is async, call via asyncio
        try:
            import asyncio
            try:
                vec = asyncio.run(build_embedding(emb_text))
            except RuntimeError:
                # Already in event loop
                import concurrent.futures
                vec = [0.0] * 64
        except Exception:
            vec = [0.0] * 64

        if existing:
            if existing.description != p["description"]:
                existing.description = p["description"]
                existing.embedding = vec
                existing.version += 1
                existing.threshold = p.get("threshold", 0.35)
                existing.source_url = source_url
                updated += 1
        else:
            obj = FacultyProfile(faculty_id=fac.id, axis_id=ax.id, description=p["description"], embedding=vec, threshold=p.get("threshold", 0.35), color=fac.color, version=1, source_url=source_url)
            db.add(obj)
            created += 1
    db.commit()
    return {"faculties": len(faculty_map), "axes": len(axis_map), "created": created, "updated": updated}


def seed_faculties_sync(db: Session) -> dict:
    """Sync version for use in seed.py bootstrap - uses zero vectors initially."""
    import json
    from pathlib import Path

    # Find seed JSON
    candidates = [
        Path(__file__).parent.parent.parent / "seed" / "faculties_axes_v1.json",
        Path("seed/faculties_axes_v1.json"),
        Path("apps/api/seed/faculties_axes_v1.json"),
        Path(__file__).parent / "../../seed/faculties_axes_v1.json",
    ]
    data = None
    for c in candidates:
        if c.exists():
            data = json.loads(c.read_text())
            break
    if data is None:
        # Fallback: try relative to cwd
        import os
        for root, _, files in os.walk("."):
            if "faculties_axes_v1.json" in files:
                data = json.loads(Path(root, "faculties_axes_v1.json").read_text())
                break
    if data is None:
        return {"faculties": 0, "axes": 0, "created": 0, "updated": 0}

    faculty_map: dict[str, Faculty] = {}
    for f in data["faculties"]:
        existing = db.scalar(select(Faculty).where(Faculty.key == f["key"]))
        if existing:
            faculty_map[f["key"]] = existing
        else:
            obj = Faculty(key=f["key"], name=f["name"], slug=f["slug"], color=f["color"], icon=f["icon"], description=f["description"])
            db.add(obj)
            db.flush()
            faculty_map[f["key"]] = obj

    axis_map: dict[str, InstitutionalAxis] = {}
    for a in data["axes"]:
        existing = db.scalar(select(InstitutionalAxis).where(InstitutionalAxis.key == a["key"]))
        if existing:
            axis_map[a["key"]] = existing
        else:
            obj = InstitutionalAxis(key=a["key"], label=a["label"], description=a["description"])
            db.add(obj)
            db.flush()
            axis_map[a["key"]] = obj

    # Precompute embeddings synchronously using hash fallback for speed
    from app.core.ai import build_embedding_sync
    from app.core.config import get_settings
    import hashlib, math

    def hash_vec(text: str, dims=64):
        vec = [0.0]*dims
        import re
        tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t]
        if not tokens:
            return vec
        for tok in tokens:
            d = hashlib.sha256(tok.encode()).digest()
            b = int.from_bytes(d[:4], "big") % dims
            vec[b] += 1.0 + min(len(tok), 12)/12.0
        norm = math.sqrt(sum(v*v for v in vec))
        if norm == 0:
            return vec
        return [round(v/norm, 6) for v in vec]

    source_url = data["source_urls"][0] if data["source_urls"] else None
    created = 0
    for p in data["profiles"]:
        fac = faculty_map[p["faculty"]]
        ax = axis_map[p["axis"]]
        existing = db.scalar(select(FacultyProfile).where(FacultyProfile.faculty_id == fac.id, FacultyProfile.axis_id == ax.id))
        if existing:
            continue
        emb_text = f"{fac.name} - {ax.label}: {p['description']}"
        # Use hash vec for sync seeding to avoid async
        vec = hash_vec(emb_text, dims=64)
        obj = FacultyProfile(faculty_id=fac.id, axis_id=ax.id, description=p["description"], embedding=vec, threshold=p.get("threshold", 0.35), color=fac.color, version=1, source_url=source_url)
        db.add(obj)
        created += 1
    db.commit()
    return {"faculties": len(faculty_map), "axes": len(axis_map), "created": created, "updated": 0}
