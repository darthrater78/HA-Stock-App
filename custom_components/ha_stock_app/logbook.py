from __future__ import annotations

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_STOCK_UPDATE,
    EVENT_PRICE_ALERT,
    EVENT_EOD_SUMMARY,
    EVENT_EOD2_SUMMARY,
    EVENT_PAYCHECK_DETECTED,
    EVENT_MONARCH_STATUS,
    EVENT_MARKET_OPEN,
    EVENT_FINNHUB_ERROR,
    EVENT_FINNHUB_OK,
)

NAME = "HA Stock App"


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event,
) -> None:

    @callback
    def describe_stock_update(event: Event) -> dict[str, str]:
        prices = event.data.get("prices", {})
        parts = [f"{s} ${p:.2f}" for s, p in prices.items()]
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"polled prices: {', '.join(parts)}" if parts else "polled prices",
        }

    @callback
    def describe_price_alert(event: Event) -> dict[str, str]:
        d = event.data
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: (
                f"{d.get('symbol')} price alert: ${d.get('price', 0):.2f} "
                f"({d.get('direction', '')} {d.get('change_pct', 0):.1f}%)"
            ),
        }

    @callback
    def describe_eod_summary(event: Event) -> dict[str, str]:
        stocks = event.data.get("stocks", {})
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"end-of-day summary for {len(stocks)} stock(s)",
        }

    @callback
    def describe_eod2_summary(event: Event) -> dict[str, str]:
        d = event.data
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"401k update: ${d.get('new_value', 0):,.2f} ({d.get('day_change_pct', 0):+.2f}%)",
        }

    @callback
    def describe_paycheck(event: Event) -> dict[str, str]:
        d = event.data
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"paycheck detected: ${d.get('amount', 0):,.2f}",
        }

    @callback
    def describe_monarch_status(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"Monarch Money went {event.data.get('status', 'unknown')}",
        }

    @callback
    def describe_market_open(event: Event) -> dict[str, str]:
        d = event.data
        msg = "market opened"
        if d.get("early_close"):
            msg += f" (early close at {d.get('close_time', '13:00')})"
        return {LOGBOOK_ENTRY_NAME: NAME, LOGBOOK_ENTRY_MESSAGE: msg}

    @callback
    def describe_finnhub_error(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"Finnhub self-test failed: {event.data.get('error', 'unknown')}",
        }

    @callback
    def describe_finnhub_ok(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: NAME,
            LOGBOOK_ENTRY_MESSAGE: f"Finnhub self-test passed ({event.data.get('symbol')} ${event.data.get('price', 0):.2f})",
        }

    async_describe_event(DOMAIN, EVENT_STOCK_UPDATE, describe_stock_update)
    async_describe_event(DOMAIN, EVENT_PRICE_ALERT, describe_price_alert)
    async_describe_event(DOMAIN, EVENT_EOD_SUMMARY, describe_eod_summary)
    async_describe_event(DOMAIN, EVENT_EOD2_SUMMARY, describe_eod2_summary)
    async_describe_event(DOMAIN, EVENT_PAYCHECK_DETECTED, describe_paycheck)
    async_describe_event(DOMAIN, EVENT_MONARCH_STATUS, describe_monarch_status)
    async_describe_event(DOMAIN, EVENT_MARKET_OPEN, describe_market_open)
    async_describe_event(DOMAIN, EVENT_FINNHUB_ERROR, describe_finnhub_error)
    async_describe_event(DOMAIN, EVENT_FINNHUB_OK, describe_finnhub_ok)
