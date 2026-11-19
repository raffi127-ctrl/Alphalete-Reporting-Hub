# -*- coding: utf-8 -*-
"""What changed in ApplicantStream this week vs last week, for the Vitals tab.

Megan 2026-11-15: "at the bottom of the vital section, we should have like a
what changed this week versus last week. That way we can see what changes
they made. And you can tell them like the trend that correlated it, whether
it improved anything or didn't improve anything."

ApplicantStream keeps no history of its settings, so every card run saves
what the setup pull found (AI Settings, buffers, AI replies, interview
times, text + email templates) as one dated snapshot. The section compares
the newest snapshot with the one from the run before (5+ days older), and
puts the week's vitals next to it: what moved the week the changes landed.
One week moving is a hint, not proof, and the card says so.

History lives at output/setup-history/<office>.json on the machine that
builds the card (Lucy 2 for the Sunday run).
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import datetime as dt
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "output" / "setup-history"
KEEP = 12            # snapshots kept per office
GAP_DAYS = 5         # "last week" = the newest snapshot at least this old


def _e(s):
    return escape(str(s if s is not None else ""), quote=True)


def snapshot(setup):
    """{what: value} for everything the setup tabs show. Parts that weren't
    pulled are left out, so a failed pull never reads as 'removed'."""
    from automations.applicant_stream_card import setup_page as SP
    s = setup or {}
    out = {}
    for label, value, _f in s.get("info") or []:
        out["AI Settings · " + label.split(" (")[0]] = value or ""
    # The row's own label: rows the office's page lacks are skipped
    # (SP.PREFS_IF_PRESENT), so zipping against SP.PREFS would misname them.
    for row in s.get("prefs") or []:
        out["Buffer · " + row[0]] = "" if row[1] is None else str(row[1])
    for name, routing, msg, _f in s.get("replies") or []:
        out["AI reply · " + (name or "")] = "{}: {}".format(
            routing or "(no type)", msg or "")
    if s.get("hours"):
        for label, am, pm, tot in SP.slot_rows(s["hours"]):
            out["Interview slots · " + label] = _plain(
                "{} | {} | {} a day".format(am, pm, tot))
    for sec, state, tpls, _f in s.get("sms") or []:
        out["Text step · " + sec] = state or ""
        for name, body, _t in tpls:
            out["Text template · {} · {}".format(sec, name)] = \
                body or ""
    for sec, state, tpls, _f in s.get("email") or []:
        out["Email step · " + sec] = "{} ({})".format(
            state or "", ", ".join(nm for nm, _b in tpls) or "none saved")
    return out


def _plain(html):
    import re
    return re.sub(r"<[^>]+>", "", html.replace("<br>", " ")).replace(
        "·", "-").strip()


def _path(office):
    return HISTORY / "{}.json".format(office)


def load(office):
    try:
        return json.loads(_path(office).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(office, day, snap):
    """Add today's snapshot (replacing one from the same day)."""
    if not snap:
        return
    hist = load(office)
    hist[day.isoformat()] = snap
    keep = dict(sorted(hist.items())[-KEEP:])
    HISTORY.mkdir(parents=True, exist_ok=True)
    _path(office).write_text(json.dumps(keep, indent=1, ensure_ascii=False),
                             encoding="utf-8")


def compare(hist):
    """(last week's date, this week's date, [(what, before, after)]) or
    (None, newest date, []) when there's nothing old enough to compare."""
    if not hist:
        return None, None, []
    days = sorted(hist)
    now = days[-1]
    cut = dt.date.fromisoformat(now) - dt.timedelta(days=GAP_DAYS)
    older = [d for d in days[:-1] if dt.date.fromisoformat(d) <= cut]
    if not older:
        return None, now, []
    before, after = hist[older[-1]], hist[now]
    # Only things both pulls looked at: a part one pull missed isn't a change.
    parts = {k.split(" · ")[0] for k in before} & \
        {k.split(" · ")[0] for k in after}
    out = []
    for k in sorted(set(before) | set(after)):
        if k.split(" · ")[0] not in parts:
            continue
        b, a = before.get(k), after.get(k)
        if b != a:
            out.append((k, b, a))
    return older[-1], now, out


def _when(iso):
    d = dt.date.fromisoformat(iso)
    return "{}/{}".format(d.month, d.day)


def _moves(vitals):
    """[(label, last week, this week, 'up'|'down'|'steady', pct)] for the two
    newest vitals weeks."""
    from automations.applicant_stream_card import vitals as V
    weeks = (vitals or ([], None))[0]
    if len(weeks) < 2:
        return []
    (_d0, prev), (_d1, cur) = weeks[-2], weeks[-1]
    out = []
    for key, label, pct in V.VITALS:
        a, b = prev.get(key), cur.get(key)
        if a is None or b is None:
            continue
        d = b - a
        way = "steady" if abs(d) < (1 if pct else max(1, 0.03 * abs(a))) \
            else "up" if d > 0 else "down"
        out.append((label, a, b, way, pct))
    return out


def html(hist, vitals):
    """The 'What changed this week' block for the bottom of the Vitals tab."""
    out = ["<h2 class='k'>What changed this week vs last week</h2>"]
    then, now, diffs = compare(hist)
    if now is None:
        out.append("<p class='s'>Nothing saved yet. Each Sunday's card "
                   "saves what ApplicantStream is set to, so changes show up "
                   "from the second week on.</p>")
        return "".join(out)
    if then is None:
        out.append("<p class='s'>We started tracking this office's "
                   "settings and templates on {}. Next week's card shows "
                   "what changed since then.</p>".format(_when(now)))
        return "".join(out)
    if not diffs:
        out.append("<p class='s'>No changes to the AI settings, AI replies, "
                   "interview times or templates between {} and {}.</p>"
                   .format(_when(then), _when(now)))
    else:
        out.append("<p class='s'>{} change{} between {} and {}. Tap one to "
                   "see before and after.</p>".format(
                       len(diffs), "" if len(diffs) == 1 else "s",
                       _when(then), _when(now)))
        out.append("<div class='changes'>")
        for what, b, a in diffs:
            kind = ("Added" if b is None else "Removed" if a is None
                    else "Changed")
            out.append(
                "<details class='chg'><summary><span class='ck {0}'>{1}"
                "</span> {2}</summary><div class='body'>"
                "<p class='lbl'>Before ({3}):</p><div class='says'>{4}</div>"
                "<p class='lbl'>Now ({5}):</p><div class='says'>{6}</div>"
                "</div></details>".format(
                    kind.lower(), kind, _e(what), _when(then),
                    _e(b) if b else "<i class='s'>nothing</i>", _when(now),
                    _e(a) if a else "<i class='s'>nothing</i>"))
        out.append("</div>")
    moves = _moves(vitals)
    if moves:
        out.append("<p class='lbl'><b>How the vitals moved the same week"
                   "</b> (latest week vs the week before):</p><ul class='mv'>")
        for label, a, b, way, pct in moves:
            fmt = (lambda v: "{:.1f}%".format(v)) if pct else \
                (lambda v: "{:,.0f}".format(v))
            out.append("<li><span class='{}'>{}</span> {}: {} → {}</li>"
                       .format(way, {"up": "▲", "down": "▼",
                                     "steady": "→"}[way],
                               _e(label), fmt(a), fmt(b)))
        out.append("</ul>")
        if diffs:
            up = sum(1 for m in moves if m[3] == "up")
            down = sum(1 for m in moves if m[3] == "down")
            verdict = ("Most vitals went up after these changes." if up > down
                       else "Most vitals went down after these changes."
                       if down > up else
                       "The vitals didn't clearly move after these changes.")
            out.append("<p class='s'>{} One week is a hint, not proof: "
                       "check next week's card before deciding a change "
                       "worked.</p>".format(verdict))
    return "".join(out)


CSS = """
.changes details.chg{background:#fff;border:1px solid var(--line);
     border-radius:8px;margin:.3em 0;padding:.35em .6em}
.changes summary{cursor:pointer}
.ck{font-size:.8em;font-weight:bold;padding:.05em .45em;border-radius:5px;
     margin-right:.3em}
.ck.changed{background:#fff3d6;color:#8a5a00}
.ck.added{background:#e3f1e8;color:#156E46}
.ck.removed{background:#fdecea;color:#A8322A}
ul.mv{list-style:none;padding-left:0;margin:.3em 0}
ul.mv li{margin:.15em 0}
"""
