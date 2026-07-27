from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_401K_SENSOR,
    CONF_ENABLE_401K_REPORTING,
    DEFAULT_ENABLE_401K_REPORTING,
    DOMAIN,
    EVENT_EOD2_SUMMARY,
    EVENT_MONARCH_STATUS,
    device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [RefreshStocksButton(entry)]

    if data.get("monarch_coordinator"):
        entities.append(RefreshMonarchButton(entry))

    scheduler = data.get("scheduler")
    eod2_enabled = entry.options.get(
        CONF_ENABLE_401K_REPORTING, DEFAULT_ENABLE_401K_REPORTING
    )
    if scheduler and eod2_enabled:
        entities.append(Trigger401kCheckButton(entry))

    entities.append(SendTestNotificationButton(entry))
    async_add_entities(entities)


class RefreshStocksButton(ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_refresh_stocks"
        self._attr_name = "Refresh Stock Prices"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            _LOGGER.warning("Entry data not available during stock refresh")
            return
        coordinator = data.get("stock_coordinator")
        if coordinator:
            await coordinator.async_force_refresh()
        scheduler = data.get("scheduler")
        if scheduler:
            await scheduler._eod1_summary()


class RefreshMonarchButton(ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_refresh_monarch"
        self._attr_name = "Refresh Monarch Accounts"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            _LOGGER.warning("Entry data not available during Monarch refresh")
            return
        coordinator = data.get("monarch_coordinator")
        if coordinator:
            await coordinator.async_request_refresh()
            self.hass.bus.async_fire(
                EVENT_MONARCH_STATUS, {"status": "manual_refresh"}
            )


class SendTestNotificationButton(ButtonEntity):
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_test_notification"
        self._attr_name = "Send Test Notification"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        from . import _TEST_EVENTS

        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            _LOGGER.warning("Entry data not available during test notification")
            return
        test_type = data.get("test_notification_type", "eod_summary")
        if test_type in _TEST_EVENTS:
            event_name, event_data = _TEST_EVENTS[test_type]
            self.hass.bus.async_fire(event_name, {**event_data, "test": True})
            _LOGGER.info("Fired test event: %s", event_name)


class Trigger401kCheckButton(ButtonEntity):
    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_trigger_401k"
        self._attr_name = "401k Update"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            _LOGGER.warning("Entry data not available during 401k trigger")
            return
        sensor_id = self._entry.options.get(CONF_401K_SENSOR, "")
        if not sensor_id:
            _LOGGER.warning("No 401k sensor entity configured")
            return
        state = self.hass.states.get(sensor_id)
        if not state:
            _LOGGER.warning("401k sensor %s not found", sensor_id)
            return
        try:
            old_val = float(state.state)
        except (ValueError, TypeError):
            old_val = 0.0

        coordinator = data.get("monarch_coordinator")
        if coordinator:
            await coordinator.async_request_refresh()

        state = self.hass.states.get(sensor_id)
        try:
            new_val = float(state.state) if state else old_val
        except (ValueError, TypeError):
            new_val = old_val

        change = round(new_val - old_val, 2)
        change_pct = round((change / old_val * 100), 2) if old_val else 0.0

        self.hass.bus.async_fire(EVENT_EOD2_SUMMARY, {
            "sensor": sensor_id,
            "previous_value": old_val,
            "new_value": new_val,
            "day_change": change,
            "day_change_pct": change_pct,
            "deferred": False,
            "manual": True,
        })
        _LOGGER.info(
            "401k manual update: %s was $%.2f, now $%.2f (change: $%.2f / %.2f%%)",
            sensor_id, old_val, new_val, change, change_pct,
        )
