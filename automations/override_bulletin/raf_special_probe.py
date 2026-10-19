"""Read-only probe: what is inside Rafael's Special Override (Raf-wow view).

The bulletin only reads the single 'Raf Payout Total' row of `Payout- Raf wow`.
His special fell from ~$37k/wk (August) to ~$30k/wk (late Sept / Oct), and that
one row can't say why. This downloads EVERY crosstab sheet of the view for the
last few retail periods and dumps the rows (all of them, wide) to the throwaway
tab `_raf_special_probe` so the components can be compared week over week.

Writes only to `_raf_special_probe`. No fill, no send.

RUN ON LUCY 1 (Raf's login):
  lucy rerun raf_special_probe
"""
from __future__ import annotations

import sys
from pathlib import Path

OUT = Path("output/override_bulletin/raf_special_probe")
WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DUMP_TAB = "_raf_special_probe"
DUMP_W = 30          # columns kept per row
DUMP_ROWS = 80       # rows kept per sheet per period
PERIODS = ["Period 7", "Period 8", "Period 9", "Period 10"]
MAX_SHEETS = 8


def _pad(row, w=DUMP_W):
    r = [str(c)[:60] for c in row[:w]]
    return r + [""] * (w - len(r))


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import tableau_session
    from automations.recruiting_report.opt_phase import list_crosstab_sheets
    from automations.override_bulletin import pulls as P
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    with tableau_session(headless=True, verbose=True) as page:
        sheets = []
        for attempt in (1, 2):
            try:
                sheets = list_crosstab_sheets(
                    P._with_filter(P.RAF_BONUS_VIEW, "Period", PERIODS[-1]),
                    page=page, verbose=True,
                    settle_s=8 * attempt, max_s=60 * attempt)
            except Exception as e:  # noqa: BLE001
                print(f"  list_crosstab_sheets FAILED (try {attempt}): "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:120]}", flush=True)
            if sheets:
                break
        sheets = sheets or [P.RAF_BONUS_SHEET]
        print(f"crosstab sheets ({len(sheets)}): {sheets}", flush=True)
        dump.append(_pad(["SHEETS", str(sheets)]))

        for period in PERIODS:
            for sheet in sheets[:MAX_SHEETS]:
                tag = f"{period} | {sheet}"
                out = OUT / f"{period}_{sheet}.csv".replace("/", "-").replace(" ", "_")
                try:
                    rows, used = P._download_first_nonempty(
                        P.RAF_BONUS_VIEW, sheet, out, P.period_candidates(period),
                        page=page, verbose=True,
                        accept=lambda rs: rs if len(rs) > 1 else None)
                except Exception as e:  # noqa: BLE001
                    print(f"  {tag} FAILED: {type(e).__name__}", flush=True)
                    dump.append(_pad([f"== {tag} FAILED", type(e).__name__]))
                    continue
                rows = rows or []
                print(f"  {tag}: {len(rows)} rows (filter {used!r})", flush=True)
                dump.append(_pad([f"== {tag}", f"{len(rows)}rows", f"used={used}"]))
                for r in rows[:DUMP_ROWS]:
                    dump.append(_pad(list(r)))
                dump.append(_pad([""]))

    try:
        wb = _fill._client().open_by_key(WORKBOOK_ID)
        try:
            ws = wb.worksheet(DUMP_TAB)
            ws.clear()
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(title=DUMP_TAB, rows=max(200, len(dump) + 10),
                                  cols=DUMP_W)
        if ws.row_count < len(dump) + 10:
            ws.resize(rows=len(dump) + 10, cols=DUMP_W)
        ws.update(dump, "A1", value_input_option="RAW")
        print(f"\nwrote {len(dump)} rows to {DUMP_TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"\ncouldn't write {DUMP_TAB}: {type(e).__name__}: {e}", flush=True)
        return 1
    print("probe done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
