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
| `credit_card_change` | Payment or charge with before/after balance | `Stocks` |

`stock_update` fires on every poll and is intentionally not wired to a
notification.

### Rate limiting

Three layers, in the **Rate Limit + Test Tag** node:

- **Duplicate collapse** — the same message is never delivered twice in quick
  succession, test events included (5s window for tests, 10 minutes otherwise).
  This is what makes the flow immune to being delivered the same event several
  times, whether from a second deployed copy or a websocket subscription that
  outlived a redeploy.
- **Burst limit** — at most 5 notifications in any 60 seconds, *including test
  events*. The backstop: nothing legitimate needs more.
- **Hourly ceiling** — at most 12 non-test notifications an hour.
- **Per-title cooldown** — the same notification is not repeated within 10
  minutes. Price alerts instead fire once per whole-percent level with an hourly
  cooldown, so a stock hovering at +1.2% notifies once rather than every poll.
  Finnhub errors are deduped for two hours.

### Shape

```
Price Alert Event  ->  Format Price Alert  ->\
EOD Summary Event  ->  Format EOD Summary  -> >  Rate Limit  ->  Mobile Notify
        ... x8            ... x8            ->/
```

**Each listener subscribes to exactly one event type, and that filter is applied
by Home Assistant, not by Node-RED.** The websocket client passes the type
straight to HA's `subscribe_events`:

```ts
for (const type of add) {
    this.#unsubCallback[type] = await this.client.subscribeEvents(
        (ent) => this.onClientEvents(ent), type);
}
```

So HA only ever sends these nine event types down the socket. `state_changed`
— which fires hundreds of times a minute in a normal install — is never
transmitted, never deserialised, and never wakes a node.

**Never blank an Event Type field.** An empty one takes the library's `__ALL__`
branch and subscribes to the entire bus; the package's own documentation warns
this "may overload the WebSocket message queue". Nine filtered subscriptions
cost far less than one unfiltered one, so node count is the wrong thing to
optimise here.

Each node sets both `eventType` and `event_type`. Current releases read the
former, older ones the latter, and a flow exported from an older version filters
nothing on a newer install — which is exactly how this flow once ended up
subscribed to everything.

A payload that reaches a formatter but lacks the event's fields is refused and
logged as a warning. Without that, an unexpected payload still produced a
notification — `undefined NaN%` and similar.

Limiter state lives in Node-RED **global** context, so every copy of the flow
shares one budget rather than each getting its own. It resets when Node-RED
restarts.

If you ever see one event arrive as several notifications, restart Node-RED —
the Home Assistant websocket node can leave a subscription behind across a
redeploy, and each stale subscription redelivers every event.

### Customising

Message text lives in the per-event **Format …** function nodes; each is
self-contained, so edits are local. The **Rate Limit + Test Tag** node is
the single exit gate — everything passes through it before the notify call, so
that is the place to add a global mute or a quiet-hours check.
