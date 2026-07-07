import asyncio
import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.connectors.common import clean_text, fetch_httpx_text, looks_like_noise_text, parse_date_text
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult

DEEP_FETCH_LIMIT = 10
DETAIL_PAGE_TIMEOUT = 15


CLOSED_KEYWORDS = (
    "closed",
    "cerrado",
    "application closed",
    "call closed",
    "closed call",
    "cierre cerrado",
)
DATE_FIELDS = (
    "close_date",
    "closeDate",
    "deadline",
    "deadlineDate",
    "deadline_date",
    "closing_date",
    "closingDate",
    "endDate",
    "dueDate",
    "application_deadline",
)


class GenericHtmlConnector:
    # Common URL path patterns that government/convocatoria portals use
    FALLBACK_PATTERNS = (
        "/convocatorias",
        "/es/convocatorias",
        "/convocatorias-abiertas",
        "/convocatorias-concursos",
        "/convocatorias-y-concursos",
        "/convocatorias/",
        "/oportunidades",
        "/web/guest/convocatorias",
        "/web/entidad/convocatorias",
        "/tramites-y-servicios/convocatorias",
        "/tramites-servicios/convocatorias",
        "/seccion/convocatorias",
        "/node/41",  # Common Drupal pattern
    )

    def __init__(self, source_key: str, base_url: str, *, entity_name: str | None = None, default_country: str | None = None, default_categories: list[str] | None = None) -> None:
        self.source_key = source_key
        self.base_url = base_url
        self._entity_name = entity_name or source_key
        self._default_country = default_country or "Por validar"
        self._default_categories = default_categories or []
        self._resolved_url: str | None = None

    async def _try_url(self, url: str) -> tuple[str, str, str] | None:
        """Try fetching a URL, return (final_url, content, content_type) or None."""
        try:
            return await fetch_httpx_text(url, fallback_content_type="text/html")
        except Exception:
            return None

    def _parent_paths(self, url: str) -> list[str]:
        """Generate parent paths from most specific to domain root."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.hostname}"
        paths = parsed.path.rstrip("/").split("/")
        parents: list[str] = []
        for i in range(len(paths), 0, -1):
            parent = domain + "/".join(paths[:i])
            if parent != url.rstrip("/"):
                parents.append(parent)
        parents.append(domain)
        return parents

    async def _resolve_base_url(self) -> str:
        """Try original URL, then parent paths, fallback patterns, then homepage."""
        # 1. Try original URL first
        result = await self._try_url(self.base_url)
        if result is not None:
            self._resolved_url = result[0]
            return self._resolved_url

        # 2. Try parent paths (e.g. /a/b/c → /a/b, /a, /)
        parsed = urlparse(self.base_url)
        domain = f"{parsed.scheme}://{parsed.hostname}"

        for parent in self._parent_paths(self.base_url):
            if parent == domain:
                continue  # Will try as last resort
            result = await self._try_url(parent)
            if result is not None:
                self._resolved_url = result[0]
                return self._resolved_url

        # 3. Try common fallback patterns on domain root
        for path in self.FALLBACK_PATTERNS:
            test_url = urljoin(domain, path)
            if test_url == self.base_url:
                continue
            result = await self._try_url(test_url)
            if result is not None:
                self._resolved_url = result[0]
                return self._resolved_url

        # 4. Last resort: try domain homepage and let parse() find convocatorias links
        result = await self._try_url(domain)
        if result is not None:
            self._resolved_url = result[0]
            return self._resolved_url

        return self.base_url

    async def fetch(self) -> RawSourceResult:
        resolved_url = await self._resolve_base_url()
        final_url, content, content_type = await fetch_httpx_text(resolved_url, fallback_content_type="text/html")
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

    def _candidate_close_date(self, item: dict, text: str | None = None) -> datetime | None:
        for key in DATE_FIELDS:
            value = item.get(key)
            if isinstance(value, list):
                for entry in value:
                    parsed = parse_date_text(str(entry))
                    if parsed:
                        return parsed
            elif isinstance(value, dict):
                for nested_key in ("value", "date", "content"):
                    nested_value = value.get(nested_key)
                    if nested_value:
                        parsed = parse_date_text(str(nested_value))
                        if parsed:
                            return parsed
            elif value:
                parsed = parse_date_text(str(value))
                if parsed:
                    return parsed
        return parse_date_text(text)

    def _is_closed(self, title: str, summary: str, raw_text: str, close_date: datetime | None) -> bool:
        if close_date and close_date.date() < datetime.now(UTC).date():
            return True
        normalized = f"{title} {summary} {raw_text}".lower()
        return any(keyword in normalized for keyword in CLOSED_KEYWORDS) or looks_like_noise_text(normalized)

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
                close_date = self._candidate_close_date(item, summary)
                raw_text = summary[:2500]
                if self._is_closed(title, summary, raw_text, close_date):
                    continue
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity=str(item.get("entity") or self._entity_name),
                        country=str(item.get("country") or self._default_country),
                        official_url=link,
                        summary=summary[:700] or title,
                        categories=[str(value) for value in (item.get("categories") or [])[:4] if isinstance(value, str)],
                        topics=[str(value) for value in (item.get("topics") or [])[:4] if isinstance(value, str)],
                        raw_text=raw_text,
                        confidence_score=0.55,
                        close_date=close_date,
                    )
                )
            if candidates:
                candidates = await self._deep_fetch_candidates(candidates)
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
                close_date = self._candidate_close_date(item, summary)
                raw_text = summary[:2500]
                if self._is_closed(title, summary, raw_text, close_date):
                    continue
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity=str(item.get("entity") or self._entity_name),
                        country=str(item.get("country") or self._default_country),
                        official_url=link,
                        summary=summary[:700] or title,
                        categories=[str(value) for value in (item.get("categories") or [])[:4] if isinstance(value, str)] or ["opportunity"],
                        topics=[str(value) for value in (item.get("topics") or [])[:4] if isinstance(value, str)],
                        raw_text=raw_text,
                        confidence_score=0.72,
                        close_date=close_date,
                    )
                )
            if candidates:
                candidates = await self._deep_fetch_candidates(candidates)
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
                if looks_like_noise_text(title) or looks_like_noise_text(text):
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
                close_date = parse_date_text(text)
                if self._is_closed(title, text, text[:2500], close_date):
                    continue
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity=self._entity_name,
                        country=self._default_country,
                        official_url=official_url,
                        summary=text[:700] or title,
                        raw_text=text[:2500],
                        confidence_score=0.55,
                        close_date=close_date,
                    )
                )
        if not candidates:
            for link in tree.css("a"):
                text = (link.text() or "").strip()
                href = link.attributes.get("href")
                if not text or not href:
                    continue
                lowered = text.lower()
                if looks_like_noise_text(text):
                    continue
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
                    close_date = parse_date_text(text)
                    if self._is_closed(text, text, text[:2500], close_date):
                        continue
                    candidates.append(
                        OpportunityCandidate(
                            title=text[:180],
                            entity=self._entity_name,
                            country=self._default_country,
                            official_url=official_url,
                            summary=text,
                            raw_text=text,
                            confidence_score=0.45,
                            close_date=close_date,
                        )
                    )
        # Deep fetch: enrich low-confidence candidates with detail-page data
        if candidates:
            candidates = await self._deep_fetch_candidates(candidates)
        return candidates[:50]

    async def _enrich_from_detail(self, url: str) -> dict | None:
        """Fetch a detail page and extract structured data.

        Returns a dict with keys: title, summary, close_date, categories,
        funding_amount_raw, or None if the page can't be fetched or has no
        usable data.
        """
        try:
            _, content, content_type = await fetch_httpx_text(
                url,
                timeout_seconds=DETAIL_PAGE_TIMEOUT,
                retries=1,
            )
        except Exception:
            return None

        result: dict = {}

        # 1. Try JSON-LD for highest-confidence data
        tree = HTMLParser(content)
        for script in tree.css("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.text() or "{}")
            except json.JSONDecodeError:
                continue
            for item in self._iter_items(payload):
                title = str(item.get("name") or item.get("title") or "").strip()
                if title:
                    result["title"] = title
                desc = str(item.get("description") or item.get("summary") or "").strip()
                if desc:
                    result["summary"] = desc
                cd = self._candidate_close_date(item)
                if cd:
                    result["close_date"] = cd
                cats = [str(v) for v in (item.get("categories") or [])[:4] if isinstance(v, str)]
                if cats:
                    result["categories"] = cats
                amount = str(item.get("funding", item.get("fundingAmount", ""))).strip()
                if amount:
                    result["funding_amount_raw"] = amount
                break  # First valid item is enough

        # 2. Meta / Open Graph tags (fill gaps not covered by JSON-LD)
        og_title = tree.css_first("meta[property='og:title']")
        if og_title and "title" not in result:
            value = (og_title.attributes.get("content") or "").strip()
            if value:
                result["title"] = value
        og_desc = tree.css_first("meta[property='og:description']")
        if og_desc and "summary" not in result:
            value = (og_desc.attributes.get("content") or "").strip()
            if value:
                result["summary"] = value
        meta_desc = tree.css_first("meta[name='description']")
        if meta_desc and "summary" not in result:
            value = (meta_desc.attributes.get("content") or "").strip()
            if value:
                result["summary"] = value

        # 3. h1 fallback for title
        if "title" not in result:
            h1 = tree.css_first("h1")
            if h1:
                value = clean_text(h1.text())
                if value:
                    result["title"] = value

        # 4. Article / main content for summary (last resort)
        if "summary" not in result:
            for tag in ("article", "[role='main']", "main", ".content", "#content"):
                el = tree.css_first(tag)
                if el:
                    value = clean_text(el.text())[:700]
                    if value:
                        result["summary"] = value
                        break

        # 5. Scan all text for dates not captured by JSON-LD
        if "close_date" not in result:
            body = tree.css_first("body")
            if body:
                all_text = clean_text(body.text())
                cd = parse_date_text(all_text)
                if cd:
                    result["close_date"] = cd

        return result if result.get("title") else None

    async def _deep_fetch_candidates(
        self,
        candidates: list[OpportunityCandidate],
    ) -> list[OpportunityCandidate]:
        """Enrich low-confidence candidates by fetching their detail pages.

        Only processes candidates with confidence < 0.7, up to
        ``DEEP_FETCH_LIMIT`` per call. Each detail page fetch is independent
        and runs concurrently.
        """
        to_enrich = [c for c in candidates if c.confidence_score < 0.7][:DEEP_FETCH_LIMIT]
        if not to_enrich:
            return candidates

        tasks = {c.official_url: self._enrich_from_detail(c.official_url) for c in to_enrich}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        url_to_data: dict[str, dict | None] = {}
        for url, task in zip(tasks, results):
            url_to_data[url] = task if isinstance(task, dict) else None

        enriched: list[OpportunityCandidate] = []
        for c in candidates:
            detail = url_to_data.get(c.official_url)
            if detail:
                enriched.append(
                    OpportunityCandidate(
                        title=(detail.get("title") or c.title)[:180],
                        entity=c.entity,
                        country=c.country,
                        official_url=c.official_url,
                        summary=(detail.get("summary") or c.summary)[:700],
                        categories=detail.get("categories", c.categories or self._default_categories),
                        raw_text=c.raw_text,
                        confidence_score=0.82,  # Confirmed via detail page
                        close_date=detail.get("close_date") or c.close_date,
                        funding_amount_raw=detail.get("funding_amount_raw") or c.funding_amount_raw,
                    )
                )
            else:
                enriched.append(c)
        return enriched

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if self._is_closed(candidate.title, candidate.summary, candidate.raw_text, candidate.close_date):
            return ValidationResult(ok=False, reason="Opportunity appears closed")
        return ValidationResult(ok=True)
