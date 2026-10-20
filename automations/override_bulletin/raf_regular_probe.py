"""Read-only probe: what makes up Rafael's REGULAR override (ORG Override Summary).

The fill only sums Rafael's campaign rows into one number per week. This
downloads every crosstab sheet of the ORG Override Summary view for the given
periods and dumps Rafael's block (his name row + its blank-col-A continuation
rows) plus the header rows to the throwaway tab `_raf_regular_probe`, so the
per-campaign / per-line detail can be read week over week.

Writes only to `_raf_regular_probe`. No fill, no send.

RUN ON LUCY 1 (Raf's login):
  lucy rerun raf_regular_probe                       # Period 2026-9 + 2026-10
  lucy rerun raf_regular_probe "Period 2026-10"      # explicit periods
"""
from __future__ import annotations

import sys
from pathlib import Path

OUT = Path("output/override_bulletin/raf_regular_probe")
WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DUMP_TAB = "_raf_regular_probe"
DUMP_W = 30
HEADER_ROWS = 4
MAX_SHEETS = 8
DEFAULT_PERIODS = ["Period 2026-9", "Period 2026-10"]
NEEDLE = "rafael hidalgo"


def _pad(row, w=DUMP_W):
    r = [str(c)[:60] for c in row[:w]]
    return r + [""] * (w - len(r))


def _raf_block(rows):
    """Header rows + Rafael's name row and the continuation rows under it."""
    out = [r for r in rows[:HEADER_ROWS]]
    inside = False
    for r in rows[HEADER_ROWS:]:
        first = (r[0] if r else "").strip()
        low = " ".join(str(c).lower() for c in r[:3])
        if NEEDLE in low:
            inside = True
            out.append(r)
            continue
        if inside:
            if first:                      # next owner's group starts
                inside = False
                continue
            out.append(r)
    return out


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import tableau_session
    from automations.recruiting_report.opt_phase import list_crosstab_sheets
    from automations.override_bulletin import pulls as P
    from automations.recruiting_report import fill as _fill
    periods = [a for a in (argv or []) if a.strip()] or DEFAULT_PERIODS
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    with tableau_session(headless=True, verbose=True) as page:
        sheets = []
        for attempt in (1, 2):
            try:
                sheets = list_crosstab_sheets(
                    P._with_filter(P.ORG_SUMMARY_VIEW, "Period", periods[-1]),
                    page=page, verbose=True,
                    settle_s=8 * attempt, max_s=60 * attempt)
            except Exception as e:  # noqa: BLE001
                print(f"  list_crosstab_sheets FAILED (try {attempt}): "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:120]}", flush=True)
            if sheets:
                break
        sheets = sheets or [P.ORG_SUMMARY_SHEET]
        print(f"crosstab sheets ({len(sheets)}): {sheets}", flush=True)
        dump.append(_pad(["SHEETS", str(sheets)]))

        for period in periods:
            for sheet in sheets[:MAX_SHEETS]:
                tag = f"{period} | {sheet}"
                out = OUT / f"{period}_{sheet}.csv".replace("/", "-").replace(" ", "_")
                try:
                    rows, used = P._download_first_nonempty(
                        P.ORG_SUMMARY_VIEW, sheet, out, P.period_candidates(period),
                        page=page, verbose=True,
                        accept=lambda rs: rs if len(rs) > 1 else None)
                except Exception as e:  # noqa: BLE001
                    print(f"  {tag} FAILED: {type(e).__name__}", flush=True)
                    dump.append(_pad([f"== {tag} FAILED", type(e).__name__]))
                    continue
                rows = rows or []
                block = _raf_block(rows)
                print(f"  {tag}: {len(rows)} rows, {len(block)} kept (filter {used!r})",
                      flush=True)
                dump.append(_pad([f"== {tag}", f"{len(rows)}rows", f"used={used}"]))
                for r in block:
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
