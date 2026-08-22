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

import datetime as dt
from pathlib import Path

from automations.recruiting_report import opt_phase

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday"]          # Mon–Sat: the board's window — Sunday out.

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
                       aliases_map: dict[str, list[str]]) -> dict[str, int]:
    """{rep name: Mon–Sat apps, all product types} for `owner`'s office.

    The owner match runs through the canonical ICD alias list (same
    candidates find_owner builds), so 'Rafael Hidalgo' finds a crosstab
    that says 'Raf Hidalgo'. Reps with zero sales simply aren't in the
    crosstab — absent means 0, not missing data."""
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
    day_cols = {d: headers.index(d) for d in DAY_ORDER if d in headers}
    if not day_cols:
        raise RuntimeError(
            f"PSS crosstab {path} has no weekday columns — header was: "
            f"{headers}")

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
