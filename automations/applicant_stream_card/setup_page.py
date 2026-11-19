# -*- coding: utf-8 -*-
"""Page 2 of the grade card: what ApplicantStream is actually set to.

Megan 2026-11-13, after Aptel changed 25065's buffers from 180/300 to 45/30
without the card showing it: "we need to add a 2nd page to this audit about
the settings in actual app stream - what their SMS / emails say and then the
AI settings overall including the buffer times".

Page 1 grades. This page only SHOWS, as last pulled: AI Settings, the three
AI Preferences numbers next to our standard, every AI reply with its
escalation type, and every SMS template (on/off and its full words). So
anyone can see a change the moment a pull picks it up.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import html
import re

from automations.applicant_stream_card import fixes as F

# AI Settings fields in the order the page shows them, with plain labels.
INFO = [
    ("ai_company_name", "Company name the AI uses"),
    ("office_name", "Office name"),
    ("ai_assistant_name", "AI's name"),
    ("office_address1", "Address"),
    ("office_city", "City"),
    ("office_state", "State"),
    ("office_zip", "Zip"),
    ("office_phone", "Phone"),
    ("interview_type", "1st round interview type"),
    ("interview_length", "Interview length"),
    ("escalation_contact_name", "Escalation contact (who your AI says "
     "it'll pass questions to \u2014 usually your recruiter)"),
    ("escalation_contact_title", "Escalation contact title"),
]

# Which office-info row each AI Settings flag is about
# (sms_audit/ai_settings.WHY kinds).
ROW_OF = {
    "WRONG TITLE": "escalation_contact_title",
    "SAME NAME": "escalation_contact_name",
    "AI IS A REAL PERSON": "ai_assistant_name",
    "NAME MISMATCH": "ai_assistant_name",
    "ONE INTERVIEW TYPE": "interview_type",
    "ADDRESS": "office_address1",
}

# What each AI Preferences number does, in plain words
# (resources/appstream-ai-preferences-standard.md).
PREFS = [
    ("offered_buffer", "Earliest time the AI suggests",
     "When the AI texts the applicant a few times to choose from, none of "
     "them are sooner than this."),
    ("accepted_buffer", "Earliest time an applicant can ask for",
     "When the applicant names their own time instead, the AI only books it "
     "if it's at least this far away."),
    ("ghosting_threshold", "Ghosting flag",
     "Minutes of silence before a conversation is flagged as ghosting. "
     "Display only."),
    # New on AppStream's page 11/16. No standard yet, so shown, not graded.
    ("interviewer_prep_buffer", "Interviewer prep time",
     "Minutes kept free before each interview so whoever runs it can get "
     "ready. Display only."),
]
# Rows shown only when the office's page still has the field: AppStream
# folded the two timeslot buffers into one on 11/16, and "accepted" went.
PREFS_IF_PRESENT = {"accepted_buffer", "interviewer_prep_buffer"}

# Raf's ARS doc, Auditing Process -> Templates: the texts and emails that
# should be live at every office (resources/recruiting-context/
# ars-processes-2026.md). Names as ApplicantStream spells the steps.
# The call cycle we recommend (Megan 2026-11-15: "we should just say we
# recommend that your call cycle be this ... let's follow back up on that
# one"). Empty until Megan gives it; then it shows at the top of Templates.
RECOMMENDED_CYCLE = []

RECOMMENDED_SMS = [
    "Await Call AI", "2nd Left Message - Call List", "No Answer - Call List",
    "On Hold", "Directions", "Directions AI", "2nd Interview Invite",
    "No Show - Interview", "No Show - 2nd Interview",
    "1st Interview - Reschedule", "2nd Interview - Reschedule",
    "Follow Up from Calendar - Left Message",
    "Follow Up from Calendar - No Answer",
    "Follow Up from Calendar - Late Join", "Showed Up - Interview",
    "FDOT/BOB", "First Interview Confirmation",
]
RECOMMENDED_EMAIL = [
    "1st Left Message - Call List", "2nd Left Message - Call List",
    "3rd Left Message - Call List", "Directions", "2nd Interview Invite",
    "2nd Interview - Reschedule", "Second Interview Confirmation", "FDOT/BOB",
]
WHY_ON = ("It's on Raf's list of {} every office should have on. While it's "
          "off, applicants at this step get nothing from us.")
# AI Settings fields the AI drops into its texts — a blank leaves a hole.
MUST_FILL = {"ai_company_name", "office_name", "ai_assistant_name",
             "office_address1", "office_city", "office_state", "office_zip",
             "office_phone", "interview_type"}
WHY_DONT = ("Only Don't Escalate sends our approved words. On any other "
            "type the AI writes its own answer.")


# Who fixes each flag (Megan 2026-11-13: "it can say you or communicate to
# the Aptel team"). Offices can edit their own templates; the AI side is
# set up by Aptel.
YOU = APTEL_FIX = F.WHO_FIXES


# AppStream adds this note to a row whose type does not send its message.
NOT_SENT = re.compile(r"\s*Message not sent as written:.*$", re.S)


def _flag(title, found="", why="", owner="", options=None, link=None):
    return {"title": title, "found": found, "why": why, "owner": owner,
            "options": options or [], "link": link}


def options_html(versions, link=None):
    """'We'd recommend one of these replies' plus ONE link, so a page of 30
    recommendations stays short. With a replies-page link, that page holds
    the 5 versions and their Copy buttons; otherwise the signed-off reply
    opens here with its own Copy button."""
    if link:
        return ("<p class='rec'>We'd recommend one of our approved replies: "
                "<a class='opts-link' href='{}' target='_blank' "
                "rel='noopener'>See the 5 replies \u2197</a></p>"
                "<p class='s'>Copy any one. Anything in red braces there "
                "isn't in AppStream yet, so don't paste one of those."
                "</p>").format(_e(link))
    if not versions:
        return ""
    return ("<p class='rec'>We'd recommend this reply:</p>"
            "<details class='opts'><summary>See the reply</summary>"
            "<div class='body'>{}<p class='s'>Words like officeName fill in "
            "by themselves. Paste as written.</p></div></details>").format(
                "".join("<div class='opt'><span>{}</span><button type='button' "
                        "onclick='cp(this)'>Copy</button></div>".format(_e(v))
                        for v in versions))


# Copy button. The fallback selects the text so a viewer that blocks the
# clipboard still lets you press Cmd/Ctrl+C.
COPY_JS = ("<script>function cp(b){var t=b.previousElementSibling;"
           "function sel(){var r=document.createRange();"
           "r.selectNodeContents(t);var s=getSelection();"
           "s.removeAllRanges();s.addRange(r);"
           "try{document.execCommand('copy')}catch(e){}}"
           "var done=function(){b.textContent='Copied';"
           "setTimeout(function(){b.textContent='Copy'},1500)};"
           "if(navigator.clipboard){navigator.clipboard.writeText("
           "t.innerText).then(done,function(){sel();done()})}"
           "else{sel();done()}}</script>")


def _k(name):
    return F._key(name)


def _section_of(where, sections):
    """The longest section name `where` starts with ("Directions AI / x"
    belongs to Directions AI, not Directions)."""
    hits = [sec for sec in sections if (where or "").startswith(sec)]
    return max(hits, key=len) if hits else None


# What to mark red in "What it says now", per finding kind.
CURLY = re.compile("[\u2018\u2019\u201c\u201d\u2013\u2014\u2026]")
QUOTED = re.compile("\u201c([^\u201d]{2,120}?)\u2026?\u201d")
URL = re.compile(r"https?://\S+")
PHONE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
OPENING = re.compile("\\(the one starting \u201c(.+?)\u2026\u201d\\)")


def _spans(kind, body, detail):
    """[(start, end)] of the part of `body` the finding is about."""
    body = body or ""
    if kind == "PLACEHOLDER":
        return [(0, len(body))]
    if kind == "NOT PLAIN TEXT":
        return [m.span() for m in CURLY.finditer(body)]
    if kind == "PROMISES A CALL":
        return [m.span() for m in SOON_WORDS.finditer(body)]
    if kind == "GRAMMAR":
        q = _quoted(detail)
        q = re.sub(r" \(.+?\)$", "", q).split(" \u2192 ")[0]
        if q == "i on its own":
            return [m.span() for m in
                    re.finditer(r"(?<![\w'/])i(?![\w'/])", body)]
        i = body.find(q) if q else -1
        return [(i, i + len(q))] if i >= 0 else []
    if kind == "BASE PAY":
        return [m.span() for m in re.finditer(r"\bbase\b", body, re.I)]
    out = []
    for frag in (QUOTED.findall(detail or "") + URL.findall(detail or "")
                 + PHONE.findall(detail or "")):
        frag = frag.strip().rstrip(".,)")
        i = body.find(frag) if frag else -1
        if i >= 0:
            out.append((i, i + len(frag)))
    return out


def marked(body, spans, warn=()):
    """Escaped body with the spans wrapped in <mark> (orange for `warn`
    spans: a question to check, not a fault)."""
    body = body or ""
    warn = set(warn)
    out, at = [], 0
    for a, b in sorted(set(spans) | warn):
        if a < at:
            continue
        tag = "<mark class='warn'>" if (a, b) in warn and (a, b) not in \
            set(spans) else "<mark>"
        out += [_e(body[at:a]), tag, _e(body[a:b]), "</mark>"]
        at = b
    out.append(_e(body[at:]))
    return "".join(out)


# Plain one-liners for the template flags people see most.
PLAIN_FIX = {
    "CALL CHECK": "Do you actually call after this one, or only text?",
    "CHECK ROOM": "Is this Zoom room the one you use for 2nd rounds?",
    "WHO WE HIRE": "Take out the red word: it says who we hire",
    "LOW PAY": "Change the pay to $1,000-$1,500 a week",
    "TYPED ADDRESS": "Use the address fields instead of typing the address",
    "WRONG CITY": "Change the city in the red part to where you are",
    "NOT PLAIN TEXT": "Retype the red mark with your keyboard's plain ' or -",
    "PROMISES A CALL": "Take out the time you promise to call by",
    "GRAMMAR": "Fix the grammar in the red part",
    "DEFLECTS": "Answer the question here instead of pushing it off",
    "SHOUTING": "Write the red part in normal letters, not all capitals",
    "BASE PAY": "Take out the word \u201cbase\u201d: pay is $1,000-$1,500 a "
                "week",
}
PLAIN_WHY = {
    "NOT PLAIN TEXT": "It's a curly \u2019 (or long \u2014) pasted in from "
                      "Word or a phone. It looks the same, but one curly mark "
                      "makes the carrier bill the whole text at about double "
                      "the cost, and longer texts are more likely to not "
                      "arrive. The plain ' in \u201cyou're\u201d is the right "
                      "one.",
}


SOON_WORDS = re.compile(
    r"\s*\b(shortly|soon|today|right away|right now|in a (few|couple)"
    r"( of)? (minutes|mins|hours)|within the (hour|next \w+)|momentarily|"
    r"asap|straight away|in \d+ ?(minutes|mins|min|hours|hour))\b", re.I)


def suggest(body, flags):
    """`body` with the fixes we can make for sure, keeping the office's own
    words (Megan 2026-11-15: "here's what we would recommend ... keeping it
    as like what they have as possible"). Anything that needs a person's
    judgement (base pay, deflecting) is left as it is and stays flagged."""
    from automations.sms_audit import sms_text as SMS
    out = body or ""
    for f in flags:
        kind, detail = f.get("kind"), f.get("detail") or ""
        if kind == "NOT PLAIN TEXT":
            out = SMS.clean(out)
        elif kind == "PROMISES A CALL":
            out = SOON_WORDS.sub("", out)
        elif kind == "SHOUTING":
            m = re.search("\u201c(.+?)\u201d", detail)
            if m and m.group(1) in out:
                out = out.replace(m.group(1), m.group(1).capitalize())
        elif kind == "GRAMMAR":
            out = _fix_grammar(out, detail)
        elif kind == "TYPED ADDRESS":
            q = _quoted(detail)
            if q and q in out:
                out = out.replace(q, "officeAddress1, officeCity, "
                                     "officeState officeZip")
        elif kind == "WRONG CITY":
            m = re.search("says \u201c(.+?)\u201d \u2014 this office is in "
                          "(.+?)\\.?$", detail)
            if m and m.group(1) in out:
                wrong = m.group(1).split(",")[0]
                out = out.replace(m.group(1), m.group(1).replace(
                    wrong, m.group(2)))
        elif kind in ("WRONG ROOM", "WRONG ADDRESS", "CHECK PHONE",
                      "WRONG MEETING ID"):
            pat = {"WRONG ROOM": r"sends (\S+) \u2014 this office\u2019s "
                                 r"room is (\S+?)\.?$",
                   "WRONG ADDRESS": r"sends \u201c(.+?)\u201d \u2014 this "
                                    r"office is (.+?)\.?$",
                   "CHECK PHONE": r"shows (.+?) \u2014 the office number on "
                                  r"file is (.+?)\.?$",
                   "WRONG MEETING ID": r"says (\d+) \u2014 this office's id "
                                       r"is (\d+)\.?$"}[kind]
            m = re.search(pat, detail)
            if m and m.group(1) in out:
                out = out.replace(m.group(1), m.group(2))
    # Megan 2026-11-15: no unneeded spaces in what we recommend.
    out = re.sub(r"[ \t\u00a0]{2,}", " ", out)
    out = re.sub(r" +([,.!?])", r"\1", out)
    out = "\n".join(ln.strip() for ln in out.splitlines())
    return out


def _quoted(detail):
    m = re.search("\u201c(.+?)\u201d", detail or "")
    return m.group(1) if m else ""


def grammar_says(detail):
    """(what's wrong, in plain words) for a proofread finding."""
    q = _quoted(detail)
    kind = (detail or "").split(" \u2014 ")[0].split(":")[0].strip()
    if kind == "doubled word":
        return "The same word twice in a row: \u201c{}\u201d".format(q)
    if kind == "missing space":
        return "Missing a space after the period in \u201c{}\u201d".format(q)
    if kind == "lowercase i":
        return "\u201ci\u201d on its own should be a capital \u201cI\u201d"
    if kind == "capital mid-sentence":
        return ("A capital letter in the middle of a sentence: \u201c{}\u201d"
                .format(q))
    if kind == "comma splice":
        return ("Two sentences joined with a comma: \u201c{}\u201d. Use a "
                "period instead".format(q))
    if kind == "verb form":
        a, _s, b = q.partition(" \u2192 ")
        return "\u201c{}\u201d should be \u201c{}\u201d".format(a, b) \
            if b else "Wrong verb form: \u201c{}\u201d".format(q)
    if kind == "grammar":
        m = re.match(r"(.+?) \((.+?) \u2192 (.+?)\)$", q)
        if m:
            return "\u201c{}\u201d: use \u201c{}\u201d, not \u201c{}\u201d".format(
                m.group(1), m.group(3), m.group(2))
    return "Reads as a mistake: \u201c{}\u201d".format(q) if q else \
        "Reads as a mistake"


def _fix_grammar(out, detail):
    q = _quoted(detail)
    kind = (detail or "").split(" \u2014 ")[0].split(":")[0].strip()
    if kind == "doubled word":
        return re.sub(r"\b(\w+)( \1)+\b", r"\1", out, flags=re.I)
    if kind == "missing space":
        return re.sub(r"([a-z]{2}[.!?])([A-Z][a-z])", r"\1 \2", out)
    if kind == "lowercase i":
        return re.sub(r"(?<![\w'/])i(?![\w'/])", "I", out)
    if kind == "capital mid-sentence" and " " in q:
        a, b = q.rsplit(" ", 1)
        return out.replace(q, "{} {}".format(a, b.lower()))
    if kind == "comma splice" and q:
        m = re.search(r", (\w)", q)
        if m:
            fixed = q[:m.start()] + ". " + m.group(1).upper() + q[m.end():]
            return out.replace(q, fixed)
    if kind == "verb form":
        a, _s, b = q.partition(" \u2192 ")
        if b and a in out:
            return out.replace(a, b)
    if kind == "grammar":
        m = re.match(r"(.+?) \((.+?) \u2192 (.+?)\)$", q)
        if m:
            hit, bad, good = m.groups()
            return out.replace(hit, re.sub(re.escape(bad), good, hit,
                                           count=1, flags=re.I))
    return out


def _changed(old, new):
    """`new`, escaped, with what differs from `old` marked green."""
    import difflib
    # Whole words, so "Irving" -> "Plano" marks Plano, not "Pla" + "o".
    tok = re.compile(r"\s+|[\w']+|[^\w\s]")
    a, b = tok.findall(old), tok.findall(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, _i, _j, c, d in sm.get_opcodes():
        piece = "".join(b[c:d])
        out.append(_e(piece) if op == "equal" or not piece.strip()
                   else "<ins>{}</ins>".format(_e(piece)))
    return "".join(out)


def _rec(item):
    """The one-line change, from the walkthrough's own step."""
    steps = [st for st in item.get("steps") or []
             if not st.startswith(("In ApplicantStream", "Find ", "Click Save"))]
    return steps[0] if steps else item.get("title", "")


def _template_of(where, section, tpls):
    """Index of the template a finding's `where` points at, or None."""
    m = OPENING.search(where or "")
    opening = m.group(1) if m else None
    base = OPENING.sub("", where or "").strip()
    for n, (name, body) in enumerate(tpls):
        label = name if name.startswith(section) else "{} / {}".format(
            section, name)
        if base == label and (opening is None or
                              (body or "").startswith(opening)):
            return n
    return None


STATE_ORDER = {"Activated": 0, "Not Activated": 1, "None Created": 2}


def _e(t):
    return html.escape(str(t if t is not None else ""))


def _mins(v):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return str(v or "")
    if n >= 60 and n % 60 == 0:
        return "{} min ({} hr)".format(n, n // 60)
    if n >= 60:
        return "{} min ({:.1f} hr)".format(n, n / 60)
    return "{} min".format(n)


def _templates(bodies, states):
    """[(section, state, [(name, body)])] — on first, then off, then empty.
    The probe sometimes dumps a template twice (the field, then a stray
    input); the same name+body is kept once."""
    by = {}
    for section, name, body in bodies or []:
        body = "\n".join(ln for ln in (body or "").splitlines()
                         if not ln.startswith("[")).strip()
        lst = by.setdefault(section, [])
        if body and (name, body) not in lst:
            lst.append((name, body))
    names = list(states or {}) + [s for s in by if s not in (states or {})]
    out = [(s, (states or {}).get(s, "Unknown"), by.get(s, [])) for s in names]
    out.sort(key=lambda r: STATE_ORDER.get(r[1], 3))
    return out


_EMAIL_ROW = re.compile(r"^(?P<name>.+?)\s*\((?P<state>Activated|Not Activated)\)")


EMAIL_LINE = re.compile(r"^\[EMAIL (?P<head>.*?) / (?P<name>[^\]]+)\] "
                        r"(?P<field>subject|from|link|body|read failed):"
                        r"\s?(?P<val>.*)$")


def parse_email_bodies(text):
    """[{head, name, subject, from, links, body}] for the switched-on emails
    the pull opened (phase 3), or [] when it didn't."""
    out, cur, in_body = [], None, False
    for raw in (text or "").splitlines():
        m = EMAIL_LINE.match(raw.strip())
        if m:
            key = (m.group("head"), m.group("name").strip())
            if cur is None or (cur["head"], cur["name"]) != key:
                cur = {"head": key[0], "name": key[1], "subject": "",
                       "from": "", "links": [], "body": ""}
                out.append(cur)
            f, v = m.group("field"), m.group("val")
            in_body = f == "body"
            if f == "link":
                cur["links"].append(v)
            elif f in ("subject", "from"):
                cur[f] = v
            continue
        if raw.startswith("=====") or raw.startswith("opening Edit #"):
            in_body = False
            continue
        if in_body and cur is not None:
            cur["body"] += ("\n" if cur["body"] else "") + raw
    for e in out:
        e["body"] = e["body"].strip()
    return out


def parse_email_list(text):
    """[(section, state, [(name, "")])] off the Email Templates page (p=325)
    in the template pull. Names and on/off only: the pull opens SMS
    templates to read their words, not emails. A section is ON when any of
    its emails is Activated."""
    if not text or "PAGE p=325" not in text:
        return None
    page = text.split("PAGE p=325", 1)[1].split("\n#####", 1)[0]
    out, recent = [], []
    cur = None
    for raw in page.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "Create New":
            # section name sits 4 lines up: name, description, Found, Multiples
            cur = [recent[-4] if len(recent) >= 4 else "?", "Not Activated", []]
            out.append(cur)
        elif cur is not None:
            m = _EMAIL_ROW.match(raw.strip())
            if m:
                on = m.group("state") == "Activated"
                cur[2].append((m.group("name").strip() + (" (ON)" if on else
                                                          ""), ""))
                if on:
                    cur[1] = "Activated"
        recent.append(line)
    out = [(a, b, c) for a, b, c in out]
    out.sort(key=lambda r: STATE_ORDER.get(r[1], 3))
    return out


def gather(sinfo=None, prefs=None, esc_rows=None, bodies=None, states=None,
           pulled=None, emails=None, items=(), email_bodies=None):
    """Everything page 2 shows, as data. Any part may be None = not pulled.
    `pulled` is {"ai": date|None, "templates": date|None}."""
    """`items` are page 1's findings (fixes.py items); each is shown again
    here, flagged next to the thing it is about."""
    items = list(items or ())
    out = {"pulled": pulled or {}}
    if sinfo is not None:
        # Megan 2026-11-15: flag "the actual section that we're
        # recommending", on its own row, not in a pile at the bottom.
        on_row = {}
        loose = []
        for i in items:
            if i["source"] != "AI Settings" or i["kind"].startswith("PREF "):
                continue
            f = _flag(i["title"], i["found"], i["why"], APTEL_FIX)
            key = ROW_OF.get(i["kind"])
            if key:
                on_row.setdefault(key, []).append(f)
            else:
                loose.append(f)
        out["info"] = []
        for key, label in INFO:
            flags = list(on_row.get(key, []))
            if key in MUST_FILL and not (sinfo.get(key) or "").strip():
                flags.insert(0, _flag(
                    "Blank. Fill this in.", "",
                    "The AI puts this into its texts. Blank leaves a hole in "
                    "the message.", APTEL_FIX))
            out["info"].append((label, sinfo.get(key) or "", flags))
        out["info_flags"] = loose
        out["prefs"] = []
        for key, label, meaning in PREFS:
            now = (prefs or {}).get(key)
            flag = None
            # Flag only what the card grades (fixes.check_preferences), so
            # page 2 never contradicts page 1 over a 45 vs 60.
            hit = [i for i in F.check_preferences({key: now})]
            if key in PREFS_IF_PRESENT and not str(now or "").strip():
                continue
            if hit:
                flag = _flag("We recommend {}".format(_mins(
                    F.STANDARD[key])), "", hit[0]["why"], APTEL_FIX)
            out["prefs"].append((label, now, F.STANDARD.get(key), meaning,
                                 flag))
    if esc_rows is not None:
        approved = {_k(n): (num, msg) for num, n, msg in F.approved_replies()}
        lint = {}
        for i in items:
            if i["source"] == "AI replies" and i["kind"] != "ROUTING":
                lint.setdefault(_k(i["where"]), []).append(_flag(
                    i["title"], i["found"], i["why"], APTEL_FIX))
        rows = sorted(esc_rows, key=lambda r: (r.get("routing") or "",
                                               r.get("name") or ""))
        out["replies"], seen = [], set()
        dupes = set()
        for r in rows:
            k = _k(r.get("name"))
            sig = (k, r.get("routing"), r.get("message"))
            if sig in dupes:          # the pull can list a row twice
                continue
            dupes.add(sig)
            seen.add(k)
            locked = "only" in (r.get("routing") or "").lower()
            flags = list(lint.get(k, []))
            dont = (r.get("routing") or "").lower().replace("\u2019", "'") \
                in ("don't escalate", "dont escalate", "do not escalate")
            # "Silent Only" rows are locked by AppStream: no type to pick.
            words = NOT_SENT.sub("", r.get("message") or "").strip()
            if k in approved and not dont and not locked:
                num, msg = approved[k]
                if words and not lint.get(k):
                    # The words are fine (often ours already); only the type
                    # stops them going out. Don't offer new wording.
                    flags.insert(0, _flag(
                        "We'd recommend: switch this to Don't Escalate so "
                        "your reply actually sends", "",
                        "It's set to {} right now, so AppStream never sends "
                        "this reply. The AI writes its own answer "
                        "instead.".format(r.get("routing") or "another type"),
                        APTEL_FIX))
                else:
                    flags.insert(0, _flag(
                        "We'd recommend: set this to Don't Escalate with one "
                        "of our replies", "", WHY_DONT, APTEL_FIX,
                        F.reply_versions(r.get("name"), msg),
                        F.reply_link(r.get("name"))))
            out["replies"].append((r.get("name"), r.get("routing"),
                                   words, flags))
        out["replies_missing"] = [
            (num, n, msg) for num, n, msg in F.approved_replies()
            if _k(n) not in seen]
    if bodies is not None:
        tpl = _templates(bodies, states)
        names = [sec for sec, _st, _t in tpl]
        by, per = {}, {}
        for i in items:
            if i["source"] != "Templates":
                continue
            sec = _section_of(i["where"], names)
            if not sec:
                continue
            tpls = next(t for sc, _s, t in tpl if sc == sec)
            n = _template_of(i["where"], sec, tpls)
            f = _flag(i["title"], "", i["why"], YOU)
            f["rec"] = _rec(i)
            f["kind"] = i["kind"]
            f["detail"] = i["found"]
            f["warn"] = i["kind"] in F.WARN_KINDS
            if n is None:
                f["found"] = i["found"]
                by.setdefault(sec, []).append(f)
            else:
                f["spans"] = _spans(i["kind"], tpls[n][1], i["found"])
                per.setdefault((sec, n), []).append(f)
        # Megan 2026-11-15: Raf doesn't have a list of what every office
        # should have on, so no "turn this on" flags. A recommended call
        # cycle replaces them once Megan sets one (RECOMMENDED_CYCLE).
        out["sms"] = []
        for sec, state, tpls in tpl:
            flags = list(by.get(sec, []))
            full = [(name, body, per.get((sec, n), []))
                    for n, (name, body) in enumerate(tpls)]
            out["sms"].append((sec, state, full, flags))
    if emails is not None:
        out["email"] = [(sec, state, tpls, []) for sec, state, tpls in emails]
        # The wording of each switched-on email, with its flags, keyed by
        # the email's name (unique in practice; the section heading the
        # pull saw can differ from the list's).
        by_name = {}
        for e in email_bodies or []:
            flags = []
            where = F.email_where(e["head"], e["name"])
            for i in items:
                if i["source"] != "Templates" or \
                        (i["where"] or "").strip() != where:
                    continue
                f = _flag(i["title"], "", i["why"], YOU)
                f.update(rec=_rec(i), kind=i["kind"], detail=i["found"],
                         warn=i["kind"] in F.WARN_KINDS)
                f["spans"] = _spans(i["kind"], e["body"], i["found"])
                flags.append(f)
            by_name[e["name"].strip()] = dict(e, flags=flags)
        out["email_bodies"] = by_name
    out["flags"] = count(out)
    return out


def count(setup):
    """Flags per section of page 2."""
    s = setup or {}
    return {
        "ai": sum(len(r[2] or []) for r in s.get("info", []))
        + len(s.get("info_flags", [])),
        "prefs": sum(1 for r in s.get("prefs", []) if r[4]),
        "replies": sum(len(r[3]) for r in s.get("replies", []))
        + len(s.get("replies_missing", [])),
        "sms": sum(len(r[3]) + sum(len(t[2]) for t in r[2])
                   for r in s.get("sms", [])),
        "email": sum(len(r[3]) for r in s.get("email", []))
        + sum(len(e["flags"]) for e in (s.get("email_bodies") or {}).values()),
    }


def _when(d):
    return " · pulled {}/{}/{}".format(d.month, d.day, d.year) if d else ""


def _ampm(start):
    """'08:15 AM' -> 'am'; '12:30 PM' -> 'pm'. Noon counts as afternoon."""
    t = (start or "").strip().upper()
    return "pm" if t.endswith("PM") else "am" if t.endswith("AM") else ""


def _short_time(t):
    """'08:15 AM' -> '8:15'."""
    return (t or "").strip().upper().replace(" AM", "").replace(
        " PM", "").lstrip("0")


def _slot_list(lst):
    """One line for a half-day: '5 times, 8:15-10:15 AM · 24 seats each'.
    Megan 2026-11-15: every time listed out was "a lot to look at"."""
    if not lst:
        return "<span class='s'>none</span>"
    first, last = lst[0].get("start", ""), lst[-1].get("start", "")
    span = _short_time(first) if first == last else "{}\u2013{}".format(
        _short_time(first), _short_time(last))
    seats = sorted({x["seats"] for x in lst if x.get("seats")})
    # Megan 2026-11-15: "5 slots with x amount / slot", on 2 distinct lines.
    per = ("" if not seats else " \u00b7 {} / slot".format(seats[0])
           if len(seats) == 1 else " \u00b7 {}\u2013{} / slot".format(
               seats[0], seats[-1]))
    return ("<b>{} slot{}</b>{}<br><span class='s'>{} {}</span>".format(
        len(lst), "" if len(lst) == 1 else "s", per, _e(span),
        _ampm(last).upper()))


DAY_SHORT = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
             "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat",
             "Sunday": "Sun"}


def slot_rows(hours):
    """[(day label, morning html, afternoon html)] with days in a row that
    are set the same folded into one ('Mon\u2013Fri')."""
    rows = []
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday"):
        lst = hours.get(day) or []
        am = _slot_list([x for x in lst if _ampm(x.get("start")) == "am"])
        pm = _slot_list([x for x in lst if _ampm(x.get("start")) == "pm"])
        # Megan 2026-11-15: "how many total 1st rounds can happen that
        # day? let's add that total" = every slot's seats added up.
        total = sum(x.get("seats") or 1 for x in lst)
        tot = ("<b>{}</b>".format(total) if lst
               else "<span class='s'>0</span>")
        if rows and rows[-1][2:] == [am, pm, tot]:
            rows[-1][1] = day
        else:
            rows.append([day, day, am, pm, tot])
    return [(DAY_SHORT[a] if a == b else "{}\u2013{}".format(
        DAY_SHORT[a], DAY_SHORT[b]), am, pm, tot)
        for a, b, am, pm, tot in rows]


def _clock(minutes):
    """Minutes after midnight -> '1:00 PM'."""
    h, m = divmod(int(minutes) % (24 * 60), 60)
    return "{}:{:02d} {}".format(h % 12 or 12, m, "AM" if h < 12 else "PM")


def example(key, now):
    """One worked example for a buffer, from what it's set to now
    (Megan 2026-11-15: "if it's noon, then the soonest offered time would
    be 1 p.m.")."""
    try:
        n = int(str(now).strip())
    except (TypeError, ValueError):
        return ""
    if key == "offered_buffer":
        return ("Example: at 12:00 PM the AI texts \u201cI have {} or "
                "{}\u201d, never anything sooner.".format(
                    _clock(12 * 60 + n), _clock(12 * 60 + n + 30)))
    if key == "accepted_buffer":
        soon = max(n - 30, 0)
        return ("Example: at 12:00 PM the applicant asks \u201ccan I do "
                "{}?\u201d The AI says no{}. {} or later, it books."
                .format(_clock(12 * 60 + soon), "" if soon else
                        " to anything right now", _clock(12 * 60 + n)))
    if key == "ghosting_threshold":
        return ("Example: if the applicant's last text was at 1:00 PM, it's "
                "flagged at {}.".format(_clock(13 * 60 + n)))
    return ""


def _flag_body(f):
    """One flag opened inside a row: its title, then the usual box."""
    return "<div class='rowbox'><b>\u2691 {}</b>{}{}{}{}</div>".format(
        _e(f["title"]),
        "<div class='found'>{}</div>".format(_e(f["found"]))
        if f.get("found") else "",
        options_html(f.get("options"), f.get("link")),
        "<p class='why'><b>Why:</b> {}</p>".format(_e(f["why"]))
        if f.get("why") else "",
        "<p class='who'><b>Who fixes it:</b> {}</p>".format(_e(f["owner"]))
        if f.get("owner") else "")


def _flags_html(flags):
    out = []
    for f in flags or []:
        out.append("<details class='flag'><summary>\u2691 {}</summary>"
                   "{}{}{}{}</details>".format(
            _e(f["title"]),
            "<div class='found'>{}</div>".format(_e(f["found"]))
            if f.get("found") else "",
            options_html(f.get("options"), f.get("link")),
            "<p class='why'><b>Why:</b> {}</p>".format(_e(f["why"]))
            if f.get("why") else "",
            "<p class='who'><b>Who fixes it:</b> {}</p>".format(
                _e(f["owner"]))
            if f.get("owner") else ""))
    return "".join(out)


def _badge(n):
    return ("<span class='fl'>\u2691 {}</span>".format(n) if n else "")


def _head(title, n, when=None, checked=False):
    """`checked`: a section we grade, so a clean one says so in green
    (Megan 2026-11-15: "this section should check green")."""
    ok = (" <span class='okay'>\u2713 matches what we recommend</span>"
          if checked and not n else "")
    return "<h2 class='k'>{}{} {}{}</h2>".format(
        _e(title), _e(_when(when)), _badge(n), ok)


# ApplicantStream's short step names, spelled out next to the name
# (Megan 2026-11-15: FDOT = "first day of training").
ABBREV = {"FDOT": "First Day of Training"}


def _email_html(e):
    """One switched-on email: subject, what it says, our version, flags."""
    flags = e.get("flags") or []
    spans = [sp for f in flags if not f.get("warn")
             for sp in f.get("spans", [])]
    warn = [sp for f in flags if f.get("warn") for sp in f.get("spans", [])]
    out = ["<div class='tpl'><p class='tn'>Email: {}</p>".format(
        _e(e["name"]))]
    if e.get("subject"):
        out.append("<p><b>Subject:</b> {}</p>".format(_e(e["subject"])))
    out.append("<p class='lbl'>What it says now:</p><div class='says mail'>"
               "{}</div>".format(marked(e["body"], spans, warn)))
    # Only real fixes get a recommended version; an orange question has
    # nothing to rewrite.
    fixes = [f for f in flags if not f.get("warn")]
    fixed = suggest(e["body"], fixes) if fixes else e["body"]
    if fixed != e["body"]:
        out.append("<p class='lbl'>Here's what we'd recommend:</p>"
                   "<div class='opt rec'><span class='says ok mail'>{}</span>"
                   "<button type='button' onclick='cp(this)'>Copy</button>"
                   "</div>".format(_changed(e["body"], fixed)))
    for f in flags:
        out.append("<details class='flag{}'><summary>\u2691 {}</summary>"
                   "<p class='why'><b>Why:</b> {}</p><p class='who'><b>Who "
                   "fixes it:</b> {}</p></details>".format(
                       " warn" if f.get("warn") else "",
                       _e(grammar_says(f.get("detail"))
                          if f.get("kind") == "GRAMMAR" else
                          PLAIN_FIX.get(f.get("kind")) or f["rec"]),
                       _e(PLAIN_WHY.get(f.get("kind")) or f["why"]),
                       _e(f["owner"])))
    out.append("</div>")
    return "".join(out)


def _sec_label(section):
    """Escaped step name, with any short name spelled out after it."""
    out = _e(section)
    for short, full in ABBREV.items():
        if re.search(r"\b{}\b".format(short), section or ""):
            out += " <span class='s'>({} = {})</span>".format(short, full)
    return out


def _onoff(state):
    on = state == "Activated"
    return "<span class='onoff {}'>{}</span>".format(
        "on" if on else "off",
        "ON" if on else "OFF" if state == "Not Activated" else "NONE")


# Megan 2026-11-15: the setup page split in two tabs. AI Settings is
# everything set on ApplicantStream's AI Settings page; Templates is the
# text + email wording.
AI_PARTS = ("ai", "prefs", "replies")
TEMPLATE_PARTS = ("sms", "email")


def flag_total(setup, parts):
    """How many flags fall on one tab."""
    s = setup or {}
    n = s.get("flags") or count(s)
    return sum(n.get(k) or 0 for k in parts)


def _intro(total, what):
    out = ["<p class='s'>{}, as of the last pull. <span class='fl'>\u2691"
           "</span> marks what we recommend changing or setting up, and why."
           "</p>".format(what)]
    if total:
        out.append("<p class='flagsum'>\u2691 {} thing{} we recommend "
                   "changing</p>".format(total, "" if total == 1 else "s"))
    return out


def render(setup):
    """Both setup tabs, one after the other (for tests and old callers)."""
    return render_ai(setup) + "\n" + render_templates(setup)


# Megan 2026-11-15: "if an office isn't set up with AI yet, that AI
# breakdown tab should say so and then list the price of enrolling in AI and
# how to set it up". Fill these in from Aptel; until then the tab says to ask.
AI_PRICE = None          # e.g. "$X a month"
AI_SETUP_STEPS = []      # plain-English steps, in order


def no_ai(setup):
    """True when the AI Settings pull ran but found no AI on the office:
    no AI name, no replies and no interview times."""
    s = setup or {}
    if "info" not in s:
        return False                       # not pulled: can't tell
    name = next((v for label, v, _f in s["info"] if label == "AI's name"),
                "")
    return not (name or "").strip() and not s.get("replies") \
        and not s.get("hours")


def _no_ai_html():
    price = ("<p><b>Price:</b> {}</p>".format(_e(AI_PRICE)) if AI_PRICE
             else "<p><b>Price:</b> message the Aptel team for the current "
             "price.</p>")
    steps = ("<p><b>How to set it up:</b></p><ol>{}</ol>".format(
        "".join("<li>{}</li>".format(_e(x)) for x in AI_SETUP_STEPS))
        if AI_SETUP_STEPS else
        "<p><b>How to set it up:</b> message the Aptel team and ask to "
        "enroll this office in ApplicantStream's AI.</p>")
    return ("<div class='flag noai'><b>This office isn't set up with "
            "ApplicantStream's AI yet.</b><p>The AI texts every new "
            "applicant within minutes, answers their questions and books "
            "the 1st round for you, day and night.</p>{}{}</div>".format(
                price, steps))


def render_ai(setup):
    """HTML for the AI Settings tab."""
    s = setup or {}
    if no_ai(s):
        return _no_ai_html()
    n = s.get("flags") or count(s)
    L = _intro(flag_total(s, AI_PARTS),
               "What ApplicantStream's AI is set to")
    add = L.append
    when = s.get("pulled") or {}

    add(_head("Office info the AI uses", n.get("ai"), when.get("ai")))
    if "info" not in s:
        add("<p class='s'>Not pulled yet.</p>")
    else:
        add("<div class='truth'><table>")
        for label, value, flag in s["info"]:
            main, _sep, note = label.partition(" (")
            shown = _e(value) if value else "<i>blank</i>"
            if flag:
                # The value with a flag on the right; tap it to open the
                # red box right there under the value.
                shown = ("<details class='flag rowflag'><summary>{}<span "
                         "class='pin'>\u2691 {}</span></summary>{}</details>"
                         .format(shown, len(flag), "".join(
                             _flag_body(f) for f in flag)))
            add("<tr{}><td>{}</td><td>{}</td></tr>".format(
                " class='diff'" if flag else "", _e(main) + (
                    "<br><span class='s note'>{}</span>".format(
                        _e(note.rstrip(")"))) if note else ""), shown))
            if label == "1st round interview type":
                # ApplicantStream has no 2nd-round type field yet; Megan is
                # asking Aptel to add it.
                add("<tr><td>2nd round interview type</td><td><i class='s'>"
                    "Not available yet in ApplicantStream</i></td></tr>")
        add("</table>{}</div>".format(_flags_html(s.get("info_flags"))))

        add(_head("Buffer times + ghosting", n.get("prefs"), checked=True))
        add("<div class='truth'><table class='prefs'><tr><th></th>"
            "<th>Set now</th><th>Our standard</th></tr>")
        # By label, not position: a row the office's page lacks is skipped
        # (PREFS_IF_PRESENT), so zip(PREFS, rows) would pair the wrong key.
        _key_of = {l: k for k, l, _m in PREFS}
        for label, now, want, meaning, flag in s["prefs"]:
            key = _key_of.get(label, "")
            ex = example(key, now)
            if ex:
                meaning = "{} {}".format(meaning, ex)
            add("<tr{}><td><b>{}</b><br><span class='s'>{}</span></td>"
                "<td{}>{}{}</td><td>{}</td></tr>".format(
                    " class='diff'" if flag else "", _e(label), _e(meaning),
                    "" if flag else " class='okay'",
                    "" if flag else "\u2713 ",
                    _e(_mins(now)) if now not in (None, "") else
                    "<i>blank</i>",
                    _e(_mins(want)) if want is not None else "—"))
            if flag:
                add("<tr><td colspan='3'>{}</td></tr>".format(
                    _flags_html([flag])))
        add("</table></div>")

    add(_head("Interview slots (1st rounds)", 0, when.get("ai")))
    if not s.get("hours"):
        add("<p class='s'>Not pulled yet. They're on AI \u2192 AI Settings "
            "\u2192 Hours.</p>")
    else:
        add("<div class='truth'><table class='list'><tr><th>Day</th>"
            "<th>Morning</th><th>Afternoon</th><th>1st rounds / day</th>"
            "</tr>")
        for label, am, pm, tot in slot_rows(s["hours"]):
            add("<tr><td><b>{}</b></td><td>{}</td><td>{}</td>"
                "<td class='tot'>{}</td></tr>".format(label, am, pm, tot))
        add("</table></div>")

    add(_head("AI replies (escalations)", n.get("replies"), when.get("ai"),
              checked="replies" in s))
    if "replies" not in s:
        add("<p class='s'>Not pulled yet.</p>")
    else:
        if s.get("replies_missing"):
            add("<details open><summary><span class='t'>Not set up at all"
                "</span><span class='s'>{} of our replies</span> {}"
                "</summary><div class='body'>".format(
                    len(s["replies_missing"]),
                    _badge(len(s["replies_missing"]))))
            for num, name, msg in s["replies_missing"]:
                add("<p class='tn'>#{} {}</p>{}".format(num, _e(name),
                    _flags_html([_flag(
                        "Recommend: add it as Don't Escalate", "", WHY_DONT,
                        APTEL_FIX, F.reply_versions(name, msg),
                        F.reply_link(name))])))
            add("</div></details>")
        groups = {}
        for name, routing, msg, flags in s["replies"]:
            groups.setdefault(routing or "(no type)", []).append(
                (name, msg, flags))
        for routing, rows in groups.items():
            nf = sum(len(f) for _n, _m, f in rows)
            # Megan 2026-11-15: "these should be green if they are set up
            # correctly" - a group with no flags says so in green.
            add("<details{}><summary>{}<span class='t'>{}</span>"
                "<span class='s'>{} replies</span> {}</summary>"
                "<div class='body'><table class='list'>".format(
                    "" if nf else " class='good'",
                    "" if nf else "<span class='okay'>\u2713</span> ",
                    _e(routing), len(rows), _badge(nf) if nf else
                    "<span class='okay'>matches what we recommend</span>"))
            for name, msg, flags in rows:
                add("<tr><td><b>{}</b><p class='lbl'>What your current "
                    "reply says:</p><div class='says'>{}</div>{}</td></tr>"
                    .format(_e(name), _e(msg) if msg else
                            "<i class='s'>nothing (blank)</i>",
                            _flags_html(flags)))
            add("</table></div></details>")
    return "\n".join(L)


def render_templates(setup):
    """HTML for the Templates tab."""
    s = setup or {}
    n = s.get("flags") or count(s)
    L = _intro(flag_total(s, TEMPLATE_PARTS),
               "What your text and email templates say")
    add = L.append
    when = s.get("pulled") or {}

    if RECOMMENDED_CYCLE:
        add("<div class='truth'><b>We recommend your call cycle be:</b><ol>"
            "{}</ol></div>".format("".join(
                "<li>{}</li>".format(_e(x)) for x in RECOMMENDED_CYCLE)))
    add(_head("SMS templates", n.get("sms"), when.get("templates")))
    if "sms" not in s:
        add("<p class='s'>Not pulled yet.</p>")
    else:
        for section, state, tpls, flags in sorted(
                s["sms"], key=lambda r: (not r[3], STATE_ORDER.get(r[1], 3))):
            add("<details><summary>{}<span class='t'>{}</span>"
                "<span class='s'>{}</span> {}</summary><div class='body'>"
                .format(_onoff(state), _sec_label(section),
                        "{} template{}".format(len(tpls),
                                               "" if len(tpls) == 1 else "s")
                        if tpls else "none saved", _badge(
                            len(flags) + sum(len(t[2]) for t in tpls))))
            add(_flags_html(flags))
            for name, body, tflags in tpls:
                spans = [sp for f in tflags if not f.get("warn")
                         for sp in f.get("spans", [])]
                warn = [sp for f in tflags if f.get("warn")
                        for sp in f.get("spans", [])]
                add("<div class='tpl'><p class='tn'>Template name: {}</p>"
                    "<p class='lbl'>What it says now:</p>"
                    "<div class='says'>{}</div>".format(
                        _e(name), marked(body, spans, warn)))
                fixes = [f for f in tflags if not f.get("warn")]
                fixed = suggest(body, fixes) if fixes else (body or "")
                if fixed != (body or ""):
                    add("<p class='lbl'>Here's what we'd recommend:</p>"
                        "<div class='opt rec'><span class='says ok'>{}</span>"
                        "<button type='button' onclick='cp(this)'>Copy"
                        "</button></div>".format(_changed(body or "", fixed)))
                for f in tflags:
                    add("<details class='flag{}'><summary>\u2691 {}</summary>"
                        "<p class='why'><b>Why:</b> {}</p>"
                        "<p class='who'><b>Who fixes it:</b> {}</p></details>"
                        .format(" warn" if f.get("warn") else "",
                                _e(grammar_says(f.get("detail"))
                                   if f.get("kind") == "GRAMMAR" else
                                   PLAIN_FIX.get(f.get("kind")) or f["rec"]),
                                _e(PLAIN_WHY.get(f.get("kind")) or f["why"]),
                                _e(f["owner"])))
                add("</div>")
            if not tpls:
                add("<p class='s'>No template saved here.</p>")
            add("</div></details>")

    add(_head("Email templates", n.get("email"), when.get("templates")))
    if not s.get("email"):
        add("<p class='s'>Not pulled yet.</p>")
    else:
        add("<p class='s'>Each step's emails. Tap a step to read what the "
            "switched-on email says.</p>")
        bodies = s.get("email_bodies") or {}
        for section, state, tpls, flags in sorted(
                s["email"], key=lambda r: (not r[3], STATE_ORDER.get(r[1], 3))):
            live = [nm[:-5] for nm, _b in tpls if nm.endswith(" (ON)")]
            shown = [bodies[n.strip()] for n in live if n.strip() in bodies]
            nflags = len(flags) + sum(len(e["flags"]) for e in shown)
            add("<details><summary>{}<span class='t'>{}</span>"
                "<span class='s'>{}</span> {}</summary><div class='body'>"
                .format(_onoff(state), _sec_label(section),
                        _e(", ".join(live)) if live else
                        "{} saved, none on".format(len(tpls)),
                        _badge(nflags)))
            add(_flags_html(flags))
            for e in shown:
                add(_email_html(e))
            if live and not shown:
                add("<p class='s'>The wording of this email wasn't pulled "
                    "yet.</p>")
            off = [nm for nm, _b in tpls if not nm.endswith(" (ON)")]
            if off:
                add("<p class='lbl'>Also saved here, switched off:</p><ul>{}"
                    "</ul>".format("".join("<li>{}</li>".format(_e(nm))
                                           for nm in off)))
            add("</div></details>")
    return "\n".join(L)


CSS = """
.tabs{display:flex;gap:.4em;margin:0 0 1em}
.tabs label{flex:1;text-align:center;padding:.55em .4em;border-radius:8px;
     border:2px solid var(--ink);cursor:pointer;font-weight:bold;
     background:#fff}
#pg0,#pg1,#pg2,#pg3,#pg4{display:none}
#pg0:checked~.tabs label[for=pg0],#pg1:checked~.tabs label[for=pg1],
#pg2:checked~.tabs label[for=pg2],#pg3:checked~.tabs label[for=pg3],
#pg4:checked~.tabs label[for=pg4]{
     background:var(--ink);color:#fff}
.page0,.page1,.page2,.page3,.page4{display:none}
#pg0:checked~.page0,#pg1:checked~.page1,#pg2:checked~.page2,
#pg3:checked~.page3,#pg4:checked~.page4{display:block}
.tabs .fl{font-size:.8em;margin-left:.3em}
.okay{color:#156E46;font-weight:bold}
.noai{background:#fff8e6;border-color:#e0b85c}
details.good{border-color:#9fd3b5;background:#f1faf4}
details.good summary .okay{margin-right:.2em}
.list td.tot{text-align:center;font-size:1.15em}
h2 .okay{font-size:.85em;margin-left:.4em;text-transform:none;
     letter-spacing:0}
.prefs td:nth-child(2),.prefs td:nth-child(3){white-space:nowrap}
table.prefs th{font-size:.8em;color:var(--muted);text-align:left;
     font-weight:normal;padding:.2em .3em}
table.prefs td{text-align:left;white-space:normal}
table.prefs td:first-child{width:auto;color:var(--ink)}
table.prefs tr.diff td:nth-child(2){color:#A8322A;font-weight:bold}
table.list td{text-align:left;white-space:normal}
.onoff{flex:none;font-size:.72em;font-weight:bold;padding:.15em .45em;
     border-radius:5px;min-width:2.8em;text-align:center}
.onoff.on{background:#e3f1e8;color:#156E46}
.onoff.off{background:#eee;color:#777}
.tn{font-weight:bold;margin:.6em 0 .1em}
.flag{background:#fdecea;border-left:3px solid #A8322A;border-radius:6px;
     padding:.4em .6em;margin:.4em 0;font-size:.95em;text-align:left;
     white-space:normal}
.flag .found{background:#fff}
details.flag.warn{background:#fff4e0;border-left-color:#e08a00}
details.flag.warn>summary,details.flag.warn>summary::after{color:#a35f00}
details.flag.warn:not([open]){background:transparent}
.says mark.warn{background:#ffe1a8;color:#7a4a00;outline-color:#e08a00}
.says.mail{white-space:pre-line;max-height:22em;overflow:auto}
.opt.rec{display:flex;gap:.5em;align-items:flex-start}
.opt.rec .says{flex:1;background:#f1faf4;border:1px solid #9fd3b5}
.says ins{background:#cdebd8;color:#0f5a36;text-decoration:none;
     font-weight:bold;border-radius:3px;padding:0 .12em}
details.flag>summary{cursor:pointer;font-weight:bold;color:#A8322A;
     list-style:none}
details.flag>summary::-webkit-details-marker{display:none}
details.flag>summary::after{content:" \u25B8";color:#A8322A}
details.flag[open]>summary::after{content:" \u25BE"}
details.flag:not([open]){background:transparent;border-left-color:transparent;
     padding:.1em 0}
.truth td{vertical-align:middle}
tr.diff>td{background:#fdecea}
details.rowflag,details.rowflag:not([open]){background:transparent;
     border:0;padding:0;margin:0;font-size:1em}
details.rowflag>summary{color:inherit;font-weight:normal;display:flex;
     align-items:center;gap:.5em}
details.rowflag>summary::after,details.rowflag[open]>summary::after{display:none}
tr.diff>td:first-child{vertical-align:top;padding-top:.7em}
details.rowflag .pin{margin-left:auto;color:#A8322A;font-weight:bold;
     white-space:nowrap}
details.rowflag[open] .pin::after{content:" \u25BE"}
details.rowflag:not([open]) .pin::after{content:" \u25B8"}
.rowbox{background:#fff;border-left:3px solid #A8322A;border-radius:6px;
     padding:.4em .6em;margin:.4em 0 0;font-size:.95em}
.note{font-size:.8em;line-height:1.25}
.flag .why{margin:.2em 0}
.rec{margin:.3em 0 .1em}
.tpl{border-top:1px solid var(--line);padding:.5em 0 .2em;margin-top:.4em}
.tpl .tn{margin:0}
.lbl{margin:.3em 0 .1em;color:var(--muted);font-size:.9em}
.says{background:var(--soft);padding:.45em .6em;border-radius:6px;
     white-space:pre-wrap;word-break:break-word}
.says mark{background:#f3b6ae;color:#7a1d14;font-weight:bold;
     border-radius:3px;padding:0 .15em;outline:1px solid #A8322A}
details.opts{background:#fff;border:1px solid var(--line);margin:.2em 0}
a.opts-link{color:#1a56c4;font-weight:bold}
details.opts>summary{padding:.35em .6em;color:#1a56c4;font-weight:bold}
details.opts .body{padding:0 .6em .5em}
.opt{display:flex;gap:.6em;align-items:flex-start;border-top:1px solid
     var(--line);padding:.45em 0}
.opt span{flex:1}
.opt button{flex:none;font:inherit;font-size:.85em;padding:.2em .7em;
     border:1px solid #1a56c4;color:#1a56c4;background:#fff;
     border-radius:6px;cursor:pointer}
.flag .who{margin:.2em 0;color:#1a56c4}
.fl{color:#A8322A;font-weight:bold;font-size:.9em;letter-spacing:0;
     text-transform:none}
.flagsum{background:#fdecea;color:#A8322A;font-weight:bold;
     border-radius:8px;padding:.5em .8em}
.truth tr.diff>td:first-child{color:#A8322A;font-weight:bold}
"""
