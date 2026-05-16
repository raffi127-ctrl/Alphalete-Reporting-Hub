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

## Glitch recovery + resumable report runs
Logged: 2026-05-15

**What:** when a report run hits a glitch, the user can pick it back up
from the report's project card instead of starting the whole run over.

**Details to build:**
- Detect the glitch and alert the user clearly — what went wrong, and the
  exact steps to take to fix it or continue.
- A "Continue / resume run" action on the project card so a stalled or
  failed run carries on from where it stopped, not from scratch.
- A "Report this glitch to the Hub master" button so the issue gets sent
  to whoever owns the Hub (Megan) for follow-up.
- Persistent run state: the user can navigate out of the running-report
  screen and back in and land exactly where they left off — the live
  progress view, not a reset/refreshed one.

---

## Upload validation checklist
Logged: 2026-05-15

**What:** when someone uploads / wires up an automation, the Hub runs it
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
- Ideally a dry/test run completes without error.

**Note:** some checks can be fully automated (syntax valid, metadata
present); others — like "works on Windows" — can't be proven without
actually running on that OS, so the checklist may mix automated checks
with items the creator ticks to confirm.

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
