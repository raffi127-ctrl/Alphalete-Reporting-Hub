# Hub card snippet — Disconnect / Cancel Feedback Log

**For Megan.** Drop the dict below into the `AUTOMATED_REPORTS` list in
`automations/dashboard.py`. Nothing else in `dashboard.py` needs to change.

- **Module:** `automations/disconnect_followup/` (`run.py` is the entry point)
- **What it does:** Dylan texts AT&T-fiber customers who cancelled/disconnected
  asking for feedback (sent from Salesforce, lands in RingCentral). This scans
  RingCentral and, once a customer replies, writes the whole conversation that
  follows the inquiry (both sides, minus the inquiry itself) into the **feedback
  column of that customer's row** in the `AT&T Fiber Metrics Report` sheet.
- **Tabs written:** Local Office - Daily Cancels (`Cancel Feedback`), Local
  Office - New Internet Disconnects (`Disconnects Feedback`), Raf's Captainship -
  Cancels Ongoing (`Cancels Feedback`), Raf's Captainship - New Internet
  Disconnects (`DISCONNECTS FEEDBACK`).
- **Safe to re-run:** idempotent — it only re-applies the current replies to the
  matched customer's feedback cell. It never touches other rows/columns.
- **No Tableau/patchright** — reads the daily-refreshed source sheet + the
  RingCentral API, so it runs anywhere with the Sheets token + RC creds.

---

## Notes

- **On-demand, not scheduled.** Dylan runs it after sending a batch of feedback
  texts. There's deliberately no `schedule` block — assignee is
  **Office Operations**. If you ever want it unattended on the mini, move the
  assignee to **Lucy 1** and add a `schedule`.
- **Matching is by phone**, and the module handles the source sheet's per-row
  column shift (some rows sit one column left of the header).
- **Watch the daily refresh:** written feedback stays with its row as long as the
  refresh *inserts* rows. If a tab ever gets cleared/rebuilt, just run the card
  again — it re-applies every current reply.

---

## The card dict

```python
    {
        "id": "disconnect-followup",
        "name": "Disconnect / Cancel Feedback Log",
        "creator": "Dylan",
        "emoji": "💬",
        "color": "#F59E0B",
        "category": "🎯 Fiber",
        "description": "Logs customer replies to the cancel/disconnect feedback texts straight into the feedback columns of the AT&T Fiber Metrics Report.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Dylan texts fiber customers who **cancelled** or **disconnected** "
            "asking why. This scans RingCentral and, once a customer has "
            "**replied**, writes the whole conversation after that first text "
            "(both sides — Dylan's follow-ups and the customer's) into the "
            "**feedback column of the customer's row** on the AT&T Fiber "
            "Metrics Report.\n\n"
            "WHEN IT RUNS\n"
            "**On demand** — run it after sending a batch of feedback texts, "
            "then again later as replies come in. Safe to re-run any time.\n\n"
            "WHAT IT WON'T DO\n"
            "**•** It never logs the initial feedback text itself.\n"
            "**•** It logs nothing until the customer actually replies.\n"
            "**•** It only writes the matched customer's feedback cell.\n\n"
            "IF A REPLY ISN'T SHOWING\n"
            "The customer's number must match a row in one of the four office "
            "tabs, and the reply must be inside the look-back window "
            "(`--days`, default 7). Widen it with the **Look Back 14 Days** "
            "button."
        ),
        "sheet_url": "https://docs.google.com/spreadsheets/d/1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8/edit",
        "assignees": ["Office Operations"],
        "checklist": [],
        "post_run": {
            "message_success": "✅ Replies logged into the feedback columns on the AT&T Fiber Metrics Report.",
            "message_failed": "❌ Run failed. Check the log above (usually a RingCentral auth/rate-limit or a Sheets permission issue), then run again.",
        },
        "actions": [
            {
                "label": "Log Replies",
                "icon": "▶",
                "primary": True,
                "help": "Scan RingCentral and write any customer replies into the feedback columns.",
                "module": "automations.disconnect_followup.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Preview (Dry Run)",
                "icon": "👀",
                "help": "Show which replies WOULD be written, and where, without changing anything.",
                "module": "automations.disconnect_followup.run",
                "args_fn": lambda: ["--dry-run"],
            },
            {
                "label": "Look Back 14 Days",
                "icon": "🔁",
                "help": "Same as Log Replies, but scans a 14-day RingCentral window (slower) to catch older replies.",
                "module": "automations.disconnect_followup.run",
                "args_fn": lambda: ["--days", "14"],
            },
        ],
    },
```
