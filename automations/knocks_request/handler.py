"""`/knocks` — the Slack half: a two-field popup, an image back in a DM.

Rides the SAME always-on Jiraiya listener as `/dd` and the Promotion Check-In
buttons (`due_diligence.bot`), so there is no second app, no second token and
no second process to keep alive. `bot._handler` opens this modal on the slash
command and hands the submission straight here.

THE POPUP IS TWO FIELDS on purpose (the 7-year-old-simple rule): whose office,
and which day — the day defaulting to yesterday, which is what "the board from
this morning" means. No flags, no syntax, no way to type it wrong.

WHAT COMES BACK is the same amber board the morning thread posts, in a DM. Most
requests are answered from what the morning build already pulled, so they land
in seconds and never touch ownerville; the rest say they are waiting and then
arrive. Errors are answered in words the requester can act on — an office we
have no ownerville access to says exactly that, because it is the one failure
nobody can fix by retrying.

Everything that decides WHAT to send lives in `service`; this file only turns
it into Slack messages.
"""
from __future__ import annotations

import datetime as dt
import threading
import traceback
from typing import Optional, Tuple

from . import service

CALLBACK = "knocks_form"
COMMAND = "/knocks"

# One request at a time inside the bot process: two live pulls would race for
# the same ownerville session as surely as two reports would. Cache hits are
# quick enough that queuing behind one is not worth a second lock.
_PULL_LOCK = threading.Lock()


def _pretty(d: dt.date) -> str:
    """'August 23, 2026' with no leading zero — built by hand because %-d is
    glibc/BSD only and Windows strftime rejects it (the cross-platform rule)."""
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def modal(today: dt.date | None = None) -> dict:
    """The popup. `today` is injectable so the default date is testable."""
    target = (today - dt.timedelta(days=1)) if today else service.default_target()
    return {
        "type": "modal", "callback_id": CALLBACK,
        "title": {"type": "plain_text", "text": "Knocks"},
        "submit": {"type": "plain_text", "text": "Get the board"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": ":door: I'll send you that office's knock board for the "
                     "day you pick — the same one that goes out every morning."}},
            {"type": "input", "block_id": "office",
             "label": {"type": "plain_text", "text": "Whose office?"},
             "element": {"type": "plain_text_input", "action_id": "v",
                         "placeholder": {"type": "plain_text",
                                         "text": "Rafael Hidalgo"}}},
            {"type": "input", "block_id": "day",
             "label": {"type": "plain_text", "text": "Which day?"},
             "element": {"type": "datepicker", "action_id": "v",
                         "initial_date": target.isoformat()}},
        ],
    }


# Words that open a plain-DM request, so nobody needs the slash command at all
# (a slash command has to be registered in the Slack app by its owner; a DM does
# not — the listener already receives message.im for the /dd name corrections).
_DM_TRIGGERS = ("knocks", "knock")
# Day words people actually type. Anything else is treated as part of the name.
_DAY_WORDS = {"today": 0, "yesterday": 1}


def parse_dm(text: str) -> Optional[Tuple[str, dt.date]]:
    """(office, day) for a DM like `knocks Chan Park` / `knocks chan park
    2026-08-21` / `knocks Chan Park yesterday`, else None.

    None means "not a knocks request" and the DM keeps its old meaning — that
    matters, because the same inbox is how `/dd` takes a corrected rep name.
    Deliberately narrow: the message must LEAD with knock(s)."""
    words = (text or "").strip().split()
    if not words or words[0].lower().strip(":,") not in _DM_TRIGGERS:
        return None
    rest = words[1:]
    target = service.default_target()
    if rest:
        tail = rest[-1].lower().strip(".,")
        if tail in _DAY_WORDS:
            target = service.central_today() - dt.timedelta(days=_DAY_WORDS[tail])
            rest = rest[:-1]
        else:
            try:
                target = dt.date.fromisoformat(rest[-1].strip(".,"))
                rest = rest[:-1]
            except ValueError:
                pass
    return " ".join(rest).strip(), target


def handle_dm(web, user_id: str, text: str) -> None:
    """A plain DM that starts with 'knocks'. Callers check parse_dm first; this
    also answers the bare word with the one line of help it needs."""
    parsed = parse_dm(text)
    if parsed is None:
        return
    office, target = parsed
    if not office:
        try:
            chan = web.conversations_open(users=user_id)["channel"]["id"]
            web.chat_postMessage(channel=chan, text=(
                ":door: Tell me whose office — e.g. `knocks Chan Park`, or "
                "`knocks Chan Park 2026-08-21` for a specific day. (Yesterday "
                "is the default.)"))
        except Exception:  # noqa: BLE001
            pass
        return
    process(web, user_id, office, target)


def is_knocks_submission(payload: dict) -> bool:
    return (payload.get("type") == "view_submission"
            and payload.get("view", {}).get("callback_id") == CALLBACK)


def handle_submission(web, payload: dict) -> None:
    """Read the popup and start the work. Called from bot._handler AFTER the
    3-second ack, on its own thread."""
    vals = payload["view"]["state"]["values"]
    office = (vals.get("office", {}).get("v", {}).get("value") or "").strip()
    day_s = vals.get("day", {}).get("v", {}).get("selected_date") or ""
    try:
        target = dt.date.fromisoformat(day_s)
    except ValueError:
        target = service.default_target()
    process(web, payload["user"]["id"], office, target)


def process(web, user_id: str, office: str, target: dt.date) -> None:
    """Fetch + send, reporting every outcome in the DM. Never raises: this runs
    on the listener's thread pool and a crash here would be silence for the
    requester and a stack trace nobody reads."""
    try:
        chan = web.conversations_open(users=user_id)["channel"]["id"]
    except Exception:  # noqa: BLE001 — DMs by user id work in most workspaces
        chan = user_id

    def say(text: str) -> None:
        try:
            web.chat_postMessage(channel=chan, text=text)
        except Exception:  # noqa: BLE001 — a lost progress line ≠ a lost board
            pass

    if not office:
        say(":warning: I need whose office — run `/knocks` again and fill in "
            "the name.")
        return

    pretty = _pretty(target)
    # Refused before any work: a future day comes back from Ownerville as an
    # empty grid, indistinguishable from a day nobody knocked.
    if target > service.central_today():
        say(f":calendar: {pretty} hasn't happened yet — ask me for today or "
            "any day that's already gone by.")
        return

    canonical = service.resolve_office(office)
    have, _src = service.cached_rows(canonical, target)
    if have:
        say(f":door: Getting *{canonical}*'s knocks for {pretty} — one second.")
    else:
        busy = service.ownerville_busy()
        if busy:
            say(f":door: *{canonical}* — {pretty}. The scheduled reports are "
                "using Ownerville right now, so I'm queued behind them. I'll "
                "send the board as soon as they're done — no need to ask again.")
        else:
            say(f":door: Pulling *{canonical}*'s knocks for {pretty} from "
                "Ownerville — about a minute.")

    try:
        with _PULL_LOCK:
            board = service.board_for(office, target, logfn=lambda m: None)
    except Exception as e:  # noqa: BLE001 — every failure answers in words
        traceback.print_exc()
        if service.access_gap(e):
            say(f":lock: I can't pull *{canonical}* — that office isn't on the "
                "Ownerville account these reports run on, so there's nothing "
                "to fetch until someone grants Office Access to it. (16 offices "
                "are in this position; it's a permissions gap, not a typo.)")
        else:
            say(f":x: Couldn't get *{canonical}* for {pretty} — "
                f"{type(e).__name__}: {str(e)[:200]}")
        return

    if board.png is None:
        say(f":zero: *{canonical}* — {pretty}: {board.note}.")
        return

    reps = len(board.rows)
    cap = (f":door: *Total Knocks — {canonical} — {pretty}*  "
           f"({reps} rep{'s' if reps != 1 else ''})")
    if board.partial:
        # Today's numbers keep moving; say so on the image itself, because a
        # screenshot of it will outlive this message.
        cap += "\n_Today so far — the day isn't over, these numbers will grow._"
    elif board.source in ("cache", "build"):
        cap += "\n_From this morning's run — same numbers the report used._"
    try:
        web.files_upload_v2(channel=chan, file=str(board.png),
                            filename=f"{canonical} knocks {target}.png",
                            initial_comment=cap)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        say(f":x: The board rendered but Slack wouldn't take the image — "
            f"{type(e).__name__}: {str(e)[:160]}")
