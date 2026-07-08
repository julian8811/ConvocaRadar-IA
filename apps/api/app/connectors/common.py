from __future__ import annotations

import html
import re
import socket
from datetime import datetime
import unicodedata
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings

CHROMIUM_CONTAINER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
PLAYWRIGHT_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


async def launch_chromium(playwright, *, headless: bool = True):
    return await playwright.chromium.launch(headless=headless, args=CHROMIUM_CONTAINER_ARGS)


async def render_page_html(
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout_ms: int | None = None,
    wait_selector: str | None = None,
    wait_selector_timeout_ms: int = 8000,
    post_wait_ms: int = 500,
    user_agent: str | None = None,
) -> tuple[str, str, str]:
    from urllib.parse import urlparse

    settings = get_settings()
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    request_user_agent = user_agent or settings.scraping_user_agent
    navigation_timeout_ms = timeout_ms or settings.scraping_timeout_seconds * 1000
    from playwright.async_api import async_playwright

    for attempt in range(2):
        try:
            async with async_playwright() as playwright:
                browser = await launch_chromium(playwright)
                try:
                    page = await browser.new_page(user_agent=request_user_agent)

                    async def _route_handler(route) -> None:
                        if route.request.resource_type in PLAYWRIGHT_BLOCKED_RESOURCE_TYPES:
                            await route.abort()
                            return
                        await route.continue_()

                    await page.route("**/*", _route_handler)
                    await page.goto(url, wait_until=wait_until, timeout=navigation_timeout_ms)
                    if wait_selector:
                        try:
                            await page.wait_for_selector(wait_selector, timeout=wait_selector_timeout_ms)
                        except Exception:
                            pass
                    if post_wait_ms > 0:
                        await page.wait_for_timeout(post_wait_ms)
                    final_url = page.url
                    if _is_private_host(urlparse(final_url).hostname or ""):
                        raise ValueError(f"Blocked redirect to unsafe URL: {final_url}")
                    return final_url, await page.content(), "text/html"
                finally:
                    await browser.close()
        except Exception as exc:
            if attempt == 0 and "Executable doesn't exist" in str(exc):
                import subprocess, sys as _sys
                _sys.stdout.flush()
                subprocess.run(
                    [_sys.executable, "-m", "playwright", "install", "chromium", "chromium-headless-shell"],
                    capture_output=True, timeout=180,
                )
                continue
            raise RuntimeError(
                f"Playwright/Chromium not available: {exc}. "
                "Install with: playwright install chromium"
            ) from exc


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
        pass
    else:
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    try:
        addrs = socket.getaddrinfo(host, 80)
        for family, _type, _proto, _cname, sockaddr in addrs:
            raw = sockaddr[0]
            try:
                addr = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
                return True
    except OSError:
        pass
    return False


def is_allowed_host(url: str, allowed_domains: list[str] | tuple[str, ...] | None = None) -> bool:
    from urllib.parse import urlparse
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


def extract_close_date(text: str) -> datetime | None:
    """Extract a deadline/close date from text using Spanish & English patterns.
    Looks for ``fecha de cierre``, ``deadline``, ``hasta el``, etc.
    """
    if not text:
        return None
    for pattern in [
        r"(?:fecha\s+(?:de\s+)?(?:\w+\s+)?(?:cierre|limite|maxima|maxima))\s*[:\-]?\s*([a-z]+\s+\d{1,2},?\s*(?:de\s+)?\d{4})",
        r"(?:cierra|vence|finaliza|termina|deadline|closes)\s+(?:el\s+|on\s+)?(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})",
        r"(?:hasta\s+(?:el\s+)?(?:dia\s+)?)(\d{1,2}\s+de\s+[a-z]+\s+de\s+\d{4})",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date_text(match.group(1))
            if parsed:
                return parsed
    return None


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
    playwright_fallback: bool = True,
    timeout_seconds: int | None = None,
) -> tuple[str, str, str]:
    from urllib.parse import urlparse

    settings = get_settings()
    request_headers = {"User-Agent": settings.scraping_user_agent}
    if headers:
        request_headers.update(headers)
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or _is_private_host(parsed_url.hostname or ""):
        raise ValueError(f"Blocked unsafe URL: {url}")
    request_timeout = timeout_seconds or settings.scraping_timeout_seconds
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        try:
            async with httpx.AsyncClient(
                timeout=request_timeout,
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
    if not playwright_fallback:
        raise last_error or RuntimeError(f"Failed to fetch {url}")
    if _is_private_host(parsed_url.hostname or ""):
        raise last_error or ValueError(f"Blocked unsafe URL: {url}")
    return await render_page_html(
        url,
        user_agent=request_headers["User-Agent"],
        timeout_ms=request_timeout * 1000,
    )


async def fetch_httpx_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    retries: int = 2,
    fallback_content_type: str = "application/octet-stream",
) -> tuple[str, bytes, str]:
    from urllib.parse import urlparse

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
