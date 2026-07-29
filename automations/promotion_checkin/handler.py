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


def is_promo_action(payload) -> bool:
    """True if this block_actions payload is one of OUR buttons."""
    if payload.get("type") != "block_actions":
        return False
    for a in payload.get("actions", []):
        if a.get("action_id") in (C.ACTION_SUBMIT, C.ACTION_NONE, C.ACTION_PICK):
            return True
    return False


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
                    if a.get("action_id") in (C.ACTION_SUBMIT, C.ACTION_NONE)), None)
    action = clicked.get("action_id") if clicked else None
    if action is None:
        return {"noop": True}                 # a mid-pick select change — ignore
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

    _tab, week, reps = B.load_board()
    by_name = {r.name.lower(): r for r in reps}
    promos, misses = [], []
    for nm in names:
        rep = by_name.get(nm.lower())
        if rep and rep.recognition:
            promos.append(R.Promotion(name=rep.name, trainer=rep.trainer,
                                      recognition=rep.recognition))
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


def _week_from_message(payload):
    """Pull the 'WE 8.2' tag out of the header block text, best-effort."""
    for b in (payload.get("message") or {}).get("blocks", []):
        if b.get("type") == "header":
            txt = (b.get("text") or {}).get("text", "")
            if "·" in txt:
                return txt.split("·")[-1].strip()
    return "this week"
