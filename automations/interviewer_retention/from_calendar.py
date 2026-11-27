"""One AppStream Calendar row -> the values an ARS row holds.

Every rule here was checked against Raf's office (11280), Tue 2026-11-24, read
live off the Calendar day view (p=102) and matched by applicant name to what
the interviewers typed in his ARS tab the same day:

  INTERVIEWER: the row's "Done By" dropdown (who ran it; NOT the login that
    clicked). 62 of 62 showed-up applicants map one-to-one onto the ARS
    dropdown names via interviewer_names.json. "None" = the owner ran it.
    A name missing from the map is never guessed: UnknownInterviewer.

  1st ROUND, Qualify (60 of 62 agree; AppStream is truth on the 2):
    Action cell starts "Disqualified"  -> Disqualify
    Action cell starts "Declined"      -> Disqualify - Declined
    Show Up radio = 2 (no)             -> a no-show: no ARS row at all
    otherwise (radio 1, or "2nd On ...", "First Day of Sales") -> Qualify

  1st ROUND, Answer Call + Booked, from Follow Up Status (qualified only):
    Invite to next - Booked     -> Answered, Booked        (34 of 34)
    Declined Next Round         -> Answered, Not Booked    (6 of 6)
    Invite to next - SMS sent   -> No Answer               (5 of 6)
    Invite to next - NA         -> No Answer               (none that day)
    anything else / nothing     -> left blank, as the interviewers do
  Megan 2026-11-27: "copy what is already being entered on the sheet". Over
  10/12-11/22 (1,361 qualified rows) they typed only Answered+Booked 1,169,
  Answered+Not Booked 98, No Answer 92, blank 2 -- never "Not Contacted".

  2nd ROUND, Showed Up to 2nd Round (37 of 37):
    Show Up shows the offer dropdown (Yes OR No) -> Showed
      (a "No" there is the leader saying no, not a no-show)
    otherwise, Follow Up Status "Rescheduled Requested" -> Reschedule Requested
              Follow Up Status "Cancelled"             -> Cancelled
              anything else                            -> No Show
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Tuple

from automations.interviewer_retention import boxes as bx

NAMES_FILE = Path(__file__).with_name("interviewer_names.json")
UNSET = ""          # Answer Call for a qualified person with no invite status: blank


class UnknownInterviewer(KeyError):
    """A Done By name the office's map doesn't have. Flag it; never guess."""


def _key(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def load_names(office: str, path: Path = NAMES_FILE) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {_key(k): v for k, v in data.get(office, {}).items() if not k.startswith("_")}


def interviewer(done_by: str, names: Dict[str, str]) -> str:
    k = _key(done_by) or "none"
    if k not in names:
        raise UnknownInterviewer(done_by)
    return names[k]


def first_round(show_up: str, action: str, follow_up: str) -> Optional[Tuple[str, object, str]]:
    """(qualify, answer, booked), or None for a no-show (the ARS has no row)."""
    act = (action or "").strip().lower()
    if act.startswith("disqualified"):
        return bx.DISQUALIFY, "", ""
    if act.startswith("declined"):
        return bx.DECLINED, "", ""
    if (show_up or "").strip().lower() in ("radio2", "no show"):
        return None
    fus = _key(follow_up)
    if fus == "invite to next booked":
        return bx.QUALIFY, bx.ANSWERED, bx.BOOKED
    if fus == "declined next round":
        return bx.QUALIFY, bx.ANSWERED, "Not Booked"
    if fus in ("invite to next sms sent", "invite to next na"):
        return bx.QUALIFY, bx.NO_ANSWER, ""
    return bx.QUALIFY, UNSET, ""


def second_round(offer_shown: bool, follow_up: str) -> str:
    if offer_shown:
        return bx.SHOWED
    fus = _key(follow_up)
    if fus.startswith("reschedule"):
        return bx.RESCHEDULE
    if fus == "cancelled":
        return bx.CANCELLED
    return bx.NO_SHOW
