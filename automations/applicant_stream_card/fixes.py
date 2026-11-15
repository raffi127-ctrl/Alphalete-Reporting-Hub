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
  * AI replies, escalation types and AI Settings get NO steps: the Aptel
    team sets those up, so the card names the problem and the owner.
    Standards: appstream-ai-escalations.md and appstream-ai-preferences-
    standard.md (60 / 60 / 60 since 2026-11-13).
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import re
from pathlib import Path

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

# One general how-to per kind of template, instead of steps on every item
# (Megan 2026-11-13: "we shouldn't have a 'how' section on each of these -
# just like a link on how to edit text templates in general"). Raf's Looms,
# linked from the ARS doc's training list.
HOWTO_SMS = ("How to edit text templates",
             "https://www.loom.com/share/97b7979b1a5249ec9a947aaceb98fa2a")
HOWTO_EMAIL = ("How to edit email templates",
               "https://www.loom.com/share/fe2af2505d214b169db9681fdada4b9e")


def howto(item):
    """(label, url) for a template item, or None."""
    if item.get("source") != "Templates":
        return None
    return HOWTO_EMAIL if _is_email(item.get("where")) else HOWTO_SMS


def recommend(item):
    """The one line to do, without the click-by-click around it."""
    steps = [st for st in item.get("steps") or []
             if not st.startswith(("In ApplicantStream", "Find ",
                                   "Click Save"))]
    return " ".join(steps)


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

# The ICD-wide AI Preferences standard (appstream-ai-preferences-standard.md).
# 60 / 60 / 60 since 2026-11-13: Aptel confirmed both buffers are "too soon"
# floors, so the old 180 / 300 (which read "accepted" as a hold time) blocked
# same-day bookings.
STANDARD = {"offered_buffer": 60, "accepted_buffer": 60,
            "ghosting_threshold": 60}
# A buffer is only flagged outside this range: above it same-day closes,
# below it the AI can book a slot nobody can make in time.
BUFFER_OK = (30, 120)
STANDARD_WHY = {
    "offered_buffer": (
        "The AI's earliest offer is set too far out" ,
        "Same-day interviews show up 57% against 42% next day. Above 2 hours, "
        "anyone who texts in the afternoon can only be offered tomorrow. "
        "60 gives them an hour to get ready and keeps same-day open."),
    "accepted_buffer": (
        "Applicants can't pick a time soon enough",
        "This is the earliest time an applicant can pick. Above 2 hours, "
        "anyone who texts in the afternoon can't take a same-day slot, and "
        "same-day shows up 57% against 42% next day. 60 keeps it open."),
    "ghosting_threshold": (
        "Conversations get flagged as ghosting too early",
        "Most applicants answer within the hour. 60 flags the ones that "
        "really went quiet."),
}
# When a buffer is set too LOW (under 30) instead.
TOO_SOON_WHY = (
    "The AI can book a time that's too soon",
    "Under 30 minutes, an applicant can be booked into an interview they "
    "can't get ready for or log in to in time. 60 gives them an hour.")
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
    text = text or ""
    # A colon inside the quoted opening ("(the one starting \u201cHere's the
    # link again: https\u2026\u201d)") is part of the name, not the split.
    m = re.search(r"\(the one starting \u201c.*?\u2026\u201d\)", text)
    skip = m.end() if m else 0
    i = text.find(": ", skip)
    if i >= 0:
        return text[:i].strip(), text[i + 2:].strip()
    return text.strip(), ""


def _is_email(where):
    return "email" in (where or "").lower()


def template(kind, text, office):
    where, detail = split_where(text)
    title, why = (T.WHY.get(kind) or EXTRA_WHY.get(kind)
                  or ESC.WHY.get(kind, (kind.title(), "")))
    ctx = dict(context(office), where="“{}”".format(where))
    steps = (EMAIL_TPL if _is_email(where) else SMS_TPL) \
        + [TEMPLATE_HOW.get(kind, "Fix what is shown.")] + SAVE_TPL
    return {"source": "Templates", "kind": kind, "title": title,
            "where": where, "found": detail or text, "why": why,
            "steps": _fill(steps, ctx)}


# AI replies, escalation types and AI Settings are set up by the Aptel team
# (Megan 2026-11-12: "the AppTel team would be in charge of setting these
# up, they'll know how to do it ... we just need them notified"). So these
# items say what is wrong and who fixes it, with no click-by-click steps.
APTEL = "Aptel team"
# Megan 2026-11-13: the office "or their admin can go into their app stream
# at any time and make these edits" — so the owner line names both.
WHO_FIXES = ("You or your admin can change this in ApplicantStream "
             "anytime, or message the Aptel team to help you get it done.")


def _aptel(source, kind, title, where, found, why):
    return {"source": source, "kind": kind, "title": title, "where": where,
            "found": found, "why": why, "steps": [], "owner": WHO_FIXES}


def escalation(kind, text, office):
    where, detail = split_where(text)
    title, why = ESC.WHY.get(kind, (kind.title(), ""))
    return _aptel("AI replies", kind, title, where, detail or text, why)


def setting(kind, text, office):
    title, why = AIS.WHY.get(kind, (kind.title(), ""))
    return _aptel("AI Settings", kind, title, "AI Settings", text, why)


def preference(field, now):
    """A buffer off the standard."""
    title, why = STANDARD_WHY[field]
    return _aptel("AI Settings", "PREF " + field, title,
                  STANDARD_LABEL[field],
                  "Set to {} minutes. Should be {}.".format(
                      now, STANDARD[field]), why)


def check_preferences(prefs):
    """[item] for every AI Preferences number outside the standard's range.

    Replaces ai_settings' WINDOW TOO SHORT / GHOST TOO SOON for this card:
    those read the two buffers as a window (offered - accepted), which Aptel
    confirmed is not how they work (2026-11-13)."""
    lo, hi = BUFFER_OK
    out = []
    for field, want in STANDARD.items():
        now = AIS._int((prefs or {}).get(field))
        if now is None:
            continue
        if field == "ghosting_threshold":
            if now < 30:
                out.append(preference(field, now))
        elif now > hi:
            out.append(preference(field, now))
        elif now < lo:
            item = preference(field, now)
            item["title"], item["why"] = TOO_SOON_WHY
            out.append(item)
    return out


# 11280 and 24065 after the 29-30 Oct rebuild: 31 of 51 rows on Don't
# Escalate (appstream-ai-escalations.md section 2). Only Don't Escalate
# sends the office's own words; Clarify and Escalate let the AI write its
# own. The list itself is read from that doc so it never drifts.


APPROVED_DOC = (Path(__file__).resolve().parents[2] / "resources"
                / "recruiting-context" / "appstream-ai-escalations.md")
_ROW = re.compile(r"^\|\s*\*\*(.+?)\*\*(.*?)\|\s*(.+?)\s*\|\s*$")
# The doc's Commute row types 11280's own address; any office gets the fields.
_HARD_ADDR = "5217 Tennyson Pkwy Suite 100, Plano TX"
_ADDR_VARS = "{officeAddress1}, {officeCity} {officeState} {officeZip}"


def approved_replies(doc=None):
    """[(number, row name, reply)] — the signed-off Don't Escalate set, in the
    doc's order (section 3 of appstream-ai-escalations.md). AppStream does
    not number these rows, so the number is ours, stable as long as the
    doc's order is. Rows the doc marks Silent are left out."""
    try:
        text = Path(doc or APPROVED_DOC).read_text(encoding="utf-8")
    except OSError:
        return []
    sect = text.split("## 3.", 1)[-1].split("\n## ", 1)[0]
    out = []
    for line in sect.splitlines():
        m = _ROW.match(line.strip())
        if not m or "silent" in m.group(2).lower():
            continue
        out.append((len(out) + 1, m.group(1).strip(),
                    m.group(3).replace(_HARD_ADDR, _ADDR_VARS)))
    return out


# Megan 2026-11-13: "we have 5 versions of the reply ... give them, hey,
# these are the 5 potential responses we'd recommend". They live on the
# Approved Applicant Replies page (23 questions x 5 versions, each with its
# own Copy button), so the card links to the right question rather than
# copying the words and letting the two drift.
REPLY_PAGE = "https://claude.ai/artifact/QqHyfff9tDpzU9C2SRUCKL"
# AppStream AI reply row -> that page's question number. Only clear matches;
# a row with none keeps the one signed-off reply from the escalations doc.
REPLY_QUESTION = {
    "Compensation": 16,
    "Remote Work": 7,
    "Work Flexibility (Remote/Flex hours)": 7,
    "Applicant Requested Directions": 8,
    "Company Name Confusion": 11,
    "Confusion About Role Type": 11,
    "Does Not Remember Applying": 11,
    "Job Description": 14,
    "Request for Unprovided Information": 14,
    "Work Hours": 19,
    "Work Days": 19,
    "Full-Time / Part-Time Definitions": 19,
    "Empathetic Reason / Personal Hardship": 17,
    "Request to talk via Phone": 12,
}


def reply_link(name):
    """Link to the 5 approved versions for this row, or None."""
    want = _key(name)
    for row, q in REPLY_QUESTION.items():
        if _key(row) == want:
            return "{}#q{}".format(REPLY_PAGE, q)
    return None


def reply_versions(name, approved_msg):
    """The words to offer inline when the row has no replies-page match."""
    return [approved_msg] if approved_msg else []


def _key(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()
                  .replace("\u2019", "'")).strip()


def routing_summary(rows, approved=None):
    """One finding listing which of our recommended AI replies are not on
    Don't Escalate, by number, with the reply to paste in.

    Replaces escalations' per-row NO MESSAGE: a blank box on an Escalate
    row is deliberate (a person must act) and on a Silent row it is
    meant to say nothing, so 30-odd 'no message' lines were mostly noise.
    """
    if not rows:
        return None
    approved = approved_replies() if approved is None else approved
    if not approved:
        return None

    def dont(r):
        m = (r.get("routing") or "").strip().lower().replace("\u2019", "'")
        return m in ("don't escalate", "dont escalate", "do not escalate")
    on = {_key(r.get("name")) for r in rows if dont(r)}
    missing = [a for a in approved if _key(a[1]) not in on]
    if not missing:
        return None
    total = len(approved)
    item = _aptel(
        "AI replies", "ROUTING",
        "Not all of our recommended AI replies are active and set to the "
        "right escalation type",
        "{} of {} set up".format(total - len(missing), total),
        "{} of {} set up. Set these to Don't Escalate with the reply "
        "below:\n{}".format(total - len(missing), total, "\n".join(
            "#{} {}".format(n, name) for n, name, _m in missing)),
        "Until they are, the AI writes its own answer instead of ours.")
    item["replies"] = missing
    return item


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


# --- the AI-reply rules, run on the office's templates too ----------------
# Megan 2026-11-15: "we should also flag like bad grammar or red flag things
# that we see in those text messages, following the same guidelines that
# we've already set up for our AI responses". templates.lint (shared with
# the weekly SMS audit) already covers curly quotes, length, block capitals,
# base pay and wrong links; these are the reply rules it doesn't run, added
# here so the shared audit is not changed under other reports.
REPLY_RULES = ("GRAMMAR",)

# Megan 2026-11-15: a promised call TIME in a template ("I'll call you
# shortly") is fine, too nitpicky to flag. What's worth a look is a 2nd or
# 3rd left message promising a call at all: "for second and third, we don't
# always call ... are you making a promise you're not going to keep?" That
# is an orange question, not a red fault, so it is never graded.
WARN_KINDS = {"CALL CHECK", "TYPED ADDRESS", "CHECK ROOM"}

# Megan 2026-07-09: never an age, gender or "who we hire" preference in
# anything public (feedback_recruiting_copy_compliance).
WHO_WE_HIRE = re.compile(
    r"\b(young|guys|gentlemen|ladies|\d0-somethings?|twenty-somethings?|"
    r"men only|women only|males?|females?|under \d\d|over \d\d|"
    r"recent grads? only)\b", re.I)
# appstream-ai-escalations.md rule: "Address lines are read from fields,
# not typed" - a typed street address drifts (11280's Suite 207 / 100).
TYPED_STREET = re.compile(
    r"\b\d{2,6} [A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)? "
    r"(Pkwy|Parkway|St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Way|Hwy)"
    r"\b\.?(?:,? (?:Suite|Ste\.?|#) ?\w+)?(?:,? [A-Z][a-z]+(?: [A-Z][a-z]+)?"
    r",? (?:TX|Texas)(?: \d{5})?)?")
CALL_SAID = re.compile(
    r"\b(i'?ll|i will|we'?ll|we will|someone will|we are going to|i'?m going "
    r"to)\b[^.!?]{0,25}\b(call|give you a (quick )?call|ring)\b", re.I)
LATER_LEFT_MESSAGE = re.compile(r"^(2nd|3rd|second|third) left message", re.I)
CITY_ST = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?), ?(TX|Texas)\b")
EXTRA_WHY = {
    "CALL CHECK": (
        "Do you actually call after this message?",
        "This text promises a call. On a 2nd or 3rd left message, offices "
        "often only follow up by text. If nobody calls, the applicant is "
        "left waiting on a call that won't come."),
    "WHO WE HIRE": (
        "Says who we hire",
        "Words about age or gender, like \u201cyoung\u201d or \u201cguys\u201d, "
        "in a hiring message can read as discrimination and put the office "
        "at legal risk."),
    "LOW PAY": (
        "Pay figure under our range",
        "Our pay answer is weekly pay of $1,000\u2013$1,500. A lower number "
        "here undersells the job."),
    "TYPED ADDRESS": (
        "Address typed in by hand",
        "A typed address goes stale when the office moves or changes suite. "
        "The address fields always send what's on file."),
    "CHECK ROOM": (
        "Is this your 2nd-round Zoom room?",
        "This sends a different Zoom room than the one on file. If 2nd "
        "rounds use their own room, that's fine; if not, applicants are "
        "sent to the wrong meeting."),
    "WRONG CITY": (
        "Names the wrong city",
        "The text tells applicants the office is somewhere it isn't, so "
        "some will plan for the wrong place."),
}


def template_where(bodies):
    """[(section, name, body, where)] with the same 'where' label
    templates.lint gives each template."""
    seen = {}
    out = []
    for section, name, body in bodies or []:
        where = (name if name.startswith(section)
                 else "{} / {}".format(section, name))
        seen[where] = seen.get(where, 0) + 1
        if seen[where] > 1:
            opening = " ".join((body or "").split())[:34]
            where = "{} (the one starting “{}…”)".format(
                where, opening)
        out.append((section, name, body, where))
    return out


def reply_rule_findings(bodies, city=None):
    """[(kind, text)] in templates.lint's shape for the reply rules, plus
    the wrong-city check (`city` = where this office is)."""
    from automations.sms_audit import analyze as A
    from automations.sms_audit import rebuttals as R
    out = []
    for _sec, _name, body, where in template_where(bodies):
        # The pull adds "[Section / Name] input 0: <name>" lines: the name
        # box, not the message. Proofread the message only.
        msg = "\n".join(ln for ln in (body or "").splitlines()
                        if not ln.startswith("[")).strip()
        if not msg.strip():
            continue
        # No DEFLECTS here: a template is a message the office sends, not
        # an answer to a question (Megan 2026-11-15, on a 1st interview
        # confirmation: "This isn't answering a question").
        if LATER_LEFT_MESSAGE.match(_sec or "") and CALL_SAID.search(msg):
            out.append(("CALL CHECK", "{}: \u201c{}\u201d".format(
                where, CALL_SAID.search(msg).group(0))))
        hit = WHO_WE_HIRE.search(msg)
        if hit:
            out.append(("WHO WE HIRE", "{}: \u201c{}\u201d".format(
                where, hit.group(0))))
        if ESC.PAY_TOPIC.search(msg):
            low = re.search(r"\$\s?[1-9]\d{2}\b(?![\d,])", msg)
            if low:
                out.append(("LOW PAY", "{}: \u201c{}\u201d".format(
                    where, low.group(0))))
        typed = TYPED_STREET.search(msg)
        if typed:
            out.append(("TYPED ADDRESS", "{}: \u201c{}\u201d".format(
                where, typed.group(0))))
        want = (city or "").strip().lower()
        if want:
            for m in CITY_ST.finditer(msg):
                if m.group(1).lower() != want:
                    out.append(("WRONG CITY",
                                "{}: says \u201c{}\u201d \u2014 this office is "
                                "in {}.".format(where, m.group(0),
                                                city.strip())))
        for kind, detail in A.proofread(msg):
            out.append(("GRAMMAR", "{}: {} — “{}”".format(
                where, kind, detail)))
    return out


# --- emails ---------------------------------------------------------------
# Megan 2026-11-15: the emails "aren't showing what's being sent". The pull
# now reads each switched-on email; these are the checks that matter in an
# email. Curly quotes, length, capitals and the typed address are text-only
# costs (an email signature is SUPPOSED to carry the address), and a second
# office number in a signature is not a wrong one, so those are left out.
EMAIL_TPL_KINDS = {"WRONG ROOM", "WRONG MEETING ID", "WRONG ADDRESS",
                   "BASE PAY", "DEAD LINK", "MERGE"}
EMAIL_RULE_KINDS = {"GRAMMAR", "WHO WE HIRE", "LOW PAY", "WRONG CITY"}


def email_where(head, name):
    # No colon: split_where cuts a finding at the first ": ", and
    # "Email: ..." came out as just "Email".
    # The heading the pull saw is not reliable (11280: a page notice), so
    # the email's own name is the label.
    return "Email \u2014 {}".format(name.strip())


def email_findings(emails, office, city=None):
    """[(kind, text)] for the switched-on emails, `where` = email_where()."""
    out = []
    for e in emails or []:
        body = e.get("body") or ""
        lint_body = body + "\n" + "\n".join(e.get("links") or [])
        where = email_where(e["head"], e["name"])
        plain = (e["name"] if e["name"].startswith(e["head"])
                 else "{} / {}".format(e["head"], e["name"]))
        found, _p = T.lint([(e["head"], e["name"], lint_body)], {}, office)
        second = re.search(r"\b(2nd|second)\b", "{} {}".format(
            e["head"], e["name"]), re.I)
        asked = False
        for kind, text in found:
            if kind not in EMAIL_TPL_KINDS:
                continue
            # No 2nd-round room on file: a different room in a 2nd-round
            # email may be right, so ask instead of calling it wrong.
            if kind in ("WRONG ROOM", "WRONG MEETING ID") and second and \
                    not (office or {}).get("zoom2"):
                if asked:
                    continue
                asked = True
                kind = "CHECK ROOM"
            out.append((kind, text.replace(plain, where, 1)))
        for kind, text in reply_rule_findings(
                [(e["head"], e["name"], body)], city=city):
            if kind in EMAIL_RULE_KINDS:
                out.append((kind, text.replace(plain, where, 1)))
    return out
