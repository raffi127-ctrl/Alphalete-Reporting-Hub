# Scheduler on the Mac mini — AppStream 3am batch

The mini is the always-on home (see [session-holder-autostart](session-holder-autostart.md)).
Scheduled reports live as macOS LaunchAgents on the mini.

**Ordering principle.** AppStream applicant data is ready well before Tableau
refreshes, so **AppStream-only reports run FIRST at 3am CST**, ahead of the
(later, readiness-gated) Tableau batch. The mini is in CST, so launchd
`Hour = 3` is literally 3am CST — no timezone conversion.

## What the 3am batch runs
`deploy/appstream_morning.sh`:
- **Daily:** Daily Focus — Raf, Daily Focus — Carlos
- **Mondays also:** 1st Round Recruiter Retention

All three are AppStream-only (no Tableau). They need the ownerville session
holder warm — AppStream SSOs through ownerville.

The weekly ATT Program recruiting report stays **combined** (AppStream + Tableau
OPT) on its own Monday schedule — it is NOT part of this batch.

## Deploy on the mini (one-time)
The committed plist holds the laptop's path; regenerate it with the mini's
install path (same python-replace trick as the session holder — avoids the
heredoc paste corruption).

```bash
cd ~/recruiting-report
git pull --ff-only origin main          # pull the wrapper + plist
chmod +x deploy/appstream_morning.sh
mkdir -p ~/Library/LaunchAgents output/logs

# Regenerate the plist with the mini's path
python3 -c "import os; src=open(os.path.expanduser('~/recruiting-report/deploy/com.alphalete.appstream-morning.plist')).read(); home=os.path.expanduser('~'); src=src.replace('/Users/megan/1st Claude Folder', home+'/recruiting-report'); open(os.path.expanduser('~/Library/LaunchAgents/com.alphalete.appstream-morning.plist'),'w').write(src); print('PLIST WRITTEN')"
plutil -lint ~/Library/LaunchAgents/com.alphalete.appstream-morning.plist
```

## TEST before going live (do this first)
Run the batch by hand in dry-run — no writes to the Sheet, no Slack:

```bash
cd ~/recruiting-report
bash deploy/appstream_morning.sh --dry-run
tail -n 40 output/logs/appstream-morning-*.log | tail -40
```

Confirm both Daily Focus runs reached the offices and the numbers look right.

## Go live
```bash
launchctl enable gui/$(id -u)/com.alphalete.appstream-morning
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.appstream-morning.plist
launchctl print gui/$(id -u)/com.alphalete.appstream-morning | grep -iE "state|next" | head
```

Fires at 3:00am CST daily. Logs: `output/logs/appstream-morning-*.log` (per-run)
and `output/logs/appstream-morning.launchd.{out,err}.log`.

## Reload after a change
```bash
launchctl bootout gui/$(id -u)/com.alphalete.appstream-morning 2>/dev/null
# ...re-run the python-replace step if the plist changed...
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.appstream-morning.plist
```

## Noon brand-health social scan (com.alphalete.brand-audit-noon)
Catches new posts/reviews daily at 12:00 Central. Pure API (no browser/session
holder); idempotent (review_history + alerted state dedupe re-runs, so only NEW
findings post). `deploy/brand_audit_noon.sh` runs
`automations.brand_audit.run --company "Alphalete Marketing"` (swap to `--all`
in the wrapper to scan every intake-sheet company).

**Mini prereqs (one-time, sensitive — NOT in git):** copy the whole
`~/.config/brand-audit/` folder from the laptop to the mini, so it has:
- `keys.json` (Google Places / SerpAPI / Anthropic / Slack tokens) — required
- the state files (`alerted.json`, `review_history.json`, …) — so the first mini
  run doesn't re-alert every existing finding or reset the review deltas

```bash
# from the laptop (example — adjust host):
#   scp -r ~/.config/brand-audit/  alphalete@<mini>:~/.config/
# or AirDrop / USB the folder to ~/.config/brand-audit/ on the mini
```

Deploy + test + go-live (same shape as the 3am batch):
```bash
cd ~/recruiting-report
git pull --ff-only origin main
chmod +x deploy/brand_audit_noon.sh
python3 -c "import os; src=open(os.path.expanduser('~/recruiting-report/deploy/com.alphalete.brand-audit-noon.plist')).read(); home=os.path.expanduser('~'); src=src.replace('/Users/megan/1st Claude Folder', home+'/recruiting-report'); open(os.path.expanduser('~/Library/LaunchAgents/com.alphalete.brand-audit-noon.plist'),'w').write(src); print('PLIST WRITTEN')"
plutil -lint ~/Library/LaunchAgents/com.alphalete.brand-audit-noon.plist
# TEST FIRST (no Slack/sheet writes):
bash deploy/brand_audit_noon.sh --dry-run
ls -t output/logs/brand-audit-noon-*.log | head -1 | xargs tail -n 40
# GO LIVE:
launchctl enable gui/$(id -u)/com.alphalete.brand-audit-noon
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.brand-audit-noon.plist
```

## 6am weather alert (com.alphalete.weather-6am)
Friendly daily forecast for the Frisco, TX team → `#alphalete-sales`, posted at
6am Central (just before the 7am metrics thread). `automations/weather_alert/run.py`:
Open-Meteo forecast (no key) → Claude writes the warm prep blurb (umbrella / layers
/ sunscreen / water) → posts to #alphalete-sales. Template fallback if Claude is
unavailable, so it never hard-fails. `deploy/weather_alert_6am.sh`.

Deploy + test + go-live:
```bash
cd ~/recruiting-report
git pull --ff-only origin main
chmod +x deploy/weather_alert_6am.sh
python3 -c "import os; src=open(os.path.expanduser('~/recruiting-report/deploy/com.alphalete.weather-6am.plist')).read(); home=os.path.expanduser('~'); src=src.replace('/Users/megan/1st Claude Folder', home+'/recruiting-report'); open(os.path.expanduser('~/Library/LaunchAgents/com.alphalete.weather-6am.plist'),'w').write(src); print('PLIST WRITTEN')"
plutil -lint ~/Library/LaunchAgents/com.alphalete.weather-6am.plist
bash deploy/weather_alert_6am.sh --dry-run   # prints the message, no post
ls -t output/logs/weather-6am-*.log | head -1 | xargs tail -n 20
# GO LIVE:
launchctl enable gui/$(id -u)/com.alphalete.weather-6am
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.weather-6am.plist
```

## SHARED mini prereq — Slack user token
Any job that POSTS to Slack (weather alert, brand audit, the 3am daily-focus Slack
summary) reads `~/.config/recruiting-report/slack-user-token` (an `xoxp-` token).
The fresh mini won't have it — copy it from the laptop ONCE:
```bash
# from the laptop (AirDrop the file, or over SSH/Tailscale):
#   scp ~/.config/recruiting-report/slack-user-token alphalete@<mini>:~/.config/recruiting-report/
# on the mini, make sure the dir exists first:  mkdir -p ~/.config/recruiting-report
```
Also needed for the Anthropic-written weather wording: `~/.config/brand-audit/keys.json`
(same file the brand audit uses). Without it the weather post still works via the
plain template.

## Day orchestrator — the readiness-gated Tableau batch (com.alphalete.day-orchestrator)

The "Tableau batch with a data-readiness gate" that was the next-up item. ONE
resident process, launched once at 4am CST, that owns the whole day's Tableau
reports: it probes each source for readiness (today's rows actually present — not
a clock time), runs what's ready, **circles back every 25 min**, emails a 7:30
checkpoint, keeps retrying to a **noon backstop**, then emails a final summary.
It **reconciles** by re-reading the sheet (never trusts exit 0) and **fails
closed** if the ownerville session is stale (skips + alerts to re-seed, never
writes garbage). Code: `automations/day_orchestrator/` · design:
`output/day-orchestrator-design.md` (laptop only — output/ is gitignored).

Scope: runs the unscheduled Tableau metrics (daily_metrics, captainship_churn,
owners_metrics_churn, fiber_activations, daily_rep_breakdown, + weekly int_wow /
country / leaders_call). EXCLUDES org_sales_board (deferred). Upload-gated reports
stay MANUAL. The 3 jobs above stay standalone — the orchestrator only reads their
status for the summary. Knobs live in
`automations/day_orchestrator/schedule_config.json` (cadence / priority / freshness
target) — edit by hand; they're tuned during the dry-run week.

### Mini prereq — Gmail app password (for the summary emails)
The checkpoint + final emails send from `alphaletereporting@gmail.com` over Gmail
SMTP, reusing the scheduled_6_days_out path. It reads a 16-char **App Password**
(needs 2-Step Verification on that account) from
`~/.config/recruiting-report/gmail-app-password` (one line). Without it, reports
still run + reconcile — only the email send fails (logged, non-fatal). The
*email-reply* STOP path also needs `~/.config/recruiting-report/gmail-token.json`
(authorize once: `python -m automations.shared.gmail_auth` as alphaletereporting@);
the CLI `stop` works without it. Slack token + warm session holder are already on
the mini.

### Deploy
```bash
cd ~/recruiting-report
git pull --ff-only origin main
chmod +x deploy/day_orchestrator.sh
```

### TEST by hand first (no writes, no real email)
```bash
bash deploy/day_orchestrator.sh --dry-run --simulate --once   # offline: loop/email/control wiring
bash deploy/day_orchestrator.sh --dry-run --once              # real Tableau pulls, no writes/email
ls -t output/logs/day-orchestrator-*.log | head -1 | xargs tail -40
# checkpoint/final emails are written as .eml under output/orchestrator_emails/ in dry-run
```

### Install for the DRY-RUN WEEK (runs alongside the live jobs, writes nothing)
Uses `plistlib` (not a heredoc paste) to fix the path AND append `--dry-run`:
```bash
python3 - <<'PY'
import os, plistlib
home=os.path.expanduser('~'); root=home+'/recruiting-report'
pl=plistlib.load(open(root+'/deploy/com.alphalete.day-orchestrator.plist','rb'))
fix=lambda s: s.replace('/Users/megan/1st Claude Folder', root)
pl['ProgramArguments']=[fix(x) for x in pl['ProgramArguments']]
pl['WorkingDirectory']=fix(pl['WorkingDirectory'])
pl['EnvironmentVariables']={k:fix(v) for k,v in pl['EnvironmentVariables'].items()}
pl['StandardOutPath']=fix(pl['StandardOutPath']); pl['StandardErrorPath']=fix(pl['StandardErrorPath'])
pl['ProgramArguments'] += ['--dry-run', '--live-emails']   # DRY-RUN WEEK: reports
# write NOTHING, but the checkpoint/final summary emails SEND for real so Megan +
# Eve actually receive them each morning to evaluate. Drop --live-emails to keep
# emails as .eml files on the mini instead.
out=home+'/Library/LaunchAgents/com.alphalete.day-orchestrator.plist'
plistlib.dump(pl, open(out,'wb')); print('wrote', out)
PY
plutil -lint ~/Library/LaunchAgents/com.alphalete.day-orchestrator.plist
launchctl enable gui/$(id -u)/com.alphalete.day-orchestrator
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.day-orchestrator.plist
```
Fires 4am CST daily; each report runs in its own `--dry-run` (no sheet writes),
and you + Eve get the real checkpoint/final summary emails. Watch them +
`output/logs/day-orchestrator-*.log` for ~a week; tune `schedule_config.json`.

### Stop a stuck report (phone or terminal)
```bash
# terminal:
python -m automations.day_orchestrator.control stop  country_metrics
python -m automations.day_orchestrator.control resume country_metrics
# phone: reply to the checkpoint email with subject  STOP <report_id>
```

### BEFORE going live (wire these — all marked _todo in schedule_config.json)
1. The 5 Tableau **source probes** (view_url + crosstab_sheet + date_col). Until
   wired, a `not_configured` probe is READY in dry-run but NOT-READY in live —
   on purpose, so live can't run an unprobed source.
2. **`verify`** per report (sheet/tab/anchor_label/date_header, or manifest) — else
   reports show "DONE (unverified)".
3. **Idempotency guards** on `int_wow_penetration` + `country_metrics` (insert-a-week
   reports — a retry must not double-insert today's column).

### GO LIVE (after the dry-run week)
Re-run the `plistlib` block above **without** the
`pl['ProgramArguments'].append('--dry-run')` line, then reload:
```bash
launchctl bootout gui/$(id -u)/com.alphalete.day-orchestrator 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.day-orchestrator.plist
launchctl print gui/$(id -u)/com.alphalete.day-orchestrator | grep -iE "state|next" | head
```

## Notes
- A run-time trigger only fires if the mini is awake — keep `sudo pmset -c sleep 0` set.
- If the mini is asleep/off at 3am, launchd runs the job at next wake (StartCalendarInterval is catch-up). Keep it awake to fire on time.
- The **Tableau batch** is the day orchestrator above (built 2026-06-23) — readiness-gated so it never fills on half-refreshed Tableau. org_sales_board is still excluded until its sandbox→`--real` fix.
