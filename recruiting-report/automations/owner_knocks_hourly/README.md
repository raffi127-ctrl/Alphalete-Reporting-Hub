# Owner Knocks Hourly

Raf, Slack 2026-10-29: *"Once an hour, can we get a report of the owners
knocking numbers please? We can do guys on LucyECHO only ... [his Total Knocks
board] but now it be the owners in the org. This can be posted in the
alphalete owners iMessage Chat."*

## What it texts

One picture into **Alphalete Owners 🔥 - Real** (the chat owner_sales_hourly
already texts), from Lucy 1: Raf's Total Knocks board, same columns, but one
line per owner (most knocks first) and an **ORG TOTAL** line under them.

- Teal **CHAN PARK** line on top, for comparison (Raf 2026-11-03): in no total.
- **D2D OWNERS**, then **B2B OWNERS** (B2B = an office whose campaign starts
  `b2b`), then **D2D TOTAL**, **B2B TOTAL**, **ORG TOTAL** at the bottom.
- Every knock time is on the office's own clock, so a time zone doesn't move
  an average (a 1:30 Eastern start = a 1:30 Central start).
- :20 every hour, Mon–Sat, 2 PM–10 PM Central (last one 10:20, Carlos 11/6).
- Same picture also into Carlos's **NEW A Players** and **ATT B2B Leaders** (Carlos 11/6).
- Skipped when no owner's knocks moved since the last text.
- An office whose relay stopped (>25 min old) is left off, not drawn frozen.

## Source

Lucy ECO knocks relay: **Lucy Access App** workbook → **ICD Knocks** tab →
today's row per office (the office's own TeleMapper grid), the same rows each
office's own knocks board is drawn from. Pooled per owner per group. Owner
names and campaigns come from `icd_alerts.offices`. Carlos's NDS crew comes from
the same workbook's **Lucy Knocks** tab (`share.py`). Chan is pulled live by this
job on Lucy 1 (OwnerVille → TeleMapper, Chan Park, campaign 3), only when the
board is about to go out; if the pull fails, the board goes without his line.

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
