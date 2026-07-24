"""Text normalization helpers for imported source content."""
def repair_mojibake(value: str | None) -> str:
    if not value or not any(token in value for token in ("Ã", "Â", "â")):
        return value or ""
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if "�" not in repaired else value
