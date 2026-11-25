"""Which order did this result email come back from -- the background check,
or the drug test?

THE EMAIL DOES NOT SAY. Rafael Hidalgo, on Loom
`ba6bf293febd4e4baf4dbb01c9912ecc` (2026-11-25, at 1:36): "that's the only
email we get when I do their back or their drug tests, so it doesn't actually
say drug tests on it."

`parse.classify` reads the SUBJECT -- "E-Invite for X is Complete",
"Background Check for X is complete" -- so the moment an office starts sending
drug tests, its drug results land in the background-check column. For somebody
with both in flight the later email overwrites the earlier, and a rep can end
up reading as background-check-complete on the strength of a drug screen. That
is a compliance answer written off the wrong evidence, which is the same
family of mistake as the "never mark Passed without a Score PASS" rule in
`parse`.

THE ONLY SIGNAL IS WHAT WE SENT. Since the mail carries nothing, attribution
has to come from our own record of who was invited to what and when: the
`send_bgc` and `send_drug` rows on the 'Admin Requests' tab, written by
`office_admin.actions` every time somebody presses a button.

THE RULE IS DRIVEN BY THE DRUG INVITE, NOT THE BACKGROUND ONE, and that is
deliberate:

    no drug invite for this person   -> BACKGROUND CHECK. It cannot be a drug
                                        result if we never ordered one.
    drug invite, no background one   -> DRUG.
    both, and both could have landed -> UNKNOWN. Held, never written.

So an office that has never sent a drug test is completely unaffected -- every
event still attributes to the background check, exactly as before. Ambiguity
only appears once drug orders actually start going out, which is the property
that lets this ship without changing anybody's current behaviour.

A DRY RUN ORDERED NOTHING. `drug_mode` ships "dry" everywhere, and a dry send
reports who it WOULD invite and places no order -- so no email will ever come
back from it. Counting those as invites would hold a whole office's real
background-check results the first time somebody pressed the test button.
The result JSON says `status: dry_run`, which is what distinguishes them.

AND A SEND THAT MIGHT HAVE GONE OUT COUNTS AS ONE. Anything that is not an
outright "nothing was ordered" is treated as a real invite, because the two
errors are not symmetrical: over-counting holds a result for a human to look
at, and under-counting files a drug screen as a background check without
telling anybody.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from automations.bg_check_sync.parse import norm

BGC = "bgc"
DRUG = "drug"
UNKNOWN = "unknown"

# The two actions on 'Admin Requests' that put an order into Sterling.
# office_admin.config's SEND_BGC / SEND_DRUG -- named here rather than
# imported so this module does not drag the office-admin page's dependencies
# into the nightly run.
SEND_BGC = "send_bgc"
SEND_DRUG = "send_drug"

_STAMP = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class Invite:
    """One person, one order, one day."""
    key: str        # parse.norm of "Last, First"
    kind: str       # BGC or DRUG
    on: dt.date


def _day(stamp: str) -> Optional[dt.date]:
    """The DATE out of an 'Admin Requests' stamp or an email's date header.

    Only the day matters: an invite and its result never need separating by
    hours, and the two sources are written in different shapes anyway
    ("2026-11-25 08:41:02" from the sheet, an ISO-ish string from the mail).
    Anything unreadable is None, which callers treat as "could be anything".
    """
    s = str(stamp or "").strip()
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, _STAMP).date()
    except (TypeError, ValueError):
        pass
    try:                        # "2026-11-25", "2026-11-25T08:41:02+00:00"
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _key(first: str, last: str) -> str:
    return norm("%s, %s" % (str(last or "").strip(), str(first or "").strip()))


def _ordered_nothing(result: str) -> bool:
    """True when this row's own answer says no order was placed.

    Only a DRY RUN is certain: it fills the whole form and stops before Send
    Invites. A failure is NOT counted here -- `judge_job` itself says an
    unanswered send is "UNCONFIRMED ... check Sterling before pressing Send
    again", so a failed row may well have invited somebody.
    """
    try:
        res = json.loads(result or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(res, dict) and res.get("status") == "dry_run"


def invites_from_requests(rows: Iterable[Dict[str, str]]) -> List[Invite]:
    """'Admin Requests' rows -> the invites they placed.

    Rows whose Details cannot be read are SKIPPED rather than guessed at; an
    unreadable row is one we know nothing about, and inventing a background
    check for it would be the mistake this module exists to stop.
    """
    out: List[Invite] = []
    for r in rows or []:
        action = str(r.get("Action") or "").strip().lower()
        kind = {SEND_BGC: BGC, SEND_DRUG: DRUG}.get(action)
        if not kind:
            continue
        if _ordered_nothing(r.get("Result") or ""):
            continue
        on = _day(r.get("Requested At") or "")
        if on is None:
            continue
        try:
            details = json.loads(r.get("Details") or "{}")
        except (TypeError, ValueError):
            continue
        for p in (details or {}).get("people") or []:
            if not isinstance(p, dict):
                continue
            key = _key(p.get("first_name"), p.get("last_name"))
            if key:
                out.append(Invite(key=key, kind=kind, on=on))
    return out


def attribute(event, invites: Iterable[Invite]) -> str:
    """BGC, DRUG or UNKNOWN for one parsed result email.

    An event we cannot date is treated as "after everything", because the
    alternative -- assuming it predates a drug invite -- is the assumption
    that files a drug screen as a background check.
    """
    key = _key(getattr(event, "first", ""), getattr(event, "last", ""))
    mine = [i for i in invites or [] if i.key == key]
    drug = [i for i in mine if i.kind == DRUG]
    if not drug:
        return BGC
    when = _day(getattr(event, "date", "") or "")
    if when is not None:
        drug = [i for i in drug if i.on <= when]
        if not drug:
            # Every drug order for them was placed AFTER this email, so this
            # one cannot have come from any of them.
            return BGC
        bgc = [i for i in mine if i.kind == BGC and i.on <= when]
    else:
        bgc = [i for i in mine if i.kind == BGC]
    return DRUG if not bgc else UNKNOWN


def split(events: Iterable, invites: Iterable[Invite]) -> Tuple[List, List]:
    """(background-check events, held events).

    Held = everything we could not attribute to a background check: the drug
    results and the ones that could be either. They never reach the sheet.
    `held_names` turns them into something to show a person.
    """
    invites = list(invites or [])
    keep, held = [], []
    for ev in events or []:
        (keep if attribute(ev, invites) == BGC else held).append(ev)
    return keep, held


def held_names(held: Iterable, invites: Iterable[Invite]) -> List[Tuple[str, str]]:
    """[(name, why)] for the held events, de-duplicated, for a human to read.

    SAYING WHICH KIND OF DOUBT IT IS matters: "this is their drug test" is an
    answer and needs no action, while "we cannot tell which" is a result
    sitting unapplied and somebody has to look. One message for both would
    make the second invisible inside the first.
    """
    invites = list(invites or [])
    seen: Dict[str, str] = {}
    for ev in held or []:
        name = ("%s %s" % (getattr(ev, "first", ""), getattr(ev, "last", ""))).strip()
        verdict = attribute(ev, invites)
        why = ("this looks like their drug test, not their background check"
               if verdict == DRUG else
               "a result came back and we can't tell whether it's the "
               "background check or the drug test — both were sent")
        # The ambiguous message wins where somebody has both, because it is
        # the one that needs doing something about.
        if name and (name not in seen or verdict == UNKNOWN):
            seen[name] = why
    return sorted(seen.items())
