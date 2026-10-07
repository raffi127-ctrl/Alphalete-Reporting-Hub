"""The full audit of one interview, as a Google Doc -- the link in each Slack reply.

Same layout as the manual pilot's docs (Sep 22-24, Rafael's 9/24 feedback):
plain full-width text, no tables -- header, scorecard + coaching, the red
flags, the must-dos, then the applicants' questions.

Drive (Eve, 2026-09-29): Rafael's folder "1st rd Transcribes", where the
people who read them already have access -- so nothing is shared by code.
Inside it, one folder per interviewer, then one per day, then one doc per
interview:  1st rd Transcribes / Valentina / 2026-09-29 / <doc>.
Interviewer first: the coaching is per person, and so are the Slack threads.
(Camila's hand-uploaded transcripts, by date, sit next to them; the bot reads
Fathom directly and doesn't use them.) A re-run updates the doc in place, so
the link already posted keeps working. Written with its own full-drive token,
see drive_auth.py.
"""
from __future__ import annotations

import html
import io
import re
from typing import Dict

from automations.first_round_scorecards import appstream, fathom, grade

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
GREEN, RED, YELLOW = "#38761d", "#cc0000", "#bf9000"
_TS = re.compile(r"@(\d{1,2}):(\d{2})(?::(\d{2}))?")


def _linked(text: str, share: str) -> str:
    """Escape the note and turn every '@12:29' into a link to that moment."""
    def go(m):
        h, mi, se = m.group(1), m.group(2), m.group(3)
        secs = int(h) * 3600 + int(mi) * 60 + int(se) if se else int(h) * 60 + int(mi)
        return f'<a href="{share}?timestamp={secs}">{m.group(0)}</a>'
    return _TS.sub(go, html.escape(text))


def build_html(m: Dict, name: str, result: Dict) -> str:
    s = grade.score(result)
    share = m.get("share_url") or m.get("url") or ""
    start = fathom.start_ct(m)
    col = GREEN if s["score"] >= 90 else (YELLOW if s["score"] >= 70 else RED)
    who = ", ".join(a for a in result.get("applicants") or [] if a.strip()) or "—"
    speaker = (m.get("recorded_by") or {}).get("name") or ""
    sched = appstream.scheduled_text(m)
    sched = f" · <b>Scheduled (AppStream):</b> {html.escape(sched)}" if sched else ""
    early = appstream.early_by(m)
    early = (f'<p style="color:{RED}"><b>⚠️ Started {early} min before the scheduled '
             f"time.</b></p>") if early else ""
    gaps = grade.skipped(result)
    out = ['<html><head><meta charset="utf-8"></head><body style="font-family:Arial;font-size:11pt">',
           f"<h1>1st Round AI Audit — {html.escape(name)}, {start:%b %d} {start.strftime('%I:%M %p').lstrip('0')}</h1>",
           f"<p><b>Interview:</b> {start:%a, %b %d, %Y} · <b>Start time:</b> "
           f"{start.strftime('%I:%M %p').lstrip('0')} CT{sched} · {fathom.minutes(m)} min · "
           f'<a href="{share}">Fathom recording</a></p>' + early,
           f"<p><b>Interviewer:</b> {html.escape(name)} ({html.escape(speaker)}) · "
           + (f"<b>Office:</b> {html.escape(m['owner'])} · " if m.get("owner") else "")
           + f"<b>Applicants:</b> {html.escape(who)}</p>"
           # whose script the score was counted against (each office has its own
           # pay + schedule, 2026-10-06); older docs never had it
           + (f"<p><b>Script:</b> {html.escape(result['script_office'])}'s office</p>"
              if result.get("script_office") else
              "<p><b>Script:</b> standard (Rafael's)</p>" if "script_office" in result else ""),
           f'<h2>Scorecard: <span style="color:{col}">{s["score"]} / 100 {_emoji(s["score"])}</span></h2>',
           f"<p>🚩 Red flags: <b>{s['red_hit']} of 5</b> happened · ✅ Must-dos: "
           f"<b>{s['musts_done']} of 6</b> done</p>",
           "<p><i>11 items (5 red flags + 6 must-dos). Score = % of items passed. Red flag: "
           "YES = bad. Must-do: YES = good, only if fully done. Each script portion in "
           "incorrect verbiage: minus half an item. 90+ 🟢 · 70–89 🟡 · under 70 🔴</i></p>",
           "<p><b>Coaching points:</b></p><ul>"
           + "".join(f"<li>{html.escape(c)}</li>" for c in result.get("coaching") or [])
           + "</ul>"]
    if "skipped_portions" in result:
        # Rafael 9/30: the count, and each skipped script line word for word
        out.append(f"<h2>⏭️ Skipped portions: {len(gaps)}</h2>")
        if not gaps:
            out.append("<p>She said every part of the script.</p>")
        for n_gap, (_, line, note) in enumerate(gaps, 1):
            out.append(f"<p><b>{n_gap}.</b> <i>\"{html.escape(line)}\"</i>"
                       + (f"<br>{_linked(note, share)}" if note else "") + "</p>")
        wrong = grade.verbiage(result)
        if wrong:
            out.append(f"<h2>✏️ Incorrect verbiage: {len(wrong)}</h2>"
                       f"<p><i>Said, but in different words than the script. Each one "
                       f"costs half an item of the score.</i></p>")
        for n_gap, (_, line, note) in enumerate(wrong, 1):
            out.append(f"<p><b>{n_gap}. She said:</b> {_linked(note, share)}"
                       f"<br><b>Script:</b> <i>\"{html.escape(line)}\"</i></p>")
    n = 0
    for kind, title in (("red", "🚩 Red flags — should NOT happen"),
                        ("must", "✅ Must-dos — should happen")):
        out.append(f"<h2>{title}</h2>")
        for key, question, k in grade.ITEMS:
            if k != kind:
                continue
            n += 1
            it = (result.get("items") or {}).get(key) or {}
            yes = bool(it.get("happened"))
            good = (not yes) if kind == "red" else yes
            flag = " 🚩" if kind == "red" and yes else ""
            out.append(f'<h3>{n}. {html.escape(question)} — <span style="color:{GREEN if good else RED}">'
                       f'{"YES" if yes else "NO"}{flag}</span></h3>')
            out.append(f"<p>{_linked(it.get('note') or '', share)}</p>")
            if key == "commute":
                out.append("<p><i>Address in the Zoom chat: chat messages are not in the Fathom "
                           "transcript, so this is only caught if she says it out loud.</i></p>")
    out.append("<h2>❓ Applicants' questions</h2>")
    qs = result.get("applicant_questions") or []
    if not qs:
        out.append("<p>None of the usual questions came up (door to door, benefits, flexible "
                   "schedule, scam, hourly pay, specific city).</p>")
    for q in qs:
        out.append(f"<p><b>{html.escape(q.get('topic') or '')}:</b> {_linked(q.get('question') or '', share)}"
                   f"<br><b>Answer:</b> {_linked(q.get('answer') or '', share)}</p>")
    out.append("</body></html>")
    return "\n".join(out)


def _emoji(score: int) -> str:
    return "🟢" if score >= 90 else ("🟡" if score >= 70 else "🔴")


def doc_name(m: Dict, name: str) -> str:
    start = fathom.start_ct(m)
    return f"{name} — {start:%b %d} {start.strftime('%I:%M %p').lstrip('0')} — 1st rd audit"


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _folder(svc, name: str, parent: str) -> str:
    q = (f"name = '{_q(name)}' and mimeType = '{FOLDER_MIME}' and trashed = false "
         f"and '{parent}' in parents")
    found = svc.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
    if found:
        return found[0]["id"]
    return svc.files().create(body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
                              fields="id").execute()["id"]


def upload(m: Dict, name: str, result: Dict, svc=None) -> str:
    """Create (or update in place) the interview's doc -> its link."""
    from googleapiclient.http import MediaIoBaseUpload
    from automations.first_round_scorecards import drive_auth
    svc = svc or drive_auth.service()
    person = _folder(svc, name, drive_auth.AUDIT_FOLDER_ID)
    day = _folder(svc, fathom.start_ct(m).date().isoformat(), person)
    title = doc_name(m, name)
    media = MediaIoBaseUpload(io.BytesIO(build_html(m, name, result).encode("utf-8")),
                              mimetype="text/html", resumable=False)
    q = f"name = '{_q(title)}' and '{day}' in parents and trashed = false"
    existing = svc.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
    if existing:
        fid = existing[0]["id"]
        svc.files().update(fileId=fid, media_body=media).execute()
    else:
        fid = svc.files().create(body={"name": title, "parents": [day], "mimeType": DOC_MIME},
                                 media_body=media, fields="id").execute()["id"]
    return svc.files().get(fileId=fid, fields="webViewLink").execute()["webViewLink"]
