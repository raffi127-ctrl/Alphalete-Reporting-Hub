"""One-shot probe: scrape the UNFILTERED Fiber Penetration-by-Zip view to
see how the new owner-subtotal rows look (column headers, row-tag
shape). The output drives the bulk-replacement of the slow per-ICD
loop in download_fiber.

Run: .venv/bin/python -m automations.recruiting_report._probe_fiber

Prints column headers, first 30 rows, total row count, and a count of
rows that look like owner-subtotals (Account_Owner set + zip/lead-zip
columns blank). Also saves the full grid to output/fiber_probe.csv.
"""
from __future__ import annotations

import csv
from pathlib import Path

from automations.recruiting_report.opt_phase import (
    FIBER_VIEW_URL,
    FIBER_OVERVIEW_XY,
    _scrape_one_view_data,
)
from automations.shared.tableau_patchright import tableau_session


WORKSPACE = Path(__file__).resolve().parent.parent.parent
OUT_CSV = WORKSPACE / "output" / "fiber_probe.csv"


def _snippet(s: str, n: int = 24) -> str:
    s = str(s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    print(f"-> loading UNFILTERED Fiber view: {FIBER_VIEW_URL}", flush=True)
    # v1 probe showed (0.45, 0.45) activates the Program Overview box —
    # we got 4 grand-total measure rows (Penetration / Sales / Leads /
    # Zips). What we WANT is the by-zip table lower on the dashboard,
    # which has the new owner-subtotal rows. Try a sweep of activate_xy
    # positions further down + report which one yields the most rows.
    # Try header-row XY positions first — clicking a data cell selects that
    # mark and Tableau scopes View Data to it (saw this in probe v2: all 93
    # rows were one owner). The table header has no marks, so a click there
    # activates the worksheet without filtering.
    CANDIDATE_XYS = [
        (0.50, 0.55),   # just below Program Overview — likely table title
        (0.50, 0.58),   # column-header band
        (0.50, 0.60),   # column-header band (slightly lower)
        (0.30, 0.58),   # left side of header
        (0.50, 0.65),   # OLD winner — kept as sanity comparison
    ]
    best_fields, best_recs, best_xy = [], [], None
    with tableau_session(verbose=True) as page:
        for xy in CANDIDATE_XYS:
            print(f"\n=== probing activate_xy={xy} ===", flush=True)
            try:
                fields, recs = _scrape_one_view_data(
                    page, page.context, FIBER_VIEW_URL,
                    verbose=True, activate_xy=xy)
            except Exception as e:
                print(f"  ✗ failed: {type(e).__name__}: {e}", flush=True)
                continue
            print(f"  -> {len(fields)} cols × {len(recs)} rows", flush=True)
            if len(recs) > len(best_recs):
                best_fields, best_recs, best_xy = fields, recs, xy
    fields, recs = best_fields, best_recs
    print(f"\n=== WINNER: activate_xy={best_xy} "
          f"({len(fields)} cols × {len(recs)} rows) ===", flush=True)

    print()
    print("=" * 70)
    print(f"COLUMN HEADERS ({len(fields)}):")
    for i, f in enumerate(fields):
        print(f"  [{i:2}] {f}")
    print()
    print(f"TOTAL ROWS: {len(recs)}")
    print()
    print(f"FIRST {min(30, len(recs))} ROWS (truncated cells):")
    print("-" * 70)
    if fields:
        print("  " + " | ".join(_snippet(h, 16) for h in fields))
        print("  " + "-" * 70)
    for r in recs[:30]:
        print("  " + " | ".join(_snippet(c, 16) for c in r))
    print("-" * 70)

    # Subtotal-row heuristic: per memory, owner subtotal rows have
    # Account_Owner set + the per-zip measure columns blank. Try to
    # detect by looking for an "owner" column + checking which rows
    # have blanks in the columns that look like zip/lead-zip ids.
    owner_col = next(
        (i for i, f in enumerate(fields)
         if "owner" in f.lower() or "account" in f.lower()),
        None,
    )
    zip_col = next(
        (i for i, f in enumerate(fields)
         if "zip" in f.lower() or "postal" in f.lower()),
        None,
    )
    if owner_col is not None and zip_col is not None:
        subtotal_like = sum(
            1 for r in recs
            if len(r) > max(owner_col, zip_col)
               and (r[owner_col] or "").strip()
               and not (r[zip_col] or "").strip()
        )
        print(f"\nHEURISTIC subtotal-row count (Account_Owner set + "
              f"{fields[zip_col]!r} blank): {subtotal_like} / {len(recs)}")
    else:
        print("\nHEURISTIC: couldn't auto-find Owner/Zip columns to count "
              "subtotal rows.")

    print(f"\n-> saving full grid to {OUT_CSV}", flush=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        w.writerows(recs)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
