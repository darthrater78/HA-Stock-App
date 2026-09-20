from __future__ import annotations

import importlib
import logging
from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.requirements import (
    RequirementsNotFound,
    async_clear_install_history,
    async_process_requirements,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MONARCH_PACKAGE = "monarchmoneycommunity"


class MonarchUpdateFlow(RepairsFlow):
    def __init__(self, *, installed: str = "", latest: str = "") -> None:
        super().__init__()
        self._installed = installed
        self._latest = latest

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            if not self._latest:
                _LOGGER.error(
                    "Cannot upgrade %s: the repair issue carries no target version",
                    MONARCH_PACKAGE,
                )
                return self.async_abort(reason="update_failed")

            # Install through Home Assistant instead of calling pip directly.
            # HA applies its own package_constraints.txt, so a future release of
            # this package cannot drag aiohttp or gql to a version core does not
            # pin. Moving those in HA's shared environment is what broke Monarch
            # auth for the core integration in v2.3.2 -- and because HA never
            # uninstalls pip packages, that damage outlived removing this one.
            # A conflict now fails the install rather than succeeding and taking
            # unrelated integrations down with it.
            #
            # The floor has to name the target version: HA skips a requirement
            # that is already satisfied, and the bare package name always is.
            requirement = f"{MONARCH_PACKAGE}>={self._latest}"

            # HA remembers a failed install for the rest of the run and refuses
            # to retry it. Pressing this button *is* a request to retry, so a
            # transient failure (no network, PyPI unreachable) must not need a
            # restart to clear.
            async_clear_install_history(self.hass)

            try:
                await async_process_requirements(self.hass, DOMAIN, [requirement])
            except RequirementsNotFound as err:
                _LOGGER.error("Failed to install %s: %s", requirement, err)
                return self.async_abort(reason="update_failed")

            importlib.invalidate_caches()
            self.hass.data.pop(f"{DOMAIN}_monarch_version_checked", None)
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
