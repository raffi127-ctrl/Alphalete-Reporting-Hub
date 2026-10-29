# Check-In Bot

A personal Slack agent that fills out your daily fitness check-in sheet for
you:

| When (local time) | It does | Sheet column |
|---|---|---|
| 4:30 am | DMs you *"What was your weigh-in today?"* — you reply with a number | AM Body Weight (G) |
| 9:00 pm | DMs you *"How many steps are you at?"* — you reply with a number | Daily Steps (V) |
| 9:00 pm | DMs you *"Did you work out today?"* with **Upper / Lower / Push / Pull / Legs / Off** buttons | Body Part Trained (O) |
| 11:00 pm | *(optional)* pulls your MyFitnessPal diary totals automatically | Protein / Carbs / Fat (J/K/L) |

Every answer is written to **today's date row** (it matches the date in
column F, format `M/D/YY`). If your pre-filled dates run out, the weigh-in
adds new date rows automatically.

Your sheet tab must be laid out like the original: **F**=Date,
**G**=AM Body Weight, **J/K/L**=Protein/Carbs/Fat, **O**=Body Part Trained,
**V**=Daily Steps. Different layout? Override any column number in `.env`
(e.g. `COL_STEPS=20`).

---

## Setup (~15 minutes)

You need Python 3.10+ and a computer that stays on (or wakes) at the
check-in times — a Mac mini, home server, or always-on laptop.

### 1. Slack app (5 min)

1. Go to https://api.slack.com/apps → **Create New App** → **From a
   manifest** → pick your workspace → paste the contents of
   `slack-manifest.yaml` → Create.
2. **Basic Information → App-Level Tokens** → Generate token with the
   `connections:write` scope → copy the `xapp-…` token.
3. **Install App** → Install to Workspace → copy the **Bot User OAuth
   Token** (`xoxb-…`).
4. Get your own Slack member ID: your profile → **⋯** → **Copy member ID**
   (`U…`).

### 2. Google service account (5 min)

1. Go to https://console.cloud.google.com → create a project (any name).
2. **APIs & Services → Enable APIs** → enable **Google Sheets API** and
   **Google Drive API**.
3. **APIs & Services → Credentials → Create Credentials → Service
   account** → any name → Done.
4. Open the service account → **Keys → Add key → JSON** → download it →
   save it in this folder as **`google-creds.json`**.
5. Open the JSON, copy the `client_email` (…@…iam.gserviceaccount.com),
   and **share your check-in Google Sheet with that email as Editor**.

### 3. Run it

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python checkin_bot.py
```

First run asks for your tokens, member ID, and sheet URL, and writes them
to `.env`. After that it just runs.

Test it immediately by DMing the bot: `test weighin`, `test steps`,
`test workout` — each fires the corresponding question right now. You can
also log without being asked: `weigh in 186.4`, `steps 12500`,
`workout push`, `macros`.

### 4. Keep it running (macOS)

Create `~/Library/LaunchAgents/com.you.checkinbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.you.checkinbot</string>
  <key>ProgramArguments</key><array>
    <string>/FULL/PATH/TO/checkin-bot/venv/bin/python</string>
    <string>/FULL/PATH/TO/checkin-bot/checkin_bot.py</string>
  </array>
  <key>WorkingDirectory</key><string>/FULL/PATH/TO/checkin-bot</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/checkinbot.log</string>
  <key>StandardErrorPath</key><string>/tmp/checkinbot.log</string>
</dict></plist>
```

Then `launchctl load ~/Library/LaunchAgents/com.you.checkinbot.plist`.
(Don't put the folder in `~/Desktop` or `~/Documents` — macOS blocks
launchd from reading those. `~/checkin-bot` works.)

On Linux, an equivalent systemd user service works the same way.

### Optional: MyFitnessPal sync

Say **y** at setup (or set `ENABLE_MFP=1` in `.env`), and make sure you're
logged in at myfitnesspal.com **in Chrome on this machine**. Heads-up: MFP
has no public API, so this uses an unofficial scraper that reads your own
Chrome session — it can break when MFP redesigns their site. If the diary
is empty that day, the sheet is left untouched.

### Custom times / columns

Add to `.env`:

```
WEIGHIN_TIME=04:30
EVENING_TIME=21:00
MFP_TIME=23:00
COL_STEPS=22        # any column override, 1-based (A=1, B=2, …)
```
