"""The onboarding board, written from an office's OWN computer.

Megan, 2026-11-16: *"we need Raf's fully running on HIS ECO machine, not the
Lucys."*

WHY THIS EXISTS. An office Mac has no Google access at all -- not a service
account, not a signed-in browser, nothing. It reaches our sheets only through
the Apps Script relay. Every module in `icd_onboarding` writes the board with
gspread, so every step had to run on a Lucy, which is how one office's
onboarding ended up living on shared machines signed in as somebody else. Lucy
2 read 0 of 10 on Raf's people on 2026-11-10 for exactly that reason: it signs
into OwnerVille as Carlos.

This is the same two writes the board already does -- add this week's people,
tick a step -- aimed at the relay instead of at gspread. The step modules keep
their logic; only the last inch changes.

WHAT IT IS NOT. Not a general sheet API. It can add rows and it can tick, and
that is all it can do: it cannot create a tab, add a column, delete a row,
clear a cell, or write a column a person owns (Classroom, Gender, Location --
nothing we read holds them, so a machine writing one would be inventing a fact
that lands on a payroll record). A machine that can only add is a machine that
cannot lose somebody's work.

AUTHORISATION is the office key this Mac was enrolled with, the same one the
knocks hand-over and the job queue use. The relay checks it before either call
is reached, so an office can only ever touch its own board. There is
deliberately no admin session here: nobody is sitting at an office Mac to sign
in at 6:30am, which is what made the extension's board calls unusable for this.

THE RELAY IS DEPLOYED BY HAND. These two calls answer "unknown call" until
`resources/icd-alerts-relay.gs` is pasted into Apps Script, so every function
here treats that as a plain not-available rather than a crash:
[[reference_apps_script_relay_gotchas]].
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict, Iterable, List, Optional, Sequence

from automations.icd_onboarding import board as B
# BOTH `week` and `weekTab` go on every call. `weekTab` ("OBCL 11.23") is
# the sheet to open in an office's own workbook; `week` ("11/22/2026") is
# the Week of value to filter by on the old stacked tab. An office part-way
# through the move needs whichever one its book actually has, and the relay
# picks -- sending only one would break the other shape.
# The one name this needs from the per-week book, out of the module that
# SHIPS: `book`'s siblings open Google Sheets, which an office's own
# computer has no access to -- and this file is that machine's only way
# to reach its board.
from automations.shared import onboarding_week as K


class RelayBoardError(RuntimeError):
    """The relay answered, and the answer was no."""


# The relay says this when it is running code older than the calls below. It is
# a deployment fact, not a fault with the run: the caller falls back to gspread
# rather than failing a whole hourly pass over it.
NOT_DEPLOYED = "unknown call"


def _endpoint(office_key: str) -> Dict[str, str]:
    from automations.icd_alerts import relay as R
    return R._endpoint(office_key)


def available(office_key: str = "") -> bool:
    """Is there a relay enrolment on THIS machine for that office?

    False on a box that was never enrolled -- Megan's laptop, a dev checkout --
    which is the signal to keep writing the board with gspread there.
    """
    try:
        _endpoint(office_key)
        return True
    except Exception:       # noqa: BLE001 -- no enrolment is an answer, not a fault
        return False


def _call(office_key: str, what: str, args: Dict) -> Dict:
    """One relay call. Raises RelayBoardError with the relay's own words."""
    from automations.icd_alerts import relay as R
    rec = _endpoint(office_key)
    body = {"office_key": rec["office_key"], "key": rec["relay_key"],
            what: args}
    raw = R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
    try:
        out = json.loads(raw)
    except ValueError:
        raise RelayBoardError(
            "the relay answered a web page, not JSON -- is it deployed? (%s)"
            % " ".join(raw.split())[:120])
    if not out.get("ok"):
        raise RelayBoardError(str(out.get("error") or "no reason given"))
    return out


def week(office_key: str, week_start: dt.date) -> List[Dict]:
    """This office's rows for that week, read through the relay.

    A step has to know what a cell already says before it can obey the on-only
    rule, and on an office Mac there is no other way to find out. Same function
    the extension's panel reads with, reached with the office key instead of a
    person's sign-in.

    The relay returns the row dicts keyed by the board's own column names, so
    everything in `board.py` that already works on rows works on these.
    """
    out = _call(office_key, "board_read",
                {"week": B.week_label(week_start),
                 "weekTab": K.tab_name(week_start)})
    return list(out.get("people") or [])


def seed(office_key: str, week_start: dt.date, people: Iterable[Dict],
         *, dry_run: bool = True, log=print) -> Dict:
    """Add this week's people to the board. Returns the relay's own answer.

    Idempotent, because the seed runs every hour: a second pass adds whoever
    the calendar has gained since the last one and touches nothing else. A row
    that is already there is never rewritten -- not even its email -- because a
    hand correction on the board beats what the calendar says, and the calendar
    is the thing that is usually out of date.

    That same rule is what keeps somebody the ICD marked off from coming back:
    their row still exists, so they count as already there and are skipped.

    THE ONE THING THE SHEET SIDE DOES AND THIS DOES NOT: `sheet.move_starts`,
    a start day the calendar has pushed back, written onto the row already
    there. It needs a relay op that OVERWRITES a cell, and the only writer
    here is `board_tick`, which is on-only on purpose. Not built, because no
    office is served through the relay yet -- every board is read and written
    from our machines ([[feedback_eco_migration_comes_last]]) -- and it is
    listed with the rest of that move rather than half-built now.
    """
    rows = B.seed_rows(people, started=week_start)
    week = B.week_label(week_start)
    payload = [{"first": r.get("Name", ""), "last": r.get("Last Name", ""),
                "email": r.get("Email", ""), "phone": r.get("Phone", ""),
                "start": r.get("Start", "")} for r in rows]
    if dry_run:
        log("  (dry run — would offer %d person(s) to the relay for week %s)"
            % (len(payload), week))
        return {"ok": True, "added": 0, "names": [], "dry_run": True}
    out = _call(office_key, "board_seed",
                {"week": week, "weekTab": K.tab_name(week_start),
                 "people": payload})
    log("  seed: %d added, %d already on week %s"
        % (int(out.get("added") or 0), int(out.get("already") or 0), week))
    return out


def tick(office_key: str, week_start: dt.date, column: str,
         names: Sequence[str], *, dry_run: bool = True, log=print) -> Dict:
    """Tick `column` for `names`. ON ONLY.

    A cell that already says something is left exactly as it is, and somebody
    NOT in `names` is never cleared: a tick is evidence that something
    happened, and nothing here is entitled to say it did not. The relay stamps
    the date itself, so a machine with a wrong clock cannot write a wrong one.

    An empty `names` sends nothing at all rather than sending a blank -- an
    unread step must leave its column alone ([[feedback_empty_means_proven_zero]]).
    """
    week = B.week_label(week_start)
    want = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not want:
        log("  %s: nobody to tick" % column)
        return {"ok": True, "changed": 0, "names": []}
    if dry_run:
        log("  (dry run — would tick %s for %d on week %s)"
            % (column, len(want), week))
        return {"ok": True, "changed": 0, "names": [], "dry_run": True}
    out = _call(office_key, "board_tick",
                {"week": week, "weekTab": K.tab_name(week_start),
                 "column": column, "names": want})
    log("  %s: %d ticked, %d already written"
        % (column, int(out.get("changed") or 0), int(out.get("left_alone") or 0)))
    return out


def advance(office_key: str, week_start: dt.date, column: str,
            values: Dict[str, str], *, dry_run: bool = True, log=print) -> Dict:
    """Move one of the two background-check answers forward.

    FORWARDS ONLY, judged by the relay against its own copy of the ranking, so
    a late "Sent" email can never pull somebody back from Passed. Blank means
    not sent, and a blank value is dropped rather than written -- the chase
    sheet counts an empty cell as outstanding and that must stay true.
    """
    if column not in B.STATUS_STEPS:
        raise ValueError(
            "%r is not one of the status columns (%s). Everything else is a "
            "tick -- use tick()." % (column, ", ".join(B.STATUS_STEPS)))
    week = B.week_label(week_start)
    want = {str(k).strip(): str(v or "").strip()
            for k, v in (values or {}).items()
            if str(k).strip() and str(v or "").strip()}
    if not want:
        log("  %s: nothing to say" % column)
        return {"ok": True, "changed": 0, "names": []}
    if dry_run:
        log("  (dry run — would set %s for %d on week %s)"
            % (column, len(want), week))
        return {"ok": True, "changed": 0, "names": [], "dry_run": True}
    out = _call(office_key, "board_tick",
                {"week": week, "weekTab": K.tab_name(week_start),
                 "column": column, "values": want})
    log("  %s: %d written, %d already further along"
        % (column, int(out.get("changed") or 0), int(out.get("left_alone") or 0)))
    return out


def is_not_deployed(err: Exception) -> bool:
    """Is this failure "the relay has not been updated yet"?

    Worth telling apart from a real refusal: the first means fall back to
    gspread and carry on, the second means this office's board genuinely will
    not take the write and somebody should hear about it.
    """
    return NOT_DEPLOYED in str(err).lower()


def mark(office_key: str, week_start: dt.date, names: Iterable[str],
         *, reason: str = "", restore: bool = False,
         dry_run: bool = True, log=print) -> Dict:
    """Put people in the board's REMOVED section, or take them back out of it.

    THE ROW STAYS EITHER WAY. This is not a delete and not a hide-forever: the
    removed section is part of the board, and the row is still there to answer
    what happened to somebody months later (the relay's `_boardMark` says the
    same, and the panel has used it since 2026-11-11).

    `restore=True` puts them back and CLEARS the reason, so a row that came
    back does not keep the reason for a removal that was undone.

    The relay leaves a row that is already how you want it alone, so sending
    the same names twice changes nothing -- which is what makes this safe on a
    pass that runs again every night.
    """
    want = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not want:
        log("  removal: nobody to mark")
        return {"ok": True, "changed": 0}
    week = B.week_label(week_start)
    if dry_run:
        log("  (dry run — would %s %d on week %s%s)"
            % ("restore" if restore else "mark removed", len(want), week,
               "" if restore else ": %s" % reason))
        return {"ok": True, "changed": 0, "dry_run": True}
    out = _call(office_key, "board_mark",
                {"week": week, "weekTab": K.tab_name(week_start),
                 "names": want, "reason": reason,
                 "action": "restore" if restore else "terminate"})
    log("  %s: %d row(s) changed"
        % ("restored" if restore else "marked removed",
           int(out.get("changed") or 0)))
    return out
