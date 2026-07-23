"""Lucy-1 validation for the three remaining override pulls, in ONE run:
  1. DD captain overrides — content-based parse; per-captain per-week amounts
     (compare Carlos ~7.12 to the sheet's $10,875).
  2. RAF special override — Period-filtered crosstab, 'Raf Payout Total' row.
  3. Regular overrides — Period-filtered ORG summary, per-owner week sum.
Writes results to `_validate_out`. RUN ON LUCY 1 (Raf's login).
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
OUT = Path("output/override_bulletin/validate")
TAB = "_validate_out"

CAPTAINS = ["Rafael Hidalgo", "Carlos Hidalgo", "Colten Wright",
            "Khalil Mansour", "Jairo Ruiz", "Eveliz Wright"]


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import tableau_session
    from automations.override_bulletin import pulls as P
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    def row(*cells):
        dump.append([str(c) for c in cells])

    with tableau_session(headless=True, verbose=True) as page:
        # 1) DD captain overrides — all weeks, per captain
        row("=DD CAPTAIN OVERRIDES (per week; expect Carlos 7.12 ~= 10875)=")
        try:
            dd = P.dd_captain_overrides(CAPTAINS, OUT / "dd.csv", page=page, verbose=True)
            for owner in sorted(dd):
                wks = dd[owner]
                row(owner, *[f"{w}={a}" for w, a in sorted(wks.items())])
        except Exception as e:  # noqa: BLE001
            row("DD FAILED", type(e).__name__, str(e)[:200])

        # 2) RAF special override — Period-filtered
        row("=RAF SPECIAL (Period 7; expect 7/12 = 39522, 7/5 = 26950)=")
        for period in ("Period 7", "Period 2026-7"):
            try:
                v12 = P.raf_special_override("7/12/2026", OUT / "raf.csv",
                                             period=period, page=page, verbose=True)
                v5 = P.raf_special_override("7/5/2026", OUT / "raf.csv",
                                            period=period, page=page, verbose=True)
                row(f"period={period!r}", f"7/12={v12}", f"7/5={v5}")
            except Exception as e:  # noqa: BLE001
                row(f"RAF FAILED period={period!r}", type(e).__name__, str(e)[:160])

        # 3) Regular overrides — Period-filtered ORG summary
        row("=REGULAR OVERRIDES (ORG summary; # owners found)=")
        for period in ("Period 2026-7", "Period 7"):
            try:
                reg = P.regular_overrides("7/12/2026", OUT / "org.csv",
                                          period=period, page=page, verbose=True)
                sample = sorted(reg.items(), key=lambda kv: -kv[1])[:6]
                row(f"period={period!r}", f"{len(reg)} owners",
                    *[f"{k}={v}" for k, v in sample])
            except Exception as e:  # noqa: BLE001
                row(f"REGULAR FAILED period={period!r}", type(e).__name__, str(e)[:160])

    try:
        wb = _fill._client().open_by_key(WORKBOOK_ID)
        try:
            ws = wb.worksheet(TAB)
            ws.clear()
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(title=TAB, rows=200, cols=40)
        ws.update([[str(c)[:80] for c in r] for r in dump], "A1", value_input_option="RAW")
        print(f"wrote {len(dump)} rows to {TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't write {TAB}: {type(e).__name__}: {e}", flush=True)
    print("validate done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
