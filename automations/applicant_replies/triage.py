"""Which applicant messages Lucy would pick up, and why.

Option B from the 2026-10-20 exploration: Lucy works ALONGSIDE eStream's AI
("A. Messaging"), never over it. She only takes the moments the AI hands off
or can't handle — so an applicant never gets two answers to one question.

A "turn" is one or more applicant texts in a row; what we said next is the
first outbound text after the last of them. Reasons, first match wins:

  opt_out     they said stop / not interested — Lucy stays QUIET (a reply
              to an opt-out is the one text that must never go)
  spanish     AppStream blocks the AI from answering Spanish (ruling table,
              appstream-ai-settings.md: "Non-English Language Detected" is
              Silent Only)
  scam        "is this real" — also Silent Only and blocked
  call_me     #1 thing applicants text; the AI escalates and a person has to
              ring them. Lucy confirms, and makes sure a person is told
  dodged      the AI answered, but deflected or ignored a question we have
              an approved answer for (rebuttals.score)
  unanswered  nothing from us within WAIT_MINUTES

Everything else the AI or a recruiter already handled, and Lucy leaves alone.
"""
from __future__ import annotations

import datetime as dt
import re

from automations.applicant_replies import config as C
from automations.sms_audit import analyze as A
from automations.sms_audit import rebuttals as R

REASONS = ("opt_out", "spanish", "scam", "call_me", "scheduling", "dodged",
           "unanswered")

# Reasons Lucy never writes a text for — a person acts, Lucy only tells them.
NO_TEXT = ("opt_out", "scheduling")

CALL_ME = re.compile(
    r"\b(call me|give me a call|can (you|someone|u) call|could (you|someone) "
    r"call|please call|rather (talk|speak)|prefer (a )?(call|to talk)|"
    r"talk (on|over) the phone|phone call|call (me )?back|"
    r"(can|could) we (talk|speak)|ll?amame|ll[áa]mame|"
    # the complaint form: Megan's 10/1 example, "no one called me"
    r"(no one|nobody|noone) (has )?call(ed)?|"
    r"(didn'?t|did not|never|haven'?t) (get|got|receive[d]?) (a |any |the |your )?"
    r"calls?)\b", re.I)

# Withdrawing is saying no, in more words than analyze.SAID_NO knows.
OPT_OUT_EXTRA = re.compile(r"\b(withdraw\w*|cancel my (application|candidacy)|"
                           r"no longer (want|looking)|take me off)\b", re.I)

# Booking talk is the AI's and the recruiters' job: they hold the calendar.
# Lucy can't see it, so she never answers these — at most she tells the team
# one has been waiting.
SCHEDULING = re.compile(
    r"\b(reschedul\w*|cancel\w*|can'?t make it|won'?t (be able to )?make it|"
    r"running late|be late|i can do|i can make|works for me|that works|"
    r"(am|i'?m) available|available (on|at|after|before)|"
    r"\d{1,2}(:\d{2})?\s?(am|pm)\b|\d{1,2}:\d{2}|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|"
    r"today at|another (time|day)|different (time|day)|what times?)\b", re.I)

# iPhone reactions arrive as texts: 'Liked "See you then"'.
REACTION = re.compile(r"^\s*(liked|loved|laughed at|emphasized|disliked|"
                      r"questioned|reacted \S+ to)\s+[“\"]", re.I)

SCAM_TOPIC = "Spam / scam likely"


def is_spanish(text):
    """Two Spanish words is enough: "De que es el trabajo" has only two the
    list knows, and English almost never carries two of them."""
    t = text or ""
    if A.SPANISH_MARKS.search(t):
        return True
    hits = {m.group(0).lower() for m in A.SPANISH.finditer(t)}
    return len(hits) >= 2


# analyze.CLOSER takes one closing phrase ("ok", "thanks"); applicants
# usually send two ("Ok thanks!", "Yes see you then"). A turn made only of
# these words closes the loop and needs nothing back.
CLOSER_WORDS = set("""ok okay k kk c y yes yep yeah yup sure great perfect
awesome cool thanks thank you ty so much very again sounds good got it will
do see then there soon confirmed confirm i'm im am appreciate it alright np
too enjoy your weekend day night of course likewise good to go same have a
nice and once again no questions so far still all set""".split())


def is_closer(text):
    if A.CLOSER.match(text or ""):
        return True
    words = [w for w in re.split(r"[^\w']+", (text or "").lower()) if w]
    return bool(words) and len(words) <= 8 and all(w in CLOSER_WORDS
                                                   for w in words)


def turns(convo):
    """[{q, at, msgs, reply, reply_msg, wait_min}] for one conversation."""
    msgs = convo["msgs"]
    out, i = [], 0
    while i < len(msgs):
        if msgs[i]["dir"] != "In":
            i += 1
            continue
        j = i
        while j + 1 < len(msgs) and msgs[j + 1]["dir"] == "In":
            j += 1
        group = msgs[i:j + 1]
        nxt = msgs[j + 1] if j + 1 < len(msgs) else None
        last = group[-1]["when"]
        out.append({
            "q": " ".join(" ".join((m["body"] or "").split()) for m in group),
            "at": last,
            "upto": j,                       # index of the last applicant text
            "reply_msg": nxt,
            "reply": (nxt or {}).get("body", ""),
            "wait_min": ((nxt["when"] - last).total_seconds() / 60.0
                         if nxt else None),
        })
        i = j + 1
    return out


def classify(turn, log_end=None):
    """(reason, detail) or (None, why_left_alone)."""
    q = turn["q"]
    if REACTION.match(q):
        return None, "an iPhone reaction, not a message"
    if A.SAID_NO.search(q) or OPT_OUT_EXTRA.search(q):
        return "opt_out", "said stop / not interested / withdrawing"
    rep = turn["reply_msg"]
    wait = turn["wait_min"]
    answered = rep is not None and wait is not None and wait <= C.WAIT_MINUTES
    if answered and not A.is_ai(rep):
        # A person already has this thread. Lucy never answers over them.
        return None, "a recruiter answered"
    hits = R.match(q)
    if not answered:
        if is_spanish(q):
            return "spanish", "AppStream's AI is blocked from Spanish"
        if hits and hits[0][0] == SCAM_TOPIC:
            return "scam", "AppStream's AI is blocked from scam questions"
        if CALL_ME.search(q):
            return "call_me", "asked for a phone call"
    booking = bool(SCHEDULING.search(q))
    if booking and not hits:
        if answered:
            return None, "booking talk, answered"
        if rep is None and log_end is not None and \
                (log_end - turn["at"]) < dt.timedelta(minutes=C.WAIT_MINUTES):
            return None, "log ends before the wait was up"
        return "scheduling", ("booking talk waiting {} min".format(int(wait))
                              if wait is not None else "booking talk never answered")
    if answered:
        s = R.score(q, rep.get("body"))
        # "Can we schedule a call?" trips the hours topic on the word alone;
        # that is booking talk, and the AI handing it on is right.
        if s and s[1] in ("deflected", "ignored") and \
                not (booking and s[0] == "Schedule / hours"):
            return "dodged", "AI {} a {} question".format(s[1], s[0].lower())
        return None, "AI answered"
    if is_closer(q):
        return None, "closes the loop (ok / thanks)"
    if rep is None and log_end is not None:
        if (log_end - turn["at"]) < dt.timedelta(minutes=C.WAIT_MINUTES):
            return None, "log ends before the wait was up"
    return "unanswered", ("no reply in {} min".format(int(wait))
                          if wait is not None else "never answered")


def pick(convos, log_end=None):
    """[(convo, turn, reason, detail)] — every moment Lucy would take."""
    out = []
    for c in convos.values():
        for t in turns(c):
            reason, detail = classify(t, log_end)
            if reason:
                out.append((c, t, reason, detail))
    return out
