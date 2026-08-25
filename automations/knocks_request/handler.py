"""`/knocks` — the Slack half: a two-field popup, an image back in a DM.

Rides the SAME always-on Jiraiya listener as `/dd` and the Promotion Check-In
buttons (`due_diligence.bot`), so there is no second app, no second token and
no second process to keep alive. `bot._handler` opens this modal on the slash
command and hands the submission straight here.

THE POPUP IS THREE FIELDS, the third OPTIONAL (the 7-year-old-simple rule):
whose office, which day — defaulting to yesterday, which is what "the board
from this morning" means — and a "through" day that is blank unless you want a
range (Raf 2026-08-25: "so it can do a range?"). Blank means one day, so
anyone who ignores the third field gets exactly what they got before it
existed. No flags, no syntax, no way to type it wrong.

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
             "label": {"type": "plain_text", "text": "From which day?"},
             "element": {"type": "datepicker", "action_id": "v",
                         "initial_date": target.isoformat()}},
            # NO initial_date, and optional: the blank IS the single-day
            # answer. Pre-filling it would make every request a range and
            # quietly change what the untouched popup does.
            {"type": "input", "block_id": "through", "optional": True,
             "label": {"type": "plain_text", "text": "Through which day?"},
             "hint": {"type": "plain_text",
                      "text": "Leave blank for just that one day."},
             "element": {"type": "datepicker", "action_id": "v"}},
        ],
    }


# Words that open a plain-DM request, so nobody needs the slash command at all
# (a slash command has to be registered in the Slack app by its owner; a DM does
# not — the listener already receives message.im for the /dd name corrections).
_DM_TRIGGERS = ("knocks", "knock")
# Day words people actually type. Anything else is treated as part of the name.
_DAY_WORDS = {"today": 0, "yesterday": 1}
# Words that join two dates into a range. '..' needs no word (it's one token).
_SPAN_WORDS = {"to", "through", "thru", "until", "til", "-", "–", "—"}


def _one_date(tok: str) -> Optional[dt.date]:
    """A bare token as a date — an ISO date or a day word — else None."""
    t = (tok or "").lower().strip(".,")
    if t in _DAY_WORDS:
        return service.central_today() - dt.timedelta(days=_DAY_WORDS[t])
    try:
        return dt.date.fromisoformat(t)
    except ValueError:
        return None


def _pop_span(rest: list) -> Tuple[list, Optional[dt.date], Optional[dt.date]]:
    """Peel a trailing date or date RANGE off the words after the name.

    Understood, in the order tried:
        … 2026-08-18..2026-08-23      (one token)
        … 2026-08-18 to 2026-08-23    (also through / thru / until / -)
        … 2026-08-21   /   … yesterday
    Anything else stays part of the office name, which is the old behaviour and
    the reason a name containing a stray word still works."""
    if rest:
        tok = rest[-1].strip(".,")
        if ".." in tok:
            a, _, z = tok.partition("..")
            d1, d2 = _one_date(a), _one_date(z)
            if d1 and d2:
                return rest[:-1], d1, d2
    if len(rest) >= 3 and rest[-2].lower().strip(".,") in _SPAN_WORDS:
        d1, d2 = _one_date(rest[-3]), _one_date(rest[-1])
        if d1 and d2:
            return rest[:-3], d1, d2
    if rest:
        d1 = _one_date(rest[-1])
        if d1:
            return rest[:-1], d1, d1
    return rest, None, None


def parse_dm(text: str) -> Optional[Tuple[str, dt.date, dt.date]]:
    """(office, start, end) for a DM like `knocks Chan Park` / `knocks chan
    park 2026-08-21` / `knocks Chan Park yesterday` / `knocks Chan Park
    2026-08-18 to 2026-08-23` / `knocks Chan Park 2026-08-18..2026-08-23`,
    else None. `end` equals `start` for a single day.

    None means "not a knocks request" and the DM keeps its old meaning — that
    matters, because the same inbox is how `/dd` takes a corrected rep name.
    Deliberately narrow: the message must LEAD with knock(s)."""
    words = (text or "").strip().split()
    if not words or words[0].lower().strip(":,") not in _DM_TRIGGERS:
        return None
    rest, start, end = _pop_span(words[1:])
    if start is None:
        start = end = service.default_target()
    return " ".join(rest).strip(), start, end


def handle_dm(web, user_id: str, text: str) -> None:
    """A plain DM that starts with 'knocks'. Callers check parse_dm first; this
    also answers the bare word with the one line of help it needs."""
    parsed = parse_dm(text)
    if parsed is None:
        return
    office, target, end = parsed
    if not office:
        try:
            chan = web.conversations_open(users=user_id)["channel"]["id"]
            web.chat_postMessage(channel=chan, text=(
                ":door: Tell me whose office — e.g. `knocks Chan Park`, or "
                "`knocks Chan Park 2026-08-21` for a specific day, or "
                "`knocks Chan Park 2026-08-18 to 2026-08-23` for a stretch of "
                "days. (Yesterday is the default.)"))
        except Exception:  # noqa: BLE001
            pass
        return
    process(web, user_id, office, target, end)


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
    # The optional third field. Blank — the untouched default — is a single
    # day, so it must land on exactly the old one-day path, not on a range of
    # one that merely behaves like it.
    through_s = vals.get("through", {}).get("v", {}).get("selected_date") or ""
    try:
        end = dt.date.fromisoformat(through_s)
    except ValueError:
        end = target
    process(web, payload["user"]["id"], office, target, end)


def process(web, user_id: str, office: str, target: dt.date,
            end: Optional[dt.date] = None) -> None:
    """Fetch + send, reporting every outcome in the DM. Never raises: this runs
    on the listener's thread pool and a crash here would be silence for the
    requester and a stack trace nobody reads."""
    end = end or target
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

    pretty = service.pretty_span(target, end)
    # Refused before any work: a future day comes back from Ownerville as an
    # empty grid, indistinguishable from a day nobody knocked; a backwards or
    # month-long span is refused in words rather than guessed at.
    problem = service.check_span(target, end)
    if problem:
        say(f":calendar: {problem}")
        return

    canonical = service.resolve_office(office)
    need = service.missing_days(canonical, target, end)
    total = len(service.span_days(target, end))
    if not need:
        say(f":door: Getting *{canonical}*'s knocks for {pretty} — one second.")
    else:
        # Say how many days are actually being scraped, not how many were
        # asked for: "6 days" when 5 are already on disk reads as a wait that
        # never comes.
        how_long = ("about a minute" if len(need) == 1
                    else f"a minute or two for {len(need)} day"
                         f"{'s' if len(need) != 1 else ''}")
        got = (f" ({total - len(need)} of the {total} days already on hand.)"
               if total > len(need) else "")
        busy = service.ownerville_busy()
        if busy:
            say(f":door: *{canonical}* — {pretty}. The scheduled reports are "
                "using Ownerville right now, so I'm queued behind them. I'll "
                "send the board as soon as they're done — no need to ask "
                f"again.{got}")
        else:
            say(f":door: Pulling *{canonical}*'s knocks for {pretty} from "
                f"Ownerville — {how_long}.{got}")

    try:
        with _PULL_LOCK:
            board = service.board_for(office, target, end,
                                      logfn=lambda m: None)
    except Exception as e:  # noqa: BLE001 — every failure answers in words
        traceback.print_exc()
        if service.access_gap(e):
            say(f":lock: I can't pull *{canonical}* — that office isn't on the "
                "Ownerville account these reports run on, so there's nothing "
                "to fetch until someone grants Office Access to it. It's a "
                "permissions gap, not a typo.")
        else:
            say(f":x: Couldn't get *{canonical}* for {pretty} — "
                f"{type(e).__name__}: {str(e)[:200]}")
        return

    if board.png is None:
        say(f":zero: *{canonical}* — {pretty}: {board.note}.")
        return

    reps = len(board.rows)
    # A gaps-only (NDS) office has no Disposition page, so there are no knock
    # COUNTS to send — calling that board "Total Knocks" would read as a
    # report of zero. Name it what it is and say why in one line.
    gaps_only = board.shape == "gaps_only"
    title = "TeleMapper Knocks" if gaps_only else "Total Knocks"
    cap = (f":door: *{title} — {canonical} — {pretty}*  "
           f"({reps} rep{'s' if reps != 1 else ''})")
    if gaps_only:
        cap += ("\n_This office knocks without a Disposition page, so "
                "Ownerville records knock activity — times and gaps — not "
                "knock counts. Time Gaps below._")
    if board.is_range:
        # A range board is a FOLD, and a screenshot of it will outlive this
        # message — so what the numbers mean has to ride on the post itself.
        cap += (f"\n_{board.days} days added together. First and Last Knock "
                "are the earliest and latest in that stretch; Avg. Hrs "
                "Knocking is the average over the days each rep actually "
                "knocked._")
    if board.partial:
        # Today's numbers keep moving; say so on the image itself, because a
        # screenshot of it will outlive this message.
        cap += ("\n_Today so far — the day isn't over, these numbers will "
                "grow._")
    elif board.source in ("cache", "build"):
        cap += "\n_From this morning's run — same numbers the report used._"

    # NDS shapes come back as a PAIR (board + Time Gaps); house is one image.
    span = target.isoformat() if not board.is_range else f"{target} to {end}"
    names = [f"{canonical} knocks {span}.png",
             f"{canonical} time gaps {span}.png"]
    caps = [cap, f":hourglass: *Time Gaps — {canonical} — {pretty}*"]
    for i, img in enumerate(board.pngs or [board.png]):
        try:
            web.files_upload_v2(channel=chan, file=str(img),
                                filename=names[min(i, 1)],
                                initial_comment=caps[min(i, 1)])
        except Exception as e:  # noqa: BLE001 — image 2 failing ≠ image 1 lost
            traceback.print_exc()
            say(f":x: {'The board' if i == 0 else 'The Time Gaps board'} "
                f"rendered but Slack wouldn't take the image — "
                f"{type(e).__name__}: {str(e)[:160]}")
