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

All events are fired on the HA event bus (`ha_stock_app_*`) for use with Node-RED or automations to deliver mobile notifications.

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

### v2.3.0 — 2026-07-24
- Added a test suite covering the market calendar, timezone handling, scheduling and quiet hours. It has no dependencies — run `python3 -m unittest discover tests`
- Fixed end-of-day per-position P/L matching stocks by searching Monarch account *names* for the ticker. A one-letter ticker such as `A` was a substring of nearly every account name, and an account's balance was reported as the position's value. Positions are now matched against actual holdings by ticker, so the day's P/L is share count times per-share change rather than a figure derived from a percentage, and holdings split across accounts are summed
- Fixed a failed holdings fetch being indistinguishable from an account holding nothing, which is what allowed a transient error to look like a deletion. The refresh still succeeds on a partial failure, but records that the holdings set is incomplete so the entity cleanup leaves those sensors alone
- `monarchmoney` is now imported only when Monarch is actually enabled, so a stock-only install no longer loads it — and the "package not installed" messages became reachable for the first time
- Corrected `hacs.json`, which still advertised only the `sensor` platform
- Added a **Market Timezone** setting in the options flow. Scheduled events (market open, end-of-day summary, API self-test, 401k watch) now fire according to the market's clock regardless of Home Assistant's own timezone
- Fixed those scheduled events firing at the wrong time on any non-Eastern Home Assistant. They were registered with `async_track_time_change`, which matches HA's local wall clock, while the market-hours and trading-day checks inside them used Eastern — so a Pacific install ran the end-of-day summary three hours after the close, and a UK install ran it mid-session. Each occurrence is now scheduled as an absolute instant and re-armed, which also keeps it correct across DST transitions in either timezone
- Fixed a total quote-fetch failure being recorded as a successful poll. `get_quote` returns `None` instead of raising on an HTTP error, so a revoked or expired API key produced an empty result that looked identical to success — a fresh Last Stock Poll timestamp, no prices, and nothing reported as wrong. An empty result now fails the poll; a partial failure still succeeds but logs which symbols were missing
- Paycheck pay-window matching now uses Home Assistant's local date rather than Eastern, since pay dates are unrelated to trading hours
- Declared `monarchmoney==0.1.15` in the manifest so Home Assistant installs it. It was imported at module scope but never declared, so the integration only loaded on systems where another integration happened to pull the package in — and would fail to import at all on a clean install, even with Monarch disabled
- Fixed a Monarch outage permanently deleting its sensors: if Monarch was unreachable at startup, the stale-entity cleanup treated every Monarch sensor as removed and deleted it from the entity registry, losing entity IDs, renames, areas and long-term statistics. Cleanup now only prunes entities it could actually evaluate, so deselecting an account still removes its sensor while an outage leaves them intact
- Fixed a Monarch outage becoming permanent: `ConfigEntryNotReady` was caught by a broad `except Exception`, discarding Home Assistant's automatic retry. The coordinator is now kept on failure so the refresh button and the scheduled double-refresh recover it without a reload
- Fixed 401k quiet hours ignoring the minute component and misfiring for windows that don't cross midnight — an update landing at 08:15 with a quiet end of 08:35 was released 20 minutes early, and a same-day window like 16:00–20:00 marked almost the whole day as quiet
- Fixed the Last Stock Poll sensor raising `AttributeError`: `last_update_success_time` is only provided by `TimestampDataUpdateCoordinator`, which `StockCoordinator` now extends
- Fixed the setup wizard aborting with an unknown-error screen when the stock API test timed out — timeouts now route to the existing retry step
- Added a 15-second timeout to Finnhub requests (previously the aiohttp default of 5 minutes)

### v2.2.3 — 2026-07-24
- Added logbook platform — integration events (stock polls, price alerts, EOD summaries, paycheck detection, etc.) now appear in the device Activity tab
- Fires a `ha_stock_app_stock_update` event on every successful poll for logbook and automation use
- Added poll-triggered and market-closed INFO-level log messages for better System Log visibility
- Fixed poll frequency radio buttons not showing the saved selection: stored string values (e.g. `"300"`) didn't match integer dict keys (`300`) — now uses string keys throughout

### v2.2.1 — 2026-07-24
- Reverted direct notification delivery (back to Node-RED for notifications)
- Fixed poll frequency not persisting: added `vol.Coerce(int)` to all integer dropdown selectors (poll frequency, Monarch poll interval, 401k retry interval) — HA frontend sends JSON string keys, which silently failed `vol.In` validation against integer keys
- Fixed missing log entries: changed default log level from WARNING to INFO so operational messages (poll results, coordinator startup, market hours gating) appear in the HA system log
- Added startup log showing configured poll interval and market hours gate status
- Added per-poll log showing fetched prices

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
