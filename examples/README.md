# Examples

## `node-red-notifications.json`

A Node-RED flow that listens for the integration's `ha_stock_app_*` events and
sends formatted notifications to a mobile device. Optional — the integration
works without it, and fires its events either way.

### Import

1. Node-RED → menu → **Import** → paste the file contents → **Import**.
2. Open the **Mobile Notify** node and set its action to your own device, e.g.
   `notify.mobile_app_pixel_9`. The flow ships with `notify.mobile_app_owner`.
3. Check the Home Assistant server on each node points at your HA connection.
4. **Deploy**.

### Test it

Use the integration's own controls rather than injecting messages by hand:

1. Pick a type from the **Test Notification Type** dropdown on the HA Stock App
   device.
2. Press **Send Test Notification**.

Test events are prefixed 🧪 and bypass repeat suppression, so the button always
delivers.

### What it sends

| Event | Notification | Channel |
|---|---|---|
| `price_alert` | `🟢 VOO (S&P 500) +1.25% today` | `Stocks`, or `stock_alert` below −2% |
| `eod_summary` | Per-position lines, then a portfolio total | `Stocks` |
| `market_open` | Market open, plus early-close time when there is one | `Stocks` |
| `eod2_summary` | 401k old → new, day P/L, index change | `Stocks` |
| `paycheck_detected` | Estimated paycheck and whether it fits a pay window | `Network Restored` |
| `monarch_status` | Monarch went down or recovered | `Flow Errors` |
| `finnhub_error` | Self-test failure, deduped for 2h | `Flow Errors` |
| `finnhub_ok` | Silent unless manually triggered | `Flow Errors` |

`stock_update` fires on every poll and is intentionally not wired to a
notification.

### Repeat suppression

Price alerts fire once per whole-percent level with an hourly cooldown, so a
stock drifting around +1.2% notifies once rather than on every poll. Crossing to
the next level notifies again, and each symbol is tracked separately. Finnhub
errors are deduped for two hours. State lives in Node-RED flow context and
resets on redeploy.

### Customising

Message text lives in the per-event **Format …** function nodes; each is
self-contained, so edits are local. The **Test Tag + Repeat Suppression** node is
the single exit gate — everything passes through it before the notify call, so
that is the place to add a global mute or a quiet-hours check.
