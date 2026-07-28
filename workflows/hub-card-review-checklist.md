# Hub Card Review Checklist

The standard we run against **every** Hub card, one at a time. Each item is a
single yes/no. If the answer is "no," it's a flag — fix it or note why it's N/A.

Card schema lives in `AUTOMATED_REPORTS` in `automations/dashboard.py`. Field
names are called out so you know exactly what to look at.

---

## A. Right machine & profile

- [ ] **Assigned to the correct profile.** `assignees` = `["Lucy 1"]` (Raf / the
      always-on mini), `["Lucy 2"]` (Carlos), or a human queue like
      `["Office Operations"]`. Lucy 1 owns the ownerville/AppStream single-session
      logins; Lucy 2 owns Carlos's sessions + CDP Chrome. A report that needs a
      session must live on the machine that holds it.
- [ ] **`run_machine` matches the profile** when set. This is the routing key that
      forces a Hub "play" onto a specific mini (needed where a machine-bound Slack
      token or per-machine state matters). Blank = runs wherever the Hub runs.
- [ ] **No machine collision.** Two reports on the same machine don't fight over the
      same resource at the same time (e.g. `att_order_log` + `vantura_churn` both
      using CDP debug port 9246 on Lucy 2 → must be staggered).

## B. Runs at the correct time, in the correct section

- [ ] **In the right schedule section.** The day tile splits into
      ☀️ **Morning Batch** → ⏰ **Time Set** → 🏢 **Other Offices** → 📲 **Ops**.
      A fixed-clock report should sit in Time Set; a 4 AM circle-back report in
      Morning Batch; a 24/7 poller in Ops.
- [ ] **Time-Set cards show their run time on the pill.** If it's a fixed-time
      report, the actual time (e.g. "8:00 AM") is legible on the card at a glance —
      not buried. Pulled from `schedule.time`.
- [ ] **Morning-batch order makes sense.** Non-Tableau reports run first (data ready
      early); Tableau reports run last (max time to publish). Heaviest/flakiest
      scrape (`daily_rep_breakdown`) is pinned dead-last. Confirm nothing that reads
      Tableau is jumping ahead of the publish window.
- [ ] **Ops/24-7 pollers are flagged self-scheduled.** `self_scheduled: true` +
      `hide_schedule: true` so they show "Q N Min" / "24/7", not a fake 4 AM slot.

## C. Pill colors are functional

- [ ] **Pill reflects real run state**, computed by `_cal_status` from run history —
      green ✅ `ok` / amber 🟡 `progress` / orange 🟠 `partial` / red ⚠️ `fail` /
      grey `miss` / gold 🔄 `running`. Watch it flip after a run.
- [ ] **Multi-pass shown on the card.** If the report runs N times a day, it carries
      `daily_runs` (int) or a weekday-keyed dict, and the pill climbs
      grey → amber "(N/M done)" → green only on the **last** pass. Confirm the count
      is right (e.g. new-start-followup Sat=4 / Sun=1, leaders-call Mon=4).
- [ ] **Accent color (`color`) is intentional** — this is just the emoji-tile hue,
      not a status. Should fit the card's category, not clash.

## D. Failure alerting is wired (the whole point — catch fails NOW, not at EOD)

- [ ] **Completion is verified, not just exit-0.** In `schedule_config.json` the
      report's `verify` is a real `manifest` check that re-reads what it wrote —
      **NOT** `null` and **NOT** `type: "not_configured"` (both silently trust
      exit 0). A board that exits clean but writes nothing must still flag.
- [ ] **Real-time failure alert fires to Slack the moment it fails** — a threaded
      message in **#claudecorrections-and-requests** (`notify.send_failure_alert`):
      parent = report + error, reply = scoped re-run command + paste-to-Claude block.
- [ ] **No-show is detected.** If it never runs, the noon backstop marks it
      `MISSED_NOT_READY` and it rides the "didn't run today" alert — OR, for a
      standalone LaunchAgent poster, it has a `post_watch` entry with a deadline
      (a dropped launchd entry leaves no error row, so error-watch alone won't catch
      a silent no-fire).

## E. Card content reads right (the Library page)

- [ ] **Screenshot uploaded.** `resources/report-screenshots/<id>.png` exists and
      shows what the report actually produces.
- [ ] **"How it works" reads clean.** The `breakdown` field is correct, current,
      simple, jargon-free — WHAT IT DOES / WHEN IT RUNS / how to add or fix. A
      non-technical ICD should understand it.
- [ ] **Preflight makes sense.** The `checklist` (pre-flight clicks) is right for
      THIS report — no stale steps, nothing missing. Empty list = fully unattended
      (correct only if it truly needs no human prep).
- [ ] **"More actions" make sense.** The `actions` list — the primary Run action +
      every secondary (backfill, single-office, pick-a-week) — all point at real
      modules, have clear labels/help, and match how this report is actually re-run.
- [ ] **Layout / category correct.** Right `category`, right emoji, `description`
      one-liner accurate.
- [ ] **Linked doc deep-links to the exact tab.** `sheet_url` points at the specific
      worksheet the report fills, using the `?gid=<gid>#gid=<gid>` form — NOT the
      bare Sheet URL that dumps you on tab 1. Open it and confirm it lands on the
      right tab.

---

**Related:** [[report-validation-checklist]] (correctness before "done"),
[[hub-watch]] (change notifications), [[new-hub-card-intake-checklist]] (the gate
for cards just added).
