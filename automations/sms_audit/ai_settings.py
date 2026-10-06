# -*- coding: utf-8 -*-
"""The AI Settings page, audited — AppStream AI tab -> AI Settings (p=1504).

Megan 2026-10-01, after checking several offices: "I checked multiple
offices, all were not set correctly." These are not cosmetic. Two of them
decide whether an applicant can accept the time the AI offers, and the
office cannot see that from the page — the two numbers only mean something
together, and the meaning is backwards.

Checks, in the order they cost you money:

  WINDOW TOO SHORT   (offered - accepted) against how fast this office's
                     applicants actually reply. Not a rule of thumb: the
                     median comes from their own log.
  GHOST TOO SOON     flagging people who are replying at a normal pace.
  AI IS A REAL PERSON  the assistant name belongs to someone on the team.
  SAME NAME          the AI and the escalation contact are one person, so
                     the handoff points back at the AI.
  NAME MISMATCH      the assistant name is not the name the templates sign.
  WRONG TITLE        "Hiring Manager" is the ICD, who never takes those
                     calls before an interview.
  ONE INTERVIEW TYPE the office runs two rounds differently and the page
                     holds one answer.
  ADDRESS            no suite, or not the address the office gave us.

Reads output/ai_settings_<office>.json, written by pull_ai_settings.py.
No pull, no findings — never a quiet pass.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import json
import re
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[2] / "output"

# Titles that name the owner rather than whoever rings the applicant.
OWNER_TITLES = re.compile(r"(hiring manager|owner|president|ceo|director)", re.I)

WHY = {
    "WINDOW TOO SHORT": (
        "Applicants cannot accept the time they are offered",
        "The two timeslot buffers are both counted backwards from the "
        "interview, so the window an applicant actually gets is the first "
        "number minus the second. Set too tight, most of them reply after "
        "it has closed and the AI has to start over."),
    "GHOST TOO SOON": (
        "Normal repliers are being flagged as ghosting",
        "The ghosting threshold is shorter than how long this office's "
        "applicants usually take to answer, so the flag fires on people "
        "who are simply busy."),
    "AI IS A REAL PERSON": (
        "The AI is texting under a real person's name",
        "An escalation only works if it hands the applicant to someone "
        "new. If the AI already texts as that person there is nobody to "
        "hand them to."),
    "SAME NAME": (
        "The AI and the escalation contact are the same person",
        "The handoff reads as the assistant passing the applicant to "
        "itself."),
    "NAME MISMATCH": (
        "The AI's name is not the name the templates sign",
        "An applicant meets two people in their first two texts. "
        "AppStream's own setup video says these have to match."),
    "WRONG TITLE": (
        "The escalation title names someone who will not call",
        "The ICD is the Hiring Manager and is never on the phone with an "
        "applicant before an interview, so the title promises a call from "
        "someone who will not make it."),
    "ONE INTERVIEW TYPE": (
        "One interview type for an office that runs two rounds",
        "The page holds a single answer, so an office running Zoom first "
        "rounds and in-person second rounds can only describe one of "
        "them."),
    "ADDRESS": (
        "The address the AI sends is not the office's address",
        "This is what goes out when an applicant asks where to go."),
    "NOT PULLED": (
        "Settings have not been pulled for this office",
        "Nothing here has been checked. Run pull_ai_settings."),
}


def load(office):
    """({office_info}, {preferences}) or (None, None) when not pulled.

    The local file if this machine did the pull, otherwise the control-sheet
    tab the pull also writes — the pull only runs on Lucy 2, so every other
    machine has no file and would otherwise read a clean run as "not
    pulled"."""
    f = OUTPUT / "ai_settings_{}.json".format(office)
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        return d.get("office_info") or {}, d.get("preferences") or {}
    from automations.sms_audit import ai_settings_tab as TAB
    info, prefs, _rows, src = TAB.read(office)
    if not src:
        return None, None
    return info or {}, prefs or {}


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def window(prefs):
    """Minutes an applicant actually has to accept, or None."""
    off = _int(prefs.get("offered_buffer"))
    acc = _int(prefs.get("accepted_buffer"))
    if off is None or acc is None:
        return None
    return off - acc


def lint(info, prefs, office=None, median_reply=None, template_names=None,
         human_senders=None):
    """[(kind, text)].

    `median_reply` is this office's own median applicant reply in minutes
    (analyze.applicant_reply_speed). Passed in rather than assumed, because
    a new office has no history and the check should then be skipped and
    said, not guessed at.

    `human_senders` are the real names in the log's Sent By column. The AI
    persona matching one of those is the fault — NOT matching the template
    signature, which is the state AppStream's own setup video asks for.
    """
    office = office or {}
    out = []
    if info is None:
        return [("NOT PULLED", "office {}".format(office.get("office", "?")))]

    ai = (info.get("ai_assistant_name") or "").strip()
    contact = (info.get("escalation_contact_name") or "").strip()
    title = (info.get("escalation_contact_title") or "").strip()

    # --- the two buffers, against this office's own applicants ----------
    w = window(prefs)
    if w is None:
        out.append(("WINDOW TOO SHORT",
                    "the timeslot buffers are not both set, so nobody knows "
                    "how long an applicant has"))
    elif median_reply is None:
        # No history to measure against. Most applicants anywhere take 20
        # to 30 minutes, so only call out a window that is short by any
        # reading, and say the number is a benchmark rather than theirs.
        if w < 20:
            out.append((
                "WINDOW TOO SHORT",
                "applicants get {} minutes to accept. No message history "
                "for this office yet, but applicants generally take 20 to "
                "30 minutes to answer a text".format(w)))
    elif w < median_reply:
        out.append((
            "WINDOW TOO SHORT",
            "applicants get {} minutes to accept, and the median applicant "
            "here takes {:.0f} minutes to reply — so more than half are "
            "too late for the time they were offered".format(w, median_reply)))

    gh = _int(prefs.get("ghosting_threshold"))
    if gh is not None and median_reply is not None and gh < median_reply:
        out.append(("GHOST TOO SOON",
                    "flagged after {} minutes, but the median applicant here "
                    "takes {:.0f}".format(gh, median_reply)))

    # --- who the AI is ---------------------------------------------------
    if ai and contact and ai.lower() == contact.lower():
        out.append(("SAME NAME", "both are “{}”".format(ai)))
    if ai and template_names:
        signs = {n.strip().lower() for n in template_names if n}
        if signs and ai.lower() not in signs:
            out.append((
                "NAME MISMATCH",
                "the AI is “{}” but the live templates sign {}".format(
                    ai, ", ".join(sorted(template_names)))))
    if ai and human_senders:
        first = ai.split()[0].lower()
        for person in human_senders:
            p = (person or "").strip()
            if not p:
                continue
            if p.lower() == ai.lower() or p.split()[0].lower() == first:
                out.append((
                    "AI IS A REAL PERSON",
                    "the AI is named \u201c{}\u201d and {} is a real person "
                    "who sends texts from this office".format(ai, p)))
                break

    if title and OWNER_TITLES.search(title):
        out.append(("WRONG TITLE", "it is set to “{}”".format(title)))

    # --- interviews ------------------------------------------------------
    r1 = (office.get("r1_mode") or "").strip().lower()
    r2 = (office.get("r2_mode") or "").strip().lower()
    itype = (info.get("interview_type") or "").strip()
    if r1 and r2 and r1 != r2:
        out.append((
            "ONE INTERVIEW TYPE",
            "1st rounds are {} and 2nd rounds are {}, and the page says "
            "“{}”".format(r1, r2, itype or "nothing")))

    # --- the address that goes out ---------------------------------------
    want = (office.get("address") or "").strip()
    line1 = (info.get("office_address1") or "").strip()
    if want and line1:
        unit = re.search(r"(suite|ste\.?|unit)\s*(\w+)", want, re.I)
        if unit and unit.group(2).lower() not in line1.lower():
            out.append((
                "ADDRESS",
                "Address Line 1 is “{}” with no {} {} — there is "
                "no second address field, so the suite has to live "
                "here".format(line1, unit.group(1).lower(), unit.group(2))))
        num = re.match(r"\s*(\d{2,6})", want)
        if num and num.group(1) not in line1:
            out.append((
                "ADDRESS",
                "Address Line 1 is “{}” but this office is at "
                "“{}”".format(line1, want)))
    return out
