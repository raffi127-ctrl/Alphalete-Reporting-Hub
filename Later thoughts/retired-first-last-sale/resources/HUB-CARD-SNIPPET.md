# FSLS Hub card — snippet to add to `AUTOMATED_REPORTS` in `dashboard.py`

This is a self-contained dict — paste it into the `AUTOMATED_REPORTS` list
in `dashboard.py` (alongside `recruiting` and `daily-focus`). It mirrors
the existing two cards' structure.

Run module: `automations.first_last_sale.run` (default upload dir is
`automations/uploaded/first_last_sale/`).

```python
{
    "id": "first-last-sale",
    "name": "First Sale / Last Sale (Upload)",
    "creator": "Megan",
    "emoji": "🕰️",
    "color": "#A78BFA",
    "category": "🎯 Recruiting",
    "description": "Parses the emailed B2B.D2D First Last Sale .xlsx and "
                   "fills the FK/LK section (1 week behind) on every ICD "
                   "tab.",
    "breakdown": (
        "WHAT IT DOES\n"
        "Fills the **first/last sale times + Order Count** table at the "
        "bottom of every ICD tab from the weekly emailed Excel.\n\n"
        "WHEN IT RUNS\n"
        "**Mondays**, after the email arrives. The file's filename carries "
        "the week (e.g. `B2B.D2D First Last Sale WE 5.10.2026.xlsx`).\n\n"
        "UPLOAD\n"
        "Drop the .xlsx into the uploader on this card; the run uses the "
        "latest WE-dated file in the folder.\n\n"
        "IF AN ICD IS NOT IN THE FILE\n"
        "Their section header turns into **'Not On Emailed Report'** "
        "(light-red background) so it's visibly intentional, and the body "
        "cells are cleared."
    ),
    "sheet_url": SHEET_URL,   # same ATT Program report
    "assignees": ["Megan"],
    "schedule": {
        "frequency": "weekly",
        "weekdays": [0],   # Monday
        "time": "9:00 AM",
        "estimated_minutes": 3,
    },
    "checklist": [
        # No Chrome needed — file-only report
    ],
    "uploader": {
        "label": "Upload the emailed B2B.D2D First Last Sale .xlsx",
        "accept": ".xlsx",
        "target_dir": "automations/uploaded/first_last_sale",
    },
    "post_run": {
        "message_success": "✅ FK/LK table filled on every ICD tab.",
        "message_failed": "❌ Run failed. Check the log above.",
    },
    "actions": [
        {
            "label": "Run FSLS Fill",
            "icon": "▶",
            "primary": True,
            "help": "Reads the latest uploaded .xlsx and fills every tab.",
            "module": "automations.first_last_sale.run",
            "args_fn": lambda: [],
        },
    ],
},
```

**Note:** the `uploader` block is hypothetical — check whether your Hub
card schema already supports an upload section (financial_report doesn't
have a Hub card yet either, so this is the first upload-based card).
If your Hub uses a different mechanism (a separate Wire-Up dialog),
just point that flow at the same module.

# Production Breakdown + Team Breakdowns

These are NOT separate Hub cards — they run automatically as the last 2
steps of the OPT phase (see `opt_phase.run_opt_phase`), reusing the
PRODUCT SALES SUMMARY crosstab that's already downloaded. No extra
upload, no extra run button needed. The OPT card already covers them.
