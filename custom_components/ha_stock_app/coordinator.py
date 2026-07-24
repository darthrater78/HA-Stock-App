from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later

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
    CONF_ENABLE_MARKET_HOURS,
    CONF_ENABLE_PAYCHECK_DETECTION,
    CONF_MONARCH_POLL_INTERVAL,
    CONF_PAYCHECK_THRESHOLD,
    CONF_PAYCHECK_WINDOWS,
    DEFAULT_ALERT_THRESHOLD,
    DEFAULT_ENABLE_MARKET_HOURS,
    DEFAULT_ENABLE_PAYCHECK_DETECTION,
    DEFAULT_MONARCH_POLL_INTERVAL,
    DEFAULT_PAYCHECK_THRESHOLD,
    DEFAULT_PAYCHECK_WINDOWS,
    EVENT_PRICE_ALERT,
    EVENT_PAYCHECK_DETECTED,
    EVENT_MONARCH_STATUS,
)
from .providers import get_provider, StockQuote
from .monarch import MonarchHolding
from .market import et_now, in_pay_window, parse_pay_windows

_LOGGER = logging.getLogger(__name__)

SENSITIVE_KEYS = {CONF_API_KEY, CONF_MONARCH_PASSWORD, CONF_MONARCH_MFA_SECRET}


def _strip_sensitive(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in config.items() if k not in SENSITIVE_KEYS}


class StockCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._config = _strip_sensitive(config)
        self._provider = get_provider(
            config[CONF_API_PROVIDER],
            config[CONF_API_KEY],
            async_get_clientsession(hass),
        )
        self._previous_prices: dict[str, float] = {}
        self._alert_threshold = config.get(CONF_ALERT_THRESHOLD, DEFAULT_ALERT_THRESHOLD)
        self._poll_seconds = config[CONF_POLL_FREQUENCY]
        self._market_hours_enabled = config.get(
            CONF_ENABLE_MARKET_HOURS, DEFAULT_ENABLE_MARKET_HOURS
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

    async def _async_update_data(self) -> dict[str, StockQuote]:
        if self._market_hours_enabled:
            from .market import NYSECalendar
            if not NYSECalendar.is_market_open(et_now(self.hass)):
                if self.data:
                    return self.data
                # First poll ever — fetch once even if market closed
                # so sensors have initial values

        try:
            quotes = await self._provider.get_quotes(self.stocks)
        except Exception as exc:
            raise UpdateFailed("Stock data fetch failed") from exc

        for symbol, quote in quotes.items():
            prev = self._previous_prices.get(symbol)
            if prev is not None and prev > 0:
                pct = abs((quote.current_price - prev) / prev) * 100
                if pct >= self._alert_threshold:
                    self.hass.bus.async_fire(
                        EVENT_PRICE_ALERT,
                        {
                            "symbol": symbol,
                            "price": quote.current_price,
                            "previous": prev,
                            "change_pct": round(quote.change_percent, 2),
                            "direction": "up" if quote.current_price > prev else "down",
                        },
                    )
            self._previous_prices[symbol] = quote.current_price

        return quotes


class MonarchCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._config = _strip_sensitive(config)
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
        self._double_refresh_unsub = None

        poll_minutes = config.get(CONF_MONARCH_POLL_INTERVAL, DEFAULT_MONARCH_POLL_INTERVAL)
        self._paycheck_enabled = config.get(
            CONF_ENABLE_PAYCHECK_DETECTION, DEFAULT_ENABLE_PAYCHECK_DETECTION
        )
        self._paycheck_threshold = config.get(
            CONF_PAYCHECK_THRESHOLD, DEFAULT_PAYCHECK_THRESHOLD
        )
        self._pay_windows = parse_pay_windows(
            config.get(CONF_PAYCHECK_WINDOWS, DEFAULT_PAYCHECK_WINDOWS)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_monarch",
            update_interval=timedelta(minutes=poll_minutes),
        )

    async def async_trigger_double_refresh(self) -> None:
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
            self.hass.bus.async_fire(
                EVENT_MONARCH_STATUS,
                {"status": "online" if is_available else "offline"},
            )
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

        _SKIP_TYPES = {"depository", "credit", "loan"}
        all_holdings: dict[str, MonarchHolding] = {}
        for acct in accounts:
            type_lower = (acct.type_name or "").lower()
            if type_lower in _SKIP_TYPES:
                _LOGGER.debug(
                    "Skipping holdings for %s (%s) — type=%s",
                    acct.name, acct.id, acct.type_name,
                )
                continue
            _LOGGER.debug(
                "Fetching holdings for %s (%s) — type=%s",
                acct.name, acct.id, acct.type_name,
            )
            acct_holdings = await self._client.get_holdings(
                acct.id, acct.name
            )
            _LOGGER.debug(
                "Got %d holdings for %s", len(acct_holdings), acct.name,
            )
            for h in acct_holdings:
                all_holdings[h.id] = h
        result["holdings"] = all_holdings

        if self._paycheck_enabled:
            total_cash = (
                by_type.get("Cash", 0.0)
                + by_type.get("Checking", 0.0)
                + by_type.get("Savings", 0.0)
            )

            if self._previous_cash is not None:
                delta = total_cash - self._previous_cash
                if delta >= self._paycheck_threshold:
                    day = et_now(self.hass).day
                    self.hass.bus.async_fire(
                        EVENT_PAYCHECK_DETECTED,
                        {
                            "amount": round(delta, 2),
                            "new_balance": round(total_cash, 2),
                            "in_pay_window": in_pay_window(day, self._pay_windows),
                        },
                    )
            self._previous_cash = total_cash

        return result
