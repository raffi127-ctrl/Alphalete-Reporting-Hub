"""Replicate Wayne's conditional formatting onto every other ABP tab.

Eve banded her own tab by hand (2026-07-29) and asked for the same on the
other four. This is a re-runnable maintenance command, not part of the daily
fill — the daily run never touches formatting.

    python -m automations.captainship_abp_6days.apply_formatting --dry-run
    python -m automations.captainship_abp_6days.apply_formatting

THE BANDS (read off Wayne's tab, not hardcoded — if he re-bands, re-run this):

    ABP %                       6+ DAYS OUT
      >= 85%      green           <= 30%      green
      50-84.90%   yellow          30-84.99%   yellow
      <= 49.99%   red             >= 85%      orange

The two scales run OPPOSITE ways on purpose: a high ABP mix is good, a high
share of sales scheduled 6+ days out is not.

TWO THINGS THIS DOES NOT COPY LITERALLY

1. Row numbers. Wayne's ABP box sits at rows 3 + 5-11; Starr's is 3 + 5-13 and
   her second box starts at 17, not 15. Ranges are rebuilt from each tab's OWN
   find_boxes() result, so nothing here breaks when a rep is added.

2. The column span. Wayne's rules cover column B ALONE. That works exactly
   once: the daily fill inserts a fresh column at B and Sheets carries the old
   range along with the cells it was attached to, so tomorrow the bands would
   sit on C and the new day would come out unpainted. Every rule written here
   spans B through the end of the grid instead, so each new column is already
   covered on the day it opens. Wayne's own tab is widened to match (same
   bands, same colors — only the span changes).

Rep ranges also run past the last rep, down to the row before the next box, so
an ICD appended by the daily fill lands inside an already-banded range.
"""
from __future__ import annotations

import argparse
import sys

from automations.captainship_abp_6days import fill

# The tab whose bands are the source of truth.
SOURCE_TAB_SLUG = "wayne"

# Rows to leave banded past the last rep of the LAST box (the next box's header
# bounds every other one). Room for a few appended ICDs.
_TAIL_ROWS = 6


def _rule_specs(ws, boxes: dict) -> dict:
    """{box key: [booleanRule, ...]} read off the SOURCE tab, in sheet order.

    Rules are matched to a box by which box's rows they cover, so this survives
    Wayne re-ordering or re-banding. Exact duplicates are dropped (his tab
    carries the '>= 85% orange' rule twice; the second can never fire).
    """
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),conditionalFormats)"})
    raw = []
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == ws.id:
            raw = s.get("conditionalFormats") or []
            break

    # row (1-indexed) -> box key, for every row a box owns
    owner: dict = {}
    for box, sect in boxes.items():
        owner[sect["office_avg_row"]] = box
        for r in sect["rep_rows"].values():
            owner[r] = box

    out: dict = {b: [] for b in boxes}
    for rule in raw:
        brule = rule.get("booleanRule")
        if not brule:
            # Gradient rules aren't used on these tabs; copying one blindly
            # would be a guess, so say so instead of half-doing it.
            print("  ⚠ skipping a non-boolean (gradient) rule — not replicated")
            continue
        hit = None
        for rng in rule.get("ranges", []):
            for r in range(rng.get("startRowIndex", 0) + 1,
                           rng.get("endRowIndex", 0) + 1):
                if r in owner:
                    hit = owner[r]
                    break
            if hit:
                break
        if hit is None:
            continue
        if brule in out[hit]:
            continue                      # exact duplicate
        out[hit].append(brule)
    return out


def _ranges_for(ws, boxes: dict, box: str) -> list:
    """The cells one box's bands apply to: its Captainship Avg row and its rep
    rows, from column B to the right edge of the grid."""
    sect = boxes[box]
    # This box ends where the next one starts; the last box gets a tail.
    later = [s["header_row"] for b, s in boxes.items()
             if s["header_row"] > sect["header_row"]]
    last_rep = max(sect["rep_rows"].values()) if sect["rep_rows"] \
        else sect["rep_header_row"]
    end_row = (min(later) - 1) if later else (last_rep + _TAIL_ROWS)
    end_row = max(end_row, last_rep)

    common = {"sheetId": ws.id, "startColumnIndex": 1,
              "endColumnIndex": ws.col_count}
    return [
        {**common, "startRowIndex": sect["office_avg_row"] - 1,
         "endRowIndex": sect["office_avg_row"]},
        {**common, "startRowIndex": sect["rep_header_row"],
         "endRowIndex": end_row},
    ]


def apply_to(ws, boxes: dict, specs: dict, *, dry_run: bool,
             logfn=print) -> int:
    """Replace every conditional-format rule on `ws` with the source bands,
    re-ranged for this tab. Returns the number of rules written.

    Deleting first is deliberate: four of these tabs still carry the churn
    bands they inherited from the workbook they were duplicated from (<=29.99%
    green ... >=40.01% red), which paint a healthy 96% ABP RED. Leaving them
    underneath would mean whichever rule sorts first wins.
    """
    existing = _rule_count(ws)
    requests = [{"deleteConditionalFormatRule": {"sheetId": ws.id, "index": 0}}
                for _ in range(existing)]
    idx = 0
    for box in sorted(boxes, key=lambda b: boxes[b]["header_row"]):
        for brule in specs.get(box, []):
            requests.append({"addConditionalFormatRule": {
                "rule": {"ranges": _ranges_for(ws, boxes, box),
                         "booleanRule": brule},
                "index": idx,
            }})
            idx += 1

    logfn(f"    {existing} old rule(s) removed, {idx} written")
    if dry_run:
        return idx
    ws.spreadsheet.batch_update({"requests": requests})
    return idx


def _rule_count(ws) -> int:
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),conditionalFormats)"})
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == ws.id:
            return len(s.get("conditionalFormats") or [])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_abp_6days.apply_formatting")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without writing.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated slugs to write. Default: all tabs "
                         "(the source tab included — its bands are re-ranged "
                         "to span every day column).")
    args = ap.parse_args(argv)

    only = ({s.strip().lower() for s in args.only.split(",")}
            if args.only else None)

    print(f"=== ABP tabs — conditional formatting "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    src_ws = fill.open_ws(SOURCE_TAB_SLUG)
    src_boxes = fill.find_boxes(src_ws)
    specs = _rule_specs(src_ws, src_boxes)
    print(f"Source: {src_ws.title!r}")
    for box, rules in specs.items():
        print(f"  {box:>6}: {len(rules)} rule(s)")
    if not any(specs.values()):
        print("  ⚠ the source tab has no boolean rules — nothing to copy.")
        return 1

    failures = []
    for slug, tab in fill.TABS.items():
        if only and slug not in only:
            continue
        try:
            ws = src_ws if slug == SOURCE_TAB_SLUG else fill.open_ws(slug)
            boxes = fill.find_boxes(ws)
            print(f"\n  {tab}")
            for box in sorted(boxes, key=lambda b: boxes[b]["header_row"]):
                rows = _ranges_for(ws, boxes, box)
                print(f"    {box:>6}: avg row {rows[0]['startRowIndex'] + 1}, "
                      f"reps {rows[1]['startRowIndex'] + 1}-"
                      f"{rows[1]['endRowIndex']}, cols B-"
                      f"{ws.col_count}")
            apply_to(ws, boxes, specs, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001 — one tab must not stop the rest
            print(f"    ⚠ FAILED: {type(e).__name__}: {e}")
            failures.append(slug)

    if failures:
        print(f"\n=== INCOMPLETE — failed: {failures} ===")
        return 1
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
