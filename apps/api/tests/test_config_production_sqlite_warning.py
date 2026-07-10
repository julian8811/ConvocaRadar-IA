"""Task 5 — Verify production SQLite startup warning.

When APP_ENV=production and DATABASE_URL contains 'sqlite', the
application must log a warning that SQLite is unsafe for production.

The warning is triggered by calling ``check_production_sqlite()``
in app.core.config at startup.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from app.core.config import check_production_sqlite


def test_production_with_sqlite_logs_warning() -> None:
    """check_production_sqlite() must log a warning when
    app_env=production and database_url contains 'sqlite'."""
    with patch("app.core.config.logger.warning") as mock_warning:
        check_production_sqlite(app_env="production", database_url="sqlite:///./prod.db")

    mock_warning.assert_called_once()
    call_arg = mock_warning.call_args[0][0]
    assert "sqlite" in call_arg.lower() or "SQLite" in call_arg, (
        f"Expected warning containing 'sqlite'. Got: {call_arg!r}"
    )


def test_non_production_with_sqlite_does_not_warn() -> None:
    """check_production_sqlite() must NOT log when app_env=development."""
    with patch("app.core.config.logger.warning") as mock_warning:
        check_production_sqlite(app_env="development", database_url="sqlite:///./dev.db")

    mock_warning.assert_not_called()


def test_production_with_postgres_does_not_warn() -> None:
    """check_production_sqlite() must NOT log when database_url
    is postgresql, even in production."""
    with patch("app.core.config.logger.warning") as mock_warning:
        check_production_sqlite(
            app_env="production", database_url="postgresql://user:pass@localhost/db"
        )

    mock_warning.assert_not_called()
