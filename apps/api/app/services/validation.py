"""Validation utilities — pure functions, no IO except url_is_reachable.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

import ipaddress
import re
import time
from functools import lru_cache
from urllib.parse import urlparse

import httpx


def is_noise_title(title: str | None) -> bool:
    """Check if an opportunity title looks like scraping noise."""
    if not title:
        return True
    cleaned = title.strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if "@" in cleaned:
        return True
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    if len(cleaned) < 6 and " " not in cleaned:
        return True
    if any(
        marker in lowered
        for marker in (
            "color:",
            "background-color:",
            "font-weight:",
            "display:",
            "justify-content:",
            ".box-address",
            ".caja",
            "budgetyearscolumns",
        )
    ):
        return True
    if "{" in cleaned or "}" in cleaned or "<style" in lowered or "<script" in lowered:
        return True

    if cleaned == cleaned.upper() and len(cleaned) > 30:
        if re.search(r"[A-Z]{3,}\s*[-–—]\s*\d{2,}", cleaned):
            return True
    years = re.findall(r"\b(20\d{2})\b", cleaned)
    if len(years) >= 2 and len(set(years)) <= 2:
        return True
    upper_ratio = sum(1 for c in cleaned if c.isupper()) / max(len(cleaned), 1)
    if upper_ratio > 0.8 and len(cleaned) > 60 and re.search(r"\b(20\d{2})\b", cleaned):
        return True
    if re.search(
        r"\b(CONVOCATORIA|AVISO|LICITACION|LICITACIÓN|CONCURSO|PROCESO)\b",
        cleaned,
        re.IGNORECASE,
    ) and re.search(r"[A-Z]{3,}\s*[-–—]\s*\d{3,}", cleaned):
        return True
    if re.search(r"\b(cliquer ici|click here|read more|download pdf|view pdf|pdf)\b", lowered):
        return True

    informational_markers = [
        "sobre nosotros",
        "about us",
        "about the",
        "our team",
        "our mission",
        "our work",
        "quienes somos",
        "quiénes somos",
        "nuestra historia",
        "nuestro equipo",
        "directorio",
        "contacto",
        "contact us",
        "términos",
        "terms and conditions",
        "privacy policy",
        "política de privacidad",
        "politica de privacidad",
        "preguntas frecuentes",
        "faq",
        "oficina",
        "office",
        "what we do",
        "cómo trabajamos",
        "como trabajamos",
        "nuestro impacto",
        "our impact",
        "our approach",
        "nuestro enfoque",
        "transparencia",
        "transparency",
        "informes",
        "reports",
        "publicaciones",
        "publications",
        "noticias",
        "news",
        "eventos",
        "events",
        "historias",
        "stories",
        "member states",
        "estados miembros",
        "governance",
        "gobernanza",
        "partners",
        "socios",
        "aliados",
        "our leadership",
        "nuestro liderazgo",
        "director ejecutivo",
        "executive director",
        "deputy director",
        "board",
        "consejo",
    ]
    if any(marker in lowered for marker in informational_markers):
        return True
    return False


def is_noise_payload(*parts: str | None) -> bool:
    """Check if a payload looks like scraping noise."""
    title = parts[0] if parts else None
    if is_noise_title(title):
        return True
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return any(
        marker in text.lower()
        for marker in (
            "color: white",
            "background-color:",
            "font-weight: bold",
            "text-decoration: underline",
            "display: flex",
            "justify-content: center",
        )
    )


def is_private_url(url: str) -> bool:
    """Check if a URL points to a private/internal address."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True
    host = parsed.hostname
    if not host:
        return True
    host = host.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    if (
        host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".lan")
        or host.endswith(".corp")
    ):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def is_public_http_url(url: str | None) -> bool:
    """Check if a URL is a public HTTP(S) URL."""
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and not is_private_url(url)


def validate_source_url(source: object) -> None:
    """Validate a source's base URL against private-URL and allowed-domains rules."""
    # Lazy import to avoid circular dependency at module level
    from app.models import Source

    if not isinstance(source, Source):
        # Accept duck-typing for tests
        base_url = getattr(source, "base_url", None)
        allowed_domains = getattr(source, "allowed_domains", None)
    else:
        base_url = source.base_url
        allowed_domains = source.allowed_domains

    if is_private_url(base_url):
        raise ValueError("Source URL is not allowed")
    host = urlparse(base_url).hostname or ""
    if allowed_domains and not any(
        host == allowed or host.endswith(f".{allowed}") for allowed in allowed_domains
    ):
        raise ValueError("Source URL host is outside the allowed domains")


_url_cache: dict[str, tuple[bool, float]] = {}
_url_cache_ttl_seconds: float = 24 * 3600
_url_cache_maxsize: int = 4096


def _get_cached_url(url: str) -> bool | None:
    entry = _url_cache.get(url)
    if entry is None:
        return None
    value, ts = entry
    if (time.monotonic() - ts) < _url_cache_ttl_seconds:
        return value
    _url_cache.pop(url, None)
    return None


def _set_cached_url(url: str, value: bool) -> None:
    if len(_url_cache) >= _url_cache_maxsize:
        oldest = next(iter(_url_cache))
        _url_cache.pop(oldest, None)
    _url_cache[url] = (value, time.monotonic())


def _clear_url_cache() -> None:
    _url_cache.clear()


async def async_url_is_reachable(url: str) -> bool:
    """Async non-blocking variant — uses shared AsyncClient pool with 24h TTL cache."""
    if not is_public_http_url(url):
        return False
    cached = _get_cached_url(url)
    if cached is not None:
        return cached
    try:
        from app.core.http_client import http_client

        client = await http_client()
        headers = {"User-Agent": "ConvocaRadar/1.0"}
        response = await client.head(url, follow_redirects=True, timeout=5.0, headers=headers)
        if response.status_code in {405, 501}:
            response = await client.get(url, follow_redirects=True, timeout=5.0, headers=headers)
        result = 200 <= response.status_code < 400
        _set_cached_url(url, result)
        return result
    except httpx.HTTPError:
        _set_cached_url(url, False)
        return False


def url_is_reachable(url: str) -> bool:
    """Sync wrapper — kept for backward compat (blocking). Prefer async_url_is_reachable.

    Uses TTL cache shared with async variant to avoid duplicate HEADs.
    """
    if not is_public_http_url(url):
        return False
    cached = _get_cached_url(url)
    if cached is not None:
        return cached
    try:
        from app.core.http_client import sync_http_client

        client = sync_http_client()
        headers = {"User-Agent": "ConvocaRadar/1.0"}
        response = client.head(url, follow_redirects=True, timeout=5.0, headers=headers)
        if response.status_code in {405, 501}:
            response = client.get(url, follow_redirects=True, timeout=5.0, headers=headers)
        result = 200 <= response.status_code < 400
        _set_cached_url(url, result)
        return result
    except httpx.HTTPError:
        _set_cached_url(url, False)
        return False


# Keep lru_cache compatibility for tests that call cache_clear/cache_info
try:
    _lru = lru_cache(maxsize=4096)(lambda x: x)  # dummy to expose type
except Exception:
    pass

# Expose cache helpers on sync function for test compatibility
url_is_reachable.cache_clear = _clear_url_cache  # type: ignore[attr-defined]
url_is_reachable.cache_info = lambda: None  # type: ignore[attr-defined]


def slugify(value: str) -> str:
    """Convert a string to a URL-safe slug."""
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "item"


def normalize_official_url(url: str | None) -> str | None:
    """Normalize a URL to its canonical form."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
