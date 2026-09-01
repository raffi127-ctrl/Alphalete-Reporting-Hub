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


# NO CAMPAIGN PICKER HERE, deliberately (Megan 2026-09-01: "the enrollment can
# have the option but I don't think Jiraiya needs it"). The campaign is a
# property of the OFFICE, not of a request: enrollment declares it, which is
# how Jay Turnage has one entry per campaign, and campaign_for_office answers
# for everyone who runs exactly one. Asking again on every /knocks would be
# putting a question to the requester that the system already knows.
#
# The plumbing stays — service.board_for(campaign=…) and the (name, days,
# campaign) job — because enrollment-driven callers use it.


LAST_WEEK_VALUE = "last_full_week"


def last_full_week(today: dt.date | None = None) -> tuple:
    """(monday, sunday) of the last FULLY COMPLETED Mon-Sun week.

    Not "the last 7 days" and not the week in progress: a full prior week is
    always a completed one, which is also the week the apps columns can be read
    from the harvest for free. So the checkbox and the apps rule agree by
    construction — tick it and the board always carries Total Apps, Average App
    per Rep and Avg Talk To's per App.
    """
    from automations.shared.report_week import week_ending
    today = today or service.central_today()
    sunday = week_ending(today) - dt.timedelta(days=7)
    return sunday - dt.timedelta(days=6), sunday


def modal(today: dt.date | None = None) -> dict:
    """The popup. `today` is injectable so the default date is testable."""
    # TODAY, not yesterday (Megan 2026-09-01). The popup opened on yesterday
    # because the morning report is about yesterday — but somebody typing
    # /knocks at 2pm is almost always asking how today is going, and having to
    # change the date every time made the default wrong more often than right.
    # A today board comes back marked "Today so far — the day isn't over".
    target = today or service.central_today()
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
            # One tick instead of two datepickers for the commonest range
            # anyone asks for (Megan 2026-09-01: "a 'last full week' checkbox
            # where they don't have to go into both dropdowns"). It OVERRIDES
            # the two dates rather than sitting alongside them — a request
            # cannot be both, and silently honouring one of the two would be
            # worse than either.
            {"type": "input", "block_id": "week", "optional": True,
             "label": {"type": "plain_text", "text": "Or just:"},
             "element": {
                 "type": "checkboxes", "action_id": "v",
                 "options": [{
                     "text": {"type": "plain_text",
                              "text": "Last full week (Mon–Sun)"},
                     "value": LAST_WEEK_VALUE}]},
             "hint": {"type": "plain_text",
                      "text": "Tick this and the two dates above are "
                              "ignored."}},
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


def parse_dm(text: str) -> Optional[Tuple[str, dt.date, dt.date, "str | None"]]:
    """(office, start, end, campaign) for a DM like `knocks Chan Park` / `knocks chan
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
    name = " ".join(rest).strip()
    # A trailing campaign word ("… jay turnage energywell") belongs to the
    # REQUEST, not the name. Peeled only when the office actually has a
    # campaign by that word, so an office genuinely called "... Energy" is
    # never mangled.
    campaign = None
    if len(rest) > 1:
        from automations.rashad_metrics.knocks_pull import campaign_by_keyword
        head = " ".join(rest[:-1]).strip()
        cid = campaign_by_keyword(service.resolve_office(head), rest[-1])
        if cid:
            name, campaign = head, cid
    return name, start, end, campaign


def handle_dm(web, user_id: str, text: str) -> None:
    """A plain DM that starts with 'knocks'. Callers check parse_dm first; this
    also answers the bare word with the one line of help it needs."""
    parsed = parse_dm(text)
    if parsed is None:
        return
    office, target, end, campaign = parsed
    if not office:
        try:
            chan = web.conversations_open(users=user_id)["channel"]["id"]
            web.chat_postMessage(channel=chan, text=(
                ":door: Tell me whose office — e.g. `knocks Chan Park`, or "
                "`knocks Chan Park 2026-08-21` for a specific day, or "
                "`knocks Chan Park 2026-08-18 to 2026-08-23` for a stretch of "
                "days. (Today is the default.)"))
        except Exception:  # noqa: BLE001
            pass
        return
    process(web, user_id, office, target, end, campaign=campaign)


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
    # The checkbox wins over the pickers, as its hint says.
    picked = (vals.get("week", {}).get("v", {})
              .get("selected_options") or [])
    if any(o.get("value") == LAST_WEEK_VALUE for o in picked):
        target, end = last_full_week()

    process(web, payload["user"]["id"], office, target, end)


def process(web, user_id: str, office: str, target: dt.date,
            end: Optional[dt.date] = None,
            campaign: Optional[str] = None) -> None:
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

    # AN OFFICE WITH TWO CAMPAIGNS IS ASKED ABOUT, not guessed at. Silently
    # picking one would hand back half of Jay's day as though it were all of
    # it. Everyone else — one campaign, which is everyone — never sees this.
    if campaign is None:
        from automations.rashad_metrics.knocks_pull import campaigns_for
        options = campaigns_for(service.resolve_office(office))
        if options:
            say(f":grey_question: *{office}* runs {len(options)} campaigns — "
                "which one?\n"
                + "\n".join(f"• `knocks {office} {key}`  ({label})"
                             for label, _cid, key in options))
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
    # The comparison office counts toward the wait: its days are pulled to
    # match the span, so a request can take a minute even when every one of
    # our own days is already on disk.
    need, need_cmp = service.pull_plan(canonical, target, end)
    total = len(service.span_days(target, end))
    if not need and not need_cmp:
        say(f":door: Getting *{canonical}*'s knocks for {pretty} — one second.")
    else:
        busy = service.ownerville_busy()
        if busy:
            say(f":door: *{canonical}* — {pretty}. The scheduled reports are "
                "using Ownerville right now, so I'm queued behind them. I'll "
                "send the board as soon as they're done — no need to ask "
                "again.")
        elif not need:
            # Ours are all on hand; the wait is entirely the comparison line.
            # Say which office we're waiting on, or the delay looks unexplained.
            say(f":door: I have *{canonical}*'s knocks for {pretty} — pulling "
                f"*{service.compare_office()}*'s numbers for the same stretch "
                "so the comparison lines up. About a minute.")
        else:
            # Say how many days are actually being scraped, not how many were
            # asked for: "6 days" when 5 are already on disk reads as a wait
            # that never comes.
            how_long = ("about a minute" if len(need) == 1
                        else f"a minute or two for {len(need)} days")
            got = (f" ({total - len(need)} of the {total} days already on "
                   "hand.)" if total > len(need) else "")
            say(f":door: Pulling *{canonical}*'s knocks for {pretty} from "
                f"Ownerville — {how_long}.{got}")

    try:
        with _PULL_LOCK:
            board = service.board_for(office, target, end,
                                      campaign=campaign,
                                      logfn=lambda m: None)
    except Exception as e:  # noqa: BLE001 — every failure answers in words
        traceback.print_exc()
        if service.access_gap(e) and service.unknown_office(office):
            # Ownerville says "not found" for a misspelling AND for an office
            # we have no access to, so the permissions line below used to be
            # promised to names that simply aren't ICDs ("Frank Castillo",
            # 2026-08-31 — no such office; Francisco Castillo is the one on
            # the roster). Only claim a permissions gap for a name we know.
            # OWNERVILLE'S OWN near-matches first. They come from the live
            # site, so they beat any roster guess: the office exists and only
            # the spelling was wrong.
            near = service.ownerville_near_matches(e)
            if near:
                # READY-TO-SEND COMMANDS, not bare names. A DM only counts as
                # a request when it LEADS with "knocks" — parse_dm returns None
                # for "muhammad ui haque" — so "send me one of those exactly"
                # was an instruction that quietly does nothing (Megan
                # 2026-09-01: "if someone responds to this with the correct
                # name, is Jiraiya going to read it?"). No.
                say(f":grey_question: I couldn't find *{office}* in "
                    "Ownerville. These are close — send one back and I'll "
                    "pull it:\n"
                    + "\n".join(f"• `knocks {n}`" for n in near))
                return
            hint = service.suggest_office(office)
            say(f":grey_question: I don't have an office called *{office}* on "
                "the roster"
                + (f" — did you mean *{hint}*?" if hint else
                   ". Either the spelling is off, or that office was never "
                   "added to these reports — tell me the name as it reads on "
                   "the report and I'll pull it."))
        elif service.access_gap(e):
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
        # No "Time Gaps below" — the TeleMapper board carries the gap columns
        # itself, so there is no second image (render.needs_time_gaps).
        cap += ("\n_This office knocks without a Disposition page, so "
                "Ownerville records knock activity — times and gaps — not "
                "knock counts._")
    if board.is_range:
        # A range board is a FOLD, and a screenshot of it will outlive this
        # message — so what the numbers mean has to ride on the post itself.
        # Kept SHORT: the long version buried the part people actually needed.
        cap += (f"\n_{board.days} days added together — First and Last Knock "
                "are each rep's average over the days they knocked._")

    # WHY the apps columns are there, or why they are not (Megan 2026-09-01).
    # Three columns appearing and disappearing between requests reads as a bug
    # unless the reply says what decides it, and the rule is not guessable:
    # a completed week can be read from the harvest for free, the current week
    # cannot.
    _APP_COLS = ("• Total Apps\n• Average App per Rep\n"
                 "• Avg Talk To's per App")
    if board.apps_reps:
        cap += ("\n\nSince every date you picked is in a fully completed "
                f"week (Mon–Sun), these are included too:\n{_APP_COLS}")
    elif board.apps_skipped == "current_week":
        cap += ("\n\n_These dates are in the current week, so apps aren't "
                "final yet — pick a completed week (Mon–Sun) and you'll also "
                f"get:_\n{_APP_COLS}")
    elif board.apps_skipped == "crossed_weeks":
        cap += ("\n\n_This span crosses two weeks, so the apps columns are "
                "left off rather than counting part of one._")
    if board.partial:
        # Today's numbers keep moving; say so on the image itself, because a
        # screenshot of it will outlive this message.
        cap += ("\n_Today so far — the day isn't over, these numbers will "
                "grow._")
    # No "From this morning's run" line (Megan 2026-09-01). Where the numbers
    # were read from is our plumbing, not the reader's business — and it read
    # like a caveat on numbers that need none.

    # Most shapes are ONE image now; only the wireless board still comes back
    # with a Time Gaps companion, so the second name/caption stays available.
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
