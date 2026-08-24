"""Text normalization helpers for imported source content."""
from html import escape, unescape


def safe_escape(value: str | None) -> str:
    """HTML-escape *unescaped* text so already-encoded entities are not double-escaped.

    Source data from scrapers may contain HTML entities (``&aacute;``,
    ``&ntilde;``, etc.) that were part of the original web page.  A plain
    ``html.escape()`` would turn ``&aacute;`` into ``&amp;aacute;``,
    producing literal ``&aacute;`` in the rendered output.  We unescape
    first so every character is decoded to its real Unicode codepoint,
    then escape exactly once.
    """
    return escape(unescape(value or ""))


def repair_mojibake(value: str | None) -> str:
    if not value or not any(token in value for token in ("Ã", "Â", "â")):
        return value or ""
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if "�" not in repaired else value
