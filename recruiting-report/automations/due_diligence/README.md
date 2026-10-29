# Jiraiya — Due Diligence numbers on demand

Raf **DMs the Jiraiya bot** an ICD + a rep → it pulls that rep's due-diligence
numbers from Tableau, replies in the DM, and logs the block to that ICD's tab in
the [DD log sheet](https://docs.google.com/spreadsheets/d/1RB07z5xmXBzFgKPRmbvqsvbFJ4yymrsk2z0tkMeCbpQ/edit)
(the manual flow Eve walks through in her Loom). Named Jiraiya — the Sannin who
ran a spy network; "due diligence" is his whole thing.

There's no inbound Slack listener in the repo, so the bot **polls** each allowed
user's DM (`conversations_history`, the standard pattern) — near-instant at a
60s tick, no new listener infra.

**Request format** (ICD then rep):
```
Alex Touati / Adalberto Celaya
ICD: Alex Touati   Rep: Adalberto Celaya
```
The ICD picks the tab (one tab per ICD, **auto-created on first request**) and
disambiguates the rep. A lone name gets a "give me both" nudge.

## What it pulls (per rep)

Mirrors Eve's [template](https://docs.google.com/spreadsheets/d/1YgiiodwnIq-5NwKSlEBiQGEd_juO-ixDcUOIP4r_mYs/edit#gid=1928298299)
— **two tables**, New Internet + Wireless:

| Field | Source (reused, not rebuilt) |
|---|---|
| New INT / Wireless weekly (8 wks) | Product Sales `DailyRepBDreportpull` (`opt_phase.parse_personal_production`), 1 pull/week |
| 8-wk avg / 4-wk avg | computed (mean of the 8 / newest 4, blanks skipped like the Sheet's AVERAGE) |
| 0-30 & 30-60 Day Cancel Rate | Metrics workbook rep row (30-60 = 100 − activation) |
| 0-30 / 30 / 60 / 90 Day Churn | all-team churn views, sliced to the rep (`new_internet_churn.parse`) |
| Start date / first day of sales | earliest logged sale, from the org-wide `ORDERLOG`/`ALLREPS` `A.Order Log` (`first_sale.py`) |

All ~12 crosstab pulls run over **one** `tableau_session` login per request.

## Run it

```bash
# Preview one rep (live Tableau pull; prints reply + the ICD-tab block, writes nothing)
.venv/bin/python -m automations.due_diligence.run --rep "Adalberto Celaya" --icd "Alex Touati"

# Poll the bot's DMs once — PREVIEW (prints replies, no DM, no Sheet write)
DD_DM_USERS="Rafael Hidalgo" .venv/bin/python -m automations.due_diligence.run --once

# Go live: DM replies AND log to each rep's ICD tab
DD_DM_USERS="…" DD_BOT_TOKEN="xoxb-…" .venv/bin/python -m automations.due_diligence.run --once --live --write
```

## Safety defaults (deliberate)

- **No Slack post** unless `--live`. Without it, replies print to stdout.
- **No Sheet write** unless `--write`. Without it, the block is preview-only.
- **Append-only** into the ICD tab, 2 rows below existing content — never
  overwrites a filled cell (each block carries its own header + WE dates).
- **Auto-creates** the ICD tab on first request (only ever ADDs a tab — never
  edits or deletes an existing one).
- `DD_DM_USERS` is empty until set, so the bot answers no one by default —
  DD performance data only reaches named leaders. [[feedback_verify_slack_recipient]]
- Idempotent: newest handled message ts is saved to
  `output/due_diligence/watch_state.json` and each request gets a ✅, so a
  re-run never double-answers.

## Config (all env-overridable — see `config.py`)

| Env | Default | Why |
|---|---|---|
| `DD_SHEET_ID` | prod DD workbook | point at a **sandbox** copy while building |
| `DD_CHANNEL_ID` | *(blank)* | the request channel — **must set before live** |
| `DD_WEEKS` | 8 | weekly columns |
| `DD_PRODUCT_VIEW_URL` / `DD_METRICS_*` / `DD_CHURN_*` | maintained views | override a source for testing |

Source URLs default to the constants the other reports maintain
(`opt_phase`, `office_metrics.offices`) so they never drift.

## Deploy (the poller) — NOT enabled yet

Runs as a launchd job on the mini every ~60s (near-instant; there's no inbound
Slack listener infra in the repo, so this polls — the same pattern every other
"read Slack" report uses). Plist template lives in `deploy/`; it stays off until
go-live is confirmed (it posts to a team channel — [[feedback_ask_before_slack]]).

## Verified (2026-07-28, live)

- All 5 Tableau sources pull + parse over one login (product, NI/WL metrics,
  NI/WL churn). Confirmed on a real rep (Adalberto Celaya, ICD Alex Touati):
  cancel 0-30 **12.5%** / 30-60 **27.3%**, NI churn 0/0/0/**14.29%**.
- **Cancel is rep-level** — the Metrics crosstab has a `Rep Name` column, so
  the 0-30 cancel + 30-60 (=100−activation) come straight off the rep's row.
- New INT count = `NEW INTERNET` only (excludes `UPGRADE INTERNET`).

## First day of sales (`first_sale.py`)

Raf's spec (2026-07-30): **any** logged sale counts (cancelled/inactive
included) and rep names are consistent — so a rep's first sale date is
`min(Order Date)` over every row they appear on, with **no** product-type and
**no** status filter.

> ⚠️ **History is NOT forever.** Probed 2026-07-30: asking ALLREPS for June 2025
> returned only 06-25 onward, and June 2024 / June 2023 returned nothing — a
> rolling **~400-day** window (today − 400 = 2025-06-25, exactly the boundary
> seen). So a rep whose earliest visible sale sits at that floor may have
> started well before it. Those reps render **"6/25/2025 or earlier"**, never a
> fabricated exact day. The floor is measured from what the view actually
> served, because the window rolls forward daily. Reps who started *inside* the
> window get a real, exact date. **An exact day for a pre-window rep needs a
> longer-history source** — open item.

Source is the org-wide `ORDERLOG` / `ALLREPS` `A.Order Log` crosstab (per-order
rows). The DD product view can't do this — it has no date field, only weekday
*columns* inside a week-filtered pull, so reaching back years would need one
pull per week.

Two phases, because a first-sale date never changes once known:

```bash
# how far back the history actually reaches (walks back, stops after 2 empty years)
.venv/bin/python -m automations.due_diligence.run --first-sale-probe

# one-time backfill — monthly chunks, resumable, preview by default
.venv/bin/python -m automations.due_diligence.run --first-sale-backfill --verbose
.venv/bin/python -m automations.due_diligence.run --first-sale-backfill --write
```

Then the 3am harvest calls `update_recent()` over the same warm session: a
rolling 30-day window that adds **only** reps missing from the map. Add-only, so
it can never move a date the backfill established.

The map lives on the **`_first_sale` tab** of the DD workbook (rep → ISO date),
not a local JSON, so it works from any machine. That tab is derived data the
report owns end-to-end — it's the one DD tab that is rewritten rather than
appended to; every ICD tab stays append-only.

A monthly chunk that trips `CHUNK_ROW_ALARM` (150k rows, vs ~47k measured for a
normal month) is re-pulled as weekly sub-chunks rather than trusted — a
truncated export must never pass silently.

## Open items

1. **B2B** — first-sale is RESIDENTIAL only (Megan 2026-07-30). Carlos's B2B
   order log is a separate universe; a rep's first B2B sale is not counted.
2. **Structure** — Eve asked Raf whether he wants the rolling 8-week snapshot
   (current) or continuous weeks. Default stays 8-week until he answers.
3. **New-rep averages** — an absent sales week counts as 0 in the 8-wk/4-wk
   average (true "new INTs per week"); a brand-new rep's pre-start zeros drag it
   down. The Start-Date column is the context; revisit if Raf wants avg-from-start.
4. **ICD tabs** — Megan creates one tab per ICD in the log sheet; the bot matches
   tab titles to the requested ICD (exact-normalized, then contains).
