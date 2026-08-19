# Recruiting Funnel Board — how it updates

> Quick version. The complete reference — every tab, the Lucy schedule,
> metric definitions, adding a manager — is in **`RUNBOOK.md`**.

Five tabs at the far right of the **Alphalete Org Applicant Tracker**
(`1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo`):

| Tab | What it is |
|---|---|
| **Manager Board** | All 17 managers side by side, one week at a time. Week picker in `I1`. |
| **Manager Trend** | One manager, every week. Manager picker in `B1`. Click the `+` above a week to open Mon–Sun. |
| **Manager Matrix** | Every manager × every week, for one metric. Metric picker in `B1`. |
| **Daily Log** | The raw data. One row per manager per day. |
| **Goals** | Per-manager targets. Hand-typed. |

---

## The one thing to understand

**Daily Log is the only tab the automation writes.**

Manager Board, Manager Trend and Manager Matrix are *views* — every cell is a
`SUMIFS` reading Daily Log. They recalculate themselves the instant Daily Log
changes. Nothing is pasted into them, so there is nothing to reapply and nothing
to break.

```
ApplicantStream  ->  Daily Log  ->  Manager Board
                         |------->  Manager Trend
                         \------->  Manager Matrix
                     Goals  ------>  the colours on all three
```

Manager Trend does **not** feed Manager Board. They are siblings, not a chain.

---

## The ad budget box (Manager Board, rows 21–37)

The one part of the Board that has nothing to do with ApplicantStream. It shows
each manager's **daily, weekly and monthly ad budget**, and it is fed by a
completely separate path:

```
each manager's Indeed sheet
   -> IMPORTRANGE -> their own tab in this workbook ('Carlos Hidalgo', ...)
                        -> the budget box on Manager Board
```

**Nobody has to tell the automation when a tracker is updated.** The box is pure
spreadsheet formula, not scraped data. Those manager tabs are `IMPORTRANGE`
mirrors, Google refreshes them by itself, and the box recalculates when they
change. There is no job to run and no schedule to miss — the 4am run only
re-draws the box, it does not compute the numbers.

How a row is worked out, for manager *M*:

1. `MAX` of `'M'!B:B` — the most recent **Report Date** on their tab.
2. `SUMIF` of `'M'!S:S` — **Daily Budget** for the rows carrying that date.
3. Weekly = daily × 7. Monthly = daily × days in the current month.

No status filter: LIVE, RESERVE and PAUSED ads all count if they sit on the
latest report date.

Two things to know before you trust the total:

- It reads the **manager tabs directly, never `Manager View`.** Manager View is
  `=INDIRECT` on its own `B1` picker, so it only ever shows whichever manager
  the dropdown was last left on. A box built from it would silently change
  meaning as people browsed.
- **ORG TOTAL is the Board's 14 managers only.** Justin Wood has a tracker tab
  and real budget on it but does not appear on the Board, so he is not in the
  total.

---

## What runs, and when

**Lucy 1** runs it. Two schedules, same command:

| When | What runs it | Why |
|---|---|---|
| 4am daily | the orchestrator batch (`funnel_board`) | the day's run + the Monday close-out of the prior week |
| :05 past the hour, **every hour** | launchd `com.alphalete.funnel-board-hourly` | keeps the Board and Trend from showing hours-old numbers |

Running it 16 extra times a day is safe because **every pass re-pulls and
overwrites the whole current week** rather than appending — see the restatement
rule below. A pass that fails or is skipped is simply corrected by the next one.

**Two runs must never write at once.** Overlapping runs clobbered a manager's
whole column once (2026-08-10). Two guards now: the wrapper skips if any
funnel_board run is alive, and `run.py` takes `state/run.lock` (broken
automatically if older than 90 minutes, so a crash can't wedge the report).

It runs round the clock (Carlos, 2026-08-11). Overnight passes mostly rewrite the
week with identical numbers, since nobody books interviews at 3am, but they cost
only browser time on Lucy 1. The 4:05 pass and the 4am orchestrator pass overlap
by design — whichever starts second sees the first and skips. To narrow the
window, delete `Hour` dicts from
`deploy/com.alphalete.funnel-board-hourly.plist` and re-run the installer.

Each run:

1. Reads the existing Daily Log back out of the sheet.
2. Logs into ApplicantStream and opens **Report → Retention - Details (new)**
   for each of the 17 offices.
3. Pulls the days it needs, merges them over the existing history.
4. Writes Daily Log and rebuilds the three view tabs.

Takes roughly 8–10 minutes for all 17 offices.

### Which days it refreshes

**Never "yesterday only."** Managers backfill late — Monday's numbers routinely
change on Tuesday or Wednesday — so every run re-pulls the **whole current
Mon–Sun week** and overwrites it.

On **Mondays** it also re-pulls the **previous week** one final time, then leaves
it alone forever. At most two weeks are ever in play.

### Two things about the source report that trip people up

- **The report's week runs Sunday–Saturday for some offices and Monday–Sunday
  for others.** It is a per-office setting. The job reads whichever dates came
  back and pulls a second week if it needs to, rather than assuming.
- **Email is not the only intake path.** Applicants also arrive via Manual Apps
  Entry, Resume Scooper and File Import, each with its own "sent to call list"
  line. Sent to Call List counts all four. Counting email alone understated some
  managers by a third and made bookings exceed sends.

---

## Driving it by hand

Queue these on the **Mini Control** tab (Lucy 1) of the mini-control sheet
(`1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`) — append a row with Status
`queued` and the poller picks it up within ~2 minutes.

| Action | Args | What it does |
|---|---|---|
| `rerun` | `funnel_board` | Run it now, live. |
| `rerun` | `funnel_board --dry-run` | Pull and report, write nothing. |
| `rerun` | `funnel_board --weeks 4` | Backfill the last 4 weeks. |
| `update` | | Pull the latest code onto Lucy 1 first. |
| `rerun` | `install_funnel_board_hourly_agent` | (Re)install the hourly launchd agent. |
| `logtail` | `<log name> <grep> <n>` | Read a run's log. |

---

## Goals

The **Goals** tab is the control panel. You type **nine numbers** per manager and
everything else computes:

**You type:** Removal % · Sent to Call List · Retention to Call List ·
1st Show % · 2nd Booked % · 2nd Show % · Offer % · BOB Conversion ·
New Start Show %

**Computed from those:**

```
Applies      = Sent / (1 - Removal %)
Removed      = Applies - Sent
1st Booked   = Sent       x Retention to Call List
1st Showed   = 1st Booked x 1st Show %
2nd Booked   = 1st Showed x 2nd Booked %
2nd Showed   = 2nd Booked x 2nd Show %
Job Offered  = 2nd Showed x Offer %
BOB          = Job Offered x BOB Conversion
NS Scheduled = BOB                       (measured 99% across the year)
NS Showed    = NS Scheduled x New Start Show %
```

Amber cells are yours to edit. Grey cells are formulas — don't type over them.
Column A (Office ID) is hidden plumbing.

**Your typed goals survive a rebuild.** The job reads them back before writing and
restores them, and also mirrors them to `state/goals_backup.json` in case a run
dies midway.

---

## Colours

One rule everywhere: **how far off goal are you.**

| Band | Colour |
|---|---|
| Within 5% of goal | green |
| 5–10% off goal | yellow |
| More than 10% off | red |

Judged on falling *short*. Beating a goal stays green. Removal % inverts — being
under the removal goal is good.

Only the nine metrics you set goals for are coloured: Removal %, Sent to CL,
Ret to CL %, 1st Shw %, 2nd Booked %, 2nd Shw %, Offer %, BOB Conv %, NS Shw %.
Derived counts stay black.

**Mid-week, counts are judged on run rate.** A count is compared against
`goal x the share of a week normally done by that weekday`, measured per metric
from completed weeks — so 30 bookings by Wednesday against a goal of 50 reads as
on-track, not 60%. New Starts are ~79% done by Monday; applies only ~29%. Rates
are compared to goal directly, since a rate doesn't accumulate.

---

## Known issue — five offices on Lucy 2

Lucy 2's ApplicantStream login is **not assigned** these five offices, so they
fail every run and keep their previous numbers:

| Manager | Office |
|---|---|
| Isaiah Revelle | 19717 |
| Jacob Dover | 23607 |
| Kash Rai | 22177 |
| Rashad Reed | 23411 |
| Salik Mallick | 21328 |

Navigating to them returns **"This Office is not assigned to you!"**. The other
nine work. The Mac mini pulls all 14 because it logs in as `rcaptain`, which has
them.

**Fix:** in ApplicantStream, assign those five offices to whichever user Lucy 2
logs in as (or point Lucy 2's `ownerville-creds.json` at `rcaptain`). No code
change will help — it's an account permission.

Until then the run exits 1 and says which offices were skipped. Their numbers
stay at the last successful pull rather than blanking.

## When something looks wrong

- **A manager's numbers didn't move.** That office failed its pull and kept its
  previous values. The log says which. Re-run.
- **The current week looks low.** It's partial. Every tab carries a banner
  saying which days it covers.
- **A number disagrees with your Focus Report.** Retention to Call List is
  AppStream's own cohort stat (of the people sent to the call list this week,
  what share got booked). The Focus Report divides this week's bookings by this
  week's sends. Different populations; they diverge when a manager's sends and
  bookings are out of phase.
- **Column P onwards on Daily Log is hidden.** That's the intake breakdown
  (Email / Manual / Scooper / File, and both removal paths). Unhide to see which
  path produced a total.
