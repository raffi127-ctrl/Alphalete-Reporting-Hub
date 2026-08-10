"""Make "a human approved it in Slack" something the Hub can SEE.

Megan (2026-08-10): *"a 'phase' hub card that goes green on approval, so we
have visual on it."*

Until now the Hub could not tell approval from posting. A review-gated card
(Captainship Reports, Org / Country Sales Board Email) is a `phases` card: the
tile ramps as each phase lands and turns green when the last one does. But the
only rows those chains ever got were "the build ran" and "the review PDF was
posted" — both written the moment the 4am/9:30am steps exit 0, hours before
anybody looks at the PDF. So the tile went green on POSTED, and a day nobody
approved looked exactly like a day that went out.

This module adds the missing phase. When a gate finds an authorised checkmark,
it calls `record()`, which appends ONE success row to the same "Hub Activity"
tab the Hub already reads — under `<report id>-approved`. The card lists that id
as its LAST phase (`approval_phase` in dashboard.py), so:

    build → post → 🟣 AWAITING ✅ (purple, human's turn) → ✅ green on approval

WHY A ROW AND NOT A SLACK READ. The Hub could ask Slack "is today's post
✅'d?" on every render, but that is a network call per card per refresh, needs a
token on whatever machine has the Hub open, and would show nothing for a past
day once the post scrolls out of the 100-message history window. A row is
written once, by the machine that already has Lucy's token (the mini), and the
whole week's strip reads it for free.

IDEMPOTENT. The gates' checkers run every 15 minutes and keep finding the same
checkmark all day. A marker file under output/review_approvals/ means only the
first pass writes a row — without it the tab would collect ~40 duplicate rows a
day and the "how many passes landed" counters elsewhere would read nonsense.
The marker is per-machine, which is fine: the same machine runs every pass of a
given gate. If the marker is missing but the row already landed (a wiped
output/), the day gets one extra row — harmless, the Hub counts "any success".

Best-effort throughout: never raises. Nothing here may stop an approved report
from going out.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable, Optional, Union

_REPO = Path(__file__).resolve().parents[2]
MARKER_DIR = _REPO / "output" / "review_approvals"

SUFFIX = "-approved"

# What a caller may hand us as "who approved": the (uid, name) tuple the gates'
# find_approval() returns, a bare name, or a callable that goes and looks it up
# (only called when we actually need it — see ensure_recorded).
Approver = Union[str, tuple, Callable[[], Optional[tuple]], None]


def phase_id(report_id: str) -> str:
    """The Hub Activity id for "this report was approved today".

    Deliberately derived, not configured: the card lists it in `phases` and the
    gate writes it, and the two must agree without a shared table to drift.
    """
    return f"{report_id}{SUFFIX}"


def _marker(pid: str, day: dt.date) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in pid)
    return MARKER_DIR / f"{safe}_{day.isoformat()}.json"


def already_recorded(report_id: str, day: Optional[dt.date] = None) -> bool:
    """Has this day's approval already been published to the Hub?"""
    try:
        return _marker(phase_id(report_id), day or dt.date.today()).exists()
    except Exception:      # noqa: BLE001
        return False


def _name_of(who: Approver) -> str:
    if isinstance(who, tuple):
        return str(who[1]) if len(who) > 1 else str(who[0])
    return str(who) if who else "an approver"


def record(report_id: str, report_name: str, who: Approver = None, *,
           day: Optional[dt.date] = None, verbose: bool = True) -> bool:
    """Publish "approved today" for `report_id`. True if a row landed now.

    False means either "already recorded today" (the normal case on passes 2..n)
    or a write that didn't land — the caller must not care which: this is
    display, not the gate.
    """
    day = day or dt.date.today()
    pid = phase_id(report_id)
    marker = _marker(pid, day)
    try:
        if marker.exists():
            return False
    except Exception:      # noqa: BLE001
        pass

    name = _name_of(who)
    ok = False
    try:
        from automations.shared import hub_activity
        ok = hub_activity.log_completed(
            pid, f"{report_name} — approved",
            status="success", user=f"✅ {name}",
            # NOT a card of its own: it is a phase of `report_id`'s card.
            register_card=False)
    except Exception as e:      # noqa: BLE001
        if verbose:
            print(f"  (could not tell the Hub about the approval: "
                  f"{type(e).__name__})", flush=True)
        return False

    if not ok:
        if verbose:
            print("  (the Hub approval row did not land — the pill stays "
                  "purple; the send is unaffected)", flush=True)
        return False

    # Only mark it done once the row actually landed, so a Sheets hiccup is
    # retried by the next 15-minute pass instead of being swallowed forever.
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({
            "report_id": report_id, "phase_id": pid,
            "day": day.isoformat(), "approved_by": name,
            "recorded_at": dt.datetime.now().isoformat(timespec="seconds"),
        }), encoding="utf-8")
    except Exception:      # noqa: BLE001
        pass                # the row is what matters; a missing marker costs a dupe

    if verbose:
        print(f"✓ Hub: {pid} → approved by {name} (the card's pill goes green)",
              flush=True)
    return True


def ensure_recorded(report_id: str, report_name: str, who: Approver = None, *,
                    day: Optional[dt.date] = None, verbose: bool = True) -> bool:
    """record(), but cheap to call on every pass — including the ones that
    short-circuit on "already sent".

    `who` may be a CALLABLE, which is only invoked when the day is not yet
    recorded. That is what lets an already-sent pass repair a missing row (the
    approval happened on some earlier pass, maybe before this code shipped)
    without spending a Slack call on the other 40 passes of the day.
    """
    if already_recorded(report_id, day):
        return False
    if callable(who):
        try:
            who = who()
        except Exception:      # noqa: BLE001
            who = None
    return record(report_id, report_name, who, day=day, verbose=verbose)
