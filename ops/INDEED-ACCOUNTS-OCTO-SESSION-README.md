# Indeed Accounts through Octo — session README (Nov 16 → Nov 25, 2026)

What this chat built, what happened, and how to drive it. Give this file to a
new chat and it has the history. The living how-it-works text is
`~/recruiting-report/PUSHING-OPERATIONS-README.md` (Fix 2 under the phone-lookup
section, and the dated changelog); the plain-language version is
`RESUME-PUSHING-README.md` (same folder, "The 5am phone lookups + billing
check"). Billing holds on the live-ads numbers: `AD-SALES-BOARD-README.md` §4b.
All code: `~/recruiting-report/automations` (GitHub raffi127-ctrl/Alphalete-Reporting-Hub, main).

This file is public (the README hub): no phone numbers, applicant names,
emails or ids in it, ever.

---

## 1. What runs, in one paragraph

Carlos's office computer (the "relay machine", a Mac running the Lucy Reports
agent) opens **Octo Browser** twice a day and walks Carlos's **17 Indeed
accounts**. **5:00am:** for every applicant on the no-phone list, open that
applicant's Indeed account, read the number off the "Call" pop-up, write it to
`output/phone-lookups.csv` so the 5:30 resume walk can text them; then read
every account's All Jobs page for a payment/billing alert and its Gmail for
Indeed's billing emails. **1:00pm:** the billing pass only. Results travel as a
names-only tally row (`probe-octo-lookup`) to the ICD Faults tab of the relay
workbook; a billing alert is a loud `octo-billing` fault that Lucy 1 turns into
one group DM (Carlos + helpers + Megan/Eve). Lucy 1 (`billing_holds.py`, every
minute 8am–11pm) turns the tally into **hold rows** on the `Billing Holds` tab
of the Alphalete Recruiting Dashboard (timed off the Indeed emails when it has
them), DMs ":white_check_mark: ads are back live" when a hold clears, and the
live-ads sheet's **Days Down** column subtracts hold time from Days Live, CPA
and Cost / 2nd Booked.

The one-page report: **https://claude.ai/artifact/VtMcocEjDYPABYWbVufnFz**
(private to Carlos's Claude login; regenerate with
`python -m automations.oat_processing.octo_report`, see §5).

## 2. Where it stands (Wed Nov 25, 6:30pm)

Octo on the office computer is on 3.2.7 (updated by the run itself at 5:32pm).
All 17 accounts opened on the 5:32pm pass.

| Account | Ads | Status | Hold since |
|---|---|---|---|
| Hawk Specialized Marketing | 1 | live | |
| Fast Track Strategies | 1 | live | |
| Revolt Consulting Marketing | 1 | live | |
| Raw Sales Group Marketing | 1 | live | |
| Kinetic Marketing Partners | 1 | billing hold | Wed 11/18 7:05pm (never cleared) |
| Ascendra ("New Ascendra" in Octo) | 1 | billing hold | Fri 11/20 ~9pm, 2nd episode (est.) |
| Haus Specialized Marketing | 1 | billing hold | Sun 11/22 2:09pm |
| Titanium TX | 1 | billing hold | Sun 11/22 2:12pm |
| Peak Sales Strategies | 3 | billing hold | Mon 11/23 2:03pm (hand-set) |
| Iron Sales Group | 1 | billing hold | Tue 11/24 2:06pm |
| Magma Inc Marketing | 1 | billing hold | Tue 11/24 ~11pm (est., hand-set) |
| W Edge | 1 | billing hold | Wed 11/25 2:17pm (may be up to 2 days earlier) |
| Market Minds, Maverick Strategies, Pinnacle Growth Acquisitions, Riot Specialized Marketing, VividReach | 0 | nothing posted | |

So: 4 accounts with ads live, 8 with a billing issue (10 ads held), 5 with
nothing posted. "Ads" = Active rows of the newest week block on `carlos' live
ads`, not Indeed itself. The alert on every held account reads "Your Sponsored
Job benefits are unavailable until you add payment information or update your
plan" — Carlos ruled 11/16 that this COUNTS as a billing issue (keep flagging).

Phone lookups this week (5am runs, found / looked up): Thu 1/1, Fri 3/4,
Sat 0/1, Sun 2/6, Mon 8/11, Tue (5:32pm pass) 1/1.

## 3. Timeline and decisions

- **Nov 16** — Carlos: "automate this through the relay machine so that ...
  Octo Browser gets opened up and it looks for applicants' phone numbers for
  the ones that we don't have ... let's just do it at 5 in the morning." Built
  `automations/oat_processing/octo_lookup.py` + `octo_profiles.json` (17
  profiles; ships to the office computers). Same evening: "can we also add in
  launching all of the accounts and checking if there's a billing issue" →
  the billing pass; then "check for it, and actually do it twice a day ...
  notify me through Slack as well" → SLOTS 5am + 1pm, Slack via the fault road.
- **Nov 17** — first office run 5:01–5:33am: 3 numbers found, several accounts
  Cloudflare-walled (walls are waited out ≤4 min, one reload, NEVER clicked).
  `relay_faults` verb added to Lucy 1 so the laptop can read an office tally.
- **Nov 18** — every tally carries `ran` {argv, release, host} after an
  unexplained lookups-only 1pm row on 11/17 (still unexplained).
- **Nov 19** — Carlos: "go through these ads that had billing issues and check
  the email tab to see when we got the billing issue email ... communicate it
  with the automation that does Carlos's live ads so the CPAs are properly
  adjusted" and "it needs to somehow communicate when the ads go back live."
  Built: the run reads each profile's Gmail for Indeed's "Payment declined" /
  "We received your payment" / "job is live" mails (never signs in; a signed-out
  Gmail = times estimated from the checks); `Billing Holds` tab; `Days Down`
  column N on `carlos' live ads` (formula overlaps holds with each ad's live
  window); Lucy 1 `billing_holds.py` opens/closes holds and DMs back-live notes.
- **Nov 20–22** — it ran on its own: back-live DMs for Ascendra + Peak (11/20),
  W Edge (11/21), Raw (11/22); Titanium + Haus holds opened Sun 11/22 off the
  emails.
- **Nov 24, 5am** — Octo downloaded an update mid-run and from the 7th profile
  on refused every start: "Update is available. Please restart application."
  Nothing opened Mon 1pm, Tue 5am, Tue 1pm; the quiet tally said so 17 times a
  run and nobody was told.
- **Nov 25** — Carlos: "have these automations been working?" → read back the
  week; shipped (a) every-account-refusing = one loud fault (release .14);
  (b) Ascendra's second hold had reused its OLD decline mail and overlapped the
  first row → a decline dates a hold only if newer than the last clean read,
  else halfway between the last clean check and the first flagged one (.14);
  (c) a restart of Octo inside the run (.15 — which turned out to do nothing,
  see below). Carlos: "Try now and give me cleaner report to look at."
  - The office computer takes no commands, so a **run-now request** now
    travels with the code: `automations/oat_processing/octo_kick.json`
    {id, asked, lookups, billing}; a new id + release bump runs once on the
    next agent tick (`octo_lookup.kick_request`), requests older than 6h are
    ignored, `ran.kick` on the tally says a request ran it (release .16).
  - Pass one (5:14pm): every account still refused — the .15 restart quit
    Octo with `osascript`, which a background agent is not allowed to do on a
    Mac (no Apple-events consent), so nothing quit.
  - Pass two (5:32pm, release .19): `quit_octo` = NSRunningApplication
    `terminate` (resume_push's ctypes helper), then SIGTERM, then SIGKILL,
    each waited on; reopen; Octo's own `GET /api/update` said 3.1.3 → 3.2.7
    still required → `POST /api/update` ("update to 3.2.7 triggerred
    successfully"), Octo went down, came back on 3.2.7, all 17 opened. Every
    step is in the tally (`ran.restart`).
  - That pass showed two more faults, fixed in release .21: the tally row with
    8 alerts was longer than the relay's 6000-character cut, Lucy 1's
    json.loads failed and no hold opened → Lucy 1 reads a cut row for what is
    whole (`billing_holds._tolerant_json`) and the office side sends a tally
    that fits (the alert's own clause, no `billing_problems` twin). And Indeed
    RE-SENDS "Payment declined" every afternoon while an account is unpaid, so
    the newest mail dates nothing → `mail_times.declined_first` (first decline
    after the last payment) dates a hold from .21 on. Peak's and Magma's
    starts were set by hand on the tab (notes say why).
  - The report page (§1) was built and published; Carlos asked for the counts
    of live / billing issue / nothing posted — they are its headline tiles.
  - Seven `octo-billing` group DMs went out 5:50–5:53pm (Peak's did not show
    in the search; not chased).

## 4. Standing rules from Carlos (keep them)

- Never click a CAPTCHA / "Verify you are human" / Turnstile box — wait it out.
- Never download files without explicit permission; never enter passwords
  (a Gmail "Verify it's you" page = report as signed out).
- Never echo the proxy credentials in Octo's tentacle command line, any API
  token, or an email address into a log, a tally or a README.
- The recruiting-report repo and this README hub are PUBLIC: no phone numbers
  or applicant names in tracked files.
- The Revolt Octo window on Carlos's laptop is his own — never stop that
  profile, never POST /api/update on the laptop (it would restart his Octo).
- Carlos wants short, simple, result-first messages (phone-screen length).

## 5. How to drive it (for the next chat)

- **See a run:** on the laptop, `python -m automations.day_orchestrator.mini_control
  --enqueue relay_faults carlos probe-octo-lookup 2026-11-26 --machine "Lucy 1"`,
  wait ~3 min, read the `Relay Faults` tab of the shared control sheet (gspread
  via `automations.recruiting_report.fill._client()`). The row has found /
  missing names, per-account `accounts` + `billing` ("ok", "PROBLEM: …",
  "walled", "could not start (…)", "in use on another computer"), `billing_mail`
  (declined / declined_first / paid / live / signed_in) and `ran` {argv,
  release, host, kick, restart}. A row over 6000 characters is cut at the end.
- **Run it now:** new `id` + `asked` = now (office local time) in
  `automations/oat_processing/octo_kick.json`; bump `automations/icd_alerts/
  agent_release.txt` AND the `# release:` line of `agent_files.txt` (read the
  number on origin/main first — teammates bump it too; rebase conflicts land
  on exactly these two files); `git push origin HEAD:main`. The office
  computer usually picks it up within a tick or two; once it took 50 minutes.
- **Octo "Update is available. Please restart application."** → the run
  handles it (quit → reopen → POST /api/update) since release .19; if it
  still refuses, `ran.restart` says which step failed.
- **Holds:** `Billing Holds` tab of the Alphalete Recruiting Dashboard
  (111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA): Indeed Account | Hold From |
  Hold Until | Source / note. Blank Until = still on hold. Hand-fixing a start
  is fine (append why to the note). Lucy 1 can be nudged with `rerun
  billing_holds` (it also runs by itself every minute). Account names on the
  tab are the live-ads names (Ascendra, VividReach), the tally uses the Octo
  titles (New Ascendra, VividReach - Active).
- **The report page:** `python -m automations.oat_processing.octo_report
  [kick-id]` → `output/indeed-account-check.html`; publish it to the Artifact
  URL in §1 (pass the URL as `url` from a new chat). WEEK / LAST_KNOWN /
  FIRST_DECLINE inside it are this week's by hand — refresh or drop.
- **Laptop can't open the relay workbook** — go through Lucy 1's queue; the
  Lucy 1 queue tab is its own workbook (`control_books.book_for("Lucy 1")`,
  tab "Mini Control"); results keep ~480 chars.

## 6. Open items

- Haus and Revolt: Gmail signed out in their Octo profiles (times estimated).
  W Edge's hold start (11/25 2:17pm) may be up to two days early — its earlier
  decline mails were unread while its Gmail was signed out.
- Six profiles have no domain on file in `octo_profiles.json` (New Ascendra,
  Pinnacle, Market Minds, Riot, Maverick, VividReach): matched by title.
- The 11/17 1:27pm lookups-only run is still unexplained (telemetry since .18.1).
- Run-now pickup lag (50 min on 11/25 4:22pm) — why, unknown.
- Memory notes for Claude: `octo-phone-lookup-5am.md`, `live-ads-billing-holds.md`.
