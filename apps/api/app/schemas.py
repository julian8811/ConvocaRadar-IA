"""Temporary re-export facade — delegates to ``app.schemas.*`` domain modules.

All schema classes have been moved to ``app/schemas/<domain>.py``.
This file is kept for backward compatibility and will be removed in a
future cleanup. Import directly from ``app.schemas`` for new code.
"""

from app.schemas import *  # noqa: F401, F403
