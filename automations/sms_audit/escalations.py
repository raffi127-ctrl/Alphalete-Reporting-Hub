# -*- coding: utf-8 -*-
"""The AI's canned answers — AppStream AI Settings -> Escalations (p=1504).

Megan 2026-10-01, having found the page: "I found where we can edit what
their AI responds with in app stream. Help me to give better responses and
not deflections" and "we should also audit this in the Jiriayah audit we're
building".

Each row is one situation the AI recognises, a routing choice (Clarify /
Escalate / Silent / Don't Escalate) and an optional Custom Message. This is
the SOURCE of most of what the message audit sees downstream: a deflection
in a thousand threads is usually one row here, not a thousand mistakes.

WHAT IT CHECKS
  * a situation applicants actually hit, routed Silent with no message —
    the applicant is answered with nothing at all
  * a message that deflects instead of answering (REFUSES / DEFERS)
  * a message that promises a call we may not make
  * pay wording against Raf's ruling: weekly $1,000-$1,500, never a "base",
    never "depending on background/experience"
  * block capitals, and an address that is not this office's

READ-ONLY. Reads output/escalations_<office>.json, written by
pull_escalations.py. No pull, no findings — never a quiet pass.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import json
import re
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[2] / "output"

# Routing words as AppStream spells them.
SILENT = "silent"

# Situations where saying nothing is a real cost, because applicants ask
# these constantly — straight off the complaints the auditor already counts.
MUST_ANSWER = {
    "confusion about role type": "Confused about the job",
    "request for unprovided information": "They think it's a scam",
    "company name confusion": "Confused about the job",
    "compensation": "Pay",
    "schedule": "Hours",
    "location": "Where the office is",
}

WHY = {
    "SILENT AND BLANK": (
        "The AI answers these with nothing",
        "This situation is set to Silent and has no custom message, so an "
        "applicant who hits it gets no reply at all. Either write a message "
        "or route it to someone who will answer."),
    "NO MESSAGE": (
        "No custom message set",
        "The AI falls back to its own wording here. Write the answer you "
        "want it to give instead of leaving it to guess."),
    "DEFLECTS": (
        "Pushes the question away instead of answering",
        "These tell the applicant somebody else will explain. Megan's "
        "ruling stands: deflection is not fine. Answer the question, then "
        "invite them."),
    "PROMISES A CALL": (
        "Promises a call",
        "This promises somebody will ring them. Applicants are already "
        "complaining that the call never came. Ask for a time instead of "
        "promising one."),
    "PAY WORDING": (
        "Pay wording does not match Raf's ruling",
        "Raf, via Megan on 2026-09-27: weekly pay $1,000–$1,500, never a "
        "“base”, and not “depending on background/experience”. "
        "This row teaches the wording that was retired."),
    "SHOUTING": (
        "Written in block capitals",
        "Block capitals read as shouting and trip spam filters."),
    "WRONG ADDRESS": (
        "Wrong office address",
        "The address here is not where this office interviews."),
}

PAY_BAD = re.compile(
    r"(\$\s?[2-9]\d{2}\b|\bbase\b|depending on (your )?background|"
    r"background\s*/\s*experience)", re.I)
PAY_TOPIC = re.compile(r"(pay|salar|earn|compensat|\$)", re.I)

# analyze.CALL_PROMISE is deliberately first-person ("I will call you"),
# because in a thread the point is whether THAT recruiter promised it.
# A canned answer promises on behalf of the office, so the third-person
# phrasings count here too: "a member from our team will give you a call".
ESC_CALL_PROMISE = re.compile(
    r"(give you a call|will call you|call you (back|shortly|soon|today)|"
    r"(someone|somebody|a member|our team|the team)[^.]{0,40}"
    r"(call|reach out|contact|follow up)|reach out to you)", re.I)


def load(office):
    """[{name, category, description, message, routing}] or ([], None)."""
    f = OUTPUT / "escalations_{}.json".format(office)
    if not f.exists():
        return [], None
    rows = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        out.append({
            "name": (r.get("name") or "").strip(),
            "category": (r.get("category") or "").strip(),
            "description": (r.get("description") or "").strip(),
            "message": (r.get("message") or "").strip(),
            "routing": (r.get("routing") or "").strip(),
        })
    return out, str(f)


def lint(rows, office=None):
    """[(kind, text)] — same shape as templates.lint, so the report renders
    both the same way."""
    from automations.sms_audit import rebuttals as R
    from automations.sms_audit.analyze import CALL_PROMISE
    office = office or {}
    findings = []
    for r in rows:
        where = r["name"] or r["category"] or "(unnamed)"
        msg, routing = r["message"], r["routing"].lower()
        key = r["name"].strip().lower()

        if not msg:
            if routing == SILENT and any(k in key for k in MUST_ANSWER):
                findings.append((
                    "SILENT AND BLANK",
                    "{}: applicants ask this constantly — it is one of the "
                    "complaints the audit counts — and the AI says "
                    "nothing.".format(where)))
            else:
                findings.append(("NO MESSAGE", where))
            continue

        if R.REFUSES.search(msg) or R.DEFERS.search(msg):
            findings.append((
                "DEFLECTS", "{}: “{}”".format(where, msg[:130])))
        if CALL_PROMISE.search(msg) or ESC_CALL_PROMISE.search(msg):
            findings.append((
                "PROMISES A CALL", "{}: “{}”".format(where, msg[:130])))
        if PAY_TOPIC.search(msg) and PAY_BAD.search(msg):
            findings.append((
                "PAY WORDING", "{}: “{}”".format(where, msg[:160])))
        shout = R.shouts(msg)
        if shout:
            findings.append((
                "SHOUTING", "{}: “{}” in block capitals.".format(
                    where, shout)))
        if office.get("address"):
            bad = R.wrong_address(office.get("office", ""), msg)
            if bad:
                findings.append((
                    "WRONG ADDRESS",
                    "{}: says “{}” — this office is {}.".format(
                        where, bad, office["address"])))
    return findings
