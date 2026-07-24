from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

_LOGGER = logging.getLogger(__name__)


def _format_event(event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    kind = event_type.replace("ha_stock_app_", "")

    title = message = ""
    color = "#1565C0"
    priority = "default"
    channel = "Stock Alerts"

    if kind == "price_alert":
        d = data
        arrow = "\U0001f4c8" if d.get("direction") == "up" else "\U0001f4c9"
        sign = "+" if d.get("direction") == "up" else ""
        title = f"{arrow} {d['symbol']} Price Alert"
        message = (
            f"{d['symbol']} {sign}{d['change_pct']}% "
            f"(${d['previous']:.2f} → ${d['price']:.2f})"
        )
        color = "#2E7D32" if d.get("direction") == "up" else "#D32F2F"
        priority = "high"

    elif kind == "eod_summary":
        stocks = data.get("stocks", {})
        if not stocks:
            return None
        lines = []
        has_loss = False
        for sym, s in stocks.items():
            sign = "+" if s["change_pct"] >= 0 else ""
            lines.append(f"{sym} {sign}{s['change_pct']}% (${s['price']:.2f})")
            if s["change_pct"] < 0:
                has_loss = True
        title = "\U0001f4ca End of Day Summary"
        message = "\n".join(lines)
        color = "#FF8F00" if has_loss else "#2E7D32"

    elif kind == "market_open":
        title = "\U0001f514 Market Open"
        message = "NYSE is now open."
        if data.get("early_close"):
            message += f" Early close today at {data['close_time']} ET."
        color = "#2E7D32"

    elif kind == "paycheck_detected":
        amt = round(data["amount"])
        bal = round(data["new_balance"])
        in_window = data.get("in_pay_window", False)
        title = "\U0001f4b0 Likely Paycheck" if in_window else "\U0001f4b5 Large Cash Increase"
        window_text = " — lines up with payday" if in_window else ""
        message = f"Cash increased by +${amt:,}{window_text}\nNew balance: ${bal:,}"
        color = "#2E7D32"
        priority = "high"

    elif kind == "eod2_summary":
        change = data.get("day_change", 0)
        pct = data.get("day_change_pct", 0)
        new_val = data.get("new_value", 0)
        sign = "+" if change >= 0 else ""
        arrow = "\U0001f4c8" if change >= 0 else "\U0001f4c9"
        title = f"{arrow} 401k Update"
        message = f"401k {sign}${change:.2f} ({sign}{pct:.2f}%)\nNew value: ${new_val:.2f}"
        if data.get("deferred"):
            message += "\n(Deferred from overnight)"
        color = "#2E7D32" if change >= 0 else "#D32F2F"

    elif kind == "finnhub_error":
        title = "⚠️ Finnhub API Error"
        message = f"Self-test failed for {data['symbol']}: {data['error']}"
        color = "#D32F2F"
        priority = "high"

    elif kind == "finnhub_ok":
        title = "✅ Finnhub API OK"
        message = f"{data['symbol']} quote returned: ${data['price']:.2f}"
        color = "#2E7D32"

    elif kind == "monarch_status":
        if data.get("status") == "online":
            title = "✅ Monarch Restored"
            message = "Monarch sensors are reporting again."
            color = "#2E7D32"
        else:
            title = "⚠️ Monarch Down"
            message = "Monarch sensors are unavailable."
            color = "#D32F2F"
            priority = "high"

    else:
        return None

    return {
        "title": title,
        "message": message,
        "data": {"color": color, "channel": channel, "priority": priority, "ttl": 0},
    }


async def async_send_notification(
    hass: HomeAssistant,
    notify_service: str,
    event_type: str,
    event_data: dict[str, Any],
) -> None:
    if not notify_service:
        return

    payload = _format_event(event_type, event_data)
    if payload is None:
        return

    domain, _, service = notify_service.partition(".")
    if not service:
        service = notify_service
    domain = "notify"

    try:
        await hass.services.async_call(
            domain,
            service,
            payload,
            blocking=False,
        )
        _LOGGER.debug("Sent %s notification via %s.%s", event_type, domain, service)
    except (HomeAssistantError, ServiceNotFound):
        _LOGGER.warning("Failed to send notification via %s.%s", domain, service, exc_info=True)
