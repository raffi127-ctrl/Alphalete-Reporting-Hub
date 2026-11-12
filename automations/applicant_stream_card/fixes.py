# -*- coding: utf-8 -*-
"""How to fix each thing the card finds — the steps, in ApplicantStream's
own words.

Megan 2026-11-12: "when we find the errors, we need to walk them through
what our recommendations would be or how to correct it if it's like the
incorrect information listed."

The WHY for each finding already lives beside the check that raises it
(templates.WHY, escalations.WHY, ai_settings.WHY) and is reused, so the
reason never says one thing here and another there. This file adds the
HOW: where to click, what to change it to, and how to check it took.

Click paths come from:
  * SMS / email templates — "All About SMS Templates" and "All About
    Emails" (Sept 2024 Looms): SMS/Email -> SMS Templates / Email
    Templates -> pencil -> save -> ACTIVATE AGAIN.
  * AI Settings + Escalations — resources/recruiting-context/
    appstream-ai-settings.md and appstream-ai-escalations.md (current,
    checked against the live page Oct 2026), including the editor traps.
  * The three AI Preferences numbers — resources/appstream-ai-preferences-
    standard.md (180 / 300 / 60).
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

from automations.sms_audit import ai_settings as AIS
from automations.sms_audit import escalations as ESC
from automations.sms_audit import templates as T

ESTREAM = "aisupport@estream.com"

# ----------------------------------------------------------- the paths

SMS_TPL = ["In ApplicantStream, open SMS/Email, then SMS Templates.",
           "Find {where} and click the pencil to edit it."]
EMAIL_TPL = ["In ApplicantStream, open SMS/Email, then Email Templates.",
             "Find {where} and click the pencil to edit it."]
SAVE_TPL = ["Click Save, then click Activate again. Saving a change can "
            "leave the template switched off."]

ESC_OPEN = ["Open the AI tab, then AI Settings, then the Escalations tab.",
            "Type “{where}” in the Search box so only that row "
            "shows."]
ESC_SAVE = ["Click Save and wait 10-15 seconds while it checks the "
            "wording.",
            "If it says the message is not compliant, tick “I've read "
            "the AI's concerns…” and press Save Anyway (it turns "
            "from faded to solid once the tick registers).",
            "Reload the page and search the row again to make sure it "
            "kept your change."]
ESC_TYPE = ["Click into the message box (it often takes two clicks), "
            "select all, then type the new wording. Check the counter "
            "moved off 0/250, or nothing was entered."]

SETTINGS_OPEN = ["Open the AI tab, then AI Settings, then the Settings tab."]

# ----------------------------------------------------- per-finding HOW

# What to change, written as the instruction. {detail} is the finding text.
TEMPLATE_HOW = {
    "WRONG ROOM": "Replace the Zoom link with this office's room: {want_zoom}.",
    "WRONG MEETING ID": "Change the Meeting ID to {want_zoom_id}.",
    "WRONG ADDRESS": "Change the address to {want_address} (street, suite, "
                     "city). Same address for every round.",
    "CHECK PHONE": "Change the phone number to {want_phone}, or confirm "
                   "the number shown is meant to be there.",
    "SHOUTING": "Retype the words in capitals in normal case "
                "(“Alphalete Marketing”, not "
                "“ALPHALETE MARKETING”).",
    "BASE PAY": "Take out the word “base”. Say weekly pay "
                "{pay}.",
    "DEAD LINK": "Delete the link and type it again by hand. A look-alike "
                 "letter got pasted in, so the link opens nothing.",
    "MERGE": "Fix the merge field so it fills in. Use the field list in the "
             "editor rather than typing it.",
    "PLACEHOLDER": "Write the real message, or switch this template off.",
    "NO OPT-OUT": "Add “Reply STOP to opt out.” at the end.",
    "NOT PLAIN TEXT": "Retype curly quotes and long dashes as plain ' and -. "
                      "It halves the cost of the text.",
    "TOO LONG": "Cut it to 2 segments (about 300 characters). Use the "
                "address field instead of typing the address out.",
}

ESC_HOW = {
    "SILENT AND BLANK": [
        "Write a short, direct answer in the message box (approved "
        "wording: resources/recruiting-context/appstream-ai-"
        "escalations.md, section 3).",
        "Set the row to Don't Escalate. It is the ONLY setting that sends "
        "your words; Clarify and Escalate let the AI write its own."],
    "NO MESSAGE": [
        "Write the answer you want the AI to give, then set the row to "
        "Don't Escalate so it actually sends it.",
        "Leave it on Escalate with no message ONLY if a person truly has "
        "to step in (e.g. All Timeslots Booked)."],
    "DEFLECTS": [
        "Rewrite it to answer the question first, then invite them to the "
        "interview. Never “the hiring manager will explain”."],
    "PROMISES A CALL": [
        "Take out the time word (“shortly”, “today”, "
        "“in a few minutes”). Say “we'll give you a "
        "call”. Keep the row on Escalate so a recruiter sees it."],
    "PAY WORDING": [
        "Say weekly pay {pay}. Never “base”."],
    "NOT PLAIN TEXT": [
        "Retype every curly quote and long dash as a plain ' and -."],
    "TOO LONG": [
        "Cut it under 250 characters (2 texts). Use officeAddress1 / "
        "officeCity instead of typing the address."],
    "GRAMMAR": ["Fix the wording shown. It goes out every time an "
                "applicant hits this situation."],
    "SHOUTING": ["Retype the capitals in normal case."],
    "WRONG ADDRESS": [
        "Replace the typed address with the variables officeAddress1, "
        "officeCity, officeState, so it can never drift from the record."],
}

SETTINGS_HOW = {
    "AI IS A REAL PERSON": [
        "Under Office Info, change Name your AI Assistant to a name nobody "
        "on the team uses, and match it to the name your Await Call "
        "template signs."],
    "SAME NAME": [
        "Under Office Info, set Escalation Contact Person Name to the real "
        "recruiter who calls applicants. It must be different from the AI "
        "assistant name."],
    "NAME MISMATCH": [
        "Make Name your AI Assistant match the name the live templates "
        "sign (or change the templates to match). Applicants should meet "
        "one name."],
    "WRONG TITLE": [
        "Change Escalation Contact Title to the person who really calls, "
        "e.g. “Recruiting Coordinator”, not “Hiring "
        "Manager”."],
    "ONE INTERVIEW TYPE": [
        "Set Interview Type to how the FIRST round is run. The page holds "
        "one answer; the second round has to be covered in the 2nd round "
        "templates."],
    "ADDRESS": [
        "The address on the right is greyed out: only eStream can change "
        "it. Email {estream} with your account number ({office}) and the "
        "full address on ONE line, suite included: {want_address}. There "
        "is no Line 2, so the suite has to go in Line 1."],
}

# The ICD-wide AI Preferences standard (appstream-ai-preferences-standard.md).
STANDARD = {"offered_buffer": 180, "accepted_buffer": 300,
            "ghosting_threshold": 60}
STANDARD_WHY = {
    "offered_buffer": (
        "Earliest time the AI can offer is too soon",
        "Interviews set under 3 hours out show 45%; 3-6 hours out show 59%. "
        "180 stops the AI offering into the worst window and keeps "
        "same-day open."),
    "accepted_buffer": (
        "Applicants lose the time before they can answer",
        "At 5 minutes, 36% of people who reply find the slot already gone "
        "and get offered new times. At 300, 92% are still in time."),
    "ghosting_threshold": (
        "Conversations get flagged as ghosting too early",
        "Most applicants answer within the hour. 60 flags the ones that "
        "really went quiet."),
}
STANDARD_LABEL = {
    "offered_buffer": "Timeslot Buffer — For Times Offered by AI",
    "accepted_buffer": "Timeslot Buffer — For Times Accepted by "
                       "Candidates",
    "ghosting_threshold": "Ghosting Threshold",
}


def _fill(lines, ctx):
    out = []
    for ln in lines:
        try:
            out.append(ln.format(**ctx))
        except (KeyError, IndexError):
            out.append(ln)
    return out


def context(office):
    """What 'the right answer' is for this office, for the steps."""
    o = office or {}
    lo, hi = (o.get("pay_low") or "").strip(), (o.get("pay_high") or "").strip()
    pay = ("${}-${}".format(lo.lstrip("$"), hi.lstrip("$")) if lo and hi
           else "$1,000-$1,500")
    return {"office": o.get("office", "?"),
            "want_zoom": o.get("zoom") or "(the room on file)",
            "want_zoom_id": o.get("zoom_id") or "(the ID on file)",
            "want_address": o.get("address") or "(the address on file)",
            "want_phone": o.get("phone") or "(the number on file)",
            "pay": pay, "estream": ESTREAM}


def split_where(text):
    """'Section / Name: the rest' -> ('Section / Name', 'the rest')."""
    if ": " in (text or ""):
        a, b = text.split(": ", 1)
        return a.strip(), b.strip()
    return (text or "").strip(), ""


def _is_email(where):
    return "email" in (where or "").lower()


def template(kind, text, office):
    where, detail = split_where(text)
    title, why = T.WHY.get(kind, (kind.title(), ""))
    ctx = dict(context(office), where="“{}”".format(where))
    steps = (EMAIL_TPL if _is_email(where) else SMS_TPL) \
        + [TEMPLATE_HOW.get(kind, "Fix what is shown.")] + SAVE_TPL
    return {"source": "Templates", "kind": kind, "title": title,
            "where": where, "found": detail or text, "why": why,
            "steps": _fill(steps, ctx)}


def escalation(kind, text, office):
    where, detail = split_where(text)
    title, why = ESC.WHY.get(kind, (kind.title(), ""))
    ctx = dict(context(office), where=where)
    steps = ESC_OPEN + ["Click the row to open it."] + ESC_TYPE \
        + ESC_HOW.get(kind, ["Fix what is shown."]) + ESC_SAVE
    return {"source": "AI replies (Escalations)", "kind": kind,
            "title": title, "where": where, "found": detail or text,
            "why": why, "steps": _fill(steps, ctx)}


def setting(kind, text, office):
    title, why = AIS.WHY.get(kind, (kind.title(), ""))
    ctx = context(office)
    steps = SETTINGS_OPEN + SETTINGS_HOW.get(kind, ["Fix what is shown."])
    return {"source": "AI Settings", "kind": kind, "title": title,
            "where": "AI Settings", "found": text, "why": why,
            "steps": _fill(steps, ctx)}


def preference(field, now):
    """A buffer off the standard -> one walkthrough."""
    want = STANDARD[field]
    title, why = STANDARD_WHY[field]
    return {"source": "AI Settings", "kind": "PREF " + field,
            "title": title, "where": STANDARD_LABEL[field],
            "found": "set to {} minutes".format(now),
            "why": why,
            "steps": SETTINGS_OPEN + [
                "Under AI Preferences, set {} to {}.".format(
                    STANDARD_LABEL[field], want),
                "Click Save, reload, and check the number stuck."]}


def check_preferences(prefs):
    """[walkthrough] for every AI Preferences number off the standard.

    Replaces ai_settings' WINDOW TOO SHORT / GHOST TOO SOON for this card:
    those read the two buffers as (offered - accepted), which the 180/300
    standard written down after them (6c9de67) would itself fail."""
    out = []
    for field, want in STANDARD.items():
        now = AIS._int((prefs or {}).get(field))
        if now is None:
            continue
        if field == "offered_buffer" and now < 60:
            out.append(preference(field, now))
        elif field == "accepted_buffer" and now < want:
            out.append(preference(field, now))
        elif field == "ghosting_threshold" and now < 30:
            out.append(preference(field, now))
    return out


# 11280 and 24065 after the 29-30 Oct rebuild: 31 of 51 rows on Don't
# Escalate (appstream-ai-escalations.md §2). Only Don't Escalate sends the
# office's own words; Clarify and Escalate let the AI write its own.
DONT_ESCALATE_STANDARD = 31


def routing_summary(rows):
    """One finding when too few rows send the office's own wording.

    Replaces escalations' per-row NO MESSAGE: a blank box on an Escalate
    row is deliberate (a person must act) and on a Silent row it is
    meant to say nothing, so 30-odd 'no message' lines were mostly noise.
    """
    def mode(r):
        return (r.get("routing") or "").strip().lower().replace("’", "'")
    dont = sum(1 for r in rows if mode(r) in ("don't escalate",
                                              "dont escalate",
                                              "do not escalate"))
    if dont >= DONT_ESCALATE_STANDARD or not rows:
        return None
    clar = [r["name"] for r in rows if mode(r) == "clarify"]
    return {"source": "AI replies (Escalations)", "kind": "ROUTING",
            "title": "The AI is not using the office's own replies",
            "where": "{} of {} rows on Don't Escalate (standard {})".format(
                dont, len(rows), DONT_ESCALATE_STANDARD),
            "found": ("Clarify rows (the AI writes its own deflection): "
                      + ", ".join(clar[:12])) if clar else "",
            "why": "Only Don't Escalate sends the words you wrote. On "
                   "Clarify or Escalate the AI makes up its own answer, so "
                   "every custom message on those rows has never reached an "
                   "applicant.",
            "steps": ESC_OPEN[:1] + [
                "Load the 32 approved replies (resources/recruiting-context/"
                "appstream-ai-escalations.md, section 3).",
                "For each one: search the row, paste the approved wording, "
                "set it to Don't Escalate, Save.",
                "Leave these six on Escalate with the box EMPTY — a "
                "person has to act: All Timeslots Booked, Request Outside "
                "Available Timeframes, Scheduling Dead End, Scheduling "
                "Impasse / Repeated Rejection, External Context Reference, "
                "Work Location.",
                "Reload and count the Don't Escalate rows: it should be "
                "31."]}


def recruiter_text(entry):
    """A typing slip in a recruiter's own text — coached, not edited."""
    sent = entry.get("sent") or 1
    who = entry.get("sender") or "a recruiter"
    saved = sent > 1
    steps = (["This exact wording went to {} people, so it is a saved "
              "reply. In any applicant's text box click Load Template, "
              "find it, fix it ({}), then Save Template over it.".format(
                  sent, entry.get("detail") or entry.get("kind"))]
             if saved else
             ["Show {} the text below and the fix: {}.".format(
                 who, entry.get("detail") or entry.get("kind"))])
    return {"source": "Recruiter texts", "kind": "TYPO",
            "title": "{} — {}".format(
                (entry.get("kind") or "mistake").capitalize(), who),
            "where": who, "found": (entry.get("body") or "")[:220],
            "why": "Applicants read typos as a careless or fake company.",
            "steps": steps}


def house_rule(entry):
    """A who_to_talk_to entry: wrong address, no suite, "base", etc."""
    return {"source": "Recruiter texts", "kind": "HOUSE RULE",
            "title": "{} — {}".format(entry.get("issue"),
                                           entry.get("sender")),
            "where": entry.get("sender") or "",
            "found": "{} text{} — e.g. {}".format(
                entry.get("count"), "" if entry.get("count") == 1 else "s",
                (entry.get("example") or "")[:180]),
            "why": "These are set by Raf/Megan's rulings "
                   "(resources/recruiting-context/megan-overrides.md).",
            "steps": ["If it came from a saved reply, click Load Template "
                      "in the text box, fix the saved copy once, and Save "
                      "Template over it.",
                      "Otherwise walk {} through the rule with the example "
                      "shown.".format(entry.get("sender") or "them")]}
