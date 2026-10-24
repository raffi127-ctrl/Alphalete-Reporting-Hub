# Owner Sales Hourly

Raf, Slack 2026-10-24: *"On our 'alphalete owners' iMessage chat, once an hour.
Can we get an update on how many sales each owner is at please?"*

## What it texts

Into **Alphalete Owners 🔥 - Real** (same chat `owner_chat_texts` sends the
trackers to), from Lucy 1:

```
Owner Sales Today - 5:50 PM CT

1. Jairo Ruiz 33
2. Colten Wright 31
...
🏆 TOTAL: 261
```

- :50 every hour, Mon–Sat, 12 PM–9 PM Central.
- Skipped when no number moved since the last text.
- Not sent before any office has relayed a sale that day.

## Source

Lucy ECO relay: **Lucy Access App** workbook → **ICD Relay** tab → **Sales JSON**
(today's row per office), read by `icd_sales_board.relay_read`.
Per rep, the campaign's own total (`shared.sale_hype.rep_total`: AT&T
Int+Up+DTV+NL, Box Sales, NDS +Air), then summed per owner (Carlos's B2B AT&T +
Box = one line). Owner names come from `icd_alerts.offices`.

**Only owners whose laptop runs Lucy ECO and has relayed a sale today are on
the list.** No relay row = no line (not a 0).

## Run

```
# preview: prints the text, sends nothing (on a Mac also resolves the chat)
python -m automations.owner_sales_hourly.run --force

# live (what the LaunchAgent runs)
python -m automations.owner_sales_hourly.run --send
```

## Deploy (Lucy 1)

1. `lucy update`, then preview: `lucy rerun owner_sales_hourly --machine "Lucy 1"`.
2. `lucy rerun install_owner_sales_hourly_agent --machine "Lucy 1"`.

Tests: `python -m unittest automations.owner_sales_hourly.test_build`
