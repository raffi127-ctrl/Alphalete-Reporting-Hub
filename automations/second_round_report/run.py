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
           "bob": "bob status", "orient": "orientation date", "cr": "classroom retention",
           "email": "email", "phone": "phone #"}
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
                     "ns_showed": g("cr") == "Showed To CR",
                     "email": g("email").lower(), "phone": re.sub(r"\D", "", g("phone"))[-10:]})
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
td.asc { font-size: 13px; white-space: nowrap; }
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


def render_week(s: Dict, cards_only: bool = False) -> str:
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
    if cards_only:
        return _doc("<div class='band'><h1>2ND ROUND INTERVIEWS <span>&middot; AT&amp;T vs VERIZON</span></h1>"
                    "<div class='wk'>Week of %s – %s</div></div><div class='sub1'>So far this week: %s. "
                    "Accepted = accepted, orientation booked.</div><div class='cards'>%s%s%s</div>"
                    % (s["lo"].strftime("%b %-d"), s["hi"].strftime("%b %-d, %Y"), span,
                       _card("OFFICE", T, None, "tot", ""), _card("AT&amp;T", s["AT&T"], None, "att", ATT_LOGO),
                       _card("VERIZON", s["Verizon"], None, "vz", VZ_LOGO)))
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


def render_weeks(weeks: List[Dict], tot: Dict, through: dt.date, cards_only: bool = False) -> str:
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

    if cards_only:
        return _doc("<div class='band'><h1>2ND ROUNDS &amp; NEW STARTS <span>&middot; AT&amp;T vs VERIZON</span></h1>"
                    "<div class='wk'>%s – %s</div></div><div class='sub1'>Last %d weeks through %s. "
                    "Closing %% = accepted &divide; 2nd rounds conducted. New starts = orientation; showed = showed to "
                    "classroom.</div><div class='cards'>%s%s%s</div>"
                    % (weeks[0]["lo"].strftime("%b %-d"), through.strftime("%b %-d, %Y"), len(weeks), _md(through),
                       _card("OFFICE", tot["total"], tot["ns_total"], "tot", ""),
                       _card("AT&amp;T", tot["AT&T"], tot["ns_AT&T"], "att", ATT_LOGO),
                       _card("VERIZON", tot["Verizon"], tot["ns_Verizon"], "vz", VZ_LOGO)))
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


# ------------------------------------------------------ by leader -----

def _clean_who(v: str) -> str:
    v = " ".join((v or "").split())
    v = re.sub(r"^SELECT=", "", v, flags=re.I).strip()
    return "" if v.lower() in ("", "none", "select", "-", "--") else v


def same_leader(a: str, b: str, rosters) -> bool:
    """Two spellings of one interviewer (board name, nickname, middle names)."""
    if not a or not b:
        return False
    ta, tb = team_of(a, rosters), team_of(b, rosters)
    if ta[1] and tb[1]:
        return ta[1] == tb[1]
    x, y = toks(a), toks(b)
    return bool(x and y) and NICK.get(x[0], x[0]) == NICK.get(y[0], y[0]) and x[-1] == y[-1]


def is_carlos(who: str) -> bool:
    return "carloshidalgo" in re.sub(r"[^a-z]", "", (who or "").lower())


def _as_people(as_rows: List[Dict], label: str, lo: dt.date, hi: dt.date) -> List[Dict]:
    from automations.second_round_report.appstream_people import digits, loose
    out = []
    for x in as_rows:
        if x.get("Row") != label:
            continue
        try:
            d = dt.date.fromisoformat(x.get("Day", ""))
        except ValueError:
            continue
        if lo <= d <= hi:
            name = ("%s %s" % (x.get("First", ""), x.get("Last", ""))).strip()
            out.append({"day": d, "name": name, "key": loose(name), "email": (x.get("Email") or "").strip().lower(),
                        "phone": digits(x.get("Phone", "")), "who2": _clean_who(x.get("Done By 2nd", ""))})
    return out


def _match(r: Dict, people: List[Dict], same_day: bool = True) -> Optional[Dict]:
    from automations.second_round_report.appstream_people import loose
    k = loose(r["cand"])
    for p in people:
        if same_day and p["day"] != r.get("date2"):
            continue
        if (k and p["key"] == k) or (r.get("email") and p["email"] == r["email"]) or \
                (r.get("phone") and len(r["phone"]) >= 7 and p["phone"] == r["phone"]):
            return p
    return None


def leaders_summary(rows: List[Dict], lo: dt.date, hi: dt.date, as_rows: List[Dict], rosters) -> Dict:
    seconds = [r for r in rows if r["showed"] and in_range(r["date2"], lo, hi)]
    starts = [r for r in rows if in_range(r["orient"], lo, hi)]
    shown = _as_people(as_rows, "Second Interviews Showed Up", lo, hi)
    total = _as_people(as_rows, "Total Second Interviews", lo, hi)
    have_as = bool(shown or total)
    checks = []
    for r in seconds:
        p = _match(r, shown) if shown else None
        t = _match(r, total)
        who = (p or {}).get("who2") or (t or {}).get("who2") or ""
        if not (p or t):
            kind = "not found"
        elif not who:
            kind = "blank"
        elif same_leader(who, r["who"], rosters) or (r["shown"] and same_leader(who, r["shown"], rosters)):
            kind = "same"
        elif is_carlos(who):
            kind = "carlos"
        else:
            kind = "other"
        r["as_who"], r["as_kind"] = who, kind
        checks.append(r)
    leaders: Dict[Tuple[str, str], Dict] = {}
    for r in seconds:
        leaders.setdefault((r["team"] or "", r["shown"]), {"sec": [], "ns": []})["sec"].append(r)
    for r in starts:
        leaders.setdefault((r["team"] or "", r["shown"]), {"sec": [], "ns": []})["ns"].append(r)
    out = {"lo": lo, "hi": hi, "have_as": have_as, "teams": {}}
    for team in TEAMS + ("",):
        ls = []
        for (tm, name), v in leaders.items():
            if tm != team:
                continue
            kinds = {}
            for r in v["sec"]:
                kinds[r.get("as_kind", "")] = kinds.get(r.get("as_kind", ""), 0) + 1
            ls.append((name, second_block(v["sec"]), ns_block(v["ns"]), kinds))
        ls.sort(key=lambda t: (-t[1]["conducted"], -t[1]["accepted"], t[0]))
        tr = [r for r in seconds if (r["team"] or "") == team]
        ts = [r for r in starts if (r["team"] or "") == team]
        out["teams"][team or "none"] = {"leaders": ls, "total": second_block(tr), "ns": ns_block(ts)}
    out["others"] = [r for r in checks if r.get("as_kind") == "other"]
    out["kinds"] = {}
    for r in checks:
        out["kinds"][r["as_kind"]] = out["kinds"].get(r["as_kind"], 0) + 1
    # person-level: who is on one list and not the other, over the whole period
    diffs = []
    for label, du_rows in (("Second Interviews Showed Up", seconds),
                           ("Offered Job From Second Round", [r for r in seconds if r["offered"]]),
                           ("Brought on Board Booked", [r for r in seconds if r["accepted"]]),
                           ("Total New Starts Scheduled", starts),
                           ("New Starts Showed Up", [r for r in starts if r["ns_showed"]])):
        ppl = _as_people(as_rows, label, lo, hi)
        if not ppl:
            continue
        only_as = [p["name"] for p in ppl if not any(_match(r, [p], same_day=False) for r in du_rows)]
        only_du = [r["cand"] for r in du_rows if not _match(r, ppl, same_day=False)]
        diffs.append((label, len(ppl), len(du_rows), only_as, only_du))
    out["diffs"] = diffs
    return out


def _as_cell(kinds: Dict[str, int], have_as: bool) -> str:
    if not have_as:
        return "<td>—</td>"
    parts = []
    if kinds.get("same"):
        parts.append("&#10003; %d" % kinds["same"])
    if kinds.get("carlos"):
        parts.append("Carlos %d" % kinds["carlos"])
    if kinds.get("other"):
        parts.append("<b>&ne; %d</b>" % kinds["other"])
    if kinds.get("blank"):
        parts.append("blank %d" % kinds["blank"])
    if kinds.get("not found"):
        parts.append("not found %d" % kinds["not found"])
    return "<td class='asc'>%s</td>" % (" &middot; ".join(parts) or "—")


def render_leaders(L: Dict, through: dt.date, weeks: int) -> str:
    """The by-leader picture: the AT&T and Verizon tables only. Carlos 11/20,
    on the AppStream notes box under them: "Remove this bottom section." -- the
    done-by detail (who AppStream names instead, who is on one list only) is in
    the run log, not the picture."""
    show_as = L["have_as"]
    def table(team, cls):
        T = L["teams"].get(team) or {"leaders": [], "total": second_block([]), "ns": ns_block([])}
        rows = ""
        for name, b, n, kinds in T["leaders"]:
            rows += ("<tr><td class='nm'>%s</td><td>%d</td><td>%d</td><td>%d</td><td class='pc'>%s</td>"
                     "<td>%d</td><td>%d</td><td class='pc'>%s</td>%s</tr>"
                     % (html.escape(name), b["conducted"], b["offered"], b["accepted"],
                        pct(b["close_pct"]) if b["conducted"] else "—", n["scheduled"], n["showed"],
                        pct(n["show_pct"]) if n["scheduled"] else "—",
                        _as_cell(kinds, True) if show_as else ""))
        b, n = T["total"], T["ns"]
        rows += ("<tr class='tot'><td class='nm'>%s total</td><td>%d</td><td>%d</td><td>%d</td><td class='pc'>%s</td>"
                 "<td>%d</td><td>%d</td><td class='pc'>%s</td>%s</tr>"
                 % (team, b["conducted"], b["offered"], b["accepted"], pct(b["close_pct"]),
                    n["scheduled"], n["showed"], pct(n["show_pct"]), "<td></td>" if show_as else ""))
        return ("<table class='%s'><tr class='th'><th class='nm'>%s leader</th><th>2nd rounds<br>conducted</th>"
                "<th>Offered</th><th>Accepted</th><th>Closing %%</th><th>New starts<br>scheduled</th>"
                "<th>New starts<br>showed</th><th>NS show %%</th>%s</tr>%s</table>"
                % (cls, team, "<th>AppStream<br>done by</th>" if show_as else "", rows))
    body = ("<div class='band'><h1>BY LEADER <span>&middot; 2ND ROUNDS &amp; NEW STARTS</span></h1>"
            "<div class='wk'>%s – %s</div></div>"
            "<div class='sub1'>Last %d weeks through %s, by the leader who did the 2nd round on the Daily Update. "
            "New starts count for the leader who did their 2nd round. Accepted = BOB.</div>"
            "<div class='stack'>%s%s</div>"
            % (L["lo"].strftime("%b %-d"), through.strftime("%b %-d, %Y"), weeks, _md(through),
               table("AT&T", "att"), table("Verizon", "vz")))
    return _doc(body)


# ------------------------------------------------------ the text -----

TEXT_CAMPAIGN = "2ND ROUNDS"
# (picture, chain) -> TEXT_ROUTES kind (b2b_dispositions.config). One kind per
# chain, so each chain texts once a day on its own: Carlos 11/20, "Send daily in
# the morning on the Aplayers and leaders text chain" -- then "On the A Players
# you can send now. Leaders you can send at 9am".
CHAINS = ("aplayers", "leaders")        # NEW A Players, ATT B2B Leaders
TEXT_KINDS = {("cards", "aplayers"): "second_rounds_cards",
              ("leaders", "aplayers"): "second_rounds_leaders_ap",
              ("leaders", "leaders"): "second_rounds_leaders_att"}
TEXT_STATE = Path.home() / ".config" / "recruiting-report" / "second_round_text_state.json"


def _text_state() -> Dict[str, str]:
    import json
    try:
        return json.loads(TEXT_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def queue_text(png: Path, title: str, key: str, kind: str, now: dt.datetime, force: bool = False) -> bool:
    """Text the picture through the local text outbox to the groups routed for
    ("2ND ROUNDS", kind), once per `key`."""
    import json
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import text_outbox as tob
    state = _text_state()
    if state.get(key) and not force:
        _log("text %s already sent at %s -- not again (--force)" % (key, state[key]))
        return False
    spec = {"kind": kind, "title": title, "by_campaign": {TEXT_CAMPAIGN: [str(png)]}}
    if not tp.spec_has_routes(spec):
        _log("no route for %s/%s in TEXT_ROUTES -- not queued" % (TEXT_CAMPAIGN, kind))
        return False
    day = now.date()
    mp = tp.write_manifest(spec, bd_run.OUTPUT_DIR / day.isoformat(), "%s-%s" % (kind, now.strftime("%H%M")))
    tob.drop(mp, by="second_round_report", day=day.isoformat())
    state[key] = now.isoformat(timespec="seconds")
    TEXT_STATE.parent.mkdir(parents=True, exist_ok=True)
    TEXT_STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    _log("text queued (outbox %s)" % mp.name)
    return True


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

def through_day(arg: Optional[str], today: dt.date) -> dt.date:
    """--through: a date, 'yesterday' (the daily morning text), or today."""
    if not arg or arg == "today":
        return today
    if arg == "yesterday":
        return today - dt.timedelta(days=1)
    return dt.date.fromisoformat(arg)


def week_window(through: dt.date, n_weeks: int) -> Tuple[dt.date, dt.date]:
    """(Monday of `through`'s week, first day of the n Mon-Sun weeks ending with it)."""
    monday = through - dt.timedelta(days=through.weekday())
    return monday, monday - dt.timedelta(days=7 * (n_weeks - 1))


def caught_up_through(rows: List[Dict], appstream: Dict, last: dt.date, max_back: int = 7) -> dt.date:
    """The latest day on or before `last` that is on the Daily Update: its 2nd
    rounds marked Showed are at most one short of AppStream's '2nd Showed' that
    day (a day AppStream shows none counts as there). The Daily Update is typed
    by hand -- its fill was retired 11/3 -- so at 9am yesterday may not be in yet
    (11/20: Thursday had 0 rows, AppStream 11). Steps back at most a week."""
    d = last
    for _ in range(max_back):
        du_n = sum(1 for r in rows if r["showed"] and r["date2"] == d)
        as_n = int((appstream.get(d) or {}).get("s2", 0) or 0)
        if du_n + 1 >= as_n:
            return d
        _log("%s is not on the Daily Update yet (2nd rounds showed: Daily Update %d, AppStream %d) "
             "-- the picture stops the day before" % (d, du_n, as_n))
        d -= dt.timedelta(days=1)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--view", choices=["week", "weeks", "leaders"], default="week")
    ap.add_argument("--weeks", type=int, default=4, help="--view weeks: how many Mon-Sun weeks")
    ap.add_argument("--through", help="YYYY-MM-DD or 'yesterday' (the daily timer), last day counted (default today)")
    ap.add_argument("--out", help="picture path (default output/second_round_report/)")
    ap.add_argument("--dm", metavar="U...", help="Slack-DM the picture to this user (from Lucy)")
    ap.add_argument("--note-to", metavar="U1,U2", help="--view week: the offers note's recipients")
    ap.add_argument("--send-note", action="store_true", help="actually send the note (else print it)")
    ap.add_argument("--cards-only", action="store_true", help="only the top cards (office / AT&T / Verizon)")
    ap.add_argument("--text", action="store_true",
                    help="text the picture, once per chain per day: --cards-only -> NEW A Players; "
                         "--view leaders -> NEW A Players + ATT B2B Leaders")
    ap.add_argument("--to", default=",".join(CHAINS),
                    help="--text: which chains, comma list of aplayers / leaders (default both)")
    ap.add_argument("--force", action="store_true", help="--text: send again")
    ap.add_argument("--only-on", help="YYYY-MM-DD: do nothing unless today is that day (one-shot timers)")
    ap.add_argument("--appstream-pull", action="store_true",
                    help="read AppStream's per-person lists into the '2R AppStream Pull' tab, then stop")
    ap.add_argument("--from", dest="from_", help="--appstream-pull: first day (default 4 weeks back)")
    ap.add_argument("--pull", action="store_true",
                    help="--view leaders: refresh the AppStream pull first (best effort; the report still goes out)")
    a = ap.parse_args(argv)
    if a.only_on and dt.date.today().isoformat() != a.only_on:
        _log("--only-on %s: today is %s -- nothing to do" % (a.only_on, dt.date.today()))
        return 0

    # `asked` keys the once-a-day text; `through` is the last day the picture
    # counts -- for 'yesterday', the last day that is on the Daily Update.
    asked = through_day(a.through, dt.date.today())
    n_weeks = a.weeks if a.view in ("weeks", "leaders") else 1
    through = asked
    monday, first = week_window(through, n_weeks)
    text_key = "%s|%s|%s|%s" % (a.view, a.weeks, asked.isoformat(), "cards" if a.cards_only else "full")
    picture = "leaders" if a.view == "leaders" else ("cards" if a.cards_only else "")
    chains = [c.strip() for c in a.to.split(",") if c.strip()]
    bad = [c for c in chains if c not in CHAINS]
    if bad:
        ap.error("--to: unknown chain(s) %s (use %s)" % (bad, ", ".join(CHAINS)))
    chains = [c for c in chains if (picture, c) in TEXT_KINDS]
    if a.text and not chains:
        _log("--text: this picture has no text chain (cards: aplayers; leaders: aplayers, leaders)")
    sent = _text_state()
    if a.text and chains and not a.force and not a.dm and all(sent.get("%s|%s" % (text_key, c)) for c in chains):
        # the retry timer after a good send: don't walk AppStream again for nothing
        _log("text %s already sent to %s -- nothing to do" % (text_key, ", ".join(chains)))
        return 0
    if a.appstream_pull:
        from automations.second_round_report import appstream_people as AP
        lo = dt.date.fromisoformat(a.from_) if a.from_ else first
        AP.write_tab(AP.pull(lo, through, OFFICE, log=_log), lo, through, log=_log)
        return 0
    sh = _sheet(VANTURA)
    rosters = read_rosters(sh)
    rows = read_du(sh, through.year)
    assign_teams(rows, rosters)
    appstream = read_appstream(first - dt.timedelta(days=7), through)   # a week spare for the step back
    if a.through == "yesterday":
        through = caught_up_through(rows, appstream, asked)
        if through != asked:
            monday, first = week_window(through, n_weeks)
    stamp = through.isoformat()
    _log("rosters: AT&T %d, Verizon %d | Daily Update rows %d | AppStream days %d | %s .. %s"
         % (len(rosters["AT&T"]), len(rosters["Verizon"]), len(rows), len(appstream), first, through))
    unmapped = sorted({(r["who"], r["camp"]) for r in rows if r["showed"] and r["how"] == "campaign"
                       and in_range(r["date2"], first, through)})
    if unmapped:
        _log("interviewers not on a board (team from campaign): %s" % unmapped)

    if a.view == "week":
        s = summarize(rows, monday, through, appstream)
        for team in TEAMS:
            b = s[team]
            _log("%s: conducted %d, offered %d, accepted %d, closing %s"
                 % (team, b["conducted"], b["offered"], b["accepted"], pct(b["close_pct"])))
        _log("AppStream: %s | gaps: %s" % (s["as"], [(str(g["day"]), g["what"], g["appstream"], g["du"]) for g in s["gaps"]]))
        page = render_week(s, cards_only=a.cards_only)
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
    elif a.view == "leaders":
        from automations.second_round_report import appstream_people as AP
        pulled = True
        if a.pull:
            try:
                AP.write_tab(AP.pull(first, through, OFFICE, log=_log), first, through, log=_log)
            except Exception as e:  # noqa: BLE001 -- AppStream down: the Daily Update numbers still go out
                pulled = False
                _log("AppStream pull failed -- %s: %s -- picture goes out without the AppStream column"
                     % (type(e).__name__, str(e).splitlines()[0][:160] if str(e) else ""))
        as_rows = AP.read_tab() if pulled else []
        if as_rows and not AP.covers(as_rows, first, through):
            # an older pull for another window would read as "not found" -- leave the column off
            _log("the '2R AppStream Pull' tab is %s -- not this window (%s .. %s); no AppStream column"
                 % (AP.window(as_rows) or "from before the window was recorded", first, through))
            as_rows = []
        L = leaders_summary(rows, first, through, as_rows, rosters)
        for team in TEAMS:
            for name, b, n, kinds in L["teams"][team]["leaders"]:
                _log("%-8s %-28s 2nd %2d off %2d acc %2d  NS %2d/%2d  AS %s"
                     % (team, name, b["conducted"], b["offered"], b["accepted"], n["scheduled"], n["showed"], kinds))
        _log("AppStream done-by: %s | others: %s" % (L["kinds"], [(r["cand"], str(r["date2"]), r["who"], r["as_who"])
                                                             for r in L["others"]]))
        for d in L["diffs"]:
            _log("diff %s: AS %d DU %d only AS %s only DU %s" % d)
        page = render_leaders(L, through, a.weeks)
        out = Path(a.out) if a.out else OUT_DIR / ("second_rounds_leaders_%dweeks_%s.png" % (a.weeks, stamp))
        caption = ("2nd rounds & new starts by leader — last %d weeks (%s – %s)"
                   % (a.weeks, first.strftime("%b %-d"), through.strftime("%b %-d")))
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
        page = render_weeks(weeks, tot, through, cards_only=a.cards_only)
        out = Path(a.out) if a.out else OUT_DIR / ("second_rounds_%dweeks_%s.png" % (a.weeks, stamp))
        caption = ("2nd rounds & new starts — AT&T vs Verizon, last %d weeks (%s – %s)"
                   % (a.weeks, first.strftime("%b %-d"), through.strftime("%b %-d")))
    if a.cards_only:
        out = out.with_name(out.stem + "_cards.png")
    to_png(page, out)
    _log("picture: %s" % out)
    if a.text:
        for c in chains:
            queue_text(out, caption, "%s|%s" % (text_key, c), TEXT_KINDS[(picture, c)], dt.datetime.now(),
                       force=a.force)
    if a.dm:
        dm_picture(out, a.dm, caption)
        _log("DM'd to %s" % a.dm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
