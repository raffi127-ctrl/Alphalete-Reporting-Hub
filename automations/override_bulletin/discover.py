"""One-shot Lucy-1 discovery for the override-fill Tableau views.

Lists each view's Crosstab worksheet names and dumps the downloaded structure
(headers + first rows) BOTH to stdout and to a Google-Sheet tab `_discover_out`
in the override workbook — so the full structure is readable from anywhere
without paging the log through `lucy logtail`. Downloads with DEFAULT filters;
period/owner selection is layered on in the pull modules once the structure is
known. Writes only to the throwaway `_discover_out` tab.

RUN ON LUCY 1 (Raf's login — only Raf's org views see the whole downline):
  lucy rerun override_discover
"""
from __future__ import annotations

import sys
from pathlib import Path

OUT = Path("output/override_bulletin/discover")
WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DUMP_TAB = "_discover_out"
DUMP_W = 12          # columns written per row (crosstab rows truncated to this)
DUMP_ROWS = 24       # crosstab rows dumped per view

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


def _pad(row, w=DUMP_W):
    r = [str(c)[:40] for c in row[:w]]
    return r + [""] * (w - len(r))


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.recruiting_report.opt_phase import list_crosstab_sheets
    from automations.override_bulletin.pulls import read_crosstab
    from automations.recruiting_report import fill as _fill
    only = set(argv or [])
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []                                  # rows to write to _discover_out

    with tableau_session(headless=True, verbose=True) as page:
        for name, url in VIEWS:
            if only and name not in only:
                continue
            print(f"\n===== {name} =====", flush=True)
            dump.append(_pad([f"===== {name} ====="]))
            sheets = []
            for attempt in (1, 2):                 # 2nd attempt: longer settle
                try:
                    sheets = list_crosstab_sheets(
                        url, page=page, verbose=True,
                        settle_s=8 * attempt, max_s=60 * attempt)
                except Exception as e:  # noqa: BLE001
                    print(f"  list_crosstab_sheets FAILED (try {attempt}): "
                          f"{type(e).__name__}: {str(e).splitlines()[0][:120]}", flush=True)
                if sheets:
                    break
            print(f"  crosstab sheets ({len(sheets)}): {sheets}", flush=True)
            dump.append(["SHEETS", str(sheets)] + [""] * (DUMP_W - 2))   # FULL, untruncated
            # Dump the first few rows of EVERY sheet so we can see which holds the
            # data (default-first grabbed a title/summary sheet last time).
            for sheet in (sheets or [""])[:6]:
                out = OUT / f"{name}_{(sheet or 'default')}.csv".replace("/", "-")
                try:
                    download_crosstab_patchright(url, sheet, out, page=page, verbose=True)
                    rows = read_crosstab(out)
                    print(f"  {sheet!r}: {len(rows)} rows x "
                          f"{max((len(r) for r in rows), default=0)} cols", flush=True)
                    dump.append(_pad([f"SHEET={sheet!r}", f"{len(rows)}rows"]))
                    for i, r in enumerate(rows[:5]):        # 5 rows per sheet
                        dump.append(_pad([f"r{i}"] + list(r), DUMP_W))
                except Exception as e:  # noqa: BLE001
                    print(f"  {sheet!r} FAILED: {type(e).__name__}: "
                          f"{str(e).splitlines()[0][:120]}", flush=True)
                    dump.append(_pad([f"SHEET={sheet!r} FAILED", f"{type(e).__name__}"]))
            dump.append(_pad([""]))

    # write the dump to the throwaway tab
    try:
        wb = _fill._client().open_by_key(WORKBOOK_ID)
        try:
            ws = wb.worksheet(DUMP_TAB)
            ws.clear()
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(title=DUMP_TAB, rows=max(200, len(dump) + 10),
                                  cols=DUMP_W)
        ws.update(dump, "A1", value_input_option="RAW")
        print(f"\nwrote {len(dump)} rows to {DUMP_TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"\ncouldn't write {DUMP_TAB}: {type(e).__name__}: {e}", flush=True)
    print("discovery done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
