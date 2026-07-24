"""Dedicated connector for DANE convocatorias y contratación."""
from __future__ import annotations

from app.connectors.base import RawSourceResult
from app.connectors.generic_html import GenericHtmlConnector


class DaneConnector(GenericHtmlConnector):
    """DANE section connector; generic parser is constrained to official page."""
    async def parse(self, raw: RawSourceResult):
        candidates = await super().parse(raw)
        return [c for c in candidates if c.title and not c.title.lower().startswith(("inicio", "home", "dane -")) and not any(str(year) in c.title for year in range(2010, 2026))]

