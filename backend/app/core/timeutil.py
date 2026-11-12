"""Time helpers. Internally all event times are UTC epoch milliseconds (int)."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")


def now_ms() -> int:
    return int(time.time() * 1000)


def ms_to_dt(ms: int, tz: ZoneInfo | timezone = timezone.utc) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=tz)


def dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed; attach a timezone first")
    return int(dt.timestamp() * 1000)


def parse_provider_time(value: str | None, assume_tz: ZoneInfo = CAIRO) -> int | None:
    """Parse a provider timestamp string into UTC epoch ms.

    Naive strings are interpreted in ``assume_tz`` (EGX feeds are Cairo local).
    Returns ``None`` when the value cannot be parsed - callers must then use
    the receive time AND mark the timestamp as receive-time based.
    """
    if not value:
        return None
    v = value.strip()
    # .NET style "/Date(1690000000000)/"
    if v.startswith("/Date(") and v.endswith(")/"):
        try:
            return int(v[6:-2].split("+")[0].split("-")[0])
        except ValueError:
            return None
    for candidate in (v, v.replace(" ", "T", 1)):
        try:
            dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=assume_tz)
            return dt_to_ms(dt)
        except ValueError:
            continue
    # Time-of-day only, e.g. "13:45:12" -> today in assume_tz
    try:
        t = datetime.strptime(v, "%H:%M:%S").time()
        d = datetime.now(assume_tz).date()
        return dt_to_ms(datetime.combine(d, t, tzinfo=assume_tz))
    except ValueError:
        return None


def cairo_date(ms: int) -> date:
    return ms_to_dt(ms, CAIRO).date()


def cairo_iso(ms: int) -> str:
    return ms_to_dt(ms, CAIRO).isoformat()
