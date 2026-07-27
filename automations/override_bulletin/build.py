"""Org Override Bulletin — branded weekly bulletin (VA-replacement Item 2).

Replaces the VA's hand-built BeeFree email + screenshot. We RENDER our own
black/gold Alphalete bulletin from the live override data, so there's nothing to
paste into an email designer each Friday.

SOURCE: the 'Org Overrides Ongoing Report' tab (gid 653029315) of the Org/
Captainship workbook. Each active ICD's weekly override sits in a dated column;
the '2026 total' is column D. We show the seven org leaders (the ones we have
headshots for), ranked by their 2026 override total, with this week's figure.

OUTPUT: a self-contained HTML file (assets embedded as data URIs) that doubles
as both the emailable body and the source for the Slack PNG. This module only
BUILDS the file — rendering it to PNG and posting are separate steps, so nothing
goes out by running this.

The weekly NUMBERS are still entered upstream (Credico + captain/special) — this
reads whatever the sheet currently holds. Build after the sheet is filled.
"""
from __future__ import annotations

import base64
import datetime as dt
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HEADSHOTS = REPO / "resources" / "leader-headshots" / "processed"
LOGO = REPO / "resources" / "alphalete-logo-hq.png"
OUT_DIR = REPO / "output" / "override_bulletin"

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
TAB = "Org Overrides Ongoing Report"

# The seven org leaders we render. `match` is a case-insensitive substring test
# against the sheet's column-A label (names there carry stray spaces / middle
# names, so we don't hardcode the exact string). `file` is the processed
# circular headshot. Order here is irrelevant — the bulletin ranks by 2026 total.
LEADERS = [
    {"name": "Rafael Hidalgo",  "match": "rafael hidalgo",  "file": "rafael-hidalgo.png", "loc": "Dallas, TX"},
    {"name": "Colten Wright",   "match": "colten wright",   "file": "colten-wright.png",  "loc": "Miami, FL"},
    {"name": "Carlos Hidalgo",  "match": "carlos hidalgo",  "file": "carlos-hidalgo.png", "loc": "Dallas, TX"},
    {"name": "Jairo Ruiz",      "match": "jairo ruiz",      "file": "jairo-ruiz.png",     "loc": "Doral, FL"},
    {"name": "Khalil Mansour",  "match": "khalil mansour",  "file": "khalil-mansour.png", "loc": "Dallas, TX"},
    {"name": "Eveliz Wright",   "match": "eveliz wright",   "file": "eveliz-wright.png",  "loc": "Miami, FL"},
    # "hammad" alone is a substring of "muHAMMAD", so it wrongly matched Salik's
    # row too — anchor on the unique "ul haque".
    {"name": "Muhammad Hammad", "match": "hammad ul",       "file": "hammad-haque.png",   "loc": "Detroit, MI"},
    {"name": "Muhammad Salik",  "match": "salik",           "file": "salik-mallick.png",  "loc": "Detroit, MI"},
    {"name": "Benjamin Burden", "match": "burden",          "file": "ben-burden.png",     "loc": "Houston, TX"},
    {"name": "Ryan McSpadden",  "match": "mcspadden",       "file": "ryan-mcspadden.png", "loc": "Irving, TX"},
    {"name": "Roshan Ahmad",    "match": "roshan",          "file": "roshan-ahmad.png",   "loc": ""},
    {"name": "Joseph Delgado",     "match": "joseph delgado",   "file": "joseph-delgado.png",     "loc": ""},
    {"name": "Nicolas Murrugarra", "match": "nicolas murr",     "file": "nicolas-murrugarra.png", "loc": ""},
    {"name": "Amjad Malhas",       "match": "malhas",           "file": "amjad-malhas.png",       "loc": ""},
    {"name": "Boaktear Chowhury",  "match": "chowhury",         "file": "boaktear-chowhury.png",  "loc": ""},
]

# How many recent weeks to show in the tables + card sparklines (Megan 2026-07-22:
# "just want the last 4 weeks").
WOW_WEEKS = 5

# Prior years to show (Megan: "and then the last 3 years"). Their COLUMN positions
# are found by header label at read time, never hardcoded — the fill inserts a new
# week column each Friday, which shifts these year totals right (rule: derive
# positions, don't hardcode indices).
YEARS = ["2025", "2024", "2023"]
_YEAR_HDR_RE = re.compile(r"total overrides\s+(\d{4})", re.I)

GOLD = "#C9A24B"
GOLD_LT = "#E7CE86"

# Distro email goes to two contact groups on alphaletereporting@gmail.com
# (resolved by name via automations.shared.contacts_auth at send time).
EMAIL_FROM = "alphaletereporting@gmail.com"
EMAIL_GROUPS = ["Alphalete Org Owners", "Bulletins"]
# Slack targets for the posted image (VA sent to both).
SLACK_CHANNELS = ["#alphalete-sales", "#rafs-office-recruiting"]


def email_subject(week_label: str) -> str:
    """Distro-email subject (Megan 2026-07-22): 'Alphalete Organization Override
    Bulletin WE 7.12' — WE = week ending, month.day of the newest week (the sheet
    label is m.d.yy; the year is dropped)."""
    md = ".".join(week_label.split(".")[:2]) if week_label else ""
    return f"Alphalete Organization Override Bulletin WE {md}"


def _b64(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _money(raw: str):
    """'$78,595.49' -> 78595.49, or None if blank/unparseable."""
    if not raw:
        return None
    try:
        return float(raw.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _fmt(n) -> str:
    return "—" if n is None else f"${n:,.0f}"



_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")


def _week_cols(header):
    """The CONTIGUOUS run of dated columns starting just after 'Total Overrides
    2026' (col E). Not a blanket scan: the tab is 192 cols wide and carries a
    large HISTORICAL weekly block far to the right (~185 dated cols); a global
    regex match pulls those in and everyone looks active. Stop at the first
    non-week header (e.g. 'Total Overrides 2025')."""
    cols, started = [], False
    for i, h in enumerate(header):
        if _WEEK_RE.match(h.strip()):
            cols.append((i, h.strip()))
            started = True
        elif started:
            break
    return cols


def _year_cols(header):
    """{'2025': col_idx, ...} located by 'Total Overrides YYYY' header labels —
    so a week-column insert (which shifts these right) can't misalign them."""
    out = {}
    for i, h in enumerate(header):
        m = _YEAR_HDR_RE.search((h or "").strip())
        if m:
            out[m.group(1)] = i
    return out


def _mk_row(r, week_cols, year_cols, led):
    series = [_money(r[i]) if i < len(r) else None for i, _lbl in week_cols]
    # Total 2026 = the sum of the 2026 weekly columns, computed here rather than
    # read from the sheet's col-D formula. Col D is =SUM(E:AF) for the good rows
    # (so this matches), but a few sub-rows carry a broken range (Eveliz's Captain
    # Override is =SUM(E:CG), pulling in prior years) — summing the 2026 weeks
    # ourselves keeps every category consistent so Combined = Regular + Captainship
    # + Program and Regular never goes negative.
    total = round(sum(v or 0 for v in series), 2) if any(v is not None for v in series) else None
    return {
        "name": led["name"] if led else (r[0] or "").strip(),
        "led": led,
        "total": total,
        "series": series,
        "week": series[0] if series else None,
        "years": {yr: (_money(r[i]) if i < len(r) else None)
                  for yr, i in year_cols.items()},
    }


def read_data(tab=None):
    """Return (week_labels, combined, regular, captainship, program).

    `tab` overrides the source tab so a build can preview off the SANDBOX copy.

    Raf 2026-07-25: break the overrides into the three categories his org uses,
    plus the combined total — four stacked sections:
      combined    = ALL ORG OVERRIDES — everyone's total override (all 3 combined).
      regular     = the base override (1st Gen / RC / NC) = combined − captainship
                    − program, per person.
      captainship = the 'Captain Override' rows (the captain bonus).
      program     = the 'Special Override' rows — the program-specific override
                    that not everyone gets (only Rafael / Carlos / Colten).
    Each row carries `led`, total, series (weekly), week, years (2025/24/23)."""
    from automations.recruiting_report import fill as _fill
    ws = _fill._client().open_by_key(WORKBOOK_ID).worksheet(tab or TAB)
    vals = ws.get_all_values()
    week_cols = _week_cols(vals[0])
    year_cols = _year_cols(vals[0])
    week_labels = [lbl for _i, lbl in week_cols]

    def led_for(low):
        return next((l for l in LEADERS if l["match"] in low), None)

    # --- COMBINED: ALL ORG OVERRIDES (everyone's total override) ---------------
    combined, cap_start = [], None
    for ri, r in enumerate(vals[1:], start=1):
        name = (r[0] if r else "").strip()
        low = name.lower()
        if "captain/special" in low:            # section-2 header — remember + stop
            cap_start = ri + 1
            break
        if low == "total" or "credico" in low or not name:
            continue
        row = _mk_row(r, week_cols, year_cols, led_for(low))
        # Keep an ICD unless they've had $0 for the last 4 weeks IN A ROW (Megan
        # 2026-07-25). The old rule dropped anyone with $0 THIS week, which hid
        # people like Ryan McSpadden ($0 in 7.19 but active the weeks before);
        # this keeps anyone with activity in the recent window and drops only
        # those who've genuinely gone quiet.
        if any((v or 0) > 0 for v in row["series"][:4]):
            combined.append(row)
    combined.sort(key=lambda x: (x["total"] or 0), reverse=True)

    # --- CAPTAINSHIP + PROGRAM: the sub-rows under each section-2 leader -------
    cap_by, prog_by, leader_name = {}, {}, {}    # normalized leader name -> row
    if cap_start:
        cur = None
        for i in range(cap_start, len(vals)):
            name = (vals[i][0] if vals[i] else "").strip()
            low = name.lower()
            if not name:
                break                            # blank row ends the section
            if low == "captain override":
                if cur:
                    cap_by[cur] = _mk_row(vals[i], week_cols, year_cols, led_for(cur))
            elif low in ("special override", "special overrides"):
                if cur:
                    prog_by[cur] = _mk_row(vals[i], week_cols, year_cols, led_for(cur))
            else:                                # a leader name row
                cur = low
                leader_name[cur] = name

    def _named(by):
        out = []
        for key, row in by.items():
            row = dict(row)
            row["name"] = leader_name.get(key, row["name"])
            row["led"] = led_for(key)
            if (row["total"] or 0) > 0:
                out.append(row)
        out.sort(key=lambda x: (x["total"] or 0), reverse=True)
        return out
    captainship, program = _named(cap_by), _named(prog_by)

    # --- REGULAR = combined − captainship − program, per person/week ----------
    def _val(src, key, i=None, yr=None):
        if not src:
            return 0
        if i is not None:
            s = src["series"]
            return (s[i] or 0) if i < len(s) else 0
        if yr is not None:
            return src["years"].get(yr) or 0
        return src["total"] or 0
    regular = []
    for row in combined:
        key = row["name"].strip().lower()
        cap, prog = cap_by.get(key), prog_by.get(key)
        reg = dict(row)
        reg["series"] = [(row["series"][i] or 0) - _val(cap, "s", i=i) - _val(prog, "s", i=i)
                         for i in range(len(row["series"]))]
        reg["week"] = reg["series"][0] if reg["series"] else None
        reg["total"] = (row["total"] or 0) - _val(cap, "t") - _val(prog, "t")
        reg["years"] = {y: (v or 0) - _val(cap, "y", yr=y) - _val(prog, "y", yr=y)
                        for y, v in row["years"].items()}
        regular.append(reg)

    return week_labels, combined, regular, captainship, program


def _delta(row):
    """(arrow, text, css_class) for this week vs prior week, or None if no prior."""
    s = row.get("series") or []
    if len(s) < 2 or s[0] is None or s[1] is None:
        return None
    d = s[0] - s[1]
    if abs(d) < 0.5:
        return ("→", "flat", "flat")
    up = d > 0
    return ("▲" if up else "▼", f"{'+' if up else '−'}${abs(d):,.0f}",
            "up" if up else "down")


def _spark(series, w=120, h=26):
    """Tiny inline-SVG sparkline of the last WOW_WEEKS, oldest→newest."""
    pts = [v or 0 for v in reversed(series[:WOW_WEEKS])]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    step = w / (len(pts) - 1)
    coords = [(i * step, h - 3 - (v - lo) / rng * (h - 6)) for i, v in enumerate(pts)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    cx, cy = coords[-1]
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline points="{line}" fill="none" stroke="{GOLD}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.6" fill="{GOLD_LT}"/></svg>')


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper()


def _card(row, rank: int, hero: bool = False) -> str:
    led = row["led"]
    cls = "card hero" if hero else "card"
    if led:                                   # real headshot
        avatar = f'<img src="{_b64(HEADSHOTS / led["file"])}" alt="{row["name"]}">'
    else:                                     # monogram placeholder (no photo yet)
        avatar = f'<div class="mono">{_initials(row["name"])}</div>'
    loc = led["loc"] if led else ""
    loc_html = f'<div class="loc">{loc}</div>' if loc else '<div class="loc">&nbsp;</div>'
    d = _delta(row)
    delta_html = (f'<div class="delta {d[2]}">{d[0]} {d[1]} <em>vs last wk</em></div>'
                  if d else '<div class="delta flat">—</div>')
    return f"""
    <div class="{cls}">
      <div class="rank">#{rank}</div>
      <div class="ring">{avatar}</div>
      <div class="nm">{row['name']}</div>
      {loc_html}
      <div class="week">{_fmt(row['week'])}</div>
      <div class="wlabel">THIS WEEK</div>
      {delta_html}
      <div class="spark">{_spark(row['series'])}</div>
      <div class="total"><span>2026 TOTAL</span> {_fmt(row['total'])}</div>
    </div>"""


def _section_table(title: str, rows: list, week_labels: list, years: list,
                   featured: set = frozenset()) -> str:
    """One branded section table: Leader · 2026 Total · last-N weeks · prior years.
    `years` is the subset of ('2025','2024','2023') this section carries.
    Rows whose name is in `featured` (the top-10 shown as cards) are highlighted."""
    weeks = week_labels[:WOW_WEEKS]
    # `lastwk` is the weekly column that BUTTS the divider. Weekly figures are
    # right-aligned, so without extra room on this side the rule sat ~7px off the
    # last week's digits and 16px off the annual ones — reading as crushed
    # against the weekly numbers (Megan 2026-07-24). Padding both sides equally
    # centres the rule in the gap.
    _lastwk = len(weeks) - 1
    wk_head = "".join(
        f'<th class="wk{" cur" if i == 0 else ""}'
        f'{" lastwk" if i == _lastwk else ""}">{w}</th>'
        for i, w in enumerate(weeks))
    # `sep` marks the FIRST annual column, which carries the rule dividing the
    # weekly block from the annual one (Megan 2026-07-24: "add some lines between
    # the weekly and annual sections"). Driven off position, so a section with a
    # different number of year columns still gets exactly one divider.
    yr_head = "".join(f'<th class="yr{" sep" if i == 0 else ""}">{y}</th>'
                      for i, y in enumerate(years))
    body = ""
    for r in rows:
        wk = "".join(
            f'<td class="wk{" cur" if i == 0 else ""}'
            f'{" lastwk" if i == _lastwk else ""}">'
            f'{_fmt(r["series"][i] if i < len(r["series"]) else None)}</td>'
            for i in range(len(weeks)))
        yr = "".join(f'<td class="yr{" sep" if i == 0 else ""}">'
                     f'{_fmt(r["years"].get(y))}</td>'
                     for i, y in enumerate(years))
        body += (f'<tr class="{"lead" if r["name"] in featured else ""}">'
                 f'<td class="nmcell">{r["name"]}</td>'
                 f'<td class="t26">{_fmt(r["total"])}</td>{wk}{yr}</tr>')
    # Shared <colgroup> so both tables get identical column widths and line up.
    colgroup = ("<colgroup><col class=\"c-name\"><col class=\"c-t26\">"
                + '<col class="c-wk">' * len(weeks)
                + '<col class="c-yr">' * len(years)
                + "</colgroup>")
    return f"""
    <div class="sec">
      <div class="sec-h">{title}</div>
      <table>
        {colgroup}
        <tr><th class="nmcell">Leader</th><th class="t26">Total 2026</th>{wk_head}{yr_head}</tr>
        {body}
      </table>
    </div>"""


def build_html(week_labels, combined, regular, captainship, program) -> str:
    week_label = week_labels[0] if week_labels else ""
    logo = _b64(LOGO)
    # FEATURED = our org leaders — the people we have headshots for — who earned
    # an override this week, ranked by this week's amount, capped at 10 (Megan
    # 2026-07-22: feature the leaders, and "why aren't Hammad and Ryan
    # highlighted" — because featured must follow who we've onboarded, not raw
    # top-10 earnings). Cards and table highlights are this same set, so everyone
    # featured has a real photo (no monograms) and every leader is highlighted.
    # Feature the TOP 5 by this week's override (Megan 2026-07-22: only feature
    # the top 5 — a $53 card "isn't very motivating"). Everyone else lives in the
    # tables below; the featured 5 are highlighted there to tie back to the cards.
    # We still keep headshots for the whole roster so whoever lands in the top 5
    # any given week has a photo.
    featured = sorted(combined, key=lambda x: (x["week"] or 0), reverse=True)[:5]
    featured_names = {r["name"] for r in featured}
    grid = "\n".join(_card(r, i + 1) for i, r in enumerate(featured))
    YRS = ["2025", "2024", "2023"]               # same 3 year cols so all line up
    # Four stacked sections (Raf 2026-07-25): the combined total, then the three
    # categories separated. The leadership tier (whoever has captain/program) is
    # highlighted in every table so the same names tie together across sections.
    lead_names = {r["name"] for r in captainship} | {r["name"] for r in program}
    tbl_all = _section_table("ALL OVERRIDES — COMBINED", combined, week_labels,
                             YRS, featured_names)
    tbl_reg = _section_table("REGULAR OVERRIDES — 1ST GEN / RC / NC", regular,
                             week_labels, YRS, featured_names)
    tbl_cap = _section_table("CAPTAINSHIP OVERRIDES", captainship, week_labels,
                             YRS, lead_names)
    tbl_prog = _section_table("PROGRAM OVERRIDES", program, week_labels,
                              YRS, lead_names)
    org_total = sum(r["total"] or 0 for r in combined)
    wk_total = sum(r["week"] or 0 for r in combined)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1180px; background:#0a0a0a;
    background-image: radial-gradient(circle at 50% 0%, #1a1712 0%, #0a0a0a 60%);
    font-family: 'Georgia', serif; color:#f4f1ea; padding:44px 40px 34px; }}
  .head {{ text-align:center; }}
  .head img {{ width:150px; height:150px; object-fit:contain; }}
  .title {{ font-size:40px; letter-spacing:6px; font-weight:bold;
    background:linear-gradient(180deg,{GOLD_LT},{GOLD}); -webkit-background-clip:text;
    -webkit-text-fill-color:transparent; margin-top:2px; }}
  .sub {{ color:#b9b4a8; letter-spacing:3px; font-size:14px; margin-top:8px; text-transform:uppercase; }}
  .rule {{ height:2px; margin:20px auto 26px; width:78%;
    background:linear-gradient(90deg,transparent,{GOLD},transparent); }}
  .totals {{ display:flex; justify-content:center; gap:60px; margin-bottom:30px; }}
  .totals .t {{ text-align:center; }}
  .totals .n {{ font-size:30px; color:{GOLD_LT}; font-weight:bold; }}
  .totals .l {{ font-size:11px; letter-spacing:2px; color:#8f8a7e; text-transform:uppercase; margin-top:3px; }}
  .grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:16px; }}
  .card {{ position:relative; background:linear-gradient(180deg,#17140f,#0d0b08);
    border:1px solid #2c2619; border-radius:14px; padding:20px 12px 15px; text-align:center; }}
  .rank {{ position:absolute; top:10px; left:11px; color:{GOLD}; font-size:13px; font-weight:bold; letter-spacing:1px; }}
  .ring {{ width:92px; height:92px; margin:4px auto 10px; border-radius:50%;
    padding:3px; background:linear-gradient(135deg,{GOLD_LT},{GOLD}); }}
  .ring img {{ width:100%; height:100%; border-radius:50%; object-fit:cover; display:block; }}
  .mono {{ width:100%; height:100%; border-radius:50%; display:flex; align-items:center;
    justify-content:center; background:radial-gradient(circle at 50% 38%,#2a2418,#141109);
    color:{GOLD_LT}; font-weight:bold; font-size:32px; letter-spacing:1px; }}
  .nm {{ font-size:15px; font-weight:bold; color:#f7f3ea; line-height:1.2; }}
  .loc {{ font-size:10px; letter-spacing:1px; color:#8f8a7e; margin-top:2px; text-transform:uppercase; }}
  .week {{ font-size:25px; color:{GOLD_LT}; font-weight:bold; margin-top:9px; }}
  .wlabel {{ font-size:9px; letter-spacing:2px; color:#8f8a7e; margin-top:1px; }}
  .delta {{ font-size:11px; font-weight:bold; margin-top:6px; }}
  .delta em {{ font-style:normal; color:#6f6b60; font-weight:normal; font-size:9px; }}
  .delta.up {{ color:#5fbf6a; }}
  .delta.down {{ color:#d06a6a; }}
  .delta.flat {{ color:#8f8a7e; }}
  .spark {{ margin:9px auto 4px; height:26px; }}
  /* The card's 2026 total is an ANNUAL total too, and at 13px over an 8px label
     it was the smallest number on the page. Same readability pass as the table's
     year columns (Megan 2026-07-24). */
  .total {{ font-size:18px; color:#e7dcbb; font-weight:bold; margin-top:6px;
    border-top:1px solid #2c2418; padding-top:9px; }}
  .total span {{ display:block; color:#a8a294; font-size:10px; letter-spacing:2px; font-weight:normal; margin-bottom:3px; }}
  /* section tables */
  .sec {{ margin-top:38px; }}
  .sec-h {{ text-align:center; color:{GOLD}; letter-spacing:4px; font-size:20px;
    font-weight:bold; margin-bottom:16px;
    background:linear-gradient(180deg,{GOLD_LT},{GOLD}); -webkit-background-clip:text;
    -webkit-text-fill-color:transparent; }}
  /* Type scale (Megan 2026-07-24: "not very easy to read/see the numbers").
     The figures ARE the report, so they get read at a glance on a phone: the
     table went 12.5 -> 16px, headers 10 -> 12px, rows breathe (8 -> 12px), and
     every value sits on a brighter ink than the mid-grey it used to. Prior-year
     columns stay dimmer than the live weeks, but are no longer near-invisible. */
  /* table-layout:fixed + shared column widths so BOTH tables line up column-for-
     column (Megan 2026-07-25). Widths are for the 1-name + 1-total + 6-week +
     3-year layout and sum to 100%; 5 weeks so the columns have room to breathe. */
  .sec table {{ width:100%; border-collapse:collapse; font-size:15px;
    table-layout:fixed; }}
  .sec col.c-name {{ width:17%; }}
  .sec col.c-t26  {{ width:10%; }}
  .sec col.c-wk   {{ width:8%; }}
  .sec col.c-yr   {{ width:11%; }}
  /* Column headers (Megan 2026-07-24: "still hard to read the date headers").
     They were 12px, un-bold, on mid-grey with 1px tracking — the faintest text
     on the page, and the one that tells you WHICH WEEK you're looking at. Now
     15px bold on near-white, with the tracking eased off: letter-spacing helps
     a word read as a label but actively hurts a date like 7.19.26. */
  .sec th {{ color:#ded8ca; font-size:14px; letter-spacing:0.3px; font-weight:bold;
    padding:7px 8px 8px; border-bottom:1px solid {GOLD}; text-align:right;
    text-transform:uppercase; white-space:nowrap; }}
  /* Condensed (Raf 2026-07-25): cells fit their content — the name column takes
     only what the longest name needs (width:1% + nowrap collapses it to content,
     no more big empty gap), and MORE weeks fill the freed width. */
  .sec th.nmcell, .sec td.nmcell {{ text-align:left; white-space:nowrap;
    padding-right:12px; overflow:hidden; text-overflow:ellipsis; }}
  /* This Week stays GOLD (matches the cards' big gold "THIS WEEK"); Total 2026 is
     bright cream so the two headline columns read as distinct, not one gold block
     (Megan 2026-07-25). The current-week column also opens the WEEKLY block with a
     vertical gold rule, so the table reads as three blocks — [leader+total] |
     [weeks] | [years] — like the DD bulletin Megan likes. */
  .sec th.wk.cur, .sec td.wk.cur {{ color:{GOLD_LT};
    border-left:2px solid rgba(201,162,75,0.55); padding-left:14px; }}
  /* keep the Total 2026 number clear of the divider on its right */
  .sec th.t26, .sec td.t26 {{ padding-right:14px; }}
  .sec th.t26, .sec td.t26 {{ color:#f4efe2; }}
  .sec th.yr {{ color:#cfc8b7; }}
  /* Bolder row rule + zebra shading so the eye tracks straight across a wide row
     (Megan 2026-07-25: "bolder lines and some nuance in color every other line"). */
  .sec td {{ padding:6px 8px; text-align:right; color:#eae5d9;
    white-space:nowrap; border-bottom:1px solid rgba(201,162,75,0.34); }}
  .sec tr:nth-child(even) td {{ background:rgba(255,255,255,0.05); }}
  .sec td.nmcell {{ color:#f2eee4; font-size:15px; }}
  /* Total 2026 and This Week are bold (and cream / gold) to stand out — same SIZE
     as the rest so the big totals don't overflow their column into the divider
     (Megan 2026-07-25 "overlap"). */
  .sec td.t26 {{ font-weight:bold; }}
  .sec td.wk.cur {{ font-weight:bold; }}
  /* Annual totals (Megan 2026-07-24, second pass: "the annual totals are still
     hard to read"). They were deliberately dimmed to push the eye to the live
     weeks, but a number nobody can read has no reason to be on the page. Now the
     same size and near the same brightness as the weeks — the current week keeps
     its priority through GOLD and bold, not by starving the rest of contrast. */
  .sec td.yr {{ color:#e2ddd1; font-size:16px; }}
  /* The rule dividing the weekly block from the annual one, sitting CENTRED in
     the gap: equal breathing room either side so it never crowds a number. */
  .sec th.sep, .sec td.sep {{ border-left:2px solid rgba(201,162,75,0.60);
    padding-left:22px; }}
  .sec th.lastwk, .sec td.lastwk {{ padding-right:22px; }}
  .sec tr.lead td.nmcell {{ color:#f6f2e9; font-weight:bold;
    border-left:3px solid {GOLD}; padding-left:9px; }}
  .sec tr.lead td {{ background:rgba(201,162,75,0.14); }}
  .foot {{ text-align:center; margin-top:30px; }}
  .foot .tag {{ color:{GOLD}; letter-spacing:5px; font-size:15px; font-weight:bold; }}
  .foot .dt {{ color:#6f6b60; font-size:11px; letter-spacing:1px; margin-top:8px; }}
</style></head><body>
  <div class="head">
    <img src="{logo}" alt="Alphalete">
    <div class="title">ORG OVERRIDE BULLETIN</div>
    <div class="sub">Alphalete Organizational Leaders &nbsp;·&nbsp; Week of {week_label}</div>
  </div>
  <div class="rule"></div>
  <div class="totals">
    <div class="t"><div class="n">{_fmt(org_total)}</div><div class="l">Total 2026 Overrides</div></div>
    <div class="t"><div class="n">{_fmt(wk_total)}</div><div class="l">This Week</div></div>
  </div>
  <div class="grid">{grid}</div>
  {tbl_all}
  {tbl_reg}
  {tbl_cap}
  {tbl_prog}
  <div class="foot">
    <div class="tag">LEARN MORE. DREAM MORE. DO MORE.</div>
    <div class="dt">Overrides through {week_label}</div>
  </div>
</body></html>"""


def build(out_dir: Path = OUT_DIR, tab=None) -> Path:
    week_labels, combined, regular, captainship, program = read_data(tab)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(week_labels, combined, regular, captainship, program)
    path = out_dir / "override-bulletin.html"
    path.write_text(html, encoding="utf-8")
    wk = week_labels[0] if week_labels else "?"
    print(f"built {path}  (week {wk!r}; combined {len(combined)}, regular "
          f"{len(regular)}, captainship {len(captainship)}, program {len(program)}, "
          f"{WOW_WEEKS}-week)")
    return path


def render_png(html_path: Path | None = None, out_png: Path | None = None) -> Path:
    """Render the bulletin HTML to a full-height PNG (headless Chromium). This is
    the Slack image; the same HTML is the email body. Separate from build() so a
    render can't accidentally re-pull the sheet."""
    from patchright.sync_api import sync_playwright
    html_path = html_path or (OUT_DIR / "override-bulletin.html")
    out_png = out_png or (OUT_DIR / "override-bulletin.png")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1000, "height": 1200},
                        device_scale_factor=2)
        pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(out_png), full_page=True)
        b.close()
    print(f"rendered {out_png}")
    return out_png


if __name__ == "__main__":
    build()
