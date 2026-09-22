"""Read-only probe: WHICH owners does Sara Plus actually carry?

Rafael asked (2026-09-22) for a Focus Report covering every owner in the NDS
tracker, not just our org's. The NDS OPT fill then skipped most of them with
'no metrics available', and the cached crosstabs suggested Sara Plus only
carries our own ICDs. Eve: "estas buscando en una vista customizada? insisti y
buscalos como owners en sara plus summary en tableau" — so this asks Tableau
itself instead of trusting a stale csv.

Prints, for each source opt_nds fills sales from, the DISTINCT owner names in
the export, plus which NDS-tracker owners are missing from it. Writes nothing:
no Sheet, no state, just stdout (the queue keeps it in the job's Result cell).

    python -m automations.alphalete_org_report.sara_owner_probe
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path
from typing import List

from automations.alphalete_org_report import opt_nds, tableau_http
from automations.shared.tableau_patchright import (
    tableau_session,
    requests_session_from_page,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, same guard as opt_nds
    pass

OUT = opt_nds.OUTPUT_DIR / "probe_sara_owners"


def _rows(path: Path) -> List[List[str]]:
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except Exception:  # noqa: BLE001
            continue
    else:
        return []
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = "\t" if "\t" in first else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _owners(path: Path) -> List[str]:
    rows = _rows(path)
    if not rows:
        return []
    header = rows[0]
    cols = [i for i, h in enumerate(header)
            if "owner" in h.lower() or "icd" in h.lower()]
    names = set()
    for r in rows[1:]:
        for i in cols:
            v = (r[i] if i < len(r) else "").split("\r")[0].split("\n")[0].strip()
            if v and v.lower() not in ("total", "grand total"):
                names.add(v)
    return sorted(names)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tracker = sorted(opt_nds.parse_tt_detail(
        opt_nds.OUTPUT_DIR / "opt_nds_tt_detail.csv"))
    print(f"NDS tracker owners: {len(tracker)}")

    with tableau_session(verbose=False) as page:
        http = requests_session_from_page(page)
        for wb, view, fname in (
            ("DropshipV_2", "SARAPLUSSALESSUMMARY", "probe_sara_summary.csv"),
            ("DropshipV_2", "SARAPLUSSALESSUMMARYBYDAY", "probe_sara_byday.csv"),
            ("NDS-SNRES-ATT-OOFWorkbook", "ProductSalesSummaryRep",
             "probe_product_sales.csv"),
            ("NDS-SNRES-ATT-OOFWorkbook", "NDSDailyTracker",
             "probe_nds_tracker.csv"),
        ):
            out = OUT / fname
            try:
                tableau_http.download_view_csv(wb, view, out, session=http)
            except Exception as e:  # noqa: BLE001 — report, never raise
                print(f"{view}: DOWNLOAD FAILED {type(e).__name__}: {str(e)[:120]}")
                continue
            owners = _owners(out)
            norm = {opt_nds._norm_owner(o) for o in owners}
            hits = [t for t in tracker if t in norm]
            print(f"{view}: {len(owners)} owner(s) in the export; "
                  f"{len(hits)}/{len(tracker)} tracker owners present")
            print(f"  owners: {', '.join(owners)}")
            missing = [t for t in tracker if t not in norm]
            print(f"  tracker owners MISSING: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
