from datetime import UTC, datetime
from zoneinfo import ZoneInfo
BOGOTA = ZoneInfo("America/Bogota")
def now_bogota() -> datetime:
    return datetime.now(UTC).astimezone(BOGOTA)
def format_bogota(value: datetime | None) -> str:
    if value is None: return "Sin fecha"
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(BOGOTA).strftime("%d/%m/%Y %H:%M")
