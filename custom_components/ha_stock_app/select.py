from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, device_info

_LOGGER = logging.getLogger(__name__)

TEST_NOTIFICATION_OPTIONS = {
    "eod_summary": "End-of-Day Summary",
    "market_open": "Market Open",
    "price_alert": "Price Alert",
    "paycheck_detected": "Paycheck Detected",
    "eod2_summary": "401k Update",
    "finnhub_error": "Finnhub API Error",
    "finnhub_ok": "Finnhub API OK",
    "credit_card_change": "Credit Card Change",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TestNotificationTypeSelect(entry)])


class TestNotificationTypeSelect(SelectEntity):
    _attr_icon = "mdi:bell-cog-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_test_notification_type"
        self._attr_name = "Test Notification Type"
        self._attr_options = list(TEST_NOTIFICATION_OPTIONS.values())
        self._attr_current_option = "End-of-Day Summary"
        self._value_map = {v: k for k, v in TEST_NOTIFICATION_OPTIONS.items()}
        self._attr_device_info = device_info(entry)

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        internal = self._value_map.get(option, "eod_summary")
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data is not None:
            data["test_notification_type"] = internal
        else:
            _LOGGER.warning("Entry data not available when selecting notification type")
        self.async_write_ha_state()
