from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, device_info

_INTEGRATION_LOGGER = logging.getLogger("custom_components.ha_stock_app")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DebugLoggingSwitch(entry)])


class DebugLoggingSwitch(SwitchEntity):
    _attr_icon = "mdi:bug"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_debug_logging"
        self._attr_name = "Debug Logging"
        self._attr_device_info = device_info(entry)
        self._enabled = _INTEGRATION_LOGGER.level == logging.DEBUG

    @property
    def is_on(self) -> bool:
        return self._enabled

    async def async_turn_on(self, **kwargs) -> None:
        self._enabled = True
        _INTEGRATION_LOGGER.setLevel(logging.DEBUG)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._enabled = False
        _INTEGRATION_LOGGER.setLevel(logging.INFO)
        self.async_write_ha_state()
