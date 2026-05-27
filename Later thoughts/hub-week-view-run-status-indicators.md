# Hub "This week" view — per-report run-status indicators

Captured 2026-05-27. **Non-priority.** Polish for the Home Hub's "This week"
calendar view (the grid of cards per day of week).

## The ask

On each report card in the week view, show a visual indicator of the run's outcome:

- ✅ green / checkmark if the day's run succeeded
- ⚠️ warning / red if something went wrong

When the user clicks into a card that's flagged as failed, the open detail
should explain **what went wrong** (not just "failed" — the actual error
or symptom from the run log).

## Today's behavior

Each card is identical regardless of run state. Users have to open the
card to see if it ran, then dig into the run log to see if it succeeded.

## Implementation notes for future-Claude

- The run-history is already tracked by the Hub (see `_read_active_runs`,
  `_load_all_run_state`, `_get_completed_today` in `automations/dashboard.py`).
  Per-report success/fail state lives in the `completed_runs` / run-state
  files; the week-view just doesn't surface it visually.
- `_diagnose_run_failure(log_text)` already parses common failure
  modes from log tails — that's the source of the "what went wrong"
  text to surface inside the card detail.
- Touching the week-view layout is a [[feedback_hub_ownership]] /
  Megan-owned area — pair this work with Megan rather than auto-applying.
