# New Hub Card — Intake Checklist

Fires **every time a new card is added** to the Hub (hardcoded in
`AUTOMATED_REPORTS`, uploaded to the shared library, or auto-registered by
`hub_coverage.py`). The point: no card goes live unreviewed, and Megan gets
prompted to eyeball it against the full [[hub-card-review-checklist]].

## The rule

> When a new Hub card appears, **Claude proactively pings Megan** — "New card
> `<name>` was added; go review it" — with a link to the card and this checklist.
> Don't wait for her to notice. (Matches her standing "prompt me, I forget" rule.)

The `hub-watch` mini watcher already emails Megan on any Hub code/card change
([[hub-watch]]). This checklist is what that ping should point her at.

## Before the card is considered "live"

Run the full [[hub-card-review-checklist]] (A–E). The intake-specific must-haves:

- [ ] **Screenshot uploaded** — `resources/report-screenshots/<id>.png`. A new card
      with no screenshot is the #1 thing that slips through.
- [ ] **"How it works" written** — a real `breakdown`, not a placeholder. Simple,
      plain-English, WHAT IT DOES / WHEN IT RUNS.
- [ ] **Profile chosen deliberately** — Lucy 1 vs Lucy 2 vs Ops, and it can actually
      reach its sessions/tokens on that machine.
- [ ] **Placed in the correct schedule section** with the right time (and the time
      shows on the pill if it's Time-Set).
- [ ] **Alerting wired from day one** — `verify` is a real `manifest` check (not
      `null` / `not_configured`), and a failure routes to
      #claudecorrections-and-requests. A new report with no completion check is the
      #2 thing that slips through.
- [ ] **Validated for correctness** — run through [[report-validation-checklist]]
      (dry-run, Marcellus preview for multi-tab, terminated-ICD check, etc.).
- [ ] **Multi-pass declared** if it runs more than once a day (`daily_runs`).
- [ ] **Preflight + More-actions** sane for this specific report.

## After review

- [ ] Megan gives the explicit OK, OR the flags are logged for follow-up.
- [ ] If anything's a "no," it's fixed or the card stays visibly flagged (not
      silently shipped).

---

**Related:** [[hub-card-review-checklist]], [[report-validation-checklist]],
[[hub-watch]], [[project-report-validation-gate]].
