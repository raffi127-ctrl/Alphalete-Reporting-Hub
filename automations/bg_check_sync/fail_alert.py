"""Text the admin group when THIS WEEK's new start fails their background check.

Megan 2026-09-26, after Quincy Williams failed on the 25th and nobody was told:
"If it says failed in the email, then it's failed. We need current week new
starts that get a failed status to send a text. NOT for every failed, just the
current week."

So the trigger is the EMAIL — Sterling's "Background Check Complete - Score
FAIL" (which sets needs_adjudication) or a terminal Failed — and the audience
is the week IN FLIGHT plus the cohort starting next Monday — both are "current
week new starts" depending on the day you ask (the sync's own _active_monday
rolls to the next Monday late in the week, which is how the first version
missed Quincy on the Friday). Weeks further out, and weeks already gone, are
not texted.

What this does NOT change: the OBCL still records "Review" for a Score FAIL,
because Sterling's FAIL is an adverse-action review a rep can be cleared
through, and writing "Failed" off that email is the false-fail Raf ruled out on
2026-07-20. The sheet stays cautious; the text goes out immediately.

Sent from the BG sync's own process on Lucy 1, the way gap_alerts texts from
that box. Idempotent: a name is texted once per week per outcome, so the 11:30
and 4pm passes can't repeat it.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import List, Sequence

GROUP = "ORIENTATION CREW - Real"
STATE = Path("output") / "bg_check_sync" / "failed_bg_texted.json"


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _key(name: str, week: str) -> str:
    return f"{week}|{' '.join(name.split()).lower()}"


def failures(decisions: Sequence) -> List[tuple]:
    """[(name, what the email said)] for decisions whose EMAIL says failed.

    `needs_adjudication` is set by parse.classify on a "Score FAIL" email;
    `new_status == "Failed"` is a terminal fail. Either one is a fail as far as
    this text is concerned."""
    out, seen = [], set()
    for d in decisions:
        p = getattr(d, "person", None)
        if p is None:
            continue
        name = f"{p.first} {p.last}".strip()
        if getattr(d, "new_status", "") == "Failed":
            what = "Failed"
        elif getattr(d, "needs_adjudication", False):
            what = "Score FAIL — in adverse-action review"
        else:
            continue
        # One line per person: a rep can have two emails in the same run
        # (Quincy Williams had both on 2026-09-25) and the text named him twice.
        key = " ".join(name.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((name, what))
    return out


def message(rows: Sequence) -> str:
    head = ("🚨 Background check FAILED — this week's new start"
            if len(rows) == 1 else
            f"🚨 Background check FAILED — {len(rows)} of this week's new starts")
    # Megan 2026-09-26: headline + one line per person, nothing after it.
    return "\n".join([head] + [f"• {n} — {what}" for n, what in rows])


def send(decisions: Sequence, week: str, *, is_current_week: bool,
         dry_run: bool = True, group: str = GROUP) -> dict:
    """Text the group about this week's failures. Returns what it did."""
    res = {"week": week, "current": is_current_week, "texted": [],
           "already": [], "dry_run": dry_run}
    if not is_current_week:
        return res                      # only the week in flight
    rows = failures(decisions)
    if not rows:
        return res
    state = _load()
    fresh = [(n, w) for n, w in rows if _key(n, week) not in state]
    res["already"] = [n for n, _ in rows if _key(n, week) in state]
    if not fresh:
        return res
    text = message(fresh)
    res["text"] = text
    if dry_run:
        res["texted"] = [n for n, _ in fresh]
        return res
    from automations.b2b_dispositions import text_post as tp
    sent = tp.send_to_group(group, text, [], dry_run=False,
                            allow_textonly=True)
    if not sent.get("ok"):
        res["error"] = str(sent)[:200]
        return res                      # NOT recorded — a failed send retries
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    for n, _ in fresh:
        state[_key(n, week)] = stamp
    _save(state)
    res["texted"] = [n for n, _ in fresh]
    res["chat"] = sent.get("resolved_name")
    res["participants"] = sent.get("participants")
    return res
