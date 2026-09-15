"""Total Apps per rep — the Tableau PRODUCT SALES SUMMARY side of the board.

ONE org-wide crosstab serves every office in the run: the rep-level
'DailyRepBDreportpull' custom view (PRODUCT SALES SUMMARY 4WK) yields
Owner | Rep | Product Type | Mon–Sun day columns for the filtered week —
the same view + week-filter mechanism the OPT phase uses weekly in
production (constants imported from opt_phase, never copied, so they can't
drift).

'Apps' is Raf's high-level count: EVERY product type — internet, upgrades,
video, wireless, all of it ("I don't need to break that out"). Days are
summed Mon–Sat to match the knock window; a Sunday-evening rerun therefore
reports the same number the 4am run did.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path

from automations.recruiting_report import opt_phase

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday"]          # Mon–Sat: the board's window — Sunday out.


def day_name(day: dt.date) -> str:
    """The crosstab column header for ONE date — '%A' is the same weekday
    spelling Tableau writes ('Wednesday'), and it is locale-independent here
    because the crosstab is English either way."""
    return day.strftime("%A")

OUT_DIR = Path("output") / "weekly_knock_dispositions"


def download(we_sunday: dt.date, *, out_path: Path | None = None,
             verbose: bool = True) -> Path:
    """Download the week's rep-level crosstab (all owners) once per run."""
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright,
    )
    out_path = out_path or (OUT_DIR / f"pss_rep_{we_sunday.isoformat()}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = opt_phase._week_url(opt_phase.PRODUCT_SALES_VIEW_URL, we_sunday)
    if verbose:
        print(f"[wkd] PSS crosstab (week ending {we_sunday}) → {out_path}",
              flush=True)
    return download_crosstab_patchright(url, opt_phase.PRODUCT_SALES_SHEET,
                                        out_path, verbose=verbose)


def _read_tsv(path: Path) -> list[list[str]]:
    raw = Path(path).read_text(encoding="utf-16")
    return [ln.split("\t") for ln in raw.splitlines() if ln.strip()]


def rep_apps_for_owner(path: Path, owner: str,
                       aliases_map: dict[str, list[str]],
                       days: "list[str] | None" = None) -> dict[str, int]:
    """{rep name: apps, all product types} for `owner`'s office.

    The owner match runs through the canonical ICD alias list (same
    candidates find_owner builds), so 'Rafael Hidalgo' finds a crosstab
    that says 'Raf Hidalgo'. Reps with zero sales simply aren't in the
    crosstab — absent means 0, not missing data.

    `days` (optional) narrows the window to those weekday columns. Default
    (None) = DAY_ORDER, the weekly board's Mon–Sat. The Captainship Report's
    DAILY knocks board passes a single day (day_name(target)) and reads the
    same crosstab the weekly section already downloads — the daily target
    always falls inside that same Mon–Sun week (both derive from
    yesterday), so one download still serves the whole build. A day the
    crosstab doesn't carry raises rather than quietly summing nothing: a
    silent 0 apps column is indistinguishable from a real quiet day.
    """
    rows = _read_tsv(path)
    if not rows:
        raise RuntimeError(f"PSS crosstab {path} is empty.")
    headers = [h.strip() for h in rows[0]]
    try:
        owner_col = headers.index("Owner Name")
        rep_col = headers.index("Rep")
    except ValueError:
        raise RuntimeError(
            f"PSS crosstab {path} missing 'Owner Name'/'Rep' — header was: "
            f"{headers}")
    wanted = list(days or DAY_ORDER)
    day_cols = {d: headers.index(d) for d in wanted if d in headers}
    if not day_cols:
        raise RuntimeError(
            f"PSS crosstab {path} has no {'/'.join(wanted)} column(s) — "
            f"header was: {headers}")

    cands = {opt_phase._norm(owner)}
    for canon, al in aliases_map.items():
        pool = {opt_phase._norm(canon)} | {opt_phase._norm(a) for a in al}
        if cands & pool:
            cands |= pool

    out: dict[str, int] = {}
    for r in rows[1:]:
        if len(r) <= max(rep_col, owner_col):
            continue
        if opt_phase._norm((r[owner_col] or "").strip()) not in cands:
            continue
        rep = (r[rep_col] or "").strip()
        if not rep or rep.lower() == "total":
            continue
        n = sum(int(r[c].strip())
                for c in day_cols.values()
                if c < len(r) and r[c].strip().isdigit())
        out[rep] = out.get(rep, 0) + n
    return out


# ---------------------------------------------------------------------------
# NDS — the same Total Apps, from the NDS workbook (Eve 2026-09-15: "las app de
# nds las podés encontrar en .../NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep").
# NDS sales never reach the D2D crosstab above, so the NDS captainships' boards
# read this one too.
#
# WHY THE 'Thisweekandlast' CUSTOM VIEW AND NOT A WEEK FILTER IN THE URL. Probed
# from Windows 2026-09-15: the base view and REPEXPANDED both lose the worksheet
# the moment 'Sale Date Week Ending (mon-sun)' rides the URL (the Crosstab dialog
# shows only 'Last Refresh (2)'). Thisweekandlast — the view opt_nds already
# pulls for Personal Production — exports LAST week and THIS week side by side,
# one Mon..Sun block each, under a week-ending header row. That covers both
# callers without pinning anything: the daily board's day (yesterday) and the
# weekly board's Mon–Sat are always one of those two weeks when the build runs.
#
# Shape (measured): row 0 = week-ending label per column ('9/13/2026'), row 1 =
# 'Owner & Office ' | 'Rep Name' | 'Product Type (Broken Out)' | Monday … |
# Total. The owner cell is only on the first row of its block and reads
# 'KHALIL MANSOUR\r[alphalete management group, inc. dba hab]'; counts can
# carry thousands commas. One row per (rep, product type) — summed, like Raf's
# "every product type" count above.
NDS_PRODUCT_SALES_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
    "5e31de75-1d1c-4f23-b234-4148516134c0/Thisweekandlast?:iid=1"
)
NDS_PRODUCT_SALES_SHEET = "Sales By ICD (Weekly View)"


def download_nds(today: dt.date, *, out_path: Path | None = None,
                 verbose: bool = True) -> Path:
    """Download the NDS rep-level crosstab (last week + this week, all owners).
    Keyed by the DOWNLOAD day, not a week: the file's two weeks move with it."""
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright,
    )
    out_path = out_path or (OUT_DIR / f"nds_pss_rep_{today.isoformat()}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if verbose:
        print(f"[wkd] NDS PSS crosstab (this week + last) → {out_path}",
              flush=True)
    return download_crosstab_patchright(NDS_PRODUCT_SALES_VIEW_URL,
                                        NDS_PRODUCT_SALES_SHEET, out_path,
                                        verbose=verbose)


def _read_quoted_tsv(path: Path) -> list[list[str]]:
    """Tab-separated, with QUOTED cells — the owner cell holds a line break,
    so a plain line split (_read_tsv) would cut every owner row in two."""
    raw = Path(path).read_bytes()
    try:
        txt = raw.decode("utf-16")
    except UnicodeDecodeError:
        txt = raw.decode("utf-8", "replace")
    return list(csv.reader(io.StringIO(txt), delimiter="\t", quotechar='"'))


def _week_label(we_sunday: dt.date) -> str:
    """The crosstab's week header for a week-ending Sunday: '9/13/2026'."""
    return f"{we_sunday.month}/{we_sunday.day}/{we_sunday.year}"


def _count(cell: str) -> int:
    s = (cell or "").replace(",", "").strip()
    return int(s) if s.isdigit() else 0


def nds_rep_apps_for_owner(path: Path, owner: str,
                           aliases_map: dict[str, list[str]],
                           we_sunday: dt.date,
                           days: "list[str] | None" = None) -> dict[str, int]:
    """{rep name: apps, all product types} for `owner`'s office in the week
    ending `we_sunday`, from the NDS crosstab. Same contract as
    rep_apps_for_owner: owner matched through the alias list, reps with no
    sales simply absent, and `days` narrows to those weekday columns (default
    Mon–Sat). Raises when the file doesn't carry that week, or any of the
    asked days in it — a missing column must read as "apps unavailable", never
    as a quiet 0."""
    rows = _read_quoted_tsv(path)
    if len(rows) < 2:
        raise RuntimeError(f"NDS crosstab {path} is empty.")
    weeks = [c.strip() for c in rows[0]]
    heads = [c.strip() for c in rows[1]]
    try:
        owner_col = heads.index("Owner & Office")
        rep_col = heads.index("Rep Name")
    except ValueError:
        raise RuntimeError(
            f"NDS crosstab {path} missing 'Owner & Office'/'Rep Name' — header "
            f"was: {heads}")
    label = _week_label(we_sunday)
    wanted = list(days or DAY_ORDER)
    cols = [i for i, (w, h) in enumerate(zip(weeks, heads))
            if w == label and h in wanted]
    if not cols:
        raise RuntimeError(
            f"NDS crosstab {path} has no {'/'.join(wanted)} column(s) for the "
            f"week ending {label} — weeks in file: "
            f"{sorted({w for w in weeks if w and w != 'Grand Total'})}")

    cands = {opt_phase._norm(owner)}
    for canon, al in aliases_map.items():
        pool = {opt_phase._norm(canon)} | {opt_phase._norm(a) for a in al}
        if cands & pool:
            cands |= pool

    out: dict[str, int] = {}
    current = ""
    for r in rows[2:]:
        if len(r) > owner_col and r[owner_col].strip():
            current = re.split(r"[\r\n]", r[owner_col].strip())[0].strip()
        if not current or opt_phase._norm(current) not in cands:
            continue
        rep = (r[rep_col] if len(r) > rep_col else "").strip()
        if not rep or rep.lower() == "total":
            continue
        n = sum(_count(r[c]) for c in cols if c < len(r))
        out[rep] = out.get(rep, 0) + n
    return out
