"""The answers the company has already decided on, and whether we gave them.

Megan 2026-09-27: "I need you to learn how we would actually want things
answered." The standard was never a judgement call — it is written down, in
Raf's ARS Processes 2026 doc under REBUTTALS and the SMS Templates table
(resources/recruiting-context/ars-processes-2026.md, lines ~1028-1090). Every
question applicants actually ask has an approved answer already.

So a reply is not scored by whether it "seems responsive", which is what four
rounds of heuristics kept getting wrong. It is scored against the approved
answer for that question: did we say the thing we decided to say?

  gave_it     the approved facts are in the reply
  deflected   pushed it to the hiring manager or the interview, and the
              approved answer exists, so there was nothing to push
  ignored     the reply never engages with the question at all

SOURCE IS LIVE. The Google Doc is still being edited and this is a snapshot
(see resources/recruiting-context/README.md). Re-pull before treating a
scorecard built from it as final.

`must` is the facts an answer has to carry, not the wording — a recruiter who
says "$16-21 an hour plus commission" in their own words has answered, and
scoring on phrasing would fail every human in the office.
"""
from __future__ import annotations

import re

# name -> (what they asked, approved answer, facts the reply must carry)
REBUTTALS = [
    ("Pay / commission",
     r"\b(pay|paid|salary|wage|hourly|how much|commission|compensat|"
     r"\$\d)\b",
     "We offer weekly pay ranging from $1,000-$1,500 plus bonuses or "
     "commission. Is that something you're okay with? (Raf via Megan, "
     "2026-09-27, asked directly whether bookers should say there is a "
     "BASE weekly pay: \"No, just weekly pay ranging from $1,000-$1500.\" "
     "That overrides the ARS doc's \"base salary is determined on your "
     "background/experience\" wording, which is what bookers were "
     "reading off.)",
     r"(\$\s?\d|\b\d{2}\s*-\s*\d{2}\b|weekly (salary|pay)|base salary|"
     r"bonus|commission|hourly|an hour|paid training)"),

    ("Door-to-door / is it sales",
     r"\b(door.?to.?door|d2d|knock|canvas|outside sales|street)\b",
     "We have different locations available for this role either in office, "
     "in store, Business 2 Business, depending on which one of our clients "
     "you will be working with. Did you have a preference? — and: if D2D "
     "means knocking on random doors, we do not do that, we work with LEADS.",
     r"(in.?office|in.?store|business 2 business|b2b|lead|preference|"
     r"random doors|face to face|f2f|residential)"),

    # Megan's own wording, 2026-09-27, when shown the address replies:
    #   "You applied to our open AT&T Enrollment Associate position. Our
    #    office address is in Irving at 3100 Premier Dr."
    # The SHAPE matters as much as the facts: name the role they applied
    # to first, then the address, in sentence case, and do not pivot
    # straight into asking for their email.
    ("Remote or in person / where",
     r"\b(remote|work from home|wfh|virtual|on.?site|in person|in.?office|"
     r"location|located|where (is|would|are)|which (city|office|location)|"
     r"storefront|in a store)\b",
     "You applied to our open [Role] position. Our office address is "
     "[the office's own address]. (Per account, NOT one address: Raf's "
     "11280/23965/24065 are 3100 Premier Drive, Suite 207, Irving; Carlos's "
     "11580 is 1901 N Highway 360, Suite 610, Grand Prairie \u2014 a different "
     "office. Megan 2026-09-27.)",
     r"(main office|located|location|dfw|metroplex|irving|frisco|grand "
     r"prairie|denton|plano|dallas|fort worth|in.?office|in.?store|"
     r"in person|on.?site|remote|specific city|address)"),

    ("Schedule / hours",
     r"\b(schedule|shift|hours|what days|how many hours|part.?time|"
     r"full.?time)\b",
     "Our shifts range from 8am - 8pm, Monday - Saturday. Was there a "
     "specific schedule you were seeking?",
     r"(8\s?am|8\s?pm|monday|saturday|shift|schedule|full.?time|part.?time|"
     r"\d{1,2}\s?(am|pm)\s?-\s?\d{1,2}\s?(am|pm))"),

    ("What is the role / company",
     r"\b(what (is|s) the (job|role|position)|which (job|role|position)|"
     r"what company|which company|what.?s the company|who are you with|"
     r"tell me more about|more info about (this|the) (job|role|position)|"
     r"job listed under|what position)\b",
     "It looks like you applied to our [ROLE] — in this position you would "
     "be handling customer service, escalations, new sales and up-sales "
     "with our AT&T client. We have different locations available either in "
     "office, in store or B2B.",
     r"(alphalete|vantura|polarity|at&?t|customer service|sales|"
     r"entry level|assistant manager|representative|marketing|role is|"
     r"position is|applied (to|for) our)"),

    ("No experience",
     r"\b(no experience|don'?t have experience|never done|without "
     r"experience|entry level\?)\b",
     "All of our roles are entry-level so we do provide complete paid "
     "training. That pay is also based on your background/experience and "
     "can be negotiated in the meeting as well. Is that okay?",
     r"(entry.?level|paid training|no experience (needed|required)|"
     r"we train|training provided)"),

    ("Advancement",
     r"\b(advancement|promot|grow(th)?|move up|career path)\b",
     "Yes! We fully promote from within our business and provide cross "
     "training in all departments if you are interested in growth.",
     r"(promote from within|advancement|cross.?train|grow(th)?|move up)"),

    ("Group interview",
     r"\b(group interview|others|someone else be there|by myself)\b",
     "Yes, this will be a small group interview. (Megan's wording, "
     "2026-09-27 — lead with yes, soften it, do not clip it to "
     "“It is a group interview”.) It looks like 2 other people also "
     "applied to the same listing; depending on who shows up you may "
     "interview by yourself or with someone else.",
     r"(other people|also applied|by yourself|group)"),

    ("Spam / scam likely",
     r"\b(spam|scam|robocall|fake|is this real|legit)\b",
     "My apologies, I think that's because our office number is not saved "
     "as a contact in your phone.",
     r"(not saved|contact in your phone|apolog|our office number|legit|real)"),

    ("Clients we work with",
     r"\b(what clients|which clients|who (are|is) (your|the) client)\b",
     "Our main client right now is AT&T but we also work with clients in "
     "other industries such as Verizon, T-Mobile, Apple, Google and Samsung.",
     r"(at&?t|verizon|t.?mobile|apple|google|samsung|client)"),
]

# An outright refusal to answer. Checked BEFORE the facts, because the
# refusal usually NAMES the thing it is refusing to discuss — "I am not able
# to go into details about remote or flexible work options" contains the word
# "remote" and scored as a correct answer about remote work on the strength
# of it (Megan 2026-09-27: "this would not be approved"). Saying the word is
# not answering the question; refusing is refusing, whatever words it uses.
REFUSES = re.compile(
    r"((i'?m |i am |we'?re |we are )?not able to (go into|discuss|share|"
    r"provide|give|get into)|"
    r"(can'?t|cannot|unable to) (really )?(go into|discuss|share|say|"
    r"provide|get into|give)|"
    r"(that|this|those) (is|are) (something|details?) "
    r"(i|we) (can'?t|cannot|don'?t))", re.I)

# Pushing the answer away when an approved answer exists.
DEFERS = re.compile(
    r"((hiring )?manager|recruiter|director|hr)\b[^.?!]{0,40}\b"
    r"(can|will|would|is able to|to)\s+"
    r"(go over|explain|cover|discuss|answer|clarify|walk|provide|give|share)|"
    r"(i|we)('| wi)?ll have the (hiring )?(manager|recruiter)|"
    r"that'?s something the (hiring )?(manager|recruiter)|"
    r"(go over|discuss|cover) (that|it|those|all of that|the details) "
    r"(on|during|in|at) the (call|interview|zoom|meeting)|"
    r"not able to (go into|discuss|share)|"
    r"(during|in) (the|your) (interview|zoom|meeting)", re.I)

_COMPILED = [(n, re.compile(q, re.I), a, re.compile(m, re.I))
             for n, q, a, m in REBUTTALS]


def match(question):
    """Which approved rebuttals this question is asking for, if any."""
    return [(n, a, m) for n, q, a, m in _COMPILED if q.search(question or "")]


def score(question, reply):
    """(topic, verdict, approved answer) for one exchange, or None.

    verdict: "gave_it" | "deflected" | "ignored"
    """
    hits = match(question)
    if not hits:
        return None
    name, approved, must = hits[0]
    body = " ".join((reply or "").split())
    if REFUSES.search(body):
        return name, "deflected", approved
    if must.search(body):
        return name, "gave_it", approved
    if DEFERS.search(body):
        return name, "deflected", approved
    return name, "ignored", approved


# HOUSE STYLE, not content. Megan 2026-09-27: "I don't like that the company
# is in all caps", then "I don't like an all caps address either" — and the
# standing house rule is title-cased names. A shouted line is a fault whatever
# else the reply gets right, so it is counted apart from whether the question
# was answered. Exclusions are the genuine initialisms; the rest is shouting.
SHOUTING = re.compile(
    r"\b(?!AT&T|ATT|USA|PST|CST|EST|CDT|EDT|ASAP|HR|ID|OK|B2B|D2D|ZIP|TX|"
    r"NY|CA|FL|AM|PM|SMS|FAQ|CEO|COO|LLC|INC)"
    r"[A-Z]{4,}(?:[ ,.&-]+[A-Z0-9]{2,})*")


# "ZOOM: https://..." is a field LABEL in the Directions template, not
# shouting in a sentence, and at 2,065 uses it drowned the fault Megan
# actually named. A capitalised word immediately followed by a colon is a
# label; anything else in block capitals is shouting.
LABEL = re.compile(r"^[A-Z0-9 ]{2,20}:")


# A company signature is not shouting either. "ALPHALETE MARKETING, INC"
# is how the business is spelled, and flagging it told Leticia Robinson she
# shouted five times for typing her employer's name. A run made up ENTIRELY
# of brand words and corporate vocabulary is a name; one word of anything
# else and it is back to being a shout.
CORPORATE = set("""ALPHALETE VANTURA INC LLC CORP CORPORATION LTD CO
COMPANY GROUP MARKETING ENTERPRISES SOLUTIONS HOLDINGS THE AND OF""".split())


def _is_company_name(run):
    words = [w for w in re.split(r"[^A-Z0-9&]+", run.upper()) if w]
    return bool(words) and all(w in CORPORATE for w in words)


# An address or link is not shouting. AppStream echoes the applicant's own
# email back in capitals ("verify that your email address is
# VEGAMARTHA01@GMAIL.COM") and every one of the last three flags was that.
ADDRESSY = re.compile(r"\S+@\S+|https?://\S+|\S+\.(?:com|net|org|io|co|edu)\b",
                      re.I)


def _addressy_spans(body):
    return [(m.start(), m.end()) for m in ADDRESSY.finditer(body)]


_JOB_RE = None


def _is_job_title(run):
    """Is this capitalised run the job NAME rather than shouting?

    AppStream carries the job ad's own title into the templates, and the ads
    are written in capitals: "ENTRY LEVEL CUSTOMER REPRESENTATIVE". Every one
    of Aisha Ceron's 14 "shouts" in 11280 was that string — a recruiter told
    she shouts 14 times would rightly say she wrote none of them. Same trap
    as the 36 "sent people to Grand Prairie" messages that were job-ad
    titles. Single-sourced off analyze.JOB_TITLE so the two lists cannot
    drift; imported late because analyze imports this module."""
    global _JOB_RE
    if _JOB_RE is None:
        from automations.sms_audit.analyze import JOB_TITLE
        _JOB_RE = re.compile(JOB_TITLE, re.I)
    return bool(_JOB_RE.search(run))


def shouts(text):
    """The shouted run in this message, or None."""
    body = " ".join((text or "").split())
    skip = _addressy_spans(body)
    for m in SHOUTING.finditer(body):
        tail = body[m.end():m.end() + 2]
        if tail.startswith(":"):
            continue                      # a field label, not shouting
        if any(a < m.end() and m.start() < b for a, b in skip):
            continue                      # inside an email address or link
        got = m.group(0).strip(" ,.&-")
        if got and not _is_job_title(got) and not _is_company_name(got):
            return got
    return None


# Saying there is a BASE pay is itself a fault, not just an incomplete
# answer (Raf via Megan, 2026-09-27). The ARS doc still carries the older
# "base salary is determined on your background/experience" line, so this
# is a wording bookers are being taught, and it needs naming wherever it
# appears rather than quietly passing as a correct pay answer.
SAYS_BASE = re.compile(r"\bbase\s+(weekly\s+)?(pay|salary|rate)\b|"
                       r"\bbase\b(?=[^.?!]{0,30}\b(pay|salary))", re.I)


def says_base_pay(text):
    m = SAYS_BASE.search(" ".join((text or "").split()))
    return m.group(0).strip() if m else None


# The office each account should be naming. Per ACCOUNT, and the SAME at
# every stage of the process: Megan 2026-09-27, "carlos' account has a
# different address than that because he's in another office", and "Raf's
# always go to Irving address regardless of where they are in the interview
# process. Carlos has the same for his location." The ARS doc's separate
# Grand Prairie "2nd Confirmation" address is Carlos's own office, not a
# second-round venue for Raf's candidates.
#
# 24065 has never sent a correct one: 21 "Unit 232", 2 "3000 Premier Drive",
# and 6 sending Raf's candidates to Carlos's Grand Prairie office.
OFFICE_ADDRESS = {
    "11280": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
    "23965": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
    "24065": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
    # Confirmed by Megan in her own words, 2026-09-27.
    "11580": "1901 N Highway 360, Suite 610, Grand Prairie, Texas 75050",
}
_STREET = re.compile(r"(\d{3,5})\s+([A-Za-z0-9.' ]{3,28}?)\s*"
                     r"(Dr|Drive|St|Street|Rd|Road|Blvd|Hwy|Highway|Ln|Lane)\b"
                     r"[^.!?\n]{0,40}", re.I)
_UNIT = re.compile(r"(Unit|Suite|Ste\.?)\s*(\w+)", re.I)


def wrong_address(office, text):
    """The offending address in this message, or None.

    Flags a street number or a suite that is not this office's."""
    want = OFFICE_ADDRESS.get(office)
    if not want:
        return None
    body = " ".join((text or "").split())
    m = _STREET.search(body)
    if not m:
        return None
    if m.group(1) not in want:
        return m.group(0).strip()
    unit = _UNIT.search(body)
    if unit and unit.group(2).lower() not in want.lower():
        return m.group(0).strip()
    return None
