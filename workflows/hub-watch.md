# Hub change notifications — email Megan on every code/card change

Megan wants an email whenever Hub code or a card changes, from **either** path:

- **Pushed from a Claude session** (commits land on the GitHub repo, bypassing
  the Hub) → `automations/hub_push_watch/run.py`
- **Uploaded through the Hub** (a card published/edited via "Upload Built
  Automation" → the shared "Report Library" Google Sheet) →
  `automations/hub_library_watch/run.py`

Both run as **one** LaunchAgent on the always-on Mac mini
(`com.alphalete.hub-watch`), every 10 minutes, 24/7. The mini is used because it
always has the mail app password **and** the Sheets OAuth token — a teammate's
Hub instance might have neither.

- **From:** `alphaletereporting@gmail.com` (same account as the other Hub emails)
- **To:** `meganhidalgo1191@gmail.com` (set in `automations/shared/hub_notify_email.py`)
- **What's in it:** new card → metadata + code preview; edit → which metadata
  fields changed + a unified code diff; push → each commit's author/subject/files
  + a combined diff.

Marker/snapshot state is **per-machine, outside the repo** (never committed):
`~/.config/recruiting-report/hub-push-watch-last-sha` and
`…/hub-library-watch-state.json`. First run snapshots silently — no backfill
blast. A failed fetch/read/send leaves state untouched, so the next run retries
(no missed changes, no dupes).

## Test locally first (no email sent)
```bash
cd "/Users/megan/1st Claude Folder"     # or ~/recruiting-report on the mini
bash deploy/hub_watch_10min.sh --dry-run
tail -n 40 output/logs/hub-watch-*.log
```
`--dry-run` builds the emails to `output/logs/*.eml` and neither sends nor moves
state. Open a `.eml` to see exactly what would arrive.

## Deploy on the mini (one-time)
The committed plist holds the laptop's path; regenerate it with the mini's path
(same python-replace trick as the other agents — avoids heredoc paste corruption).

```bash
cd ~/recruiting-report
git pull --ff-only origin main            # pull the watchers + wrapper + plist
chmod +x deploy/hub_watch_10min.sh
mkdir -p ~/Library/LaunchAgents output/logs

# Regenerate the plist with the mini's path
python3 -c "import os; src=open(os.path.expanduser('~/recruiting-report/deploy/com.alphalete.hub-watch.plist')).read(); home=os.path.expanduser('~'); src=src.replace('/Users/megan/1st Claude Folder', home+'/recruiting-report'); open(os.path.expanduser('~/Library/LaunchAgents/com.alphalete.hub-watch.plist'),'w').write(src); print('PLIST WRITTEN')"
plutil -lint ~/Library/LaunchAgents/com.alphalete.hub-watch.plist

# Snapshot current state ONCE so the first live run doesn't email a backlog
bash deploy/hub_watch_10min.sh --init
```

## Go live
```bash
launchctl enable gui/$(id -u)/com.alphalete.hub-watch
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.hub-watch.plist
launchctl print gui/$(id -u)/com.alphalete.hub-watch | grep -iE "state|next" | head
```
Fires every 10 min. Logs: `output/logs/hub-watch-*.log` (per-run) and
`output/logs/hub-watch.launchd.{out,err}.log`.

## Reload after a change
```bash
launchctl bootout gui/$(id -u)/com.alphalete.hub-watch 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.hub-watch.plist
```

## Turn it off
```bash
launchctl bootout gui/$(id -u)/com.alphalete.hub-watch
```

## Notes / knobs
- **Recipient:** change `NOTIFY_TO` in `automations/shared/hub_notify_email.py`.
- **Identical re-publishes are silent** — the library watcher compares the card's
  metadata + code, not the upload timestamp. A re-upload with no content change
  won't email. (Change `hub_library_watch/run.py` if you want every publish.)
- **Cadence:** edit the `Minute` entries in the plist (and re-bootstrap).
