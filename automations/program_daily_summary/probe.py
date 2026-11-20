"""READ-ONLY probe: which worksheet of each COUNTRY tracker gives sales by day?

Program Daily Summary needs a per-day COUNTRY total for Fiber, NDS and B2B. The
Fiber one is known (D2D1-PAGERV4 -> 'Sales By ICD (ATT) (V2)', owner x day, the
Country Sales Board's own pull). NDS and B2B are not: we don't know their
worksheet names. For each view this asks the Crosstab dialog for a sheet that
does not exist — the error lists every worksheet it has — then downloads each
one whose name looks like sales/daily and prints its header + total rows.
Writes no Sheet, posts nothing.

  lucy rerun program_daily_summary_probe
"""
from __future__ import annotations

import csv
import io
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console
    pass

from pathlib import Path

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"
VIEWS = {
    "Fiber (D2D1-PAGERV4)": _BASE + "ATTTRACKER2_1-D2D/D2D1-PAGERV4?:iid=1",
    "NDS (NDSDailyTracker)": _BASE + "NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1",
    "B2B AT&T (D2D1-PAGERV3)": _BASE + ("ATTTRACKER-B2B/D2D1-PAGERV3/"
                                        "87ae0671-15de-4d80-bdc0-702d0946dd1d/"
                                        "B2BLeaderRecognition?:iid=1"),
    "B2B D2D Consolidated": _BASE + "ATTD2D_B2Bconsolidated/B2B_D2D1-PAGER?:iid=1",
    "BOX (BoxDailyTracker)": _BASE + "B2BBOXEnergyTracker/BoxDailyTracker?:iid=1",
}
_WANT = re.compile(r"sale|daily|day|icd|owner|summary|total", re.I)
OUT = Path(__file__).resolve().parents[2] / "output" / "program_daily_probe"


def _rows(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _sheet_names(err: str):
    """Sheet names out of "… saw N thumb(s): ['A', 'B']. The view may …"."""
    m = re.search(r"saw \d+ thumb\(s\):\s*(\[[^\]]*\])", err, re.S)
    if not m:
        return []
    import ast
    try:
        return [str(x) for x in ast.literal_eval(m.group(1))]
    except (ValueError, SyntaxError):
        return []


def main() -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    OUT.mkdir(parents=True, exist_ok=True)
    with tableau_session(verbose=False) as page:
        for label, url in VIEWS.items():
            print(f"\n######## {label}\n  {url}", flush=True)
            try:
                download_crosstab_patchright(url, "__no_such_sheet__",
                                             OUT / "x.csv", page=page,
                                             verbose=False)
                names = []
            except Exception as e:  # noqa: BLE001 — the error IS the answer
                names = _sheet_names(str(e))
                if not names:
                    print(f"  could not list sheets: {str(e)[:300]}")
            print(f"  worksheets: {names}")
            for sheet in [n for n in names if _WANT.search(n)][:8]:
                safe = re.sub(r"[^\w]+", "_", f"{label}_{sheet}")[:80]
                out = OUT / f"{safe}.csv"
                try:
                    download_crosstab_patchright(url, sheet, out, page=page,
                                                 verbose=False)
                except Exception as e:  # noqa: BLE001 — a probe reports
                    print(f"  [{sheet}] FAILED {str(e)[:200]}")
                    continue
                rows = _rows(out)
                print(f"  [{sheet}] {len(rows)} rows -> {out.name}")
                for r in rows[:3]:
                    print("     H", r[:16])
                for r in rows:
                    if any("total" in c.lower() for c in r[:4]):
                        print("     T", r[:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())
