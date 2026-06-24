"""Day Orchestrator — the always-on Mac mini scheduler that guarantees every
scheduled Tableau report for the day ends up RUN-AND-VERIFIED, or explicitly
flagged as MISSED with a reason.

One resident process, launched once each morning by launchd
(com.alphalete.day-orchestrator). It:

  * Probes readiness PER TABLEAU SOURCE (today's rows actually present — not a
    clock time). AppStream + pure-API are treated as immediately ready; uploads
    are manual (only noted, never auto-run).
  * Runs what's ready, skips what isn't, and CIRCLES BACK every 25 min.
  * Emails a CHECKPOINT at 7:30am CST (status snapshot, incl. "still trying"),
    keeps retrying until a NOON backstop, then emails a FINAL completion summary.
  * RECONCILES by re-reading the sheet (never trusts exit 0) — the completeness
    guarantee.
  * Fails CLOSED if the ownerville session is stale (skip, don't write garbage)
    and alerts immediately to re-seed the mini.

Design doc: output/day-orchestrator-design.md
Everything honors --dry-run (no sheet writes, no real emails) until cutover.
"""
