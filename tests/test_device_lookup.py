"""Tests for const.entry_device_id — the config entry's device lookup.

Home Assistant 2026.8 made device identifiers unique per config entry and
deprecated device_registry.async_get_device (it stops working in 2027.8).
entry_device_id must use the per-entry lookup when it exists and fall back to
async_get_device on older versions. Home Assistant itself is stubbed, so this
suite runs with no dependencies, like test_market:

    python3 -m unittest discover tests
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parent.parent / "custom_components" / "ha_stock_app" / "const.py"
_spec = importlib.util.spec_from_file_location("ha_stock_app_const", _SRC)
const = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(const)

ENTRY_ID = "entry123"
IDENTIFIER = (const.DOMAIN, ENTRY_ID)


class _NewRegistry:
    """Device registry as of Home Assistant 2026.8."""

    def __init__(self, device):
        self.device = device
        self.calls = []

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        self.calls.append((identifier, config_entry_id))
        return self.device

    def async_get_device(self, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("deprecated async_get_device was called")


class _OldRegistry:
    """Device registry before Home Assistant 2026.8."""

    def __init__(self, device):
        self.device = device
        self.calls = []

    def async_get_device(self, identifiers=None, connections=None):
        self.calls.append(identifiers)
        return self.device


def _patch_registry(registry):
    """Stub homeassistant.helpers.device_registry.async_get to return registry."""
    dr = types.ModuleType("homeassistant.helpers.device_registry")
    dr.async_get = lambda hass: registry
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.device_registry = dr
    return mock.patch.dict(
        sys.modules,
        {
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.device_registry": dr,
        },
    )


class TestEntryDeviceId(unittest.TestCase):
    def test_uses_per_entry_lookup(self):
        registry = _NewRegistry(types.SimpleNamespace(id="dev1"))
        with _patch_registry(registry):
            self.assertEqual(const.entry_device_id(object(), ENTRY_ID), "dev1")
        self.assertEqual(registry.calls, [(IDENTIFIER, ENTRY_ID)])

    def test_falls_back_on_older_home_assistant(self):
        registry = _OldRegistry(types.SimpleNamespace(id="dev1"))
        with _patch_registry(registry):
            self.assertEqual(const.entry_device_id(object(), ENTRY_ID), "dev1")
        self.assertEqual(registry.calls, [{IDENTIFIER}])

    def test_missing_device_returns_none(self):
        for registry in (_NewRegistry(None), _OldRegistry(None)):
            with self.subTest(registry=type(registry).__name__), _patch_registry(registry):
                self.assertIsNone(const.entry_device_id(object(), ENTRY_ID))


if __name__ == "__main__":
    unittest.main()
