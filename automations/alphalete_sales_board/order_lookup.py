"""Look a sale up in Tableau -- READ-ONLY, for checking a sale transfer.

When the form and the board disagree (Gabe Caldwell <- Hank Tran, 1 DTV "on
10/27", but the board has Hank's only DTV on 10/29), the D2D ORDER LOG says
which rep the order sits on and its real order date. Pulls the same
"A.Order Log" crosstab country_metrics reads, for the date range given, and
prints every row that matches any needle (rep name, customer, order / SPM #).
Writes nothing, posts nothing.

    python -m automations.alphalete_sales_board.order_lookup \
        --start 2026-10-25 --end 2026-10-31 "Hank Tran" "Caldwell" 280927557

Runs on a Lucy (warm Tableau session), not the laptop.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.country_metrics.pull import ORDERLOG_SHEET, ORDERLOG_URL_TMPL
from automations.recruiting_report import opt_phase

# Printed for every hit, when the column exists. Others are left out so the
# result fits the Mini Control row.
SHOW = ("Order Date", "Rep", "Owner Name", "Product Type (Broken Out)",
        "DTR Status", "Customer", "SPM", "Order")


def _rows(path: Path):
    b = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            return [ln.split("\t") for ln in b.decode(enc).splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("could not decode %s" % path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("needles", nargs="+", help="rep / customer / order # to find")
    a = ap.parse_args(argv)

    out = Path(tempfile.mkdtemp()) / "orderlog.csv"
    opt_phase.download_crosstab(ORDERLOG_URL_TMPL.format(start=a.start, end=a.end),
                                ORDERLOG_SHEET, out, verbose=False)
    rows = _rows(out)
    hdr = [h.strip() for h in rows[0]]
    keep = [i for i, h in enumerate(hdr) if any(s.lower() in h.lower() for s in SHOW)]
    needles = [n.strip().lower() for n in a.needles if n.strip()]
    print("order log %s..%s: %d rows" % (a.start, a.end, len(rows) - 1))
    hits = 0
    for r in rows[1:]:
        line = "|".join(r).lower()
        if not any(n in line for n in needles):
            continue
        hits += 1
        print("HIT " + " ; ".join("%s=%s" % (hdr[i], r[i].strip())
                                  for i in keep if i < len(r) and r[i].strip()))
    print("%d hit(s) for %s" % (hits, ", ".join(a.needles)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
