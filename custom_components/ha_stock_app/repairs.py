from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MONARCH_PACKAGE = "monarchmoneycommunity"


def _pip_upgrade(package: str) -> bool:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", package],
            timeout=120,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


class MonarchUpdateFlow(RepairsFlow):
    def __init__(self, *, installed: str = "", latest: str = "") -> None:
        super().__init__()
        self._installed = installed
        self._latest = latest

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            success = await self.hass.async_add_executor_job(
                _pip_upgrade, MONARCH_PACKAGE
            )
            if not success:
                return self.async_abort(reason="update_failed")
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Monarch Package Updated",
                    "message": (
                        f"monarchmoneycommunity has been upgraded to {self._latest}. "
                        "Restart Home Assistant to use the new version."
                    ),
                    "notification_id": f"{MONARCH_PACKAGE}_updated",
                },
            )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="init",
            description_placeholders={
                "installed": self._installed,
                "latest": self._latest,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    data = data or {}
    return MonarchUpdateFlow(
        installed=str(data.get("installed", "")),
        latest=str(data.get("latest", "")),
    )
