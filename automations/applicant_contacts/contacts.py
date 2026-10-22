"""Add applicants to alphaletereception@gmail.com's Google Contacts.

General contact list, no group (Eve 2026-10-22). A contact created through the
People API lands in "Contacts" (myContacts) on its own.

Already there = same phone (last 10 digits) or same email on any contact in the
account. Then nothing is created -- reception may have filed them by hand
under a fuller name, and a second card for one person is what breaks texting.
"""
from __future__ import annotations  # Lucy runs Python 3.9

import datetime as dt
from typing import Dict, List, Tuple

from automations.applicant_contacts.extract import e164, phone10, pretty_phone
from automations.fiber_owners_distro import contacts_write as cw

ACCOUNT = "alphaletereception@gmail.com"


def service():
    return cw._service(ACCOUNT)


def existing_index(svc) -> Tuple[Dict[str, str], Dict[str, str]]:
    """({phone10: display name}, {email: display name}) for every contact."""
    phones: Dict[str, str] = {}
    emails: Dict[str, str] = {}
    token = None
    while True:
        resp = cw._retry(lambda: svc.people().connections().list(
            resourceName="people/me", pageSize=1000,
            personFields="names,phoneNumbers,emailAddresses",
            pageToken=token).execute())
        for p in resp.get("connections", []) or []:
            name = ((p.get("names") or [{}])[0].get("displayName") or "").strip()
            for ph in p.get("phoneNumbers") or []:
                d = phone10(ph.get("value", ""))
                if d:
                    phones.setdefault(d, name or pretty_phone(d))
            for e in p.get("emailAddresses") or []:
                v = (e.get("value") or "").strip().lower()
                if v:
                    emails.setdefault(v, name or v)
        token = resp.get("nextPageToken")
        if not token:
            return phones, emails


def problem(a: dict) -> str:
    """Why this entry can't be added, or '' if it can."""
    if not (a.get("first_name") or a.get("last_name")):
        return "no name"
    if not (a.get("phone") or a.get("email")):
        return "no phone or email"
    return ""


def plan(applicants: List[dict], phones: Dict[str, str],
         emails: Dict[str, str]) -> List[dict]:
    """One row per applicant: {applicant, status: add|exists|skip, why}."""
    rows = []
    seen_p, seen_e = set(), set()
    for a in applicants:
        why = problem(a)
        if why:
            rows.append({"applicant": a, "status": "skip", "why": why})
            continue
        p, e = a.get("phone", ""), a.get("email", "")
        hit = (phones.get(p) if p else None) or (emails.get(e) if e else None)
        if hit:
            rows.append({"applicant": a, "status": "exists",
                         "why": "already saved as %s" % hit})
            continue
        if (p and p in seen_p) or (e and e in seen_e):
            rows.append({"applicant": a, "status": "exists",
                         "why": "listed twice in this message"})
            continue
        seen_p.add(p)
        seen_e.add(e)
        rows.append({"applicant": a, "status": "add", "why": ""})
    return rows


def person_body(a: dict, added_by: str, today: dt.date) -> dict:
    body = {"names": [{"givenName": a.get("first_name", ""),
                       "familyName": a.get("last_name", "")}]}
    if a.get("phone"):
        body["phoneNumbers"] = [{"value": e164(a["phone"]), "type": "mobile"}]
    if a.get("email"):
        body["emailAddresses"] = [{"value": a["email"]}]
    body["biographies"] = [{"value": "Applicant - added from Slack by %s, %s"
                            % (added_by or "Jiraiya", today.strftime("%m/%d/%Y")),
                            "contentType": "TEXT_PLAIN"}]
    return body


def add_all(applicants: List[dict], *, write: bool, added_by: str = "",
            svc=None) -> List[dict]:
    """plan() + create the 'add' rows when write. Each row gains 'done'."""
    svc = svc or service()
    phones, emails = existing_index(svc)
    rows = plan(applicants, phones, emails)
    today = dt.date.today()
    for r in rows:
        r["done"] = False
        if r["status"] != "add" or not write:
            continue
        body = person_body(r["applicant"], added_by, today)
        cw._retry(lambda: svc.people().createContact(
            body=body, personFields="names").execute())
        r["done"] = True
    return rows


def full_name(a: dict) -> str:
    return " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x)


def summary(rows: List[dict], *, write: bool) -> str:
    """The Slack reply: what went in, what didn't and why."""
    if not rows:
        return (":thinking_face: I couldn't find any applicant info in that. "
                "Send a screenshot or type their name + phone or email.")
    lines = []
    for r in rows:
        a = r["applicant"]
        bits = [b for b in (pretty_phone(a.get("phone", "")), a.get("email"))
                if b]
        who = "*%s*" % (full_name(a) or "(no name)")
        detail = " · ".join([who] + bits)
        if r["status"] == "add":
            mark = ":white_check_mark: Added" if write else ":eyes: Would add"
            lines.append("%s: %s" % (mark, detail))
        elif r["status"] == "exists":
            lines.append(":ballot_box_with_check: Already in contacts: %s (%s)"
                         % (detail, r["why"]))
        else:
            lines.append(":warning: Not added: %s (%s). Resend with it."
                         % (detail, r["why"]))
    if write and any(r["status"] == "add" for r in rows):
        lines.append("_alphaletereception contacts._")
    return "\n".join(lines)
