from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import StockCoordinator, MonarchCoordinator
from .monarch import MonarchAccount


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    stock_coordinator: StockCoordinator = data["stock_coordinator"]
    for symbol in stock_coordinator.stocks:
        entities.append(StockPriceSensor(stock_coordinator, symbol))

    monarch_coordinator: MonarchCoordinator | None = data.get("monarch_coordinator")
    if monarch_coordinator and monarch_coordinator.data:
        for acct_id, acct in monarch_coordinator.data.get("accounts", {}).items():
            entities.append(MonarchAccountSensor(monarch_coordinator, acct))
        entities.append(MonarchNetWorthSensor(monarch_coordinator))

    async_add_entities(entities, update_before_add=True)


class StockPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: StockCoordinator, symbol: str) -> None:
        super().__init__(coordinator)
        self._symbol = symbol
        self._attr_unique_id = f"{DOMAIN}_stock_{symbol.lower()}"
        self._attr_name = f"{symbol} Stock Price"

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
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:bank"

    def __init__(self, coordinator: MonarchCoordinator, account: MonarchAccount) -> None:
        super().__init__(coordinator)
        self._acct_id = account.id
        self._attr_unique_id = f"{DOMAIN}_monarch_{account.id}"
        self._attr_name = f"Monarch {account.institution} - {account.name}"

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


class MonarchNetWorthSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: MonarchCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_monarch_net_worth"
        self._attr_name = "Monarch Net Worth"

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
