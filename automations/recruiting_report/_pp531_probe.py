"""Carlos PP backfill for ONLY week-ending 5/31, runnable on the mini.

The original output/pp_backfill.py is a gitignored scratch script (laptop-only,
not deployed), so this self-contained module reimplements just the 5/31 slice on
top of the TRACKED opt_phase_carlos helpers. Scoped to 5/31 on purpose: the old
PLAN's 6/7 entry pins to the dashboard's "Last Week" default, which has moved off
6/7, so re-pulling it would be wrong.

    lucy rerun carlos_pp_531                       # download + DRY-RUN preview
    (flip base_args to --write --skip-download to fill from the cached pull)

Verdict lands in `lucy status`: whether 5/31 was selectable + rep rows pulled.
Temporary — remove once 5/31 is filled (or re-confirmed still blocked).
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import sys
from pathlib import Path

os.environ.setdefault("CAPTAINSHIP", "Carlos")

from automations.recruiting_report import opt_phase_carlos as m
from automations.recruiting_report import fill
from automations.focus_office_att.daily import _q
from automations.shared.tableau_patchright import tableau_session

WE = dt.date(2026, 5, 31)
OUT = Path("output/_pp_backfill"); OUT.mkdir(parents=True, exist_ok=True)
CSV = OUT / f"pp_{WE.isoformat()}.csv"


def download() -> int:
    pp = next(v for v in m.VIEWS if v.key == "personal_production")
    with tableau_session(verbose=True) as page:
        print(f"=== download WE {WE.isoformat()} via Time Frame dropdown ===", flush=True)
        hook = m.select_time_frame_week(WE)          # raises if 5/31 not selectable
        m.download_view_crosstab(pp, CSV, week=None, page=page, pre_download_hook=hook)
    return sum(1 for _ in open(CSV, encoding="utf-16")) - 1


def parse_by_rep(path: Path) -> dict:
    with open(path, encoding="utf-16") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    headers = [h.strip() for h in rows[0]]
    rep_idx = next((i for i, h in enumerate(headers) if h.strip().lower() == "rep"), 1)
    by_rep = {}
    for r in rows[1:]:
        if len(r) <= rep_idx:
            continue
        rep = (r[rep_idx] or "").strip()
        if not rep or rep.lower() == "total":
            continue
        by_rep[rep.lower()] = {h: (r[i].strip() if i < len(r) and r[i] else "")
                               for i, h in enumerate(headers)}
    return by_rep


def _match_rep(tab: str, by_rep: dict, as_owner_map: dict):
    fb = as_owner_map.get(tab, "")
    candidates = [tab, fb] if fb and fb.lower() != tab.lower() else [tab]
    for cand in candidates:
        if cand.lower() in by_rep:
            return by_rep[cand.lower()]
    for cand in candidates:
        parts = cand.strip().split()
        if len(parts) < 2:
            continue
        first, last = parts[0].lower(), parts[-1].lower()
        for rep_key, rep_rec in by_rep.items():
            rp = rep_key.split()
            if len(rp) >= 2 and rp[0] == first and rp[-1] == last:
                return rep_rec
    return None


def apply(write: bool) -> tuple[int, int]:
    sh = fill.open_sheet()
    icd_tabs = m._carlos_icd_tabs()
    as_owner_map = m._as_owner_by_tab()
    ranges = []
    for t in icd_tabs:
        ranges += [f"{_q(t)}!1:1", f"{_q(t)}!B:B"]
    vrs = sh.values_batch_get(ranges).get("valueRanges", [])
    by_rep = parse_by_rep(CSV)
    print(f"\n===== WE {WE.isoformat()}  ({len(by_rep)} reps) "
          f"{'[WRITE]' if write else '[dry-run]'} =====")
    wrote = skipped = 0
    for i, tab in enumerate(icd_tabs):
        row1 = vrs[i * 2].get("values", [])
        col_b = [r[0] if r else "" for r in vrs[i * 2 + 1].get("values", [])]
        target_col = (fill.find_sunday_columns([row1[0]], header_row_idx=0).get(WE)
                      if row1 else None)
        pp_row = m.metric_row_for_tab(col_b, "Personal Production")
        if not target_col or not pp_row:
            skipped += 1
            continue
        rec = _match_rep(tab, by_rep, as_owner_map)
        value = m._format_carlos_pp(rec or {})
        print(f"  {tab:28} col{target_col} row{pp_row} = {value!r}"
              + ("" if rec else "   (no rep match)"))
        if write:
            ws = sh.worksheet(tab)
            for _ in m.write_icd_values(ws, {pp_row: value}, target_col, dry_run=False):
                pass
        wrote += 1
    print(f"  → {wrote} {'written' if write else 'previewed'}, {skipped} skipped")
    return wrote, skipped


def main() -> int:
    write = "--write" in sys.argv
    skip_dl = "--skip-download" in sys.argv
    try:
        n = download() if not skip_dl else (
            sum(1 for _ in open(CSV, encoding="utf-16")) - 1 if CSV.exists() else 0)
        wrote, skipped = apply(write)
    except Exception as e:  # noqa: BLE001 — report failure as the verdict
        print(f"PP531 VERDICT: ❌ 5/31 FAILED (likely still not selectable in the "
              f"Time Frame dropdown) — {type(e).__name__}: {str(e)[:120]}")
        return 1
    print(f"PP531 VERDICT: ✓ 5/31 {'WROTE to Sheet' if write else 'previewed (dry-run)'} "
          f"— {n} rep rows pulled, {wrote} tabs {'written' if write else 'previewed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
