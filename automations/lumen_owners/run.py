"""Lumen Owners — one email, Raf only: how the owners coming from Lumen
(Quantum Fiber) are doing now that they are moving over to AT&T.

    lucy rerun lumen_owners                         # dry run: writes the preview, sends nothing
    lucy rerun lumen_owners --to eve@alphaletemarketing.com   # preview by mail
    lucy rerun lumen_owners --send                  # the real one, to the distro

WHY (Raf, 2026-10-08, email "Metrics reporting"): "Similar to the captainship
report, can we make a captainship report for the Lumen owners only that only
goes to me ... And on the sales board, maybe we have something that says,
'List out all the owners,' and then it says, 'Not on AT&T yet, Lumen sales.'"

WHO IS IN IT. Every ICD owner on the Quantum tracker's week-ending sales view
— that view IS the list of Lumen owners, so nobody has to keep a roster. An
owner Raf does not want listed goes in EXCLUDE.

WHAT EACH ROW SAYS.
  * AT&T this week: all units (no Voice) + New Internets, week to date, from
    the SAME all-teams fiber crosstab the Org Sales Board captainships read
    (org_sales_board.captainship.pull_programs) — one definition, no drift.
  * Lumen: fiber sales for the last two complete weeks on the Quantum tracker
    (weekly only; there is no per-owner daily Quantum view).
  * Status: "On AT&T" once any AT&T unit shows up this week, otherwise
    "Not on AT&T yet" — and their Lumen sales are what tells Raf how they are
    doing.

THE SALES BOARD under the table (Raf, 2026-10-20: "can we also add the sales
board similar to what we get on the captainship reports?"). The same New
Internet + All Units boxes a fiber captain gets, owner x day Mon-Sun, built
from the SAME fiber crosstab already pulled above — no second Tableau pull and
no box on the shared Org Sales Board.
Eve 2026-10-20: two more columns per box, the Org Sales Board's own pair —
"Last Week Total" (the week before this one) and "Prior Week Total" (two
weeks back) — pulled from the same crosstab pinned to those weeks.

THE LUMEN OWNERS TAB (Raf, 2026-10-21, a screenshot of his own captainship
box: "can we add this type of reporting as well please?"). Product Summary,
Current vs Prior Weeks, the week-by-week history and the daily board need
weeks of history, so they live on a tab of the Org Sales Board workbook
(board.py) and the mail carries a picture of each box under the table.
Every run re-pulls this week + the two before (they still move) and pulls any
older week the hidden history tab does not have yet — the first run backfills
9 weeks, later runs one at most.

STATUS words (Raf, same mail: "guys like Nigel Marshal are only selling
wireless ... can we put 'INT' or 'INT + Wireless' or 'wireless only'"): read
from this week's product rows of the same crosstab.

Its own module on purpose: the Org Sales Board is shared and its captainship
boxes feed every other captain's email; this touches none of it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "lumen_owners"

RAF = "raffi127@gmail.com"

# WHO GETS --send (Eve, 2026-10-23): the "Lumen Owners" Contacts group of
# alphaletereporting — Chan, Myles Neal, David Pancoast, Raf, Eve. Raf had
# asked Chan for a "quantum sales board ... the captainship email but for the
# quantum guys only" and confirmed this mail IS that board. Everybody gets the
# full mail, other owners included. Edit the group, not the code; FALLBACK_TO
# is only used when the group can't be read (same rule as the captainships).
# Raf, 2026-10-24: "add all the lumen owners to this email and Pat Thompson"
# — the 13 owners on the Quantum tracker that day + Pat joined the group.
DISTRO_GROUP = "Lumen Owners"
FALLBACK_TO = ["parkwchan19@gmail.com", "mylesnealbusiness@gmail.com",
               "pancoast10xbusiness@gmail.com", RAF,
               "eve@alphaletemarketing.com",
               "resoundinc@gmail.com", "aaron.nimako@gmail.com",
               "lajahnikv@gmail.com", "padilla10x2001@gmail.com",
               "partnersmarketing.co@gmail.com", "osterhousevaughn@gmail.com",
               "nigelmarshall002@gmail.com", "isaiahkellum07@gmail.com",
               "batde3y@gmail.com", "krisnatvhuoth@gmail.com",
               "ecebuyukozerbusiness@gmail.com", "pthomp2133@gmail.com",
               "aiye.afariogun.b@gmail.com",   # Chan, 10/29 thread
               "miller10xbusiness@gmail.com"]  # Shealey Miller, 24273
TITLE = "Lumen Owners"

# Owner names (as the Quantum view prints them, any case) Raf asked to leave
# off. Empty = everybody on the tracker.
EXCLUDE: Tuple[str, ...] = ()

# Owners who get a row even when the Quantum view leaves them out (Eve,
# 2026-10-30): the view only lists ICDs with recent Quantum sales, so Vaughn
# (on it in September) dropped off and wrote "my stats are not included", and
# Shealey (incorporated 10/2026) was never on it. (name, company). Their Lumen
# columns print dashes; the AT&T columns come from the fiber crosstab as usual.
EXTRA_OWNERS: Tuple[Tuple[str, str], ...] = (
    ("Vaughn Osterhouse", "kingdom management group, inc."),
    ("Shealey Miller", ""),
)

ON_ATT = "On AT&T"            # sells AT&T, but neither internet nor wireless
NOT_YET = "Not on AT&T yet"
INT = "INT"
INT_WIRELESS = "INT + Wireless"
WIRELESS_ONLY = "Wireless only"

# Product rows of the fiber crosstab that count as internet / wireless for the
# Status column. AIR = AT&T Internet Air.
INTERNET_PRODUCTS = ("NEW INTERNET", "INTERNET", "UPGRADE INTERNET", "AIR")
WIRELESS_PRODUCTS = ("WIRELESS",)


def _fold(s: str) -> str:
    return " ".join(str(s or "").casefold().split())


def split_sales_key(key: str) -> Tuple[str, str]:
    """'Nigel Marshall [VP Executives, Inc.] (Nest)' -> ('Nigel Marshall',
    'VP Executives, Inc.'). Pure."""
    s = str(key or "").strip()
    owner, office = s, ""
    if "[" in s:
        owner = s.split("[", 1)[0].strip()
        office = s.split("[", 1)[1].split("]", 1)[0].strip()
    return owner, office


def lumen_weeks(rows: List[List[str]], today: dt.date, n: int = 2) -> List[dt.date]:
    """The last `n` week-ending dates in the grid's header that are already
    over (< today). Newest first. Pure."""
    from automations.recruiting_report.quantum_fallback import _date
    if not rows:
        return []
    ds = sorted({d for d in (_date(h) for h in rows[0]) if d and d < today},
                reverse=True)
    return ds[:n]


def lumen_by_owner(rows: List[List[str]], weeks: List[dt.date]
                   ) -> Dict[str, dict]:
    """{sales_key: {'owner', 'office', 'weeks': {date: int|None}}}. Pure.
    Grand-total rows are dropped."""
    from automations.recruiting_report.quantum_fallback import quantum_sales
    out: Dict[str, dict] = {}
    for r in rows[1:] if rows else []:
        key = (r[0] if r else "").strip()
        if not key or "total" in _fold(key):
            continue
        owner, office = split_sales_key(key)
        if _fold(owner) in {_fold(x) for x in EXCLUDE}:
            continue
        out[key] = {"owner": owner, "office": office,
                    "weeks": {w: quantum_sales(rows, key, w) for w in weeks}}
    return out


def add_extra_owners(lumen: Dict[str, dict], weeks: List[dt.date],
                     extra=None) -> Dict[str, dict]:
    """`lumen` plus a dash-only entry for each EXTRA_OWNERS name the view
    didn't list (matched on the folded owner name). Pure."""
    have = {_fold(L["owner"]) for L in lumen.values()}
    out = dict(lumen)
    for name, office in (EXTRA_OWNERS if extra is None else extra):
        if _fold(name) in have:
            continue
        out["%s [%s]" % (name.upper(), office)] = {
            "owner": name.upper(), "office": office,
            "weeks": {w: None for w in weeks}}
    return out


def att_metrics(owner: str, fiber: Dict[str, dict], aliases) -> dict:
    """This owner's {'Total': {date: n}, 'NewInternet': {date: n}} on the AT&T
    fiber crosstab, matched the way the captainship fill matches. {} when
    absent — the crosstab omits owners with no sales."""
    from automations.org_sales_board.captainship import _candidates_for_name
    cands = _candidates_for_name(owner, aliases)
    k = next((x for x in fiber if x in cands), None)
    return fiber[k] if k else {}


def att_for(owner: str, fiber: Dict[str, dict], aliases) -> Tuple[int, int]:
    """(all units, new internets) week to date for this owner. (0, 0) when
    absent."""
    m = att_metrics(owner, fiber, aliases)
    return (sum((m.get("Total") or {}).values()),
            sum((m.get("NewInternet") or {}).values()))


def status_for(units: int, internet: int, wireless: int) -> str:
    """Raf's Status words. Pure."""
    if units <= 0:
        return NOT_YET
    if internet > 0 and wireless > 0:
        return INT_WIRELESS
    if internet > 0:
        return INT
    if wireless > 0:
        return WIRELESS_ONLY
    return ON_ATT


def pretty_name(name: str) -> str:
    """'NIGEL MARSHALL' -> 'Nigel Marshall' for what people read (Eve,
    2026-10-21). Only ALL-CAPS words change, so a name already typed as
    'McElwee' keeps its capitals. Matching still uses the raw name."""
    return " ".join(w.title() if w.isupper() else w for w in name.split(" "))


def build_rows(lumen: Dict[str, dict], fiber: Dict[str, dict], aliases,
               past: Optional[List[Optional[Dict[str, dict]]]] = None,
               mix: Optional[Dict[str, dict]] = None) -> List[dict]:
    """One row per Lumen owner, On AT&T first (most AT&T units first), then
    Not on AT&T yet (most Lumen sales first). `past` = the fiber pulls of the
    earlier weeks, newest first; None for a week whose pull failed, so its
    cell prints a dash instead of a 0 that looks real. `mix` = this week's
{owner: {'Internet': {..}, 'Wireless': {..}}} for the Status words; without
it every seller reads "On AT&T". Pure given its inputs."""
    rows = []
    for key, L in lumen.items():
        m = att_metrics(L["owner"], fiber, aliases)
        prev = {}
        for metric in ("Total", "NewInternet"):
            prev[metric] = [
                None if f is None else
                sum((att_metrics(L["owner"], f, aliases).get(metric) or {}).values())
                for f in (past or [])]
        units = sum((m.get("Total") or {}).values())
        ni = sum((m.get("NewInternet") or {}).values())
        mx = att_metrics(L["owner"], mix or {}, aliases)
        internet = sum((mx.get("Internet") or {}).values())
        wireless = sum((mx.get("Wireless") or {}).values())
        rows.append({"owner": L["owner"], "office": L["office"],
                     "att_units": units, "att_ni": ni,
                     "att_days": {"Total": dict(m.get("Total") or {}),
                                  "NewInternet": dict(m.get("NewInternet") or {})},
                     "att_past": prev,
                     "lumen": L["weeks"],
                     "status": status_for(units, internet, wireless)})

    def _lumen_last(r):
        vals = [v for v in r["lumen"].values() if v is not None]
        return vals[0] if vals else 0

    rows.sort(key=lambda r: (r["status"] == NOT_YET,
                             -r["att_units"] if r["status"] != NOT_YET
                             else -_lumen_last(r),
                             r["owner"].casefold()))
    return rows


def _cell(v) -> str:
    return "&ndash;" if v is None else html.escape(str(v))


def table_html(rows: List[dict], weeks: List[dt.date], att_week: str) -> str:
    """The email body: a plain table any mail client renders."""
    th = ('style="padding:6px 10px;border:1px solid #ccc;background:#1f3864;'
          'color:#fff;font-size:13px;text-align:center"')
    td = 'style="padding:6px 10px;border:1px solid #ccc;font-size:13px;text-align:center"'
    tdl = 'style="padding:6px 10px;border:1px solid #ccc;font-size:13px;text-align:left"'
    wk = ["Lumen WE %d/%d" % (w.month, w.day) for w in weeks]
    head = ("<tr><th %s>Owner</th><th %s>Status</th><th %s>AT&amp;T units<br>%s</th>"
            "<th %s>AT&amp;T New Internet<br>%s</th>%s</tr>"
            % (th, th, th, html.escape(att_week), th, html.escape(att_week),
               "".join("<th %s>%s</th>" % (th, w) for w in wk)))
    body = []
    for r in rows:
        on = r["status"] != NOT_YET
        badge = ('<span style="color:%s;font-weight:bold">%s</span>'
                 % ("#1a7f37" if on else "#b35900", html.escape(r["status"])))
        who = html.escape(pretty_name(r["owner"])) + (
            '<br><span style="color:#777;font-size:11px">%s</span>'
            % html.escape(r["office"]) if r["office"] else "")
        body.append(
            "<tr><td %s>%s</td><td %s>%s</td><td %s>%s</td><td %s>%s</td>%s</tr>"
            % (tdl, who, td, badge, td, r["att_units"], td, r["att_ni"],
               "".join("<td %s>%s</td>" % (td, _cell(r["lumen"].get(w)))
                       for w in weeks)))
    on = sum(1 for r in rows if r["status"] != NOT_YET)
    summary = ("<p style=\"font-size:14px\"><b>%d</b> Lumen owner(s) &middot; "
               "<b style=\"color:#1a7f37\">%d on AT&amp;T</b> &middot; "
               "<b style=\"color:#b35900\">%d not on AT&amp;T yet</b></p>"
               % (len(rows), on, len(rows) - on))
    return (summary + '<table style="border-collapse:collapse">' + head
            + "".join(body) + "</table>"
            + '<p style="color:#777;font-size:11px">AT&amp;T = all units except '
              "Voice, week to date (ATTTRACKER2_1-D2D &rarr; PRODUCTSALESSUMMARY4WK "
              "&rarr; AllproductsALLTEAMS). Status: INT = any internet "
              "(New, Upgrade, Air), Wireless = wireless lines, this week. Lumen = fiber sales per week "
              "(AT&amp;T Quantum Fiber Sales Tracker &rarr; RES-Quantum Fiber ICD "
              "Week Ending Sales).</p>")


BOARD_BOXES = (("NewInternet", "NEW INTERNET"), ("Total", "ALL UNITS"))
PAST_LABELS = ("Last Week Total", "Prior Week Total")


def sales_board_html(rows: List[dict], days: List[dt.date], today: dt.date,
                     att_week: str) -> str:
    """The captainship-style Sales Board: one box per metric (New Internet,
    All Units), one line per Lumen owner, Mon-Sun + week total + the two
    earlier weeks' totals, team total on the last line. Days still ahead stay blank (a 0 there would read as "sold
    nothing"). Owners sorted by the box's week total, most first. Pure."""
    th = ('style="padding:5px 8px;border:1px solid #ccc;background:#1f3864;'
          'color:#fff;font-size:12px;text-align:center"')
    td = 'style="padding:5px 8px;border:1px solid #ccc;font-size:12px;text-align:center"'
    tdl = 'style="padding:5px 8px;border:1px solid #ccc;font-size:12px;text-align:left"'
    tdt = ('style="padding:5px 8px;border:1px solid #ccc;font-size:12px;'
           'text-align:center;font-weight:bold;background:#eef2f8"')
    tdtl = ('style="padding:5px 8px;border:1px solid #ccc;font-size:12px;'
            'text-align:left;font-weight:bold;background:#eef2f8"')
    out = ['<div style="font-size:16px;font-weight:bold;margin:22px 0 6px">'
           'AT&amp;T Sales Board &mdash; %s</div>' % html.escape(att_week)]
    for metric, label in BOARD_BOXES:
        past_we = [days[-1] - dt.timedelta(days=7 * (i + 1))
                   for i in range(len(PAST_LABELS))]
        head = ("<tr><th %s>%s</th>%s<th %s>Total</th>%s</tr>"
                % (th, label, "".join("<th %s>%s<br>%d/%d</th>"
                                      % (th, d.strftime("%a"), d.month, d.day)
                                      for d in days), th,
                   "".join("<th %s>%s<br>WE %d/%d</th>" % (th, lb, w.month, w.day)
                           for lb, w in zip(PAST_LABELS, past_we))))

        def _p(r, i):
            vals = (r.get("att_past") or {}).get(metric) or []
            return vals[i] if i < len(vals) else None

        def _pcells(style, vals):
            return "".join("<td %s>%s</td>" % (style, "&ndash;" if v is None else v)
                           for v in vals)

        def _ptot(i):
            vals = [_p(r, i) for r in rows]
            return None if any(v is None for v in vals) else sum(vals)

        def _v(r, d):
            return (r.get("att_days") or {}).get(metric, {}).get(d, 0)

        ranked = sorted(rows, key=lambda r: (-sum(_v(r, d) for d in days),
                                             r["owner"].casefold()))
        body = []
        for r in ranked:
            cells = "".join("<td %s>%s</td>" % (td, _v(r, d) if d < today else "")
                            for d in days)
            body.append("<tr><td %s>%s</td>%s<td %s>%d</td>%s</tr>"
                        % (tdl, html.escape(pretty_name(r["owner"])), cells, tdt,
                           sum(_v(r, d) for d in days),
                           _pcells(td, [_p(r, i) for i in range(len(PAST_LABELS))])))
        tot = "".join("<td %s>%s</td>" % (tdt, sum(_v(r, d) for r in rows)
                                          if d < today else "") for d in days)
        body.append("<tr><td %s>TEAM TOTAL</td>%s<td %s>%d</td>%s</tr>"
                    % (tdtl, tot, tdt, sum(_v(r, d) for r in rows for d in days),
                       _pcells(tdt, [_ptot(i) for i in range(len(PAST_LABELS))])))
        out.append('<table style="border-collapse:collapse;margin:0 0 14px">'
                   + head + "".join(body) + "</table>")
    return "".join(out)


def _week_ok(fiber: Dict[str, dict], ref: dt.date) -> bool:
    """True when every date in the pull falls in ref's reporting week. A view
    that ignored the week pin and came back on another week is not that
    week's answer (same guard as delta_lastweek_backfill). Pure."""
    from automations.org_sales_board import week as _wk
    want = set(_wk.reporting_week(ref))
    got = {d for m in fiber.values() for per in m.values() for d in (per or {})}
    return got <= want


def _product_mix(csv: Path, today: dt.date) -> Dict[str, dict]:
    """{owner: {'Internet': {date: n}, 'Wireless': {date: n}}} from the fiber
    crosstab already on disk — no extra download."""
    from automations.org_sales_board import section_pull as sp
    from automations.org_sales_board.captainship import PROGRAMS, TYPES
    fp = TYPES["fiber"]["parse"]
    out: Dict[str, dict] = {}
    for metric, products in (("Internet", INTERNET_PRODUCTS),
                             ("Wireless", WIRELESS_PRODUCTS)):
        spec = sp.ScrapeSpec(
            section_label="PROG_fiber", metric=metric,
            view_url=PROGRAMS["fiber"], owner_col=fp["owner_col"],
            value_col="", day_col="", method=sp.CROSSTAB,
            crosstab_sheet=fp["crosstab_sheet"], include_products=products,
            skip_owners=("Grand Total", "Sales Total"), week_pin=True,
            out_name=csv.name)
        for owner, metrics in sp.parse_byday(spec, csv, today).items():
            out.setdefault(owner, {}).update(metrics)
    return out


def weeks_to_pull(have: Dict[dt.date, dict], today: dt.date) -> List[int]:
    """How many weeks back to pull this run: always 1 and 2 (still moving),
    plus any older LUMEN TEAM week the history does not have. Pure."""
    from automations.lumen_owners import board as B
    from automations.org_sales_board import week as _wk
    cur = _wk.reporting_sunday(today)
    return [i for i in range(1, B.WEEK_COLS)
            if i <= len(PAST_LABELS)
            or (cur - dt.timedelta(days=7 * i)) not in have]


def _pull(today: dt.date, history: Dict[dt.date, dict]):
    """(quantum grid, fiber {owner: metrics}, failed, weeks, mix, 30-day grid) in ONE
    Tableau session. `weeks` = `history` with every week pulled clean this
    run laid over it ({week_ending: fiber}); a week whose pull failed or came
    back on the wrong week keeps what history had, or stays missing."""
    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from automations.recruiting_report import probe_quantum_views as PQ
    from automations.recruiting_report.quantum_fallback import (
        SALES_SHEET, SALES_VIEW)
    from automations.org_sales_board.captainship import pull_programs
    from automations.org_sales_board import week as _wk

    weeks = dict(history)
    with tableau_session(verbose=False, profile_dir=OUT / ".profile") as page:
        prog, failed = pull_programs(page, today, programs=["fiber"],
                                     out_dir=OUT, out_prefix="lumen_owners_")
        mix = {}
        if not failed:
            weeks[_wk.reporting_sunday(today)] = prog.get("fiber", {})
            try:
                mix = _product_mix(OUT / "lumen_owners_PROG_fiber.csv", today)
            except Exception as e:  # noqa: BLE001 — Status falls back, mail goes
                print("[lumen] product mix unreadable: %s" % e)
        for i in weeks_to_pull(history, today):
            ref = today - dt.timedelta(days=7 * i)
            we = _wk.reporting_sunday(ref)
            try:
                p, f = pull_programs(page, ref, programs=["fiber"], out_dir=OUT,
                                     out_prefix="lumen_owners_wk%d_" % i)
            except Exception as e:  # noqa: BLE001 — a dash, not a dead email
                print("[lumen] week -%d pull crashed: %s" % (i, e))
                p, f = {}, ["fiber"]
            fib = p.get("fiber", {})
            if not f and _week_ok(fib, ref):
                weeks[we] = fib
            else:
                print("[lumen] week -%d pull unusable (failed=%s) — %s"
                      % (i, f, "kept history" if we in weeks else "dashes"))
        page.goto(PQ.BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        _, data = PQ._call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 500}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        wb = next((w for w in wbs if any(
            n in (w.get("name", "") + " " + (w.get("repositoryUrl") or "")).casefold()
            for n in PQ.WB_NEEDLES)), None)
        if not wb:
            raise RuntimeError("Quantum workbook not found in Tableau")
        urls = dict(PQ._views(page, wb))
        if SALES_VIEW not in urls:
            raise RuntimeError("Quantum view %r not found" % SALES_VIEW)
        out = OUT / "quantum_week_ending_sales.csv"
        download_crosstab_patchright(urls[SALES_VIEW], SALES_SHEET, out,
                                     verbose=False, page=page)
        grid = PQ._read_grid(out)
        # Last-30-days activation/cancel table (Eve, 2026-10-23). Optional:
        # a miss leaves the table off, never the mail.
        grid30 = []
        from automations.lumen_owners import metrics30 as M30
        try:
            if M30.VIEW not in urls:
                raise RuntimeError("view %r not found" % M30.VIEW)
            out30 = OUT / "quantum_30day_icd_metrics.csv"
            download_crosstab_patchright(urls[M30.VIEW], M30.SHEET, out30,
                                         verbose=False, page=page)
            grid30 = PQ._read_grid(out30)
        except Exception as e:  # noqa: BLE001 — see above
            print("[lumen] 30-day metrics FAILED: %s: %s" % (type(e).__name__, e))
    return grid, prog.get("fiber", {}), failed, weeks, mix, grid30


def recipients(to_arg: str, expand=None) -> List[str]:
    """--to wins; otherwise the Lumen Owners group, or FALLBACK_TO when the
    group is unreadable or empty (with a warning in the log)."""
    to = [a.strip() for a in (to_arg or "").split(",") if a.strip()]
    if to:
        return to
    try:
        if expand is None:
            from automations.shared.contacts_auth import expand_groups as expand
        got, missing = expand([DISTRO_GROUP])
    except Exception as e:  # noqa: BLE001 — an unreadable group must not cost the mail
        got, missing = [], ["%s (%s: %s)" % (DISTRO_GROUP, type(e).__name__, e)]
    if got and not missing:
        return list(got)
    print("[lumen] ⚠ group %r unreadable (%s) — using FALLBACK_TO"
          % (DISTRO_GROUP, missing or "empty"))
    return list(FALLBACK_TO)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="mail it to the Lumen Owners group (default: dry run, preview file only)")
    ap.add_argument("--to", default="",
                    help="mail it to THIS address instead (preview); implies a send")
    ap.add_argument("--no-sheet", action="store_true",
                    help="skip the Lumen Owners tab (and its pictures in the mail)")
    ap.add_argument("--no-knocks", action="store_true",
                    help="skip yesterday's Quantum knock boards (OwnerVille)")
    ap.add_argument("--subject-suffix", default="",
                    help="added to the subject, so a resend starts its own "
                         "Gmail thread instead of landing in today's")
    args = ap.parse_args(argv)

    from automations.focus_office_att.aliases import load_aliases
    from automations.org_sales_board import week as _wk
    from automations.shared import report_email as _mail
    from automations.lumen_owners import board as B

    today = dt.date.today()
    sh = None if args.no_sheet else B._open()
    history = B.read_history(sh) if sh else {}
    grid, fiber, failed, att_weeks, mix, grid30 = _pull(today, history)
    if failed:
        # An empty fiber pull would mark EVERY owner "Not on AT&T yet" — a
        # wrong answer that looks like a real one. Refuse instead.
        print("[lumen] AT&T fiber pull FAILED (%s) — not sending" % failed)
        return 1
    weeks = lumen_weeks(grid, today)
    lumen = lumen_by_owner(grid, weeks)
    if not lumen:
        print("[lumen] Quantum view returned no owners — not sending")
        return 1
    lumen = add_extra_owners(lumen, weeks)
    aliases = load_aliases()
    cur = _wk.reporting_sunday(today)
    past = [att_weeks.get(cur - dt.timedelta(days=7 * i))
            for i in range(1, len(PAST_LABELS) + 1)]
    rows = build_rows(lumen, fiber, aliases, past, mix)
    monday = _wk.reporting_monday(today)
    att_week = "week of %s" % monday.strftime("%m/%d")
    body = table_html(rows, weeks, att_week)
    from automations.lumen_owners import metrics30 as M30
    m30 = M30.by_owner(grid30)
    print("[lumen] 30-day metrics: %d owner(s) in the view" % len(m30))
    body += M30.table_html(rows, m30)
    for r in rows:
        print("ROW | %-28s | %-16s | AT&T %3d (NI %3d) | Lumen %s"
              % (r["owner"], r["status"], r["att_units"], r["att_ni"],
                 [r["lumen"].get(w) for w in weeks]))

    # The tab + its pictures. A Sheets hiccup here must not cost Raf the
    # table he already gets — the mail goes without the pictures and says so.
    blocks = []
    if sh is not None:
        try:
            n = B.write_history(att_weeks, today, sh)
            g, spans = B.build_grid([r["owner"] for r in rows], att_weeks,
                                    _wk.reporting_week(today), today, aliases)
            ws = B.write_tab(g, sh)
            print("[lumen] tab '%s' written (%d rows); history %d lines"
                  % (B.TAB, g.row, n))
            blocks = B.render_boxes(ws, spans, OUT / today.isoformat())
        except Exception as e:  # noqa: BLE001 — see above
            print("[lumen] Lumen Owners tab FAILED: %s: %s" % (type(e).__name__, e))
            blocks = []
    # The burgundy/plum boxes go first and carry the day-by-day numbers, so the
    # old daily table is dropped (Eve, 2026-10-21); the owner table follows as
    # a note. Without the boxes the daily table comes back so Raf loses nothing.
    if blocks:
        blocks = list(blocks) + [("<br>" + body, None, None, "note")]
        body = ""
    else:
        body += sales_board_html(rows, _wk.reporting_week(today), today, att_week)
        if sh is not None:
            body += ('<p style="color:#b35900;font-size:12px">The New Internet / '
                     "All Units performance boxes could not be built this run."
                     "</p>")

    # Yesterday's Quantum knock boards (Eve, 2026-10-23), after the boxes and
    # before the owner table. OwnerVille runs once the Tableau session above
    # is closed — they share the machine's session lock.
    files = []
    if not args.no_knocks:
        from automations.lumen_owners import knocks as KN
        kb, files = KN.build(today, OUT / today.isoformat(), aliases)
        if kb:
            notes = [b for b in blocks if len(b) > 3 and b[3] == "note"]
            blocks = [b for b in blocks if b not in notes] + kb + notes

    send = bool(args.send or args.to)
    to = recipients(args.to) if send else [DISTRO_GROUP]
    res = _mail.send_boards(
        subject="%s — %s%s" % (TITLE, today.strftime("%m/%d/%Y"),
                               (" " + args.subject_suffix.strip())
                               if args.subject_suffix.strip() else ""),
        to=to, title=TITLE, blocks=blocks, intro_html=body, files=files,
        dry_run=not send, preview_dir=OUT / today.isoformat())
    print("[lumen] %s → %s · %s" % ("SENT" if send else "DRY RUN (preview only)",
                                    ", ".join(to), res))
    return 0 if (res.get("ok") or not send) else 1


if __name__ == "__main__":
    raise SystemExit(main())
