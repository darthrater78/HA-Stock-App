# HA Stock App

A Home Assistant custom integration (HACS) for tracking stock prices and, optionally, Monarch Money account balances — with all scheduling and notification logic built into the integration itself.

## Features

- **Stock tracking** — add/remove tickers from the HA UI, pluggable price provider (Finnhub by default), configurable poll frequency
- **Market-hours aware** — full NYSE holiday calendar (with early closes) gates polling and scheduled events, computed locally with no external dependency
- **Timezone-correct scheduling** — a configurable market timezone (Eastern by default) drives every scheduled event, so they fire at the right moment whatever Home Assistant's own timezone is, and stay correct across DST
- **Price alerts** — event fired when a symbol's daily change from previous close exceeds a configurable threshold, with configurable cooldown per symbol (15 min – 4 hours)
- **End-of-day summary** — fired at market close, including per-position P/L when Monarch is connected
- **Today's P&L sensor** — real-time daily P&L across selected Monarch investment accounts, using live Finnhub prices where available and falling back to Monarch's daily change. Configurable ticker mapping lets you pair each holding to a live symbol
- **Monarch Money (optional)** — account balances, individual stock holdings within investment/brokerage/IRA accounts, paycheck detection, and a double-refresh workaround for a known Monarch API race condition. Selectable accounts let you import only what you need. Uses the community-maintained [monarchmoneycommunity](https://github.com/bradleyseanf/monarchmoneycommunity) package; not affiliated with or endorsed by Monarch Money
- **401k delayed NAV reporting** — watches a Monarch holding sensor for value changes after market close, defers notifications during configurable quiet hours and releases them the next morning. Manual trigger button available for on-demand checks
- **Finnhub self-test** — validates API connectivity once per trading day
- **Manual refresh buttons** — button entities to trigger stock and Monarch data refreshes on demand, plus Sync Monarch Accounts (real bank sync) and 401k Update for manual NAV watch
- **Test notifications** — select a notification type from a dropdown and fire a test event, all from within the integration (no Developer Tools needed)
- **Repair issues** — surfaces connection failures, API problems, and package updates as HA repair issues with one-click fixes where possible
- **Account sync** — trigger a real bank sync via Monarch's API with configurable cooldown (4–24 hours), with completion status in the logbook
- **Daily change % sensors** — per-symbol percentage change sensors for history graph charting
- **Debug logging** — toggle verbose logging on/off from a switch entity on the device page (session-only, no integration reload)
- **Diagnostics** — Market Status, Last Stock Poll, and Monarch Package Version sensors show at a glance whether the market is open, when prices last updated, and what Monarch library version is installed
- **Credit card balance tracking** — fires an event whenever a credit card balance changes between Monarch polls (payment posted, new charge, etc.)
- **Logbook integration** — all scheduled actions and events (polls, price alerts, summaries, paycheck detection, credit card changes, Monarch refreshes) appear in the device's Activity tab
- **Device grouping** — all entities are grouped under a single HA Stock App device with proper `SensorDeviceClass.MONETARY` for currency display
- Every feature above is independently toggleable through the config/options flow

All events are fired on the HA event bus (`ha_stock_app_*`). The integration tracks prices and balances — **to get mobile notifications, import the included Node-RED flow** (see below).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Home Assistant                               │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐  │
│  │  Finnhub API  │    │  Monarch Money   │    │  NYSE Calendar    │  │
│  │  (providers)  │    │  (monarch)       │    │  (market)         │  │
│  └──────┬───────┘    └────────┬─────────┘    └────────┬──────────┘  │
│         │                     │                       │             │
│         ▼                     ▼                       │             │
│  ┌──────────────┐    ┌──────────────────┐             │             │
│  │    Stock      │    │    Monarch       │             │             │
│  │  Coordinator  │    │   Coordinator    │             │             │
│  └──────┬───────┘    └────────┬─────────┘             │             │
│         │                     │                       │             │
│         ├─────────────────────┤                       │             │
│         ▼                     ▼                       ▼             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                     Sensor Platform                         │    │
│  │  Stock prices · Monarch accounts · Holdings · Net worth     │    │
│  │  Today's P&L · Market status · Last poll · Package version  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌──────────────────────┐    ┌──────────────────────────────────┐   │
│  │  Button Platform      │    │  Select Platform                │   │
│  │  Refresh stocks       │    │  Test notification type picker  │   │
│  │  Refresh Monarch      │    └──────────────────────────────────┘   │
│  │  Sync Monarch         │    ┌──────────────────────────────────┐   │
│  │  401k Update          │    │  Switch Platform                │   │
│  │  Send test notif.     │    │  Debug logging toggle           │   │
│  └──────────────────────┘    └──────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   Scheduled Features                         │   │
│  │  9:15  Finnhub self-test          16:00  EOD summary         │   │
│  │  9:25  Monarch double-refresh     16:00  Monarch refresh     │   │
│  │  9:30  Market open notification   16:05  401k NAV watch      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     HA Event Bus                              │   │
│  │  ha_stock_app_stock_update    ha_stock_app_eod_summary       │   │
│  │  ha_stock_app_price_alert     ha_stock_app_eod2_summary      │   │
│  │  ha_stock_app_market_open     ha_stock_app_paycheck_detected │   │
│  │  ha_stock_app_finnhub_error   ha_stock_app_monarch_status    │   │
│  │  ha_stock_app_finnhub_ok      ha_stock_app_monarch_sync     │   │
│  │  ha_stock_app_credit_card_change                            │   │
│  └──────────────┬───────────────────────────────────────────────┘   │
│                 │                                                    │
│                 ▼                                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Logbook · Node-RED · Automations · Scripts                  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Module breakdown

| Module | Role |
|---|---|
| `__init__.py` | Entry setup, config migration, `ScheduledFeatures` class, service registration (`test_notification`), Monarch version check |
| `config_flow.py` | Multi-step config and options flow: stock API setup → Monarch auth → account selection → P&L ticker mapping → advanced settings (paycheck/401k) |
| `coordinator.py` | Two HA `DataUpdateCoordinator` subclasses — `StockCoordinator` polls Finnhub on a configurable interval with market-hours gating and price alerts; `MonarchCoordinator` polls Monarch with paycheck detection and a double-refresh mechanism |
| `sensor.py` | All sensor entities plus stale-entity cleanup. `TodayPLSensor` bridges both coordinators, using live Finnhub prices where a ticker mapping exists and Monarch's daily change as fallback |
| `button.py` | Manual refresh buttons (stocks, Monarch, 401k trigger, test notification) and Sync Monarch Accounts (real bank sync with configurable cooldown). Stock and 401k buttons fire their corresponding events immediately |
| `select.py` | Test notification type picker — sets which event the test button fires |
| `switch.py` | Debug logging toggle — session-only switch that sets the integration's log level without triggering an integration reload |
| `market.py` | NYSE calendar (holidays, early closes, trading-day checks), timezone resolution, `next_market_time` schedule resolver, quiet-hours logic, pay-window parser. Zero HA dependencies at module scope — testable standalone |
| `monarch.py` | Monarch Money API client: session persistence with `0o600` file permissions, exponential login backoff (rate-limit-aware), holdings retrieval with explicit error distinction from empty results |
| `providers.py` | Stock provider abstraction (`StockProvider` ABC) with `FinnhubProvider` implementation. 15-second request timeout. Symbol validation via regex |
| `logbook.py` | Logbook event descriptions for all eleven event types |
| `repairs.py` | Monarch package update repair flow — one-click pip upgrade from the HA repairs UI |

### Key design decisions

**Event-driven notifications.** The integration fires events on the HA bus and does not send notifications directly. This keeps the integration focused on data and scheduling, and lets the user choose their notification method (Node-RED, automations, scripts). The included Node-RED flow is optional.

**Absolute-instant scheduling.** Scheduled features are registered as one-shot `async_track_point_in_time` calls that re-arm after firing, rather than `async_track_time_change` wall-clock matches. This is necessary because the market's timezone and Home Assistant's timezone may observe DST on different dates — a wall-clock match in one zone drifts by an hour in the other. Each firing resolves the next market wall time to an absolute UTC instant.

**Graceful Monarch degradation.** A Monarch failure (network, auth, rate limit) never takes stock tracking down with it. `ConfigEntryNotReady` is caught and the coordinator is kept in a degraded state rather than propagated, which would put the entire config entry into setup-retry. Login failures back off exponentially (60s → 1h) with a higher floor (15m) when rate-limited.

**Holdings completeness tracking.** A failed holdings fetch for one account is distinct from that account holding nothing. The coordinator records whether the holdings set is complete; the sensor platform only prunes stale holding entities when the set is authoritative, preventing a transient error from permanently deleting sensors and their long-term statistics.

## Notifications — Node-RED Flow

The recommended way to receive mobile notifications is the ready-made Node-RED flow included in this repo:

**[`examples/node-red-notifications.json`](examples/node-red-notifications.json)** — import into Node-RED, point it at your mobile device, deploy. That's it.

It formats every event type the integration fires (price alerts, end-of-day summaries, market open, paycheck detection, 401k updates, Finnhub status) into clean mobile notifications with per-event channels, built-in rate limiting, duplicate suppression, and test-event support.

**Quick start:**
1. Node-RED → menu → **Import** → paste the contents of `examples/node-red-notifications.json` → **Import**
2. Open the **Mobile Notify** node → set the action to your device (e.g. `notify.mobile_app_pixel_9`)
3. **Deploy**
4. Test it from the HA Stock App device: pick a type from the **Test Notification Type** dropdown, press **Send Test Notification**

Full details (event table, rate-limiting behavior, customization) are in [`examples/README.md`](examples/README.md).

## Installation

Install via HACS as a custom repository, or copy `custom_components/ha_stock_app` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Configuration is entirely through the HA UI:

1. **Settings → Devices & Services → Add Integration → HA Stock App**
2. Enter your stock provider API key and ticker symbols
3. Optionally enable Monarch Money and provide credentials (with TOTP secret if MFA is enabled)
4. Select which Monarch accounts to import
5. Choose P&L accounts and map holdings to live Finnhub symbols
6. Fine-tune feature toggles (market hours gating, market timezone, EOD summary, 401k reporting, paycheck detection, debug logging, etc.) via the integration's **Configure** options

## Development

The market calendar, timezone handling, schedule resolution and quiet-hours logic
are covered by tests that need no dependencies — `market.py` deliberately keeps
Home Assistant out of its module scope:

```bash
python3 -m unittest discover tests
```

## Version History

### v2.7.3 — 2026-07-28
- **Added credit card balance change notifications** — fires `ha_stock_app_credit_card_change` whenever any credit card balance changes between Monarch polls (payments, charges, refunds). Includes account name, previous/new balance, and change amount. Logbook handler, test event, and notification type selector option included
- Node-RED example flow updated with credit card change listener and formatter nodes

### v2.7.2 — 2026-07-28
- **Fixed events missing from full Activity page** — custom events now include `entity_id` alongside `device_id` so they appear in both the collapsed Activity card on the device page and the full Activity log page. The HA frontend's full Activity page resolves `device_id` to `entity_ids` and queries with `entities_stmt()` which only checks `entity_id` in event data

### v2.7.0 — 2026-07-28
- **Added Monarch account sync button** — triggers a real bank sync via Monarch's `request_accounts_refresh_and_wait` API (not just a cached data refresh), with a 5-minute timeout. Fires `ha_stock_app_monarch_sync` events (started, completed, failed, cooldown) visible in the logbook
- **Added configurable sync cooldown** — prevents excessive sync requests with a configurable cooldown (4–24 hours, default 4h). Session-only tracking resets on restart. Configurable via the options flow
- Monarch coordinator gains `async_sync_accounts()` — runs the bank sync, then auto-refreshes the coordinator on success
- Logbook descriptions for all four sync event statuses (started, completed with duration, failed, cooldown with remaining time)

### v2.6.1 — 2026-07-27
- Bumped manifest version to match v2.6.0 release

### v2.6.0 — 2026-07-27
- **Moved debug logging to a switch entity** — toggle on the device page instead of the options flow. Session-only (sets logger level directly, no integration reload)
- **Added Monarch manual refresh to Activity logbook** — the Refresh Monarch Accounts button now fires an `ha_stock_app_monarch_status` event with `status: manual_refresh`, appearing in the device's Activity tab
- New `switch` platform registered in `PLATFORMS`
- Removed `enable_debug_logging` from options flow schema

### v2.5.6 — 2026-07-26
- **Added Today's P&L sensor** — real-time daily P&L across selected Monarch investment accounts, using live Finnhub prices where available with Monarch daily change as fallback
- **Added configurable P&L ticker mapping** — options flow step to map each Monarch holding to a Finnhub symbol, with auto-matching for identical tickers and explicit "None" for Monarch-only fallback
- **Added 401k Update button** — manual trigger for the NAV watch, fires the eod2_summary event immediately after refreshing Monarch data and comparing the balance change
- **Added portfolio dashboard example** — `examples/portfolio-dashboard.yaml` with stock prices, Monarch accounts, P&L, and 401k sections
- P&L account selector now filters to investment accounts only, showing tickers in dropdown labels
- P&L ticker mapping shows holding name and account context for disambiguation
- Manual refresh buttons now fire regardless of market hours and trigger notification events immediately
- 401k button refreshes Monarch data before comparing values, so the change reflects the actual current balance
- Monarch version check skipped if repair issue already exists (prevents redundant PyPI calls)
- Fixed Monarch update repair showing on every reload
- Account list cached across options flow steps (eliminates redundant API calls when navigating back)
- Synced translations/en.json with strings.json
- Fixed P&L sensor state_class (TOTAL, not MEASUREMENT)
- Dropped stock poll log messages from INFO to DEBUG (reduces log noise by ~78 entries per trading day)
- Cached P&L computation per update cycle (was computing twice per state write)
- Scheduled Monarch double-refresh now fires an event visible in the logbook
- Improved exception logging in Monarch update check

### v2.4.0 — 2026-07-25
- **Fixed `gql` version conflict that broke the HA core Monarch Money integration.** The v2.3.2 manifest pinned `gql<4`, but `monarchmoney` itself requires `gql>=4.0` and the HA core Monarch Money integration (`monarchmoneycommunity`) requires `gql==4.0`. Installing this HACS integration downgraded `gql` from 4.x to 3.x in HA's shared Python environment, breaking Monarch authentication for both integrations. The damage persisted after disabling or removing the HACS integration because HA does not uninstall pip packages — only a full restore reverted the `gql` version
- Changed `gql<4` to `gql>=4.0` to match upstream requirements
- Relaxed `monarchmoney==0.1.15` to `monarchmoney>=0.1.15` to avoid forcing a specific version
- Removed the unnecessary `gql` import pre-check from setup (the manifest handles package installation)
- Switched from the abandoned `monarchmoney` package to the actively maintained `monarchmoneycommunity`
- Added PyPI version check for `monarchmoneycommunity` with a fixable repair issue for one-click upgrades
- Added Monarch Package Version diagnostic sensor
- Streamlined the setup flow by removing confirmation screens
- Added paycheck account selector for single-account detection
- Surfaced connection failures as HA repair issues (Monarch auth, stock API, Finnhub self-test)
- Made the Node-RED notification flow more prominent in the README — it's the recommended way to get mobile notifications from the integration

### v2.3.3 — 2026-07-25
- Set an explicit 30-second timeout on Monarch requests. The `monarchmoney` client defaults to 10 seconds, which is tight for a login round trip — and a timeout was indistinguishable from a rejected credential, so it triggered the same backoff as a real auth failure
- Made the login backoff rate-limit aware. `monarchmoney` has no handling for HTTP 429, so a rate-limit response arrives as an ordinary error; retrying one of those after 60 seconds only prolongs the lockout. A failure that looks like a rate limit now starts at 15 minutes instead, still capping at an hour. Monarch applies the limit per account, so this matters for anything else signed in as the same user

### v2.3.2 — 2026-07-25
- **Constrained `gql` to `<4`** — this was incorrect and is reverted in v2.4.0; see that entry for details
- **Stopped re-authenticating on every failed poll.** A fetch failure discarded the Monarch session, so the next poll performed a full login. With a persistent fault that became a login attempt every poll interval, and Monarch answered with `HTTP 429: Too Many Requests` — locking out other integrations using the same account. The session is now retained on fetch failures, and failed logins back off exponentially from 60 seconds up to an hour

### v2.3.1 — 2026-07-25
Fixes to the optional Node-RED example flow only. The integration itself is unchanged from v2.3.0.

- Fixed the example flow flooding devices. Every event node held a subscription to the entire Home Assistant event bus, because the `server-events` node's own `event_type` filter is not honoured by all versions of `node-red-contrib-home-assistant-websocket`. `state_changed` fires hundreds of times a minute, and each one was formatted into a notification — enough to require rebooting a phone
- Rebuilt the flow around a single subscription and a router, so an event reaches exactly one formatter rather than waking eight. 19 nodes down to 13
- Added rate limiting that applies to test events too. They were previously exempt from every limit, which is why the one path that can be fired repeatedly had no protection at all
- Added duplicate collapse, so an event delivered more than once produces a single notification. Limiter state moved to global context so several copies of the flow share one budget
- Each formatter now refuses to build a notification from a payload lacking that event's fields, rather than emitting `undefined NaN%`

### v2.3.0 — 2026-07-24
- Fixed a typo in the quiet-hours or pay-window fields stopping the integration from loading. Both are free-form text; they now reject bad input in the form with an explanatory error, and fall back to the default at runtime instead of raising during setup. Pay-window days are range-checked too, so a value like `99-200` no longer parses cleanly while silently never matching
- Fixed the Monarch double-refresh timer not being cancelled on unload, which left it to fire into a torn-down coordinator
- Removed the superseded standalone Node-RED engine (`node-red-portfolio-flow-v2.json` and its add-ons). The integration has done that work since v2.0.0; the flows remain in git history
- Added `examples/node-red-notifications.json`, an optional Node-RED flow that turns the integration's events into mobile notifications, formatted to match the engine it replaced
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
