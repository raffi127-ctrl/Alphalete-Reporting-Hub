# Hub card snippet — Raf Wrap-Up Check (RingCentral)

**For Megan.** Drop the dict below into the `AUTOMATED_REPORTS` list in
`automations/hub_cards.py` (right after the **B2B Customer Contacts** card is
the natural home — this is its twin for Raf's office). Nothing else needs to
change.

- **Module:** `automations/rc_contact_sync_raf/` (`run.py` is the entry point)
- **What it does:** mirror of **B2B Customer Contacts (RingCentral)**, but for
  **Raf's office** and checked against **Dylan's** RingCentral line (the same
  account `rc_autoread` uses). For every sale under Raf's SaraPlus code
  yesterday (**all reps**), it asks "was this customer ever messaged on
  Dylan's line?" and posts the ones who weren't — grouped by rep — to
  **#alphalete-sales**.
- **No contacts are created.** Dylan's RingCentral app can read messages but
  does not hold the `ReadContacts` scope, so this twin does the wrap-up check
  and the Slack post only. (Carlos's version also writes contacts; to light
  that up here, add `ReadContacts` + `Contacts` to Dylan's RingCentral app and
  re-mint the JWT — no code change needed.)
- **Google Sheets:** none for output. It reads Raf's order export off the
  control sheet (handed over from Lucy 1) and talks to the RingCentral API.

---

## ⚠️ Two steps, one box (Lucy 1)

Unlike the B2B card (Lucy 2), this runs entirely on **Lucy 1**, because Raf's
SaraPlus login + verified profile live there (no emailed-passcode step). The
morning flow is two commands, in order:

1. `python -m automations.rc_contact_sync_raf.pull_raf --pull`  — pulls Raf's
   full Sales Order History and hands it to the control sheet.
2. `python -m automations.rc_contact_sync_raf.run --live`  — the wrap-up check
   + the Slack post.

See `resources/rc_contact_sync_raf/RUNBOOK.md` for the schedule wiring. The
`schedule` field below is display-only.

---

## The card dict

```python
    {
        "id": "rc-contact-sync-raf",
        "name": "Raf Wrap-Up Check (RingCentral)",
        "creator": "Dylan",
        "emoji": "📞",
        "color": "#60A5FA",
        "category": "📊 Metrics",
        "description": "For every sale under Raf's SaraPlus code yesterday (all reps), checks whether the customer was ever texted on Dylan's RingCentral line, and posts the ones who weren't — grouped by rep — to #alphalete-sales. The B2B Customer Contacts report, mirrored for Raf's office.",
        "breakdown": (
            "WHAT IT DOES\n"
            "The twin of B2B Customer Contacts, for RAF's office. For each of "
            "yesterday's sales under Raf's SaraPlus code (ALL reps), it asks "
            "whether the customer was EVER messaged on **Dylan's** RingCentral "
            "line — the same account rc_autoread uses — matched by phone, and "
            "as a backstop by customer or business name. The window starts on "
            "the day of the sale and runs to now.\n\n"
            "IT POSTS\n"
            "A header — \"Customers who didn't receive wrap up text\" — in "
            "#alphalete-sales, and in that header's thread the names grouped "
            "under the rep who sold them. A re-run replies to the same header "
            "instead of posting a second one.\n\n"
            "NO CONTACTS ARE CREATED\n"
            "Dylan's RingCentral app can read messages but not contacts (no "
            "ReadContacts scope), so unlike the B2B report this one does the "
            "check and the post only.\n\n"
            "WHEN IT RUNS\n"
            "Every morning on Lucy 1 — Raf's SaraPlus login, Dylan's "
            "RingCentral login. A bare run is a DRY RUN and posts nothing."
        ),
        "assignees": ["Lucy 1"],
        # Raf's SaraPlus profile + Dylan's in-repo RingCentral creds both work
        # on Lucy 1, so a Hub button from any other machine QUEUES the run
        # there.
        "run_machine": "Lucy 1",
        "schedule": {
            "frequency": "daily",
            # Mon–Sat, matching the B2B cadence. Python weekday(): Monday = 0.
            "weekdays": [0, 1, 2, 3, 4, 5],
            "time": "4 AM flow",
            "estimated_minutes": 6,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Checked yesterday's sales under Raf's code and posted the un-texted customers to #alphalete-sales.",
            "message_failed": "❌ Something didn't land. The log names it. The usual causes: the Raf SaraPlus pull on Lucy 1 is missing or stale (re-run 'Refresh Raf pull'), or the RingCentral token isn't Dylan's — the report stops rather than reading the wrong inbox.",
        },
        "actions": [
            {
                "label": "Check Yesterday + Post",
                "icon": "▶",
                "primary": True,
                "help": "Reads yesterday's sales under Raf's code and posts the un-texted customers, grouped by rep, to #alphalete-sales.",
                "module": "automations.rc_contact_sync_raf.run",
                "args_fn": lambda: ["--live"],
            },
            {
                "label": "Refresh Raf pull (Lucy 1)",
                "icon": "⟳",
                "primary": False,
                "help": "Logs into Raf's SaraPlus and refreshes the order handoff. Run this first if the check says the pull is missing or stale.",
                "module": "automations.rc_contact_sync_raf.pull_raf",
                "args_fn": lambda: ["--pull"],
            },
            {
                "label": "Preview (posts nothing)",
                "icon": "👁",
                "primary": False,
                "help": "Shows exactly what the Slack post would say, without posting.",
                "module": "automations.rc_contact_sync_raf.run",
                "args_fn": lambda: ["--dry-run"],
            },
        ],
    },
```
