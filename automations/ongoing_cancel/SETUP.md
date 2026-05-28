# Ongoing Cancel — one-time Slack setup

This automation (and New Internet Disconnects) posts to **#alphalete-sales**
from the user's **own Slack account** (not a bot). Each teammate creates
their own personal Slack app once + saves the user-token locally. After
that, every run posts as them with zero per-run interaction.

There is **no shared install URL** — each teammate creates their own app
in `api.slack.com/apps`. Takes ~3 minutes.

## What each person does (Megan, Eve, Maud, …)

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**.
2. App name: `Alphalete Hub – <Your First Name>` (e.g. `Alphalete Hub – Eve`).
   Workspace: `ao-pbns`. → **Create App**.
3. Sidebar → **OAuth & Permissions** → scroll to **User Token Scopes**
   (NOT Bot Token Scopes) → click **Add an OAuth Scope** and add all four:
   - `chat:write`
   - `files:write`
   - `channels:history`
   - `groups:history`
4. Scroll back to the top of that same page → **Install to ao-pbns** →
   click **Allow** on the consent screen.
5. You're now back on the OAuth & Permissions page. Copy your
   **User OAuth Token** (starts with `xoxp-...`).
6. Save the token locally using the one-liner for YOUR OS below — both
   prompt for the token so it doesn't end up in your shell history.

### macOS / Linux (zsh or bash)

In Terminal:

```sh
read "TOKEN?Paste your Slack xoxp- token: " && \
  mkdir -p ~/.config/recruiting-report && \
  printf '%s\n' "$TOKEN" > ~/.config/recruiting-report/slack-user-token && \
  chmod 600 ~/.config/recruiting-report/slack-user-token && \
  unset TOKEN && echo "Saved."
```

(On bash, swap `read "TOKEN?…"` for `read -p "…" TOKEN`.)

### Windows (PowerShell)

In PowerShell:

```powershell
$tok = Read-Host -AsSecureString "Paste your Slack xoxp- token"
$dir = "$env:USERPROFILE\.config\recruiting-report"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tok))
# Force UTF-8 without BOM. PowerShell 5.x's Set-Content adds a BOM
# that corrupts the Authorization header at send time.
[System.IO.File]::WriteAllText("$dir\slack-user-token", $plain,
  [System.Text.UTF8Encoding]::new($false))
"Saved to $dir\slack-user-token"
```

That's it. The Hub reads the token on every Ongoing Cancel + New Internet
Disconnects run.

## Pre-flight before each run

A Slack Workflow auto-posts the daily **Metrics** header thread in
#alphalete-sales at 7:00 AM. The Hub replies to that parent thread.
The pre-flight checkbox on the card is a defensive confirmation —
if the workflow ever fails to post, the report will fail too.

## Failure modes

- **"No Slack user token found"** → run the one-liner for your OS above.
- **"Couldn't find today's Metrics header thread"** → the 7 AM workflow
  didn't post. Post it manually (`Metrics for: <Month Day Year>`) and
  click Run Again.
- **"channel_not_found"** → the token's user isn't in #alphalete-sales.
  Get added to the channel, then retry.
- **"Couldn't find the '…' sheet in the Crosstab dialog — saw 0 thumb(s)"**
  → Tableau took longer than expected to load. The report already retries
  once automatically; if you see this error, hit Run Again.
