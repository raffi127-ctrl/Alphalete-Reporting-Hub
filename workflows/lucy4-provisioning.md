# Lucy 4 — provisioning runbook

Written 2026-09-17, before the machine exists. Supersedes
`workflows/lucy3-provisioning.md` and `workflows/setup-new-runner.md` for any
NEW box (both are kept, both contain stale login text — see §0).

**Why this document is longer than "run the installer":** Lucy 3 was
provisioned on 2026-08-21, passed every check that day, and on its debut
morning ran **zero reports for four hours**. Nothing errored. Everything below
marked 🩹 is a scar from that week. Work the phases in order; do not skip the
verification line at the end of a phase because the step before it printed ✓.

---

## 0. Read this first — the docs that lie

- `workflows/lucy3-provisioning.md` step 3, `workflows/setup-new-runner.md`
  §"What still needs a human", and the closing banner of
  `deploy/setup_lucy_machine.sh` all say a person must clear the Cloudflare
  "verify you're human" box at the machine. **That has been false since
  2026-09-02.** Both logins are typed by code
  (`session_holder._unattended_ownerville_login`,
  `session_holder._appstream_form_login`); Cloudflare clears itself if the
  20–30s pre-submit pause is respected.
- **`resources/lucy-login-standard.md` is authoritative on every login
  question.** If code or a banner disagrees, the code is the stale thing.
- Fix `deploy/setup_lucy_machine.sh`'s closing banner as part of this build
  (see §7) so Lucy 5 isn't told the same thing.

---

## ⚖️ Decisions — SETTLED 2026-09-17 (Megan)

1. **OwnerVille account: Raf (`rhidalgo`)**, same as Lucy 1 and Lucy 3.
   AppStream is `Lucy Reports`, as on every machine. Already written into
   `login_check.EXPECTED_OWNERVILLE_ACCOUNT` and asserted by
   `test_login_policy` — a box that signs in as anyone else now fails the check
   rather than quietly producing Carlos's numbers.
2. **Workload: undecided — "set up to run anything."**
   So the build gives Lucy 4 every *capability* on day one, and leaves it **off
   the 4am clock**:
   - every credential, token and browser profile a report could need (§2),
     including the **Messages grant**, which is the one thing that cannot be
     done remotely afterwards;
   - all five always-on agents;
   - **no `day-orchestrator`, and no heartbeat entry**, until the first report
     is actually routed to it (§6). An orchestrator on a box with zero assigned
     reports buys nothing and arms a watchdog that pages about a batch that was
     never going to run.

Hardware: any Apple Silicon Mac mini, 16 GB+, on wired power and ethernet if
possible (Lucy 3's Wi-Fi timeouts are on record).

---

## 1. One command at the machine

Log in as the box's own local user (e.g. `lucy4`), open Terminal, paste:

```bash
curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/deploy/setup_lucy_machine.sh -o /tmp/setup_lucy.sh && bash /tmp/setup_lucy.sh Lucy 4
```

It asks for the Mac password once and a GitHub browser sign-in, then does:
timezone → **America/Chicago** (launchd caches TZ — it must be set before any
agent loads), network time, Command Line Tools, `pmset … disablesleep 1`,
Remote Login, Screen Sharing, the team installer, the Google sign-in, the
`.machine-profile` marker, and five LaunchAgents:
`mini-control`, `mini-control-read`, `session-holder`, `keep-awake`,
`orchestrator-schedule-guard`.

Anything that didn't stick is printed as a manual checklist at the end — read it,
don't close the window.

🩹 **Do the Google sign-in as `alphaletereporting@gmail.com`**, not a personal
account. A 403 from gspread arrives as a `PermissionError` whose `str()` is
**empty**, printed as `()`. `brand_audit` died this way on Lucy 3's third day.

🩹 **Before that sign-in, confirm `alphaletereporting@` has Editor (not Viewer)
on the Mini Control queue workbook.** A runner that can't write its result row
cannot be driven remotely any more, and fixing it needs someone physically at
the machine.

### Still manual, on purpose
- **Automatic login** — System Settings → Users & Groups. Not scripted because
  scripting it writes the Mac password to `/etc/kcpassword`.
- **FileVault OFF** (Megan's call on Lucy 3) — otherwise a reboot never reaches
  the login the agents need.
- **NOPASSWD sudo** for remote sleep/reboot control:
  ```bash
  echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/pmset, /sbin/shutdown, /sbin/reboot" | sudo tee /etc/sudoers.d/lucy-nopasswd
  sudo chmod 440 /etc/sudoers.d/lucy-nopasswd
  ```
- **Restart on power failure**: `sudo pmset -a autorestart 1`.

**Verify phase 1** — from Megan's laptop:
```bash
lucy diag --machine "Lucy 4"
```
If this prints *"UNKNOWN machine 'Lucy 4'"*, the poller has not drained its tab
yet — that is correct and expected; the tab bootstraps the first time Lucy 4's
own poller runs, never from the laptop side. Wait for a poll cycle, retry.

---

## 2. Secrets (typed at the machine — never through the queue)

```bash
cat > ~/recruiting-report/ownerville-creds.json <<'JSON'
{
  "ownerville_username": "rhidalgo",
  "ownerville_password": "…",
  "appstream_username": "Lucy Reports",
  "appstream_password": "…"
}
JSON
chmod 600 ~/recruiting-report/ownerville-creds.json
```

🩹 `Lucy Reports` **has a space in it.** Not `LucyReports`, not `lucy_reports`.
A wrong AppStream username does not error: the form fills, Cloudflare clears,
the submit goes through, and the console renders off the *previous* session's
cookies carrying no token. It took out a whole 4am batch once.

🩹 OwnerVille logs in at `https://ownerville.com/`, never `v2.ownerville.com`.

Everything else can be pushed remotely once the poller is live:

```bash
lucy push_slack_tokens "Lucy 4" --machine "Lucy 1"          # bot + xoxp user token
lucy push_cred_file gmail-app-password "Lucy 4" --machine "Lucy 1"
lucy push_cred_file drive-token "Lucy 4" --machine "Lucy 1"  # only if it gets a Drive report
```

🩹 **Never `push_appstream_fleet` / `set_appstream_state` at a machine that has
its own login.** Pushing a session is an *identity swap*, not a favour — every
office lookup behind it silently becomes the other account's. Each Lucy mints
and heals its own (`resources/lucy-login-standard.md` §6).

### 🩹 The Messages grant — do it while a person is still at the machine

This is the one capability that cannot be added remotely later, so "set up to
run anything" means doing it now even though no texting report is assigned yet.

```bash
bash ~/recruiting-report/deploy/grant_orchestrator_messages.sh
```

Click **Allow**, then read the verdict it prints. Two traps it exists to cover:

- **The grant is per IDENTITY, not per machine.** Granting Full Disk Access from
  a Terminal test grants *Terminal* — the launchd job is a different identity and
  still gets `authorization denied` on the same `chat.db` path.
- A runner's `.venv/bin/python3.9` is a **257-byte bash script**, not a binary,
  so macOS attributes the grant to bash and it never lands. That is why the
  privileged step is its own stdlib-only script with its own LaunchAgent whose
  `ProgramArguments[0]` IS the granted binary. Do not "fix" the venv wrapper —
  ~130 automations run on it.

Separately: iMessage **groups** live in one machine's `chat.db`. Granting
Messages here does not give Lucy 4 Lucy 1's chats, so a texting report still
only moves if its groups exist on this box (§8).

**Verify phase 2:**
```bash
lucy login_check --machine "Lucy 4"     # passes only if BOTH OV and AppStream pass
lucy sheets_whoami --machine "Lucy 4"
lucy slack_whoami --machine "Lucy 4"    # must come back lucy_reporting, ~13 scopes
lucy messages_diag --machine "Lucy 4"   # the grant, as the identity that will use it
lucy install_pinned_chrome --machine "Lucy 4"   # a box with no SSH needs this action
```

---

## 3. ✅ Register Lucy 4 in the code — now ONE file

**This used to be the step that broke everything.** The roster was eleven
hand-maintained literals across nine files; every one fails silently when a
machine is missing from it, and four had gone stale unnoticed —
`hub_schedule_status._LUCY` (four weeks of Lucy 3 cards reporting "no
schedule"), `office_onboarding.MACHINES`, a dead `card_scheduler._LUCY`, and
`gap_alerts.MACHINE_OWNER` (no Lucy 3, so the "who is logged in here" line said
"this machine's owner" on the box most likely to be mid-rerun).

**As of 2026-09-17 there is one roster: `automations/shared/fleet.py`.**
Lucy 4 is already in it. Adding **Lucy 5** is two edits:

1. append a `Machine(...)` to `fleet.MACHINES`;
2. add its `MEMBERS` entry in `automations/dashboard.py` (display only — colour
   and badge; `test_fleet` fails if you forget).

Everything else derives: `RUNNERS`, `APPSTREAM_HOLD_MACHINES`,
`APPSTREAM_FLEET_MACHINES`, `MORNING_CLOCK_MACHINES`,
`EXPECTED_OWNERVILLE_ACCOUNT`, `OFFICE_ONBOARDING_MACHINES`,
`TEXTING_MACHINES`, `MACHINE_OWNER`, `HOSTNAMES`.

**Capabilities are FLAGS, not membership**, and they flip at **go-live**, never
at provisioning — `holds_appstream` / `runs_appstream` when the first AppStream
report is routed there, `morning_clock_since` when it joins the 4am batch (that
date doubles as the heartbeat's `watch_from`, so a new box gets one clean 04:20
cycle before it can page), `can_text` only after
`grant_orchestrator_messages.sh` has run ON it and a real line AND image were
seen to arrive.

`automations/shared/test_fleet.py` is the guard, and it was proven to fire
rather than assumed — each of these was simulated against a deliberately
wrong Lucy 5:

| Mistake | Caught by |
|---|---|
| in the roster, no Hub profile card | `test_every_runner_has_a_profile_card` |
| a consumer left out of step | `ConsumersAgreeWithTheRoster` (6 consumers) |
| a NEW hand-rolled machine list anywhere under `automations/` | `test_no_new_hand_maintained_machine_list` |
| holds an AppStream console it never reads | `test_a_holder_also_runs_appstream` |
| a box off the 4am clock given a heartbeat | `test_a_machine_off_the_clock_has_no_heartbeat` |

Still separate, once real work moves (§6):
`day_orchestrator/schedule_config.json` → `"machine": "Lucy 4"`,
`library_assignments.json`, and each Hub card's `assignees` / `run_machine`
in `automations/hub_cards.py` — those are per-REPORT routing, not roster.

`machine_digest.run._machine_label()` resolves a run's hostname to a label and
takes its Lucy-2 hosts as a CLI argument; `fleet.HOSTNAMES` now carries the
hostname map for when that is unified. An unknown host still prints RAW on
purpose — "Lucys-Mac-mini.local" is Lucy 3 and "Lucys-MacBook-Neo" is Lucy 2, so
any "lucy in the hostname → Lucy 1" shortcut names the wrong box.

### 🩹 Why Lucy 4 does NOT warm AppStream on day one

This was added and then backed out on 2026-09-17, and the reason is the whole
point of this document.

Every Lucy signs in to AppStream as the **same `Lucy Reports` account** — the
per-person migration never happened. `session_holder.py`'s own history is
explicit that mutual token invalidation is a *same-account* problem that
"returns the moment two machines share an account again": each holder re-hops
its console every ~6 min, and renewing **invalidates the token every other
machine is still holding**. Three machines already pay that churn. A fourth
raises it against Lucy 1, 2 and 3's **live 4am batches**, in exchange for
warming a session no report on Lucy 4 is waiting for.

So it is a **go-live step**: add Lucy 4 the day its first AppStream report is
routed there, and watch the other three for a morning afterwards.

This does **not** leave Lucy 4 idle or half-built — the readiness gate reads the
**OwnerVille** export, which its own holder keeps warm from day one (§4).

Plus the per-report routing, once real work moves (§6):
`day_orchestrator/schedule_config.json` → `"machine": "Lucy 4"`,
`library_assignments.json`, and each Hub card's `assignees` / `run_machine`
in `automations/hub_cards.py`.

And, once the hostname is known: `automations/machine_digest/run.py:616`
`_machine_label()` maps hostname → label. Lucy 3 is `Lucys-Mac-mini.local` and
Lucy 2 is `Lucys-MacBook-Neo.local`, so *no* "lucy in the hostname" shortcut is
safe. Lucy 4's hostname prints raw until it's added, and the digest will name
the wrong machine to anyone debugging.

> **Still worth doing:** collapse these into one `automations/shared/fleet.py`
> roster with a test that fails when any consumer disagrees with it. Nine
> literals is why three of them went stale, and hand-editing nine files is the
> same bet that lost last time. The prep above buys Lucy 4 a clean start; it
> does not stop Lucy 5 from repeating this.

---

## 4. 🩹 The session holder — install it AND prove it exports

This is the Lucy 3 debut failure in one line: `readiness.session_status()` is a
**machine-global precondition**. The holder-exported
`.ownerville_storage_state.json` must exist **and be under 20 minutes old**, or
*every* report on the box is refused — including reports that never touch
OwnerVille. No holder = a machine that passes every health check and does
nothing, with one buried log line per pass:

```
still trying — no ownerville session yet (.ownerville_storage_state.json missing)
```

`setup_lucy_machine.sh` now installs it in phase 1. Verify it **three ways** —
the Lucy 3 fix was only believed after all three:

```bash
lucy diag --machine "Lucy 4"                     # 1. "OV session: MISSING" must be gone
lucy rerun probe_readiness --machine "Lucy 4"    # 2. must say READY: all sources ready
lucy diag --machine "Lucy 4"                     # 3. run twice more, 6 min apart —
                                                 #    the age must CYCLE (1→5→3 min),
                                                 #    proving the re-export loop is live
```

A one-shot export reads identically at minute 0 and goes stale at minute 20.
Step 3 is the one that distinguishes them.

🩹 **If an agent looks "missing", check disabled first.** `launchctl kickstart`
says *"Could not find service … in domain"* and `bootstrap` says *"Bootstrap
failed: 5: Input/output error"* — neither says the word "disabled", and the
state survives reboots:
```bash
launchctl print-disabled gui/$(id -u) | grep alphalete
launchctl enable gui/$(id -u)/com.alphalete.session-holder
```

---

## 5. Deploy discipline — push is not deploy

Lucy boxes pull **nothing** on their own. No report wrapper runs `git pull`.

```
push → lucy update --machine "Lucy 4" → confirm `done` + read the diffstat → then rerun
```

🩹 A stale runner reproduces its own previous output perfectly, so "the numbers
match" is not proof the new code ran. Put a signal in the check that *must*
change if the new code is live.

🩹 A **brand-new mini_control action** needs one more step — the poller is
long-lived and holds its action registry in memory:
```
push → update → restart_poller → confirm done → enqueue
```

🩹 An **untracked file deadlocks every deploy**: `git pull --ff-only` refuses,
and the runner silently accepts no deploys (Lucy 2 sat 15 commits behind for 11
hours). `git_status`'s "nothing blocking a pull" only inspects *tracked* files.
Never `git clean -fdx` on a runner — it wipes browser profiles and caches.

🩹 **Lucy 4 must be assumed to have no SSH.** Lucy 2 and Lucy 3 both refuse it,
so the Mini Control queue is the only way in. Before relying on a step, check
there is a *queue action* for it — `install_pinned_chrome` exists precisely
because a box with no SSH needed Chrome installed.

🩹 The queue is **one serial worker per lane**. A long report owns the main lane
for hours; the read lane only covers `READONLY_ACTIONS`. **Never queue a
`--force` rerun** — the window check is evaluated when the job *runs*, and three
`--force` rows once drained at midnight and scraped an empty new day.

---

## 6. Going live (only when phases 1–5 are green)

The day-orchestrator is **deliberately not installed** by the setup script —
putting a box on the 4am clock is its own decision:

```bash
lucy rerun install_orchestrator_agent --machine "Lucy 4"
```

Then move work one report at a time:

1. `lucy rerun "<report> --dry-run" --machine "Lucy 4"` — must be clean.
2. One real rerun; confirm the output landed *and* the Hub card published.
3. Only then set `"machine": "Lucy 4"` in `schedule_config.json` (+
   `library_assignments.json` + the Hub card's `assignees`/`run_machine`), so
   the old machine stops running it. Never both — that is a double post.
4. Add the heartbeat entry (§3 #6) the same day, with `watch_from` set to
   tomorrow so it gets one clean 04:20 cycle before it can page.

Each machine emails its own `[Lucy 4]` summary of only its reports, and stays
quiet on days it has none.

---

## 7. Fix the runbook debt while you're here

- `deploy/setup_lucy_machine.sh` — the closing "REQUIRED — SEED OWNERVILLE"
  banner and the in-code comment above `[8/8]` still claim a human must clear
  Cloudflare. Rewrite to match `resources/lucy-login-standard.md`.
- `workflows/setup-new-runner.md` §"What still needs a human" — same.
- `workflows/lucy3-provisioning.md` step 3 — same.
- `automations/day_orchestrator/mini_control.py` line ~3418 docstring says
  "only Lucy 2 and Lucy 3 were ever set up by that script" — extend, don't
  replace, so the history stays readable.

---

## 8. What does NOT move to a new machine

Reasons a report is pinned where it is. Check before routing anything to Lucy 4.

- **iMessage / texting jobs.** The Messages grant is per *identity*, and the
  groups live in one machine's `chat.db`. `alphalete_sales_board_5min` is on
  Lucy 1 because Lucy 3's `chat.db` has none of those groups. A new box's
  Messages grant also needs `deploy/grant_orchestrator_messages.sh` run at the
  screen, with a person clicking Allow.
- **Saved-view reports.** B2B Quality reads Carlos's `CarlosLocalOffice*`
  views; its sort-click lands on Lucy 2's rendering and misses elsewhere, and
  the board posts alphabetical and wrong. Run those on that person's machine.
- **`raffi127@`-scoped sheets.** `funnel_board` is pinned to Lucy 1 for exactly
  this. A share for one Google account says nothing about the other.
- **Tableau budget.** eStream flagged ~10k views/week; the target is <10 logins
  a day. A new box must ride the harvest-once shadow caches, never re-pull.
- **Python 3.9.** Every Lucy is 3.9; this laptop is 3.14. A green local suite
  proves nothing about whether the code *parses* on the runner. The
  `deploy/git-hooks/pre-commit` → `deploy/check_py39.py` hook covers syntax
  only, and only where a real 3.9 exists.
- **Chrome.** Never open human Chrome on the box — it adopts our launches and a
  held profile blocks reports. Bot Chrome runs `--disable-sync`.

---

## 9. Acceptance checklist — Lucy 4 is done when every line is a real observation

```
[ ] lucy diag --machine "Lucy 4"            → answers; sleep LOCKED; agents listed
[ ] agent list matches Lucy 2/3: mini-control, mini-control-read, session-holder,
    keep-awake, orchestrator-schedule-guard (+ day-orchestrator only if §6 ran)
[ ] lucy login_check                        → BOTH OwnerVille and AppStream pass
[ ] lucy sheets_whoami                      → alphaletereporting@, no denials
[ ] lucy slack_whoami                       → lucy_reporting user token
[ ] lucy messages_diag                      → grant held by the identity that runs jobs
[ ] lucy install_pinned_chrome              → done (no SSH means no fallback)
[ ] OV session age CYCLES across 3 diags 6 min apart (not just "present")
[ ] lucy rerun probe_readiness              → READY: all sources ready
[ ] lucy update                             → done + a diffstat matching the commit
[ ] a remote reboot round-trips: machine comes back, auto-login, agents reload
[ ] fleet.py names Lucy 4 and the machine has pulled it (lucy update)
[ ] python -m unittest automations.shared.test_fleet  -> 18 tests, OK
[ ] one real report ran end to end AND published its Hub card
```

At GO-LIVE (§6), three more — none of them before the first report is routed:

```
[ ] morning_clock_since set in fleet.py to TOMORROW's date (it becomes the
    heartbeat's watch_from), and it stamped one real 04:20 beat
[ ] Hub Pack card + MEMBERS entry (Megan's layout call — 4 Lucys break the row of 3)
[ ] office_onboarding_choice flipped in fleet.py (Lucy 3 too — still False)
[ ] holds_appstream + runs_appstream flipped in fleet.py, and both
    test_lucy_4_is_not_a_holder_yet and test_fleet's
    test_lucy_4_is_provisioned_but_not_yet_live deleted — then watch
    Lucy 1/2/3 for one morning: this is the change that can cost the live fleet
```

**Green means delivered.** Exit 0 is not green, a rendered console is not a
token, and an agent that loaded is not an agent that works.
