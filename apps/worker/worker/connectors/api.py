from __future__ import annotations

import json
from urllib.parse import urljoin

from worker.connectors.common import fetch_httpx_text
from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


class ApiConnector:
    def __init__(self, source_key: str, base_url: str) -> None:
        self.source_key = source_key
        self.base_url = base_url

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="application/json")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    def _maybe_load_json(self, value: object) -> object | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _iter_items(self, payload: object, _depth: int = 0) -> list[dict]:
        if _depth > 5:
            return []
        if isinstance(payload, list):
            items: list[dict] = []
            for item in payload:
                if isinstance(item, dict):
                    items.append(item)
                else:
                    parsed = self._maybe_load_json(item)
                    if parsed is not None:
                        items.extend(self._iter_items(parsed, _depth + 1))
            return items
        if not isinstance(payload, dict):
            parsed = self._maybe_load_json(payload)
            return self._iter_items(parsed, _depth + 1) if parsed is not None else []

        direct_fields = ("title", "name", "opportunityName", "summary", "description", "url", "link", "opportunityUrl")
        if any(payload.get(field) for field in direct_fields):
            return [payload]

        items: list[dict] = []
        for key in ("items", "results", "data", "opportunities", "records", "content", "itemListElement", "@graph", "graph"):
            value = payload.get(key)
            parsed = self._maybe_load_json(value)
            if parsed is not None:
                value = parsed
            if isinstance(value, list):
                items.extend(self._iter_items(value, _depth + 1))
            elif isinstance(value, dict):
                nested = self._iter_items(value, _depth + 1)
                if nested:
                    items.extend(nested)
        return items

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
        candidates: list[OpportunityCandidate] = []
        for item in self._iter_items(payload):
            title = str(item.get("title") or item.get("name") or item.get("opportunityName") or "").strip()
            link = str(
                item.get("url")
                or item.get("link")
                or item.get("official_url")
                or item.get("opportunityUrl")
                or ""
            ).strip()
            if not title:
                continue
            if link and not link.startswith(("http://", "https://")):
                link = urljoin(raw.url, link)
            summary = str(item.get("summary") or item.get("description") or title).strip()
            country = str(item.get("country") or item.get("location") or "Por validar").strip()
            identifier = str(item.get("id") or item.get("identifier") or item.get("opportunityId") or "").strip()
            if not link and identifier:
                link = urljoin(raw.url, f"#{identifier}")
            categories = [str(value) for value in (item.get("categories") or item.get("tags") or []) if isinstance(value, str)]
            topics = [str(value) for value in (item.get("topics") or []) if isinstance(value, str)]
            if not categories:
                lowered = f"{title} {summary}".lower()
                inferred = [label for label, needles in {
                    "grants": ["grant", "subsidy", "funding", "award"],
                    "education": ["scholarship", "fellowship", "study", "education"],
                    "research": ["research", "science", "investigation", "innovation"],
                    "cooperation": ["cooperation", "partnership", "collaboration"],
                }.items() if any(needle in lowered for needle in needles)]
                categories = inferred or ["opportunity"]
            if not topics:
                topics = [value for value in (str(item.get("theme") or item.get("program") or "").strip(),) if value]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=str(item.get("entity") or item.get("agency") or self.source_key),
                    country=country or "Por validar",
                    official_url=link or raw.url,
                    summary=summary[:700],
                    categories=categories[:5],
                    topics=topics[:5],
                    raw_text=summary[:2500],
                    confidence_score=0.66 if link else 0.52,
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and candidate.official_url))
