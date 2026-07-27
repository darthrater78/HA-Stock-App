from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from importlib.metadata import version as pkg_version

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MONARCH_ACCOUNTS,
    CONF_PL_ACCOUNTS,
    CONF_PL_TICKER_MAP,
    DOMAIN,
    device_info,
)
from .coordinator import StockCoordinator, MonarchCoordinator
from .market import NYSECalendar, market_now

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .monarch import MonarchAccount, MonarchHolding


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    selected_accounts = entry.data.get(CONF_MONARCH_ACCOUNTS, [])

    stock_coordinator: StockCoordinator = data["stock_coordinator"]
    entities.append(MarketStatusSensor(stock_coordinator, entry))
    entities.append(LastPollSensor(stock_coordinator, entry))
    entities.append(MonarchPackageVersionSensor(entry))
    for symbol in stock_coordinator.stocks:
        entities.append(StockPriceSensor(stock_coordinator, symbol, entry))
        entities.append(StockChangePercentSensor(stock_coordinator, symbol, entry))

    monarch_coordinator: MonarchCoordinator | None = data.get("monarch_coordinator")
    if monarch_coordinator and monarch_coordinator.data:
        for acct_id, acct in monarch_coordinator.data.get("accounts", {}).items():
            if not selected_accounts or acct_id in selected_accounts:
                entities.append(MonarchAccountSensor(monarch_coordinator, acct, entry))
        entities.append(MonarchNetWorthSensor(monarch_coordinator, entry))
        for holding_id, holding in monarch_coordinator.data.get("holdings", {}).items():
            if not selected_accounts or holding.account_id in selected_accounts:
                entities.append(MonarchHoldingSensor(monarch_coordinator, holding, entry))

        pl_accounts = entry.data.get(CONF_PL_ACCOUNTS, [])
        if pl_accounts:
            ticker_map = entry.data.get(CONF_PL_TICKER_MAP, {})
            entities.append(TodayPLSensor(
                monarch_coordinator, stock_coordinator,
                pl_accounts, ticker_map, entry,
            ))

    async_add_entities(entities, update_before_add=True)

    monarch_data = monarch_coordinator.data if monarch_coordinator else None
    monarch_loaded = bool(monarch_data)
    # Authoritative only when every account's holdings actually came back; a
    # partial fetch leaves gaps that must not be mistaken for removals.
    holdings_loaded = bool(monarch_data) and monarch_data.get("holdings_complete", False)
    valid_unique_ids = {e.unique_id for e in entities}

    def _safe_to_remove(unique_id: str) -> bool:
        """Whether a registry entry can be positively accounted for as stale.

        Removal is permanent: it drops the entity ID, any rename, icon and area
        the user set, and orphans long-term statistics. So only prune what was
        actually evaluated this run. If Monarch did not load -- a transient
        outage, an expired session -- its entities are left alone rather than
        destroyed over a condition that may clear on the next refresh.
        """
        if unique_id in valid_unique_ids:
            return False
        if unique_id.startswith(f"{DOMAIN}_monarch_holding_"):
            return holdings_loaded
        if unique_id.startswith(f"{DOMAIN}_monarch"):
            return monarch_loaded
        return True

    ent_reg = er.async_get(hass)
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent_entry.domain == "sensor" and _safe_to_remove(ent_entry.unique_id):
            ent_reg.async_remove(ent_entry.entity_id)


class StockPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: StockCoordinator, symbol: str, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._symbol = symbol
        self._attr_unique_id = f"{DOMAIN}_stock_{symbol.lower()}"
        self._attr_name = f"{symbol} Stock Price"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self._symbol in self.coordinator.data:
            return self.coordinator.data[self._symbol].current_price
        return None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data or self._symbol not in self.coordinator.data:
            return {}
        q = self.coordinator.data[self._symbol]
        return {
            "symbol": q.symbol,
            "previous_close": q.previous_close,
            "open": q.open_price,
            "high": q.high,
            "low": q.low,
            "change": round(q.change, 2),
            "change_percent": round(q.change_percent, 2),
        }


class StockChangePercentSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:percent"

    def __init__(self, coordinator: StockCoordinator, symbol: str, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._symbol = symbol
        self._attr_unique_id = f"{DOMAIN}_stock_{symbol.lower()}_change_pct"
        self._attr_name = f"{symbol} Change %"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self._symbol in self.coordinator.data:
            return round(self.coordinator.data[self._symbol].change_percent, 2)
        return None


class MonarchAccountSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:bank"

    def __init__(self, coordinator: MonarchCoordinator, account: MonarchAccount, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._acct_id = account.id
        self._attr_unique_id = f"{DOMAIN}_monarch_{account.id}"
        self._attr_name = f"Monarch {account.institution} - {account.name}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        acct = self.coordinator.data.get("accounts", {}).get(self._acct_id)
        return acct.balance if acct else None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        acct = self.coordinator.data.get("accounts", {}).get(self._acct_id)
        if not acct:
            return {}
        return {
            "institution": acct.institution,
            "account_type": acct.account_type,
            "subtype": acct.subtype,
        }


class MonarchHoldingSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:chart-areaspline"

    def __init__(self, coordinator: MonarchCoordinator, holding: MonarchHolding, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._holding_id = holding.id
        self._attr_unique_id = f"{DOMAIN}_monarch_holding_{holding.id}"
        ticker_part = holding.ticker if holding.ticker != "N/A" else holding.name[:20]
        self._attr_name = f"Monarch {ticker_part} ({holding.account_name})"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        holding = self.coordinator.data.get("holdings", {}).get(self._holding_id)
        return round(holding.value, 2) if holding else None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        holding = self.coordinator.data.get("holdings", {}).get(self._holding_id)
        if not holding:
            return {}
        attrs = {
            "ticker": holding.ticker,
            "name": holding.name,
            "quantity": round(holding.quantity, 4),
            "price": round(holding.price, 2) if holding.price else None,
            "cost_basis": round(holding.cost_basis, 2) if holding.cost_basis else None,
            "account": holding.account_name,
        }
        if holding.cost_basis and holding.value:
            gain = holding.value - holding.cost_basis
            gain_pct = (gain / holding.cost_basis * 100) if holding.cost_basis else 0
            attrs["gain_loss"] = round(gain, 2)
            attrs["gain_loss_pct"] = round(gain_pct, 2)
        if holding.one_day_change_pct:
            attrs["one_day_change_pct"] = round(holding.one_day_change_pct, 2)
        return attrs


class LastPollSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: StockCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_last_poll"
        self._attr_name = "Last Stock Poll"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self):
        return self.coordinator.last_api_poll


class MarketStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: StockCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_market_status"
        self._attr_name = "Market Status"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str:
        now = market_now(self.hass, self.coordinator.market_tz)
        d = now.date()
        if d.weekday() >= 5:
            return "Closed - Weekend"
        if not NYSECalendar.is_trading_day(d):
            return "Closed - Holiday"
        t = now.time()
        close_time = NYSECalendar.market_close_time(d)
        open_time = NYSECalendar.market_open_time()
        if open_time <= t < close_time:
            if close_time.hour == 13:
                return "Early Close"
            return "Open"
        return "Closed - After Hours"

    @property
    def extra_state_attributes(self) -> dict:
        now = market_now(self.hass, self.coordinator.market_tz)
        d = now.date()
        attrs = {"trading_day": NYSECalendar.is_trading_day(d)}
        if NYSECalendar.is_trading_day(d):
            attrs["close_time"] = NYSECalendar.market_close_time(d).strftime("%H:%M")
        return attrs


class MonarchNetWorthSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: MonarchCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_monarch_net_worth"
        self._attr_name = "Monarch Net Worth"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        totals = self.coordinator.data.get("totals", {})
        return round(sum(totals.values()), 2) if totals else None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        return {"breakdown": self.coordinator.data.get("totals", {})}


class TodayPLSensor(CoordinatorEntity, SensorEntity):
    """Daily P&L across selected Monarch accounts.

    Uses live Finnhub prices when a holding's ticker matches a configured
    stock symbol, and falls back to Monarch's one_day_change_pct otherwise.
    The ``holdings`` attribute exposes every pairing so the user can verify
    which source each holding is using.
    """

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:currency-usd"

    def __init__(
        self,
        monarch_coordinator: MonarchCoordinator,
        stock_coordinator: StockCoordinator,
        pl_account_ids: list[str],
        ticker_map: dict[str, str],
        entry: ConfigEntry,
    ) -> None:
        super().__init__(monarch_coordinator)
        self._stock_coordinator = stock_coordinator
        self._pl_account_ids = set(pl_account_ids)
        self._ticker_map = ticker_map
        self._attr_unique_id = f"{DOMAIN}_today_pl"
        self._attr_name = "Today's P&L"
        self._attr_device_info = device_info(entry)
        self._unsub_stock: Any = None
        self._cached_result: tuple[float, list[dict]] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub_stock = self._stock_coordinator.async_add_listener(
            self._handle_stock_update
        )

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self._unsub_stock:
            self._unsub_stock()
            self._unsub_stock = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._cached_result = None
        super()._handle_coordinator_update()

    @callback
    def _handle_stock_update(self) -> None:
        self._cached_result = None
        self.async_write_ha_state()

    def _resolve_quote(self, ticker: str, quotes: dict):
        """Look up the live quote for a holding's ticker.

        When an explicit ticker map is configured, it is authoritative:
        a mapping to a symbol uses that quote, a mapping to "" means
        Monarch-only, and a ticker absent from the map auto-matches
        (handles holdings added after the last config visit).
        """
        if self._ticker_map:
            mapped = self._ticker_map.get(ticker)
            if mapped is None:
                return quotes.get(ticker)
            if mapped:
                return quotes.get(mapped)
            return None
        return quotes.get(ticker)

    def _compute(self) -> tuple[float, list[dict]]:
        """Return (total_pl, per-holding detail list)."""
        if not self.coordinator.data:
            return 0.0, []

        quotes = self._stock_coordinator.data or {}

        total = 0.0
        details: list[dict] = []
        for h in self.coordinator.data.get("holdings", {}).values():
            if h.account_id not in self._pl_account_ids:
                continue

            ticker = (h.ticker or "").upper()
            label = ticker if ticker and ticker != "N/A" else h.name[:20]
            quote = self._resolve_quote(ticker, quotes)
            mapped_to = self._ticker_map.get(ticker, ticker) if self._ticker_map else ticker

            if quote:
                daily_change = h.quantity * quote.change
                source = f"live:{quote.symbol}"
                pct = round(quote.change_percent, 2)
            elif h.one_day_change_pct and (100 + h.one_day_change_pct) != 0:
                daily_change = h.value * h.one_day_change_pct / (100 + h.one_day_change_pct)
                source = "monarch"
                pct = round(h.one_day_change_pct, 2)
            else:
                daily_change = 0.0
                source = "none"
                pct = 0.0

            total += daily_change
            details.append({
                "ticker": label,
                "account": h.account_name,
                "shares": round(h.quantity, 4),
                "value": round(h.value, 2),
                "day_change": round(daily_change, 2),
                "change_pct": pct,
                "source": source,
                "mapped_to": mapped_to,
            })

        return round(total, 2), details

    def _get_computed(self) -> tuple[float, list[dict]]:
        if self._cached_result is None:
            self._cached_result = self._compute()
        return self._cached_result

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        total, _ = self._get_computed()
        return total

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        total, details = self._get_computed()
        live_count = sum(1 for d in details if d["source"] == "live")
        return {
            "holdings": details,
            "holding_count": len(details),
            "live_count": live_count,
            "fallback_count": len(details) - live_count,
        }


class MonarchPackageVersionSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:package-variant"

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{DOMAIN}_monarch_package_version"
        self._attr_name = "Monarch Package Version"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str | None:
        try:
            return pkg_version("monarchmoneycommunity")
        except Exception:
            return None
