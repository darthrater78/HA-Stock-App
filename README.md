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
- **Debug logging** — toggle verbose logging on/off from the options flow
- **Device grouping** — all entities are grouped under a single HA Stock App device with proper `SensorDeviceClass.MONETARY` for currency display
- Every feature above is independently toggleable through the config/options flow

Node-RED is used only as a thin notification layer: it listens for `ha_stock_app_*` events on the HA event bus and formats/delivers mobile notifications. All business logic (gating, thresholds, scheduling) lives in the integration.

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
