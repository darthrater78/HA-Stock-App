from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLE_DEBUG_LOGGING,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    DOMAIN,
    device_info,
)

_LOGGER = logging.getLogger(__name__)


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

    @property
    def is_on(self) -> bool:
        return self._entry.options.get(
            CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_debug(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_debug(False)

    async def _set_debug(self, enabled: bool) -> None:
        new_options = {**self._entry.options, CONF_ENABLE_DEBUG_LOGGING: enabled}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        from . import _apply_debug_logging
        _apply_debug_logging(self._entry)
        self.async_write_ha_state()
