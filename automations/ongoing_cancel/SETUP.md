# Ongoing Cancel — one-time Slack setup

This automation posts to **#alphalete-sales** from the user's **own Slack
account** (not a bot). Each teammate has to install a small Slack app
once + save their personal user-token locally. After that, every run posts
as them with zero per-run interaction.

## Megan does once (workspace owner)

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**.
2. App name: `Alphalete Hub – Metrics Poster`. Workspace: `ao-pbns`.
3. Sidebar → **OAuth & Permissions** → scroll to **User Token Scopes**
   (not Bot Token Scopes) → add:
   - `chat:write`
   - `files:write`
   - `channels:history`
   - `groups:history`
4. Top of that page → **Install to Workspace** → authorize.
5. Copy your `User OAuth Token` (starts with `xoxp-...`) → save it
   following the one-liner for YOUR OS below.
6. Sidebar → **Manage Distribution** → **Public Distribution: Activate**
   so teammates can install via a URL. (Optional — if you skip this, you
   can add teammates one-by-one in **Collaborators**.)
7. Copy the **Sharable URL** from Manage Distribution → send to teammates.

## Each teammate does once (Eve, Maud, …)

1. Open the **Sharable URL** Megan sent → click Install → authorize.
2. After authorizing, the page shows your `User OAuth Token` (`xoxp-...`).
3. Save it locally using the one-liner for YOUR OS below.

### macOS / Linux (zsh or bash)

Paste this in Terminal — it prompts for the token so it doesn't end up
in your shell history:

```sh
read "TOKEN?Paste your Slack xoxp- token: " && \
  mkdir -p ~/.config/recruiting-report && \
  printf '%s\n' "$TOKEN" > ~/.config/recruiting-report/slack-user-token && \
  chmod 600 ~/.config/recruiting-report/slack-user-token && \
  unset TOKEN && echo "✅ Saved."
```

(On bash, swap `read "TOKEN?…"` for `read -p "…" TOKEN`.)

### Windows (PowerShell)

Paste this in PowerShell — it masks the token as you paste it:

```powershell
$tok = Read-Host -AsSecureString "Paste your Slack xoxp- token"
$dir = "$env:USERPROFILE\.config\recruiting-report"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
[Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tok)
) | Set-Content -NoNewline "$dir\slack-user-token"
"✅ Saved to $dir\slack-user-token"
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
  didn't post (or post it manually as `Metrics for: <Month Day Year>`),
  then click Run Again.
- **"channel_not_found"** → the token's user isn't in #alphalete-sales.
  Get added to the channel, then retry.
