from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
    entities: list[ButtonEntity] = [RefreshStocksButton(entry)]

    if data.get("monarch_coordinator"):
        entities.append(RefreshMonarchButton(entry))

    entities.append(SendTestNotificationButton(entry))
    async_add_entities(entities)


class RefreshStocksButton(ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_refresh_stocks"
        self._attr_name = "Refresh Stock Prices"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        coordinator = data["stock_coordinator"]
        await coordinator.async_request_refresh()


class RefreshMonarchButton(ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_refresh_monarch"
        self._attr_name = "Refresh Monarch Accounts"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        coordinator = data.get("monarch_coordinator")
        if coordinator:
            await coordinator.async_request_refresh()


class SendTestNotificationButton(ButtonEntity):
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_test_notification"
        self._attr_name = "Send Test Notification"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        from . import _TEST_EVENTS

        data = self.hass.data[DOMAIN][self._entry.entry_id]
        test_type = data.get("test_notification_type", "eod_summary")
        if test_type in _TEST_EVENTS:
            event_name, event_data = _TEST_EVENTS[test_type]
            self.hass.bus.async_fire(event_name, {**event_data, "test": True})
            _LOGGER.info("Fired test event: %s", event_name)
