from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LOGGER = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def market_tz(name: str | None = None) -> ZoneInfo:
    """Resolve a configured IANA zone name, falling back to Eastern."""
    if not name:
        return ET
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        _LOGGER.warning(
            "Unknown market timezone %r; falling back to America/New_York", name
        )
        return ET


def market_now(hass, tz: ZoneInfo | None = None) -> datetime:
    from homeassistant.util import dt as dt_util
    return dt_util.now().astimezone(tz or ET)


def market_today(hass, tz: ZoneInfo | None = None) -> date:
    return market_now(hass, tz).date()


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    """Whether now falls inside the quiet window.

    The window wraps past midnight when start > end, which the default
    22:00 -> 08:35 does. Compares full times so the minute component counts.
    """
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def next_market_time(
    now: datetime, hour: int, minute: int, tz: ZoneInfo
) -> datetime:
    """Next absolute instant at which the market clock reads hour:minute.

    Resolved a calendar day at a time in the market zone rather than by adding
    24 hours, so the result stays correct across DST transitions -- in either
    the market's zone or Home Assistant's, which need not shift on the same
    date. A wall time that does not exist on a spring-forward day resolves to
    the following instant rather than being skipped.
    """
    local = now.astimezone(tz)
    for offset in range(3):
        day = (local + timedelta(days=offset)).date()
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        if candidate > now:
            return candidate
    return now + timedelta(days=1)


def parse_pay_windows(windows_str: str) -> list[tuple[int, int]]:
    result = []
    for part in windows_str.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            result.append((int(a.strip()), int(b.strip())))
    return result


def in_pay_window(day: int, windows: list[tuple[int, int]]) -> bool:
    for start, end in windows:
        if start <= end:
            if start <= day <= end:
                return True
        else:
            if day >= start or day <= end:
                return True
    return False


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


class NYSECalendar:
    @staticmethod
    def holidays(year: int) -> set[date]:
        days = set()
        days.add(_observed(date(year, 1, 1)))
        days.add(_nth_weekday(year, 1, 0, 3))
        days.add(_nth_weekday(year, 2, 0, 3))
        days.add(_easter(year) - timedelta(days=2))
        days.add(_last_weekday(year, 5, 0))
        days.add(_observed(date(year, 6, 19)))
        days.add(_observed(date(year, 7, 4)))
        days.add(_nth_weekday(year, 9, 0, 1))
        days.add(_nth_weekday(year, 11, 3, 4))
        days.add(_observed(date(year, 12, 25)))
        return days

    @staticmethod
    def early_closes(year: int) -> set[date]:
        days = set()
        thanksgiving = _nth_weekday(year, 11, 3, 4)
        days.add(thanksgiving + timedelta(days=1))
        christmas = date(year, 12, 25)
        christmas_obs = _observed(christmas)
        eve = christmas - timedelta(days=1)
        if eve.weekday() < 5 and eve != christmas_obs:
            days.add(eve)
        july4 = date(year, 7, 4)
        july4_obs = _observed(july4)
        day_before = july4 - timedelta(days=1)
        if day_before.weekday() < 5 and day_before != july4_obs:
            days.add(day_before)
        return days

    @staticmethod
    def is_trading_day(d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return d not in NYSECalendar.holidays(d.year)

    @staticmethod
    def market_close_time(d: date) -> time:
        if d in NYSECalendar.early_closes(d.year):
            return time(13, 0)
        return time(16, 0)

    @staticmethod
    def market_open_time() -> time:
        return time(9, 30)

    @staticmethod
    def is_market_open(dt: datetime, tz: ZoneInfo | None = None) -> bool:
        local = dt.astimezone(tz or ET)
        d = local.date()
        if not NYSECalendar.is_trading_day(d):
            return False
        t = local.time()
        return NYSECalendar.market_open_time() <= t < NYSECalendar.market_close_time(d)
