from __future__ import annotations

import logging
import time as _time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_STOCKS,
    CONF_API_PROVIDER,
    CONF_API_KEY,
    CONF_POLL_FREQUENCY,
    CONF_MONARCH_EMAIL,
    CONF_MONARCH_PASSWORD,
    CONF_MONARCH_MFA_SECRET,
    CONF_ALERT_THRESHOLD,
    CONF_ALERT_COOLDOWN,
    CONF_ENABLE_MARKET_HOURS,
    CONF_ENABLE_PAYCHECK_DETECTION,
    CONF_MARKET_TIMEZONE,
    CONF_MONARCH_POLL_INTERVAL,
    CONF_PAYCHECK_ACCOUNT,
    CONF_PAYCHECK_THRESHOLD,
    CONF_PAYCHECK_WINDOWS,
    DEFAULT_ALERT_THRESHOLD,
    DEFAULT_ALERT_COOLDOWN,
    DEFAULT_ENABLE_MARKET_HOURS,
    DEFAULT_ENABLE_PAYCHECK_DETECTION,
    DEFAULT_MARKET_TIMEZONE,
    DEFAULT_MONARCH_POLL_INTERVAL,
    DEFAULT_PAYCHECK_THRESHOLD,
    DEFAULT_PAYCHECK_WINDOWS,
    EVENT_PRICE_ALERT,
    EVENT_STOCK_UPDATE,
    EVENT_PAYCHECK_DETECTED,
    EVENT_MONARCH_STATUS,
    EVENT_CREDIT_CARD_CHANGE,
    first_entity_id,
)
from .providers import get_provider, StockQuote
from .market import market_now, market_tz, in_pay_window, parse_pay_windows

if TYPE_CHECKING:
    from .monarch import MonarchHolding

_LOGGER = logging.getLogger(__name__)

SENSITIVE_KEYS = {CONF_API_KEY, CONF_MONARCH_PASSWORD, CONF_MONARCH_MFA_SECRET}
_SKIP_HOLDING_TYPES = {"depository", "credit", "loan"}
_CC_STORE_KEY = f"{DOMAIN}.credit_card_balances"
_CC_STORE_VERSION = 1


def _strip_sensitive(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in config.items() if k not in SENSITIVE_KEYS}


class StockCoordinator(TimestampDataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config: dict[str, Any], entry_id: str = "") -> None:
        self._config = _strip_sensitive(config)
        self._entry_id = entry_id
        self._provider = get_provider(
            config[CONF_API_PROVIDER],
            config[CONF_API_KEY],
            async_get_clientsession(hass),
        )
        self._alert_threshold = config.get(CONF_ALERT_THRESHOLD, DEFAULT_ALERT_THRESHOLD)
        self._alert_cooldown_minutes = int(config.get(CONF_ALERT_COOLDOWN, DEFAULT_ALERT_COOLDOWN))
        self._last_alert_time: dict[str, float] = {}
        self._poll_seconds = int(config[CONF_POLL_FREQUENCY])
        self._market_hours_enabled = config.get(
            CONF_ENABLE_MARKET_HOURS, DEFAULT_ENABLE_MARKET_HOURS
        )
        self._tz = market_tz(config.get(CONF_MARKET_TIMEZONE, DEFAULT_MARKET_TIMEZONE))
        self.last_api_poll: dt_util.dt.datetime | None = None
        self._force_next_update = False

        _LOGGER.info(
            "StockCoordinator initialized: poll every %ds, market hours gate %s, stocks %s",
            self._poll_seconds, "ON" if self._market_hours_enabled else "OFF", self.stocks,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_stocks",
            update_interval=timedelta(seconds=self._poll_seconds),
        )

    @property
    def stocks(self) -> list[str]:
        return self._config.get(CONF_STOCKS, [])

    @property
    def provider(self):
        return self._provider

    @property
    def market_tz(self):
        return self._tz

    @property
    def device_id(self) -> str | None:
        if not self._entry_id:
            return None
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, self._entry_id)})
        return device.id if device else None

    @property
    def entity_id(self) -> str | None:
        if not self._entry_id:
            return None
        return first_entity_id(self.hass, self._entry_id)

    async def async_force_refresh(self) -> None:
        self._force_next_update = True
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, StockQuote]:
        force = self._force_next_update
        self._force_next_update = False
        _LOGGER.debug("Stock poll triggered (interval=%ds, force=%s)", self._poll_seconds, force)
        if self._market_hours_enabled and not force:
            from .market import NYSECalendar
            if not NYSECalendar.is_market_open(market_now(self.hass, self._tz), self._tz):
                _LOGGER.debug("Market closed — returning cached data")
                if self.data:
                    return self.data

        try:
            quotes = await self._provider.get_quotes(self.stocks)
        except Exception as exc:
            raise UpdateFailed("Stock data fetch failed") from exc

        self.last_api_poll = dt_util.utcnow()
        issue_id = f"stock_api_failure_{self._entry_id}" if self._entry_id else ""

        if self.stocks and not quotes:
            if issue_id:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="stock_api_failure",
                )
            raise UpdateFailed(
                f"No quotes returned for any of the {len(self.stocks)} configured symbols"
            )

        if issue_id:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        if missing := [s for s in self.stocks if s not in quotes]:
            _LOGGER.warning("No quote returned for: %s", ", ".join(missing))

        prices = {s: round(q.current_price, 2) for s, q in quotes.items()}
        _LOGGER.debug("Stock poll complete: %s", {s: f"${p:.2f}" for s, p in prices.items()})
        self.hass.bus.async_fire(EVENT_STOCK_UPDATE, {"prices": prices, "device_id": self.device_id, "entity_id": self.entity_id})

        now_ts = _time.monotonic()
        cooldown_secs = self._alert_cooldown_minutes * 60

        for symbol, quote in quotes.items():
            if abs(quote.change_percent) >= self._alert_threshold:
                last_fired = self._last_alert_time.get(symbol, 0)
                if now_ts - last_fired >= cooldown_secs:
                    alert_data = {
                        "symbol": symbol,
                        "price": quote.current_price,
                        "previous_close": quote.previous_close,
                        "change_pct": round(quote.change_percent, 2),
                        "direction": "up" if quote.change_percent >= 0 else "down",
                        "device_id": self.device_id,
                        "entity_id": self.entity_id,
                    }
                    self.hass.bus.async_fire(EVENT_PRICE_ALERT, alert_data)
                    self._last_alert_time[symbol] = now_ts

        return quotes


class MonarchCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config: dict[str, Any], entry_id: str = "") -> None:
        self._config = _strip_sensitive(config)
        self._entry_id = entry_id
        session_dir = hass.config.path(f".storage/{DOMAIN}")

        from .monarch import MonarchClient
        self._client = MonarchClient(
            config[CONF_MONARCH_EMAIL],
            config[CONF_MONARCH_PASSWORD],
            mfa_secret=config.get(CONF_MONARCH_MFA_SECRET, ""),
            session_dir=session_dir,
        )
        self._was_available = True
        self._previous_cash: float | None = None
        self._previous_cc: dict[str, float] = {}
        self._cc_store: Store = Store(hass, _CC_STORE_VERSION, _CC_STORE_KEY)
        self._cc_store_loaded = False
        self._double_refresh_unsub = None

        poll_minutes = int(config.get(CONF_MONARCH_POLL_INTERVAL, DEFAULT_MONARCH_POLL_INTERVAL))
        self._paycheck_enabled = config.get(
            CONF_ENABLE_PAYCHECK_DETECTION, DEFAULT_ENABLE_PAYCHECK_DETECTION
        )
        self._paycheck_threshold = config.get(
            CONF_PAYCHECK_THRESHOLD, DEFAULT_PAYCHECK_THRESHOLD
        )
        self._pay_windows = parse_pay_windows(
            config.get(CONF_PAYCHECK_WINDOWS, DEFAULT_PAYCHECK_WINDOWS)
        )
        self._paycheck_account: str = config.get(CONF_PAYCHECK_ACCOUNT, "")

        _LOGGER.info(
            "MonarchCoordinator initialized: poll every %dm, paycheck detection %s",
            poll_minutes, "ON" if self._paycheck_enabled else "OFF",
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_monarch",
            update_interval=timedelta(minutes=poll_minutes),
        )

    @property
    def device_id(self) -> str | None:
        if not self._entry_id:
            return None
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, self._entry_id)})
        return device.id if device else None

    @property
    def entity_id(self) -> str | None:
        if not self._entry_id:
            return None
        return first_entity_id(self.hass, self._entry_id)

    @callback
    def async_cancel_pending(self) -> None:
        """Cancel a deferred second refresh, if one is armed."""
        if self._double_refresh_unsub is not None:
            self._double_refresh_unsub()
            self._double_refresh_unsub = None

    async def async_sync_accounts(self) -> bool:
        _LOGGER.debug("Monarch coordinator: starting account sync")
        success = await self._client.request_sync()
        if success:
            _LOGGER.debug("Monarch coordinator: sync succeeded, refreshing coordinator data")
            await self.async_request_refresh()
            _LOGGER.debug("Monarch coordinator: post-sync data refresh complete")
        else:
            _LOGGER.debug("Monarch coordinator: sync returned failure")
        return success

    async def async_trigger_double_refresh(self) -> None:
        # Re-arming without cancelling would orphan the previous timer.
        self.async_cancel_pending()
        await self.async_request_refresh()

        @callback
        def _second_refresh(_now) -> None:
            self._double_refresh_unsub = None
            self.hass.async_create_task(self.async_request_refresh())

        self._double_refresh_unsub = async_call_later(
            self.hass, 240, _second_refresh
        )

    async def _async_update_data(self) -> dict[str, Any]:
        accounts = await self._client.get_accounts()

        is_available = len(accounts) > 0
        if is_available != self._was_available:
            status_data = {"status": "online" if is_available else "offline", "device_id": self.device_id, "entity_id": self.entity_id}
            self.hass.bus.async_fire(EVENT_MONARCH_STATUS, status_data)
            self._was_available = is_available

        if not accounts:
            raise UpdateFailed("Monarch Money returned no accounts")

        result: dict[str, Any] = {"accounts": {}, "totals": {}}

        by_type: dict[str, float] = {}
        for acct in accounts:
            result["accounts"][acct.id] = acct
            by_type.setdefault(acct.account_type, 0.0)
            by_type[acct.account_type] += acct.balance

        result["totals"] = by_type

        from .monarch import MonarchHoldingsError

        all_holdings: dict[str, MonarchHolding] = {}
        holdings_complete = True
        for acct in accounts:
            type_lower = (acct.type_name or "").lower()
            if type_lower in _SKIP_HOLDING_TYPES:
                _LOGGER.debug(
                    "Skipping holdings for %s (%s) — type=%s",
                    acct.name, acct.id, acct.type_name,
                )
                continue
            _LOGGER.debug(
                "Fetching holdings for %s (%s) — type=%s",
                acct.name, acct.id, acct.type_name,
            )
            try:
                acct_holdings = await self._client.get_holdings(acct.id, acct.name)
            except MonarchHoldingsError as exc:
                # One account failing should not fail the whole refresh, but it
                # does mean the holdings set is no longer authoritative -- so
                # record that, or the entity cleanup would read the gap as a
                # deletion and prune those sensors permanently.
                holdings_complete = False
                _LOGGER.warning("Monarch holdings unavailable for %s: %s", acct.name, exc)
                continue
            _LOGGER.debug(
                "Got %d holdings for %s", len(acct_holdings), acct.name,
            )
            for h in acct_holdings:
                all_holdings[h.id] = h
        result["holdings"] = all_holdings
        result["holdings_complete"] = holdings_complete

        if self._paycheck_enabled:
            if self._paycheck_account:
                total_cash = sum(
                    acct.balance for acct in accounts
                    if acct.id == self._paycheck_account
                )
            else:
                cash_types = {"Cash", "Checking", "Savings"}
                total_cash = sum(
                    acct.balance for acct in accounts
                    if acct.account_type in cash_types
                )

            if self._previous_cash is not None:
                delta = total_cash - self._previous_cash
                if delta >= self._paycheck_threshold:
                    # Pay windows are calendar days in the user's own
                    # timezone -- paychecks have nothing to do with
                    # trading hours, so the market zone is not used here.
                    day = dt_util.now().day
                    paycheck_data = {
                        "amount": round(delta, 2),
                        "new_balance": round(total_cash, 2),
                        "in_pay_window": in_pay_window(day, self._pay_windows),
                        "device_id": self.device_id,
                        "entity_id": self.entity_id,
                    }
                    self.hass.bus.async_fire(EVENT_PAYCHECK_DETECTED, paycheck_data)
            self._previous_cash = total_cash

        credit_accounts = [
            a for a in accounts
            if (a.type_name or "").lower() == "credit"
        ]
        if not credit_accounts:
            _LOGGER.debug(
                "No credit-type accounts found; account types present: %s",
                {a.name: a.type_name for a in accounts},
            )

        if not self._cc_store_loaded:
            stored = await self._cc_store.async_load()
            if stored and isinstance(stored, dict):
                self._previous_cc = stored
                _LOGGER.debug(
                    "Restored %d credit card balances from storage",
                    len(stored),
                )
            self._cc_store_loaded = True

        for acct in credit_accounts:
            curr = round(acct.balance, 2)
            prev = self._previous_cc.get(acct.id)
            if prev is None:
                _LOGGER.debug(
                    "Credit card %s (%s): seeding initial balance $%.2f",
                    acct.name, acct.id, curr,
                )
            elif curr != prev:
                _LOGGER.debug(
                    "Credit card %s (%s): balance changed $%.2f -> $%.2f, firing event",
                    acct.name, acct.id, prev, curr,
                )
                self.hass.bus.async_fire(EVENT_CREDIT_CARD_CHANGE, {
                    "account": acct.name,
                    "account_id": acct.id,
                    "previous_balance": prev,
                    "new_balance": curr,
                    "change": round(curr - prev, 2),
                    "device_id": self.device_id,
                    "entity_id": self.entity_id,
                })
            self._previous_cc[acct.id] = curr

        if credit_accounts:
            await self._cc_store.async_save(self._previous_cc)

        return result
