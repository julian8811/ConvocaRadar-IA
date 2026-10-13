"""EU Funding & Tenders search-API alias surface (4 programme keys).

The shared POST-only implementation lives in ``app.connectors.ft_search_v2``
(verified transport: POST with an empty body to
``{FT_SEARCH_URL}?apiKey={key}&text={term}&pageSize=50&pageNumber=1`` — the
endpoint answers 405 to GET — plus open-calls parsing that drops Ended/closed
items instead of returning the ~350k full-text project dump).

This module is a thin alias so the four fichas (``erc-calls``,
``horizon-europe-sedia``, ``msca-funding``, ``eu-creative-europe-calls``)
have a stable import surface without forking connector logic. Factory
registration stays in ``ft_search_v2`` (imported for side effects); no
``factory.py`` change is required.
"""

from __future__ import annotations

from app.connectors import ft_search_v2  # noqa: F401 — re-exported below
from app.connectors.ft_search_v2 import (  # noqa: F401 — alias surface
    CREATIVE_PROGRAM,
    ERC_PROGRAM,
    FILTERED_PROGRAMS,
    FT_PAGE_SIZE,
    FT_SEARCH_URL,
    HORIZON_PROGRAM,
    MSCA_PROGRAM,
    CreativeEuropeV2Connector,
    ErcV2Connector,
    FtSearchV2Connector,
    HorizonV2Connector,
    MscaV2Connector,
)

EU_FT_KEYS = (
    "erc-calls",
    "horizon-europe-sedia",
    "msca-funding",
    "eu-creative-europe-calls",
)

# Backwards-compatible alias name for the shared base connector.
EuFtSearchConnector = FtSearchV2Connector

__all__ = [
    "CREATIVE_PROGRAM",
    "ERC_PROGRAM",
    "EU_FT_KEYS",
    "FILTERED_PROGRAMS",
    "FT_PAGE_SIZE",
    "FT_SEARCH_URL",
    "HORIZON_PROGRAM",
    "MSCA_PROGRAM",
    "CreativeEuropeV2Connector",
    "ErcV2Connector",
    "EuFtSearchConnector",
    "FtSearchV2Connector",
    "HorizonV2Connector",
    "MscaV2Connector",
    "ft_search_v2",
]
