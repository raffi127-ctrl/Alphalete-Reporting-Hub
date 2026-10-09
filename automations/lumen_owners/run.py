"""Lumen Owners — one email, Raf only: how the owners coming from Lumen
(Quantum Fiber) are doing now that they are moving over to AT&T.

    lucy rerun lumen_owners                         # dry run: writes the preview, sends nothing
    lucy rerun lumen_owners --to eve@alphaletemarketing.com   # preview by mail
    lucy rerun lumen_owners --send                  # the real one, to Raf

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
TITLE = "Lumen Owners"

# Owner names (as the Quantum view prints them, any case) Raf asked to leave
# off. Empty = everybody on the tracker.
EXCLUDE: Tuple[str, ...] = ()

ON_ATT = "On AT&T"
NOT_YET = "Not on AT&T yet"


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


def att_for(owner: str, fiber: Dict[str, dict], aliases) -> Tuple[int, int]:
    """(all units, new internets) week to date for this owner on the AT&T
    fiber crosstab, matched the way the captainship fill matches. (0, 0) when
    absent — the crosstab omits owners with no sales."""
    from automations.org_sales_board.captainship import _candidates_for_name
    cands = _candidates_for_name(owner, aliases)
    k = next((x for x in fiber if x in cands), None)
    if not k:
        return 0, 0
    m = fiber[k]
    return (sum((m.get("Total") or {}).values()),
            sum((m.get("NewInternet") or {}).values()))


def build_rows(lumen: Dict[str, dict], fiber: Dict[str, dict], aliases
               ) -> List[dict]:
    """One row per Lumen owner, On AT&T first (most AT&T units first), then
    Not on AT&T yet (most Lumen sales first). Pure given its inputs."""
    rows = []
    for key, L in lumen.items():
        units, ni = att_for(L["owner"], fiber, aliases)
        rows.append({"owner": L["owner"], "office": L["office"],
                     "att_units": units, "att_ni": ni,
                     "lumen": L["weeks"],
                     "status": ON_ATT if units > 0 else NOT_YET})

    def _lumen_last(r):
        vals = [v for v in r["lumen"].values() if v is not None]
        return vals[0] if vals else 0

    rows.sort(key=lambda r: (r["status"] != ON_ATT,
                             -r["att_units"] if r["status"] == ON_ATT
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
        on = r["status"] == ON_ATT
        badge = ('<span style="color:%s;font-weight:bold">%s</span>'
                 % ("#1a7f37" if on else "#b35900", html.escape(r["status"])))
        who = html.escape(r["owner"]) + (
            '<br><span style="color:#777;font-size:11px">%s</span>'
            % html.escape(r["office"]) if r["office"] else "")
        body.append(
            "<tr><td %s>%s</td><td %s>%s</td><td %s>%s</td><td %s>%s</td>%s</tr>"
            % (tdl, who, td, badge, td, r["att_units"], td, r["att_ni"],
               "".join("<td %s>%s</td>" % (td, _cell(r["lumen"].get(w)))
                       for w in weeks)))
    on = sum(1 for r in rows if r["status"] == ON_ATT)
    summary = ("<p style=\"font-size:14px\"><b>%d</b> Lumen owner(s) &middot; "
               "<b style=\"color:#1a7f37\">%d on AT&amp;T</b> &middot; "
               "<b style=\"color:#b35900\">%d not on AT&amp;T yet</b></p>"
               % (len(rows), on, len(rows) - on))
    return (summary + '<table style="border-collapse:collapse">' + head
            + "".join(body) + "</table>"
            + '<p style="color:#777;font-size:11px">AT&amp;T = all units except '
              "Voice, week to date (ATTTRACKER2_1-D2D &rarr; PRODUCTSALESSUMMARY4WK "
              "&rarr; AllproductsALLTEAMS). Lumen = fiber sales per week "
              "(AT&amp;T Quantum Fiber Sales Tracker &rarr; RES-Quantum Fiber ICD "
              "Week Ending Sales).</p>")


def _pull(today: dt.date):
    """(quantum grid, fiber {owner: metrics}, failed) in ONE Tableau session."""
    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from automations.recruiting_report import probe_quantum_views as PQ
    from automations.recruiting_report.quantum_fallback import (
        SALES_SHEET, SALES_VIEW)
    from automations.org_sales_board.captainship import pull_programs

    with tableau_session(verbose=False, profile_dir=OUT / ".profile") as page:
        prog, failed = pull_programs(page, today, programs=["fiber"],
                                     out_dir=OUT, out_prefix="lumen_owners_")
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
    return grid, prog.get("fiber", {}), failed


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="mail it to Raf (default: dry run, preview file only)")
    ap.add_argument("--to", default="",
                    help="mail it to THIS address instead (preview); implies a send")
    args = ap.parse_args(argv)

    from automations.focus_office_att.aliases import load_aliases
    from automations.org_sales_board import week as _wk
    from automations.shared import report_email as _mail

    today = dt.date.today()
    grid, fiber, failed = _pull(today)
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
    rows = build_rows(lumen, fiber, load_aliases())
    monday = _wk.reporting_monday(today)
    att_week = "week of %s" % monday.strftime("%m/%d")
    body = table_html(rows, weeks, att_week)
    for r in rows:
        print("ROW | %-28s | %-16s | AT&T %3d (NI %3d) | Lumen %s"
              % (r["owner"], r["status"], r["att_units"], r["att_ni"],
                 [r["lumen"].get(w) for w in weeks]))

    to = [a.strip() for a in args.to.split(",") if a.strip()] or [RAF]
    send = bool(args.send or args.to)
    res = _mail.send_boards(
        subject="%s — %s" % (TITLE, today.strftime("%m/%d/%Y")),
        to=to, title=TITLE, blocks=[], intro_html=body,
        dry_run=not send, preview_dir=OUT / today.isoformat())
    print("[lumen] %s → %s · %s" % ("SENT" if send else "DRY RUN (preview only)",
                                    ", ".join(to), res))
    return 0 if (res.get("ok") or not send) else 1


if __name__ == "__main__":
    raise SystemExit(main())
