# -*- coding: utf-8 -*-
"""One weekly scorecard per recruiter, week over week.

Megan 2026-10-06: "maybe each recruiter gets their own scorecard for the
week- with a breakdown of what they need to work on week over week stats".

Everything here is already measured somewhere in the audit; this slices it
by PERSON and by WEEK so one recruiter can be handed their own page.

Two traps this module exists to avoid:

**The same person has two names.** Bookings come back as "L. Robinson"
(the Retention Report's initial-and-surname form) while texts come back as
"Leticia Robinson". Keyed naively, every scorecard shows bookings with no
texts or texts with no bookings. `key_of` folds both to first-initial +
surname, and `display` keeps the longest spelling seen.

**A week with no pull must stay blank.** analyze.load_log warns that a
suffixed run with no matching log quietly borrows the current week — which
is how two different weeks once ended up identical. A week is skipped
entirely unless BOTH its booking dump and its log are on disk.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import collections
import datetime as dt
import re
import statistics
import sys
from pathlib import Path

from automations.sms_audit import analyze as A
from automations.sms_audit import gradecard as GC
from automations.sms_audit import offices as O
from automations.sms_audit import retention as R

OUTPUT = Path(__file__).resolve().parents[2] / "output"
AI_NAMES = {"a messaging", "ai messaging", "lucy resume pushing", "system",
            "scheduled sms"}
# Below this many texts in a week a rate is one bad morning, not a trend.
MIN_TEXTS = 25
# And below this many MATCHED bookings, a far-out percentage is noise: one
# week of Aisha Ceron's read 100% off two bookings and the next read 0%.
MIN_MATCHED = 10
# What a suppressed cell says instead of a bare dash. Two reasons, two
# labels: not enough bookings to rate, versus a booking whose lead time
# cannot be read because it was never set by a text. Megan 2026-10-06:
# "max is marked too few booked but he has 39 booked" — he had, and he
# sent six texts all week.
TOO_FEW = "Too Few"
NO_TEXT = "Booked by Phone"


_FACTS_DONE = set()


def _load_office_facts(oid):
    """Point the per-office checks at THIS office before scoring its texts.

    The scorecard scores the same messages as the audit, so it needs the
    same facts; without them every office is marked against whichever one
    was configured last."""
    if oid in _FACTS_DONE:
        return
    _FACTS_DONE.add(oid)
    try:
        from automations.sms_audit import icd_audit as IA
        row = [o for o in (O.load()[0] or []) if o.get("office") == oid]
        if row:
            IA.apply_address_history(row[0])
    except Exception:  # noqa: BLE001 — a missing config is a gap, not a crash
        pass


def key_of(name):
    """'L. Robinson' and 'Leticia Robinson' -> the same key.

    A trailing team tag is dropped before the surname is taken, but only
    when a real surname is left behind. Without that, "Max Jimenez APT"
    keys on APT, and so do "Anthony Zelaya APT" and "Abdiel Amador APT" —
    three people on one scorecard. With it, "C. NLR" and "Caitlyn NLR"
    still pair, because stripping NLR there would leave nothing to match
    on."""
    n = re.sub(r"[^A-Za-z .'-]", " ", (name or "")).strip()
    if not n:
        return ""
    parts = [p for p in re.split(r"\s+", n) if p]
    if len(parts) >= 3 and parts[-1].isupper() and 2 <= len(parts[-1]) <= 4:
        parts = parts[:-1]
    if len(parts) == 1:
        return parts[0].lower().strip(".")
    first, last = parts[0], parts[-1]
    return "{}.{}".format(first[0].lower(), last.lower())


def is_ai(name):
    n = re.sub(r"[^a-z ]", "", (name or "").lower()).strip()
    return n in AI_NAMES or key_of(name) in {key_of(x) for x in AI_NAMES}


def _median(xs):
    return statistics.median(xs) if xs else None


def week_stats(office, tag):
    """{key: {...}} for one week, or {} when that week was not pulled."""
    oid = office if isinstance(office, str) else office["office"]
    _load_office_facts(oid)
    recs, _s = A.load_office(oid, tag)
    log, _s2 = A.load_log(oid, tag)
    if not recs or not log:
        return {}                      # never borrow another week's answer
    convos = A.log_conversations(log, A.booked_index(recs))

    out = collections.defaultdict(lambda: {
        "display": "", "booked": 0, "shown": 0, "texts": 0,
        "typing": 0, "house": 0, "dodged": 0, "replies": [],
        "far_out": 0, "matched": 0,
        "silent": 0, "silent_shown": 0, "talked": 0, "talked_shown": 0,
        "issues": collections.Counter(), "examples": [], "asked": [],
        "weak": [], "kinds": collections.Counter(), "typos": []})

    def slot(name):
        k = key_of(name)
        if not k:
            return None
        d = out[k]
        def _fullness(x):
            return (sum(c.isalpha() for c in x or ""), len(x or ""))
        if _fullness(name) > _fullness(d["display"]):
            d["display"] = name
        return d

    from automations.sms_audit import leadtime as LT
    lead = LT.measure(oid, recs=recs, log=log)

    # Who actually spoke to us before the slot. Across Jorge Pena's 702
    # bookings the applicants who never replied showed at 19% and the
    # ones who sent 3+ messages at 65% — the single biggest split in the
    # data, and it is the thing a recruiter can act on.
    said = {}
    for c in convos.values():
        ph = re.sub(r"\D", "", c.get("phone") or "")[-10:]
        if ph:
            said[ph] = sum(1 for m in (c.get("msgs") or [])
                           if m.get("dir") == "In")
    booked_here = {r["name"] for r in (lead.get("rows") or [])} \
        if lead.get("ok") else set()

    for r in recs:
        d = slot(r.get("booked_by"))
        if d is None:
            continue
        d["booked"] += 1
        shown_ = "No Show" not in (r.get("status") or "")
        if shown_:
            d["shown"] += 1
        ph = re.sub(r"\D", "", r.get("phone") or "")[-10:]
        if ph in said and r.get("name") in booked_here:
            if said[ph]:
                d["talked"] += 1
                d["talked_shown"] += shown_
            else:
                d["silent"] += 1
                d["silent_shown"] += shown_

    for row in log:
        if (row.get("type") or "").strip() != "Out":
            continue
        d = slot(row.get("sent_by") or row.get("source"))
        if d is not None:
            d["texts"] += 1

    for e in A.text_errors(convos):
        d = slot(e.get("sender"))
        if d is None:
            continue
        d["typing"] += 1
        kind = e.get("kind") or "typing"
        d["kinds"][kind] += 1
        if len(d["typos"]) < 40:
            d["typos"].append((kind.capitalize(), needle_of(e.get("detail")),
                               e.get("body") or "", e.get("name") or "",
                               "", []))

    who_said = {}
    for c in convos.values():
        for m in c.get("msgs") or ():
            b = " ".join((m.get("body") or "").split())
            if b and b not in who_said:
                who_said[b] = c.get("name") or ""

    def applicant(body):
        return who_said.get(" ".join((body or "").split()), "")

    # The WHOLE conversation per applicant, not the audit's context
    # window. Megan 2026-10-06: "what happened to diego's convo on the
    # card??" — the window cut off before the part that mattered. Diego
    # Sandoval rescheduled four times over a time zone, was turned away
    # from the waiting room, then wrote again the next day and got
    # nothing back; the card showed none of that.
    threads = {}
    for c in convos.values():
        name = c.get("name") or ""
        msgs = sorted(c.get("msgs") or [], key=lambda m: m["when"])
        if name and len(msgs) > len(threads.get(name, ())):
            threads[name] = [(m.get("dir"), " ".join((m.get("body") or "")
                                                     .split()))
                             for m in msgs]

    for e in A.who_to_talk_to(convos, oid):
        d = slot(e.get("sender"))
        if d is None:
            continue
        n = int(e.get("count") or 0)
        d["house"] += n
        d["issues"][e.get("issue") or "?"] += n
        for ex in (e.get("examples") or [])[:8]:
            d["examples"].append((e.get("issue") or "?", ex.get("hit") or "",
                                  ex.get("body") or "",
                                  applicant(ex.get("body")), "", []))

    for e in A.dodged_questions(convos):
        d = slot(e.get("sender"))
        if d is None:
            continue
        # A deflection is already the house rule "Pushed a job question
        # to the hiring manager" — who_to_talk_to owns it. Counting it
        # here too put Itza Castrejon's thread in both sections and
        # inflated the unanswered total (Megan 2026-10-06: "this should
        # be in the pushed to hirring manager section?").
        if (e.get("kind") or "") == "deflected":
            continue
        # Answered further down the thread is answered. Megan 2026-10-06
        # on Jaysel Rosa, whose immediate reply was "Awesome!" but who
        # got a real answer three messages later: "i feel like he did
        # answer this one". 56% of what this section was reporting had
        # been answered in the end.
        if str(e.get("answered_later")).lower() == "true":
            continue
        d["dodged"] += 1
        if not e.get("question"):
            continue
        # A weak answer and a non-answer need different coaching, so they
        # are kept apart (Megan 2026-10-06).
        slotname = ("weak" if is_weak(e.get("question"), e.get("reply"))
                    else "asked")
        if len(d[slotname]) < 20:
            d[slotname].append((
                "{}: {}".format(
                    "Weak answer" if slotname == "weak" else "Did not answer",
                    e.get("bucket") or "a question"),
                "they asked: {}".format(e["question"]),
                e.get("reply") or "", e.get("name") or "",
                left_hanging(threads.get(e.get("name") or "")) or
                why_dodged(e.get("bucket"), e.get("kind"),
                           e.get("question"), e.get("reply"), e),
                threads.get(e.get("name") or "") or
                [(m.get("dir"), (m.get("body") or "").strip())
                 for m in (e.get("context") or [])]))

    for st in A.reply_speed_by_sender(convos, min_n=1):
        d = slot(st.get("who"))
        if d is not None:
            d["replies"] = st

    # How far ahead each person booked, from the confirmation text that set
    # the appointment. Megan 2026-10-06 asked whether a falling show rate
    # really was someone booking further out — without this the scorecard
    # was asserting a cause it had not checked.
    if lead.get("ok"):
        for row in lead["rows"]:
            d = slot(row.get("by"))
            if d is None:
                continue
            d["matched"] += 1
            if LT.bucket_of(row["lead"]) == "more than a day":
                d["far_out"] += 1
    return dict(out)


def collect(office, weeks=None):
    """{key: {'display', 'weeks': {tag: stats}}} across every pulled week."""
    weeks = weeks or R.WEEKS
    people = {}
    for tag in weeks:
        for k, d in week_stats(office, tag).items():
            p = people.setdefault(k, {"display": "", "weeks": {}})
            if (sum(c.isalpha() for c in d["display"]),
                    len(d["display"])) > (
                    sum(c.isalpha() for c in p["display"]),
                    len(p["display"])):
                p["display"] = d["display"]
            p["weeks"][tag] = d
    return people


# ----------------------------------------------------------- what to fix

def _rate(d, num, den):
    n, t = d.get(num) or 0, d.get(den) or 0
    return (100.0 * n / t) if t else None


def best_near_week(person, weeks, far_now, show_now):
    """(tag, retention, far) for their best week that booked nearer, or None.

    Only returns a week where BOTH numbers are solid: enough bookings to
    rate, and enough matched confirmations to know the lead. Without that
    guard this would quote a 100% week built on one booking."""
    best = None
    for tag in weeks:
        w = person["weeks"].get(tag)
        if not w or (w.get("booked") or 0) < MIN_MATCHED:
            continue
        if (w.get("matched") or 0) < MIN_MATCHED:
            continue
        ret = _rate(w, "shown", "booked")
        f = _rate(w, "far_out", "matched")
        if ret is None or f is None:
            continue
        if ret <= show_now or f >= far_now - 5:
            continue
        if best is None or ret > best[1]:
            best = (tag, ret, f)
    return best


def work_on(person, weeks):
    """[(area, now, before, grade, what to do)] worst first.

    Megan 2026-10-06: "The AI should have a report card too". It books
    more than anyone, so it belongs here — but you do not coach it. Every
    instruction below is rewritten for it: a person reads their text back,
    the AI gets its message edited in AppStream."""
    got = [w for w in weeks if w in person["weeks"]]
    if not got:
        return []
    bot = is_ai(person.get("display"))
    now = person["weeks"][got[-1]]
    before = person["weeks"][got[-2]] if len(got) > 1 else None
    items = []

    def add(area, value, grade, text, prev=None, goal=""):
        if grade:
            items.append({"area": area, "now": value, "before": prev,
                          "grade": grade, "do": text, "goal": goal})

    show = _rate(now, "shown", "booked")
    if show is not None and (now.get("booked") or 0) >= 5:
        prev = _rate(before, "shown", "booked") if before else None
        booked_n = (now.get("silent") or 0) + (now.get("talked") or 0)
        silent_share = (100.0 * now["silent"] / booked_n
                        if booked_n >= 20 else None)
        silent_rate = _rate(now, "silent_shown", "silent")
        talked_rate = _rate(now, "talked_shown", "talked")
        if silent_rate is None or talked_rate is None:
            silent_share = None
        far = (_rate(now, "far_out", "matched")
               if (now.get("matched") or 0) >= MIN_MATCHED else None)
        farwas = (_rate(before, "far_out", "matched")
                  if before and (before.get("matched") or 0) >= MIN_MATCHED
                  else None)
        if far is not None and farwas is not None and far - farwas >= 5:
            why = ("You're booking further out than you were: {:.0f}% more "
                   "than a day ahead, up from {:.0f}%. Book them same or "
                   "next day, while the interest is still fresh."
                   .format(far, farwas))
        elif far is not None and far >= 25:
            why = ("{:.0f}% of your bookings are more than a day out. Book "
                   "them same or next day, while the interest is still "
                   "fresh.".format(far))
            # Megan 2026-10-06: "56% last week when you didn't book far
            # out - or something like that should be added if that's the
            # case". Only when it IS the case: their own best week where
            # the far-out share was measurable and lower.
            proof = best_near_week(person, weeks, far, show)
            if proof:
                why += (" You were at {:.0f}% in the week to {} when only "
                        "{:.0f}% were that far out."
                        .format(proof[1], R.week_label(proof[0]), proof[2]))
        elif silent_share is not None and silent_share >= 25:
            why = ("{:.0f}% of your bookings come from a phone call, and "
                   "only {:.0f}% of those show up \u2014 against {:.0f}% when "
                   "they book by text. Spend longer on the call building "
                   "the relationship, so they can see why the Zoom is worth "
                   "their time."
                   .format(silent_share, silent_rate, talked_rate))
        elif bot:
            why = "Offer sooner interview times."
        else:
            why = ("Your booking times are fine, so the drop is in the "
                   "conversations. Read them below.")
        add("1st Round Retention", "{:.0f}%".format(show),
            GC._band(show, 55, 48, 40), why,
            "{:.0f}%".format(prev) if prev is not None else None,
            goal="55% or better")

    if (now.get("texts") or 0) >= MIN_TEXTS:
        per100 = 100.0 * (now.get("typing") or 0) / now["texts"]
        prevp = (100.0 * (before.get("typing") or 0) / before["texts"]
                 if before and before.get("texts") else None)
        add("Typing and Grammar", "{}".format(now.get("typing")),
            GC._band(per100, 0.5, 2, 5, higher_is_better=False),
            "Fix the wording in AppStream." if bot
            else "Read it back before sending.",
            "{}".format(before.get("typing")) if before else None,
            goal="no more than {:.0f} across {:,} texts".format(
                max(1, round(0.5 * now["texts"] / 100.0)), now["texts"]))

    # Megan 2026-10-06: "6 house rules out of 3k texts sent seems pretty
    # low....", and the same for unanswered questions. Both were graded on
    # the RAW COUNT, so whoever sent most texts looked worst. Measured per
    # 1,000 texts the spread is median 0, 75th percentile 5, worst 124 —
    # Leticia Robinson's 2.0 was scoring the same band as Maria Quintero's
    # 57.6. Bands below are set off that distribution.
    house = now.get("house") or 0
    texts_now = now.get("texts") or 0
    if house and texts_now >= MIN_TEXTS:
        # .get: a week dict from a partial source has no counter, and a
        # missing breakdown is not worth crashing a scorecard over.
        counts = now.get("issues") or collections.Counter()
        worst = counts.most_common(1)[0][0] if counts else "House rules"
        per1k = 1000.0 * house / texts_now
        add("House Rules Broken",
            "{} in {:,} texts".format(house, texts_now),
            GC._band(per1k, 0.5, 3, 8, higher_is_better=False),
            "{}. The exact texts are below.".format(worst),
            "{}".format((before or {}).get("house")) if before else None,
            goal="no more than {:.0f} across {:,} texts".format(
                max(1, round(0.5 * texts_now / 1000.0)), texts_now))

    sp = now.get("replies") or {}
    if sp and sp.get("n", 0) >= 10:
        med = sp.get("median")
        prevmed = (before.get("replies") or {}).get("median") if before else None
        add("Reply speed", A_mins(med),
            GC._band(med, 5, 15, 45, higher_is_better=False),
            "Already instant." if bot else "Answer inside 5 minutes.",
            A_mins(prevmed) if prevmed is not None else None,
            goal="under 5 min")

    dodged = now.get("dodged") or 0
    if dodged and texts_now >= MIN_TEXTS:
        dper1k = 1000.0 * dodged / texts_now
        add("Questions Not Answered",
            "{} in {:,} texts".format(dodged, texts_now),
            GC._band(dper1k, 0.5, 2.5, 4.5, higher_is_better=False),
            "Give it a real answer in AI Settings, Escalations." if bot
            else "Answer it, then book. The exact ones are below.",
            str((before or {}).get("dodged")) if before else None,
            goal="no more than {:.0f} across {:,} texts".format(
                max(1, round(0.5 * texts_now / 1000.0)), texts_now))

    items.sort(key=lambda i: "FDCBA".index(i["grade"]))
    return items


def failing(items):
    """Only what is off target — the three a person is coached on."""
    return [i for i in items if i["grade"] not in "AB"]


# What each area is worth in the overall grade. Retention is the outcome
# everything else feeds, so it carries most; a typo is real but it is not
# why someone did not show up.
WEIGHTS = {"1st Round Retention": 3, "House Rules Broken": 2,
           "Questions Not Answered": 2}
POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


def grade_of(person, weeks):
    """One letter for the week, weighted across every area measured.

    Megan 2026-10-06: "I dont think this is a D scorecard. How are you
    coming to such a low grade?" It was the WORST single area — a rule
    copied from the office card, where "fix the worst thing" is the right
    instinct. On a person it is not: Leticia Robinson improved on three
    of five measures and still read D off one.

    A flat average is no better: it put Leticia and Aisha Ceron both on C
    when Aisha was failing three areas to Leticia's one. Weighted, they
    separate."""
    items = work_on(person, weeks)
    if not items:
        return None
    total = weight = 0
    for i in items:
        w = WEIGHTS.get(i["area"], 1)
        total += POINTS[i["grade"]] * w
        weight += w
    return "FDCBA"[min(4, int(round(float(total) / weight)))]

def A_mins(m):
    if m is None:
        return "—"
    m = float(m)
    if m < 60:
        return "{:.0f} min".format(m)
    return "{:.0f} hr {:.0f} min".format(m // 60, m % 60)


# -------------------------------------------------------------- rendering

CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#111;max-width:46em;
     margin:2em auto;padding:0 1.1em;line-height:1.5}
h1{font-size:1.5em;margin:0 0 .1em}
h2{font-size:1.1em;margin:1.8em 0 .5em;border-bottom:2px solid #111;
   padding-bottom:.2em}
.date{color:#666;margin:0 0 1.4em}
table{border-collapse:collapse;font-size:.95em;width:100%}
th,td{border:1px solid #ccc;padding:.3em .6em;text-align:left}
th{background:#f2f2f2}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;margin:.6em 0 1em}
.fix{border:2px solid #111;border-radius:6px;padding:.8em 1em;margin:1.2em 0}
.fix h2{margin-top:0;border:0}
tr.F td,tr.D td{background:#fdeaea}
tr.C td{background:#fff4e5}
.up{color:#156E46;font-weight:bold}
.down{color:#A8322A;font-weight:bold}
blockquote{margin:.4em 0 .4em 1em;padding:.3em .7em;border-left:3px solid #bbb;
           background:#f7f7f7;font-size:.95em}
.none{color:#666;font-style:italic}
.bad{color:#A8322A;font-weight:bold;background:#fdeaea}
.asked{color:#555;font-size:.9em;font-style:italic}
.who{color:#555;font-weight:normal}
.why{color:#A8322A;font-weight:bold;margin-top:.35em}
.fixit{background:#eef5ee;border-left:3px solid #156E46;padding:.4em .7em;
       margin:.4em 0;font-size:.95em}
.thread{margin:.3em 0}
.thread div{margin:.15em 0}
.thread .them{color:#333}
.thread .us{color:#000}
.thread b{color:#777;font-weight:normal;font-size:.9em}
ol.focus{margin:.4em 0 0;padding-left:1.3em}
ol.focus li{margin:.6em 0}
.moved{color:#777;font-weight:normal;font-size:.9em}
.gradebox{display:flex;gap:.7em;align-items:baseline;margin:0 0 1em}
.letter{font-size:3em;font-weight:bold;line-height:1}
.letter.A,.letter.B{color:#156E46}
.letter.C{color:#8a6d00}
.letter.D,.letter.F{color:#A8322A}
.gradenote{color:#666}
.goal{color:#156E46}
td.gr{text-align:center;font-weight:bold}
td.gr.A,td.gr.B{color:#156E46}
td.gr.C{color:#8a6d00}
td.gr.D,td.gr.F{color:#A8322A}
.well{border:1px solid #156E46;background:#f1f7f1;border-radius:6px;
      padding:.7em 1em;margin:1.2em 0}
.well h2{margin:0 0 .3em;border:0;color:#156E46;font-size:1em}
.well ul{margin:.2em 0;padding-left:1.2em}
details{margin:.35em 0;border:1px solid #ddd;border-radius:4px;
        padding:.4em .7em;background:#fafafa}
details[open]{background:#fff}
summary{cursor:pointer;font-weight:bold}
summary::marker{color:#888}
@media (max-width:640px){body{margin:1em auto;font-size:15px}}
"""


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


ASKED = re.compile(r"^\s*they asked:\s*", re.I)


# What each question bucket is actually ASKING, so the fault can be stated
# in words rather than left for the reader to work out. Megan 2026-10-06:
# "we need why this is wrong in red ... Didn't answer the driving question
# or where the location was. Answer isn't relevant to what was asked."
TOPICS = {
    "Is this remote / where is the office?":
        "whether the job is remote and where the office is",
    "What is the pay?": "the pay",
    "Which role / which company is this?": "which role and company this is",
    "What is the job / what do you do?": "what the job actually is",
    "Hours, training, is it paid?":
        "the hours and whether training is paid",
    "How long is the interview / what's next?":
        "how long the interview is",
    "What should I wear / bring?": "what to wear or bring",
    "When will you call me / what number?": "when we would call",
    "How do I join the Zoom / link trouble?": "how to join the Zoom",
    "Can we reschedule / a different time?": "a different time",
    "I can't make it / I'm sick / running late":
        "that they could not make it",
    "Is this a real job / who are you?": "whether this is a real job",
    "I never got the email": "the email they never got",
    "Am I still being considered?":
        "whether they are still being considered",
    "Are you there? (chasing us for a reply)": "their chase for a reply",
}


# They have told us the answer decides it: "if not I'm not interested",
# "otherwise I'll pass". A vague reply to THAT is not the same fault as a
# vague reply to an idle question — Megan 2026-10-06, shown both carrying
# one line: "these can't be the same".
WALKS = re.compile(r"(if not[, ]|otherwise|or else|then)?[^.?!]{0,24}"
                   r"\b(not interested|no longer interested|i'?ll pass|"
                   r"i'?m out|don'?t bother|forget it|lose interest)\b", re.I)

YES_NO = re.compile(r"^\s*(is|are|was|were|do|does|did|can|could|will|would|"
                    r"should|has|have|am)\b", re.I)
SAYS_YES_NO = re.compile(r"\b(yes|yep|yeah|no|nope|not|isn'?t|aren'?t|"
                         r"doesn'?t|don'?t|won'?t|correct|incorrect)\b", re.I)


# How to get the conversation back to a booking, per topic. Megan
# 2026-10-06: "if they are weak then it should be it's own section with a
# recommendation of how to keep the convo going to get the interview
# booked".
RECOVERY = {
    # One short line each. Megan 2026-10-06 cut these twice for being too
    # much direction, and ruled out offering interview times: answer and
    # keep them talking, booking is a separate step.
    #
    # The store answer is the ARS doc's (line 149), not mine. Its other
    # version leans on "we work with LEADS", which Megan rejected on
    # 2026-10-01, so that is left out.
    "Is this remote / where is the office?":
        "Say it is in person with customers but not at a retail location. "
        "Give the office address and ask if that is a commute they can "
        "commit to.",
    "What is the pay?":
        "Give the weekly range. Ask what they were hoping for.",
    "What is the job / what do you do?":
        "Say what a day looks like. Ask if that sounds like them.",
    # Megan's own words, including "employment" rather than "work".
    "Which role / which company is this?":
        "Tell them the job they applied to. Ask if that sounds familiar, "
        "and if they are still looking for employment.",
    "Hours, training, is it paid?":
        "Give the hours and say the training is paid.",
    # The templates say "Business Casual" in one place and "Dress to
    # Impress" in another, so point at the office's own wording.
    "What should I wear / bring?":
        "Give the dress code from the confirmation text.",
    "How long is the interview / what's next?":
        "Say how long it takes and what happens after.",
    "Is this a real job / who are you?":
        "Give your name, the company and the website.",
}


def recovery_for(bucket):
    return RECOVERY.get(bucket) or (
        "Answer it, then ask them something back.")


def is_weak(question, reply):
    """True when the reply technically answers but says nothing plainly.

    Megan 2026-10-06 on "Is the position in a store?" -> "This is a
    residential campaign": "technically this does answer but is a bit
    dodgy, should ask something back"."""
    q, r = (question or "").strip(), reply or ""
    return bool(YES_NO.match(q) and not SAYS_YES_NO.search(r)
                and "?" not in r)


# Worst first. Two faults in one thread do not need two sentences; the
# one that cost the most is the one to read.
SEVERITY = ("wrote last and never got a reply", "went round in circles",
            "walk away", "in a row",
            "Gave how long", "Gave a time", "vague", "Doesn't answer")


def what_else_moved(now, before):
    """' What also moved: ...' naming the measures that improved with it.

    Megan 2026-10-06, on "Keep doing whatever changed": "we need to know
    what changed- not just to keep doing it". These are the things that
    moved the same week, not proven causes — the sentence says moved, not
    caused."""
    if not before:
        return ""
    bits = []
    med_now = (now.get("replies") or {}).get("median")
    med_was = (before.get("replies") or {}).get("median")
    if med_now is not None and med_was is not None and med_was - med_now >= 2:
        bits.append("you replied faster ({}, was {})".format(
            A_mins(med_now), A_mins(med_was)))

    def share(w):
        tot = (w.get("silent") or 0) + (w.get("talked") or 0)
        return (100.0 * w["silent"] / tot) if tot >= MIN_MATCHED else None

    ph_now, ph_was = share(now), share(before)
    if ph_now is not None and ph_was is not None and ph_was - ph_now >= 5:
        bits.append("fewer came from a call ({:.0f}%, was {:.0f}%)".format(
            ph_now, ph_was))

    far_now = (_rate(now, "far_out", "matched")
               if (now.get("matched") or 0) >= MIN_MATCHED else None)
    far_was = (_rate(before, "far_out", "matched")
               if (before.get("matched") or 0) >= MIN_MATCHED else None)
    if far_now is not None and far_was is not None and far_was - far_now >= 5:
        bits.append("you booked nearer the slot ({:.0f}% over a day out, was "
                    "{:.0f}%)".format(far_now, far_was))

    if not bits:
        return (" Nothing else in these numbers moved with it, so it is "
                "worth asking what you did differently.")
    if len(bits) > 1:
        bits[-1] = "and " + bits[-1]
    return " What also moved: {}.".format(
        (", " if len(bits) > 2 else " ").join(bits) if len(bits) > 1
        else bits[0])


def did_well(person, weeks, limit=2):
    """What went RIGHT this week, said as praise.

    Megan 2026-10-06: "we should also have some highlight of something
    they did well", then "this needs to be more encouraging- we want to
    praise them". So each line is written to be read by the person it is
    about. Still only things the numbers show: a measure that moved the
    right way against last week, or a clean sheet on real volume."""
    got = [w for w in weeks if w in person["weeks"]]
    if not got:
        return []
    now = person["weeks"][got[-1]]
    before = person["weeks"][got[-2]] if len(got) > 1 else None
    out = []

    # Megan 2026-10-06, on "only 4 missed, down from 5": "from 5 to 4
    # isn't a big difference". It was praising any improvement at all,
    # however small, and calling it "a lot more". A move has to clear
    # BOTH a quarter of where they started and a floor that means
    # something, or it is this week's noise.
    MIN_REL = 0.25

    done = set()

    def moved(new, old, up_good, show, praise, floor=2.0, zero="", key=""):
        """`zero` is used when the new value is none at all — "only 0
        missed" is not English (Megan 2026-10-06)."""
        if new is None or old is None:
            return
        better = (new > old) if up_good else (new < old)
        if not better:
            return
        gap = abs(new - old)
        if gap < floor or gap < MIN_REL * max(abs(old), 1.0):
            return
        line = (zero or praise) if (zero and not new) else praise
        if key:
            done.add(key)
        out.append((gap / max(abs(old), 1.0),
                    line.format(new=show(new), old=show(old))))

    pct = lambda v: "{:.0f}%".format(v)
    num = lambda v: "{:.0f}".format(v)

    moved(_rate(now, "shown", "booked"),
          _rate(before, "shown", "booked") if before else None, True, pct,
          "More of your bookings turned up \u2014 {new} against {old} last "
          "week." + what_else_moved(now, before), floor=5.0)
    moved(now.get("house"), (before or {}).get("house"), False, num,
          "Good pull back on the house rules \u2014 {new} this week, down "
          "from {old}.", key="house",
          zero="A clean week on the house rules \u2014 nothing broken, down "
               "from {old} last week.")
    moved(now.get("dodged"), (before or {}).get("dodged"), False, num,
          "You answered a lot more of what applicants asked \u2014 only "
          "{new} missed, down from {old}.", key="dodged",
          zero="Every question an applicant asked got an answer, down from "
               "{old} missed last week.")
    moved(now.get("typing"), (before or {}).get("typing"), False, num,
          "Tidier writing this week \u2014 {new} against {old}.", key="typing",
          zero="Not a typo or a grammar slip all week, down from {old}.")
    moved((now.get("replies") or {}).get("median"),
          ((before or {}).get("replies") or {}).get("median"), False, A_mins,
          "You got back to people faster \u2014 {new}, down from {old}. That "
          "is the one applicants feel most.", floor=2.0)
    moved(_rate(now, "far_out", "matched"),
          _rate(before, "far_out", "matched") if before else None, False, pct,
          "You booked people closer to the slot \u2014 {new} more than a day "
          "out, down from {old}.", floor=5.0)

    texts = now.get("texts") or 0
    if texts >= MIN_TEXTS:
        if not now.get("typing") and "typing" not in done:
            out.append((0.4, "Not one typing or grammar mistake in {:,} "
                             "texts.".format(texts)))
        if not now.get("house") and "house" not in done:
            out.append((0.4, "A clean week on the house rules \u2014 nothing "
                             "broken."))
    if (not now.get("dodged") and "dodged" not in done
            and (now.get("booked") or 0) >= 5):
        out.append((0.3, "Every question an applicant asked got an answer."))

    out.sort(key=lambda t: -t[0])
    return [line for _w, line in out[:limit]]


def worst_of(whys):
    """The single worst verdict, whole.

    Megan 2026-10-06: "still redundant/repetitive". An earlier version
    split each line into a head and a chase count and recombined them,
    which stapled one question's "They asked 1 more time" onto the
    circles line that already said "they asked 3 times". Each verdict is
    already a complete sentence — pick one, do not assemble."""
    lines = [w for w in whys if w]
    if not lines:
        return ""

    def rank(h):
        for i, key in enumerate(SEVERITY):
            if key in h:
                return i
        return len(SEVERITY)

    return sorted(lines, key=lambda h: (rank(h), -len(h)))[0]


def left_hanging(thread):
    """'' unless the applicant wrote last and nobody answered.

    Megan 2026-10-06, reading Diego Sandoval's thread: "was there any
    more follow up to this convo? that would be the real red flag". There
    was — he wrote again the next day, after four reschedules and being
    turned away from the waiting room, and got nothing back. A
    conversation that ends on their message is the worst thing on a
    card, so it outranks every other verdict."""
    msgs = [m for m in (thread or []) if (m[1] or "").strip()]
    if len(msgs) < 2 or msgs[-1][0] != "In":
        return ""
    trailing = 0
    for dirn, _body in reversed(msgs):
        if dirn != "In":
            break
        trailing += 1
    return ("They wrote last and never got a reply \u2014 {} message{} left "
            "hanging.".format(trailing, "" if trailing == 1 else "s"))


def why_dodged(bucket, kind="", question="", reply="", entry=None):
    """One red line saying what went wrong with THIS reply.

    Megan 2026-10-06, shown four dodges carrying one identical sentence:
    "this isn't all the same...". They were not. One reply gave the
    interview length to someone asking where the job is; two answered a
    yes-or-no question without saying yes or no. The line is derived from
    what the reply actually does, and falls back to the weakest honest
    claim rather than asserting irrelevance it cannot show."""
    topic = TOPICS.get(bucket) or (bucket or "the question").rstrip("?").lower()
    if kind == "deflected":
        return ("Pushed {} to someone else instead of answering it."
                .format(topic))
    if kind == "informal":
        return "Texting shorthand going out under the company's name."

    q, r = question or "", reply or ""
    e = entry or {}

    # Two questions at once, and the reply picks up the other one. The
    # Janel Mills case: "Is this in a store?" and "How long is the
    # interview?" a second apart, answered "A quick 15-20 minutes".
    # Calling that a wrong-topic reply misread it — it answered, just not
    # this.
    between = 0
    ctx = e.get("context") or []
    seen = False
    for m in ctx:
        body = (m.get("body") or "").strip()
        if not seen:
            seen = body == q.strip()
            continue
        if m.get("dir") == "Out":
            break
        between += 1
    again = reasked(e, bucket, q)
    tail = _chased(e, again=again)

    # Three attempts and still no straight answer is not a slip, it is a
    # conversation nobody was steering.
    if again >= 2 and str(e.get("answered_later")).lower() != "true":
        return ("This went round in circles \u2014 they asked {} times and "
                "never got a straight answer.".format(again + 1))

    if between:
        # Say only what is visible: several questions in a row, one reply.
        # Claiming the reply ANSWERED one of the others was wrong on
        # "Can you verify? I have not applied for AT&T" -> "Thank you for
        # letting us know", which answers none of them.
        return ("They asked {} things in a row and only got one reply.{}"
                .format(between + 1, tail))

    # Answered a different question entirely.
    if A.GIVES_DURATION.search(r) and not A.ASKS_DURATION.search(q):
        return ("Gave how long the interview is. They asked about {}.{}"
                .format(topic, tail))
    if A.GIVES_TIME.search(r) and not A.ASKS_WHEN.search(q):
        return "Gave a time. They asked about {}.{}".format(topic, tail)
    # A yes-or-no question answered sideways. Megan 2026-10-06 on "Is the
    # position in a store?" -> "This is a residential campaign":
    # "technically this does answer but is a bit dodgy, should ask
    # something back". So name it as vague rather than as unanswered, and
    # say what to do — the same shape as ruling 3, answer then reassure.
    if is_weak(q, r):
        if WALKS.search(q):
            # The sentence already says they got nothing, so the chase
            # count comes without the outcome repeated after it.
            return ("They told us they would walk away if the answer was "
                    "no, and never got a straight one.{}".format(
                        _chased(e, say_outcome=False, again=again)))
        return "Never said yes or no, only a vague answer.{}".format(tail)
    return "Doesn't answer {}.{}".format(topic, tail)


IS_QUESTION = re.compile(r"^\s*(what|when|where|who|why|how|is|are|do|does|"
                         r"did|can|could|will|would|should|has|have|am|any)"
                         r"\b", re.I)


def reasked(entry, bucket, question):
    """How many times they asked THE SAME THING again, from the thread.

    The audit's own asked_again counts any later message that lands in the
    bucket, so Alexius Clark's "I was trying to apply for a store location
    sorry" — a statement, and his last word on it — read as asking again.
    Megan 2026-10-06: "she didn't ask twice." A re-ask has to look like a
    question AND be about the same thing."""
    ctx = (entry or {}).get("context") or []
    seen, n = False, 0
    for m in ctx:
        body = (m.get("body") or "").strip()
        if not seen:
            seen = body == (question or "").strip()
            continue
        if m.get("dir") != "In" or not body:
            continue
        if "?" not in body and not IS_QUESTION.match(body):
            continue
        if bucket and bucket not in A.buckets_of(body):
            continue
        n += 1
    return n


def _chased(entry, say_outcome=True, again=None):
    """' They asked 2 more times, and never got an answer.' or ''.

    `say_outcome` is False when the sentence it attaches to has already
    said they got nothing — Megan 2026-10-06 on "never got a straight
    one. They asked 1 more time, and never got an answer": "same for
    this one"."""
    e = entry or {}
    if again is None:
        try:
            again = int(e.get("asked_again") or 0)
        except (TypeError, ValueError):
            again = 0
    if not again:
        return ""
    later = str(e.get("answered_later")).lower() == "true"
    outcome = "" if (later or not say_outcome) else ", and never got an answer"
    return " They asked {} more time{}{}.".format(
        again, "" if again == 1 else "s", outcome)


def needle_of(detail):
    """The words to mark, out of text_errors' description of the fault.

    It writes "your looking (your -> you're)" and "intrested -> interested";
    only the part before the arrow or the bracket is actually in the
    message."""
    d = (detail or "").strip()
    for sep in (" (", " \u2192 ", " -> "):
        if sep in d:
            d = d.split(sep)[0].strip()
    return d


def mark(body, hit):
    """The message in full, with the part that broke the rule in red.

    Megan 2026-10-06: "we want to see EXACTLY what the person is sending
    and highlight in red what isn't approved". The hit is usually a literal
    slice of the message; when it is the APPLICANT's question instead (the
    hiring-manager rule records the question, not our words), the reply's
    own deflection is marked, and the question is shown above it."""
    body = body or ""
    hit = (hit or "").strip()
    asked = ""
    if ASKED.match(hit):
        asked = ASKED.sub("", hit)
        hit = ""
    span = None
    if hit:
        i = body.lower().find(hit.lower())
        if i >= 0:
            span = (i, i + len(hit))
    if span is None:
        from automations.sms_audit import rebuttals as _R
        m = _R.REFUSES.search(body) or _R.DEFERS.search(body)
        if m:
            span = m.span()
    if span is None:
        out = esc(body)
    else:
        a, b = span
        out = "{}<span class='bad'>{}</span>{}".format(
            esc(body[:a]), esc(body[a:b]), esc(body[b:]))
    if asked:
        # No truncation: Megan 2026-10-06 "we need to see exact".
        out = ("<span class='asked'>They asked: {}</span><br>{}".format(
            esc(asked), out))
    return out


# Light red through to light green. Used per ROW, so each measure is
# shaded against its own best and worst week rather than the whole table.
_SHADES = ("#f7c5c0", "#fbdbd3", "#fdeee4", "#f3f6e6", "#dfeedb", "#c6e3c3")


def shade(values, i, higher_is_better=True):
    """Background for cell `i` of `values`, or '' when there is nothing to
    compare it with."""
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(set(nums)) < 2 or not isinstance(values[i], (int, float)):
        return ""
    lo, hi = min(nums), max(nums)
    pos = (values[i] - lo) / float(hi - lo)
    if not higher_is_better:
        pos = 1.0 - pos
    return _SHADES[min(len(_SHADES) - 1, int(pos * len(_SHADES)))]


def render(person, office, weeks, path):
    d = person["weeks"]
    got = [w for w in weeks if w in d]
    L = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<title>Scorecard — {}</title>".format(esc(person["display"])),
         "<style>{}</style></head><body>".format(CSS),
         "<h1>{}</h1>".format(esc(person["display"])),
         "<p class='date'>Account {} · week ending {}</p>".format(
             esc(office), esc(R.week_label(got[-1]) if got else "—"))]
    add = L.append

    # Megan 2026-10-06: "they should get a 'grade' on this report card".
    mark_ = grade_of(person, weeks)
    if mark_:
        add("<div class='gradebox'><div class='letter {0}'>{0}</div>"
            "<div class='gradenote'>This week's grade</div></div>".format(
                mark_))

    wins = did_well(person, weeks)
    if wins:
        add("<div class='well'><h2>Went well</h2><ul>")
        for w in wins:
            add("<li>{}</li>".format(esc(w)))
        add("</ul></div>")

    fixes = failing(work_on(person, weeks))[:3]
    add("<div class='fix'><h2>Work on this week</h2>")
    if not fixes:
        add("<p>Nothing above the line this week.</p>")
    else:
        add("<ol class='focus'>")
        for f in fixes:
            moved = ""
            if f["before"] and f["before"] != f["now"]:
                moved = " <span class='moved'>{} last week</span>".format(
                    esc(f["before"]))
            add("<li><b>{}: {}</b>{}<br>{}</li>".format(
                esc(f["area"]), esc(f["now"]), moved, esc(f["do"])))
        add("</ol>")
    add("</div>")

    scored = work_on(person, weeks)
    if scored:
        add("<h2>What an A looks like</h2>")
        add("<div class='scroll'><table><tr><th>What</th><th>You</th>"
            "<th>Grade</th><th>For an A</th></tr>")
        for i in sorted(scored, key=lambda x: "ABCDF".index(x["grade"])):
            add("<tr><td>{}</td><td>{}</td><td class='gr {}'>{}</td>"
                "<td>{}</td></tr>".format(
                    esc(i["area"]), esc(i["now"]), i["grade"], i["grade"],
                    esc(i.get("goal") or "\u2014")))
        add("</table></div>")

    add("<h2>Week over week</h2>")
    # (label, the number to shade on, how to show it, is more better)
    rows = [
        ("Interviews Booked", lambda w: w.get("booked") or 0,
         lambda v: "{:,}".format(v), True),
        # Megan 2026-10-06: both channels on every card, under the total.
        ("\u2003Booked From a Text", lambda w: w.get("talked"),
         lambda v: "{:,}".format(v or 0), True),
        ("\u2003Booked From a Call", lambda w: w.get("silent"),
         lambda v: "{:,}".format(v or 0), False),
        ("1st Round Retention",
         lambda w: (_rate(w, "shown", "booked")
                    if (w.get("booked") or 0) >= MIN_MATCHED else None),
         lambda v: "{:.0f}%".format(v) if v is not None else TOO_FEW, True),
        ("Texts Sent", lambda w: w.get("texts") or 0,
         lambda v: "{:,}".format(v), True),
        ("Median Response Time", lambda w: (w.get("replies") or {}).get("median"),
         A_mins, False),
        ("Typing and Grammar Mistakes", lambda w: w.get("typing") or 0,
         lambda v: "{}".format(v), False),
        ("House Rules Broken", lambda w: w.get("house") or 0,
         lambda v: "{}".format(v), False),
        ("Questions Not Answered", lambda w: w.get("dodged") or 0,
         lambda v: "{}".format(v), False),
        ("Booked Over a Day Out",
         lambda w: (_rate(w, "far_out", "matched")
                    if (w.get("matched") or 0) >= MIN_MATCHED else None),
         lambda v: "{:.0f}%".format(v) if v is not None else NO_TEXT, False),
    ]
    add("<div class='scroll'><table><tr><th></th>" + "".join(
        "<th>{}</th>".format(esc(R.week_label(t))) for t in got) + "</tr>")
    all_cells = []
    for label, value_of, show, up_good in rows:
        vals = [value_of(d[t]) for t in got]
        cells = []
        for i, v in enumerate(vals):
            bg = shade(vals, i, up_good)
            text = show(v)
            all_cells.append(text)
            cells.append("<td class='n'{}>{}</td>".format(
                " style=\"background:{}\"".format(bg) if bg else "",
                esc(text)))
        add("<tr><td>{}</td>{}</tr>".format(esc(label), "".join(cells)))
    add("</table></div>")
    if any(TOO_FEW in c for c in all_cells):
        add("<p class='none'>\u201cToo Few\u201d means that week had under "
            "{} bookings \u2014 a percentage off a handful of them says "
            "nothing, so it is left out rather than shown.</p>".format(
                MIN_MATCHED))
    if any(NO_TEXT in c for c in all_cells):
        add("<p class='none'>\u201cBooked by Phone\u201d means how far "
            "ahead could not be read that week: it comes from the "
            "confirmation text, and these bookings were agreed on a call "
            "instead.</p>")

    last = d[got[-1]] if got else {}
    # Megan 2026-10-06: "Did not answer should be it's own dropdown
    # section". Three kinds of fault, three fixes, three sections — mixed
    # together they read as one undifferentiated pile.
    sections = (
        ("House Rules Broken", last.get("examples") or [], ""),
        ("Questions Not Answered", last.get("asked") or [],
         "Did not answer: "),
        ("Weak Answers", last.get("weak") or [], "Weak answer: "),
        ("Typing and Grammar", last.get("typos") or [], ""),
    )
    if any(items for _h, items, _p in sections):
        add("<p class='none'>Open any one to read the texts in full, exactly "
            "as they went out. The part that broke the rule is in red.</p>")
    for heading, items, strip in sections:
        if not items:
            continue
        groups = collections.OrderedDict()
        for issue, hit, body, name, why, ctx in items:
            label = issue[len(strip):] if strip and issue.startswith(strip) \
                else issue
            groups.setdefault(label, []).append((hit, body, name, why, ctx))
        add("<h2>{} \u2014 {}</h2>".format(esc(heading), len(items)))
        if heading == "Weak Answers":
            add("<p class='none'>Technically answered, but nothing said "
                "plainly and nothing asked back \u2014 so the conversation "
                "stops instead of becoming a booking.</p>")
        elif heading == "Questions Not Answered":
            add("<p class='none'>They asked, and it never came back to "
                "them.</p>")
        for label, rows_ in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            add("<details><summary>{} \u2014 {}</summary>".format(
                esc(label), len(rows_)))
            if heading in ("Weak Answers", "Questions Not Answered"):
                add("<p class='fixit'>Instead: {}</p>".format(
                    esc(recovery_for(label))))
            # Megan 2026-10-06: "same applicant ... should show the full
            # convo of her asking twice". One block per person, their
            # thread once, then every fault found in it.
            per = collections.OrderedDict()
            for hit, body, name, why, ctx in rows_:
                cur = per.setdefault(name, {"ctx": [], "why": [],
                                            "quotes": []})
                if len(ctx) > len(cur["ctx"]):
                    cur["ctx"] = ctx
                if why and why not in cur["why"]:
                    cur["why"].append(why)
                cur["quotes"].append((hit, body))
            for name, one in per.items():
                add("<blockquote>")
                if name:
                    add("<span class='who'>{}</span>".format(esc(name)))
                if one["ctx"]:
                    add("<div class='thread'>")
                    for dirn, line in one["ctx"]:
                        if not line:
                            continue
                        add("<div class='{}'><b>{}</b> {}</div>".format(
                            "them" if dirn == "In" else "us",
                            "Them:" if dirn == "In" else "Us:", esc(line)))
                    add("</div>")
                else:
                    for hit, body in one["quotes"]:
                        add("<div>{}</div>".format(mark(body, hit)))
                verdict = worst_of(one["why"])
                if verdict:
                    add("<div class='why'>{}</div>".format(esc(verdict)))
                add("</blockquote>")
            add("</details>")
    add("</body></html>")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def office_summary_html(people, weeks, include_ai=True):
    """The ICD's own breakdown: one row per recruiter, worst first.

    Megan 2026-10-06: "the ICD gets an email breakdown weekly and then each
    recruiter on their market has an attachment to it that is their
    scorecard". So this is the body, and the scorecards ride along as
    files — the ICD reads one table and forwards one attachment."""
    rows = []
    for _k, p in people.items():
        got = [w for w in weeks if w in p["weeks"]]
        if not got:
            continue
        if is_ai(p["display"]) and not include_ai:
            continue
        now = p["weeks"][got[-1]]
        if (now.get("texts") or 0) < MIN_TEXTS:
            continue
        fixes = failing(work_on(p, weeks))
        rows.append((p["display"], now, fixes))
    rows.sort(key=lambda r: (-len(r[2]),
                             -(r[2][0]["grade"] == "F" if r[2] else 0)))

    out = ["<table role='presentation' cellpadding='6' cellspacing='0' "
           "style=\"border-collapse:collapse;font-family:Georgia,serif;"
           "font-size:14px\">",
           "<tr>" + "".join(
               "<th align='left' style=\"border-bottom:2px solid #111\">"
               "{}</th>".format(h)
               for h in ("Recruiter", "Booked", "Showed", "Texts",
                         "Median Response Time", "To work on")) + "</tr>"]
    for name, now, fixes in rows:
        show = _rate(now, "shown", "booked")
        top = fixes[0]["area"] if fixes else "nothing"
        out.append(
            "<tr>"
            "<td style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{:,}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td style=\"border-bottom:1px solid #ddd\">{}</td></tr>".format(
                esc(name), now.get("booked") or 0,
                "{:.0f}%".format(show) if show is not None else "—",
                now.get("texts") or 0,
                A_mins((now.get("replies") or {}).get("median")),
                esc(top)))
    out.append("</table>")
    return "\n".join(out), rows


def email_icd(office, people, weeks, paths, to, dry_run=True, logfn=print):
    """One email to the ICD: the table in the body, scorecards attached."""
    from automations.shared import report_email
    got = [w for w in weeks if any(w in p["weeks"] for p in people.values())]
    week = R.week_label(got[-1]) if got else "—"
    body, rows = office_summary_html(people, weeks)
    intro = ("<p>Here is the recruiting week for account {}, ending {}. "
             "Each person's own scorecard is attached — it shows the same "
             "numbers week over week and what to work on.</p>{}".format(
                 esc(office), esc(week), body))
    files = [(name, paths[name]) for name, _n, _f in rows if name in paths]
    return report_email.send_boards(
        subject="Recruiting scorecards — account {} — week ending {}".format(
            office, week),
        to=to, title="RECRUITING SCORECARDS — ACCOUNT {}".format(office),
        blocks=[], intro_html=intro, files=files,
        dry_run=dry_run, logfn=logfn)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280")
    ap.add_argument("--email", action="store_true",
                    help="build the ICD email; writes a preview and sends "
                         "NOTHING unless --send is given too")
    ap.add_argument("--send", action="store_true",
                    help="actually send it. Never set this without asking.")
    ap.add_argument("--to", default="", help="comma list, else the office's "
                                             "email from the config tab")
    ap.add_argument("--weeks", default="", help="comma list, default last 6")
    ap.add_argument("--no-ai", action="store_true",
                    help="leave the AI out; by default it gets a card like "
                         "anyone else, because it books more than anyone")
    a = ap.parse_args(argv)

    weeks = [w.strip() for w in a.weeks.split(",") if w.strip()] or R.WEEKS
    people = collect(a.office, weeks)
    if not people:
        print("[scorecard] nothing pulled for {} in {}".format(
            a.office, ", ".join(weeks)))
        return 1
    OUTPUT.mkdir(exist_ok=True)
    made = 0
    paths = {}
    for key, person in sorted(people.items(),
                              key=lambda kv: -sum(
                                  w.get("texts", 0)
                                  for w in kv[1]["weeks"].values())):
        if is_ai(person["display"]) and a.no_ai:
            continue
        total = sum(w.get("texts", 0) for w in person["weeks"].values())
        if total < MIN_TEXTS:
            continue
        path = OUTPUT / "scorecard-{}-{}.html".format(
            a.office, re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-"))
        render(person, a.office, weeks, path)
        paths[person["display"]] = path
        fixes = work_on(person, weeks)
        print("   {:<24} {:>6,} texts · {} to work on -> {}".format(
            person["display"][:24], total, len(fixes), path.name), flush=True)
        made += 1
    print("[scorecard] {} scorecard(s) for {}".format(made, a.office))

    if not a.email:
        return 0
    to = [x.strip() for x in a.to.split(",") if x.strip()]
    if not to:
        cfg = [o for o in (O.load()[0] or []) if o.get("office") == a.office]
        to = [x.strip() for x in ((cfg[0].get("email") if cfg else "") or "")
              .replace(";", ",").split(",") if x.strip()]
    if not to:
        print("[scorecard] no ICD email on file for {} — add one to the "
              "office tab or pass --to. Nothing sent.".format(a.office))
        return 1
    # Standing rule: ask before ANY send. --send is the only way through,
    # and without it this writes the preview and sends nothing.
    res = email_icd(a.office, people, weeks, paths, to, dry_run=not a.send)
    print("[scorecard] {} -> {}".format(
        "SENT" if a.send and res.get("ok") else "preview only", ", ".join(to)))
    if res.get("preview"):
        print("[scorecard] preview: {}".format(res["preview"]))
    return 0 if res.get("ok") or not a.send else 1


if __name__ == "__main__":
    sys.exit(main())
