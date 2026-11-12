"""EGX session calendar (configurable; overridden by live market status)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.core.timeutil import CAIRO, dt_to_ms, ms_to_dt


@dataclass
class SessionInfo:
    date: str
    open_ms: int
    close_ms: int
    state: str  # pre_open | open | closed | holiday_or_weekend
    source: str  # "calendar" | "provider"

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


class SessionManager:
    def __init__(self, open_hhmm: str, close_hhmm: str, trading_days: set[int]) -> None:
        self.open_t = _parse_hhmm(open_hhmm)
        self.close_t = _parse_hhmm(close_hhmm)
        self.trading_days = trading_days
        self.provider_status: str | None = None  # set from MarketStatistics stream

    def session_for(self, ms: int) -> SessionInfo:
        dt = ms_to_dt(ms, CAIRO)
        d = dt.date()
        o = dt_to_ms(datetime.combine(d, self.open_t, tzinfo=CAIRO))
        c = dt_to_ms(datetime.combine(d, self.close_t, tzinfo=CAIRO))
        if d.weekday() not in self.trading_days:
            state = "holiday_or_weekend"
        elif ms < o:
            state = "pre_open"
        elif ms <= c:
            state = "open"
        else:
            state = "closed"
        source = "calendar"
        if self.provider_status:
            source = "provider"
            s = self.provider_status.lower()
            if s in ("open", "2"):
                state = "open"
            elif s in ("closed", "3"):
                state = "closed"
        return SessionInfo(d.isoformat(), o, c, state, source)

    def session_start_ms(self, ms: int) -> int:
        return self.session_for(ms).open_ms

    def previous_trading_day(self, d: date) -> date:
        x = d - timedelta(days=1)
        while x.weekday() not in self.trading_days:
            x -= timedelta(days=1)
        return x


def _parse_hhmm(v: str) -> time:
    h, m = v.split(":")
    return time(int(h), int(m))
