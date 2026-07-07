# Hub card snippet — RingCentral Wrap-Up Auto-Read

**For Megan.** Drop the dict below into the `AUTOMATED_REPORTS` list in
`automations/dashboard.py` to add this card to the 🤖 **Fully Automated
Alphalete Reports** bucket. Nothing else in `dashboard.py` needs to change.

- **Module:** `automations/rc_autoread/` (`run.py` is the entry point)
- **What it does:** scans Dylan's RingCentral extension for unread SMS and
  marks a conversation read once it has reached a known wrap-up message —
  unless the customer replied after the wrap-up (those stay unread).
- **Google Sheets:** none. It only talks to the RingCentral API.
- **Safe to re-run any time:** it only flips unread → read, so running it
  twice does nothing the first run didn't already do.

---

## ⚠️ One thing to know about cadence

Dylan wants this to run **every ~10 minutes**. The Hub's `schedule` block is
**display-only**, and the Mac-mini day-orchestrator fires **once each
morning** — so the card alone will **not** produce a 10-minute cadence.

Two ways to get the real cadence (pick one — see Dylan):

1. **Local Windows Task (already running on Dylan's PC).** A scheduled task
   runs `rc_autoread` every 10 min, 7 AM–midnight Central. The Hub card is
   then just a manual **Run Now** button + visibility. No mini changes.
2. **launchd timer on the always-on Mac mini** (if you want it server-side).
   A `StartInterval` job every 600 s calling
   `python -m automations.rc_autoread.run`. This would run under Dylan's
   RingCentral credentials on the mini 24/7 — your call. Ask Dylan/Claude
   for a ready-to-drop `.plist` if you want this route.

The `schedule` field below is set to `daily` purely so the card shows a
sensible "runs automatically" label. If your morning orchestrator
auto-runs scheduled cards, running this one each morning is harmless.

---

## The card dict

```python
    {
        "id": "rc-autoread",
        "name": "RingCentral Wrap-Up Auto-Read",
        "creator": "Dylan",
        "emoji": "📲",
        "color": "#34D399",
        "category": "📲 Ops",
        "description": "Marks RingCentral SMS conversations read once they hit a known wrap-up message (installs, DirecTV/cell hand-offs, fiber reminders), leaving customer-reply threads unread.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Scans the RingCentral extension for **unread SMS** and marks a "
            "conversation read once it has reached a known **wrap-up** "
            "message. Threads where the **customer replied after** the "
            "wrap-up are left unread so a human still sees them.\n\n"
            "WHEN IT RUNS\n"
            "**Every ~10 minutes, 7 AM–midnight Central**, via a background "
            "timer (see the cadence note in resources/rc_autoread/). The "
            "**Run Now** button here triggers an extra pass any time.\n\n"
            "IF A THREAD ISN'T CLEARING\n"
            "Its wrap-up wording probably isn't in the phrase list — add the "
            "phrase to WRAP_UP_PHRASES in automations/rc_autoread/run.py."
        ),
        # No Google Sheet — RingCentral API only.
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Auto-read pass complete — wrapped-up threads marked read, customer-reply threads left unread.",
            "message_failed": "❌ Run failed. Check the log above (usually a RingCentral auth/token or rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Scan the extension and mark wrapped-up threads read.",
                "module": "automations.rc_autoread.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Preview (Dry Run)",
                "icon": "👀",
                "help": "Show which threads WOULD be marked, without changing anything.",
                "module": "automations.rc_autoread.run",
                "args_fn": lambda: ["--dry-run"],
            },
        ],
    },
```
