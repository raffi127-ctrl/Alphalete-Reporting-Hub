# Session Holder — keep ownerville/AppStream warm for unattended runs

**What it is.** `automations/shared/session_holder.py` is the modern version of
the old "Report Chrome" — a browser that stays open holding a logged-in
ownerville session, so scheduled report runs never hit Cloudflare's interactive
"verify you're human" check. A human seeds the login **once**; the holder keeps
that session alive 24/7 and exports the cookies into the storage_state files the
reports reuse (`.ownerville_storage_state.json` / `.appstream_storage_state.json`).

**Why it's needed.** The patchright migration (commits 388e9b0 + e728743) moved
reports off the always-open Report Chrome onto patchright doing its own login,
which Cloudflare challenges. The holder restores the always-open-session model.
**ownerville is the master key** — seeding it covers Tableau AND AppStream
(AppStream SSOs through v2.ownerville).

**The one rule: it must run on a machine that STAYS ON.** A laptop that sleeps
kills it (just like closing Report Chrome used to). The Mac mini is the permanent
home; a laptop works only while awake.

---

## Seed it (once, per machine)
When the holder first starts it opens an ownerville window. **Log in and clear the
Cloudflare box once.** It detects your login passively (no auto-navigation) and
exports. After that it reuses the saved session — no more logins unless the
machine reboots or the session is fully invalidated.

Verify it's warm: `tail -f output/logs/session_holder.out.log` → should print
`warm ✓ — exported …` every interval.

---

## macOS (Mac mini / laptop) — LaunchAgent
A copy of the plist is committed at `deploy/com.alphalete.session-holder.plist`.
Edit the paths in it if the repo isn't at `/Users/<you>/1st Claude Folder`, then:

```bash
cp deploy/com.alphalete.session-holder.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.session-holder.plist
# starts now + at every login; KeepAlive restarts it if it dies
```
Stop / reload:
```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.session-holder.plist
```
Also turn OFF sleep on the mini: System Settings → Energy → "Prevent automatic
sleeping when the display is off" (or `sudo pmset -c sleep 0`).

---

## Windows (Eve's box) — Task Scheduler
Task Scheduler → Create Task:
- **General:** Run only when user is logged on (it needs a visible browser to seed).
- **Triggers:** At log on.
- **Actions:** Start a program →
  - Program: `C:\Users\Eve\recruiting-report\.venv\Scripts\python.exe`
  - Arguments: `-u -m automations.shared.session_holder --interval 6`
  - Start in: `C:\Users\Eve\recruiting-report`
- **Settings:** "If the task fails, restart every 1 minute" + "If the task is
  already running, do not start a new instance."
- Set `PYTHONPATH=C:\Users\Eve\recruiting-report` (system env var) so the module
  resolves.

Keep the machine awake (Power & sleep → Sleep: Never on AC).

---

## Notes
- Holder uses its OWN profile (`.browser_profile_holder`), separate from the
  reports' profile, so it never locks a report run.
- It never drives the login form itself (that hits the Turnstile) — only a human
  seed does. If a session goes stale it alerts in the log + keeps the last good
  cookie file; log back in IN the holder's window.
- `--interval 6` (min) keeps the ownerville session well under its ~20–30 min
  idle timeout. Don't go above ~15.
