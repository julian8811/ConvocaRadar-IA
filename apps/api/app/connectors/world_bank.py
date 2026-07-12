"""World Bank procurement API connector.

The World Bank procurement page is JS-rendered, but a public JSON API is
available at https://search.worldbank.org/api/v2/procnotices.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import fetch_httpx_text
from app.connectors.registry import register

WORLD_BANK_API_URL = "https://search.worldbank.org/api/v2/procnotices"
WORLD_BANK_DETAIL_URL = "https://projects.worldbank.org/en/projects-operations/procurement-detail/{id}"


def _parse_wb_date(value: str | None) -> datetime | None:
    """Parse World Bank ISO date string (e.g. '2026-08-15T00:00:00')."""
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


@register("world-bank-procurement")
class WorldBankConnector:
    source_key = "world-bank-procurement"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or WORLD_BANK_API_URL

    async def fetch(self) -> RawSourceResult:
        url = f"{self.base_url}?format=json&rows=100&srt=submission_date desc&order=desc"
        final_url, content, content_type = await fetch_httpx_text(
            url,
            fallback_content_type="application/json",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if not raw.content.lstrip().startswith("{"):
            return []
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError:
            return []

        procnotices = payload.get("procnotices") or {}
        candidates: list[OpportunityCandidate] = []
        now = datetime.now()

        for item_id, item in procnotices.items():
            bid_description = str(item.get("bid_description") or "").strip()
            if not bid_description:
                continue

            title = bid_description[:180]
            notice_id = str(item.get("id") or item_id).strip()

            # Parse close date and filter out closed opportunities
            close_date = _parse_wb_date(item.get("submission_date"))
            if close_date and close_date < now:
                continue

            official_url = WORLD_BANK_DETAIL_URL.format(id=notice_id)
            country = str(item.get("project_ctry_name") or "International").strip()
            notice_type = str(item.get("notice_type") or "").strip()
            project_name = str(item.get("project_name") or "").strip()
            notice_text = str(item.get("notice_text") or "").strip()

            categories = ["procurement"]
            if notice_type:
                categories.append(notice_type)

            candidates.append(
                OpportunityCandidate(
                    title=title,
                    entity="World Bank",
                    country=country,
                    official_url=official_url,
                    summary=project_name or title,
                    categories=categories,
                    topics=["world-bank-procurement"],
                    raw_text=notice_text[:3000] if notice_text else json.dumps(item, ensure_ascii=False),
                    confidence_score=0.85,
                    close_date=close_date,
                )
            )

        return candidates

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title:
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url or "worldbank.org" not in candidate.official_url:
            return ValidationResult(ok=False, reason="Missing or unexpected official URL")
        return ValidationResult(ok=True)
