from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MONARCH_ACCOUNTS, DOMAIN
from .coordinator import StockCoordinator, MonarchCoordinator
from .monarch import MonarchAccount, MonarchHolding


def _device_info(entry: ConfigEntry) -> dict:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "HA Stock App",
        "manufacturer": "HA Stock App",
        "model": "Stock & Finance Tracker",
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    selected_accounts = entry.data.get(CONF_MONARCH_ACCOUNTS, [])

    stock_coordinator: StockCoordinator = data["stock_coordinator"]
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


class StockPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: StockCoordinator, symbol: str, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._symbol = symbol
        self._attr_unique_id = f"{DOMAIN}_stock_{symbol.lower()}"
        self._attr_name = f"{symbol} Stock Price"
        self._attr_device_info = _device_info(entry)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

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
    _attr_state_class = SensorStateClass.MEASUREMENT
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
