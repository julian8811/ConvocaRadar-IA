from app.connectors.registry import register
import re
from datetime import datetime
from html import unescape

from app.connectors.common import fetch_httpx_text
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


SIMPLER_GRANTS_URL = "https://simpler.grants.gov/search"
SIMPLER_OPPORTUNITY_URL = "https://simpler.grants.gov/opportunity/{opportunity_id}"
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _clean(value: str | None) -> str:
    text = unescape(value or "")
    text = text.replace('\\"', '"').replace("\\/", "/")
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    match = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})\b", value)
    if not match:
        return None
    month = MONTHS.get(match.group(1))
    if not month:
        return None
    return datetime(int(match.group(3)), month, int(match.group(2)))


def _find_after(block: str, label: str) -> str:
    decoded = block.replace('\\"', '"').replace("\\/", "/")
    decoded_match = re.search(
        rf'"children"\s*:\s*(?:\[\s*)?"{re.escape(label)}".{{0,90}}?"\s*,\s*"([^"]+)"',
        decoded,
        flags=re.DOTALL,
    )
    if decoded_match:
        candidate = _clean(decoded_match.group(1)).strip(": ")
        if candidate and candidate != label and candidate.lower() not in {"div", "span", "$", "null"}:
            return candidate
    direct_patterns = [
        rf'\[\\"{re.escape(label)}\\",\\":\\"\]\}}\]\}},\\" \\",\\"([^"\\]+)',
        rf'"children"\s*:\s*\[\s*"{re.escape(label)}"\s*,\s*":"\s*\]\}}\]\}},\\" \\",\\"([^"\\]+)',
        rf'\\"children\\":\\"{re.escape(label)}\\"\}}\],\\" \\",\\"([^"\\]+)',
    ]
    for pattern in direct_patterns:
        match = re.search(pattern, block, flags=re.DOTALL)
        if match:
            candidate = _clean(match.group(1))
            if candidate.lower() not in {"div", "span", "$", "null"}:
                return candidate
    array_label = re.search(
        rf'"children"\s*:\s*\[\s*"{re.escape(label)}"\s*,\s*":"\s*\]\}}\]\}},\\" \\",\\"([^"\\]+)',
        block,
    )
    if array_label:
        return _clean(array_label.group(1))
    scalar_label = re.search(
        rf'"children"\s*:\s*"{re.escape(label)}"\}}\]}}.*?\\" \\",\\"([^"\\]+)',
        block,
        flags=re.DOTALL,
    )
    if scalar_label:
        return _clean(scalar_label.group(1))
    label_index = block.find(f'"children":"{label}"')
    if label_index != -1:
        fragment = block[label_index : label_index + 700]
        values = re.findall(r'"children":"([^"]+)"', fragment)
        for index, value in enumerate(values):
            if value == label and index + 1 < len(values):
                candidate = _clean(values[index + 1]).strip(": ")
                if candidate and candidate != ":" and candidate.lower() not in {"div", "span", "$", "null"}:
                    return candidate
    return ""


def _amount_pair(block: str) -> tuple[str, str]:
    minimum = _find_after(block, "Award min")
    maximum = _find_after(block, "Award max")
    return minimum, maximum


@register("simpler-grants")
class SimplerGrantsConnector:
    source_key = "simpler-grants"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or SIMPLER_GRANTS_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            headers={"Accept": "text/html,application/xhtml+xml"},
            fallback_content_type="text/html",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        content = raw.content
        link_pattern = re.compile(
            r'href\\?":\\?"/opportunity/([a-f0-9-]+)\\?".{0,220}?children\\?":\\?"([^"\\]+)',
            re.IGNORECASE | re.DOTALL,
        )
        matches = list(link_pattern.finditer(content))
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for index, match in enumerate(matches):
            opportunity_id = match.group(1)
            title = _clean(match.group(2))
            if not title or opportunity_id in seen:
                continue
            seen.add(opportunity_id)
            next_start = matches[index + 1].start() if index + 1 < len(matches) else min(len(content), match.end() + 7000)
            block = content[max(0, match.start() - 1800) : next_start]
            number = _find_after(block, "Number")
            agency = _find_after(block, "Agency") or "Simpler Grants"
            close_date_raw = _find_after(block, "Close date")
            posted_date_raw = _find_after(block, "Posted date")
            min_amount, max_amount = _amount_pair(block)
            amount_parts = [part for part in [min_amount, max_amount] if part]
            summary_parts = [
                f"Number: {number}" if number else "",
                f"Agency: {agency}" if agency else "",
                f"Posted date: {posted_date_raw}" if posted_date_raw else "",
                f"Close date: {close_date_raw}" if close_date_raw else "",
            ]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=agency,
                    country="United States",
                    official_url=SIMPLER_OPPORTUNITY_URL.format(opportunity_id=opportunity_id),
                    summary=" | ".join(part for part in summary_parts if part) or title,
                    categories=["grants", "federal funding"],
                    topics=[agency] if agency else [],
                    raw_text=_clean(block[:2500]),
                    confidence_score=0.84,
                    open_date=_parse_date(posted_date_raw),
                    close_date=_parse_date(close_date_raw),
                    funding_amount_raw=" - ".join(amount_parts) if amount_parts else None,
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if not candidate.official_url.startswith("https://simpler.grants.gov/opportunity/"):
            return ValidationResult(ok=False, reason="URL is outside Simpler Grants")
        return ValidationResult(ok=True)
