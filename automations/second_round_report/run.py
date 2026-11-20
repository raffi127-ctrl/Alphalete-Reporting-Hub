"""2nd rounds + new starts, AT&T vs Verizon, off the Vantura Daily Update,
checked against AppStream (Carlos 2026-11-19).

Carlos: "On the daily update, you can see all of the second rounds that were
conducted this week. And you can see who conducted them. And then you know if
they're a part of the AT&T team or the Verizon team based off of who conducted
the second round interview ... how many total second round interviews ... how
many were conducted by AT&T, how many we offered the job to, and how many
accepted ... Verizon, same thing ... show both of our closing percentages ...
cross-reference this with what's on applicant stream retention details."
Then: "another report for the last 4 weeks up until Wednesday ... add in new
starts scheduled and new starts showed, and that breakdown by AT&T and Verizon."

    lucy rerun second_round_report                                  # this week so far, picture only
    lucy rerun second_round_report --through 2026-11-18 --dm U046G04P5LG
    lucy rerun second_round_report --view weeks --weeks 4 --through 2026-11-18 --dm U046G04P5LG
    lucy rerun second_round_report --through 2026-11-18 --note-to U046G04P5LG,U06JQ4S1MRA --send-note

Daily Update columns, found by HEADER (never by position): Name, Campaign,
"2nd round Interview Date", "2nd round" (who did it), "2nd show/no show",
Offered (Y/N), "BOB Status" (BOB = accepted + orientation booked; Declined;
LM / Letting us know = waiting; Didn't offer them), Orientation Date (= the new
start day), Classroom Retention ("Showed To CR" = the new start showed).

  conducted   = a 2nd round marked Showed, by 2nd-round date
  closing %   = accepted (BOB) / conducted
  NS scheduled= orientation date in the period; NS showed = Showed To CR
  team        = the 2nd-round INTERVIEWER's team: their name on the NDS
                (AT&T) or Verizon Sales Board roster; no interviewer listed ->
                the candidate's Campaign (NDS / B2B ATT = AT&T, VERIZON).

AppStream = its Retention Details counts for office 11580 (2nd showed, offered,
brought on board, new starts scheduled / showed per day -- the calendar's
numbers), as the funnel board logs them hourly in the recruiting dashboard's
'Daily Log' tab. Compared DAY BY DAY; a day that differs is named, with the
Daily Update rows that most likely explain it.

Read-only on every sheet. Sends only with --dm / --send-note. Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VANTURA = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
FUNNEL = "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA"     # Alphalete Recruiting Dashboard
OFFICE = "11580"                                            # Carlos's AppStream office
TEAMS = ("AT&T", "Verizon")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "second_round_report"

DU_COLS = {"name": "name", "camp": "campaign", "date2": "2nd round interview date",
           "who2": "2nd round", "show2": "2nd show/no show", "offered": "offered",
           "bob": "bob status", "orient": "orientation date", "cr": "classroom retention"}
AS_COLS = {"s2": "2nd Showed", "off": "Job Offered", "bob": "BOB",
           "nss": "NS Scheduled", "nsh": "NS Showed", "b2": "2nd Booked"}
SUFFIX = {"ii", "iii", "iv", "jr", "jr.", "sr", "sr."}
NICK = {"nicholas": "nick", "william": "will"}


def _log(msg: str) -> None:
    print("[2nd] " + msg, flush=True)


def _norm(s) -> str:
    return " ".join(str(s or "").split()).lower()


def pdate(x, year: int) -> Optional[dt.date]:
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", str(x or ""))
    if not m:
        return None
    y = int(m.group(3)) if m.group(3) else year
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def toks(n) -> List[str]:
    return [t for t in re.split(r"\s+", str(n or "").strip().lower()) if t and t not in SUFFIX]


def team_of(name, rosters: Dict[str, List[str]]) -> Tuple[Optional[str], Optional[str]]:
    """(team, board name) for a 2nd-round interviewer. Last name + first name
    (or its nickname: Nicholas/Nick, William/Will) on a board roster; then a
    first name + any other shared name (Brandy Ahumada / Brandy Ahumada Ruiz);
    then a first name that is unique across both boards."""
    t = toks(name)
    if len(t) < 1:
        return None, None
    first, last = NICK.get(t[0], t[0]), t[-1]
    for team in TEAMS:
        for b in rosters.get(team, []):
            bt = toks(b)
            if bt and bt[-1] == last and NICK.get(bt[0], bt[0]) == first:
                return team, b
    for team in TEAMS:
        for b in rosters.get(team, []):
            bt = toks(b)
            if bt and NICK.get(bt[0], bt[0]) == first and any(x in bt for x in t[1:]):
                return team, b
    hits = [(team, b) for team in TEAMS for b in rosters.get(team, []) if toks(b)[:1] == t[:1]]
    return hits[0] if len(hits) == 1 else (None, None)


def campaign_team(camp: str) -> Optional[str]:
    c = _norm(camp)
    return "AT&T" if c in ("nds", "b2b att") else "Verizon" if c == "verizon" else None


# ---------------------------------------------------------------- reads -----

def _sheet(key):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(key)


def read_rosters(sh) -> Dict[str, List[str]]:
    from automations.recruiting_report.fill import _retry
    out = {}
    for team, tab, rng in (("AT&T", "NDS Sales Board", "B5:B40"), ("Verizon", "Verizon Sales Board", "B5:B33")):
        vals = _retry(lambda: sh.worksheet(tab).get(rng))
        names = []
        for r in vals:
            v = (r[0] if r else "").strip()
            low = v.lower()
            # the rep rows come first; the campaign total row ("AT&T NDS" /
            # "Verizon"), "Last Week" and the boxes below it are not people
            if low in ("at&t nds", "verizon", "last week") or "%" in v or low.startswith("teams"):
                break
            if v and len(toks(v)) >= 2:
                names.append(v)
        out[team] = names
    return out


def read_du(sh, year: int) -> List[Dict]:
    from automations.recruiting_report.fill import _retry
    vals = _retry(lambda: sh.worksheet("Daily Update").get("A1:AB6000"))
    hdr = [_norm(h) for h in vals[0]]
    idx = {}
    for k, want in DU_COLS.items():
        if want not in hdr:
            raise RuntimeError("Daily Update has no %r column (headers: %s)" % (want, hdr))
        idx[k] = hdr.index(want)
    rows = []
    for i, r in enumerate(vals[1:], start=2):
        r = list(r) + [""] * (len(hdr) + 1)
        g = lambda k: str(r[idx[k]] or "").strip()
        rows.append({"row": i, "cand": g("name"), "camp": g("camp"), "who": g("who2"),
                     "date2": pdate(g("date2"), year), "orient": pdate(g("orient"), year),
                     "showed": g("show2") == "Showed", "noshow": g("show2") == "No Show",
                     "offered": g("offered").upper() == "Y", "not_offered": g("offered").upper() == "N",
                     "accepted": g("bob").upper() == "BOB", "declined": g("bob").lower() == "declined",
                     "waiting": g("bob").lower() in ("lm", "letting us know"),
                     "ns_showed": g("cr") == "Showed To CR"})
    return rows


def read_appstream(lo: dt.date, hi: dt.date) -> Dict[dt.date, Dict[str, int]]:
    """The funnel board's own credentials (its service account where present,
    else this machine's OAuth token) -- the same reader that writes the tab."""
    from automations.funnel_board.auth import session
    s = session()
    r = None
    for _ in range(3):
        r = s.get("https://sheets.googleapis.com/v4/spreadsheets/%s/values/'Daily Log'!A1:U100000" % FUNNEL,
                  params={"valueRenderOption": "UNFORMATTED_VALUE"}, timeout=180)
        if r.status_code == 200:
            break
    if r is None or r.status_code != 200:
        raise RuntimeError("could not read the funnel board's Daily Log (HTTP %s)" % getattr(r, "status_code", "?"))
    vals = r.json().get("values") or []
    hdr = vals[0]
    ix = {k: hdr.index(h) for k, h in AS_COLS.items()}
    out: Dict[dt.date, Dict[str, int]] = {}
    for r in vals[1:]:
        if len(r) < 5 or not isinstance(r[0], (int, float)) or str(r[3]) != OFFICE:
            continue
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(r[0]))
        if lo <= d <= hi:
            out[d] = {k: int(r[i]) if i < len(r) and isinstance(r[i], (int, float)) else 0
                      for k, i in ix.items()}
    return out


def assign_teams(rows: List[Dict], rosters) -> None:
    for r in rows:
        team, shown = team_of(r["who"], rosters)
        r["how"] = "interviewer"
        if team is None:
            team = campaign_team(r["camp"])
            shown = "(no interviewer listed)" if r["who"] in ("", "?") else r["who"]
            r["how"] = "campaign"
        r["team"], r["shown"] = team, shown


# ----------------------------------------------------------------- math -----

def second_block(rs: List[Dict]) -> Dict:
    n = len(rs)
    o = sum(r["offered"] for r in rs)
    a = sum(r["accepted"] for r in rs)
    return {"conducted": n, "offered": o, "accepted": a,
            "declined": sum(r["declined"] for r in rs), "waiting": sum(r["waiting"] for r in rs),
            "not_offered": sum(r["not_offered"] for r in rs),
            "offer_pct": o / n if n else 0.0, "close_pct": a / n if n else 0.0}


def ns_block(rs: List[Dict]) -> Dict:
    n = len(rs)
    s = sum(r["ns_showed"] for r in rs)
    return {"scheduled": n, "showed": s, "show_pct": s / n if n else 0.0}


def in_range(d, lo, hi) -> bool:
    return d is not None and lo <= d <= hi


def summarize(rows: List[Dict], lo: dt.date, hi: dt.date, appstream: Dict) -> Dict:
    seconds = [r for r in rows if r["showed"] and in_range(r["date2"], lo, hi)]
    starts = [r for r in rows if in_range(r["orient"], lo, hi)]
    out = {"lo": lo, "hi": hi, "total": second_block(seconds), "ns_total": ns_block(starts)}
    for team in TEAMS:
        rs = [r for r in seconds if r["team"] == team]
        out[team] = second_block(rs)
        out["ns_" + team] = ns_block([r for r in starts if r["team"] == team])
        people: Dict[str, List[Dict]] = {}
        for r in rs:
            people.setdefault(r["shown"], []).append(r)
        out[team]["people"] = sorted(((k, second_block(v)) for k, v in people.items()),
                                     key=lambda kv: (-kv[1]["conducted"], -kv[1]["accepted"], kv[0]))
    out["unassigned"] = [r for r in seconds if r["team"] is None]
    out["by_campaign"] = [r for r in seconds if r["how"] == "campaign" and r["team"]]
    showed_names = {r["cand"].lower() for r in seconds}
    out["no_shows"] = len({r["cand"].lower() for r in rows
                           if r["noshow"] and in_range(r["date2"], lo, hi) and r["cand"].lower() not in showed_names})
    out["days"] = sorted({r["date2"] for r in seconds})
    out["as"] = {k: sum(v.get(k, 0) for d, v in appstream.items() if lo <= d <= hi) for k in AS_COLS}
    out["gaps"] = day_gaps(seconds, starts, appstream, lo, hi)
    return out


def day_gaps(seconds, starts, appstream, lo, hi) -> List[Dict]:
    """Days where AppStream and the Daily Update disagree, with the Daily Update
    rows most likely behind each difference."""
    gaps = []
    d = lo
    while d <= hi:
        a = appstream.get(d, {})
        sd = [r for r in seconds if r["date2"] == d]
        nd = [r for r in starts if r["orient"] == d]
        for key, label, du_val, hint in (
                ("s2", "2nd rounds showed", len(sd), []),
                ("off", "offers", sum(r["offered"] for r in sd), [r["cand"] for r in sd if r["not_offered"]]),
                ("bob", "accepted", sum(r["accepted"] for r in sd), []),
                ("nss", "new starts scheduled", len(nd), []),
                ("nsh", "new starts showed", sum(r["ns_showed"] for r in nd), [])):
            av = a.get(key, 0)
            if av != du_val:
                gaps.append({"day": d, "what": label, "appstream": av, "du": du_val,
                             "hint": hint if av > du_val else []})
        d += dt.timedelta(days=1)
    return gaps


def pct(x: float) -> str:
    return "%d%%" % round(100 * x)


def _md(d: dt.date) -> str:
    return "%s %d/%d" % (d.strftime("%a"), d.month, d.day)


def offer_note(s: Dict) -> str:
    """Carlos's one comment for Valeria: the offer count gap and who it is."""
    days = s["days"]
    span = "%s – %s" % (_md(days[0]), _md(days[-1])) if days else "this week"
    a, du = s["as"]["off"], s["total"]["offered"]
    if a == du:
        return "2nd rounds this week (%s): offers match — AppStream %d, Daily Update %d." % (span, a, du)
    lines = ["2nd rounds this week (%s): offers are off by %d — AppStream has %d, the Daily Update has %d."
             % (span, abs(a - du), a, du)]
    for g in s["gaps"]:
        if g["what"] != "offers":
            continue
        if g["hint"] and g["appstream"] > g["du"]:
            names = g["hint"]
            who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
            lines.append("The gap is on %s: one of %s is marked N (not offered) on the Daily Update but "
                         "offered in AppStream." % (_md(g["day"]), who) if len(names) > 1 else
                         "The gap is on %s: %s is marked N (not offered) on the Daily Update but offered in "
                         "AppStream." % (_md(g["day"]), who))
        else:
            lines.append("%s: AppStream %d, Daily Update %d." % (_md(g["day"]), g["appstream"], g["du"]))
    return " ".join(lines)


# --------------------------------------------------------------- render -----

CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #fff; font-family: "Helvetica Neue", Arial, sans-serif; color: #111; }
.wrap { width: 1180px; padding: 0 0 18px; }
.band { background: #000; color: #fff; padding: 18px 28px 16px; display: flex; justify-content: space-between; align-items: baseline; }
.band h1 { margin: 0; font-size: 30px; letter-spacing: .5px; }
.band h1 span { color: #00A8E0; }
.band .wk { font-size: 17px; color: #ddd; }
.sub1 { padding: 10px 28px 0; color: #555; font-size: 14px; }
.cards { display: flex; gap: 16px; padding: 16px 28px 6px; }
.card { flex: 1; border-radius: 10px; padding: 14px 18px 14px; color: #fff; }
.card.tot { background: #2b2b2b; } .card.att { background: #0B3A6E; } .card.vz { background: #B00000; }
.chead { display: flex; align-items: center; gap: 10px; font-size: 22px; font-weight: 700; letter-spacing: .5px; }
.globe { width: 26px; height: 26px; border-radius: 50%; display: inline-block;
         background: repeating-linear-gradient(0deg, #00A8E0 0 4px, #0B3A6E 4px 7px); border: 2px solid #00A8E0; }
.check { font-style: normal; font-size: 24px; color: #fff; }
.big { font-size: 64px; font-weight: 800; line-height: 1; margin-top: 10px; }
.biglbl { font-size: 13px; letter-spacing: 1px; opacity: .9; margin-top: 4px; }
.biglbl em { font-style: normal; opacity: .75; letter-spacing: 0; }
.stats { display: flex; gap: 10px; margin-top: 14px; }
.stats div { flex: 1; background: rgba(255,255,255,.13); border-radius: 8px; padding: 8px 0 7px; text-align: center; }
.stats b { display: block; font-size: 30px; } .stats span { font-size: 13px; opacity: .9; }
.sub { margin-top: 10px; font-size: 12px; opacity: .95; white-space: nowrap; }
.tables { display: flex; gap: 16px; padding: 12px 28px 0; align-items: flex-start; }
.stack { padding: 12px 28px 0; }
.stack table { width: 100%; margin-bottom: 12px; }
table { flex: 1; border-collapse: collapse; font-size: 15px; }
th, td { border: 1px solid #bbb; padding: 6px 8px; text-align: center; }
.nm { text-align: left; }
table.att .th th { background: #0B3A6E; color: #fff; } table.vz .th th { background: #B00000; color: #fff; }
table.chk .th th { background: #3d4a57; color: #fff; }
th.grp { font-size: 13px; letter-spacing: .5px; }
tr.tot td { font-weight: 700; background: #eee; }
td.pc { font-weight: 700; }
td.ok { color: #1b7f3b; font-weight: 700; } td.diff { color: #b25b00; font-weight: 700; }
.foot { margin: 10px 28px 0; padding: 10px 14px; background: #f3f6f9; border-left: 5px solid #00A8E0; font-size: 14px; line-height: 1.55; }
.foot b { color: #0B3A6E; }
"""
ATT_LOGO = "<i class='globe'></i>"
VZ_LOGO = "<i class='check'>&#10003;</i>"


def _doc(body: str) -> str:
    return "<!doctype html><html><head><meta charset='utf-8'><style>%s</style></head><body><div class='wrap'>%s</div></body></html>" % (CSS, body)


def _card(title, b, ns, cls, logo) -> str:
    extra = ""
    if ns is not None:
        extra = ("<div class='stats'><div><b>%d</b><span>New starts sched.</span></div>"
                 "<div><b>%d</b><span>New starts showed</span></div><div><b>%s</b><span>NS show %%</span></div></div>"
                 % (ns["scheduled"], ns["showed"], pct(ns["show_pct"])))
    return ("<div class='card %s'><div class='chead'>%s<span>%s</span></div>"
            "<div class='big'>%s</div><div class='biglbl'>CLOSING %% <em>accepted &divide; conducted</em></div>"
            "<div class='stats'><div><b>%d</b><span>Conducted</span></div><div><b>%d</b><span>Offered</span></div>"
            "<div><b>%d</b><span>Accepted</span></div></div>%s"
            "<div class='sub'>Offer %% <b>%s</b> &nbsp;&middot;&nbsp; Declined <b>%d</b> &nbsp;&middot;&nbsp; "
            "No answer <b>%d</b> &nbsp;&middot;&nbsp; Not offered <b>%d</b></div></div>"
            % (cls, logo, title, pct(b["close_pct"]), b["conducted"], b["offered"], b["accepted"], extra,
               pct(b["offer_pct"]), b["declined"], b["waiting"], b["not_offered"]))


def _cmp(a: int, d: int) -> str:
    return ("<td class='ok'>%d &#10003;</td>" % d) if a == d else ("<td class='diff'>%d vs %d</td>" % (a, d))


def render_week(s: Dict) -> str:
    days = s["days"]
    span = "%s – %s" % (_md(days[0]), _md(days[-1])) if days else "—"

    def table(team, cls):
        b = s[team]
        rows = "".join("<tr><td class='nm'>%s</td><td>%d</td><td>%d</td><td>%d</td><td class='pc'>%s</td></tr>"
                       % (html.escape(n), p["conducted"], p["offered"], p["accepted"], pct(p["close_pct"]))
                       for n, p in b["people"])
        return ("<table class='%s'><tr class='th'><th class='nm'>%s interviewer</th><th>Conducted</th><th>Offered</th>"
                "<th>Accepted</th><th>Closing %%</th></tr>%s<tr class='tot'><td class='nm'>%s total</td><td>%d</td>"
                "<td>%d</td><td>%d</td><td class='pc'>%s</td></tr></table>"
                % (cls, team, rows, team, b["conducted"], b["offered"], b["accepted"], pct(b["close_pct"])))

    a, T = s["as"], s["total"]
    ok = lambda x, y: "&#10003;" if x == y else "&ne;"
    notes = ["%s: no interviewer listed — counted to %s from the campaign." % (html.escape(r["cand"]), r["team"])
             for r in s["by_campaign"]]
    notes += ["%s: no interviewer and no campaign — not in a team." % html.escape(r["cand"]) for r in s["unassigned"]]
    gl = []
    for g in s["gaps"]:
        if g["what"] not in ("2nd rounds showed", "offers", "accepted"):
            continue
        if g["what"] == "offers" and g["hint"]:
            who = ", ".join(html.escape(n) for n in g["hint"])
            gl.append("Offers on %s: AppStream %d, Daily Update %d — one of %s (marked N on the Daily Update) is "
                      "offered in AppStream." % (_md(g["day"]), g["appstream"], g["du"], who))
    body = ("<div class='band'><h1>2ND ROUND INTERVIEWS <span>&middot; AT&amp;T vs VERIZON</span></h1>"
            "<div class='wk'>Week of %s – %s</div></div>"
            "<div class='sub1'>So far this week: interviews held %s (from the Daily Update). Team = who did the 2nd round. "
            "Accepted = BOB (accepted, orientation booked).</div>"
            "<div class='cards'>%s%s%s</div><div class='tables'>%s%s</div>"
            "<div class='foot'><b>Cross-check with AppStream</b> (Retention Details, office %s, same days): showed "
            "<b>%d</b> vs <b>%d</b> %s &nbsp;&middot;&nbsp; offered <b>%d</b> vs <b>%d</b> %s &nbsp;&middot;&nbsp; "
            "brought on board <b>%d</b> vs <b>%d</b> %s &nbsp;(AppStream vs Daily Update). No-shows: %d (not counted)."
            "%s%s</div>"
            % (s["lo"].strftime("%b %-d"), s["hi"].strftime("%b %-d, %Y"), span,
               _card("BOTH TEAMS", T, None, "tot", ""), _card("AT&amp;T", s["AT&T"], None, "att", ATT_LOGO),
               _card("VERIZON", s["Verizon"], None, "vz", VZ_LOGO), table("AT&T", "att"), table("Verizon", "vz"),
               OFFICE, a["s2"], T["conducted"], ok(a["s2"], T["conducted"]), a["off"], T["offered"],
               ok(a["off"], T["offered"]), a["bob"], T["accepted"], ok(a["bob"], T["accepted"]), s["no_shows"],
               "".join("<br>" + x for x in gl), "".join("<br>" + x for x in notes)))
    return _doc(body)


def render_weeks(weeks: List[Dict], tot: Dict, through: dt.date) -> str:
    def team_table(team, cls):
        rows = ""
        for w in weeks:
            b, n = w[team], w["ns_" + team]
            lbl = "%s – %s%s" % (w["lo"].strftime("%b %-d"), w["hi"].strftime("%b %-d"),
                                 " *" if w["partial"] else "")
            rows += ("<tr><td class='nm'>%s</td><td>%d</td><td>%d</td><td>%d</td><td class='pc'>%s</td>"
                     "<td>%d</td><td>%d</td><td class='pc'>%s</td></tr>"
                     % (lbl, b["conducted"], b["offered"], b["accepted"], pct(b["close_pct"]),
                        n["scheduled"], n["showed"], pct(n["show_pct"])))
        b, n = tot[team], tot["ns_" + team]
        rows += ("<tr class='tot'><td class='nm'>4-week total</td><td>%d</td><td>%d</td><td>%d</td><td class='pc'>%s</td>"
                 "<td>%d</td><td>%d</td><td class='pc'>%s</td></tr>"
                 % (b["conducted"], b["offered"], b["accepted"], pct(b["close_pct"]),
                    n["scheduled"], n["showed"], pct(n["show_pct"])))
        return ("<table class='%s'><tr class='th'><th class='nm grp'>%s &mdash; week</th><th>2nd rounds<br>conducted</th>"
                "<th>Offered</th><th>Accepted</th><th>Closing %%</th><th>New starts<br>scheduled</th>"
                "<th>New starts<br>showed</th><th>NS show %%</th></tr>%s</table>" % (cls, team, rows))

    chk = ""
    for w in weeks + [dict(tot, label="4-week total")]:
        a, T, N = w["as"], w["total"], w["ns_total"]
        lbl = w.get("label") or "%s – %s%s" % (w["lo"].strftime("%b %-d"), w["hi"].strftime("%b %-d"),
                                               " *" if w["partial"] else "")
        cls = " class='tot'" if w.get("label") else ""
        chk += ("<tr%s><td class='nm'>%s</td>%s%s%s%s%s</tr>"
                % (cls, lbl, _cmp(a["s2"], T["conducted"]), _cmp(a["off"], T["offered"]), _cmp(a["bob"], T["accepted"]),
                   _cmp(a["nss"], N["scheduled"]), _cmp(a["nsh"], N["showed"])))
    check = ("<table class='chk'><tr class='th'><th class='nm'>AppStream vs Daily Update</th><th>2nd rounds showed</th>"
             "<th>Offered</th><th>Accepted (BOB)</th><th>New starts scheduled</th><th>New starts showed</th></tr>%s</table>"
             % chk)
    gaps = [g for w in weeks for g in w["gaps"]]
    gl = []
    for g in gaps:
        if g["what"] == "offers" and g["hint"]:
            gl.append("%s offers: AppStream %d, Daily Update %d — %s marked N on the Daily Update."
                      % (_md(g["day"]), g["appstream"], g["du"], ", ".join(html.escape(n) for n in g["hint"])))
        elif g["what"] in ("new starts scheduled", "new starts showed"):
            more = "AppStream" if g["appstream"] > g["du"] else "the Daily Update"
            gl.append("%s %s: AppStream %d, Daily Update %d — %d more on %s (a start missing from the other, "
                      "or booked for a different day)." % (_md(g["day"]), g["what"], g["appstream"], g["du"],
                                                          abs(g["appstream"] - g["du"]), more))
    notes = ["&#10003; = same number in both. &nbsp;\"A vs B\" = AppStream A, Daily Update B. Accepted can land a day "
             "later in AppStream (it counts the day the start was booked); a status changed after booking "
             "(BOB &rarr; Declined) still counts there."]
    by_campaign = [r for w in weeks for r in w["by_campaign"]]
    if by_campaign:
        notes.append("No interviewer listed (counted by campaign): %s."
                     % ", ".join("%s (%s)" % (html.escape(r["cand"]), r["team"]) for r in by_campaign))
    body = ("<div class='band'><h1>2ND ROUNDS &amp; NEW STARTS <span>&middot; AT&amp;T vs VERIZON</span></h1>"
            "<div class='wk'>%s – %s</div></div>"
            "<div class='sub1'>Last %d weeks through %s (from the Daily Update). * = this week, Mon–%s only. "
            "Team = who did the 2nd round. Accepted = BOB. New starts = orientation date; showed = Showed To CR.</div>"
            "<div class='cards'>%s%s%s</div><div class='stack'>%s%s%s</div>"
            "<div class='foot'>%s%s</div>"
            % (weeks[0]["lo"].strftime("%b %-d"), through.strftime("%b %-d, %Y"), len(weeks), _md(through),
               through.strftime("%a"),
               _card("BOTH TEAMS", tot["total"], tot["ns_total"], "tot", ""),
               _card("AT&amp;T", tot["AT&T"], tot["ns_AT&T"], "att", ATT_LOGO),
               _card("VERIZON", tot["Verizon"], tot["ns_Verizon"], "vz", VZ_LOGO),
               team_table("AT&T", "att"), team_table("Verizon", "vz"), check,
               "<br>".join(notes), "".join("<br>" + x for x in gl)))
    return _doc(body)


def to_png(html_text: str, out: Path) -> Path:
    from playwright.sync_api import sync_playwright
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:  # noqa: BLE001 -- no Chrome: the bundled Chromium
            b = p.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": 1180, "height": 900}, device_scale_factor=2)
            pg.set_content(html_text, wait_until="load")
            pg.locator(".wrap").screenshot(path=str(out))
        finally:
            b.close()
    return out


# ----------------------------------------------------------------- send -----

def dm_picture(png: Path, user: str, comment: str) -> None:
    from automations.shared import slack_metrics_post as smp
    smp.dm_user_with_file(png, user=user, comment=comment, file_name=png.name)


def group_text(users: List[str], text: str) -> str:
    """One group DM from Lucy to these users; individual DMs if the group can't
    be opened (no mpim:write)."""
    from automations.shared import slack_metrics_post as smp
    client = smp._bot_client()
    ids = [smp._resolve_user_id(client, u) for u in users]
    try:
        ch = client.conversations_open(users=",".join(ids))["channel"]["id"]
        client.chat_postMessage(channel=ch, text=text)
        return "group DM %s" % ch
    except Exception as e:  # noqa: BLE001
        _log("group DM unavailable (%s: %s) -- individual DMs" % (type(e).__name__, str(e)[:120]))
        for uid in ids:
            ch = client.conversations_open(users=uid)["channel"]["id"]
            client.chat_postMessage(channel=ch, text=text)
        return "individual DMs to %s" % ", ".join(ids)


# ----------------------------------------------------------------- main -----

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--view", choices=["week", "weeks"], default="week")
    ap.add_argument("--weeks", type=int, default=4, help="--view weeks: how many Mon-Sun weeks")
    ap.add_argument("--through", help="YYYY-MM-DD, last day counted (default today)")
    ap.add_argument("--out", help="picture path (default output/second_round_report/)")
    ap.add_argument("--dm", metavar="U...", help="Slack-DM the picture to this user (from Lucy)")
    ap.add_argument("--note-to", metavar="U1,U2", help="--view week: the offers note's recipients")
    ap.add_argument("--send-note", action="store_true", help="actually send the note (else print it)")
    a = ap.parse_args(argv)

    through = dt.date.fromisoformat(a.through) if a.through else dt.date.today()
    monday = through - dt.timedelta(days=through.weekday())
    first = monday - dt.timedelta(days=7 * ((a.weeks if a.view == "weeks" else 1) - 1))
    sh = _sheet(VANTURA)
    rosters = read_rosters(sh)
    rows = read_du(sh, through.year)
    assign_teams(rows, rosters)
    appstream = read_appstream(first, through)
    _log("rosters: AT&T %d, Verizon %d | Daily Update rows %d | AppStream days %d"
         % (len(rosters["AT&T"]), len(rosters["Verizon"]), len(rows), len(appstream)))
    unmapped = sorted({(r["who"], r["camp"]) for r in rows if r["showed"] and r["how"] == "campaign"
                       and in_range(r["date2"], first, through)})
    if unmapped:
        _log("interviewers not on a board (team from campaign): %s" % unmapped)

    stamp = through.isoformat()
    if a.view == "week":
        s = summarize(rows, monday, through, appstream)
        for team in TEAMS:
            b = s[team]
            _log("%s: conducted %d, offered %d, accepted %d, closing %s"
                 % (team, b["conducted"], b["offered"], b["accepted"], pct(b["close_pct"])))
        _log("AppStream: %s | gaps: %s" % (s["as"], [(str(g["day"]), g["what"], g["appstream"], g["du"]) for g in s["gaps"]]))
        page = render_week(s)
        out = Path(a.out) if a.out else OUT_DIR / ("second_rounds_week_%s.png" % stamp)
        caption = ("2nd round interviews — AT&T vs Verizon, week of %s (so far: %s)"
                   % (monday.strftime("%b %-d"), ", ".join(_md(d) for d in s["days"]) or "none yet"))
        note = offer_note(s)
        _log("note: " + note)
        if a.note_to:
            users = [u.strip() for u in a.note_to.split(",") if u.strip()]
            if a.send_note:
                _log("note sent: " + group_text(users, note))
            else:
                _log("note NOT sent (pass --send-note) -- would go to %s" % users)
    else:
        weeks = []
        for k in range(a.weeks):
            lo = first + dt.timedelta(days=7 * k)
            hi = min(lo + dt.timedelta(days=6), through)
            w = summarize(rows, lo, hi, appstream)
            w["partial"] = hi < lo + dt.timedelta(days=6)
            weeks.append(w)
            _log("%s..%s  AT&T %s  VZ %s  NS AT&T %s  NS VZ %s  AS %s"
                 % (lo, hi, {k2: w["AT&T"][k2] for k2 in ("conducted", "offered", "accepted")},
                    {k2: w["Verizon"][k2] for k2 in ("conducted", "offered", "accepted")},
                    w["ns_AT&T"], w["ns_Verizon"], w["as"]))
        tot = summarize(rows, first, through, appstream)
        page = render_weeks(weeks, tot, through)
        out = Path(a.out) if a.out else OUT_DIR / ("second_rounds_%dweeks_%s.png" % (a.weeks, stamp))
        caption = ("2nd rounds & new starts — AT&T vs Verizon, last %d weeks (%s – %s)"
                   % (a.weeks, first.strftime("%b %-d"), through.strftime("%b %-d")))
    to_png(page, out)
    _log("picture: %s" % out)
    if a.dm:
        dm_picture(out, a.dm, caption)
        _log("DM'd to %s" % a.dm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
