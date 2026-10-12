"""Conservative source-specific structural noise filters.

Only eliminate known non-opportunity sections using both source identity
and explicit URL structure. Do not infer eligibility, availability or closure.
Rejected items are recorded by the runner's existing quarantine mechanism.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def source_non_opportunity_reason(
    source_key: str | None,
    title: str | None,
    official_url: str | None,
) -> str | None:
    """Return a stable reason for structurally non-opportunity URLs.

    This is intentionally an allowlist of precise false-positive URL
    patterns, NOT a global rule requiring a deadline or a money amount.
    A legitimate call with missing fields must remain eligible for
    enrichment rather than being silently discarded.
    """
    if not official_url or not source_key:
        return None
    parsed = urlsplit(official_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold().rstrip("/") + "/"
    key = source_key.casefold()

    if (
        key == "cost-open-calls"
        and host == "cost.eu"
        and path.startswith("/about/")
    ):
        return "COST: página institucional /about/, no convocatoria individual"

    if (
        key == "adaptation-fund-apply"
        and host == "adaptation-fund.org"
        and path.startswith("/projects-programmes/project-sectors/")
    ):
        return "Adaptation Fund: ficha de sector temático, no apertura de financiación"

    return None
