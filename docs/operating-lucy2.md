# Operating Lucy 2 (and the Alphalete Reporting Hub) — field manual

You (Claude Code) run on Carlos's **Mac mini** (dev/control box). Automations RUN on
a separate machine, **Lucy 2** (Carlos's MacBook). GitHub is the code hub; Google
Sheets hold report data AND the remote-control channel to Lucy 2. Read this fully
before touching anything; when in doubt, read the files named below.

---

## Topology

- **Mac mini** (you are here): git push rights, Google auth, service creds/sessions.
  Repo `/Users/carloshidalgo/recruiting-report`, python `.venv/bin/python`.
- **Lucy 2** (MacBook): runs scheduled automations. Repo `/Users/lucy2/recruiting-report`,
  python `.venv/bin/python3.9`. Reachable ONLY through the sheet queue below — no SSH.
- **GitHub**: `raffi127-ctrl/Alphalete-Reporting-Hub`. mini → GitHub → Lucy 2.
- **Google Workspace**: report output sheets + the Lucy-2 command queue sheet.

## The one rule of Lucy 2

You never touch Lucy 2 directly. You append a **row to a Google Sheet**; a launchd
poller on Lucy 2 (`com.alphalete.mini-control`, KeepAlive) reads it ~every 120s,
runs the whitelisted action, and writes the result back. Always use the mini venv
python (has Google auth + repo): `/Users/carloshidalgo/recruiting-report/.venv/bin/python`.

### Queue a command

```python
import datetime
from automations.recruiting_report import fill as _fill
SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
ws = _fill._client().open_by_key(SHEET).worksheet("Mini Control - Lucy 2")
now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
ws.append_row([now, "ping", "", "Claude", "queued", "", ""], value_input_option="RAW")
```

Columns: `[Queued At, Action, Args, By, Status, Result, Finished At]`. Status must be
`queued`. Use `value_input_option="RAW"` so args aren't reformatted.

### Wait for the result (poll by ROW NUMBER, not timestamp)

```python
import time
target = len(ws.get_all_values())          # the row you just appended
for _ in range(30):                        # ~6 min budget
    r = (ws.row_values(target) + [""]*7)[:7]
    if r[4] in ("done", "failed"):
        print(r[4], "::", r[5]); break     # r[5] = Result
    time.sleep(12)
```

Do the waiting in a background task; read the output when it completes.

### Whitelisted actions (`automations/day_orchestrator/mini_control.py`)

| Action | Args example | Effect |
|---|---|---|
| `ping` | — | liveness (pong ~2 min) |
| `update` | — | `git pull --ff-only` on Lucy 2's current branch |
| `rerun` | `resume_pushing` | run a registered report; `install_<x>_agent` loads a launchd agent |
| `logtail` | `resume-pushing finished 30` | READ `output/logs/*name*`, grep, last N lines |
| `screendrive` | `--cdp-run --extract-only` | runs `python -m automations.resume_pushing.run <args>` |
| `diag` | — | host/sleep/power/disk (⚠️ "agents" line only lists 4 hardcoded names) |
| `restart_holder` / `restart_poller` | — | kick the session-holder / poller |
| `restart_hub` | — | bounce the cached Streamlit Hub (deploy/restart_hub_if_running.sh; no-op if no Hub on :8501) |
| `set_sleep` | `1` | prevent sleep |
| `pip_install` | `reportlab` | reportlab only |

Add a new capability by adding a whitelisted action (keep it safe — no arbitrary shell).

### Reading rich output

The `Result` cell truncates (~470 chars). Have the Lucy-2 code write to a dedicated
sheet TAB and read it from the mini:

```python
for row in _fill._client().open_by_key(SHEET).worksheet("RP Diag").get_all_values():
    print(row[0])
```

Screenshots: Lucy-2 code base64-chunks a PNG into a tab (`RP Shot`, 45000-char cells);
decode on the mini:

```python
import base64
chunks = [c[0] for c in _fill._client().open_by_key(SHEET).worksheet("RP Shot").get_all_values() if c and c[0]]
open("/tmp/shot.png","wb").write(base64.b64decode("".join(chunks)))   # then Read /tmp/shot.png
```

## GitHub access

Both machines have clones with origin = the repo. From the mini you can commit +
push. `main` is canonical; do WIP on a branch and promote when verified.

⚠️ **Lucy 2's checkout tracks `resume-pushing-v2`, NOT main** (discovered
2026-07-15 after a full day of silent "Already up to date" no-op updates —
mine AND another session's). Pushing main alone never reaches Lucy 2.
**Since 2026-07-18 the branches CONVERGED** (main contains every
resume-pushing-v2 commit — screendrive, the extension loader), so delivery
is now a plain fast-forward push; the old merge-worktree dance is only
needed again if the branches ever diverge (the push below would then be
rejected non-ff — do NOT force; merge instead). Symptom check: an `update`
result showing a fetch delta followed by "Already up to date" means the
tracking branch didn't move. Long-term fix: check Lucy 2 out on main at the
laptop, then delete this warning.

```bash
cd /Users/carloshidalgo/recruiting-report
git add path/to/file.py            # never `git add .` blindly
git commit -m "..."
git pull --rebase origin main      # teammates push too — rebase first
git push origin main
git push origin main:resume-pushing-v2   # deliver to Lucy 2 (ff since 7/18)
# then queue `update`; plus `restart_poller` if mini_control.py changed,
# `restart_hub` if dashboard.py changed (see The Hub below).
# promote just one file from a branch without dumping the whole branch:
git checkout <branch> -- path/to/file
```

## Logging into services (AppStream/Ownerville, Tableau)

You almost never type a password. Creds live as JSON at the repo root (read by
`automations/shared/creds.py`); sessions persist as Playwright storage_state JSON in
`automations/shared/` and are kept warm by `com.alphalete.session-holder`. Helpers in
`automations/shared/tableau_patchright.py` reuse the session and, if stale, re-drive the
login form with creds (Cloudflare auto-passes). One-time seed on a fresh machine /
expired session: `python -m automations.shared.tableau_patchright --appstream-login`
(opens a browser, clear Cloudflare + log in once, saves the session). **Never hardcode
or echo secrets; never type passwords into forms yourself — use the seed flow / stored
session.**

## Driving browsers on Lucy 2

- Normal sites: patchright (stealth Playwright) via the session helpers.
- Sites needing a Chrome **extension**: patchright CANNOT run it (service worker never
  starts; site sees it as not-installed). Instead drive a REAL Google Chrome over CDP:
  copy the everyday Default profile to a NON-default `--user-data-dir` (Chrome 136+ blocks
  the debug port on the real default dir), launch real Chrome with `--remote-debugging-port`,
  `connect_over_cdp`, log in (inject saved cookies → form-login fallback), drive it. CDP
  clicks are trusted DOM events needing ZERO macOS Accessibility → runs unattended from
  launchd. Shadow-DOM popups are invisible to `querySelectorAll` — walk `shadowRoot`.
  Worked example: `automations/resume_pushing/run.py` (`_cdp_run`, `_copy_default_profile`,
  `_shadow_find`).

## The Hub (Streamlit dashboard)

`automations/dashboard.py`, served on :8501 on Lucy 2. Caches code in memory with the
file watcher OFF, so after new code lands it must be bounced: queue **`restart_hub`**
(wraps `deploy/restart_hub_if_running.sh`; no-op when no Hub holds :8501). Do NOT count
on the git post-merge hook — hooks are local artifacts and Lucy 2's clone doesn't have
it (bit us 2026-07-18: card pulled, Hub kept serving stale code). The "This week"
calendar reads each report's `schedule` dict (`frequency: "weekly"` + `weekdays`
filters days; `"daily"` shows all 7; past days without a recorded run show as missed
and never backfill). dashboard.py is Megan's — minimal, targeted edits only.

## New-automation checklist

1. Build `automations/<name>/run.py` with `main()` + a `--dry-run` gate; reuse shared
   session helpers; test on the mini with `--dry-run`.
2. Register it in `automations/day_orchestrator/schedule_config.json` (id + command).
3. If it runs on its own timer: `deploy/<name>.sh` (window/day gate, e.g. `date +%u -eq 6`
   skips Saturday) + `deploy/com.alphalete.<name>.plist` + an `install_<name>_agent` path.
4. Optional Hub card: a report dict in `dashboard.py` (`schedule` = weekly + weekdays).
5. Ship: commit/push (BOTH branches, see GitHub access) → queue `update` → queue
   `rerun <id> --dry-run` → then `rerun install_<name>_agent` to arm the timer →
   `restart_hub` if you added a card.
6. **Verify by log** (`logtail <name> finished 30`), not by success messages. Gate
   irreversible sends behind `--dry-run`/`--limit 1` until log-verified.

**Worked example — vantura_churn daily 7am (shipped 2026-07-18):** module
`automations/vantura_churn/` (direct authenticated Tableau export with the UI
dance as fallback; reconcile-or-fail gate) + `deploy/vantura_churn_daily.sh`
(755, pgrep guard) + `deploy/com.alphalete.vantura-churn-daily.plist` (daily
7:00, no Weekday key = all 7 days) + `install_vantura_churn_agent` entry in
schedule_config + a card in dashboard.py. Shipped exactly per steps 5-6:
push both branches → `update` → `rerun vantura_churn --dry-run` (log-verified
incl. reconciliation) → `rerun install_vantura_churn_agent` (launchctl-verified)
→ `restart_hub`. Diagnostics channel: probe output → "Vantura Diag" tab,
screenshots → "Vantura Shot" (base64), decoded on the mini.

## Gotchas & safety (learned the hard way)

- **~2 min latency** per queued command. Batch; wait in the background.
- **The poller is single-threaded** — a long `screendrive`/`rerun` (up to ~25 min) BLOCKS
  every other queued row until it returns.
- **`diag` can't confirm your agent** — its "agents:" line only greps 4 hardcoded labels
  (keep-awake, session-holder, mini-control, day-orchestrator). To confirm any other agent
  is loaded/firing, **read its log** with `logtail` — never trust diag or a "loaded ✓" msg.
- **Verify deploys by reading the run log**, not success messages.
- **Sends/deletes are irreversible** — gate behind `--dry-run`/`--limit 1` and log-verify
  before enabling a full schedule.
- macOS TCC: the launchd poller is NOT Accessibility-trusted, so OS-level synthetic clicks
  are silent no-ops from it — that's why browser-level CDP clicks are the way.
- **A dirty tree on Lucy 2 blocks EVERY `update`** ("Please commit your changes or
  stash them… Aborting"). Usual cause: `install_agent` chmod +x'ing a wrapper whose
  exec bit differs from git. There is deliberately NO remote heal — someone at the
  laptop runs `git -C /Users/lucy2/recruiting-report checkout -- deploy/` once
  (broad on purpose: any one dirty wrapper blocks, and the heal only restores
  tracked files to their committed state). Prevented going forward by d988af5
  (all deploy/*.sh committed 755).
- **A NEW poller action doesn't exist until the poller restarts** — the poller is a
  long-lived process. Ship order: push → `update` → `restart_poller` → then the
  new action works.

## Orient on a fresh device (do this first)

1. `git -C /Users/carloshidalgo/recruiting-report status` — confirm repo + branch.
2. Confirm sheet access: `_fill._client()` opens a sheet without error.
3. Confirm the Lucy 2 poller is alive: queue `ping`, expect a pong in ~2 min.
4. Read the four files that teach the system: `mini_control.py` (queue),
   `tableau_patchright.py` (sessions/login), `schedule_config.json` (jobs),
   `dashboard.py` (Hub).
