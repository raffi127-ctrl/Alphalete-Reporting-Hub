"""What this job created, per account -- the audit's memory.

THE FILE IS A CACHE, NOT THE RECORD (2026-11-22). It used to be the only
place that knew what had been created, and it is a local file, so the job
could only ever run on the one machine that had it -- which is why this step
still runs on Lucy 1 while everything around it moved to the office's own
computer. Started anywhere else the file is simply absent, and an absent
memory is the worst possible answer here: the audit can never remove a card
it does not know about, and the adds would put a second copy of everybody on
the owner's phone, which is the complaint this group exists to avoid.

So the record lives where the contacts live. Every card this job creates
carries its own note -- "2nd round 10/31/2026 - Rafael Hidalgo (AppStream
11280) - second_round_contacts" -- which is the date, the owner, the office
and a signature saying we made it. `rebuild` reads that back, so a machine
with no file can work out what it would have known, and the file goes back
to being what it should have been: a way to avoid a Contacts read, not the
only copy of the truth.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Dict

from automations.second_round_contacts import config as C

TRACKED, HIRED, REMOVED = "tracked", "hired", "removed"
# Added from an office that is no longer on the owner's roster row (a closed
# funnel). Kept for good, never audited -- Eve 2026-11-05, Omar's 24153.
KEPT = "kept"


def load() -> Dict[str, Dict[str, dict]]:
    if C.STATE_PATH.exists():
        try:
            return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- a corrupt file must not kill the run
            return {}
    return {}


def save(state: Dict[str, Dict[str, dict]]) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def key_for(a: dict) -> str:
    """phone10 first, else email -- the same identity plan() dedupes on."""
    from automations.applicant_contacts.extract import phone10
    p = phone10(a.get("phone", "") or "")
    return ("p:" + p) if p else ("e:" + (a.get("email", "") or "").strip().lower())


def entry(a: dict, *, resource_name: str, owner: str, office: str,
          second_round: dt.date, display: str) -> dict:
    return {"resourceName": resource_name, "display": display,
            "first_name": a.get("first_name", ""), "last_name": a.get("last_name", ""),
            "phone": a.get("phone", ""), "email": a.get("email", ""),
            "owner": owner, "office": office,
            "second_round": second_round.isoformat(),
            "created": dt.date.today().isoformat(), "status": TRACKED}


# "2nd round 10/31/2026 - Rafael Hidalgo (AppStream 11280) - second_round_contacts"
_NOTE = re.compile(
    r"2nd round\s+(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(.*?)\s*"
    r"\(AppStream\s*([^)]*)\)")


def from_card(person: dict) -> dict:
    """One state entry from the Google contact this job created, or {}.

    Everything an entry holds is on the card: the note carries the second
    round's date, the owner and the office, the name and number are the
    card's own, and the resourceName is how the audit deletes it.

    `created` is NOT on the card and is not invented -- it takes the second
    round's date, which is the only dated fact there is. It is used for
    nothing but reading back, while `second_round` is what every rule
    measures from.
    """
    note = ""
    for b in person.get("biographies") or []:
        if "second_round_contacts" in (b.get("value") or ""):
            note = b.get("value") or ""
            break
    m = _NOTE.search(note)
    if not m:
        return {}
    try:
        day = dt.datetime.strptime(m.group(1), "%m/%d/%Y").date()
    except ValueError:
        return {}
    display = ((person.get("names") or [{}])[0].get("displayName")
               or (person.get("names") or [{}])[0].get("unstructuredName")
               or "").strip()
    phone = ""
    for ph in person.get("phoneNumbers") or []:
        if ph.get("value"):
            phone = ph["value"]
            break
    email = ""
    for e in person.get("emailAddresses") or []:
        if e.get("value"):
            email = e["value"].strip().lower()
            break
    # The name as typed on the card is "First Last (2R 10/31)". The tag is
    # ours, so it comes off before the name is split -- otherwise every
    # rebuilt person's surname is a date.
    bare = re.sub(r"\s*\(2R\s+\d{1,2}/\d{1,2}\)\s*$", "", display).strip()
    bits = bare.split()
    return {"resourceName": person.get("resourceName", ""),
            "display": display,
            "first_name": bits[0] if bits else "",
            "last_name": " ".join(bits[1:]) if len(bits) > 1 else "",
            "phone": phone, "email": email,
            "owner": m.group(2).strip(), "office": m.group(3).strip(),
            "second_round": day.isoformat(),
            "created": day.isoformat(), "status": TRACKED}


def rebuild(svc) -> Dict[str, dict]:
    """{key: entry} for one account, read off its own contacts.

    What a machine that has never run this job would otherwise not know. A
    card whose note will not parse is SKIPPED rather than guessed at: a
    wrong second-round date here is a card removed from somebody's phone a
    fortnight early.
    """
    from automations.second_round_contacts import contacts as K

    out: Dict[str, dict] = {}
    for person in K.ours(svc):
        e = from_card(person)
        if not e:
            continue
        k = key_for(e)
        if k and k not in out:
            out[k] = e
    return out


def for_account(account: str, svc=None, log=print) -> Dict[str, dict]:
    """This account's memory: the file if it has one, else the contacts.

    A rebuild is only ever used to FILL A GAP. An account the file already
    knows about is left exactly as it is, because the file carries statuses
    the cards cannot -- removed, kept, the reason and the date -- and a
    rebuild would quietly reset every one of them to tracked.
    """
    st = load()
    if account in st:
        return st[account]
    if svc is None:
        return {}
    got = rebuild(svc)
    log("  %s: no local record -- rebuilt %d card(s) off the account itself"
        % (account, len(got)))
    if got:
        st[account] = got
        save(st)
    return got
