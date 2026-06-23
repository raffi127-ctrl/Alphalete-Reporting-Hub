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

## Notes
- A run-time trigger only fires if the mini is awake — keep `sudo pmset -c sleep 0` set.
- If the mini is asleep/off at 3am, launchd runs the job at next wake (StartCalendarInterval is catch-up). Keep it awake to fire on time.
- Next up: the **Tableau batch** (daily_metrics, org_sales_board, the weekly OPT
  half) with a data-readiness gate — don't fill on half-refreshed Tableau.
