"""T2b: migración 0020 reject_news para cundinamarca + bogotá-de.

Test-first para ``0020_reject_news_cundinamarca_bogota``: mergea
``connector_config.reject_news=true`` preservando el resto del JSON,
solo en las 2 claves objetivo. Downgrade retira la clave preservando
el resto. Patrón copiado de test_0019 (fixture SQLite + stamp + upgrade).

RED: falla sin la migración (head sigue en 0019).
GREEN: upgrade/downgrade/roundtrip + protegidas intactas.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REVISION = "0020_reject_news_cundinamarca_bogota"
DOWN_REVISION = "0019_canonical_source_urls"

TARGET_KEYS = (
    "cundinamarca-convocatorias",
    "bogota-desarrollo-economico",
)

BASE_CONFIG = {
    "list_selectors": ["article", ".views-row"],
    "title_selectors": ["h2", "h3"],
    "link_selectors": ["a"],
    "content_selectors": ["article", "main"],
    "date_labels": ["Cierre:"],
    "detail_enrichment": False,
}

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


def _read_config(db_path: str, key: str) -> dict:
    from app.models import Source

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            source = session.scalars(select(Source).where(Source.key == key)).one()
            return dict(source.connector_config or {})
    finally:
        engine.dispose()


@pytest.fixture
def seeded_db(monkeypatch, tmp_path):
    """SQLite desechable con 2 filas objetivo (config sin flag) + 1 protegida."""
    db_path = str(tmp_path / "reject_news_0020.db")
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
                    connector_config=dict(BASE_CONFIG),
                )
            )
        session.add(
            Source(
                id=f"src-{PROTECTED_KEY}",
                key=PROTECTED_KEY,
                name=PROTECTED_KEY,
                base_url="https://example.com/",
                allowed_domains=["example.com"],
                connector_config=dict(BASE_CONFIG),
            )
        )
        session.commit()
    engine.dispose()

    cfg = _cfg(db_path)
    command.stamp(cfg, DOWN_REVISION)
    yield db_path


def test_0020_registered_in_lineage() -> None:
    # El head lo posee test_migrations_chain; aquí solo: existe, cuelga
    # de 0019 e historia lineal (único head).
    script = _script()
    rev = script.get_revision(REVISION)
    assert rev is not None
    assert rev.down_revision == DOWN_REVISION
    assert len(script.get_heads()) == 1


def test_0020_upgrade_merges_flag_preserving_config(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), REVISION)
    for key in TARGET_KEYS:
        config = _read_config(seeded_db, key)
        assert config["reject_news"] is True
        for field, value in BASE_CONFIG.items():
            assert config[field] == value, f"{key} perdió {field}"
    assert "reject_news" not in _read_config(seeded_db, PROTECTED_KEY)


def test_0020_upgrade_is_idempotent(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), REVISION)
    snapshot = {k: _read_config(seeded_db, k) for k in TARGET_KEYS}
    command.upgrade(_cfg(seeded_db), REVISION)
    for key in TARGET_KEYS:
        assert _read_config(seeded_db, key) == snapshot[key]


def test_0020_downgrade_removes_flag_preserving_config(seeded_db: str) -> None:
    command.upgrade(_cfg(seeded_db), REVISION)
    command.downgrade(_cfg(seeded_db), DOWN_REVISION)
    for key in TARGET_KEYS:
        assert _read_config(seeded_db, key) == BASE_CONFIG


def test_0020_roundtrip(seeded_db: str) -> None:
    cfg = _cfg(seeded_db)
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, DOWN_REVISION)
    command.upgrade(cfg, REVISION)
    for key in TARGET_KEYS:
        assert _read_config(seeded_db, key)["reject_news"] is True
