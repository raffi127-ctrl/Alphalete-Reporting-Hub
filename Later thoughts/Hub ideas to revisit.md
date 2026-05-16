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
