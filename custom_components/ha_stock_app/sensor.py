from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MONARCH_ACCOUNTS, DOMAIN
from .coordinator import StockCoordinator, MonarchCoordinator
from .market import NYSECalendar, market_now
from .monarch import MonarchAccount, MonarchHolding


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="HA Stock App",
        manufacturer="HA Stock App",
        model="Stock & Finance Tracker",
    )


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
    for symbol in stock_coordinator.stocks:
        entities.append(StockPriceSensor(stock_coordinator, symbol, entry))

    monarch_coordinator: MonarchCoordinator | None = data.get("monarch_coordinator")
    if monarch_coordinator and monarch_coordinator.data:
        for acct_id, acct in monarch_coordinator.data.get("accounts", {}).items():
            if not selected_accounts or acct_id in selected_accounts:
                entities.append(MonarchAccountSensor(monarch_coordinator, acct, entry))
        entities.append(MonarchNetWorthSensor(monarch_coordinator, entry))
        for holding_id, holding in monarch_coordinator.data.get("holdings", {}).items():
            if not selected_accounts or holding.account_id in selected_accounts:
                entities.append(MonarchHoldingSensor(monarch_coordinator, holding, entry))

    async_add_entities(entities, update_before_add=True)

    monarch_data = monarch_coordinator.data if monarch_coordinator else None
    monarch_loaded = bool(monarch_data)
    holdings_loaded = bool(monarch_data and monarch_data.get("holdings"))
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
        self._attr_device_info = _device_info(entry)

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
        self._attr_device_info = _device_info(entry)

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
        self._attr_device_info = _device_info(entry)

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
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        if self.coordinator.last_update_success_time:
            return self.coordinator.last_update_success_time
        return None


class MarketStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: StockCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_market_status"
        self._attr_name = "Market Status"
        self._attr_device_info = _device_info(entry)

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
        self._attr_device_info = _device_info(entry)

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
