# Recruiting Funnel Board — full runbook

Everything about the Funnel Board: where the numbers come from, what Lucy runs,
what every tab does, and how to change it. Written 2026-08-18.

The quick version lives in `README.md`. The archaeology — what we got wrong and
how we found out — lives in `BUILD_NOTES.md`. This file is the complete picture.

**The workbook:** Alphalete Org Applicant Tracker
`1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo`

**Current state:** 17 managers · refreshes every hour at :05 · runs on Lucy 1

---

## 1. The one thing to understand

**Daily Log is the only tab the automation writes.**

Manager Board, Manager Trend and Manager Matrix are *views* — every cell is a
`SUMIFS` reading Daily Log. They recalculate the instant Daily Log changes.
Nothing is pasted into them, so there is nothing to reapply and nothing to break.

```
ApplicantStream  ->  Daily Log  ->  Manager Board
                         |------->  Manager Trend
                         \------->  Manager Matrix
                     Goals  ------>  the colours on all three

each manager's Indeed sheet  ->  their hidden tab  ->  Manager View
                                                   \->  the ad budget box
```

Manager Trend does **not** feed Manager Board. They are siblings, not a chain.

Two completely separate pipelines share this workbook:

| Pipeline | Source | Feeds | Who updates it |
|---|---|---|---|
| **Funnel** | ApplicantStream | Daily Log → Board / Trend / Matrix | Lucy 1, hourly |
| **Ads** | each manager's Indeed sheet | hidden manager tabs → Manager View + budget box | Google, via `IMPORTRANGE` |

Nobody has to tell the automation when an Indeed tracker is updated. Those tabs
are live mirrors; Google refreshes them itself.

---

## 2. Where the funnel numbers come from

**ApplicantStream → Report → Retention - Details (new)** — page `p=783`. Not the
older "Retention - Details". Verified against the live Focus Report.

### Metric mapping (calibrated against the Focus Report, not guessed)

| Board metric | ApplicantStream row |
|---|---|
| Applies | `Emails Received` + `Resume Scooper` + `File Import` + `Manual Apps Entry` |
| Sent to Call List | `Email Apps Sent to Call List` + the scooper / file / manual equivalents |
| Removed | `Removed From Process Emails` + `Removed From Resume Scooper` |
| 1st Booked | `Total First Interviews` — **not** `First Interviews Booked` |
| 1st Showed | `First Interviews Showed Up` |
| 2nd Booked | `Total Second Interviews` |
| 2nd Showed | `Second Interviews Showed Up` |
| Job Offered | `Offered Job From Second Round` — **not** `Position Offered from Second Calendar` |
| BOB | `Brought on Board Booked` |
| NS Scheduled / Showed | `Total New Starts Scheduled` / `New Starts Showed Up` |

### Four things that trip people up

1. **Applies means intake, not what was vetted.** All four arrival channels
   count. Counting email alone understated some managers by a third and made
   bookings exceed sends — Rashad's retention read 110.8% before the fix, 49.8%
   after. The scooper matters most: 31% of Salik's intake, 46% of Rashad's.
2. **"1st Booked" is not bookings taken that week.** `Total First Interviews`
   filters on *First Interview Date* — interviews **scheduled to occur** that
   week. The label has always been misleading. Same for second rounds, which is
   why future days inside the current week carry real numbers.
3. **Retention to Call List is a cohort stat.** It answers "of the people saved
   to the call list this period, what share got a first interview booked",
   filtered on when the save happened. It does **not** equal bookings ÷ sends
   for the same period, and the two diverge by up to 14 points when a manager's
   sends and bookings are out of phase.
4. **The report's week runs Sunday–Saturday for some offices and Monday–Sunday
   for others.** It is a per-office setting. The job reads whichever dates came
   back rather than assuming, and pulls a second week if it needs to.

### Weekends are not idle
An early assumption that Sat/Sun were ~0 was wrong. Measured across four
complete weeks: weekends are 4.7% of all activity, and Sunday alone is 5.6% of
applies.

---

## 3. What Lucy runs, and when

**Machine: Lucy 1.** She holds the ApplicantStream login that reaches all 17
offices. (Lucy 2's login is missing five of them and returns *"This Office is
not assigned to you!"* — that is an account permission, not a code problem, and
is why the job lives on Lucy 1.)

| When | What runs it | Purpose |
|---|---|---|
| 4:00am | the orchestrator batch, report id `funnel_board` | the daily run + Monday's close-out of the prior week |
| **:05 past every hour, 24/7** | launchd `com.alphalete.funnel-board-hourly` | keeps the Board and Trend current |

A full 17-office pass takes **8–10 minutes on the mini, ~4.5 minutes on Lucy 1**.

### Each run
1. Reads the existing Daily Log back out of the sheet.
2. Logs into ApplicantStream and opens Retention - Details (new) for each office.
3. Pulls the days it needs and merges them over the existing history.
4. Writes Daily Log, then rebuilds the three view tabs.

### The restatement rule — why hourly is safe
**It never pulls "yesterday only."** Managers backfill late, so every run
re-pulls the **whole current Mon–Sun week** and overwrites it. On **Mondays** it
also re-pulls the **previous week** one final time, then leaves it alone forever.
At most two weeks are ever in play.

Because every pass is a full restatement rather than an append, running it 24
times a day is safe: a failed or skipped pass is simply corrected by the next one.

### The run lock
Two runs must never write at once. This is not hypothetical — a run launched 14
seconds before an earlier one finished clobbered Jacob Dover's entire column on
2026-08-10. Two guards now:

- the wrapper skips instantly if **any** funnel_board run is alive (`pgrep`),
  including the orchestrator's, since it runs the same module path;
- `run.py` takes `state/run.lock` (an atomic `mkdir`, not `fcntl`, so it works on
  Windows too). A lock older than **90 minutes** is assumed to be a crashed run
  and broken, so one hard kill can't wedge the report.

`--dry-run` neither takes nor waits on the lock.

The 4:05 hourly pass and the 4:00 orchestrator pass overlap by design — whichever
starts second sees the first and exits.

**Limitation:** the lock is a local file, so it serializes runs *on a machine*,
not across machines. Everything scheduled lives on Lucy 1, so this never arises
in normal operation — but don't run it manually from the mini while an hourly
pass is going. Queue manual runs through Lucy 1 instead.

### History lives in the sheet, not in git
The run reads Daily Log back and merges. A daily-changing data file in the repo
would eventually collide with Lucy's `git pull --ff-only`.

### The drift guard
After a successful write the run stamps Daily Log with who wrote it, from where,
when, and a fingerprint of the rows. The next run re-fingerprints. Same
fingerprint means the sheet is exactly as the report left it; different means
something edited it in between, and the run says so and pings Slack
(`#claudecorrections-and-requests`).

A drift report is **not** a failure — late backfills by a person are legitimate
and the restatement rule overwrites the week anyway. It only removes the silence.
The stamp lives in row 1 past the data columns (`AB1:AC1`) and is found by its
label, never by column index.

---

## 4. Every tab, explained

### Tabs the automation owns

| Tab | What it is |
|---|---|
| **Manager Board** | All 17 managers side by side, one week at a time |
| **Manager Trend** | One manager, every week, with expandable Mon–Sun dailies |
| **Manager Matrix** | Every manager × every week, for one metric |
| **Daily Log** | The raw data — one row per manager per day |
| **Goals** | Per-manager targets. Hand-typed |

### Manager View + 0Config
Not automation-owned, but wired up in this session.

### Hidden per-manager tabs
`Atef Choudhury`, `Rafael Hidalgo`, … — one per manager, each an `IMPORTRANGE`
of that manager's own Indeed sheet (`*Indeed Tracking!A2:Z`). All hidden.

---

### Manager Board

Everything for one week, all managers.

- **`I1` — week picker.** Pick any week ending date.
- **`L1` — week day reached.** `=IF($I$1>=TODAY(),WEEKDAY(TODAY(),2),7)`. Drives
  the mid-week pace grading.
- **Row 3** — headers. **Rows 4–20** — one row per manager, sorted by New Starts
  Showed then Applies. **Row 21** — OFFICE TOTAL.
- **Filters cover the manager rows only** (not the total row), so sorting by a
  column doesn't drag the total into the middle.

Columns, left to right:

```
MANAGER · Applies · Removed · Removal % · Sent to CL · Ret to CL % ·
1st Bkd · 1st Shw · 1st Shw % · 2nd Booked % · 2nd Bkd · 2nd Shw ·
2nd Shw % · Offer % · Offered · BOB · BOB Conv % · NS Sched ·
NS Showed · NS Shw %
```

#### The ad budget box (rows 24–43)
The one part of the Board with nothing to do with ApplicantStream. For each
manager it shows **daily, weekly and monthly ad budget**:

1. `MAX` of that manager's tab column B — the most recent **Report Date**.
2. `SUMIF` of column S — **Daily Budget** for the rows carrying that date.
3. Weekly = daily × 7. Monthly = daily × days in the current month.

No status filter: LIVE, RESERVE and PAUSED all count if they sit on the latest
report date. The 4am run only re-*draws* this box; it does not compute the
numbers. There is no job to run and no schedule to miss.

Two things before you trust the total:
- It reads the **manager tabs directly, never Manager View.** Manager View is
  `=INDIRECT` on its own picker, so it only ever shows whoever the dropdown was
  last left on. A box built from it would silently change meaning as people browse.
- **ORG TOTAL is the Board's managers only.** Justin Wood, Noah Dubale, Jamis
  Garay and Jackie LeRoy have tracker tabs but are not on the Board, so they are
  not in the total.

#### Color key (rows 46+)
Legend for the grading bands.

---

### Manager Trend

One manager, every week, newest first.

- **`B1` — manager picker.**
- **Column B — GOAL**, pulled from the Goals tab.
- Each week is a column. **Click the `+` above a week** to expand Mon–Sun dailies.
- Rows are grouped by funnel stage: SOURCING → FIRST ROUND → SECOND ROUND →
  OFFER → NEW STARTS, with the rate under each pair of counts.

---

### Manager Matrix

Every manager × every week, for **one** metric.

- **`B1` — metric picker.**
- Weeks run newest-first across the top; managers down the side.
- Best tab for "who is trending down over two months".

---

### Daily Log

The raw data. One row per manager per day. **This is the only tab written.**

| Col | Field | |
|---|---|---|
| A | Date | |
| B | Week Ending | |
| C | Manager | |
| D | Office | |
| E | Applies | intake — all four channels |
| F | Sent to Call List | |
| G | Removed | |
| H | Processed | Sent + Removed |
| I | Ret Booked | retention numerator |
| J–K | 1st Booked / 1st Showed | |
| L–M | 2nd Booked / 2nd Showed | |
| N | Job Offered | |
| O | BOB | |
| P–Q | NS Scheduled / NS Showed | |

**Columns R–Z are hidden** — the intake and removal breakdown. Unhide to see
which channel produced a total:

```
R  · Emails Received      V  · Email Sent        Y  · Removed (Email)
S  · Scooper In           W  · Scooper Sent      Z  · Removed (Scooper)
T  · File Import In       X  · File Sent
U  · Manual Entry
```

`AB1:AC1` holds the drift-guard stamp.

---

### Goals

The control panel. **You type nine numbers per manager; everything else computes.**

**You type** (amber cells): Removal % · Sent to Call List · Retention to Call
List · 1st Show % · 2nd Booked % · 2nd Show % · Offer % · BOB Conversion ·
New Start Show %

**Computed** (grey — don't type over):

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

Why derive the counts: there are 21 columns but only ~9 real degrees of freedom.
Typing both a rate and the count it implies lets them contradict each other;
deriving makes the funnel self-consistent by construction.

Column A (Office ID) is hidden plumbing.

**Your typed goals survive a rebuild.** The job reads them back before writing
and restores them, and mirrors them to `state/goals_backup.json` in case a run
dies midway.

---

### Manager View + 0Config

**Manager View** shows one manager's Indeed ads.

- **`B1` — manager dropdown**, validated against `'0Config'!A1:A18`.
- **`A4`** is `=INDIRECT("'"&$B$1&"'!A2:Z")` — it pulls whichever hidden manager
  tab the dropdown names.

**`0Config` column A is the dropdown list** — 18 names, alphabetical. Column C
holds unrelated values; only column A feeds the dropdown.

**To add someone** you must do all three, in order:
1. Their tab must exist and be named **exactly** as it will appear in the list.
2. Add the name to `0Config` column A.
3. Widen the validation range to match the new row count.

`INDIRECT` does an exact string match, so **a trailing space in a tab name breaks
it** while looking perfectly fine in the tab bar. That bit us with
`"Aya Al-Khafaji "` — the fix was renaming the tab, not quoting the space.

---

## 5. The 17 offices

Name → office id → **what AppStream's switcher actually calls the owner** (often
not what you'd expect).

| Manager | Office | Listed in AppStream as |
|---|---|---|
| Atef Choudhury | 23467 | |
| Aya Al-Khafaji | 22992 | |
| Carlos Hidalgo | 11580 | CARLOS HIDALGO |
| Cody Cannon | 21151 | |
| Cyrus Wade | 22815 | |
| Drew Tepper | 22583 | |
| Haytham Nagi | 22524 | |
| Isaiah Revelle | 19717 | |
| Jacob Dover | 23607 | |
| Kash Rai | 22177 | **Akashdeep Rai** |
| Khalil Mansour | 11901 | KHALIL MANSOUR |
| Maxamad-Amin Aden | 23066 | **Maxamad Aden** (not 22480 Aden Berhane) |
| Rafael Hidalgo | 11280 | |
| Rashad Reed | 23411 | |
| Roshan Amin | 19833 | **Roshan Amin Ahmad** |
| Ryan McSpadden | 22820 | |
| Salik Mallick | 21328 | **Muhammad UI Haque** |

---

## 6. Colours and grading

One rule everywhere: **how far short of goal are you.**

| Band | Colour |
|---|---|
| Within 5% of goal | green |
| 5–10% off goal | yellow |
| More than 10% off | red |

Judged on falling *short* — beating a goal stays green. Removal % inverts (being
under the removal goal is good).

**Only the nine metrics you set goals for are coloured:** Removal %, Sent to CL,
Ret to CL %, 1st Shw %, 2nd Booked %, 2nd Shw %, Offer %, BOB Conv %, NS Shw %.
Derived counts stay black — colouring an output as well as the input behind it
says the same thing twice.

**Mid-week, counts are judged on run rate.** A count is compared against
`goal × the share of a week normally done by that weekday`, measured per metric
from completed weeks — so 30 bookings by Wednesday against a goal of 50 reads as
on-track, not 60%. Rates are compared to goal directly, since a rate doesn't
accumulate.

Pace differs sharply per metric: New Starts are ~79% done by Monday (training
starts Monday); applies only ~29%. A single "days elapsed" divisor misjudges both.

Two visual languages, deliberately: a **filled cell** means a rate vs its goal; a
**coloured number** means a count vs pace. Filling both turns the board into one wash.

---

## 7. Adding a manager

**Funnel side** (~2 min + backfill):
1. Find the office id.
2. Add one line to `OFFICES` in `automations/funnel_board/run.py`:
   `("New Name", "23999", "Owner As AppStream Lists Them"),`
3. Push; Lucy picks it up on her next `update`.
4. Backfill: `--only "New Name" --weeks 32` (5–35 min depending on office size).

Everything else is automatic — Board rows, the Trend picker, Matrix rows and a
Goals row seeded with the office median all derive from whoever is in the data.
**Type real goals afterwards**, or the colours grade against the median.

**The one real blocker:** the office must be assigned to the ApplicantStream
login. If it returns *"This Office is not assigned to you!"*, no code change helps.

**Ads side:** they need a tracker tab (an `IMPORTRANGE` of their Indeed sheet),
then add them to `0Config` and widen the validation range. See §4.

---

## 8. Driving it by hand

Queue on the **Mini Control** tab (Lucy 1) of the mini-control sheet
`1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw` — append a row with Status
`queued`; the poller picks it up within ~2 minutes and works the queue in order.

| Action | Args | What it does |
|---|---|---|
| `rerun` | `funnel_board` | Run it now, live |
| `rerun` | `funnel_board --dry-run` | Pull and report, write nothing |
| `rerun` | `funnel_board --weeks 4` | Backfill the last 4 weeks |
| `rerun` | `install_funnel_board_hourly_agent` | (Re)install the hourly agent |
| `update` | | Pull the latest code onto Lucy 1 first |
| `logtail` | `<log name> <grep> <n>` | Read a run's log |

Log names: `orch-<date>-funnel_board.log` (4am), `funnel-board-hourly-<timestamp>.log`
(hourly), `rerun-<timestamp>-funnel_board.log` (manual).

**Changing the schedule:** edit the `Hour` dicts in
`deploy/com.alphalete.funnel-board-hourly.plist`, push, `update`, then
`rerun install_funnel_board_hourly_agent`. It's currently all 24 hours at :05.

---

## 9. Operational gotchas

- **Run headed.** `headless=True` trips a Cloudflare re-challenge on the rcaptain
  login. The hourly wrapper deliberately does **not** set `HEADLESS=1`.
- **Every AppStream URL needs `&rqst=<TOKEN>`.** A bare `index.cfm?p=104` returns
  "Valid User ID Not Obtained!" and poisons every office after it in a loop.
- **The visible Week datepicker is decorative.** The server echoes `weekStart`
  back and ignores it; the hidden `startDate2` field selects the period. Posting
  only `weekStart` silently returns the *current* week — which looks exactly like
  success if your test date is in the current week.
- **`form.submit()` is shadowed** by an `<input name="submit">`, so
  `HTMLFormElement.prototype.submit.call(f)` is required.
- **Switch office by URL** (`&newOfficeId=`), not by driving the autocomplete —
  on Lucy only the first keystroke registered, so typing "21328" filtered on "1".
  Verify by reading `Office ID: (\d+)` off the page.
- **Rafael (11280) and Khalil (11901) render slowest.** The wait is 240s.
- **Never rebuild the views by calling `build.py` directly** unless you mean to.
  It wipes the tab and rewrites it, which removes the drift-guard stamp — only
  `run.py` re-stamps.

---

## 10. When something looks wrong

- **A manager's numbers didn't move.** That office failed its pull and kept its
  previous values. The log says which. Re-run.
- **The current week looks low.** It's partial. Every tab carries a banner saying
  which days it covers.
- **A number disagrees with your Focus Report.** Almost always Retention to Call
  List — see §2, it's a cohort stat, not a period ratio.
- **A bookings/sends ratio over 100%.** The tell that an intake channel is being
  missed.
- **Manager View shows nothing / `#REF`.** The dropdown name doesn't exactly match
  a tab name. Check for a trailing space.
- **Column R onwards on Daily Log is hidden.** That's the intake breakdown.

---

## 11. What changed in this session (2026-08-11 → 08-18)

- **Three managers added** — Aya Al-Khafaji (22992), Ryan McSpadden (22820), Drew
  Tepper (22583) — each backfilled to January. Board went 14 → 17.
- **NS Shw % is now graded.** It had always been one of the nine typed goals but
  was missing from every grading map, so you were setting a target nothing
  measured against. Added to Board, Trend and Matrix. Graded columns 8 → 9.
- **Hourly refresh.** New launchd agent on Lucy 1, 24 slots at :05, replacing
  once-a-day-only. The 4am orchestrator pass still owns the daily run and the
  Monday close-out.
- **The run lock**, added as a precondition of hourly (§3).
- **Manager View dropdown** — Aya, Ryan and Drew added; Aya's trailing-space tab
  name fixed; all three tabs hidden to match the others. List is now 18 names.
- **The job runs on Lucy 1**, which resolved the five-office access failures.
  Verified: all 17 offices pull clean.

### Still open
- **Aya, Ryan and Drew have placeholder goals** seeded from the office median.
  Colours grade against those until real targets are typed.
- **Drew's ads are Florida-based** (Alafaya, Sanford, Winter Park) where every
  other manager is Texas, and his **Report Date column is blank**, so he won't
  show budget in the Manager Board box.
- **Noah Dubale, Jamis Garay and Jackie LeRoy** have tracker tabs but are not on
  the Funnel Board and are not in the ORG TOTAL.
