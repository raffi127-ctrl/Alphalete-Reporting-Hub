"""Lucy-1 debug for the DD crosstab layout.

The parse came back empty because ORG DD Detail's columns don't align the way the
truncated discovery dump suggested. This downloads the sheet and writes the FULL
header + the first Captain's-Bonus rows (every column) to `_validate_out`, so the
real owner / DD-week / description / amount columns can be identified. RUN ON LUCY 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
OUT = Path("output/override_bulletin/validate")
TAB = "_validate_out"


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.override_bulletin.pulls import read_crosstab, DD_DETAIL_VIEW, DD_DETAIL_SHEET
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []
    with tableau_session(headless=True, verbose=True) as page:
        out = OUT / "dd.csv"
        download_crosstab_patchright(DD_DETAIL_VIEW, DD_DETAIL_SHEET, out,
                                     page=page, verbose=True)
        rows = read_crosstab(out)
        hdr = rows[0] if rows else []
        print(f"DD rows={len(rows)} cols={len(hdr)}", flush=True)
        # header: one row = index + name (so I can see all columns even if wide)
        dump.append(["=HEADER="] + [f"{i}:{h}" for i, h in enumerate(hdr)])
        # first rows that mention 'captain' in ANY cell — the Captain's Bonus rows
        found = 0
        for r in rows[1:]:
            if any("captain" in str(c).lower() for c in r):
                dump.append([f"CAPROW"] + [str(c) for c in r])
                found += 1
                if found >= 4:
                    break
        # also: which columns hold date-like 7/xx values, and $ amounts
        import re
        if len(rows) > 2:
            sample = rows[2]
            for i, c in enumerate(sample):
                tag = ""
                if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", str(c).strip()):
                    tag = "DATE"
                elif "$" in str(c):
                    tag = "MONEY"
                if tag:
                    dump.append(["COLTYPE", f"col{i}", tag, str(c)])
        print(f"captain rows found: {found}", flush=True)

    try:
        wb = _fill._client().open_by_key(WORKBOOK_ID)
        try:
            ws = wb.worksheet(TAB)
            ws.clear()
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(title=TAB, rows=200, cols=40)
        ws.update([[str(c)[:60] for c in row] for row in dump], "A1",
                  value_input_option="RAW")
        print(f"wrote {len(dump)} rows to {TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't write {TAB}: {type(e).__name__}: {e}", flush=True)
    print("dd-debug done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
