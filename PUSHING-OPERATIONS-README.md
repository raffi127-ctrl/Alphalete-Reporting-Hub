# Resume & Applicant Pushing — Operations README

**Canonical doc for how pushing works across the fleet, and the ledger of
changes that broke things — read the ledger BEFORE making any change.**
Maintained automatically: a daily 7:00 PM job appends new changes, new
issues, and new Sheet/tab additions. Manual edits welcome; put dated notes in
the changelog at the bottom so the updater doesn't fight you.

---

## 1. The machines and how code moves

- **Mini (Carlos's desktop)** — where Claude works interactively. Never runs
  scheduled pushes. Cannot hold the push login (by design, since 9/2).
- **Lucy 2 (MacBook)** — runs ALL scheduled pushing. Driven only via the
  Google-Sheet command queue ("Mini Control - Lucy 2", sheet id
  `1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`) — no SSH.
- **Deploy** = git: edit on mini → push to `origin main` → queue `update` row →
  Lucy pulls on her next tick. VERIFY BY LOG (`logtail`), never by a success
  message.
- The queue poller is **single-threaded**: one long job blocks every row behind
  it (~25 min worst case). Results in the sheet **truncate hard** — rich output
  must go to a dedicated tab (see `dump_activity`) or be read via `logtail`.

## 2. The two pushing automations (they are different things)

| | Applicant Push (send-to-call-list) | Resume Pusher (uploads) |
|---|---|---|
| What it does | Walks the OAT queue (p=604), fills phone/email, clicks Send to AI | Uploads resume files |
| Offices | 11580 (Carlos) + 23467 (Atef), hard-coded | 11580 |
| Cadence | Every 5 min, one office per tick, strict alternation | Every 10 min |
| Window | 7 AM–10 PM CST daily, **minus the weekend quiet window** | 8 AM–10 PM, skips Saturday |
| Logs | `applicant-push-<date>.log` (11580) / `applicant-push-23467-<date>.log` (Atef) — **separate stems!** | resume pusher log |

**Weekend quiet window (Carlos, 9/4): live pushes stop Friday 1:00 PM CST and
resume Sunday 1:00 PM CST.** Enforced in `applicant_push/run.py`, fails closed,
`--audit-office` is the only override.

**One office per tick, on purpose** (offices.py, 8/26): a hard time cap per
tick means a bad day in office A would starve office B if one tick did both.
Never "fix" this by merging the offices into one tick.

## 3. Accounts & logins (post-9/2 world)

- Automation NEVER uses the shared "Raf – Captain" login anymore. Two accounts
  exist: **Lucy Reports** (all reporting) and **Lucy Resume Pushing**
  (`lucyresume`, the push, byte-exact username WITH the spaces).
- The mini deliberately has no push account installed — a local run failing
  with "No AppStream account named 'lucyresume'" is the system working.
- **A wrong username does NOT error.** The form fills, Cloudflare clears, and
  the console renders off the previous session's cookies. Everything upstream
  reads that as success while every page is actually blank (the
  `extract failed: null innerText` wall). See ledger entry 9/2–9/6.
- Credential install: `set_appstream_account lucyresume "Lucy Resume Pushing"
  <password>` on the queue — password comes from Carlos/Megan only.
- The real credential test AND the session-minting path is
  `rerun applicant_push --dry-run` (real-Chrome/CDP, the path pushes actually
  use). `appstream_whoami_account` can false-negative on scoped accounts
  (patchright path). Do not trust `login_check` alone for the push account.
- The 3:15 AM self-heal tends the REPORTS token, not the push account.

## 4. Decision rules the walk enforces (taught 8/28–8/30, all in code)

- Read the applicant panel first; open the resume; fill phone AND email
  (email only from the resume itself, near the phone; NEVER from a downloaded
  .eml — those carry the OFFICE's addresses; fleet emails are blocklisted).
- Click Send to AI, then WAIT for a definite outcome (refusal panel or the
  name leaving the slot). One snapshot lies.
- Refused → read the history/status verbatim, then:
  - "Left Message" → override and send (never reached them; still looking)
  - "Removed … Insufficient Contact Info" + we now have a number → override/send
  - "Unmarked Show" → FUTURE interview → remove as duplicate (never re-text)
  - "Second Round Showed Up" / "Delay Disqualified" → remove as duplicate
  - No-show / rejected / not qualified → re-text the await message (TEXTING
    OFFICES ONLY: 11580 + 23467), then remove; non-texting offices try the
    override first and only then remove
  - Sent-to-call-list TODAY or future booking → remove as duplicate
- Resume page won't open: Carlos/Atef offices LEAVE the applicant (our failure
  never costs a record); audit offices remove as Insufficient Contact Info.
- No phone anywhere: 11580 leaves them; other offices remove (per-office
  `remove_no_phone`).

## 5. Guardrails (all fail closed — do not weaken)

1. `PUSH_ALLOWED = {"11580","23467"}` — a live push for any other office exits
   before a browser opens. Audits require the explicit `--audit-office` flag.
2. `_guard_office_now` re-reads the on-page "Office ID:" banner IMMEDIATELY
   before EVERY Send-to-AI / override / remove click. Wrong office, unreadable
   banner, or unset expectation → the click is refused and logged
   (`⛔ OFFICE GUARD`). Born from the Vincent/23318 incident (8/30).
3. Weekend quiet window (see §2).
4. Single-instance guard: a second applicant_push on one machine refuses to
   start (shared profile). Watch for LINGERING processes after kills — a stale
   pid blocks every later tick with "ALREADY running".
5. Sends by automation appear in AppStream ledgers under the fleet identity —
   remember this when auditing "who did what" (humans share names with bots
   in per-admin breakdowns prior to 9/2).

## 6. THE CHANGE→BREAKAGE LEDGER (look here before changing anything)

**Changed: login accounts split (9/2, commit 5c3177b3).**
Broke: both push queues silently backed up for ~4 days (Carlos 47+, Atef 100+).
Why: the new `lucyresume` credential never validly signed in — and wrong
usernames fake-succeed (see §3), so every tick "ran" against blank pages while
wedge-watch and coarse SENT greps looked healthy.
Fix: `set_appstream_account` row with the byte-exact username, then dry-run to
mint. LESSON: after ANY login/account change, verify with (a) whoami/identity
assert, (b) a fresh `✅ SENT` line in BOTH offices' logs — Atef's log is a
DIFFERENT FILE (`applicant-push-23467-…`), and grep counts lie.

**Changed: ran audit/one-off jobs on Lucy during push hours (8/30).**
Broke: Sunday's push day collapsed to 18 sends (normal ~50+/day).
Why: queued jobs share the push's Chrome profile; each startup pkills the
other's browser; ticks died mid-run all afternoon.
LESSON: never queue browser jobs to Lucy during push hours; if unavoidable,
expect thin pushing and say so. Also: two AppStream sessions on ONE machine
always end in TargetClosedError — mini + Lucy in parallel is fine.

**Changed: per-office behavior rules (retext/no-contact, 8/29).**
Broke: three applicants removed wrongly in one afternoon, three different ways:
(1) the override control only RENDERS after a send is attempted — checking for
it without clicking Send first removes sendable people; (2) a successful send
looks identical to "no override" one snapshot later — wait for the refusal
panel or the name to leave the slot; (3) the override is a `<button>` in some
offices but an `<input>` in others — its label lives in `value`, invisible to
innerText; and it can render in a frame. Match innerText OR value, ALL frames.
LESSON: any new office = assume its DOM differs; dump controls before trusting
matchers; on ambiguity FLAG, never remove.

**Changed: email capture added (8/29).**
Broke: typed the OWNER'S OWN email into an applicant record — twice.
Why: .eml downloads are mail TO the office; the resume viewer's page chrome
carries the logged-in account's address.
Fix: email only from within ~300 chars of the phone in the resume text; .eml
never yields an email; fleet addresses hard-blocklisted.

**Changed: allowlist-gated walks for audits (8/29–30).**
Gotchas found: OAT `MAX_PER_RUN=60` silently caps a walk (pass `--limit 400`
for full sweeps); junk-fronted queues (nameless AD receipts) trip the
end-of-queue guard unless the allowlist walk tolerates ~40 blank reads;
restore pages drop their Restore controls mid-pass (repeat until clean);
"Removed Apps <office>" Sheet tabs get OVERWRITTEN by each scrape — copy names
out (`--names-out`) before the next run.

**Changed: added a third office to the rotation (9/8, Khalil 11901).**
Broke: nothing visibly — his ticks simply never fired. Why: the rotation is
declared TWICE — `offices.py ROTATION` (Python) and `ROTATION=` in
`deploy/applicant_push.sh` (the shell wrapper that actually picks the office).
Editing only the Python side looks complete and does nothing.
Then (same day) his first slot STOPPED THE AGENT COLD, pre-log: the row was
missing the REQUIRED "account" key (post-9/2 schema; activate() reads it with
[] on purpose so a typo fails loudly) — a row built from a pre-refactor
template. And once fixed, the office switch failed anyway: the scoped
"Lucy Resume Pushing" login could not see 11901 until Megan granted access.
LESSON — the full add-an-office checklist: offices.py row WITH "account":
"lucyresume" + Python ROTATION + wrapper ROTATION (declared TWICE!) +
PUSH_ALLOWED + its own Slack channel if it posts + MEGAN GRANTS THE OFFICE to
the push account + a supervised probe (`rerun applicant_push --office <id>
--dry-run`, auto-retried past tick collisions) passes — and ONLY THEN the
wrapper rotation. A crashed slot kills ALL offices' ticks until the agent is
reinstalled (`rerun install_applicant_push_agent`).

**Changed: Khalil (11901) fully joined the scheduled rotation (9/9).**
Broke: the same-day MANUAL rerun for his office died mid-walk
(TargetClosedError) — his newly-live scheduled slot pkills the office profile
on startup. LESSON: once an office has a scheduled slot, NEVER also run a
manual push for it during push hours; the two paths share the office profile
and the scheduled tick always wins. Manual reruns are only for offices with no
slot, or outside the window.

**Changed: queue-driven diagnostics (8/30–9/3).**
Gotchas: sheet Result cells truncate (~a few hundred chars) — use `logtail`
against the log file, or a tab dump; `rerun` args are shlex-split — a literal
`--` separator errors; `logtail` greps can be case-insensitive and match
`sent=0` noise — count `✅` lines, not "SENT".

**Standing invariants** (violating these caused real damage):
- Never remove an applicant on a blocked/unreadable read in 11580/23467.
- Never text an applicant outside 11580/23467; no texts late-night (batch
  pushes for texting offices wait for morning).
- On pause: kill only python, never Chrome — Carlos watches the window.
- Removals by automation show under the fleet name in AppStream — document
  what you removed, when, per office (`output/oat-activity-<date>-<office>.csv`,
  LAST row per person wins).

## 7. Sheets & tabs inventory

- **Mini Control - Lucy 2** (queue): [Queued At, Action, Args, By, Status,
  Result, Finished At]. Whitelisted actions incl. `ping`, `update`,
  `rerun <id> [args]`, `logtail <log> [grep] [n]`, `diag`, `restart_holder`,
  `restart_poller`, `set_appstream_account` (SECRET), `login_check`,
  `appstream_whoami_account`, `reseed_appstream` (DEFAULT account only!).
- Diag tabs per office: `OAT Walk Diag[ <office>]`, `Applicant Push Diag[ <office>]`.
- Scrape tabs: `Removed Apps <office>` (overwritten per run), `OAT Activity
  <office>` / `Atef Act <date>` (dump_activity output).
- Local outputs (each machine): `output/oat-activity-<date>[-<office>].csv`,
  `oat-no-phone-queue.csv`, `oat-retext-queue.csv`,
  `oat-nophone-blocked-<date>-<office>.json` (blocked-read retry cache).

## 8. Verification protocol after ANY change

1. Deploy (push → `update` row) and confirm Lucy pulled (logtail the tick log).
2. `rerun applicant_push --dry-run` — sign-in + identity assert on the real path.
3. Wait for one live tick per office; confirm a fresh `✅ SENT` line in BOTH
   log stems (11580 and 23467 files are separate).
4. Check the retention admin breakdown (p=701, week view) next morning — the
   office's own books are the ground truth for sends/removals per admin.
5. Errors go to **#claudecorrections-and-requests**, never office channels.

---

## Changelog (auto-appended daily at 7 PM; newest first)

### 2026-09-06 (initial)
- README created. Credential fix for `lucyresume` landed 9/5–9/6; pushing
  verified live in both offices (130+/103+ ✅ sends Sunday afternoon);
  weekend quiet window (Fri 1 PM → Sun 1 PM CST) active since 9/4.
