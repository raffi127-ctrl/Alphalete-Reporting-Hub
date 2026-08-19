"""Drop a person from the All Campaigns tab's three tables.

The companion to `org_sales_board.roster_remove`. That one clears the campaign
boxes; this one clears the campaign-AGNOSTIC tab, which is only correct for
someone who went cold in EVERY campaign — one line here IS the person's total
across all of them, so a rep who stopped selling BOX and started selling Retail
Internet must keep their line.

WHY IT CAN'T REUSE THE ORG MODULE — three traps, all from
[[project_all-campaigns-board-sort]]:

  1. **Col A is a CHAIN** (`=A51+1`), not the ORG tab's literal ranks. Deleting a
     row leaves the row BELOW pointing at a deleted cell → #REF!, and the whole
     1..N numbering dies from there down. So every touched block gets its col A
     rewritten as the chain again afterwards. The first data row references the
     blank sub-header above it (`=A61+1` where A61 is empty = 1), which is what
     makes the chain start at 1 without a literal anywhere.
  2. **Three blocks, not two** — leaderboard, daily section, AND the bottom delta
     box. The delta box's totals row aggregates over itself and is the one that
     was silently short in 2026-08-17.
  3. **Aggregates are re-derived, never assumed**: `ranges_repair` runs after the
     deletes, because a block that SHRANK leaves every `=SUM`/`=SUMIF` anchored
     one row long.

Blocks are found by their header labels, the rows by col-B name — no indices.

    python -m automations.all_campaigns_board.roster_remove --names "A|B"
    python -m automations.all_campaigns_board.roster_remove --names "A|B" --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.all_campaigns_board.run import SHEET_ID, TARGET_TAB   # noqa: E402
from automations.all_campaigns_board import roster as _roster          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BACKUP_TAB = "backup_pre_roster_remove_allcampaigns"
# Each block by the label that opens it and the label that closes it. The delta
# box's terminator is a LABEL-LESS totals row, so it stops on the first row with
# no name instead.
# The header label alone is NOT enough: "All Units" also appears in the summary
# tables at the top of the tab, so the daily block is pinned by its 'Monday'
# column header too — the same anchor fill_section uses.
BLOCKS = (
    ("leaderboard", re.compile(r"^AT&T FIBER TEAM$", re.I), ""),
    ("daily",       re.compile(r"^All Units$", re.I), "monday"),
    ("delta",       re.compile(r"^All Units - All Campaigns$", re.I), ""),
)


def text(grid, r, c) -> str:
    row = grid[r] if 0 <= r < len(grid) else []
    return str(row[c] or "").strip() if 0 <= c < len(row) else ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def find_blocks(grid) -> list:
    """[{kind, first0, last0}] — data rows only, header and totals excluded."""
    out = []
    for kind, pat, needs_c in BLOCKS:
        hdr = next((r for r in range(len(grid))
                    if (pat.match(text(grid, r, 0)) or pat.match(text(grid, r, 1)))
                    and (not needs_c or text(grid, r, 2).lower() == needs_c)), None)
        if hdr is None:
            continue
        r = hdr + 1
        while r < len(grid) and not text(grid, r, 1):    # skip the sub-header row(s)
            r += 1
        first = r
        while r < len(grid) and text(grid, r, 1) and not text(grid, r, 0).lower().startswith("total"):
            r += 1
        if r > first:
            out.append({"kind": kind, "first0": first, "last0": r - 1})
    return out


def plan(grid, names: list) -> list:
    keys = {norm(n): n for n in names}
    hits = []
    for b in find_blocks(grid):
        for r in range(b["first0"], b["last0"] + 1):
            nm = text(grid, r, 1)
            if norm(nm) in keys:
                hits.append({"row0": r, "name": nm, "asked": keys[norm(nm)], "kind": b["kind"]})
    return sorted(hits, key=lambda h: h["row0"], reverse=True)


def plan_chain_repair(grid) -> list:
    """Col A back to `=A{above}+1` from the SECOND data row down, for the two
    chained blocks. Rewritten across the whole block, not just below the cut —
    cheap, and it heals a chain an earlier hand-edit already broke.

    ⚠ The FIRST data row is the anchor and is never touched: the two blocks
    anchor DIFFERENTLY (the leaderboard's A18 is a literal `1`, the daily
    section's A62 is `=A61+1` over a blank cell). Writing the chain formula into
    the leaderboard's first row would point it at the text 'All Units' and
    return #VALUE! for the entire column."""
    ups = []
    for b in find_blocks(grid):
        if b["kind"] == "delta":                  # no rank column at all
            continue
        first, last = b["first0"] + 1, b["last0"] + 1     # 1-indexed
        if last <= first:
            continue
        vals = [[f"=A{r - 1}+1"] for r in range(first + 1, last + 1)]
        ups.append({"range": f"A{first + 1}:A{last}", "values": vals})
    return ups


def _snapshot(ws, grid, logfn=print) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows, cols = len(grid), max((len(r) for r in grid), default=1)
    try:
        sh = ws.spreadsheet
        try:
            bws = sh.worksheet(BACKUP_TAB)
        except Exception:
            bws = sh.add_worksheet(title=BACKUP_TAB, rows=max(rows, 1), cols=max(cols, 1))
            logfn(f"  snapshot: created {BACKUP_TAB!r}")
        bws.resize(rows=max(rows, 1), cols=max(cols, 1))
        bws.update(range_name="A1",
                   values=[row + [""] * (cols - len(row)) for row in grid],
                   value_input_option="RAW")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"backup to {BACKUP_TAB!r} FAILED ({type(e).__name__}: {e}) "
                           f"— deleting nothing") from e
    logfn(f"  snapshot: froze {rows}x{cols} into {BACKUP_TAB!r} @ {stamp}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="all_campaigns_board.roster_remove")
    ap.add_argument("--names", required=True, help="Pipe-separated names as in col B.")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tab", default=TARGET_TAB)
    ap.add_argument("--no-range-repair", action="store_true")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.names.split("|") if n.strip()]

    sh = open_by_key(SHEET_ID)
    title = next((w.title for w in _retry(sh.worksheets)
                  if w.title.strip() == args.tab.strip()), args.tab)
    ws = _retry(lambda: sh.worksheet(title))
    grid = _retry(lambda: ws.get("A1:ZZ400", value_render_option="UNFORMATTED_VALUE")) or []

    print(f"=== all_campaigns roster_remove — {title!r} "
          f"({'APPLY' if args.apply else 'dry-run'})")
    for b in find_blocks(grid):
        print(f"    bloque {b['kind']:<12} filas {b['first0'] + 1}-{b['last0'] + 1}")
    hits = plan(grid, names)
    unexcluded = sorted({h["asked"] for h in hits if norm(h["name"]) not in _roster.EXCLUDE})
    for h in sorted(hits, key=lambda x: x["row0"]):
        print(f"  r{h['row0'] + 1:<5} {h['kind']:<12} {h['name']}")
    if unexcluded:
        print(f"  ⚠ sin EXCLUDE en all_campaigns_board.roster: {', '.join(unexcluded)}")

    if not args.apply:
        print(f"\n{len(hits)} fila(s) se borrarían. dry-run — nada escrito.")
        return 0
    if unexcluded:
        print("\nABORTADO: el auto-add los repondría. Agregalos a roster.EXCLUDE.")
        return 2

    _snapshot(ws, _retry(ws.get_all_values))
    sid = ws.id
    _retry(lambda: ws.spreadsheet.batch_update({"requests": [
        {"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                       "startIndex": h["row0"], "endIndex": h["row0"] + 1}}}
        for h in hits]}))                          # already bottom-up
    print(f"\n  borradas {len(hits)} fila(s)")

    grid2 = _retry(lambda: ws.get("A1:ZZ400", value_render_option="UNFORMATTED_VALUE")) or []
    chain = plan_chain_repair(grid2)
    if chain:
        _retry(lambda: ws.batch_update(chain, value_input_option="USER_ENTERED"))
    print(f"  cadena de col A reescrita en {len(chain)} bloque(s)")

    if not args.no_range_repair:
        # Re-derive every aggregate against the SHRUNK blocks. It writes by
        # default (--dry-run is its opt-out) and is idempotent, so calling
        # repair() straight is the same thing the daily fill does.
        from automations.all_campaigns_board import ranges_repair
        n = ranges_repair.repair(ws)
        print(f"  ranges_repair: {n} fórmula(s) reajustada(s)")
    print(f"  quedan {len(plan(grid2, names))} fila(s) con esos nombres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
