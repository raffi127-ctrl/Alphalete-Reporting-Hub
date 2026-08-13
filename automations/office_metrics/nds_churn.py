"""NDS Wireless Churn — day-over-day per-rep board via the HOUSE pipeline.

Isaiah's per-rep churn lives in Megan's "Isaiahchurnexp" custom view (per rep:
Churn Rate / Activated SPE/SP / Disconnect count across 0-30/30/60/90). This
adapter pulls that view, reshapes it into the exact {office_total, reps} dict the
house churn fill expects, then hands off to automations.churn.run (--only
wireless) — which fills his "Lucy Wireless Churn" Sheet tab with today's column
and renders/posts the same 4 multi-day blue PNGs every office gets. So the board
is the house wireless-churn board, accumulating day over day, per rep.

Only the pull + parse are Isaiah-specific: his view's dimension columns export
with BLANK headers, so the house name-based parser can't read them. Everything
downstream (fill, multi-day render, Slack post, coloring) is house code writing
to the tab Megan set up.

  python -m automations.office_metrics.nds_churn --owner "Isaiah Revelle" --dry-run
  python -m automations.office_metrics.nds_churn --owner "Isaiah Revelle" --live
"""
from __future__ import annotations

import argparse
import csv as _csv
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

# His Sheet + tab (only NDS office today). MUST be set before importing the house
# churn modules — new_internet_churn.fill reads CHURN_SHEET_ID / CHURN_WL_TAB at
# import time. The runner can override via env for a future NDS office.
os.environ.setdefault("CHURN_SHEET_ID",
                      "18Xc_LUqSiTMdOjsl8S6McfNFbDvZQ6POHUSLcmvppA4")
os.environ.setdefault("CHURN_WL_TAB", "Lucy Wireless Churn")

from automations.shared.tableau_patchright import download_crosstab_patchright
from automations.wireless_churn import pull as wl_pull
from automations.churn import run as churn_run

# Shared per-rep NDS churn view ("ChurnALlExp", Megan 2026-08-12): CHURNRATES
# expanded to Rep for ALL NDS owners (no owner filter). We slice it by owner in
# _parse — exactly how the D2D side slices the one WirelessAllTeams view — so
# every NDS office (isaiah, drew, and any future one) uses this ONE view, no
# per-office custom view. Crosstab worksheet = the standard "Churn Rates (ICD)".
CHURN_VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
                  "4fdc2f44-19b3-4941-a9c2-831e88172728/ChurnALlExp?:iid=1")
WORKSHEET = "Churn Rates (ICD)"
PERIODS = ("0-30", "30", "60", "90")

# Set by run() to the owner whose rows to keep when slicing the all-owners view.
_SLICE_OWNER = ""


def _fetch(out_path: Path | None = None, verbose: bool = False, page=None) -> Path:
    """Drop-in for wl_pull.fetch_crosstab — pulls Isaiah's per-rep churn view.
    Same signature the house churn.run calls it with (verbose=, page=)."""
    out = out_path or (Path(tempfile.gettempdir())
                       / "wireless_churn_local_office.csv")
    download_crosstab_patchright(CHURN_VIEW_URL, WORKSHEET, out,
                                 verbose=verbose, page=page)
    return out


def _decode(path: Path) -> list[list[str]]:
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-16-le", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            if text and "\t" in text.splitlines()[0]:
                return list(_csv.reader(text.splitlines(), delimiter="\t"))
        except (UnicodeDecodeError, UnicodeError, IndexError):
            continue
    return []


def _num(v: str) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


def _parse(csv_path: Path) -> dict:
    """Drop-in for wl_pull.parse. ChurnALlExp crosstab → the house
    {office_total, reps} shape, SLICED to _SLICE_OWNER. Layout: col0 owner, col1
    rep, col2 color, col3 metric, cols4-7 = 0-30/30/60/90 (col8 = 120, ignored).
    Owner/Rep are merged (blank on repeat) → forward-fill. The view's own average
    row is a GRAND total across all owners, so we skip it and recompute this
    office's total from its reps (same as the D2D slice path)."""
    from automations.alphalete_org_report.opt_nds import _norm_owner
    from automations.new_internet_churn.pull import _recompute_office_total
    want = _norm_owner(_SLICE_OWNER) if _SLICE_OWNER else ""
    rows = _decode(csv_path)
    owner = rep = ""
    reps: dict = {}
    for r in rows[1:] if rows else []:
        if len(r) < 8:
            continue
        owner = (r[0] or "").strip() or owner
        rep = (r[1] or "").strip() or rep
        if "average" in owner.lower() or "average" in rep.lower():
            continue                                  # grand-total row — skip
        if want and _norm_owner(owner) != want:
            continue                                  # slice: this owner only
        color = (r[2] or "").strip()
        metric = (r[3] or "").strip()
        for pi, pkey in enumerate(PERIODS):
            cell = (r[4 + pi] or "").strip()
            if not cell:
                continue
            slot = reps.setdefault(rep, {}).setdefault(pkey, {})
            if color and color != "Total":
                slot.setdefault("color", color)
            ml = metric.lower()                       # view-name-tolerant match:
            if ml.startswith("churn rate"):           # "Churn Rate"
                slot["pct"] = cell
            elif ml.startswith("disconnect count"):   # "Disconnect Count Churn"
                slot["num"] = _num(cell)
            elif ml.startswith("activated"):          # "Activated SPE/SP"
                slot["denom"] = _num(cell)
    return {"office_total": _recompute_office_total(reps), "reps": reps}


def run(owner: str | None = None, *, dry_run: bool = False,
        verbose: bool = False) -> int:
    """Slice the shared per-rep NDS churn view to `owner`, then run the full house
    churn flow (fill this office's tab + render + post) for the wireless side."""
    global _SLICE_OWNER
    _SLICE_OWNER = owner or ""
    wl_pull.fetch_crosstab = _fetch      # monkeypatch: same module churn.run holds
    wl_pull.parse = _parse
    argv = ["--only", "wireless"]
    if dry_run:
        argv.append("--dry-run")
    return churn_run.main(argv)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics.nds_churn",
                                 description="NDS per-rep Wireless Churn "
                                 "(day-over-day, house pipeline).")
    ap.add_argument("--owner", default="Isaiah Revelle")
    ap.add_argument("date", nargs="?", default=None, help="(unused; house run "
                    "uses today — kept for CLI compatibility).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    return run(args.owner, dry_run=not args.live, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
