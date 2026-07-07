# Set up a new runner machine (Lucy N)

How to turn a fresh Mac into an autonomous report runner like Lucy 1 (mini) or
Lucy 2 (laptop). Distilled from the Lucy 2 build (2026-07-07).

**The floor:** only THREE steps truly need a human at the machine — the installer
paste, the Google sign-in, and the ownerville "verify you're human" clear
(Cloudflare + OAuth are bot-detection; they can't be remoted). Everything else is
creds pastes + `install_agent`, and after setup the machine is driven remotely
with `lucy` / `lucy2` / `--machine "<name>"`.

Order matters only loosely; do 1–3 first (they need a person), then the rest can
be finished remotely from your laptop once the poller is up.

## 1. Install (human, at the machine)
Paste in Terminal:
```
curl -fsSL -o ~/Downloads/Install-Recruiting-Report.command https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub/releases/download/v0.1.0/Install-Recruiting-Report.command && bash ~/Downloads/Install-Recruiting-Report.command
```
Installs Python + packages + Chromium + the app. (If a stale venv breaks it:
`rm -rf ~/recruiting-report/.venv` then re-run.)

## 2. Google Sheets sign-in (human, opens a browser)
```
cd ~/recruiting-report && .venv/bin/python -m automations.recruiting_report.sheets_auth
```
Sign in as the account with the sheets this machine writes.

## 3. Creds files (paste the SECRETS at the machine — never via the queue)
Ownerville + AppStream logins (this machine's own accounts):
```
mkdir -p ~/recruiting-report && cat > ~/recruiting-report/ownerville-creds.json <<'JSON'
{
  "ownerville_username": "USER",
  "ownerville_password": "PASS",
  "appstream_username": "USER",
  "appstream_password": "PASS"
}
JSON
chmod 600 ~/recruiting-report/ownerville-creds.json
```
Email app password (for its summary email; same account as the mini works):
```
mkdir -p ~/.config/recruiting-report
printf 'APP_PW_NO_SPACES' > ~/.config/recruiting-report/gmail-app-password
chmod 600 ~/.config/recruiting-report/gmail-app-password
```

## 4. Machine identity + agents
```
cd ~/recruiting-report && git pull --ff-only origin main
printf 'Lucy N' > .machine-profile
.venv/bin/python -m automations.day_orchestrator.install_agent keep-awake
.venv/bin/python -m automations.day_orchestrator.install_agent session-holder
.venv/bin/python -m automations.day_orchestrator.install_agent mini-control
.venv/bin/python -m automations.day_orchestrator.install_agent day-orchestrator
```
The **session-holder** opens a browser → log into ownerville and clear the
**"verify you're human"** check once (step that can't be remoted). AppStream
auto-logs-in (no seed needed).

## 5. Don't-sleep (laptops only)
A laptop sleeps with the lid closed even with caffeinate. One-time:
```
sudo pmset -a disablesleep 1
```
+ keep it on power. **To make sleep remotely toggleable** (`lucy set_sleep 1|0`),
add passwordless sudo for pmset:
```
echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/pmset" | sudo tee /etc/sudoers.d/pmset-nopasswd
sudo chmod 440 /etc/sudoers.d/pmset-nopasswd
```

## 6. Verify (remotely, from your laptop)
```
# health snapshot — sleep lock, loaded agents, OV session age, disk
<repo>/.venv/bin/python -m automations.day_orchestrator.mini_control --machine "Lucy N" --enqueue diag
<repo>/.venv/bin/python -m automations.day_orchestrator.mini_control --machine "Lucy N" --status
```
Add a `lucyN` shell function (mirror of `lucy2`) so you never juggle `--machine`.

## 7. Assign reports to it
For each report that should run on this machine: **dry-run it there first**
(`--machine "Lucy N" --enqueue rerun "<report> --dry-run"`); if clean, tag its
`schedule_config.json` entry `"machine": "Lucy N"` and set the Hub card
`assignees` to `["Lucy N"]`. Lucy 1 (or whoever had it) then skips it — no
double-post. Each machine sends its own `[Lucy N]` summary email of only its
reports and stays quiet on days it has none.

## What still needs a human (irreducible)
- The ownerville **"verify you're human"** clear (step 4) — bot-detection.
- The **Google sign-in** (step 2) — OAuth.
- **sudo** and **secret files** — never routed through the shared control queue.

Everything else — updates, reruns, restarts, health, sleep (with NOPASSWD),
logs — is remote via `lucy` / `lucyN`.
