from __future__ import annotations

import html
import re
from datetime import datetime
import unicodedata
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx

from worker.config import get_settings


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?:[.#]?[A-Za-z][\w-]*\s*\{[^{}]*\}\s*)+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", html.unescape(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def looks_like_noise_text(value: str | None) -> bool:
    text = clean_text(value).lower()
    if not text:
        return False
    if "{" in text or "}" in text:
        return True
    return bool(
        re.search(
            r"(<style[\s\S]*?</style>|<script[\s\S]*?</script>|color:\s*white|background-color:|\.box-address|\.caja|display:\s*flex|justify-content:\s*center|font-weight:\s*bold|text-decoration:\s*underline|font-size:|padding:|margin:|border:|budgetyearscolumns|plannedopeningdate|deadlinedate|action:|action\"?:|action'?:)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_private_host(hostname: str) -> bool:
    host = hostname.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".lan") or host.endswith(".corp"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def is_allowed_host(url: str, allowed_domains: list[str] | tuple[str, ...] | None = None) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if _is_private_host(host):
        return False
    if not allowed_domains:
        return True
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def safe_urljoin(base_url: str, href: str | None) -> str:
    return urljoin(base_url, href or "")


def parse_date_text(text: str | None) -> datetime | None:
    value = clean_text(text)
    if not value:
        return None
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", value)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    slash_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", value)
    if slash_match:
        for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(slash_match.group(1), fmt)
            except ValueError:
                continue
    month_match = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})\b", value)
    if month_match:
        candidate = f"{month_match.group(1).title()} {month_match.group(2)}, {month_match.group(3)}"
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    spanish_month_match = re.search(r"\b([A-Za-záéíóúñ]+)\s+(\d{1,2}),\s+(\d{4})\b", value, flags=re.IGNORECASE)
    if spanish_month_match:
        months = {
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "abril": 4,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "agosto": 8,
            "septiembre": 9,
            "setiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12,
        }
        month = months.get(spanish_month_match.group(1).lower())
        if month:
            try:
                return datetime(int(spanish_month_match.group(3)), month, int(spanish_month_match.group(2)))
            except ValueError:
                pass
    spanish_match = re.search(r"\b(\d{1,2})\s+de\s+([A-Za-záéíóúñ]+)\s+de\s+(\d{4})\b", value, flags=re.IGNORECASE)
    if spanish_match:
        months = {
            "enero": 1,
            "febrero": 2,
            "marzo": 3,
            "abril": 4,
            "mayo": 5,
            "junio": 6,
            "julio": 7,
            "agosto": 8,
            "septiembre": 9,
            "setiembre": 9,
            "octubre": 10,
            "noviembre": 11,
            "diciembre": 12,
        }
        month = months.get(spanish_match.group(2).lower())
        if month:
            try:
                return datetime(int(spanish_match.group(3)), month, int(spanish_match.group(1)))
            except ValueError:
                pass
    return None


def unique_links(links: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        normalized = clean_text(link)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


async def fetch_httpx_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    retries: int = 2,
    fallback_content_type: str = "text/html",
) -> tuple[str, str, str]:
    settings = get_settings()
    request_headers = {"User-Agent": settings.scraping_user_agent}
    if headers:
        request_headers.update(headers)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        try:
            async with httpx.AsyncClient(
                timeout=settings.scraping_timeout_seconds,
                headers=request_headers,
                follow_redirects=True,
            ) as client:
                response = await client.request(method, url, json=payload)
                if _is_private_host(urlparse(str(response.url)).hostname or ""):
                    raise ValueError(f"Blocked redirect to unsafe URL: {response.url}")
                response.raise_for_status()
                content_type = response.headers.get("content-type", fallback_content_type)
                return str(response.url), response.text, content_type
        except Exception as exc:  # pragma: no cover - network fallback path
            last_error = exc
            if attempt + 1 >= retries:
                break
    if _is_private_host(parsed_url.hostname or ""):
        raise last_error or ValueError(f"Blocked unsafe URL: {url}")
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await browser.new_page(user_agent=request_headers["User-Agent"])
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.scraping_timeout_seconds * 1000)
            await page.wait_for_timeout(1500)
            final_url = page.url
            if _is_private_host(urlparse(final_url).hostname or ""):
                raise ValueError(f"Blocked redirect to unsafe URL: {final_url}")
            return final_url, await page.content(), fallback_content_type
        finally:
            await browser.close()
    raise last_error or RuntimeError(f"Failed to fetch {url}")


async def fetch_httpx_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    retries: int = 2,
    fallback_content_type: str = "application/octet-stream",
) -> tuple[str, bytes, str]:
    settings = get_settings()
    request_headers = {"User-Agent": settings.scraping_user_agent}
    if headers:
        request_headers.update(headers)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        try:
            async with httpx.AsyncClient(
                timeout=settings.scraping_timeout_seconds,
                headers=request_headers,
                follow_redirects=True,
            ) as client:
                response = await client.request(method, url, json=payload)
                if _is_private_host(urlparse(str(response.url)).hostname or ""):
                    raise ValueError(f"Blocked redirect to unsafe URL: {response.url}")
                response.raise_for_status()
                content_type = response.headers.get("content-type", fallback_content_type)
                return str(response.url), response.content, content_type
        except Exception as exc:  # pragma: no cover - network fallback path
            last_error = exc
            if attempt + 1 >= retries:
                break
    raise last_error or RuntimeError(f"Failed to fetch {url}")
