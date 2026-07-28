from __future__ import annotations

import logging
import time

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_401K_SENSOR,
    CONF_ENABLE_401K_REPORTING,
    CONF_MONARCH_SYNC_COOLDOWN,
    DEFAULT_ENABLE_401K_REPORTING,
    DEFAULT_MONARCH_SYNC_COOLDOWN,
    DOMAIN,
    EVENT_EOD2_SUMMARY,
    EVENT_MONARCH_STATUS,
    EVENT_MONARCH_SYNC,
    device_info,
)

_LOGGER = logging.getLogger(__name__)


def _device_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    return device.id if device else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [RefreshStocksButton(entry)]

    if data.get("monarch_coordinator"):
        entities.append(RefreshMonarchButton(entry))
        entities.append(SyncMonarchAccountsButton(entry))

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
            _LOGGER.info("Manual Monarch refresh triggered")
            await coordinator.async_request_refresh()
            _LOGGER.debug("Manual Monarch refresh completed")
            self.hass.bus.async_fire(
                EVENT_MONARCH_STATUS,
                {"status": "manual_refresh", "device_id": _device_id(self.hass, self._entry)},
            )


class SyncMonarchAccountsButton(ButtonEntity):
    _attr_icon = "mdi:cloud-sync"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_sync_monarch"
        self._attr_name = "Sync Monarch Accounts"
        self._attr_device_info = device_info(entry)
        self._last_sync: float = 0

    @property
    def _cooldown_seconds(self) -> int:
        minutes = int(
            self._entry.options.get(
                CONF_MONARCH_SYNC_COOLDOWN, DEFAULT_MONARCH_SYNC_COOLDOWN
            )
        )
        return minutes * 60

    async def async_press(self) -> None:
        dev_id = _device_id(self.hass, self._entry)
        cooldown_minutes = self._cooldown_seconds // 60
        _LOGGER.debug(
            "Sync button pressed (cooldown=%dm, last_sync=%s)",
            cooldown_minutes,
            f"{int(time.monotonic() - self._last_sync)}s ago" if self._last_sync else "never",
        )
        now = time.monotonic()
        if self._last_sync and (now - self._last_sync) < self._cooldown_seconds:
            remaining = int((self._cooldown_seconds - (now - self._last_sync)) / 60)
            self.hass.bus.async_fire(
                EVENT_MONARCH_SYNC,
                {"status": "cooldown", "remaining_minutes": remaining, "device_id": dev_id},
            )
            _LOGGER.info("Monarch sync cooldown: %d minutes remaining", remaining)
            return

        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            _LOGGER.warning("Entry data not available during Monarch sync")
            return
        coordinator = data.get("monarch_coordinator")
        if not coordinator:
            _LOGGER.warning("Monarch coordinator not available for sync")
            return

        self.hass.bus.async_fire(EVENT_MONARCH_SYNC, {"status": "started", "device_id": dev_id})
        _LOGGER.info("Monarch account sync started")
        start = time.monotonic()

        success = await coordinator.async_sync_accounts()

        duration = int(time.monotonic() - start)
        if success:
            self._last_sync = time.monotonic()
            self.hass.bus.async_fire(
                EVENT_MONARCH_SYNC,
                {"status": "completed", "duration_seconds": duration, "device_id": dev_id},
            )
            _LOGGER.info("Monarch account sync completed in %ds", duration)
        else:
            self.hass.bus.async_fire(
                EVENT_MONARCH_SYNC,
                {"status": "failed", "duration_seconds": duration, "device_id": dev_id},
            )
            _LOGGER.warning("Monarch account sync failed after %ds", duration)


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
            self.hass.bus.async_fire(event_name, {**event_data, "test": True, "device_id": _device_id(self.hass, self._entry)})
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
            "device_id": _device_id(self.hass, self._entry),
        })
        _LOGGER.info(
            "401k manual update: %s was $%.2f, now $%.2f (change: $%.2f / %.2f%%)",
            sensor_id, old_val, new_val, change, change_pct,
        )
