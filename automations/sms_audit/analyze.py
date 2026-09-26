"""SMS audit — read the applicant text threads a sms_thread_dump run parked in
the control sheet and answer the six questions Raf asked on 2026-09-26:

  1. when is the AI doing the booking (vs a human recruiter)
  2. how quick are the human recruiters responding
  3. what do applicants ask us
  4. what are our regular responses
  5. whose texts went unanswered
  6. anything else off

Carlos asked for his office too, side by side — so every number here is
computed per office and the report ends with a comparison table.

  python -m automations.sms_audit.analyze                       # every office with a dump
  python -m automations.sms_audit.analyze --office 11280,11580  # just these two
  python -m automations.sms_audit.analyze --out output/x.md

READ-ONLY: reads output/sms_thread_dump_<office>.json (written by
`lucy rerun sms_thread_dump --office <ids>`), falling back to the control-sheet
tab "SMS Dump <office>" when the local cache is missing, and writes one
markdown file to output/. Touches no Sheet, no Slack, no AppStream.

WHAT COUNTS AS THE AI. Two independent signals agree in the dump, so the
classifier uses the pair and reports any row where they disagree:
  * the calendar's "booked_by" cell reads "A. Messaging" for an AI booking and
    a recruiter's name ("E. Gonzalez") for a human one;
  * AppStream fires the "Directions AI" template after an AI booking and plain
    "Directions" after a human one.
The PERSONA in the message body ("this is Elena…") is NOT a signal — the same
persona name fronts both, which is worth knowing before anyone reads a name in
a thread and assumes a person typed it.
"""
from __future__ import annotations  # Lucy/mini run Python 3.9 — keep lazy

import argparse
import collections
import datetime as dt
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "SMS Dump"

AI_BOOKER = "A. Messaging"       # the automation's name in the calendar's Booked By
AI_TEMPLATE = "Directions AI"    # fires only after an AI booking
HUMAN_TEMPLATE = "Directions"    # fires only after a human one

# An applicant reply that closes a loop rather than opening one. A thread that
# ends on one of these is finished, not ignored — counting them as "unanswered"
# would bury the handful that really were dropped.
CLOSER = re.compile(
    r"^\s*(c|k|ok(ay)?|yes+|yep|yeah|yup|y|sure|sounds good|perfect|great|"
    r"(thank you|thanks|ty)( so much| very much| again)?|got it|will do|"
    r"confirmed?|see you( then| there| tomorrow| soon)?|i'?m confirmed|"
    r"[\U0001F300-\U0001FAFF☀-➿])"
    r"[\s!.,\U0001F300-\U0001FAFF☀-➿]*$", re.I)

# Buckets for "what do applicants ask us". Ordered — first match wins, so the
# specific patterns sit above the general ones.
QUESTION_BUCKETS = [
    ("Is this remote / where is the office?",
     r"\b(remote|virtual|in[- ]person|onsite|on[- ]site|location|where\b.*\b(office|located|interview)|address|directions?|how far)"),
    ("What is the pay?",
     r"\b(pay|salary|hourly|commission|compensation|how much|wage|\$\d)"),
    ("What is the job / what do you do?",
     r"\b(what (is|are|s) the (job|role|position)|what (would|do) i (be )?do|job descri|"
     r"what company|what kind of (work|job)|door to door|sales\?|tell me more|"
     r"more (detail|info)|what.{0,12}job about|give me detail)"),
    ("How do I join the Zoom / link trouble?",
     r"\b(zoom|link|meeting id|password|can'?t (get|log) ?in|join|waiting room|not working)"),
    ("Can we reschedule / a different time?",
     r"\b(reschedul|another (time|day)|different (time|day)|move (it|my)|push (it|my)|"
     r"later (time|today)|earlier|can we do|availab|what time|when would|"
     r"any(thing| time) (next|later|else)|(before|after) \d|do (monday|tuesday|wednesday|"
     r"thursday|friday|saturday)|works? for you)"),
    ("I can't make it / I'm running late",
     r"\b(can'?t make|running late|be late|won'?t be able|something came up|miss (my|the))"),
    ("What should I wear / bring?",
     r"\b(wear|dress|attire|bring|resume|business (casual|professional))"),
    ("How long is the interview / what's next?",
     r"\b(how long|next step|hear back|when will|what happens|second interview|follow up)"),
    ("Is this a real job / who are you?",
     r"\b(scam|legit|real (job|company)|who is this|who are you|spam|how did you get)"),
    ("Am I still being considered?",
     r"\b(still (hiring|available|considering|interested in me)|did i get|any update|status of my)"),
]


# ---------------------------------------------------------------- loading ----

def _ts(stamp, year):
    """'09/02 8:15 AM' + a year -> datetime. AppStream drops the year, so the
    caller passes the one off the booking row; a thread that crosses New Year
    would need the roll handled, which no audit window has ever spanned."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s*([AaPp])", stamp or "")
    if not m:
        return None
    mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    h = h % 12 + (12 if m.group(5).lower() == "p" else 0)
    try:
        return dt.datetime(year, mo, d, h, mi)
    except ValueError:
        return None


def _year_of(rec):
    m = re.match(r"\d{2}-\d{2}-(\d{4})", rec.get("date") or "")
    return int(m.group(1)) if m else dt.date.today().year


def load_office(office):
    """Records for one office: the local dump if it's there, else the sheet tab.
    Same shape either way — a list of booking dicts each holding a `thread`."""
    local = OUTPUT_DIR / "sms_thread_dump_{}.json".format(office)
    if local.exists():
        recs = json.loads(local.read_text())
        for r in recs:
            r.setdefault("office", office)
        return recs, "output/{}".format(local.name)

    from automations.recruiting_report import fill as _fill
    tab = "{} {}".format(TAB_PREFIX, office)
    ws = _fill._client().open_by_key(CONTROL_SHEET_ID).worksheet(tab)
    vals = ws.get_all_values()
    if len(vals) < 3:
        return [], "sheet tab '{}' (empty)".format(tab)
    hdr, recs, by_key = vals[1], [], {}
    for row in vals[2:]:
        d = dict(zip(hdr, row))
        key = (d.get("date"), d.get("time"), d.get("name"), d.get("phone"))
        blob = d.get("thread_json") or ""
        if key in by_key:                      # part=2,3… continuation rows
            by_key[key]["_blob"] += blob
            continue
        d["_blob"] = blob
        d["office"] = office
        by_key[key] = d
        recs.append(d)
    for d in recs:
        try:
            d["thread"] = json.loads(d.pop("_blob") or "[]")
        except ValueError:
            d["thread"] = []
        d.pop("thread_json", None)
    return recs, "sheet tab '{}'".format(tab)


def messages(rec):
    """[(when, 'In'|'Out', template_name, body)] in order, unparseable dropped."""
    year = _year_of(rec)
    out = []
    for m in rec.get("thread") or []:
        if len(m) < 4:
            continue
        when = _ts(m[3], year)
        if when:
            out.append((when, (m[0] or "").strip(), (m[1] or "").strip(), m[2] or ""))
    out.sort(key=lambda x: x[0])
    return out


# --------------------------------------------------------------- metrics ----

def booking_mix(recs):
    """Who booked the interview — the automation or a person. Reports the two
    signals separately so a disagreement shows up instead of being averaged."""
    by_booker = collections.Counter(r.get("booked_by", "") or "(blank)" for r in recs)
    ai = human = disagree = 0
    for r in recs:
        tmpl = {m[2] for m in messages(r)}
        said_ai = r.get("booked_by") == AI_BOOKER
        fired_ai = AI_TEMPLATE in tmpl and HUMAN_TEMPLATE not in tmpl
        fired_hu = HUMAN_TEMPLATE in tmpl and AI_TEMPLATE not in tmpl
        if said_ai and fired_ai:
            ai += 1
        elif (not said_ai) and fired_hu:
            human += 1
        elif said_ai:
            ai += 1
            disagree += 1
        else:
            human += 1
            disagree += 1
    return {"by_booker": by_booker, "ai": ai, "human": human,
            "disagree": disagree, "total": len(recs)}


def outcome_by_booker(recs):
    """Show rate per booking channel — an AI booking is only worth as much as
    the applicant who turns up for it."""
    out = collections.defaultdict(collections.Counter)
    for r in recs:
        who = "AI" if r.get("booked_by") == AI_BOOKER else "human"
        out[who][r.get("status", "") or "(blank)"] += 1
    return out


def reply_speed(recs):
    """How long an applicant waits for the next outbound message after they
    text in. Split by what answered them:
      * free-typed  — somebody (or the conversational AI) wrote a reply
      * template    — the scheduled/automated text that happened to come next
    Gaps over 24h are dropped: those are a NEXT-day scheduled blast, not a
    reply, and they'd drag every average into nonsense."""
    buckets = {"typed": [], "template": [], "typed_ai_thread": [],
               "typed_human_thread": []}
    first_reply = []
    for r in recs:
        th = messages(r)
        # WHICH free-typed replies were a PERSON is not in this source: the
        # chat history has no sender. The closest honest split is by who ended
        # up booking the interview — an "A. Messaging" thread was driven by the
        # automation throughout, a recruiter-booked thread had a person in it.
        # It is a proxy, labelled as one. The real column ("Sent By") lives on
        # the SMS List Report (p=336) — see the module README.
        lane = "typed_ai_thread" if r.get("booked_by") == AI_BOOKER else "typed_human_thread"
        seen_first = False
        for i, (when, dirn, _tmpl, _body) in enumerate(th):
            if dirn != "In":
                continue
            nxt = next((x for x in th[i + 1:] if x[1] == "Out"), None)
            if not nxt:
                continue
            gap = (nxt[0] - when).total_seconds() / 60.0
            if gap < 0 or gap > 24 * 60:
                continue
            if nxt[2]:
                buckets["template"].append(gap)
            else:
                buckets["typed"].append(gap)
                buckets[lane].append(gap)
            if not seen_first:
                first_reply.append(gap)
                seen_first = True
    return buckets, first_reply


def _stat(vals):
    if not vals:
        return None
    s = sorted(vals)
    return {
        "n": len(s),
        "median": statistics.median(s),
        "p90": s[min(len(s) - 1, int(0.9 * len(s)))],
        "within_5": 100.0 * sum(1 for v in s if v <= 5) / len(s),
        "within_60": 100.0 * sum(1 for v in s if v <= 60) / len(s),
        "over_4h": 100.0 * sum(1 for v in s if v > 240) / len(s),
    }


def questions(recs):
    """What applicants actually ask. An inbound message counts as a question if
    it carries a '?' or opens with a question word; everything else is a reply
    to us, not a question of theirs."""
    opener = re.compile(r"^\s*(what|when|where|who|why|how|is|are|do|does|did|can|could|"
                        r"will|would|should|may|am i|i have a question)\b", re.I)
    asked, unbucketed = collections.Counter(), []
    total = 0
    for r in recs:
        for _when, dirn, _t, body in messages(r):
            if dirn != "In":
                continue
            if "?" not in body and not opener.match(body):
                continue
            total += 1
            for label, pat in QUESTION_BUCKETS:
                if re.search(pat, body, re.I):
                    asked[label] += 1
                    break
            else:
                unbucketed.append(body.strip().replace("\n", " ")[:120])
    return asked, total, unbucketed


def regular_responses(recs):
    """Our side of it: which templates fire how often, and the free-typed lines
    repeated so often they are templates in everything but name."""
    tmpl = collections.Counter()
    typed = collections.Counter()
    for r in recs:
        for _when, dirn, t, body in messages(r):
            if dirn != "Out":
                continue
            if t:
                tmpl[t] += 1
            else:
                key = re.sub(r"\d+", "#", body.strip())
                key = re.sub(r"\s+", " ", key)
                typed[key[:160]] += 1
    return tmpl, typed


def unanswered(recs):
    """Applicants left on read. A thread qualifies when the LAST message is
    theirs and it is not a plain 'ok/thanks/C' — i.e. they said something that
    wanted an answer and never got one."""
    out = []
    for r in recs:
        th = messages(r)
        if not th or th[-1][1] != "In":
            continue
        body = th[-1][3].strip()
        if CLOSER.match(body):
            continue
        out.append({"name": r.get("name", ""), "phone": r.get("phone", ""),
                    "status": r.get("status", ""), "when": th[-1][0],
                    "booked_by": r.get("booked_by", ""),
                    "said": body.replace("\n", " ")[:160]})
    out.sort(key=lambda d: d["when"])
    return out


def anomalies(recs):
    """Everything that looks wrong on its own terms, each with the evidence.

    The carrier rule is AppStream's own (SMS Templates page, deliverability
    checklist item 6): more than 3 messages to an applicant with no reply is
    how a sending number gets flagged as spam."""
    found = collections.defaultdict(list)
    for r in recs:
        th = messages(r)
        who = r.get("name", "")

        # a link whose host is spelled with a look-alike letter never resolves
        for _when, dirn, _t, body in th:
            if dirn != "Out":
                continue
            for url in re.findall(r"https?://\S+", body):
                host = url.split("/")[2] if "://" in url else ""
                bad = [c for c in host if ord(c) > 127]
                if bad:
                    names = ", ".join(unicodedata.name(c, "?") for c in bad)
                    found["Dead link — the web address is spelled with a look-alike letter"].append(
                        "{}: {} ({})".format(who, url[:70], names))

        # a merge field that never filled in, vs one that filled but kept its
        # braces — the first reads as a bug, the second as sloppiness, and they
        # get fixed in different places, so they are counted apart
        for _when, dirn, _t, body in th:
            if dirn != "Out":
                continue
            if re.search(r"applicant(First|Last)Name|adPostingTitle|timeOnly|\bnull\b", body):
                found["A merge field never filled in — the applicant got the raw tag"].append(
                    "{}: {}".format(who, body.strip()[:90]))
            elif "{{" in body or "}}" in body:
                found["Merge braces {{ }} printed around the text"].append(
                    "{}: {}".format(who, body.strip()[:110]))

        # they asked to stop and we kept texting
        for i, (_when, dirn, _t, body) in enumerate(th):
            if dirn != "In":
                continue
            if re.search(r"\b(stop|unsubscribe|remove me|don'?t (text|contact)|"
                         r"no longer interested|not interested|cancel)\b", body, re.I):
                after = [x for x in th[i + 1:] if x[1] == "Out"]
                if after:
                    found["Kept texting after they asked us to stop / said no"].append(
                        "{}: said “{}” then got {} more message(s)".format(
                            who, body.strip()[:60], len(after)))
                break

        # carrier rule: >3 unanswered outbound in a row. A text and its
        # follow-up link go out in the same second and land as one message to
        # the applicant, so anything inside 2 minutes counts once — otherwise
        # every ordinary confirmation trips the rule and the real offenders
        # are lost in the noise.
        run, worst, last = 0, 0, None
        for when, dirn, _t, _body in th:
            if dirn == "Out":
                if last is None or (when - last).total_seconds() > 120:
                    run += 1
                last = when
            else:
                run, last = 0, None
            worst = max(worst, run)
        if worst > 3:
            found["Over the carrier limit — 4+ separate texts with no reply between"].append(
                "{}: {} in a row".format(who, worst))

        # sent inside the hours the TCPA calls quiet (before 8am / after 9pm
        # local). Keyed by send time + template, not by name: these come from
        # ONE scheduled blast, and 200 names hide that where one line shows it.
        for when, dirn, t, _body in th:
            if dirn == "Out" and (when.hour < 8 or when.hour >= 21):
                found["Texted outside 8am–9pm (TCPA quiet hours)"].append(
                    "{} · {}".format(when.strftime("%I:%M %p").lstrip("0"), t or "free-typed"))

        # the same message twice inside a minute
        seen = {}
        for when, dirn, _t, body in th:
            if dirn != "Out":
                continue
            key = body.strip()[:80]
            if key in seen and (when - seen[key]).total_seconds() < 60:
                found["Same text sent twice within a minute"].append(
                    "{}: {}".format(who, key[:70]))
            seen[key] = when
    return found


def audit(recs, office):
    mix = booking_mix(recs)
    speed, first = reply_speed(recs)
    asked, q_total, q_other = questions(recs)
    tmpl, typed = regular_responses(recs)
    threads_with_reply = sum(1 for r in recs
                             if any(m[1] == "In" for m in messages(r)))
    dates = sorted({r.get("date", "") for r in recs if r.get("date")})
    return {
        "office": office,
        "dates": dates,
        "threads": len(recs),
        "messages": sum(len(messages(r)) for r in recs),
        "inbound": sum(1 for r in recs for m in messages(r) if m[1] == "In"),
        "threads_with_reply": threads_with_reply,
        "mix": mix,
        "outcomes": outcome_by_booker(recs),
        "speed_typed": _stat(speed["typed"]),
        "speed_template": _stat(speed["template"]),
        "speed_typed_ai": _stat(speed["typed_ai_thread"]),
        "speed_typed_human": _stat(speed["typed_human_thread"]),
        "speed_first": _stat(first),
        "questions": asked, "questions_total": q_total, "questions_other": q_other,
        "templates": tmpl, "typed": typed,
        "unanswered": unanswered(recs),
        "anomalies": anomalies(recs),
    }


# ---------------------------------------------------------------- report ----

def _pct(n, d):
    return "0%" if not d else "{:.0f}%".format(100.0 * n / d)


def _speed_line(s):
    if not s:
        return "no measurable replies"
    return ("median **{:.0f} min**, 9 out of 10 inside {:.0f} min · "
            "{:.0f}% answered within 5 min · {:.0f}% within the hour"
            .format(s["median"], s["p90"], s["within_5"], s["within_60"]))


def render(reports, names):
    L = []
    add = L.append
    today = dt.date.today()
    add("# Applicant text audit")
    add("")
    add("Every first-interview text thread for the window below, read end to end. "
        "Raf asked for six things on 2026-09-26; each is a heading. "
        "Carlos asked for his office side by side — that is the last section.")
    add("")
    add("*Run {:%b %-d, %Y}. Source: ApplicantStream → Calendar → Weekly Calendar (p=105) "
        "→ each booking's **Applicant History → SMS Sent → Chat History**, scraped by "
        "`sms_thread_dump`. Read-only.*".format(today))
    add("")

    for rep in reports:
        who = names.get(rep["office"], rep["office"])
        add("---")
        add("")
        add("## {} — office {}".format(who, rep["office"]))
        add("")
        win = "{} → {}".format(rep["dates"][0], rep["dates"][-1]) if rep["dates"] else "n/a"
        add("**{} booked interviews** over {}, **{:,} text messages** "
            "({:,} from applicants). {} of the {} applicants texted back at all."
            .format(rep["threads"], win, rep["messages"], rep["inbound"],
                    rep["threads_with_reply"], rep["threads"]))
        add("")

        m = rep["mix"]
        add("### 1. When the AI is doing the booking")
        add("")
        add("- **AI booked {} of {} ({})**; a recruiter booked {} ({}).".format(
            m["ai"], m["total"], _pct(m["ai"], m["total"]),
            m["human"], _pct(m["human"], m["total"])))
        add("- Who is credited on the calendar:")
        for k, v in m["by_booker"].most_common():
            tag = " ← the automation" if k == AI_BOOKER else ""
            add("  - {} — {}{}".format(k, v, tag))
        if m["disagree"]:
            add("- ⚠️ {} thread(s) where the two signals disagree (the calendar says one "
                "thing, the template that fired says the other) — worth a look.".format(
                    m["disagree"]))
        add("- Show rate by who booked it:")
        for chan in ("AI", "human"):
            c = rep["outcomes"].get(chan)
            if not c:
                continue
            tot = sum(c.values())
            shown = sum(v for k, v in c.items() if "No Show" not in k)
            add("  - **{}**: {} booked, {} showed ({})".format(
                chan, tot, shown, _pct(shown, tot)))
        add("")
        add("*Two cautions on that show rate: it is one window, and the two channels "
            "may not get the same applicants — a recruiter tends to pick up the ones "
            "the automation could not close. Treat the gap as a question worth asking, "
            "not a finding. And the name inside the message (“this is Elena…”) is not "
            "a tell — the same persona fronts AI and human threads alike.*")
        add("")

        add("### 2. How quick the replies are")
        add("")
        add("- **Someone typed a reply**: {}".format(_speed_line(rep["speed_typed"])))
        add("  - in threads the **automation** booked: {}".format(
            _speed_line(rep["speed_typed_ai"])))
        add("  - in threads a **recruiter** booked: {}".format(
            _speed_line(rep["speed_typed_human"])))
        add("- **An automated template came next**: {}".format(_speed_line(rep["speed_template"])))
        if rep["speed_first"]:
            add("- **First time an applicant texts in**, they wait {}".format(
                _speed_line(rep["speed_first"])))
        if rep["speed_typed"] and rep["speed_typed"]["over_4h"]:
            add("- {:.0f}% of typed replies took more than 4 hours.".format(
                rep["speed_typed"]["over_4h"]))
        add("")
        add("*This source records no sender on a typed message, so those two lines "
            "split by who booked the interview, not by who typed. The true per-message "
            "sender is on the SMS List Report (p=336) — the next pull to build.*")
        add("")

        add("### 3. What applicants ask")
        add("")
        add("{} questions in the window. Most common:".format(rep["questions_total"]))
        add("")
        for label, n in rep["questions"].most_common(10):
            add("- **{}** — {} ({})".format(label, n, _pct(n, rep["questions_total"])))
        if rep["questions_other"]:
            add("")
            add("Didn't fit a bucket ({} of them), a sample:".format(len(rep["questions_other"])))
            for s in rep["questions_other"][:8]:
                add("  - “{}”".format(s))
        add("")

        add("### 4. Our regular responses")
        add("")
        add("Templates that fired:")
        add("")
        for t, n in rep["templates"].most_common(12):
            add("- {} — {}".format(t, n))
        add("")
        repeated = [(k, v) for k, v in rep["typed"].most_common(6) if v > 3]
        if repeated:
            add("Free-typed lines sent so often they are templates in practice:")
            add("")
            for body, n in repeated:
                add("- ×{} — “{}”".format(n, body[:130]))
            add("")

        ua = rep["unanswered"]
        add("### 5. Texts nobody answered")
        add("")
        add("**{} of {} threads ({})** end on the applicant saying something that wanted "
            "an answer (plain “ok/thanks/C” doesn't count).".format(
                len(ua), rep["threads"], _pct(len(ua), rep["threads"])))
        add("")
        for u in ua[:15]:
            add("- **{}** ({:%m/%d %I:%M %p}, {}) — “{}”".format(
                u["name"], u["when"], u["status"] or "no status", u["said"]))
        if len(ua) > 15:
            add("- …and {} more.".format(len(ua) - 15))
        add("")

        add("### 6. What else looks off")
        add("")
        an = rep["anomalies"]
        if not an:
            add("Nothing flagged.")
        for title in sorted(an, key=lambda k: -len(an[k])):
            hits = an[title]
            add("- **{}** — {} time(s)".format(title, len(hits)))
            # repeated hits are one cause, not N findings — collapse them
            grouped = collections.Counter(hits)
            for h, n in grouped.most_common(4):
                add("  - {}{}".format(h, " ×{}".format(n) if n > 1 else ""))
            if len(grouped) > 4:
                add("  - …and {} more kind(s).".format(len(grouped) - 4))
        add("")

    if len(reports) > 1:
        add("---")
        add("")
        add("## Side by side")
        add("")
        head = ["", ] + [names.get(r["office"], r["office"]) for r in reports]
        add("| " + " | ".join(head) + " |")
        add("|" + "---|" * len(head))

        def row(label, fn):
            add("| " + " | ".join([label] + [fn(r) for r in reports]) + " |")

        row("Interviews booked", lambda r: "{}".format(r["threads"]))
        row("Booked by the AI", lambda r: "{} ({})".format(
            r["mix"]["ai"], _pct(r["mix"]["ai"], r["mix"]["total"])))
        row("Booked by a recruiter", lambda r: "{} ({})".format(
            r["mix"]["human"], _pct(r["mix"]["human"], r["mix"]["total"])))
        row("Applicants who texted back", lambda r: _pct(r["threads_with_reply"], r["threads"]))
        row("Typed reply, median wait", lambda r: (
            "{:.0f} min".format(r["speed_typed"]["median"]) if r["speed_typed"] else "—"))
        row("Typed replies inside 5 min", lambda r: (
            "{:.0f}%".format(r["speed_typed"]["within_5"]) if r["speed_typed"] else "—"))
        row("Left unanswered", lambda r: "{} ({})".format(
            len(r["unanswered"]), _pct(len(r["unanswered"]), r["threads"])))
        row("Messages per booking", lambda r: "{:.1f}".format(
            r["messages"] / float(r["threads"] or 1)))
        row("Things flagged in §6", lambda r: "{}".format(
            sum(len(v) for v in r["anomalies"].values())))
        add("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="",
                    help="comma list; default = every office with a dump in output/")
    ap.add_argument("--out", default="",
                    help="markdown path; default output/sms-audit-<date>.md")
    a = ap.parse_args(argv)

    if a.office:
        offices = [o.strip() for o in a.office.split(",") if o.strip()]
    else:
        offices = sorted(p.stem.replace("sms_thread_dump_", "")
                         for p in OUTPUT_DIR.glob("sms_thread_dump_*.json"))
    if not offices:
        print("[sms_audit] no dumps found — run `lucy rerun sms_thread_dump "
              "--office <ids>` first", flush=True)
        return 1

    try:
        from automations.applicant_tracker.config import OFFICE_NAMES as names
    except Exception:
        names = {}

    reports = []
    for o in offices:
        recs, src = load_office(o)
        if not recs:
            print("[sms_audit] {}: nothing to read ({})".format(o, src), flush=True)
            continue
        print("[sms_audit] {}: {} threads from {}".format(o, len(recs), src), flush=True)
        reports.append(audit(recs, o))
    if not reports:
        return 1

    out = Path(a.out) if a.out else (
        OUTPUT_DIR / "sms-audit-{:%Y-%m-%d}.md".format(dt.date.today()))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(reports, names), encoding="utf-8")
    print("[sms_audit] wrote {}".format(out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
