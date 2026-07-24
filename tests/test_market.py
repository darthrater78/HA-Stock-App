"""Tests for market.py — calendar, timezone and scheduling logic.

market.py deliberately keeps Home Assistant out of its module scope, so this
suite runs with no dependencies at all:

    python3 -m unittest discover tests

It is also a valid pytest suite if you have pytest installed.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

_SRC = Path(__file__).resolve().parent.parent / "custom_components" / "ha_stock_app" / "market.py"
_spec = importlib.util.spec_from_file_location("ha_stock_app_market", _SRC)
market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(market)

ET = market.ET
D = dt.date.fromisoformat


# NYSE's published holiday calendars. If a year fails here, check it against
# nyse.com/markets/hours-calendars before assuming the test is wrong.
PUBLISHED_HOLIDAYS = {
    2025: ["2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
           "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25"],
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
           "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"],
    2027: ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
           "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"],
}


class TestHolidayCalendar(unittest.TestCase):
    def test_matches_published_calendars(self):
        for year, days in PUBLISHED_HOLIDAYS.items():
            with self.subTest(year=year):
                self.assertEqual(market.NYSECalendar.holidays(year), {D(s) for s in days})

    def test_easter_and_good_friday(self):
        for year, easter in [(2025, "2025-04-20"), (2026, "2026-04-05"), (2027, "2027-03-28")]:
            with self.subTest(year=year):
                self.assertEqual(market._easter(year), D(easter))
                self.assertIn(D(easter) - dt.timedelta(days=2), market.NYSECalendar.holidays(year))

    def test_weekend_is_never_a_trading_day(self):
        d = D("2026-07-04")  # Saturday
        self.assertFalse(market.NYSECalendar.is_trading_day(d))
        self.assertFalse(market.NYSECalendar.is_trading_day(d + dt.timedelta(days=1)))

    def test_observed_holiday_is_not_also_an_early_close(self):
        # July 4 2026 falls on a Saturday, so July 3 is the observed holiday --
        # a full close, not the usual half day before Independence Day.
        self.assertIn(D("2026-07-03"), market.NYSECalendar.holidays(2026))
        self.assertNotIn(D("2026-07-03"), market.NYSECalendar.early_closes(2026))
        # Same shape for Christmas Eve 2027, observed for Christmas Day.
        self.assertIn(D("2027-12-24"), market.NYSECalendar.holidays(2027))
        self.assertNotIn(D("2027-12-24"), market.NYSECalendar.early_closes(2027))

    def test_early_closes_are_half_days(self):
        day_after_thanksgiving = D("2026-11-27")
        self.assertIn(day_after_thanksgiving, market.NYSECalendar.early_closes(2026))
        self.assertEqual(market.NYSECalendar.market_close_time(day_after_thanksgiving), dt.time(13, 0))
        self.assertEqual(market.NYSECalendar.market_close_time(D("2026-11-30")), dt.time(16, 0))


class TestMarketOpen(unittest.TestCase):
    def _et(self, iso):
        return dt.datetime.fromisoformat(iso).replace(tzinfo=ET)

    def test_regular_session_boundaries(self):
        self.assertFalse(market.NYSECalendar.is_market_open(self._et("2026-06-15T09:29")))
        self.assertTrue(market.NYSECalendar.is_market_open(self._et("2026-06-15T09:30")))
        self.assertTrue(market.NYSECalendar.is_market_open(self._et("2026-06-15T15:59")))
        self.assertFalse(market.NYSECalendar.is_market_open(self._et("2026-06-15T16:00")))

    def test_closed_on_holidays(self):
        self.assertFalse(market.NYSECalendar.is_market_open(self._et("2026-12-25T12:00")))

    def test_early_close_afternoon_is_shut(self):
        self.assertTrue(market.NYSECalendar.is_market_open(self._et("2026-11-27T12:59")))
        self.assertFalse(market.NYSECalendar.is_market_open(self._et("2026-11-27T13:00")))

    def test_caller_timezone_does_not_change_the_answer(self):
        # Same instant, expressed in three zones -- the market is open or not
        # regardless of where the caller is standing.
        instant = self._et("2026-06-15T10:00")
        for zone in ["UTC", "Australia/Sydney", "Europe/London"]:
            with self.subTest(zone=zone):
                self.assertTrue(market.NYSECalendar.is_market_open(instant.astimezone(ZoneInfo(zone))))


class TestMarketTimezone(unittest.TestCase):
    def test_resolves_valid_zone(self):
        self.assertEqual(market.market_tz("Europe/London"), ZoneInfo("Europe/London"))

    def test_falls_back_to_eastern(self):
        for bad in [None, "", "Nonsense/Zone", "not a zone"]:
            with self.subTest(value=bad):
                self.assertEqual(market.market_tz(bad), ET)


class TestNextMarketTime(unittest.TestCase):
    """The scheduler's core: resolving a market wall time to an absolute instant.

    async_track_time_change matches Home Assistant's *local* clock, so a market
    time cannot be registered directly -- the offset between the two moves with
    DST, and the zones need not transition on the same date.
    """

    def test_resolves_to_the_requested_market_wall_time(self):
        now = dt.datetime(2026, 6, 15, 9, 0, tzinfo=dt.timezone.utc)
        fire = market.next_market_time(now, 16, 0, ET)
        self.assertEqual(fire.astimezone(ET).hour, 16)
        self.assertEqual(fire.astimezone(ET).minute, 0)
        self.assertGreater(fire, now)

    def test_utc_offset_shifts_across_dst(self):
        winter = market.next_market_time(
            dt.datetime(2026, 1, 15, 9, 0, tzinfo=dt.timezone.utc), 16, 0, ET)
        summer = market.next_market_time(
            dt.datetime(2026, 7, 15, 9, 0, tzinfo=dt.timezone.utc), 16, 0, ET)
        self.assertEqual(winter.astimezone(dt.timezone.utc).hour, 21)  # EST
        self.assertEqual(summer.astimezone(dt.timezone.utc).hour, 20)  # EDT
        # Both still read 16:00 on the market's own clock.
        self.assertEqual(winter.astimezone(ET).hour, 16)
        self.assertEqual(summer.astimezone(ET).hour, 16)

    def test_rolls_to_tomorrow_once_the_time_has_passed(self):
        now = dt.datetime(2026, 6, 15, 17, 0, tzinfo=ET)
        fire = market.next_market_time(now, 16, 0, ET)
        self.assertEqual(fire.astimezone(ET).date(), dt.date(2026, 6, 16))

    def test_nonexistent_wall_time_on_spring_forward(self):
        """A time inside the DST gap still resolves to a real instant.

        2026-03-08 02:30 ET does not exist -- the clock jumps 02:00 -> 03:00.
        The 401k quiet-hours end is user-configurable, so someone can land here
        once a year. It must resolve to an actual instant rather than being
        skipped or raising; it lands at 03:30 EDT, the same moment 02:30 EST
        would have been.
        """
        base = dt.datetime(2026, 3, 8, 0, 0, tzinfo=ET)
        fire = market.next_market_time(base, 2, 30, ET)
        self.assertGreater(fire, base)
        self.assertEqual(fire.astimezone(dt.timezone.utc).strftime("%H:%M"), "07:30")

    def test_always_strictly_in_the_future_across_two_years(self):
        """Every day of 2026-2027, four schedule times, four host timezones."""
        checked = 0
        for host in ["UTC", "America/Los_Angeles", "Europe/London", "Australia/Sydney"]:
            hz = ZoneInfo(host)
            for offset in range(730):
                base = dt.datetime(2026, 1, 1, 7, 0, tzinfo=hz) + dt.timedelta(days=offset)
                for hour, minute in [(9, 15), (9, 30), (16, 0), (16, 5)]:
                    fire = market.next_market_time(base, hour, minute, ET)
                    local = fire.astimezone(ET)
                    self.assertGreater(fire, base)
                    self.assertEqual((local.hour, local.minute), (hour, minute))
                    checked += 1
        self.assertEqual(checked, 730 * 4 * 4)


class TestQuietHours(unittest.TestCase):
    """Regression cases for the 401k deferral window.

    The original implementation compared only the hour component and joined its
    two clauses with an unconditional `or`, which broke both a window that wraps
    midnight and one that does not.
    """

    def _t(self, s):
        h, m = s.split(":")
        return dt.time(int(h), int(m))

    def test_wrapping_window(self):
        start, end = self._t("22:00"), self._t("08:35")
        for now, expected in [("08:15", True),   # minutes matter: was released early
                              ("08:35", False),
                              ("08:40", False),
                              ("21:59", False),
                              ("22:00", True),
                              ("03:00", True),
                              ("12:00", False)]:
            with self.subTest(now=now):
                self.assertIs(market.in_quiet_hours(self._t(now), start, end), expected)

    def test_non_wrapping_window(self):
        start, end = self._t("16:00"), self._t("20:00")
        for now, expected in [("09:00", False),  # was wrongly quiet
                              ("15:59", False),
                              ("16:00", True),
                              ("19:59", True),
                              ("20:00", False),
                              ("21:00", False)]:
            with self.subTest(now=now):
                self.assertIs(market.in_quiet_hours(self._t(now), start, end), expected)

    def test_empty_window_is_never_quiet(self):
        self.assertFalse(market.in_quiet_hours(self._t("12:00"), self._t("09:00"), self._t("09:00")))


class TestParseTimeOfDay(unittest.TestCase):
    """The quiet-hours fields are free-form text in the options flow.

    They previously reached a parser that raised during setup, so a typo
    stopped the whole integration from loading.
    """

    def test_parses_valid_times(self):
        self.assertEqual(market.parse_time_of_day("08:35", "22:00"), dt.time(8, 35))
        self.assertEqual(market.parse_time_of_day("0:00", "22:00"), dt.time(0, 0))
        self.assertEqual(market.parse_time_of_day("23:59", "22:00"), dt.time(23, 59))

    def test_bad_input_falls_back_instead_of_raising(self):
        for bad in ["22", "", "8:5pm", "25:00", "not a time", None, "08:60"]:
            with self.subTest(value=bad):
                self.assertEqual(market.parse_time_of_day(bad, "22:00"), dt.time(22, 0))

    def test_unusable_default_still_returns_a_time(self):
        self.assertEqual(market.parse_time_of_day("nonsense", "also nonsense"), dt.time(0, 0))


class TestPayWindows(unittest.TestCase):
    def test_parses_the_documented_default(self):
        self.assertEqual(market.parse_pay_windows("27-5,11-19"), [(27, 5), (11, 19)])

    def test_tolerates_whitespace_and_junk(self):
        self.assertEqual(market.parse_pay_windows(" 1-5 , 10-12 "), [(1, 5), (10, 12)])
        self.assertEqual(market.parse_pay_windows(""), [])

    def test_malformed_segments_are_skipped_not_raised(self):
        for bad in ["abc-def", "27-", "1-5-9", "27 to 5", None]:
            with self.subTest(value=bad):
                self.assertEqual(market.parse_pay_windows(bad), [])

    def test_out_of_range_days_are_rejected(self):
        # "99-200" parsed cleanly before but could never match a real date,
        # silently disabling pay-window matching.
        self.assertEqual(market.parse_pay_windows("99-200"), [])
        self.assertEqual(market.parse_pay_windows("0-5"), [])
        self.assertEqual(market.parse_pay_windows("1-31"), [(1, 31)])

    def test_one_bad_segment_does_not_discard_the_others(self):
        self.assertEqual(market.parse_pay_windows("27-5,oops,11-19"), [(27, 5), (11, 19)])

    def test_window_wrapping_month_end(self):
        windows = [(27, 5)]
        for day in [27, 28, 31, 1, 5]:
            self.assertTrue(market.in_pay_window(day, windows), day)
        for day in [6, 15, 26]:
            self.assertFalse(market.in_pay_window(day, windows), day)

    def test_ordinary_window(self):
        windows = [(11, 19)]
        self.assertTrue(market.in_pay_window(15, windows))
        self.assertFalse(market.in_pay_window(20, windows))
        self.assertFalse(market.in_pay_window(10, windows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
