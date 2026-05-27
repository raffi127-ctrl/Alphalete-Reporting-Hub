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
5. Copy your `User OAuth Token` (starts with `xoxp-...`) → paste into
   the file `~/.config/recruiting-report/slack-user-token` on YOUR Mac:
   ```bash
   mkdir -p ~/.config/recruiting-report
   echo 'xoxp-YOUR-TOKEN-HERE' > ~/.config/recruiting-report/slack-user-token
   chmod 600 ~/.config/recruiting-report/slack-user-token
   ```
6. Sidebar → **Manage Distribution** → **Public Distribution: Activate**
   so teammates can install via a URL. (Optional — if you skip this, you
   can add teammates one-by-one in **Collaborators**.)
7. Copy the **Sharable URL** from Manage Distribution → send to Eve, Maud, etc.

## Each teammate does once (Eve, Maud, …)

1. Open the **Sharable URL** Megan sent → click Install → authorize.
2. After authorizing, the page shows your `User OAuth Token` (`xoxp-...`).
   Paste it into the same file on YOUR Mac:
   ```bash
   mkdir -p ~/.config/recruiting-report
   echo 'xoxp-YOUR-TOKEN-HERE' > ~/.config/recruiting-report/slack-user-token
   chmod 600 ~/.config/recruiting-report/slack-user-token
   ```
3. That's it. The Hub will read the token on every Ongoing Cancel run.

## Pre-flight before each run

**Someone has to post the daily 'Metrics M/DD' header thread in
#alphalete-sales BEFORE this report runs.** The Hub replies to that
parent thread — no header thread = the run fails with a friendly error.

Once all 9 metrics are automated, the Hub will post the header thread
itself and this manual step goes away.

## Failure modes

- **"No Slack user token found"** → run step 5 / step 2 above.
- **"Couldn't find today's Metrics M/DD header thread"** → post the
  header thread first, then click Run Again.
- **"channel_not_found"** → the token's user isn't in #alphalete-sales.
  Get added to the channel, then retry.
