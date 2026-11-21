"""READ-ONLY probe: where is LAST WEEK's country NDS / B2B by day?

The board's NDS/B2B pulls use the BASE views pinned to the reporting week; a
last-week pin empties the worksheet there. This looks for a last-week sheet
instead (the way Fiber has 'Sales By ICD (ATT) (V2) (LW2)'). ONE attempt per
view (no 3x retry — the first version of this probe ran past its timeout and
held Lucy 1's queue): ask the Crosstab dialog for a sheet that doesn't exist,
print the FULL list of worksheets it offers, then download the ones that look
like last week and print their header + total rows. Writes no Sheet.

  lucy rerun program_daily_summary_probe
"""
from __future__ import annotations

import ast
import csv
import io
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console
    pass

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"
VIEWS = {
    "B2B base": _BASE + "ATTTRACKER-B2B/D2D1-PAGERV3",
    "NDS base": _BASE + "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep",
    "NDS tracker": _BASE + "NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker",
}
_LW = re.compile(r"\bLW\d?\b|last\s*week|prior", re.I)
OUT = Path(__file__).resolve().parents[2] / "output" / "program_daily_probe"


def _rows(path: Path):
    raw = path.read_bytes()
    text = ""
    for enc in ("utf-16", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _sheet_names(err: str):
    m = re.search(r"saw \d+ thumb\(s\):\s*(\[[^\]]*\])", err, re.S)
    if not m:
        return []
    try:
        return [str(x) for x in ast.literal_eval(m.group(1))]
    except (ValueError, SyntaxError):
        return []


def _once(page, url, sheet, out):
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    return drive_crosstab_dialog(page, url + "?:refresh=yes", sheet, out,
                                 verbose=False)


def main() -> int:
    from automations.shared.tableau_patchright import tableau_session
    OUT.mkdir(parents=True, exist_ok=True)
    with tableau_session(verbose=False) as page:
        for label, url in VIEWS.items():
            print(f"\n######## {label}  {url}", flush=True)
            try:
                _once(page, url, "__no_such_sheet__", OUT / "x.csv")
                names = []
            except Exception as e:  # noqa: BLE001 — the error IS the answer
                names = _sheet_names(str(e))
                if not names:
                    print(f"  could not list sheets: {str(e)[:600]}")
            print(f"  worksheets ({len(names)}): {names}", flush=True)
            for sheet in [n for n in names if _LW.search(n)][:4]:
                out = OUT / (re.sub(r"[^\w]+", "_", f"{label}_{sheet}")[:80] + ".csv")
                try:
                    _once(page, url, sheet, out)
                except Exception as e:  # noqa: BLE001 — a probe reports
                    print(f"  [{sheet}] FAILED {str(e)[:300]}")
                    continue
                rows = _rows(out)
                print(f"  [{sheet}] {len(rows)} rows")
                for r in rows[:3]:
                    print("     H", r[:14])
                for r in rows:
                    if any("total" in c.lower() for c in r[:3]):
                        print("     T", r[:14])
    return 0


if __name__ == "__main__":
    sys.exit(main())
