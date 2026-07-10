"""DOM monitoring utility — hash tracking and structural change detection.

Provides pure functions for:
- Normalizing HTML (stripping dynamic content before hashing)
- Computing a deterministic SHA256 hash of normalized HTML
- Detecting structural changes between two hashes
- Extracting item counts from list selectors
"""
from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Patterns for content to strip during normalization
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TIMESTAMP_ATTR_RE = re.compile(r'\s+(data-(?:timestamp|date|time|added|updated|modified|created|expires|published|generated))="[^"]*"', re.IGNORECASE)
_ANALYTICS_PARAM_RE = re.compile(r"(\?|&)(utm_[^&=]+|gclid|fbclid|ref|source|mc_cid|mc_eid)=[^&\s\"'>]+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_html(html_content: str | None) -> str:
    """Normalize HTML content by stripping dynamic/noise elements.

    Removes scripts, styles, HTML comments, timestamp/data attributes,
    analytics tracking parameters, and collapses whitespace.

    Args:
        html_content: Raw HTML string or None.

    Returns:
        Normalized HTML string suitable for deterministic hashing.
    """
    if not html_content:
        return ""

    content: str = html_content

    # Strip scripts and their content
    content = _SCRIPT_RE.sub("", content)
    # Strip styles and their content
    content = _STYLE_RE.sub("", content)
    # Strip HTML comments
    content = _COMMENT_RE.sub("", content)
    # Strip timestamp/data attributes
    content = _TIMESTAMP_ATTR_RE.sub("", content)
    # Strip analytics tracking params from URLs
    content = _ANALYTICS_PARAM_RE.sub("", content)
    # Collapse all whitespace
    content = _WHITESPACE_RE.sub(" ", content)

    return content.strip()


def compute_dom_hash(html_content: str) -> str:
    """Compute a deterministic SHA256 hash of normalized HTML.

    The HTML is normalized first (stripping scripts, styles, timestamps,
    analytics params, etc.) so that the hash only reflects structural
    changes, not dynamic content differences.

    Args:
        html_content: Raw HTML content to hash.

    Returns:
        A 64-character hex string (SHA256 digest).
    """
    normalized = normalize_html(html_content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def detect_structural_change(
    old_hash: str | None,
    new_hash: str,
    threshold: float = 0.4,
) -> bool:
    """Detect whether the DOM has structurally changed.

    Uses hash comparison — different hashes mean a structural change.
    The threshold parameter is accepted for API compatibility with future
    fuzzy comparison but currently uses binary hash comparison.

    Args:
        old_hash: Previous DOM hash, or None if no previous hash exists.
        new_hash: Current DOM hash.
        threshold: Must be between 0.0 and 1.0. Reserved for future use.

    Returns:
        True if the DOM has structurally changed (or old_hash is None).

    Raises:
        ValueError: If threshold is outside [0.0, 1.0].
    """
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(
            f"Threshold must be between 0.0 and 1.0, got {threshold}"
        )

    if old_hash is None:
        return True

    return old_hash != new_hash


def extract_list_item_count(
    html_content: str,
    selectors: list[str],
) -> int:
    """Count items matching any of the given CSS selectors.

    Tries each selector in order and returns the count from the first
    selector that matches.

    Args:
        html_content: Raw HTML content.
        selectors: List of CSS selectors to try (fallback chain).

    Returns:
        Number of matching elements, or 0 if none match.
    """
    if not html_content or not selectors:
        return 0

    from selectolax.parser import HTMLParser

    tree = HTMLParser(html_content)

    for selector in selectors:
        items = tree.css(selector)
        if items:
            return len(items)

    return 0
