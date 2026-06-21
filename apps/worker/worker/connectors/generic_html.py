import json
import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from worker.connectors.common import clean_text, fetch_httpx_text
from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


class GenericHtmlConnector:
    def __init__(self, source_key: str, base_url: str) -> None:
        self.source_key = source_key
        self.base_url = base_url

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    def _title_from_container(self, container) -> tuple[str, str]:
        link = None
        for anchor in container.css("a"):
            href = anchor.attributes.get("href") or ""
            text = (anchor.text() or "").strip()
            if href and text:
                link = anchor
                break
        if link:
            return clean_text(link.text()), link.attributes.get("href") or ""
        heading = container.css_first("h1, h2, h3, h4")
        if heading:
            return clean_text(heading.text()), ""
        text = clean_text(container.text())
        return text[:180], ""

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
        if any(payload.get(field) for field in ("title", "name", "url", "link", "official_url")):
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
                items.extend(self._iter_items(value, _depth + 1))
        if not items:
            for value in payload.values():
                parsed = self._maybe_load_json(value)
                if parsed is not None:
                    value = parsed
                if isinstance(value, list):
                    items.extend(self._iter_items(value, _depth + 1))
                elif isinstance(value, dict):
                    items.extend(self._iter_items(value, _depth + 1))
        return items

    def _collect_ld_json(self, tree: HTMLParser) -> list[dict]:
        candidates: list[dict] = []
        seen_titles: set[str] = set()
        for script in tree.css("script[type='application/ld+json']"):
            content = (script.text() or "").strip()
            if not content:
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            for item in self._iter_items(payload):
                title = str(item.get("name") or item.get("title") or "").strip()
                link = str(item.get("url") or item.get("link") or item.get("official_url") or "").strip()
                if title and link and title not in seen_titles:
                    seen_titles.add(title)
                    candidates.append(item)
        return candidates

    def _collect_embedded_json(self, tree: HTMLParser) -> list[dict]:
        candidates: list[dict] = []
        seen_titles: set[str] = set()
        script_selectors = [
            "script#__NEXT_DATA__",
            "script[type='application/json']",
            "script[type='application/ld+json']",
            "script",
        ]
        for selector in script_selectors:
            for script in tree.css(selector):
                content = (script.text() or "").strip()
                if not content:
                    continue
                payload = None
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError:
                    if "self.__next_f.push" in content or "__NEXT_DATA__" in content:
                        fragments = re.findall(r"\{.*\}", content, flags=re.DOTALL)
                        for fragment in fragments[:6]:
                            try:
                                payload = json.loads(fragment)
                                break
                            except json.JSONDecodeError:
                                continue
                if payload is None:
                    continue
                for item in self._iter_items(payload):
                    title = str(item.get("name") or item.get("title") or item.get("headline") or "").strip()
                    link = str(item.get("url") or item.get("link") or item.get("official_url") or "").strip()
                    if title and link and title not in seen_titles:
                        seen_titles.add(title)
                        candidates.append(item)
        return candidates

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if raw.content_type.startswith("application/json") or raw.content.lstrip().startswith("{"):
            try:
                payload = json.loads(raw.content)
            except json.JSONDecodeError:
                payload = {}
            items = self._iter_items(payload)
            candidates: list[OpportunityCandidate] = []
            for item in items:
                title = str(item.get("title") or item.get("name") or "").strip()
                link = str(item.get("url") or item.get("link") or item.get("official_url") or "").strip()
                if not title or not link:
                    continue
                summary = str(item.get("summary") or item.get("description") or title).strip()
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity=str(item.get("entity") or self.source_key),
                        country=str(item.get("country") or "Por validar"),
                        official_url=link,
                        summary=summary[:700] or title,
                        categories=[str(value) for value in (item.get("categories") or [])[:4] if isinstance(value, str)],
                        topics=[str(value) for value in (item.get("topics") or [])[:4] if isinstance(value, str)],
                        raw_text=summary[:2500],
                        confidence_score=0.55,
                    )
                )
            return candidates[:50]

        tree = HTMLParser(raw.content)
        ld_json_items = self._collect_ld_json(tree)
        embedded_json_items = self._collect_embedded_json(tree)
        if embedded_json_items:
            ld_json_items.extend(item for item in embedded_json_items if item not in ld_json_items)
        if ld_json_items:
            candidates: list[OpportunityCandidate] = []
            seen: set[str] = set()
            for item in ld_json_items:
                title = str(item.get("title") or item.get("name") or "").strip()
                link = str(item.get("url") or item.get("link") or item.get("official_url") or "").strip()
                if link and not link.startswith(("http://", "https://")):
                    link = urljoin(raw.url, link)
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                summary = str(item.get("description") or item.get("summary") or title).strip()
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity=str(item.get("entity") or self.source_key),
                        country=str(item.get("country") or "Por validar"),
                        official_url=link,
                        summary=summary[:700] or title,
                        categories=[str(value) for value in (item.get("categories") or [])[:4] if isinstance(value, str)] or ["opportunity"],
                        topics=[str(value) for value in (item.get("topics") or [])[:4] if isinstance(value, str)],
                        raw_text=summary[:2500],
                        confidence_score=0.72,
                    )
                )
            if candidates:
                return candidates[:50]
        candidates: list[OpportunityCandidate] = []
        candidates_seen: set[str] = set()
        selectors = [
            "article",
            "article a",
            ".card",
            ".card a",
            ".card-body",
            ".card-content",
            ".views-row",
            ".views-row a",
            ".teaser",
            "li",
            "tr",
            "[class*='grant']",
            "[class*='call']",
            "[class*='opportunity']",
            "[class*='convoc']",
        ]
        for selector in selectors:
            for container in tree.css(selector):
                title, href = self._title_from_container(container)
                text = (container.text() or "").strip()
                lowered = f"{title} {text}".lower()
                if not title or not href:
                    continue
                if not any(
                    word in lowered
                    for word in [
                        "convocatoria",
                        "grant",
                        "funding",
                        "beca",
                        "call",
                        "scholarship",
                        "award",
                        "program",
                        "programme",
                        "opportunity",
                        "opportunities",
                        "proposal",
                        "proposals",
                        "open call",
                        "request for applications",
                        "request for proposals",
                    ]
                ):
                    continue
                official_url = urljoin(raw.url, href)
                if official_url in candidates_seen:
                    continue
                candidates_seen.add(official_url)
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity=self.source_key,
                        country="Por validar",
                        official_url=official_url,
                        summary=text[:700] or title,
                        raw_text=text[:2500],
                        confidence_score=0.55,
                    )
                )
        if not candidates:
            for link in tree.css("a"):
                text = (link.text() or "").strip()
                href = link.attributes.get("href")
                if not text or not href:
                    continue
                lowered = text.lower()
                if any(
                    word in lowered
                    for word in [
                        "convocatoria",
                        "grant",
                        "funding",
                        "beca",
                        "call",
                        "scholarship",
                        "award",
                        "program",
                        "programme",
                        "opportunity",
                        "opportunities",
                        "proposal",
                        "proposals",
                        "open call",
                        "request for applications",
                        "request for proposals",
                    ]
                ):
                    official_url = urljoin(raw.url, href)
                    if official_url in candidates_seen:
                        continue
                    candidates_seen.add(official_url)
                    candidates.append(
                        OpportunityCandidate(
                            title=text[:180],
                            entity=self.source_key,
                            country="Por validar",
                            official_url=official_url,
                            summary=text,
                            raw_text=text,
                            confidence_score=0.45,
                        )
                    )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and candidate.official_url))
