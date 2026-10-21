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
    args = [a for a in (argv or []) if a.strip()]
    if "--views" in args:
        return _views_mode([a for a in args if a != "--views"])
    periods = args or DEFAULT_PERIODS
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


WORKBOOK_REPO = "overridesicdview"
VIEWS_CHUNK = 6          # a tableau_session dies after ~8 downloads
VIEWS_MAX_DOWNLOADS = 24
VIEWS_KEEP_HITS = 40


def _views_mode(args) -> int:
    """`--views [period]`: list EVERY view of the OverridesICDView workbook and
    its crosstab sheets, download each sheet with the Period filter, and keep
    the header rows + Rafael's rows. Finds where (if anywhere) his regular
    override is broken out by the downline owner who generated it."""
    import os
    from automations.shared.tableau_patchright import tableau_session
    from automations.recruiting_report.opt_phase import list_crosstab_sheets
    from automations.recruiting_report.probe_quantum_views import _call, _views, BASE
    from automations.override_bulletin import pulls as P
    from automations.recruiting_report import fill as _fill
    period = args[0] if args else DEFAULT_PERIODS[-1]
    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    dump, todo = [_pad(["VIEWS MODE", period])], []

    with tableau_session(headless=True, verbose=True) as page:
        page.goto(BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        st, data = _call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 500}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        wb = next((w for w in wbs
                   if (w.get("repositoryUrl") or "").casefold() == WORKBOOK_REPO), None)
        if not wb:
            print(f"OverridesICDView NOT found among {len(wbs)} workbooks (HTTP {st})")
            dump.append(_pad(["WORKBOOK NOT FOUND", str(len(wbs))]))
        else:
            for name, url in _views(page, wb):
                try:
                    sheets = list_crosstab_sheets(
                        P._with_filter(url, "Period", period), page=page)
                except Exception as e:  # noqa: BLE001
                    sheets = []
                    print(f"V|{name}|LIST FAILED {type(e).__name__}", flush=True)
                print(f"V|{name}|{sheets}", flush=True)
                dump.append(_pad([f"VIEW {name}", url, str(sheets)]))
                todo += [(name, url, s) for s in sheets]

    todo = todo[:VIEWS_MAX_DOWNLOADS]
    for i in range(0, len(todo), VIEWS_CHUNK):
        try:
            with tableau_session(headless=True, verbose=False) as page:
                for j, (name, url, sheet) in enumerate(todo[i:i + VIEWS_CHUNK], start=i):
                    out = OUT / f"view_{j:02d}.csv"
                    tag = f"{name} | {sheet}"
                    try:
                        rows, used = P._download_first_nonempty(
                            url, sheet, out, P.period_candidates(period),
                            page=page, verbose=False,
                            accept=lambda rs: rs if len(rs) > 1 else None)
                    except Exception as e:  # noqa: BLE001
                        print(f"S|{tag}|FAILED {type(e).__name__}", flush=True)
                        dump.append(_pad([f"== {tag} FAILED", type(e).__name__]))
                        continue
                    rows = rows or []
                    hits = [r for r in rows[HEADER_ROWS:]
                            if NEEDLE in " ".join(str(c) for c in r).casefold()]
                    print(f"S|{tag}|rows={len(rows)}|raf={len(hits)}", flush=True)
                    dump.append(_pad([f"== {tag}", f"{len(rows)}rows",
                                      f"raf={len(hits)}", f"used={used}"]))
                    for r in rows[:HEADER_ROWS] + hits[:VIEWS_KEEP_HITS]:
                        dump.append(_pad(list(r)))
                    dump.append(_pad([""]))
        except Exception as e:  # noqa: BLE001
            print(f"batch {i // VIEWS_CHUNK} died: {type(e).__name__}", flush=True)

    wb_out = _fill._client().open_by_key(WORKBOOK_ID)
    try:
        ws = wb_out.worksheet(DUMP_TAB)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = wb_out.add_worksheet(title=DUMP_TAB, rows=max(200, len(dump) + 10),
                                  cols=DUMP_W)
    if ws.row_count < len(dump) + 10:
        ws.resize(rows=len(dump) + 10, cols=DUMP_W)
    ws.update(dump, "A1", value_input_option="RAW")
    print(f"\nwrote {len(dump)} rows to {DUMP_TAB!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
