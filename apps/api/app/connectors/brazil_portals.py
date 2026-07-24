"""Dedicated connector types for Brazilian opportunity portals."""
from __future__ import annotations

from app.connectors.generic_html import GenericHtmlConnector


class FinepConnector(GenericHtmlConnector):
    """FINEP Brazil connector. Uses GenericHtmlConnector without overrides."""
