# Lucy 3 — provisioning runbook

Written 2026-08-20, before the machine exists. When it arrives, any Claude
session can execute this top to bottom. Owner decisions are marked ⚖️.

## Why Lucy 3 exists

Lucy 1 (Raf's accounts) wedges when the 4am scheduled flow and daytime
hand-queued reruns fight over its ONE warm browser profile, and its FIFO
command queue backs up behind long runs. Laptops can't take the overflow
because the reports need the Lucys' logins. Lucy 3 is the **rerun + overflow
box**: daytime reruns, new-report testing, and (optionally) a slice of the
4am flow to shorten Lucy 1's critical path.

## ⚖️ Decisions Megan makes up front

1. **Accounts**: recommended — mirror Lucy 1 (Raf's logins: rcaptain
   AppStream, ownerville, Tableau, the Lucy Slack identity). That's where
   the wedges are. (Carlos overflow would mean mirroring Lucy 2 instead —
   don't mix orgs on one box; wrong box = wrong data.)
2. **Workload split**: recommended — Lucy 3 takes ALL daytime reruns +
   new-report testing; Lucy 1 keeps the whole 4am flow at first. Move
   scheduled reports over one at a time only if 4am still runs long.
3. **Hardware**: any Apple Silicon Mac mini, 16GB+. Same as Lucy 1/2.

## Known gotchas (why this isn't just "run the installer")

- **Same-account double sessions**: two machines holding warm sessions on
  the SAME ownerville/Tableau/AppStream accounts can kick each other's
  logins — which is itself a wedge cause. Mitigations: the session holder
  (ownerville keep-warm) runs on ONE box per account — leave it on Lucy 1;
  Lucy 3 logs in on demand via the normal patchright auto-login. Watch the
  first week for session-kick loops between the two.
- **Tableau access budget**: eStream flagged ~10k views/week; target is
  <10/day per the ledger. A second Raf-account box must ride the
  harvest-once caches, not re-pull. Any report moved to Lucy 3 keeps
  reading the SHADOW harvest.
- **launchd TZ drift**: launchd caches the timezone — set TZ before
  loading agents or jobs fire +2h (bit the mini before).
- **Python 3.9**: if the new mini ships with old CommandLineTools Python,
  runner code must stay 3.9-compatible (same rule as Lucy 1).
- **Chrome collisions**: never open human Chrome on the box; bot Chrome
  runs with --disable-sync (tab-sync leak, 2026-08-03).

## Setup steps

1. macOS setup: log in as the dedicated user, enable auto-login, disable
   sleep (Energy: never), enable SSH + Screen Sharing.
2. Run the team installer (installs brew, gh, clones to
   ~/recruiting-report, pins the wolf icon):
   `curl -fsSL -o ~/Downloads/Install-Recruiting-Report.command https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub/releases/download/v0.1.0/Install-Recruiting-Report.command && bash ~/Downloads/Install-Recruiting-Report.command`
   Sign in to GitHub with an account that has repo access.
3. Sign in once to each site so patchright profiles exist: AppStream
   (rcaptain), v2.ownerville.com, Tableau. Store creds via
   automations/shared/creds.py flow — never in files.
4. Slack: the Lucy user token (xoxp) + bot must be present; both bots must
   be members of every private channel they post to.
5. Install the mini_control poller agent (same as Lucy 1/2) with machine
   name `lucy3` so `lucy --machine lucy3 rerun/status/update/logtail`
   routes to it. Day markers are per-machine — use --mark-sent-only when
   seeding.
6. gmail-token.json = alphaletereporting@ (if any emailing report lands
   here later).
7. Verify end to end BEFORE routing real work: `lucy --machine lucy3
   update`, then one harmless report with --dry-run, then one real rerun.
   `lucy logtail` to confirm.
8. Hub: add a "Lucy 3" MEMBERS entry + Pack card (automations/dashboard.py
   MEMBERS list — Megan-owned, ask her) once real reports are assigned.

## Routing rules after go-live

- Humans (Megan/Eve): queue reruns with `lucy --machine lucy3 rerun ...`
  — leave Lucy 1's queue for its own scheduled flow.
- New reports: sandbox + test on Lucy 3 first; promote the schedule to
  Lucy 1 only if it must run in the 4am flow.
- If a rerun needs state that only exists on Lucy 1 (per-machine day
  markers, caches), it still goes to Lucy 1 — check first.
