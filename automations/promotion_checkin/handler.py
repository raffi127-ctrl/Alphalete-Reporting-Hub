"""Process a click on the promotion check-in card.

Called from the Jiraiya Socket Mode listener (due_diligence/bot.py) after it
ack's the interaction. Reads which reps were picked, resolves each to the board,
appends them to the recognition tab, and rewrites the card to a confirmation.

SAFE BY DEFAULT: writes to the sheet only when PROMO_WRITE is on (the deploy
wrapper sets it). A preview DM leaves it off, so a click just previews.
"""
from __future__ import annotations

import os

from . import config as C
from . import board as B
from . import message as M
from . import recognition as R


_BUTTONS = (C.ACTION_SUBMIT, C.ACTION_NONE, C.ACTION_REMOVE)


def is_promo_action(payload) -> bool:
    """True if this block_actions payload is one of OUR buttons (not a mid-pick
    select change, which we ignore)."""
    if payload.get("type") != "block_actions":
        return False
    return any(a.get("action_id") in _BUTTONS for a in payload.get("actions", []))


def _selected_level(payload):
    """The Recognition string chosen in the 'Promoted to' dropdown (defaults to
    the first LEVEL_CHOICES entry if somehow unset)."""
    state = (payload.get("state") or {}).get("values") or {}
    for _bid, actions in state.items():
        act = actions.get(C.ACTION_LEVEL)
        if act and act.get("selected_option"):
            return act["selected_option"].get("value") or C.LEVEL_CHOICES[0][1]
    return C.LEVEL_CHOICES[0][1]


def _write_enabled() -> bool:
    return os.environ.get("PROMO_WRITE", "").strip().lower() in ("1", "on", "true", "yes")


def _selected_names(payload):
    state = (payload.get("state") or {}).get("values") or {}
    for _bid, actions in state.items():
        act = actions.get(C.ACTION_PICK)
        if act and act.get("selected_options") is not None:
            return [o.get("value", "") for o in act["selected_options"] if o.get("value")]
    return []


def _reply_in_thread(web, payload, blocks, fallback):
    """Post a receipt UNDER the card (thread reply) and LEAVE the card in place,
    so leaders can keep picking + logging more all evening. Dedup stops re-logs."""
    ch = (payload.get("channel") or {}).get("id")
    ts = (payload.get("message") or {}).get("ts")
    if ch and ts:
        web.chat_postMessage(channel=ch, thread_ts=ts, blocks=blocks, text=fallback)


def handle_action(web, payload, *, write_sheet=None, verbose=False):
    """Dispatch a promo button. `write_sheet=None` => decide from PROMO_WRITE."""
    if write_sheet is None:
        write_sheet = _write_enabled()
    clicked = next((a for a in payload.get("actions", [])
                    if a.get("action_id") in _BUTTONS), None)
    action = clicked.get("action_id") if clicked else None
    if action is None:
        return {"noop": True}                 # a mid-pick select change — ignore

    # "Remove a mistake" — open a modal listing only THIS office's logged reps.
    if action == C.ACTION_REMOVE:
        return _open_remove_modal(web, payload)
    # A card built with preview=True stamps its submit button value="preview";
    # that card NEVER writes the sheet, even if the listener has PROMO_WRITE on.
    if clicked.get("value") == "preview":
        write_sheet = False

    actor = (payload.get("user") or {}).get("id", "")
    # Recover the week label from the card header so the confirmation matches.
    week = _week_from_message(payload)

    if action == C.ACTION_NONE:
        _reply_in_thread(web, payload, M.none_blocks(week, actor=actor),
                         f"No promotions logged for {week}.")
        return {"none": True, "actor": actor}

    # ACTION_SUBMIT — resolve picks against the live board and log them.
    names = _selected_names(payload)
    if not names:
        # Nothing selected; leave the card up, nudge in-thread.
        ch = (payload.get("channel") or {}).get("id")
        ts = (payload.get("message") or {}).get("ts")
        if ch and ts:
            web.chat_postMessage(channel=ch, thread_ts=ts,
                text=":point_up: Pick at least one rep from the dropdown first, "
                     "then hit *Log promotions* (or *No promotions this week*).")
        return {"empty_submit": True}

    recognition = _selected_level(payload)     # the leader's chosen level
    _tab, week, reps = B.load_board()
    by_name = {r.name.lower(): r for r in reps}
    promos, misses = [], []
    for nm in names:
        rep = by_name.get(nm.lower())
        if rep:
            # Level comes from the leader's "Promoted to" pick, NOT the board.
            promos.append(R.Promotion(name=rep.name, trainer=rep.trainer,
                                      recognition=recognition))
        else:
            misses.append(nm)

    res = R.append_promotions(promos, dry_run=not write_sheet)
    blocks = M.confirmation_blocks(week, res, actor=actor)
    if misses:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
            "text": f":warning: Couldn't match on the board (not logged): "
                    f"{', '.join(misses)}"}]})
    if not write_sheet:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
            "text": ":eyes: *Preview mode* — the sheet was NOT written."}]})
    else:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
            "text": "_Missed someone? Pick them in the card above and hit "
                    "*Log promotions* again — I won't double-log anyone._"}]})
    # Reply in-thread and LEAVE the card live so more can be added all evening.
    _reply_in_thread(web, payload, blocks,
                     f"Logged {res.get('n', 0)} promotions to {res.get('tab')}.")
    return {"submit": True, "result": res, "misses": misses, "actor": actor,
            "wrote": bool(write_sheet)}


def _open_remove_modal(web, payload):
    """Open the 'Remove a promotion' modal. Reads what our office logged this week
    so the list can never offer another office's row."""
    trigger = payload.get("trigger_id")
    if not trigger:
        return {"remove": "no_trigger"}
    ch = (payload.get("channel") or {}).get("id", "")
    ts = (payload.get("message") or {}).get("ts", "")
    week = _week_from_message(payload)
    try:
        logged = R.logged_this_week()
    except Exception as e:                     # noqa: BLE001
        logged = []
        print(f"[promo] logged_this_week failed {type(e).__name__}: {e}", flush=True)
    view = M.remove_modal(week, logged, channel=ch, ts=ts)
    web.views_open(trigger_id=trigger, view=view)
    return {"remove": "opened", "n_logged": len(logged)}


def handle_remove_submission(web, payload, *, write_sheet=None):
    """Handle the remove modal's submit: clear the picked reps' rows (ours only)."""
    if write_sheet is None:
        write_sheet = _write_enabled()
    import json
    meta = {}
    try:
        meta = json.loads(payload.get("view", {}).get("private_metadata") or "{}")
    except Exception:                          # noqa: BLE001
        pass
    actor = (payload.get("user") or {}).get("id", "")
    vals = (payload.get("view", {}).get("state") or {}).get("values") or {}
    picked = []
    for _bid, actions in vals.items():
        act = actions.get("v")
        if act and act.get("selected_options"):
            picked = [o.get("value", "") for o in act["selected_options"] if o.get("value")]
    week = meta.get("week", "this week")
    if not picked:
        return {"removed": []}
    res = R.remove_promotions(picked, dry_run=not write_sheet)
    ch, ts = meta.get("channel"), meta.get("ts")
    blocks = M.removed_blocks(week, res, actor=actor)
    if ch and ts:
        web.chat_postMessage(channel=ch, thread_ts=ts, blocks=blocks,
                             text=f"Removed {res.get('n', 0)} from {res.get('tab')}.")
    elif ch:
        web.chat_postMessage(channel=ch, blocks=blocks,
                             text=f"Removed {res.get('n', 0)} from {res.get('tab')}.")
    return {"removed": res.get("removed", []), "wrote": bool(write_sheet)}


def _week_from_message(payload):
    """Pull the 'WE 8.2' tag out of the header block text, best-effort."""
    for b in (payload.get("message") or {}).get("blocks", []):
        if b.get("type") == "header":
            txt = (b.get("text") or {}).get("text", "")
            if "·" in txt:
                return txt.split("·")[-1].strip()
    return "this week"
