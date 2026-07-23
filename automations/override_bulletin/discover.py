"""One-shot Lucy-1 discovery for the override-fill Tableau views.

Lists each view's Crosstab worksheet names and dumps the downloaded structure
(headers + first rows) to stdout — read back with `lucy logtail`. Downloads with
DEFAULT filters; the period/owner selection is layered on in the pull modules
once the structure is known. Nothing is written to any sheet.

RUN ON LUCY 1 (Raf's login — only Raf's org views see the whole downline):
  lucy rerun override_discover
  lucy logtail rerun-<ts>-override_discover
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

OUT = Path("output/override_bulletin/discover")

VIEWS = [
    ("ORG_OVERRIDE_SUMMARY",
     "https://us-east-1.online.tableau.com/#/site/sci/views/"
     "OverridesICDView/ORGOVERRIDESUMMARY"),
    ("RAF_OVERRIDE_BONUS",
     "https://us-east-1.online.tableau.com/#/site/sci/views/"
     "ResATTSpecialDealOverride-Raf/RafOverrideBonus"),
    ("DD_DETAIL_ORG",
     "https://us-east-1.online.tableau.com/#/site/sci/views/"
     "DirectDepositICDVIEWVersion2_0/DDDETAILORG"),
    ("NETSUITE_SECURITY_LEDGER",
     "https://us-east-1.online.tableau.com/#/site/sci/views/"
     "OverridesICDView/NETSUITESECURITYLEDGERSFDC"),
]


def _dump_csv(path: Path, n: int = 18) -> None:
    from automations.override_bulletin.pulls import read_crosstab
    try:
        rows = read_crosstab(path)
    except Exception as e:  # noqa: BLE001
        print(f"    (couldn't read csv: {e})", flush=True)
        return
    print(f"    {len(rows)} rows x {max((len(r) for r in rows), default=0)} cols",
          flush=True)
    for i, r in enumerate(rows[:n]):
        print(f"    row{i}: {r[:9]}", flush=True)


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.recruiting_report.opt_phase import list_crosstab_sheets
    only = set(argv or [])
    OUT.mkdir(parents=True, exist_ok=True)
    with tableau_session(headless=True, verbose=True) as page:
        for name, url in VIEWS:
            if only and name not in only:
                continue
            print(f"\n===== {name} =====", flush=True)
            try:
                sheets = list_crosstab_sheets(url, page=page, verbose=True)
                print(f"  crosstab sheets ({len(sheets)}): {sheets}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  list_crosstab_sheets FAILED: "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:120]}", flush=True)
                continue
            if not sheets:
                continue
            sheet = sheets[0]
            out = OUT / f"{name}.csv"
            try:
                download_crosstab_patchright(url, sheet, out, page=page, verbose=True)
                print(f"  downloaded {sheet!r}:", flush=True)
                _dump_csv(out)
            except Exception as e:  # noqa: BLE001
                print(f"  download FAILED: "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:120]}", flush=True)
    print("\ndiscovery done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
