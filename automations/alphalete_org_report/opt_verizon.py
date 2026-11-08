"""Verizon OPT — the weekly OPT numbers for a Verizon ICD's tab, from Credico.

    python -m automations.alphalete_org_report.opt_verizon --sv FILE.xlsx            # preview
    python -m automations.alphalete_org_report.opt_verizon --office nicolas          # newest from the Hub inbox

PREVIEW ONLY. There is no "<Owner> - Verizon" tab yet and its rows are Megan's
to pick; nothing here writes a sheet (and Megan 2026-11-06: nothing live until
Nico is on ECO). When the tab exists, a fill looks rows up BY LABEL
(feedback: no hardcoded rows) using the labels below.

SOURCE: Credico's daily "Sales Verification" xlsx -> 'Overview' sheet, one row
per Credico sales week (Sun-Sat). Credico's week ending SATURDAY maps to the
sheet's week ending the NEXT SUNDAY, as Frontier's does (opt_frontier: "5/16
-> 5/17").

Every value is Credico's own number or a plain ratio of two of them; Credico's
definition of each column is in the same file's 'References' sheet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# THE NDS OPT ROWS, SAME LABELS (Megan 2026-11-06: "this should mirror as
# close to the other programs as possible"). NDS is the nearest program --
# door-to-door wireless -- so every label is opt_nds's own, filled from its
# Verizon equivalent. (row label, source, how)
ROWS: List[Tuple[str, str, str]] = [
    ("Active Selling Heads",                 "Scoring HC", "n"),
    ("Scorecard Ranking",                    "scorecard rank", "card"),
    ("National AVG for sales",               "scorecard: avg Valid Lines per office", "card"),
    ("0-30 Day Churn",                       "Compliance Flags (weekly, sales-weighted)", "pct_later"),
    ("60 Day Churn",                         "Compliance Flags (weekly, sales-weighted)", "pct_later"),
    ("90 Day Churn",                         "Compliance Flags (weekly, sales-weighted)", "pct_later"),
    ("Activation % by Week",                 "% Total Acts.", "pct"),
    ("0-30 Day Cancel Rate  4wk avg",        "Quality Scorecard 4-wk rolling Canceled %", "pct_later"),
    ("Total Leads",                          "Optix (blocked)", "later"),
    ("New Lines",                            "Valid Lines", "n"),
    ("AVG Apps Per Active Headcount",        "Scoring Avg (Valid Lines / Scoring HC)", "ratio"),
    ("AIR",                                  "not a Verizon product", "na"),
    ("Personal Production",                  "Nico's own lines (none on Credico's rep list)", "later"),
    ("Direct Deposit",                       "Credico ARC (needs his Credico sign-in)", "later"),
    ("ABP %",                                "AutoPay %", "pct"),
    ("Next Up %",                            "AT&T-only upgrade program", "na"),
    ("Extra/Premium %",                      "UPlus+ % (Unlimited Plus or higher)", "pct"),
]
_COL = {"Active Selling Heads": "Scoring HC", "Activation % by Week": "% Total Acts.",
        "New Lines": "Valid Lines", "ABP %": "AutoPay %", "Extra/Premium %": "UPlus+ %"}


def sheet_week(credico_week_end: dt.date) -> dt.date:
    """Credico Sat -> the sheet's Sunday column (the next day)."""
    return credico_week_end + dt.timedelta(days=1)


def values_for(overview_row: Dict, card: Optional[Dict] = None) -> Dict[str, object]:
    """One week's row values. 'later' = source not wired yet (shown, never 0);
    'na' = no Verizon equivalent (the row stays as the other programs have it)."""
    out: Dict[str, object] = {}
    for label, _src, kind in ROWS:
        if kind in ("n", "pct"):
            v = overview_row.get(_COL[label])
            try:
                out[label] = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                out[label] = None
        elif kind == "ratio":
            try:
                out[label] = round(float(overview_row["Valid Lines"]) / float(overview_row["Scoring HC"]), 1)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                out[label] = None
        elif kind == "card":
            out[label] = (card or {}).get(label)
        elif kind == "pct_later":
            out[label] = "nofile"  # filled by weeks() when that week's file is given
        else:
            out[label] = kind      # "later" / "na"
    return out


def scorecard(path: Path, owner: str) -> Dict[dt.date, Dict[str, object]]:
    """{credico week end: {Scorecard Ranking, National AVG for sales}} from the
    Daily Sales Scorecard xlsx (every Verizon office, one sheet per week)."""
    import openpyxl, re
    out: Dict[dt.date, Dict[str, object]] = {}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
        title = next((str(r[0]) for r in rows[:3] if r and r[0] and "Week Ending" in str(r[0])), "")
        m = re.search(r"Week Ending (\w+ \d{1,2}, \d{4})", title)
        hi = next((i for i, r in enumerate(rows) if r and r[0] == "Owner Name"), None)
        if not m or hi is None:
            continue
        hdr = [str(c).replace("\n", " ") if c else "" for c in rows[hi]]
        ix = {h: i for i, h in enumerate(hdr) if h}
        offices = [r for r in rows[hi + 1:] if r and r[0] and isinstance(r[ix["Valid Lines"]], (int, float))]
        mine = next((r for r in offices if str(r[0]).strip().lower() == owner.lower()), None)
        if not offices or not mine:
            continue
        we = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
        out[we] = {"Scorecard Ranking": "%s of %d" % (mine[ix["Rank"]], len(offices)),
                   "National AVG for sales": round(sum(r[ix["Valid Lines"]] for r in offices) / len(offices), 1)}
    return out


def fmt(label: str, v) -> str:
    if v == "later":
        return "(to wire)"
    if v == "blank":
        return "blank@CR"
    if v == "nofile":
        return "(no file)"
    if v == "na":
        return "N/A"
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    kind = next(k for l, _c, k in ROWS if l == label)
    return f"{v*100:.1f}%" if kind in ("pct", "pct_later") else f"{v:g}"


def quality_cancel(pdf: Path, owner: str) -> Optional[Tuple[dt.date, float]]:
    """(published-on, 4-week rolling Canceled %) for this owner, from Credico's
    weekly Quality Scorecard (SCI-WO) PDF. Its first block is "Four Weeks
    Rolling": Rank, Units, Approved n %, Activated n %, Canceled n %,
    Disconnected n %, Pending n %. pypdf keeps a table row on one line; fitz
    splits every cell, so pypdf it is."""
    import re
    import pypdf
    text = "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(pdf)).pages)
    line = next((l for l in text.splitlines() if l.strip().lower().startswith(owner.lower())), None)
    if not line:
        return None
    pcts = re.findall(r"(\d+(?:\.\d+)?)%", line)
    m = re.search(r"(\d{8})\.pdf$", Path(pdf).name)
    if len(pcts) < 3 or not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y%m%d").date(), float(pcts[2]) / 100   # 3rd % = Canceled


def compliance_churn(xlsx: Path) -> Optional[Tuple[dt.date, Dict[str, Optional[float]]]]:
    """(week end, {0-30/60/90 Day Churn}) -- the office's churn, each rep's
    churn weighted by their sales. All-zero INCLUDING the campaign = Credico
    left it blank: returned as None (never written as a proven 0)."""
    from automations.verizon_office import parse
    cf = parse.read_compliance(xlsx)
    tot = sum(r.sales for r in cf.reps)
    camp = next((r.campaign for r in cf.reps if r.campaign), {})
    blank = not any(r.churn.get(k) for r in cf.reps for k in parse.CHURN_KEYS) and not any(camp.values())
    vals = {}
    for k, label in (("0-30", "0-30 Day Churn"), ("60", "60 Day Churn"), ("90", "90 Day Churn")):
        vals[label] = None if (blank or not tot) else sum(r.churn.get(k, 0) * r.sales for r in cf.reps) / tot
    return (cf.week_end, vals) if cf.week_end else None


def weeks(sv_path: Path, n: int = 6, card_path: Optional[Path] = None,
          owner: str = "Nicolas Murrugarra", quality: Optional[Path] = None,
          compliance: Optional[Path] = None):
    from automations.verizon_office import parse
    sv = parse.read_sales_verification(sv_path)
    cards = scorecard(card_path, owner) if card_path else {}
    out = [(sheet_week(o["Week End Date"]), values_for(o, cards.get(o["Week End Date"])))
           for o in sv.overview[:n]]
    # Weekly files land on the sheet week they belong to: Compliance Flags by
    # its own week ending; the Quality Scorecard's 4-week figure on the week
    # it was PUBLISHED in (it is a rolling number as of that day).
    if quality:
        q = quality_cancel(quality, owner)
        if q:
            for w, vals in out:
                if w - dt.timedelta(days=6) <= q[0] <= w:
                    vals["0-30 Day Cancel Rate  4wk avg"] = q[1]
    if compliance:
        c = compliance_churn(compliance)
        if c:
            for w, vals in out:
                if w == sheet_week(c[0]):
                    for k, v in c[1].items():
                        vals[k] = v if v is not None else "blank"
    return out


OPT_TAB = "Nicolas Murrugarra - Verizon"      # created 2026-11-08 from 'NDS Template'


def fill(sv_path: Path, tab: str = OPT_TAB, n: int = 6, *, quality: Optional[Path] = None,
         compliance: Optional[Path] = None, dry_run: bool = False, log=print) -> int:
    """Write the last `n` weeks into the office's OPT tab on the Alphalete Org
    sheet (Megan 2026-11-08: "wire the weekly fill"). Same lookups as the NDS
    fill: the row by its col-B label (NDS_ROW_LABEL_ALTERNATES spellings), the
    week by the WE-Sunday header -- never a fixed index. Cells Credico doesn't
    send are LEFT ALONE, not blanked: a person may have typed one in."""
    import gspread
    from automations.alphalete_org_report import opt_nds as N
    from automations.recruiting_report import fill as rfill
    from automations.shared import sheet_flags
    rows = weeks(sv_path, n, None, quality=quality, compliance=compliance)
    if not rows:
        log("✗ no weeks in the Overview sheet — nothing written")
        return 1
    sh = rfill.open_by_key(N.ALPHALETE_ORG_SHEET_ID, rfill._client())
    ws = rfill._retry(sh.worksheet, tab)
    grid = rfill._retry(ws.get_all_values)
    updates, misses = [], []
    for week_end, vals in rows:
        col = N._find_week_col(grid, f"{week_end.month}/{week_end.day}/{week_end.year % 100}")
        if col is None:
            misses.append(f"no column for WE {week_end.month}/{week_end.day}")
            continue
        for label, _src, _kind in ROWS:
            v = vals.get(label)
            if v in ("later", "blank", "nofile", None):
                continue
            row = next((r for cand in N.NDS_ROW_LABEL_ALTERNATES.get(label, [label])
                        for r in [N._find_row_by_label(grid, cand)] if r is not None), None)
            if row is None:
                misses.append(f"no row for {label!r}")
                continue
            updates.append({"range": gspread.utils.rowcol_to_a1(row + 1, col + 1),
                            "values": [[fmt(label, v)]]})
    for m in sorted(set(misses)):
        log(f"  [miss] {tab}: {m}")
    if dry_run:
        log(f"[DRY-RUN] {tab}: would write {len(updates)} cell(s) over {len(rows)} week(s)")
        return 0
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        red = sheet_flags.weird_ranges(updates)
        if red:
            sheet_flags.apply_red_font(ws, red, retry=rfill._retry)
    log(f"[OK] {tab}: wrote {len(updates)} cell(s) over {len(rows)} week(s)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, help="local Sales Verification xlsx")
    ap.add_argument("--office", help="verizon_office key (newest file from the Hub inbox)")
    ap.add_argument("--weeks", type=int, default=6)   # Carlos 2026-11-07: a 6-week view
    ap.add_argument("--scorecard", type=Path, help="Daily Sales Scorecard xlsx (all offices) for rank + national avg")
    ap.add_argument("--quality", type=Path, help="Quality Scorecard (SCI-WO) pdf for the 4-wk cancel rate")
    ap.add_argument("--compliance", type=Path, help="Compliance Flags xlsx for 0-30/60/90 churn")
    ap.add_argument("--fill", action="store_true", help="WRITE the weeks into the OPT tab")
    ap.add_argument("--dry-run", action="store_true", help="with --fill: say what would be written")
    a = ap.parse_args(argv)
    path = a.sv
    if not path and a.office:
        from automations.verizon_office import offices as OF, run as RUN
        path = RUN.fetch(OF.get(a.office), "sales")
    if not path:
        ap.error("give --sv FILE or --office KEY (no Sales Verification found)")
    if a.fill:
        return fill(Path(path), n=a.weeks, quality=a.quality, compliance=a.compliance,
                    dry_run=a.dry_run)
    rows = weeks(path, a.weeks, a.scorecard, quality=a.quality, compliance=a.compliance)
    if not rows:
        print("✗ no weeks in the Overview sheet — nothing to show")
        return 1
    print("Verizon OPT preview — %s (nothing written)\n" % Path(path).name)
    head = "%-32s" % "Row (same label as NDS)" + "".join("%12s" % ("WE %d/%d" % (w.month, w.day)) for w, _ in rows)
    print(head)
    for label, src, _k in ROWS:
        print("%-32s" % label + "".join("%12s" % fmt(label, vals[label]) for _w, vals in rows) + "   ← " + src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
