"""Probe the SARAPLUSSALESSUMMARY / AkibMJSummary custom view to find the
activate_xy that pulls the per-Costco-store breakdown (instead of the
National Summary primary worksheet).

Run: .venv/bin/python -m automations.alphalete_org_report._probe_akib_mj_summary
"""
from __future__ import annotations

import csv
from pathlib import Path

from automations.recruiting_report.opt_phase import _scrape_one_view_data
from automations.shared.tableau_patchright import tableau_session


URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DropshipV_2/SARAPLUSSALESSUMMARY/"
    "843e051c-f343-4bfd-842e-da0fc67db111/AkibMJSummary"
    "?:iid=1&Max%20Date=2026-05-24&Min%20Date=2026-05-18"
)
WORKSPACE = Path(__file__).resolve().parent.parent.parent
OUT_DIR = WORKSPACE / "output"


def _short(s, n=18):
    s = str(s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Sweep activate_xy across the dashboard. The Tableau viz iframe usually
    # has a Program Overview band at the top (y~0.2-0.4) and detail tables
    # lower; try multiple positions + report cols/rows for each.
    CANDIDATES = [
        (0.50, 0.30),
        (0.50, 0.45),
        (0.50, 0.55),
        (0.50, 0.65),
        (0.50, 0.78),
        (0.50, 0.88),
        (0.25, 0.55),
        (0.75, 0.55),
    ]
    best_fields, best_recs, best_xy = [], [], None
    with tableau_session(verbose=True) as page:
        for xy in CANDIDATES:
            print(f"\n=== activate_xy={xy} ===", flush=True)
            try:
                fields, recs = _scrape_one_view_data(
                    page, page.context, URL,
                    verbose=False, activate_xy=xy)
            except Exception as e:
                print(f"  ✗ {type(e).__name__}: {e}", flush=True)
                continue
            print(f"  cols={len(fields)} rows={len(recs)}", flush=True)
            # Show first 3 cells of header
            print(f"  header[:3] = {fields[:3]}", flush=True)
            if recs:
                print(f"  row[0][:3] = {recs[0][:3]}", flush=True)
            # Track widest+tallest as the "interesting" one
            if (len(fields) > 2 and len(recs) > len(best_recs)):
                best_fields, best_recs, best_xy = fields, recs, xy

    print(f"\n=== WINNER: {best_xy}  ({len(best_fields)} cols × {len(best_recs)} rows) ===")
    print("Headers:")
    for i, h in enumerate(best_fields):
        print(f"  [{i:2}] {h}")
    print("First 15 rows:")
    for r in best_recs[:15]:
        print("  " + " | ".join(_short(c, 14) for c in r))

    out_csv = OUT_DIR / "probe_akib_mj_summary.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(best_fields)
        w.writerows(best_recs)
    print(f"\nSaved best scrape -> {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
