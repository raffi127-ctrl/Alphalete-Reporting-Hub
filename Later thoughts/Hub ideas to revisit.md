# Later Thoughts — Hub ideas to revisit

A parking lot for ideas we know we want to add to the Alphalete Reporting
Hub later, but are not building right now. Add to this list anytime.

---

## Auto-running scheduler
Logged: 2026-05-15 · **DONE 2026-06-23** (this is now the thing running the whole morning)

**SHIPPED.** The Mac mini day-orchestrator (launchd `com.alphalete.day-orchestrator`,
~4am CST) auto-runs ALL non-upload reports with a readiness gate + circle-back retry +
7:30/noon email summaries. The "can't run unattended while a human logs in" blocker was
solved by the session-holder keepalive (keeps ownerville/AppStream warm). Run order is
now flow-optimized (non-Tableau first → Tableau → daily_rep_breakdown last, 2026-06-30).
Remote control via `lucy`; readiness = source_type based. Original note kept for history.

**What (original):** the Hub runs reports on their own at a set time (Daily / Weekly /
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

Wishlist fully closed 2026-06-10: assignee is now a required-metadata auto-check
and "Access gaps reviewed + requests sent" is an attestation (commit 9145655).

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
Logged: 2026-05-16 · **AUDITED 2026-06-10**

**Audit verdict — Library is in good shape.** Static coverage audit across all
~18 cards (2026-06-10):
- **Failure alerts** = GLOBAL (every failed run auto-files to Bug Reports +
  emails Megan) — no per-report gap.
- **Progress bar + ETA** = GLOBAL (time-based via estimated_minutes on every
  card); live per-step [X/Y] only on daily-rep-breakdown (nice-to-have).
- **Retry failed only** (manifest) = now on every multi-part report:
  daily-focus, owners/captainship churn, org-sales-board, daily-rep-breakdown,
  fiber-activations, AND recruiting + recruiting-alphalete-org (closed
  2026-06-10, commit f6ed77d). The remaining manifest-less cards are
  single-pull / upload reports where "retry failed only" == just re-run.
- **Resume checkpoint** = only daily-rep-breakdown. Worth adding to the long
  recruiting reports someday; everything else is short enough not to need it.
  recruiting-carlos manifest **DONE 2026-06-30** — carlos_opt_all + alphalete
  opt_all now write wrapper-completeness manifests (verify wired). So every
  scheduled report now has a manifest / "retry failed only" path.

**What (original):** resume, the progress bar, retry, and failure alerts are now
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
Logged: 2026-05-15 · **DECIDED 2026-06-30 — stay on the custom Hub.**

**Decision (Megan, 2026-06-30): keep the custom Hub.** The value is the custom
scrapers (ownerville/Tableau/AppStream Cloudflare bypass + impersonation + the
one-session-per-account keepalive) and the domain logic (52 ICDs, captainships,
churn math, alias/terminated-ICD handling) — none of which Cowork replaces. The
coordination layer Cowork would swap in is a thin shell tightly wired to the
automations (cards→modules→manifests→retry→Hub Activity→mini scheduler), and the
real maintenance cost is the automations, not the shell. Revisit ONLY if the
team-collaboration side grows (generic agent/planning/doc workflows) — and even
then likely a HYBRID (Cowork for human triage, Hub stays the execution engine),
not a replacement. Original note kept below for history.

Earlier framing: revisit whether to move to **Claude Cowork**
(claude.com/blog/cowork-for-enterprise) — an off-the-shelf Anthropic agent
workspace for non-technical teams.

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
