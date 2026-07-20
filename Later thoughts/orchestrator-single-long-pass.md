# The single-long-pass problem (day orchestrator)

**Status:** proposal — no code changed. Needs Megan's sign-off before touching
`automations/day_orchestrator/run.py`.
**Found:** 2026-07-20, diagnosing why the Tableau Country Trackers were short in
one channel and why Box posted late.

---

## The one-sentence version

Everything the orchestrator does "each pass" or "at end of pass" — re-probing
readiness, retrying a flaked report, retrying an incomplete report's failed
parts — silently degrades to **once per day** on a day when the pass runs long.
Today the pass ran 3h47m, so all three mechanisms effectively never fired.

---

## Evidence: two symptoms, one cause

Both of today's tracker problems trace to the same place.

### Symptom 1 — #aeon-sales was missing 5 of 7 images for 3h18m

- 04:28:37 — a TCP socket timeout (`URLError: [Errno 60] Operation timed out`)
  killed the 3rd image upload to #aeon-sales, the last org in the fanout. The
  other 8 channels were already complete.
- 04:29:05 — the orchestrator logged it correctly:
  `tableau_screenshots: run failed (attempt 1/3) — will retry: exit 1`
  and set the report `STILL_TRYING`.
- The recovery is `_retry_flaked`, called at the **end** of `_run_pass`
  (`automations/day_orchestrator/run.py:514`). Its docstring promises recovery
  "in ~90s" (`FLAKE_RETRY_BACKOFF_S = 90`).
- The pass didn't end until ~07:47. So the "~90s" retry was actually queued
  **3h18m out**.

The thread sat visibly broken in front of five orgs the whole time. It was fixed
by a hand-run `lucy rerun tableau_screenshots` at 06:57 — i.e. a human beat the
automation by 50 minutes.

### Symptom 2 — Box posted on the 08:00 floor, not when its data landed

- 04:31:25 — probed, genuinely not ready:
  `tableau_screenshots_box: still trying — tableau:box_daily: Box only through
  2026-07-18, need 2026-07-19 — extract not refreshed`. Correct at that moment.
- ~07:42 — the extract **was** in. Independently confirmed by a `sunday_coverage`
  run: `box=Y(max 2026-07-19)`.
- 08:01:41–08:02:21 — Box finally posted to all 9 channels.

It did not post because the probe noticed. It posted because the **08:00
fail-open floor** released it (`fallback_hhmm: "08:00"`,
`automations/day_orchestrator/readiness.py:198`).

I checked whether a stale cached verdict was to blame — it isn't.
`ReadinessCache` caches **only READY** verdicts (monotonic); not-ready is
deliberately re-probed. But the docstring says *"NOT-ready is re-probed each
pass"* (`readiness.py:62`) — and there was only one pass. So Box was probed
exactly once, at 04:31, and never again. The safety net became the mechanism.

---

## Why it happens

The intended cadence is **12 minutes** (`schedule_config.json` →
`settings.interval_minutes: 12`, start 04:00, checkpoint 07:30, backstop 12:00).

But 12 minutes is the **sleep between passes**, not the pass period. The real
period is:

```
pass period  =  interval (12m)  +  sum of every report's runtime
```

`_run_pass` walks `registry.run_order(...)` and runs each ready report as a
**serial subprocess** (`run.py:434-510`). With ~19 non-upload reports, several
taking 10-30 minutes (`fiber_activations` alone ran 07:13→07:28), the pass
becomes hours long.

Today: `--- pass 1 ---` at 04:00:00, still running at 07:47. **One pass, all
day.** Intended period 12 minutes; actual 227 minutes — ~19x.

Note this is *not* the pass blocking on a not-ready report. A gated report is
skipped correctly (`run.py:498-504`, sets `STILL_TRYING` and `continue`s). The
pass is long simply because the reports that *are* ready take a long time to run,
serially. The gated ones then wait for a next pass that doesn't come.

Three mechanisms inherit that latency:

| Mechanism | Where | Intended cadence | Actual today |
|---|---|---|---|
| Readiness re-probe of a not-ready source | `readiness.py:62` | every pass (12m) | once, at 04:31 |
| Flaked-report fast retry | `run.py:514` | ~90s after the pass's reports finish | ~3h18m |
| Incomplete part-retry (`retry_args`) | `run.py:652` | every pass | deferred all day |

The third has an extra multiplier: `_retry_incomplete_parts` defers itself while
*any* report is still non-terminal (`run.py:684`). Today at 07:47 it logged
`auto-retry deferred — 4 report(s) still to run (org_sales_board, board_compare,
daily_rep_breakdown, tableau_screenshots_box)`. On a day where one report waits
on a late extract, every part-retry in the batch waits behind it.

---

## What the safety nets are currently masking

This is the important part, because **nothing was actually broken by end of day**
— and that's exactly why this has gone unnoticed.

- **The 08:00 fail-open floor** is absorbing all probe staleness. It exists as a
  last-resort backstop; it is currently the *primary* release mechanism for
  late-extract reports. Any report whose probe has no floor, or a floor set later
  than its audience needs, has no net at all.
- **Manual reruns** are absorbing the flake retries. Today a human noticed and
  fixed aeon before the orchestrator would have. That only works for reports
  someone actually looks at — the trackers are highly visible; a quieter report
  would just stay broken.
- **`MAX_RUN_RETRIES = 3` and `MAX_AUTO_RETRIES = 2` are near-fictional.** A
  budget of 3 attempts is meaningless if only one pass runs; the report gets one
  attempt and one deferred retry, then noon backstop.
- **The 07:30 checkpoint email** reports mid-pass state, so it can describe a
  report as still-trying when it has in fact been sitting recoverable for hours.

### What breaks if we don't fix it

- Any transient failure early in the batch (network blip, Tableau flake, session
  hiccup) stays broken for hours instead of ~90 seconds — in front of the orgs.
- The "post when the data lands" design goal silently reverts to "post at the
  floor." That was the whole point of the readiness probe over a hard
  `not_before: '08:00'` cadence.
- **This gets monotonically worse.** Pass duration is the sum of report runtimes,
  so every report added to the Hub lengthens the pass and further starves every
  per-pass mechanism. We are adding reports steadily.

---

## Options

### Option A — Service tick interleaved between reports *(recommended)*

Between each report in the pass loop, run a short "service" step: re-probe
not-ready sources whose verdict is older than the interval, and run any owed
flake/part retries.

- **Pro:** keeps the single-threaded, one-browser-at-a-time model completely
  intact — critical, because Chrome/ownerville/Tableau sessions are shared and
  we already have a `chrome_guard` for exactly this hazard
  (`[[reference_chrome_collision_guard]]`). Retry latency becomes bounded by "one
  report's runtime" (minutes) instead of "the whole pass" (hours). No new
  process, no locking, no schedule changes.
- **Con:** retry latency is still quantised to report boundaries — a single
  90-minute report still delays a retry by up to 90 minutes. Better than 4 hours,
  not perfect.
- **Size:** small and contained. Mostly a new helper plus one call site inside
  the existing loop.

### Option B — Bound the pass, move gated reports to their own lane

Cap pass duration; run readiness-gated reports in a separate lightweight loop
that only probes and launches when ready.

- **Pro:** conceptually cleanest — separates "run the work" from "watch for work
  becoming runnable." Probing is cheap and could run on a true fixed cadence.
- **Con:** two things can now want the browser at once. That's the failure mode
  that has already cost us real mornings (stray-Chrome collisions, ownerville
  session contention). Would need a real mutex around browser-driving reports.
- **Size:** medium-large, and it touches the concurrency model.

### Option C — Just shorten the pass (parallelise report execution)

Run independent reports concurrently so the pass finishes fast.

- **Pro:** fixes the root arithmetic and speeds up the whole morning.
- **Con:** highest risk by far. Most reports drive the same Tableau/ownerville
  session and the same Chrome. This is a rewrite of the execution model, not a
  fix. Also contradicts the deliberate serial design.
- **Size:** large. Not proportionate to the problem.

### Recommendation

**Option A.** It fixes both of today's symptoms, preserves every invariant the
current design depends on (serial execution, one browser, shared session), and
is small enough to review in one sitting. If Option A's report-boundary
quantisation later proves too coarse, Option B becomes the natural follow-up —
A doesn't block it.

---

## Risk / blast radius

**High — review before merge.** `_run_pass` drives the entire morning batch
(~19 reports, ~10 Slack channels, every ICD-facing report). A bug here doesn't
break one card; it breaks the morning.

Suggested guardrails before this goes live:

1. Exercise it with `--simulate` (bypasses readiness, exercises the loop offline)
   and `--dry-run` first.
2. Verify against a replay of today: aeon's retry should fire within minutes of
   04:29, and Box should post shortly after ~07:42 rather than on the 08:00
   floor.
3. **Leave the 08:00 fail-open floor in place.** It should go back to being a
   net, not the mechanism — do not remove it as part of this change.
4. Land it on a day someone is watching the 4am batch.

---

## Open question for Megan

Option A changes *when* retries happen, not *whether*. Do you also want a
loud signal — e.g. the existing failure email firing immediately on a flaked
report, rather than waiting for the 07:30 checkpoint? Today the system knew at
04:29:05 that a channel was short and nobody was told until a human looked.
