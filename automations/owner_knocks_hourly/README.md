# Owner Knocks Hourly

Raf, Slack 2026-10-29: *"Once an hour, can we get a report of the owners
knocking numbers please? We can do guys on LucyECHO only ... [his Total Knocks
board] but now it be the owners in the org. This can be posted in the
alphalete owners iMessage Chat."*

## What it texts

One picture into **Alphalete Owners 🔥 - Real** (the chat owner_sales_hourly
already texts), from Lucy 1: Raf's Total Knocks board, same columns, but one
line per owner (most knocks first) and an **ORG TOTAL** line under them.

- :20 every hour, Mon–Sat, 2 PM–9 PM Central.
- Skipped when no owner's knocks moved since the last text.
- An office whose relay stopped (>25 min old) is left off, not drawn frozen.

## Source

Lucy ECO knocks relay: **Lucy Access App** workbook → **ICD Knocks** tab →
today's row per office (the office's own TeleMapper grid), the same rows each
office's own knocks board is drawn from. Pooled per owner (all their offices =
one line). Owner names come from `icd_alerts.offices`.

**Only our org:** owners on the **Alphalete ORG Sales Board**'s top
per-campaign boxes — the same filter as owner_sales_hourly. **Only owners on
Lucy ECO** (no relay row = not on the board).

## Run

```
# preview: draws the board, sends nothing
python -m automations.owner_knocks_hourly.run --force
python -m automations.owner_knocks_hourly.run --force --day 2026-10-28

# live (what the LaunchAgent runs)
python -m automations.owner_knocks_hourly.run --send
```

## Deploy (Lucy 1)

1. `lucy update`, then preview: `lucy rerun owner_knocks_hourly --machine "Lucy 1"`.
2. `lucy rerun install_owner_knocks_hourly_agent --machine "Lucy 1"`.

Tests: `python -m unittest automations.owner_knocks_hourly.test_build`
