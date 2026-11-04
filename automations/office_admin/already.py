"""Who on today's offer list already has a background check (Megan 2026-11-04).

Raf's real list on 11/04 had Milandi Koch and Myles Williams on it -- both had
ALREADY finished their Sterling e-invite that day (sent by hand). Sterling
refuses a second invite to the same email anyway, but the admin couldn't tell,
so those people are shown "already done" and left UNTICKED (still tickable).

Two sources, either one enough:
  1. this page's own log -- a send_bgc row on 'Admin Requests' for this office
     that went out (done / at office computer), matched by EMAIL. Every office.
  2. Sterling's own emails -- "Background Check E-Invite for Last, First is
     Complete", "Background Check for Last, First is complete/Consider",
     "... Score PASS/FAIL". They land in the ICD's OWN inbox, so this works
     only where this computer can read that inbox (Raf: raffi127, the app
     password bg_check_sync already uses). SUBJECTS ONLY -- the names are in
     them -- so a press costs one quick IMAP search, not a body per email.
     Can't read the inbox = this source is just skipped, never an error.
"""
from __future__ import annotations

import datetime as dt
import email
import re
from email.header import decode_header
from typing import Dict, List, Optional

from automations.office_admin import config as C
from automations.office_admin import sheets as S

LOOKBACK_DAYS = 14
# Subject shapes that mean "this person already has a check going or done".
_SUBJECT_NAME = [
    re.compile(r"E-Invite for (.+?) is Complete", re.I),
    re.compile(r"^Background Check for (.+?) is (?:complete|consider)\b", re.I),
    re.compile(r"Background Check Complete.*? - (.+?)(?: - Score|$)", re.I),
]


def _norm(s: str) -> str:
    from automations.bg_check_sync.parse import norm
    return norm(s or "")


def person_key(first: str, last: str) -> str:
    """first given name + full last name, folded -- 'Myles' + 'Williams'."""
    f = _norm(first).split()
    return "%s|%s" % (f[0] if f else "", _norm(last))


def name_from_subject(subject: str) -> Optional[str]:
    """'Williams, Myles Gregory' out of a Sterling subject, else None."""
    for rx in _SUBJECT_NAME:
        m = rx.search(subject or "")
        if m and "," in m.group(1):
            return m.group(1).strip()
    return None


def key_from_sterling_name(last_comma_first: str) -> Optional[str]:
    last, _, rest = (last_comma_first or "").partition(",")
    rest = rest.strip()
    if not (last.strip() and rest):
        return None
    return person_key(rest.split()[0], last.strip())


def sent_from_page(reqs: List[Dict], office_key: str,
                   days: int = LOOKBACK_DAYS, today: Optional[dt.date] = None) -> Dict[str, str]:
    """{email: 'M/D'} for people this page already sent for this office."""
    today = today or dt.date.today()
    out: Dict[str, str] = {}
    for r in reqs:
        if (r.get("Office Key") or "").lower() != office_key or r.get("Action") != C.SEND_BGC:
            continue
        if r.get("Status") not in (C.DONE, C.AT_OFFICE):
            continue
        res = S.loads(r.get("Result"))
        if res.get("status") == "dry_run":
            continue                      # a test run sent nobody
        try:
            when = dt.datetime.strptime(r.get("Requested At", "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - when).days > days:
            continue
        for p in S.loads(r.get("Details")).get("people", []):
            e = str(p.get("email") or "").strip().lower()
            if e:
                out[e] = "%d/%d" % (when.month, when.day)
    return out


def sterling_subjects(days: int = LOOKBACK_DAYS) -> List[tuple]:
    """[(subject, 'M/D')] of Sterling mails in the inbox this computer can
    read (bg_check_sync's account). Raises when it can't."""
    from automations.bg_check_sync import email_source as ES
    M = ES._connect()
    try:
        since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, '(FROM "%s" SINCE %s)' % (ES.FADV_SENDER, since))
        ids = (data[0] or b"").split()
        out = []
        if not ids:
            return out
        typ, rows = M.fetch(b",".join(ids), "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
        for row in rows or []:
            if not isinstance(row, tuple):
                continue
            msg = email.message_from_bytes(row[1])
            subj = "".join(t.decode(enc or "utf-8", "replace") if isinstance(t, bytes) else t
                           for t, enc in decode_header(msg.get("Subject", "")))
            try:
                d = email.utils.parsedate_to_datetime(msg.get("Date"))
                md = "%d/%d" % (d.month, d.day)
            except Exception:  # noqa: BLE001
                md = ""
            out.append((" ".join(subj.split()), md))
        return out
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def sterling_done(subjects: List[tuple]) -> Dict[str, str]:
    """{person_key: 'M/D'} from Sterling subjects (latest date wins)."""
    out: Dict[str, str] = {}
    for subj, md in subjects:
        name = name_from_subject(subj)
        k = key_from_sterling_name(name) if name else None
        if k:
            out[k] = md or out.get(k, "")
    return out


def mark(people: List[Dict], *, page_log: Dict[str, str], sterling: Dict[str, str]) -> List[Dict]:
    """Each person + 'already': '' or a short reason for the admin."""
    out = []
    for p in people:
        q = dict(p)
        e = str(p.get("email") or "").strip().lower()
        k = person_key(p.get("first_name", ""), p.get("last_name", ""))
        if e and e in page_log:
            q["already"] = "already sent from here %s" % page_log[e]
        elif k in sterling:
            q["already"] = "already done in Sterling %s" % sterling[k]
        else:
            q["already"] = ""
        out.append(q)
    return out


def check(people: List[Dict], reqs: List[Dict], office_key: str, log=print) -> List[Dict]:
    """mark() with both sources; the Sterling inbox only if readable here."""
    page_log = sent_from_page(reqs, office_key)
    try:
        sterling = sterling_done(sterling_subjects())
    except Exception as e:  # noqa: BLE001 -- no inbox here: page log only
        log("already: Sterling inbox not readable here (%s)" % type(e).__name__)
        sterling = {}
    return mark(people, page_log=page_log, sterling=sterling)
