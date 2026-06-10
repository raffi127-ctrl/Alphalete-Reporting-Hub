# Later Thoughts — Hub ideas to revisit

A parking lot for ideas we know we want to add to the Alphalete Reporting
Hub later, but are not building right now. Add to this list anytime.

---

## Auto-running scheduler
Logged: 2026-05-15

**What:** the Hub runs reports on their own at a set time (Daily / Weekly /
Monthly + time of day) — no human click needed.

**Why parked:** reports that pull from a logged-in website (e.g. Daily Rep
Breakdown needs Report Chrome open + an ownerville login) can't truly run
unattended while a human still has to log in each session. Revisit once a
logged-in browser session can be kept alive or the login automated.

**When we pick it up:**
- A background helper on the Mac (LaunchAgent) that checks every minute for
  any report whose frequency + time matches now, and runs it.
- Only auto-run reports flagged "no browser login needed." Login reports
  stay a "Due now" reminder for the assignee to click.
- The Mac must be on and awake at the scheduled time.

---

## Upload validation checklist
Logged: 2026-05-15 · **DONE 2026-06-10** (verified live)

**SHIPPED + wired.** `automations/shared/report_validation.py` is the engine
(auto-checks: syntax, size, Windows-compat, required metadata; attestations:
clean run / preview-first / names-checked). It's the HARD GATE in
`_save_uploaded_report` (dashboard.py) — blocks any upload until it passes,
returns the plain-English reasons. The upload UI renders the attestation
checkboxes + live validation, and the 🛡️ Validation Audit view re-runs the
auto rules across every report when a new rule is added. Extend by appending one
`Rule` to `RULES`. Self-test passes (`python -m automations.shared.report_validation`).

Minor wishlist gaps still open (small Rule additions if wanted): require an
ASSIGNEE in metadata, and an attestation that access-gaps were reviewed + the
access requests sent. The substantive checks are all in.

**What (original):** when someone uploads / wires up an automation, the Hub runs it
through a checklist of pre-flight checks before it's added to the Report
Library — so broken or half-ready reports don't go live.

**Checklist items to include:**
- Works on both macOS and Windows — no Mac-only assumptions. Megan
  specifically called this out as one of the things to check.
- Python script is valid (syntax is already checked at upload today —
  keep it).
- Declares ESTIMATED_MINUTES.
- Required metadata present: name, Sheet URL, schedule + time, assignee.
- "Needs a browser login" flag set correctly.
- The pre-flight checklist was recognized and auto-pulled by Claude — the
  "needs a browser login" flag drives the standard launch-Chrome +
  log-in steps; the uploader never hand-types a checklist.
- A full run of the report has been completed with NO errors before it's
  uploaded to the Hub. Per Megan: this is a hard requirement, not a
  "nice to have" — no report goes live unproven.
- Any ICDs/owners the report can't scrape yet because we don't have
  access are identified and listed, so access can be requested. The Hub
  already auto-appends these to the review email (the access-gap block);
  the checklist step is to confirm the list was reviewed and the access
  requests actually sent.
- Every ICD/owner name the report matches on has been checked against
  the shared master ICD alias sheet — any tab-nickname vs legal/Tableau
  spelling mismatch gets an alias added there (the canonical place), not
  patched per report. Catches the silent failure where a report runs
  clean but quietly leaves a tab blank because the name didn't match.
  Per Megan (2026-05-19).

**Note:** some checks can be fully automated (syntax valid, metadata
present); others — like "works on Windows" — can't be proven without
actually running on that OS, so the checklist may mix automated checks
with items the creator ticks to confirm.

---

## Test the run-experience features across the whole Library
Logged: 2026-05-16

**What:** resume, the progress bar, retry, and failure alerts are now
built. Go through every report in the Report Library and confirm they
all behave correctly — not just the report the features were built
against.

**Check per report:**
- An interrupted run can resume / retry and picks up where it stopped.
- The progress bar + ETA show while it runs.
- The failure diagnosis + "Report this glitch to Megan" button work.
- The desktop alerts fire correctly on success and failure.

---

## Platform check: Claude Cowork vs the custom Hub
Logged: 2026-05-15

Decision: keep the custom Hub for now, but revisit whether to move to
**Claude Cowork** (claude.com/blog/cowork-for-enterprise) — an
off-the-shelf Anthropic agent workspace for non-technical teams.

Cowork could likely replace the Hub's coordination layer (request
intake, review workflow, dashboards, reusable skills) with far less
maintenance. The ownerville / Tableau scrapers would stay custom either
way (Cloudflare + impersonation — no off-the-shelf connector).

When we circle back: catalog every function the Hub performs, cross-
reference each against Cowork's capabilities, then decide whether to
migrate. Megan likes the Hub's deep customization to their D2D ops, so
the bar to move is real.

---

## Re-run only the failed part of an automation (not the whole report)
Logged: 2026-06-07 · **DONE 2026-06-10**

**SHIPPED.** Built `automations/shared/run_manifest.py` (standard per-report
failure manifest: failed parts + retry_args + a {reason, fix, link, message}
remediation block). `dashboard.py` reads it generically — a "Retry failed only"
button (runs the card's module with the manifest's retry_args) + a failure-help
callout (why → fix → 🔗 Tableau link → 💬 copy-paste message). Rolled out to:
daily_focus (--retry-inaccessible), owners/captainship churn (--only), org sales
board (--step), focus_office/Daily Rep Breakdown (per-phase remediation). Any
new report opts in just by writing a manifest. Commits 629ab8d + f100465.
Remaining polish if wanted: granular retry for org board MIXED failures (today
falls back to a full re-run) and per-failed-section Tableau links.

**What (original):** every Hub report should let you re-run **just the
part/phase/ICD that failed**, instead of re-running the entire automation.

**Why:** today a single failed phase (e.g. Daily Rep Breakdown Phase 3, or
one timed-out section of the Org Sales Board) forces a full re-run — slow,
and it re-does work that already succeeded.

**Notes / prior art to generalize:**
- Some reports already do a version of this per-report: daily_focus
  `--retry-inaccessible`, focus_office Phase-2 resume checkpoint,
  org_sales_board `--only <section>`, JE staleness skip.
- The ask is to make this a **consistent, Hub-wide** capability — a
  standard "Run just what failed" action on every card, driven by each
  report's saved run-state (which phase/section/ICD failed).

**When we pick it up (tomorrow+):**
- Standard per-report failure manifest (phase/section/ICD list) written on
  every run; a generic "Retry failed only" Hub action that reads it.
