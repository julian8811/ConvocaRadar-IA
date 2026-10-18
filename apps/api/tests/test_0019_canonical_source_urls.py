"""P0 fuentes muertas (T2, S3/S4/S6): migración 0019 de URLs canónicas.

Test-first para la migración ``0019_canonical_source_urls``: lleva los
``base_url`` + ``allowed_domains`` canónicos (pineados en
``CANONICAL_SEEDS`` de test_seed_canonical_urls.py, que ya coinciden con
``seed.py``) a las filas existentes de ``sources``.

- Fuente de verdad del upgrade: ``CANONICAL_SEEDS`` (importado, no copiado).
- Downgrade: revierte a las URLs viejas 404 probadas en
  ``reports/live-probe-*/live-probe-real.json`` (fijadas aquí en OLD_SEEDS
  y verificadas contra el seed previo al re-mapeo f94a163/5323554).
- Las claves protegidas (sgc, unal, flacso, rutann, cali, medellín) no se tocan.

RED: falla sin la migración (revisión 0019 ausente en la cadena alembic).
GREEN: pasa con la migración aplicada (upgrade + downgrade + roundtrip).
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REVISION = "0019_canonical_source_urls"
DOWN_REVISION = "0018_unique_opportunity_score"

# URLs viejas (404 probadas en reports/live-probe-*/live-probe-real.json)
# + allowed_domains previos al re-mapeo. El downgrade revierte a esto.
OLD_SEEDS = {
    "oei-convocatorias": (
        "https://oei.int/oficinas/secretaria-general/convocatorias",
        ["oei.int", "www.oei.int"],
    ),
    "cepal-convocatorias": (
        "https://www.cepal.org/es/convocatorias",
        ["cepal.org", "www.cepal.org"],
    ),
    "finagro-lec-2026": (
        "https://www.finagro.com.co/lineas-especiales-credito-lec-finagro-2026",
        ["finagro.com.co", "www.finagro.com.co"],
    ),
    "green-climate-fund": (
        "https://www.greenclimate.fund/projects/call-for-proposals",
        ["greenclimate.fund", "www.greenclimate.fund"],
    ),
    "supersolidaria-convocatorias": (
        "https://www.supersolidaria.gov.co/es/convocatorias",
        ["supersolidaria.gov.co", "www.supersolidaria.gov.co"],
    ),
    "global-environment-facility": (
        "https://www.thegef.org/projects-operations/calls-for-proposals",
        ["thegef.org", "www.thegef.org"],
    ),
    "giz-alemania": (
        "https://www.giz.de/en/html/ausschreibungen.html",
        ["giz.de", "www.giz.de"],
    ),
    "anp-brasil": (
        "https://www.gov.br/anp/pt-br/assuntos/pesquisa-desenvolvimento-e-inovacao",
        ["gov.br", "anp.gov.br"],
    ),
    "procolombia-inversion": (
        "https://investincolombia.com.co/es/convocatorias",
        ["investincolombia.com.co"],
    ),
    "inct-brasil": (
        "https://www.gov.br/cnpq/pt-br/assuntos/institutos-nacionais-de-ciencia-e-tecnologia",
        ["gov.br"],
    ),
}

# Claves protegidas (S3): la migración no debe tocarlas.
PROTECTED_SEEDS = {
    "sgc-convocatorias": (
        "https://www.segib.org/convocatorias/",
        ["segib.org", "www.segib.org"],
    ),
    "universidad-nacional-colombia": (
        "https://investigacion.unal.edu.co/convocatorias/",
        ["unal.edu.co", "investigacion.unal.edu.co"],
    ),
    "flacso-convocatorias": (
        "https://www.flacso.org/convocatorias",
        ["flacso.org", "www.flacso.org"],
    ),
    "rutann-convocatorias": (
        "https://www.rutanmedellin.org/convocatorias",
        ["rutanmedellin.org", "www.rutanmedellin.org"],
    ),
    "camara-comercio-cali": (
        "https://www.ccc.org.co/convocatorias/",
        ["ccc.org.co", "www.ccc.org.co"],
    ),
    "camara-comercio-medellin": (
        "https://www.camaramedellin.com.co/convocatorias",
        ["camaramedellin.com.co", "www.camaramedellin.com.co"],
    ),
}

EXPECTED_KEYS = [
    "oei-convocatorias",
    "cepal-convocatorias",
    "finagro-lec-2026",
    "green-climate-fund",
    "supersolidaria-convocatorias",
    "global-environment-facility",
    "giz-alemania",
    "anp-brasil",
    "procolombia-inversion",
    "inct-brasil",
]


def _api_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]


def _script() -> ScriptDirectory:
    return ScriptDirectory(str(_api_dir() / "migrations"))


def _cfg(db_path: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _read_row(db_path: str, key: str) -> tuple[str, list]:
    from app.models import Source

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            source = session.scalars(select(Source).where(Source.key == key)).one()
            return source.base_url, list(source.allowed_domains or [])
    finally:
        engine.dispose()


@pytest.fixture
def seeded_db(monkeypatch, tmp_path):
    """SQLite desechable con esquema vigente + filas viejas, stamp en 0018."""
    from test_seed_canonical_urls import CANONICAL_SEEDS

    assert set(CANONICAL_SEEDS) == set(EXPECTED_KEYS)

    db_path = str(tmp_path / "canonical_0019.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.db.session import Base as AppBase
    from app.models import Source
    import app.models  # noqa: F401

    engine = create_engine(f"sqlite:///{db_path}")
    AppBase.metadata.create_all(engine)
    with Session(engine) as session:
        for key, (url, domains) in OLD_SEEDS.items():
            session.add(
                Source(
                    id=f"src-{key}", key=key, name=key, base_url=url, allowed_domains=list(domains)
                )
            )
        session.flush()
        # Una fila ya-canónica antes del upgrade: debe quedar igual.
        canon_url, canon_domains = CANONICAL_SEEDS["giz-alemania"]
        giz = session.scalars(select(Source).where(Source.key == "giz-alemania")).one()
        giz.base_url = canon_url
        giz.allowed_domains = list(canon_domains)
        for key, (url, domains) in PROTECTED_SEEDS.items():
            session.add(
                Source(
                    id=f"src-{key}", key=key, name=key, base_url=url, allowed_domains=list(domains)
                )
            )
        session.commit()
    engine.dispose()

    cfg = _cfg(db_path)
    command.stamp(cfg, DOWN_REVISION)
    yield db_path


def test_0019_registered_in_lineage() -> None:
    # 0019 ya no es el head (la 0020 la sucede); la propiedad del head
    # vive en test_migrations_chain. Aquí solo: la revisión existe,
    # cuelga de 0018 y la historia sigue lineal (un único head).
    script = _script()
    rev = script.get_revision(REVISION)
    assert rev is not None
    assert rev.down_revision == DOWN_REVISION
    assert len(script.get_heads()) == 1


def test_0019_upgrade_applies_canonical_urls(seeded_db: str) -> None:
    from test_seed_canonical_urls import CANONICAL_SEEDS

    command.upgrade(_cfg(seeded_db), "head")
    for key in EXPECTED_KEYS:
        expected_url, expected_domains = CANONICAL_SEEDS[key]
        url, domains = _read_row(seeded_db, key)
        assert url == expected_url, f"{key} base_url no migrado"
        assert domains == expected_domains, f"{key} allowed_domains no migrados"


def test_0019_upgrade_is_idempotent_and_preserves_protected(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), "head")
    snapshot = {k: _read_row(seeded_db, k) for k in EXPECTED_KEYS}
    # Re-correr el upgrade es no-op: nada cambia.
    command.upgrade(_cfg(seeded_db), "head")
    for key in EXPECTED_KEYS:
        assert _read_row(seeded_db, key) == snapshot[key], f"{key} no idempotente"
    for key, (url, domains) in PROTECTED_SEEDS.items():
        assert _read_row(seeded_db, key) == (url, domains), f"{key} tocada"


def test_0019_downgrade_restores_old_urls(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), "head")
    command.downgrade(_cfg(seeded_db), DOWN_REVISION)
    for key, (url, domains) in OLD_SEEDS.items():
        # giz-alemania partía ya-canónica; el downgrade la lleva a la vieja.
        assert _read_row(seeded_db, key) == (url, domains), f"{key} no revertida"
    for key, (url, domains) in PROTECTED_SEEDS.items():
        assert _read_row(seeded_db, key) == (url, domains), f"{key} tocada"


def test_0019_roundtrip_upgrade_downgrade_upgrade(seeded_db: str) -> None:
    from test_seed_canonical_urls import CANONICAL_SEEDS

    cfg = _cfg(seeded_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, DOWN_REVISION)
    command.upgrade(cfg, "head")
    for key in EXPECTED_KEYS:
        expected_url, expected_domains = CANONICAL_SEEDS[key]
        assert _read_row(seeded_db, key) == (expected_url, expected_domains)


def test_0019_old_urls_match_live_probe_evidence() -> None:
    """Las URLs viejas del downgrade son las 404 de reports/live-probe-*."""
    import json as _json
    from pathlib import Path

    repo_root = _api_dir().parent.parent
    for key, (old_url, _domains) in OLD_SEEDS.items():
        probe = repo_root / "reports" / f"live-probe-{key}-20261012" / "live-probe-real.json"
        assert probe.exists(), f"falta evidencia probe de {key}"
        data = _json.loads(probe.read_text(encoding="utf-8"))
        assert data["http_status"] == 404, f"{key} no era 404"
        assert old_url in data["evidence"]["urls"], f"{key} vieja no coincide con probe"
