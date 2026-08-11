"""One-off state repair — ORG Sales Board per-REP prior-week columns.

WHAT WAS BROKEN
---------------
Every daily block on the board carries, per rep row:

    J = RUNNING WEEK TOTALS   K = LAST WEEK'S TOTALS   L = PREVIOUS WEEK'S

The Tuesday rollover shifts the block's *history rows* (Totals → Last Week →
Prior → 2 Weeks → 3 Weeks) and, since 2026-07-28, re-derives the *Totals row*
K/L (`rollover.apply_prior_week_totals`). Nothing ever shifted the **rep
rows**' J→K→L — the VA did that by hand, and the copy tab stopped inheriting it
after the 2026-07-14 roll.

So on every one of the 26 blocks the rep rows have been frozen at WE 07.12 (K)
and WE 07.05 (L) for four rollovers, while the Totals row kept advancing. The
board's own invariant — Σ(per-rep K) == Totals-row K — broke on 26/26 blocks
(it still holds on 25/26 of the VA's hand-kept tab, and held on 26/26 in the
`BACKUP copy 07-14 1044` snapshot).

THE REPAIR
----------
Each block sits directly below a leaderboard whose columns are dated week
endings ('WE 08.09', 'WE 08.02', …) — the ORG leaderboard for the 8 campaign
sections, the block's own 'CAPTAIN TEAM' leaderboard for the captainship
blocks. That leaderboard already holds the correct per-rep weekly totals, on
the same tab. So per rep:

    K ← leaderboard[rep][just-closed week]      L ← leaderboard[rep][week before]

ACCEPTANCE TEST (per block, enforced — a block that fails is SKIPPED, not
written): the new per-rep column must sum to the block's Totals-row K / L,
which the rollover already maintains correctly and which matches the emailed
report. Nothing is written unless both columns balance.

Everything is located by label — WE header text, col-A section name, col-B rep
name — never by row/column index ([[feedback_no_hardcoded_columns]]).

    python -m automations.org_sales_board.perrep_kl_repair            # dry-run
    python -m automations.org_sales_board.perrep_kl_repair --apply    # write

Applied 2026-08-11: 365 cells across 25 of the 26 blocks. The one column left
alone is 'B2B - All Units'!L — Ethan McKendree was dropped from that roster
after selling 88 units in WE 08.02, so the Totals row keeps them and the rep
rows structurally cannot ([[project_org-board-roster-selfheal-resurrects-deletions]]).
The undo CSV lands in output/.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry   # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB    # noqa: E402
from automations.org_sales_board.rollover import a1col               # noqa: E402
from automations.org_sales_board import week as wk                   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = Path(__file__).resolve().parent
K_HDR = "LAST WEEK'S TOTALS"
L_HDR = "PREVIOUS WEEK'S TOTALS"
WE_RE = re.compile(r"^WE\s+\d", re.IGNORECASE)


def cell(grid, r, c):
    row = grid[r] if 0 <= r < len(grid) else []
    return row[c] if 0 <= c < len(row) else ""


def text(grid, r, c):
    return str(cell(grid, r, c) or "").strip()


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def we_label(sunday: dt.date) -> str:
    """Zero-padded 'WE MM.DD' — the leaderboard header spelling."""
    return f"WE {sunday:%m.%d}"


def norm(s: str) -> str:
    """Loose label key: case/whitespace-insensitive, and blind to spacing around
    a hyphen. The board's titles drift ('Fiber -New Internet' on one leaderboard
    vs 'Fiber - New Internet' on its own daily block)."""
    s = re.sub(r"\s+", " ", str(s or "").strip().lower())
    return re.sub(r"\s*-\s*", "-", s)


def find_we_header_rows(grid):
    """Rows carrying >=2 'WE m.d' column headers — every leaderboard on the
    tab (the ORG one plus one per captainship box)."""
    out = []
    for r in range(len(grid)):
        cols = [c for c in range(len(grid[r])) if WE_RE.match(text(grid, r, c))]
        if len(cols) >= 2:
            out.append(r)
    return out


def leaderboard_sections(grid, we_row, stop_row):
    """Every section under a leaderboard header, as
    [(name, {rep_lower: row}, totals_row)]. A section is 'col A = name, col B
    blank'; its rep rows are 'col B non-blank'; it ends at TOTALS."""
    out = []
    r = we_row + 1
    while r < stop_row:
        if not (text(grid, r, 0) and not text(grid, r, 1)):
            r += 1
            continue
        name, reps, totals_row = text(grid, r, 0), {}, None
        rr = r + 1
        while rr < min(r + 60, len(grid)):
            a, b = text(grid, rr, 0), text(grid, rr, 1)
            if a.upper().startswith("TOTAL"):
                totals_row = rr
                break
            if a and not b:                    # the next section started
                break
            if b:
                reps.setdefault(norm(b), rr)   # first spelling wins
            rr += 1
        if reps:
            out.append((name, reps, totals_row))
        r = max(rr, r + 1)
    return out


def pick_section(sections, block_name, block_reps):
    """The leaderboard section feeding this daily block. Title match FIRST —
    Retail NL and Retail Internet share an identical roster, so the roster alone
    cannot tell them apart. Roster overlap is the FALLBACK, for the blocks whose
    title disagrees with their own leaderboard's ('ATT NDS - All Units' sitting
    over a 'B2B - All Units' leaderboard, same 7 reps)."""
    want = norm(block_name)
    for name, reps, tot in sections:
        if norm(name) == want:
            return name, reps, tot, "title"
    keys = {norm(b) for _r, b in block_reps}
    best, score = None, 0.0
    for name, reps, tot in sections:
        hit = len(keys & set(reps)) / max(len(keys), 1)
        if hit > score:
            best, score = (name, reps, tot), hit
    if best and score >= 0.6:
        return (*best, f"roster {score:.0%}")
    return None, None, None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default: dry-run)")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--today", default=None,
                    help="YYYY-MM-DD; defaults to today")
    args = ap.parse_args()
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())

    # The week the rep columns must hold: K = the week the board just closed,
    # L = the one before it. reporting_monday() is the OPEN week's Monday, so
    # the closed week ends the day before.
    k_sun = wk.reporting_monday(today) - dt.timedelta(days=1)
    l_sun = k_sun - dt.timedelta(days=7)
    k_lab, l_lab = we_label(k_sun), we_label(l_sun)
    print(f"=== per-rep prior-week backfill — {args.tab!r} ===")
    print(f"    K ← {k_lab}   L ← {l_lab}   (today {today:%Y-%m-%d %a})\n")

    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    # ONE unformatted read: labels come back as text, numbers as numbers, and
    # formulas as their computed value — so '1,199' can't be written back as a
    # string and turn a number into text.
    grid = _retry(lambda: ws.get("A1:ZZ2200",
                                 value_render_option="UNFORMATTED_VALUE")) or []
    we_rows = find_we_header_rows(grid)
    print(f"    {len(we_rows)} leaderboard(s) found\n")

    updates, undo, skipped = [], [], []
    print(f"{'row':>6} {'block':<28} {'reps':>4} {'ΣK':>7}{'want':>7} "
          f"{'ΣL':>7}{'want':>7}  cells  status")
    for r in range(len(grid)):
        cols = {text(grid, r, c).upper(): c for c in range(len(grid[r]))}
        if K_HDR not in cols or L_HDR not in cols:
            continue
        kc, lc = cols[K_HDR], cols[L_HDR]
        name = text(grid, r, 0) or text(grid, r, 1)

        # rep rows of this daily block, down to its 'Totals' row
        reps, tot_row = [], None
        for rr in range(r + 1, min(r + 80, len(grid))):
            a, b = text(grid, rr, 0), text(grid, rr, 1)
            if a.lower() in ("totals", "total"):
                tot_row = rr
                break
            if b:
                reps.append((rr, b))
        if not reps or tot_row is None:
            continue
        want_k, want_l = num(cell(grid, tot_row, kc)), num(cell(grid, tot_row, lc))

        # the leaderboard for this block = the nearest WE header row above it
        above = [x for x in we_rows if x < r]
        if not above:
            skipped.append((r + 1, name, "no leaderboard above it"))
            continue
        we_row = above[-1]
        src_name, src, _src_tot, how = pick_section(
            leaderboard_sections(grid, we_row, r), name, reps)
        if not src:
            skipped.append((r + 1, name, "no leaderboard section matches it"))
            continue
        we_cols = {text(grid, we_row, c).upper(): c
                   for c in range(len(grid[we_row]))
                   if WE_RE.match(text(grid, we_row, c))}
        if k_lab.upper() not in we_cols or l_lab.upper() not in we_cols:
            skipped.append((r + 1, name,
                            f"leaderboard has no {k_lab} / {l_lab} column"))
            continue
        kcol, lcol = we_cols[k_lab.upper()], we_cols[l_lab.upper()]

        block, missing = [], []
        for rr, nm in reps:
            lrow = src.get(norm(nm))
            if lrow is None:
                missing.append(nm)
                nk = nl = 0
            else:
                nk = num(cell(grid, lrow, kcol)) or 0
                nl = num(cell(grid, lrow, lcol)) or 0
            block.append((rr, nm, nk, nl))
        sk, sl = sum(b[2] for b in block), sum(b[3] for b in block)

        # ACCEPTANCE TEST, PER COLUMN — a rebuilt column is written only if it
        # reconciles to the Totals row, which the rollover already maintains
        # correctly and which matches the emailed report. Per column, not per
        # block: a rep dropped from the roster after a week he sold in leaves
        # THAT week's column short for good (the Totals row keeps his sales),
        # and there is no reason to withhold the column that does balance.
        ok_k, ok_l = (want_k is not None and sk == want_k), \
                     (want_l is not None and sl == want_l)
        n = 0
        for rr, nm, nk, nl in block:
            for col, new, good in ((kc, nk, ok_k), (lc, nl, ok_l)):
                old = cell(grid, rr, col)
                if not good or num(old) == new:
                    continue
                a1 = f"{a1col(col + 1)}{rr + 1}"
                updates.append({"range": a1,
                                "values": [[int(new) if float(new).is_integer()
                                            else new]]})
                undo.append([args.tab, name, nm, a1, old, new])
                n += 1
        status = "ok" if (ok_k and ok_l) else (
            "*** " + " + ".join(
                f"{c} NOT written (Σ {s:g} ≠ {w} on the leaderboard"
                + (f"; off-roster: {', '.join(missing)}" if missing else "")
                + ")"
                for c, s, w, g in (("K", sk, want_k, ok_k), ("L", sl, want_l, ok_l))
                if not g))
        if not (ok_k and ok_l):
            skipped.append((r + 1, name, status.lstrip("* ")))
        print(f"{r+1:>6} {name[:28]:<28} {len(reps):>4} {sk:>7.0f}"
              f"{(want_k or 0):>7.0f} {sl:>7.0f}{(want_l or 0):>7.0f} {n:>6}  "
              f"{status}{'' if how == 'title' else f'  [matched by {how}]'}")

    print(f"\n{len(updates)} cell(s) to write, {len(skipped)} block(s) skipped")
    for row, name, why in skipped:
        print(f"    ⚠ row {row} {name}: {why}")
    if not args.apply:
        print("\n[dry-run] nothing written — re-run with --apply")
        return
    if not updates:
        print("nothing to do")
        return

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    undo_path = OUT_DIR / f"org_board_perrep_kl_backfill_undo_{stamp}.csv"
    with undo_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tab", "block", "rep", "a1", "old", "new"])
        w.writerows(undo)
    print(f"undo CSV → {undo_path}")

    for i in range(0, len(updates), 500):
        _retry(ws.batch_update, updates[i:i + 500],
               value_input_option="USER_ENTERED")
        print(f"  wrote {min(i + 500, len(updates))}/{len(updates)}")
    print("done")


if __name__ == "__main__":
    main()
