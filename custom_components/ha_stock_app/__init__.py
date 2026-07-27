from __future__ import annotations

import logging
from datetime import time as dt_time
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, CALLBACK_TYPE
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_point_in_time

import voluptuous as vol

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_MONARCH_ENABLED,
    CONF_ENABLE_MARKET_HOURS,
    CONF_ENABLE_EOD_SUMMARY,
    CONF_ENABLE_MARKET_OPEN_EVENT,
    CONF_ENABLE_FINNHUB_SELF_TEST,
    CONF_ENABLE_MONARCH_DOUBLE_REFRESH,
    CONF_ENABLE_401K_REPORTING,
    CONF_ENABLE_PAYCHECK_DETECTION,
    CONF_ENABLE_DEBUG_LOGGING,
    CONF_MARKET_TIMEZONE,
    CONF_MONARCH_POLL_INTERVAL,
    CONF_PAYCHECK_ACCOUNT,
    CONF_PAYCHECK_THRESHOLD,
    CONF_PAYCHECK_WINDOWS,
    CONF_401K_SENSOR,
    CONF_401K_QUIET_START,
    CONF_401K_QUIET_END,
    CONF_401K_RETRY_INTERVAL,
    DEFAULT_ENABLE_MARKET_HOURS,
    DEFAULT_ENABLE_EOD_SUMMARY,
    DEFAULT_ENABLE_MARKET_OPEN_EVENT,
    DEFAULT_ENABLE_FINNHUB_SELF_TEST,
    DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH,
    DEFAULT_ENABLE_401K_REPORTING,
    DEFAULT_ENABLE_PAYCHECK_DETECTION,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    DEFAULT_MARKET_TIMEZONE,
    DEFAULT_MONARCH_POLL_INTERVAL,
    DEFAULT_PAYCHECK_THRESHOLD,
    DEFAULT_PAYCHECK_WINDOWS,
    DEFAULT_401K_QUIET_START,
    DEFAULT_401K_QUIET_END,
    DEFAULT_401K_RETRY_INTERVAL,
    EVENT_MARKET_OPEN,
    EVENT_EOD_SUMMARY,
    EVENT_EOD2_SUMMARY,
    EVENT_FINNHUB_ERROR,
    EVENT_FINNHUB_OK,
    EVENT_PRICE_ALERT,
    EVENT_MONARCH_STATUS,
    EVENT_PAYCHECK_DETECTED,
)
from .coordinator import StockCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_VERSION = 2

OPTION_DEFAULTS = {
    CONF_ENABLE_MARKET_HOURS: DEFAULT_ENABLE_MARKET_HOURS,
    CONF_ENABLE_EOD_SUMMARY: DEFAULT_ENABLE_EOD_SUMMARY,
    CONF_ENABLE_MARKET_OPEN_EVENT: DEFAULT_ENABLE_MARKET_OPEN_EVENT,
    CONF_ENABLE_FINNHUB_SELF_TEST: DEFAULT_ENABLE_FINNHUB_SELF_TEST,
    CONF_ENABLE_MONARCH_DOUBLE_REFRESH: DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH,
    CONF_ENABLE_401K_REPORTING: DEFAULT_ENABLE_401K_REPORTING,
    CONF_ENABLE_PAYCHECK_DETECTION: DEFAULT_ENABLE_PAYCHECK_DETECTION,
    CONF_MONARCH_POLL_INTERVAL: DEFAULT_MONARCH_POLL_INTERVAL,
    CONF_PAYCHECK_ACCOUNT: "",
    CONF_PAYCHECK_THRESHOLD: DEFAULT_PAYCHECK_THRESHOLD,
    CONF_PAYCHECK_WINDOWS: DEFAULT_PAYCHECK_WINDOWS,
    CONF_401K_SENSOR: "",
    CONF_401K_QUIET_START: DEFAULT_401K_QUIET_START,
    CONF_401K_QUIET_END: DEFAULT_401K_QUIET_END,
    CONF_401K_RETRY_INTERVAL: DEFAULT_401K_RETRY_INTERVAL,
    CONF_ENABLE_DEBUG_LOGGING: DEFAULT_ENABLE_DEBUG_LOGGING,
    CONF_MARKET_TIMEZONE: DEFAULT_MARKET_TIMEZONE,
}


def _merged_config(entry: ConfigEntry) -> dict[str, Any]:
    config = dict(entry.data)
    for key, default in OPTION_DEFAULTS.items():
        config.setdefault(key, entry.options.get(key, default))
    config.update(entry.options)
    return config


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version < CONFIG_VERSION:
        _LOGGER.info("Migrating config entry from version %s to %s", entry.version, CONFIG_VERSION)
        new_options = dict(entry.options)
        for key, default in OPTION_DEFAULTS.items():
            new_options.setdefault(key, default)
        hass.config_entries.async_update_entry(
            entry, options=new_options, version=CONFIG_VERSION
        )
    return True


MONARCH_PACKAGE = "monarchmoneycommunity"


async def _check_monarch_update(hass: HomeAssistant, entry_id: str) -> None:
    check_key = f"{DOMAIN}_monarch_version_checked"
    if hass.data.get(check_key):
        return
    hass.data[check_key] = True
    issue_id = f"monarch_update_available_{entry_id}"
    issue_registry = ir.async_get(hass)
    if issue_registry.async_get_issue(DOMAIN, issue_id):
        return
    try:
        installed = pkg_version(MONARCH_PACKAGE)
    except Exception:
        return
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            f"https://pypi.org/pypi/{MONARCH_PACKAGE}/json",
            timeout=10,
        ) as resp:
            if resp.status != 200:
                return
            data = await resp.json()
        latest = data.get("info", {}).get("version", "")
        if not latest or latest == installed:
            return
        from packaging.version import Version
        if Version(latest) > Version(installed):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="monarch_update_available",
                translation_placeholders={
                    "installed": installed,
                    "latest": latest,
                },
                data={"installed": installed, "latest": latest},
            )
    except Exception as exc:
        _LOGGER.debug("Failed to check for %s updates: %s", MONARCH_PACKAGE, exc)


def _apply_debug_logging(entry: ConfigEntry) -> None:
    enabled = entry.options.get(CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING)
    ha_stock_logger = logging.getLogger("custom_components.ha_stock_app")
    ha_stock_logger.setLevel(logging.DEBUG if enabled else logging.INFO)
    if enabled:
        _LOGGER.info("Debug logging enabled for HA Stock App")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    config = _merged_config(entry)

    _apply_debug_logging(entry)

    stock_coordinator = StockCoordinator(hass, config, entry_id=entry.entry_id)
    await stock_coordinator.async_config_entry_first_refresh()

    data: dict = {
        "stock_coordinator": stock_coordinator,
        "test_notification_type": "eod_summary",
    }

    monarch_issue_id = f"monarch_auth_failed_{entry.entry_id}"

    if config.get(CONF_MONARCH_ENABLED):
        try:
            from .coordinator import MonarchCoordinator

            monarch_coordinator = MonarchCoordinator(hass, config)
            await monarch_coordinator.async_config_entry_first_refresh()
            data["monarch_coordinator"] = monarch_coordinator
            ir.async_delete_issue(hass, DOMAIN, monarch_issue_id)
        except ImportError:
            _LOGGER.error(
                "Monarch Money enabled but monarchmoney package not available"
            )
        except ConfigEntryNotReady:
            # async_config_entry_first_refresh raises this when Monarch is
            # unreachable or rejects the credentials. It is deliberately not
            # re-raised: Monarch is optional here, and propagating it would put
            # the whole entry into setup-retry, taking stock tracking down with
            # it. The coordinator is still stored so the refresh button and the
            # scheduled double-refresh can recover it without a reload -- and so
            # the sensor platform can tell "temporarily unavailable" apart from
            # "removed" when it prunes stale entities.
            data["monarch_coordinator"] = monarch_coordinator
            _LOGGER.warning(
                "Monarch Money is not reachable; continuing without it. "
                "Its sensors are preserved and will recover on the next refresh"
            )
            ir.async_create_issue(
                hass,
                DOMAIN,
                monarch_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="monarch_auth_failed",
            )
        except (OSError, PermissionError) as exc:
            _LOGGER.error("Monarch Money file/permission error: %s", type(exc).__name__)
            ir.async_create_issue(
                hass,
                DOMAIN,
                monarch_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="monarch_file_error",
            )
        except Exception:
            _LOGGER.exception("Unexpected error initializing Monarch Money coordinator")
            ir.async_create_issue(
                hass,
                DOMAIN,
                monarch_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="monarch_auth_failed",
            )
    else:
        ir.async_delete_issue(hass, DOMAIN, monarch_issue_id)

    scheduler = ScheduledFeatures(hass, entry, data)
    scheduler.register()
    data["scheduler"] = scheduler

    hass.data[DOMAIN][entry.entry_id] = data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if not hass.services.has_service(DOMAIN, "test_notification"):
        _register_services(hass)

    hass.async_create_task(_check_monarch_update(hass, entry.entry_id))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _apply_debug_logging(entry)
    await hass.config_entries.async_reload(entry.entry_id)


_TEST_EVENTS = {
    "eod_summary": (
        EVENT_EOD_SUMMARY,
        {
            "stocks": {
                "VOO": {
                    "price": 523.45,
                    "change": 2.15,
                    "change_pct": 0.41,
                    "position_value": 52345.00,
                    "day_pl": 215.00,
                },
                "VTI": {
                    "price": 275.80,
                    "change": -1.30,
                    "change_pct": -0.47,
                },
            }
        },
    ),
    "market_open": (
        EVENT_MARKET_OPEN,
        {"date": "2026-07-24", "early_close": False, "close_time": "16:00"},
    ),
    "price_alert": (
        EVENT_PRICE_ALERT,
        {
            "symbol": "VOO",
            "price": 530.00,
            "previous_close": 523.45,
            "change_pct": 1.25,
            "direction": "up",
        },
    ),
    "paycheck_detected": (
        EVENT_PAYCHECK_DETECTED,
        {"amount": 4250.00, "new_balance": 12500.00, "in_pay_window": True},
    ),
    "eod2_summary": (
        EVENT_EOD2_SUMMARY,
        {
            "sensor": "sensor.monarch_holding_401k",
            "previous_value": 98500.00,
            "new_value": 98850.00,
            "day_change": 350.00,
            "day_change_pct": 0.36,
            "deferred": False,
        },
    ),
    "finnhub_error": (
        EVENT_FINNHUB_ERROR,
        {"error": "ClientResponseError", "symbol": "VOO"},
    ),
    "finnhub_ok": (
        EVENT_FINNHUB_OK,
        {"symbol": "VOO", "price": 523.45},
    ),
}


def _register_services(hass: HomeAssistant) -> None:
    async def handle_test_notification(call) -> None:
        notification_type = call.data.get("type", "")
        if notification_type not in _TEST_EVENTS:
            _LOGGER.warning("Unknown test notification type: %s", notification_type)
            return
        event_name, event_data = _TEST_EVENTS[notification_type]
        data = {**event_data, "test": True}
        hass.bus.async_fire(event_name, data)
        _LOGGER.info("Fired test event: %s", event_name)

    hass.services.async_register(
        DOMAIN,
        "test_notification",
        handle_test_notification,
        schema=vol.Schema({vol.Required("type"): str}),
    )


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    session_dir = Path(hass.config.path(f".storage/{DOMAIN}"))
    if session_dir.is_dir():
        import shutil
        await hass.async_add_executor_job(shutil.rmtree, str(session_dir), True)
        _LOGGER.debug("Removed Monarch session storage at %s", session_dir)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        scheduler = entry_data.get("scheduler")
        if scheduler:
            scheduler.cancel_all()
        monarch_coordinator = entry_data.get("monarch_coordinator")
        if monarch_coordinator:
            # Otherwise a double refresh armed in the last four minutes fires
            # into a coordinator that has already been torn down.
            monarch_coordinator.async_cancel_pending()
        ir.async_delete_issue(hass, DOMAIN, f"monarch_auth_failed_{entry.entry_id}")
        ir.async_delete_issue(hass, DOMAIN, f"stock_api_failure_{entry.entry_id}")
        ir.async_delete_issue(hass, DOMAIN, f"finnhub_self_test_failed_{entry.entry_id}")
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "test_notification")
    return unload_ok


class ScheduledFeatures:
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        data: dict[str, Any],
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._data = data
        self._unsubs: list[CALLBACK_TYPE] = []
        self._eod2_retry_unsub: CALLBACK_TYPE | None = None
        self._eod2_deferred: dict | None = None
        self._eod2_baseline: str | None = None

        config = _merged_config(entry)
        self._config = config

        from .market import market_tz
        self._tz = market_tz(config.get(CONF_MARKET_TIMEZONE, DEFAULT_MARKET_TIMEZONE))

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    @property
    def _stock_coordinator(self) -> StockCoordinator:
        return self._data["stock_coordinator"]

    @property
    def _monarch_coordinator(self):
        return self._data.get("monarch_coordinator")

    def _schedule_daily(self, hour: int, minute: int, handler: Any) -> None:
        """Run handler each trading day at hour:minute in the market timezone.

        async_track_time_change cannot express this: it matches Home Assistant's
        local wall clock, and the offset to the market's clock shifts with DST --
        the two zones need not even change on the same date. So each occurrence
        is scheduled as an absolute instant and re-armed once it fires.
        """
        from .market import NYSECalendar, market_now, market_today, next_market_time

        holder: list[CALLBACK_TYPE | None] = [None]

        @callback
        def _arm() -> None:
            target = next_market_time(
                market_now(self.hass, self._tz), hour, minute, self._tz
            )
            holder[0] = async_track_point_in_time(self.hass, _fired, target)

        async def _fired(_now) -> None:
            holder[0] = None
            _arm()  # re-arm first, so a failing handler cannot break the chain
            if NYSECalendar.is_trading_day(market_today(self.hass, self._tz)):
                await handler()

        _arm()

        @callback
        def _cancel() -> None:
            if holder[0] is not None:
                holder[0]()
                holder[0] = None

        self._unsubs.append(_cancel)

    def register(self) -> None:
        from .market import parse_time_of_day

        schedules: list[tuple[int, int, str, Any]] = [
            (9, 15, CONF_ENABLE_FINNHUB_SELF_TEST, self._finnhub_self_test),
            (9, 30, CONF_ENABLE_MARKET_OPEN_EVENT, self._market_open_notify),
        ]

        if self._monarch_coordinator:
            schedules.append(
                (9, 25, CONF_ENABLE_MONARCH_DOUBLE_REFRESH, self._monarch_refresh)
            )

        if self._opt(CONF_ENABLE_EOD_SUMMARY, DEFAULT_ENABLE_EOD_SUMMARY):
            schedules.append((16, 0, CONF_ENABLE_EOD_SUMMARY, self._eod1_summary))

        if self._monarch_coordinator and self._opt(
            CONF_ENABLE_MONARCH_DOUBLE_REFRESH, DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH
        ):
            schedules.append((16, 0, CONF_ENABLE_MONARCH_DOUBLE_REFRESH, self._monarch_refresh))

        if self._opt(CONF_ENABLE_401K_REPORTING, DEFAULT_ENABLE_401K_REPORTING):
            schedules.append((16, 5, CONF_ENABLE_401K_REPORTING, self._eod2_start_watch))
            quiet_end = parse_time_of_day(
                self._opt(CONF_401K_QUIET_END, DEFAULT_401K_QUIET_END),
                DEFAULT_401K_QUIET_END,
            )
            schedules.append(
                (quiet_end.hour, quiet_end.minute, CONF_ENABLE_401K_REPORTING, self._eod2_morning_release)
            )

        for hour, minute, toggle_key, handler in schedules:
            if not self._opt(toggle_key, OPTION_DEFAULTS.get(toggle_key, False)):
                continue
            self._schedule_daily(hour, minute, handler)

    def cancel_all(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._eod2_retry_unsub:
            self._eod2_retry_unsub()
            self._eod2_retry_unsub = None

    async def _finnhub_self_test(self) -> None:
        provider = self._stock_coordinator.provider
        symbols = self._stock_coordinator.stocks
        if not symbols:
            return
        issue_id = f"finnhub_self_test_failed_{self._entry.entry_id}"
        symbol = symbols[0]
        try:
            quote = await provider.get_quote(symbol)
            if quote:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                self.hass.bus.async_fire(
                    EVENT_FINNHUB_OK,
                    {"symbol": symbol, "price": quote.current_price},
                )
            else:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="finnhub_self_test_failed",
                )
                self.hass.bus.async_fire(
                    EVENT_FINNHUB_ERROR,
                    {"error": "No quote returned", "symbol": symbol},
                )
        except Exception as exc:
            _LOGGER.warning("Finnhub self-test failed for %s: %s", symbol, exc)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="finnhub_self_test_failed",
            )
            self.hass.bus.async_fire(
                EVENT_FINNHUB_ERROR,
                {"error": type(exc).__name__, "symbol": symbol},
            )

    async def _market_open_notify(self) -> None:
        from .market import NYSECalendar, market_today
        d = market_today(self.hass, self._tz)
        close = NYSECalendar.market_close_time(d)
        self.hass.bus.async_fire(
            EVENT_MARKET_OPEN,
            {
                "date": d.isoformat(),
                "early_close": close.hour == 13,
                "close_time": close.strftime("%H:%M"),
            },
        )

    async def _monarch_refresh(self) -> None:
        mc = self._monarch_coordinator
        if mc:
            await mc.async_trigger_double_refresh()
            self.hass.bus.async_fire(
                EVENT_MONARCH_STATUS, {"status": "scheduled_refresh"}
            )

    async def _eod1_summary(self) -> None:
        quotes = self._stock_coordinator.data
        if not quotes:
            return

        stocks: dict[str, dict] = {}
        for symbol, q in quotes.items():
            entry: dict[str, Any] = {
                "price": q.current_price,
                "change": round(q.change, 2),
                "change_pct": round(q.change_percent, 2),
            }

            mc = self._monarch_coordinator
            if mc and mc.data:
                # Match the holding by ticker rather than searching account names
                # for the symbol: a one-letter ticker such as "A" was a substring
                # of nearly every account name, and an account's balance is not
                # the position's value in any case. Holdings carry both the
                # ticker and the share count, so the day's P/L is exact rather
                # than derived from a percentage.
                held = [
                    h for h in mc.data.get("holdings", {}).values()
                    if (h.ticker or "").upper() == symbol.upper()
                ]
                if held:
                    entry["position_value"] = round(sum(h.value for h in held), 2)
                    entry["day_pl"] = round(sum(h.quantity for h in held) * q.change, 2)
                    if len(held) > 1:
                        entry["accounts"] = sorted({h.account_name for h in held})

            stocks[symbol] = entry

        self.hass.bus.async_fire(EVENT_EOD_SUMMARY, {"stocks": stocks})

    async def _eod2_start_watch(self) -> None:
        sensor_id = self._opt(CONF_401K_SENSOR, "")
        if not sensor_id:
            return

        state = self.hass.states.get(sensor_id)
        if not state:
            _LOGGER.warning("401k sensor %s not found", sensor_id)
            return

        if self._eod2_retry_unsub:
            self._eod2_retry_unsub()
            self._eod2_retry_unsub = None

        self._eod2_baseline = state.state
        retry_minutes = int(self._opt(CONF_401K_RETRY_INTERVAL, DEFAULT_401K_RETRY_INTERVAL))
        await self._eod2_check_and_retry(retry_minutes)

    async def _eod2_check_and_retry(self, retry_minutes: int) -> None:
        from .market import in_quiet_hours, market_now, parse_time_of_day

        sensor_id = self._opt(CONF_401K_SENSOR, "")

        if self._monarch_coordinator:
            await self._monarch_coordinator.async_request_refresh()

        state = self.hass.states.get(sensor_id)
        if not state:
            return

        current_value = state.state
        if current_value != self._eod2_baseline:
            try:
                new_val = float(current_value)
                old_val = float(self._eod2_baseline)
                change = new_val - old_val
                change_pct = (change / old_val * 100) if old_val else 0
            except (ValueError, ZeroDivisionError):
                _LOGGER.warning(
                    "401k sensor %s returned non-numeric value %r; skipping change calc",
                    sensor_id, current_value,
                )
                new_val = current_value
                old_val = self._eod2_baseline
                change = 0
                change_pct = 0

            now = market_now(self.hass, self._tz)
            quiet_start = parse_time_of_day(
                self._opt(CONF_401K_QUIET_START, DEFAULT_401K_QUIET_START),
                DEFAULT_401K_QUIET_START,
            )
            quiet_end = parse_time_of_day(
                self._opt(CONF_401K_QUIET_END, DEFAULT_401K_QUIET_END),
                DEFAULT_401K_QUIET_END,
            )
            in_quiet = in_quiet_hours(now.time(), quiet_start, quiet_end)

            event_data = {
                "sensor": sensor_id,
                "previous_value": old_val,
                "new_value": new_val,
                "day_change": round(change, 2) if isinstance(change, float) else change,
                "day_change_pct": round(change_pct, 2) if isinstance(change_pct, float) else change_pct,
                "deferred": in_quiet,
            }

            if in_quiet:
                self._eod2_deferred = event_data
                _LOGGER.debug("401k update detected during quiet hours, deferring")
            else:
                self.hass.bus.async_fire(EVENT_EOD2_SUMMARY, event_data)
                self._eod2_deferred = None
            return

        # No change yet — keep polling through quiet hours too, since the
        # NAV update this feature exists to catch typically posts overnight.
        # The event itself is deferred (see above); this loop only stops
        # once a change is found or the next trading day's watch restarts it.
        @callback
        def _retry(_now):
            self._eod2_retry_unsub = None
            self.hass.async_create_task(
                self._eod2_check_and_retry(retry_minutes)
            )

        self._eod2_retry_unsub = async_call_later(
            self.hass, retry_minutes * 60, _retry
        )

    async def _eod2_morning_release(self) -> None:
        if self._eod2_deferred:
            self._eod2_deferred["deferred"] = False
            self.hass.bus.async_fire(EVENT_EOD2_SUMMARY, self._eod2_deferred)
            self._eod2_deferred = None
