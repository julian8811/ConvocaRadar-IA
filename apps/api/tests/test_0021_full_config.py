"""T2b fix-forward: migración 0021 full-config para cundinamarca + bogotá-de.

La 0020 mergeó ``reject_news`` sobre el JSON existente, pero en prod esas
filas tenían ``connector_config`` NULL → quedaron con config incompleta
y la factory levanta ValueError. La 0021 escribe el config COMPLETO del
seed + flag; downgrade vuelve a NULL (estado pre-0020 verificado en prod).

RED: falla sin la migración (head sigue en 0020).
GREEN: upgrade/downgrade/roundtrip + protegidas intactas + coherencia seed.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REVISION = "0021_reject_news_full_config"
DOWN_REVISION = "0020_reject_news_cundinamarca_bogota"

TARGET_KEYS = (
    "cundinamarca-convocatorias",
    "bogota-desarrollo-economico",
)

PROTECTED_KEY = "ascun-convocatorias"


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


def _read_config(db_path: str, key: str):
    from app.models import Source

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            source = session.scalars(select(Source).where(Source.key == key)).one()
            raw = source.connector_config
            return dict(raw) if raw else None
    finally:
        engine.dispose()


@pytest.fixture
def seeded_db(monkeypatch, tmp_path):
    """SQLite con 2 filas objetivo en NULL (estado prod pre-0020) + 1 protegida."""
    db_path = str(tmp_path / "full_config_0021.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.db.session import Base as AppBase
    from app.models import Source
    import app.models  # noqa: F401

    engine = create_engine(f"sqlite:///{db_path}")
    AppBase.metadata.create_all(engine)
    with Session(engine) as session:
        for key in TARGET_KEYS:
            session.add(
                Source(
                    id=f"src-{key}",
                    key=key,
                    name=key,
                    base_url="https://example.com/",
                    allowed_domains=["example.com"],
                    connector_config=None,
                )
            )
        session.add(
            Source(
                id=f"src-{PROTECTED_KEY}",
                key=PROTECTED_KEY,
                name=PROTECTED_KEY,
                base_url="https://example.com/",
                allowed_domains=["example.com"],
                connector_config=None,
            )
        )
        session.commit()
    engine.dispose()

    cfg = _cfg(db_path)
    command.stamp(cfg, DOWN_REVISION)
    yield db_path


def test_0021_registered_in_lineage() -> None:
    # El head lo posee test_migrations_chain; aquí solo: existe, cuelga
    # de 0020 e historia lineal (único head).
    script = _script()
    rev = script.get_revision(REVISION)
    assert rev is not None
    assert rev.down_revision == DOWN_REVISION
    assert len(script.get_heads()) == 1


def test_0021_upgrade_writes_full_config_matching_seed(seeded_db: str) -> None:
    from test_seed_canonical_urls import _seed_definitions_by_key

    command.upgrade(_cfg(seeded_db), REVISION)
    defs = _seed_definitions_by_key()
    for key in TARGET_KEYS:
        config = _read_config(seeded_db, key)
        assert config is not None, f"{key} sin config tras upgrade"
        assert config == defs[key]["connector_config"], f"{key} diverge del seed"
        assert config["reject_news"] is True
    assert _read_config(seeded_db, PROTECTED_KEY) is None


def test_0021_upgrade_is_idempotent(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), REVISION)
    snapshot = {k: _read_config(seeded_db, k) for k in TARGET_KEYS}
    command.upgrade(_cfg(seeded_db), REVISION)
    for key in TARGET_KEYS:
        assert _read_config(seeded_db, key) == snapshot[key]


def test_0021_downgrade_restores_null(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), REVISION)
    command.downgrade(_cfg(seeded_db), DOWN_REVISION)
    for key in TARGET_KEYS:
        assert _read_config(seeded_db, key) is None
    assert _read_config(seeded_db, PROTECTED_KEY) is None


def test_0021_roundtrip(seeded_db: str) -> None:
    cfg = _cfg(seeded_db)
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, DOWN_REVISION)
    command.upgrade(cfg, REVISION)
    for key in TARGET_KEYS:
        config = _read_config(seeded_db, key)
        assert config is not None, f"{key} sin config tras roundtrip"
        assert config["reject_news"] is True
