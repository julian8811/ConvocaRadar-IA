"""Runtime health checks for scraper infrastructure.

Verifies that Playwright browsers are installed and that optional
dependencies (pypdf) are importable. Functions log their findings
via structlog and return booleans so callers can decide severity.
"""

from __future__ import annotations

import os

import structlog

struct_logger = structlog.get_logger(__name__)


def check_playwright_binary() -> bool:
    """Verify that the Playwright chromium binary is available.

    Checks ``PLAYWRIGHT_BROWSERS_PATH`` env var (if set) and confirms the
    expected ``chromium`` binary exists at that location. Logs the resolved
    path on success, warns on failure.

    Returns ``True`` when the browser binary appears to be installed,
    ``False`` otherwise.
    """
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browsers_path:
        struct_logger.warning("health_check_playwright_no_path")
        return False

    chromium_path = os.path.join(browsers_path, "chromium")
    chromium_headless_path = os.path.join(browsers_path, "chromium-headless-shell")

    binary_found = False
    for path, label in [(chromium_path, "chromium"), (chromium_headless_path, "chromium-headless-shell")]:
        if os.path.exists(path):
            struct_logger.info("health_check_playwright_binary_found", path=path, binary=label)
            binary_found = True
        else:
            struct_logger.warning("health_check_playwright_binary_missing", path=path, binary=label)

    return binary_found


def check_pypdf_import() -> bool:
    """Verify that ``pypdf`` can be imported.

    Logs success on import, warning on failure.

    Returns ``True`` if pypdf was imported successfully, ``False`` otherwise.
    """
    try:
        import pypdf  # noqa: F401

        struct_logger.info("health_check_pypdf_ok")
        return True
    except ImportError as exc:
        struct_logger.warning("health_check_pypdf_missing", error=str(exc))
        return False
