"""Remove a rep from every table of the campaign(s) where they went cold.

THE RULE (Eve, 2026-08-19): a rep who closes TWO consecutive weeks at a literal
0 comes off that campaign's boxes. Scoped PER CAMPAIGN, never per person — reps
switch campaigns, so someone who stopped selling BOX and now sells Retail
Internet loses the BOX rows and keeps the Internet ones. `zero_streak.py` picks
who; this module does the removing.

WHAT A REP OCCUPIES. One rep in one campaign owns a row in three kinds of table,
and missing any one of them leaves the board internally inconsistent:

  * leaderboard  — under a 'WE m.d' header row (the ORG one for the 8 campaign
    sections, the block's own 'CAPTAIN TEAM' for a captainship)
  * daily block  — the Mon-Sun section, col C header 'Monday'
  * delta box    — the bottom 'Total this week / Last week / Delta' tables,
    including the cross-cutting ones (RAF SPECIAL TEAM, TRANG'S ORG)

Every table is found by LABEL — WE header text, 'Monday', 'Total this week',
col-A section name, col-B rep name — never by row index. [[feedback_no_hardcoded_columns]]

WHY DELETING ROWS IS SAFE HERE (checked live 2026-08-19, don't re-litigate it):

  * The leaderboards' week columns D.. are LITERALS. Only col C (the live week)
    is a formula, `=SUMIF($B$92:$B$95,B27,$J$92:$J$95)`. So a deletion cannot
    rewrite a closed week's history — the TOTALS row keeps the numbers the rep
    actually put up.
  * Col C of the TOTALS row is `=SUM(C27:C30)` and the daily Totals row is
    `=SUM(C92:C95)`; Sheets re-points both when a row inside them is deleted.
    Every rep this module removes is at 0 for the live week too, so no total
    moves at all.
  * The delta boxes match by LITERAL NAME (`=SUMIF($B$483:$B$495,"Kevin
    Driggs",…)`), so the formula leaves with its own row.
  * The per-rep K/L invariant (Σ per-rep K == Totals!K) survives because the
    two closed weeks are 0 by definition of the rule. That is the difference
    from the Ethan McKendree case, where a rep with 88 units in WE 08.02 was
    dropped and left that column structurally short forever
    ([[project_org-board-perrep-kl-never-rolled]]).

RANKS. Col A holds LITERAL ranks (not the `=A18+1` chain the All Campaigns tab
uses — [[project_all-campaigns-board-sort]]), so a deletion in the middle of a
table would leave 1,2,4. In practice the boards are sorted desc and a 0-seller
sits at the bottom, but this renumbers every touched leaderboard/daily table
1..N anyway rather than relying on that.

DELETION ALONE DOES NOT STICK — but check WHICH list. A removed rep is still on
their captain's Tableau team, so the daily captainship reports see a name with
no board row and propose them through `new_owners/captain_gate.py`; one tick
puts them back. `captain_gate.EXCLUDE`, keyed BY CAPTAIN, is what stops that,
and --apply refuses to run for a captainship rep not pinned there yet.
(`roster_sync.EXCLUDE` was the guard while the VA-board self-heal was live. That
self-heal is retired and the list is inert — a written record, not a defence.)
The campaign half is different: `new_owners/hook.py` only adds someone a human
banked AND who then sold, so a campaign row cannot come back on its own.
[[project_org-board-roster-selfheal-resurrects-deletions]]

    python -m automations.org_sales_board.roster_remove --names "A|B"   # dry-run
    python -m automations.org_sales_board.roster_remove --names "A|B" --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import roster_sync                    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BACKUP_TAB = "backup_pre_roster_remove"
WE_RE = re.compile(r"^WE\s+\d", re.IGNORECASE)
OWNER_RE = re.compile(r"captainship|captain team|special team|'s org", re.I)
END_LABELS = {"totals", "total", "captainship", "last week", "prior week",
              "2 weeks prior", "3 weeks prior", "grand total"}


def text(grid, r, c) -> str:
    row = grid[r] if 0 <= r < len(grid) else []
    return str(row[c] or "").strip() if 0 <= c < len(row) else ""


def norm(s: str) -> str:
    """Loose name key — case/spacing insensitive, blind to spacing around a
    hyphen. Same shape as perrep_kl_repair.norm, kept local so this module can
    be read on its own."""
    s = re.sub(r"\s+", " ", str(s or "").strip().lower())
    return re.sub(r"\s*-\s*", "-", s)


def _blank(grid, r) -> bool:
    """A table ends at a row with nothing in A..L — the board's own separator."""
    return not any(text(grid, r, c) for c in range(0, 12))


def _owner_above(grid, r) -> str:
    """Whose block this is: the nearest '<X>'s Captainship' / 'RAF SPECIAL TEAM'
    banner above the header. The 8 campaign sections have none — they belong to
    the org board itself."""
    for rr in range(r - 1, max(-1, r - 30), -1):
        for c in (0, 1, 2):
            t = text(grid, rr, c)
            if t and OWNER_RE.search(t):
                return t
    return "ALPHALETE ORG"


def index_rep_rows(grid) -> list:
    """Every rep row on the tab as
    {row0, kind, table, owner, name, rank_col_used}.

    Three headers, three shapes — all matched on their own label, so a renamed
    section or a moved block still lands."""
    out, r = [], 0
    while r < len(grid):
        cC = text(grid, r, 2).lower()
        is_lb = len([c for c in range(len(grid[r])) if WE_RE.match(text(grid, r, c))]) >= 2
        if is_lb:
            owner, sec, rr = _owner_above(grid, r), "", r + 1
            while rr < len(grid) and not _blank(grid, rr):
                a, b = text(grid, rr, 0), text(grid, rr, 1)
                if a and not b and a.lower() not in END_LABELS:
                    sec = a                       # a new section inside the same leaderboard
                elif b and a.lower() not in END_LABELS:
                    out.append({"row0": rr, "kind": "leaderboard", "table": sec,
                                "owner": owner, "name": b, "ranked": True})
                rr += 1
            r = rr
            continue
        if cC == "monday" and text(grid, r, 0) and not text(grid, r, 1):
            # A REP section names itself in col A ('Retail NL', 'BOX') and leaves
            # col B empty. The summary tables at the top of every block ('Product
            # Summary - This Week', 'RAF ORG - Current vs Prior Weeks') carry a
            # Monday header too, but label themselves in col B with col A blank —
            # their rows are product types / stat lines, not reps, and ranking
            # them stamped 1..N down a gutter that is meant to stay empty
            # (Eve 2026-08-19).
            title = text(grid, r, 0)
            owner, rr = _owner_above(grid, r), r + 1
            while rr < len(grid) and not _blank(grid, rr):
                a, b = text(grid, rr, 0), text(grid, rr, 1)
                # the closing label lives in col B once col A holds a rank
                if a.lower() in END_LABELS or b.lower() in END_LABELS:
                    break
                if b:
                    out.append({"row0": rr, "kind": "daily", "table": title,
                                "owner": owner, "name": b, "ranked": True})
                rr += 1
            r = rr
            continue
        if cC == "total this week":
            title = text(grid, r - 1, 1) or text(grid, r - 1, 0)
            owner, rr = _owner_above(grid, r), r + 1
            while rr < len(grid) and not _blank(grid, rr):
                b = text(grid, rr, 1)
                if b.lower() in END_LABELS:
                    break
                if b:
                    out.append({"row0": rr, "kind": "delta", "table": title,
                                "owner": owner, "name": b, "ranked": False})
                rr += 1
            r = rr
            continue
        r += 1
    return out


def plan_removals(grid, names: list) -> list:
    """The rep rows belonging to `names`, newest-row-first so a caller can delete
    without re-mapping indices."""
    keys = {norm(n): n for n in names}
    hits = [h | {"asked": keys[norm(h["name"])]}
            for h in index_rep_rows(grid) if norm(h["name"]) in keys]
    return sorted(hits, key=lambda h: h["row0"], reverse=True)


def plan_rank_repair(grid) -> list:
    """Col A renumbered 1..N for every ranked table — run AFTER the deletes, on a
    re-read grid. Returns [{range, values}] for a batch update; a table already
    numbered right contributes nothing."""
    updates, by_table = [], {}
    for h in index_rep_rows(grid):
        if h["ranked"]:
            by_table.setdefault((h["kind"], h["table"], h["owner"]), []).append(h["row0"])
    for rows in by_table.values():
        rows.sort()
        want = [[i + 1] for i in range(len(rows))]
        have = [[text(grid, r, 0)] for r in rows]
        if [str(w[0]) for w in want] == [str(h[0]) for h in have]:
            continue
        if rows != list(range(rows[0], rows[0] + len(rows))):   # not contiguous
            continue                                            # leave it alone, report instead
        updates.append({"range": f"A{rows[0] + 1}:A{rows[-1] + 1}", "values": want})
    return updates


def _snapshot(ws, grid, logfn=print) -> None:
    """Freeze the tab into ONE fixed backup tab before the first delete — static
    values, RAW, overwritten each run. Same contract as the rollover's snapshot:
    it must succeed or nothing is deleted."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows, cols = len(grid), max((len(r) for r in grid), default=1)
    try:
        sh = ws.spreadsheet
        try:
            bws = sh.worksheet(BACKUP_TAB)
        except Exception:
            bws = sh.add_worksheet(title=BACKUP_TAB, rows=max(rows, 1), cols=max(cols, 1))
            logfn(f"  snapshot: created backup tab {BACKUP_TAB!r}")
        bws.resize(rows=max(rows, 1), cols=max(cols, 1))
        rect = [row + [""] * (cols - len(row)) for row in grid]
        bws.update(range_name="A1", values=rect, value_input_option="RAW")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"backup to {BACKUP_TAB!r} FAILED ({type(e).__name__}: {e}) — "
            f"deleting nothing") from e
    logfn(f"  snapshot: froze {rows}x{cols} of {ws.title!r} into {BACKUP_TAB!r} @ {stamp}")


def captains_of(rows) -> set:
    """The captainships a set of plan rows actually belongs to.

    LEADERBOARD ROWS ONLY, and that restriction is load-bearing. The other two
    kinds name things that are not a captainship roster:
      * a daily block's banner is the bare 'CAPTAIN TEAM' header — no name in it
      * the cross-cutting delta boxes ('RAF SPECIAL TEAM', "TRANG'S ORG") carry
        a captain's first name while listing reps from several captainships.
        Kevin Driggs sits in RAF SPECIAL TEAM but is Carlos' rep; asking for a
        pin under Raf would be asking for the wrong thing.
    The leaderboard's '<X>'s Captain Team' banner is the roster the daily
    captainship reports actually pull, which is what the gate proposes from."""
    from automations.new_owners.captain_watch import captain_name
    return {captain_name(h["owner"]) for h in rows
            if h["kind"] == "leaderboard" and h["owner"] != "ALPHALETE ORG"}


def _pinned(name: str, rows) -> bool:
    """Is this rep pinned out of every captainship we're removing them from?

    The live guard is per-captain, so a rep cold in Tony's boxes has to be
    pinned under 'Tony' — an entry under another captain proves nothing about
    Tony's gate, and that scoping is the rule itself (cold in one campaign,
    still selling another). A purely campaign-section removal has no gate to
    satisfy: hook.py only adds a banked owner who has actually sold."""
    from automations.new_owners import captain_gate as cg
    caps = captains_of(rows)
    return all(cg._excluded(c, name) for c in caps) if caps else True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_sales_board.roster_remove")
    ap.add_argument("--names", required=True,
                    help="Pipe-separated rep names, exactly as they read in col B.")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--allow-unexcluded", action="store_true",
                    help="delete even for a captainship rep not pinned in "
                         "captain_gate.EXCLUDE (the gate WILL offer them back)")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.names.split("|") if n.strip()]

    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    grid = _retry(lambda: ws.get("A1:ZZ2200", value_render_option="UNFORMATTED_VALUE")) or []
    plan = plan_removals(grid, names)

    found = {h["asked"] for h in plan}
    print(f"=== roster_remove — {args.tab!r} ({'APPLY' if args.apply else 'dry-run'})")
    for n in names:
        rows = [h for h in plan if h["asked"] == n]
        mark = ("" if _pinned(n, rows)
                else "   ⚠ sin pin en captain_gate.EXCLUDE")
        print(f"\n{n}  — {len(rows)} fila(s){mark}")
        for h in sorted(rows, key=lambda x: x["row0"]):
            print(f"   r{h['row0'] + 1:<6} {h['kind']:<12} {h['owner'][:24]:<25} {h['table'][:34]}")
    missing = [n for n in names if n not in found]
    if missing:
        print(f"\n  sin filas en el tab: {', '.join(missing)}")

    if not args.apply:
        print(f"\n{len(plan)} fila(s) se borrarían. dry-run — nada escrito.")
        return 0

    unpinned = [n for n in found
                if not _pinned(n, [h for h in plan if h["asked"] == n])]
    if unpinned and not args.allow_unexcluded:
        print(f"\nABORTADO: {', '.join(unpinned)} no está(n) pineado(s) en "
              f"new_owners.captain_gate.EXCLUDE bajo su capitán — el gate diario "
              f"los va a volver a ofrecer y un ✅ los repone. Agregalos ahí "
              f"(o pasá --allow-unexcluded si sabés lo que hacés).")
        return 2

    _snapshot(ws, _retry(ws.get_all_values))
    sid = ws.id
    reqs = [{"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                           "startIndex": h["row0"], "endIndex": h["row0"] + 1}}}
            for h in plan]                       # already sorted bottom-up
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    print(f"\n  borradas {len(reqs)} fila(s)")

    grid2 = _retry(lambda: ws.get("A1:ZZ2200", value_render_option="UNFORMATTED_VALUE")) or []
    ranks = plan_rank_repair(grid2)
    if ranks:
        _retry(lambda: ws.batch_update(ranks, value_input_option="USER_ENTERED"))
    print(f"  ranks renumerados en {len(ranks)} tabla(s)")
    left = plan_removals(grid2, names)
    print(f"  quedan {len(left)} fila(s) con esos nombres "
          f"{'— revisar' if left else '(ok)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
