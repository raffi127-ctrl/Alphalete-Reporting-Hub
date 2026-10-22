# Hub card snippet — Office Wrap-Up Check (all offices)

**For Megan.** Drop the dict below into the `AUTOMATED_REPORTS` list in
`automations/hub_cards.py`. Nothing else needs to change.

- **Module:** `automations/office_wrap_ups/` (`run.py` is the entry point)
- **What it does:** the multi-office version of the Raf Wrap-Up Check. For every
  office in Raf's captainship (12 of them), it checks which of yesterday's
  customers were never texted on **Dylan's** RingCentral line and posts the reps
  who owe a wrap-up to **that office's own Slack channel**.
- **Source:** the ORG-WIDE Tableau **Order Log** (the same ALLREPS crosstab
  disconnects/cancels use) — one pull covers every office, filtered by
  `Owner Name`. **No per-office SaraPlus logins** needed.
- **Runs on Lucy 4** (already pulls the Order Log for every per-office metrics
  runner), on-scheduler + `--live`, every morning. Channels come from
  `office_metrics.OFFICES`; Trang's `#freshsuccess-all-leaders` posts with her
  workspace's bot token (same as `trang_metrics`).
- **Google Sheets:** none. Reads Tableau + the RingCentral API.

```python
    {
        "id": "office-wrap-ups",
        "name": "Office Wrap-Up Check (all offices)",
        "creator": "Dylan",
        "emoji": "📞",
        "color": "#60A5FA",
        "category": "📊 Metrics",
        "description": "For every office in Raf's captainship, posts the reps who didn't send a wrap-up text to that office's Slack channel each morning — checked against Dylan's RingCentral line, off the org-wide Tableau Order Log (no per-office SaraPlus logins).",
        "breakdown": (
            "WHAT IT DOES\n"
            "The multi-office version of the Raf Wrap-Up Check. One pull of the "
            "org-wide Order Log, filtered per office by Owner Name; for each of "
            "yesterday's customers it asks whether they were EVER messaged on "
            "Dylan's RingCentral line, and posts the un-texted ones — grouped "
            "by rep, with each customer's phone + products (Internet / TV / "
            "Wireless) and the reps @tagged — to that office's own channel.\n\n"
            "OFFICES (12)\n"
            "Haytham, Trang, Hammad, Jacob, Joseph, Kash, Rashad, Aya, Cyrus, "
            "Nii, Cody, Salik. Channels from office_metrics.OFFICES (Hammad + "
            "Salik share #elite-prime-sales; Trang is the FRESH SUCCESS "
            "workspace).\n\n"
            "WHEN IT RUNS\n"
            "Every morning on Lucy 4. A bare run is a DRY RUN and posts nothing."
        ),
        "assignees": ["Lucy 4"],
        "run_machine": "Lucy 4",
        "schedule": {
            "frequency": "daily",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "time": "morning batch",
            "estimated_minutes": 15,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Posted each office's wrap-up status to its channel.",
            "message_failed": "❌ Something didn't land — the log names it (usually the Tableau Order Log being behind, or the RingCentral token). Re-run when the Order Log is fresh.",
        },
        "actions": [
            {
                "label": "Run Now (all offices)",
                "icon": "▶",
                "primary": True,
                "help": "Pulls the Order Log and posts each office's un-texted customers to its channel.",
                "module": "automations.office_wrap_ups.run",
                "args_fn": lambda: ["--live"],
            },
            {
                "label": "Preview (posts nothing)",
                "icon": "👁",
                "primary": False,
                "help": "Shows exactly what each office would post, without posting.",
                "module": "automations.office_wrap_ups.run",
                "args_fn": lambda: ["--dry-run"],
            },
        ],
    },
```
