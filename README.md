# HA Stock App

A Home Assistant custom integration (HACS) for tracking stock prices and, optionally, Monarch Money account balances — with all scheduling and notification logic built into the integration itself.

## Features

- **Stock tracking** — add/remove tickers from the HA UI, pluggable price provider (Finnhub by default), configurable poll frequency
- **Market-hours aware** — full NYSE holiday calendar (with early closes) gates polling and scheduled events, computed locally with no external dependency
- **Price alerts** — event fired when a symbol moves past a configurable threshold
- **End-of-day summary** — fired at market close, including per-position P/L when Monarch is connected
- **Monarch Money (optional)** — account balances, individual stock holdings within investment/brokerage/IRA accounts, paycheck detection, and a double-refresh workaround for a known Monarch API race condition. Selectable accounts let you import only what you need. Uses the unofficial [monarchmoney](https://github.com/hammem/monarchmoney) package; not affiliated with or endorsed by Monarch Money
- **401k delayed NAV reporting** — defers notifications during configurable quiet hours and releases them the next morning
- **Finnhub self-test** — validates API connectivity once per trading day
- **Manual refresh buttons** — button entities to trigger stock and Monarch data refreshes on demand
- **Test notifications** — select a notification type from a dropdown and fire a test event, all from within the integration (no Developer Tools needed)
- **Direct notifications** — configure a HA notify service in the options flow and all events are delivered as formatted mobile notifications (no Node-RED needed)
- **Debug logging** — toggle verbose logging on/off from the options flow
- **Device grouping** — all entities are grouped under a single HA Stock App device with proper `SensorDeviceClass.MONETARY` for currency display
- Every feature above is independently toggleable through the config/options flow

Notifications can be delivered directly to any HA notify service (e.g. `notify.mobile_app_*`) — configure the target in the options flow. All events are also fired on the HA event bus (`ha_stock_app_*`) for use with Node-RED or automations.

## Installation

Install via HACS as a custom repository, or copy `custom_components/ha_stock_app` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Configuration is entirely through the HA UI:

1. **Settings → Devices & Services → Add Integration → HA Stock App**
2. Enter your stock provider API key and ticker symbols
3. Optionally enable Monarch Money and provide credentials (with TOTP secret if MFA is enabled)
4. Select which Monarch accounts to import (all selected by default)
5. Fine-tune feature toggles (market hours gating, EOD summary, 401k reporting, paycheck detection, debug logging, etc.) via the integration's **Configure** options

## Version History

### v2.2.0 — 2026-07-24
- Added direct notification delivery: configure a HA notify service (e.g. `notify.mobile_app_dad_pixel`) in the options flow and all events are pushed straight to your phone — no Node-RED required
- Notifications are formatted per event type with color, channel, and priority (price alerts, EOD summary, market open, paycheck detected, 401k update, Finnhub status, Monarch status)
- Events still fire on the HA bus for Node-RED / automation use

### v2.1.3 — 2026-07-24
- Fixed `state_class` warning: monetary sensors no longer set `MEASUREMENT` (only `TOTAL` or none)
- Fixed blocking import warning on startup (`gql` now pre-imported off the event loop)
- Fixed stale entities when accounts are deselected in options flow (entity registry cleanup)

### v2.1.2 — 2026-07-24
- Fixed device_info using plain dict instead of DeviceInfo (broke entity setup on newer HA)
- Fixed holdings type filter to be case-insensitive (brokerage/IRA accounts were silently skipped)
- Added debug logging to holdings fetch for troubleshooting

### v2.1.1 — 2026-07-24
- Fixed integration icon not showing (moved icon.png/logo.png into integration directory)
- Fixed stock poll frequency not retaining selection in options flow

### v2.1.0 — 2026-07-24
- Added account selection: choose which Monarch accounts to import (multi-select in both initial setup and options flow)
- Added individual stock holding sensors for investment/brokerage/IRA accounts from Monarch
- All entities now grouped under a single HA Stock App device with `SensorDeviceClass.MONETARY` for proper currency display
- Added button entities: Refresh Stock Prices, Refresh Monarch Accounts, Send Test Notification
- Added select entity: Test Notification Type dropdown (7 notification types) — paired with the test button for in-integration testing
- Added debug logging toggle in options flow
- New platforms: `button`, `select` (in addition to existing `sensor`)

### v2.0.0 — 2026-07-24
- Pivoted from Node-RED-only flows to a full HACS integration
- Added NYSE market calendar (`market.py`) — holidays, early closes, DST-aware Eastern time
- Added market-hours gate to stock polling
- Added scheduled features: market open notification, Finnhub self-test, EOD1 summary with per-position P/L, Monarch double-refresh, 401k deferred NAV reporting
- Made previously hardcoded values configurable: Monarch poll interval, paycheck threshold/pay windows, 401k sensor/quiet hours
- Config flow bumped to version 2 with automatic migration for existing installs
- Added Node-RED notification listeners for the new events

### v1.0.0
- Initial HACS integration: stock price polling, Monarch account balances, config flow with connectivity tests, basic price alert / EOD / paycheck / Monarch status events
