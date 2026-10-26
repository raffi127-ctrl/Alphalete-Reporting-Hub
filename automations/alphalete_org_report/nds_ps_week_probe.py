"""Probe: can NDS ProductSalesSummaryRep give an OWNER's sales for a PAST week?

Why (Eve 2026-10-26): JC Lopez's NDS tab needs sales for WE 9/20 and 9/27.
opt_nds --week pins only SARA + ABP, and SARA carries our org alone — JC is
outside it ("no metrics available for jc lopez"). The Personal Production
crosstab DOES carry him, but through Megan's 'This week and last' custom view,
so only two weeks at a time. This downloads the view's .csv export with a few
date-pin variants and prints, per variant, which weeks came back and the
owner's WIRELESS / AIR totals per week. Read-only: writes nothing to any Sheet.

  lucy rerun nds_ps_week_probe --owner "JC LOPEZ" --since 2026-09-14 --until 2026-10-04
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.alphalete_org_report import tableau_http
from automations.alphalete_org_report.opt_nds import OUTPUT_DIR

WORKBOOK = "NDS-SNRES-ATT-OOFWorkbook"
VIEW = "ProductSalesSummaryRep"


def _summary(path, owner: str) -> None:
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        print("    (empty)")
        return
    hdr = rows[0]
    print(f"    {len(rows) - 1} rows; columns: {hdr}")
    # Every column whose values look like dates — that is where the week lives.
    for i, h in enumerate(hdr):
        vals = {r[i] for r in rows[1:] if len(r) > i}
        if any("/" in v and v[:1].isdigit() for v in vals):
            print(f"    date-ish column {h!r}: {sorted(vals)[:30]}")
    mine = [r for r in rows[1:] if owner.lower() in " ".join(r).lower()]
    print(f"    rows for {owner!r}: {len(mine)}")
    for r in mine[:40]:
        print("     ", r)
    # Totals per (every non-numeric column combo except rep) are left to the
    # reader: the export's shape is the unknown this probe exists to show.
    agg = collections.Counter()
    for r in mine:
        try:
            v = float(r[-1].replace(",", ""))
        except ValueError:
            continue
        key = tuple(c for c in r[:-1] if "/" in c or c.upper() in
                    ("WIRELESS", "AIR", "VIDEO", "NEW INTERNET"))
        agg[key] += v
    for k, v in sorted(agg.items()):
        print(f"    total {k}: {v:g}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="JC LOPEZ")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD (a Monday)")
    ap.add_argument("--until", required=True, help="YYYY-MM-DD (a Sunday)")
    args = ap.parse_args()

    from automations.shared.tableau_patchright import (
        tableau_session, requests_session_from_page)

    variants = [
        ("default", None),
        ("min-max-date", {"Min Date": args.since, "Max Date": args.until}),
        ("sale-date", {"Sale Date": f"{args.since},{args.until}"}),
    ]
    with tableau_session(verbose=False) as page:
        s = requests_session_from_page(page)
        for name, params in variants:
            out = OUTPUT_DIR / f"nds_ps_week_probe_{name}.csv"
            print(f"\n=== {name} params={params}")
            try:
                tableau_http.download_view_csv(WORKBOOK, VIEW, out,
                                               session=s, params=params)
            except Exception as e:  # noqa: BLE001 — a probe reports, never dies
                print(f"    FAILED {type(e).__name__}: {str(e)[:200]}")
                continue
            _summary(out, args.owner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
