"""New Owners — setup + status from the command line.

The feature itself has no schedule of its own: the campaign half runs inside the
daily Org Sales Board fill, and the captainship half inside whichever captainship
report sees the rep first. This CLI is for the two things a human needs:

    python -m automations.new_owners.run --init      create/refresh the tabs
    python -m automations.new_owners.run --status    who's waiting, what's logged

`--init` is safe to re-run: it creates the 'New Owners' and 'New Owners Log' tabs
only if they're missing, and re-points the Campaign dropdown at the board's
current section labels. It never clears an existing tab.
"""
from __future__ import annotations

import argparse
import sys

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
from automations.new_owners import bank, board_add, cap_insert, cap_roster

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _scan(ss, args) -> int:
    """Roster every requested captainship in Tableau and open a gate for anyone
    who has no row in that captainship's tables on the board.

    Read-only against the board: it proposes, it never inserts. The rows appear
    when someone ticks ✅ and the next captainship run resolves it."""
    from automations.focus_office_att.aliases import load_aliases
    from automations.org_sales_board import fill_section as fs
    from automations.new_owners import captain_gate
    from automations.shared.tableau_patchright import tableau_session

    if args.captains:
        captains = [c.strip() for c in args.captains.split(",") if c.strip()]
        skipped = {}
    else:
        progs = ({"fiber", "b2b", "nds"} if args.programs.strip().lower() == "all"
                 else {p.strip().lower() for p in args.programs.split(",")})
        captains = cap_roster.captains_for(progs)
        skipped = cap_roster.unsupported(progs)
    print(f"\nscanning {len(captains)} captainship(s): "
          f"{', '.join(captains) or 'none'}")
    if skipped:
        print("  not scannable yet (no verified captain filter on those "
              "worksheets — see cap_roster's docstring): "
              + ", ".join(f"{c} [{p}]" for c, p in skipped.items()))

    aliases = load_aliases()
    grid = _retry(ss.worksheet(args.tab).get_all_values)
    with tableau_session(verbose=False) as page:
        rosters = cap_roster.scan(page, captains, logfn=print)

    fresh_total = 0
    for captain, res in rosters.items():
        if res.get("error"):
            print(f"  ⚠ {captain}: {res['error']}")
            continue
        owners = res["owners"]
        try:
            tables = cap_insert.tables_for(grid, captain)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {captain}: can't read the board block "
                  f"({type(e).__name__}) — skipped")
            continue
        on_board = set()
        for t in tables:
            for r in t["rows"]:
                on_board |= fs._candidates_for(cap_insert._cell(grid, r, 2),
                                               aliases)
        fresh = [raw for key, raw in owners.items()
                 if not (fs._candidates_for(raw, aliases) | {key}) & on_board]
        print(f"  {captain}: {len(owners)} in Tableau, {len(fresh)} with no row "
              f"on the board{': ' + ', '.join(fresh) if fresh else ''}")
        if fresh:
            fresh_total += len(captain_gate.propose(
                fresh, captain=captain, source="Tableau captain filter",
                ss=ss, dry_run=args.dry_run, logfn=print))
    print(f"\n{fresh_total} new rep(s) waiting for a ✅ from this scan.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="new_owners")
    ap.add_argument("--init", action="store_true",
                    help="Create the 'New Owners' + 'New Owners Log' tabs if "
                         "they don't exist and refresh the Campaign dropdown.")
    ap.add_argument("--status", action="store_true",
                    help="Print the bank (who is waiting) and the log.")
    ap.add_argument("--scan", action="store_true",
                    help="Pull each captainship's roster from Tableau and ask "
                         "for a ✅ on anyone who has no row on the board.")
    ap.add_argument("--programs", default=",".join(cap_roster.DEFAULT_PROGRAMS),
                    help="Which programs to scan: b2b,nds,fiber or 'all'. "
                         "Fiber is off by default — its five captains are "
                         "already detected daily by their own reports.")
    ap.add_argument("--captains",
                    help="Comma-separated captains to scan instead of whole "
                         "programs (e.g. 'Khalil,Colten').")
    ap.add_argument("--dry-run", action="store_true",
                    help="With --scan: print what would be proposed, post "
                         "nothing.")
    ap.add_argument("--tab", default=SANDBOX_TAB,
                    help="Board tab to read the campaign labels from.")
    args = ap.parse_args(argv)
    if not (args.init or args.status or args.scan):
        ap.error("pick --init, --status or --scan")

    ss = open_by_key(SHEET_ID)
    grid = _retry(ss.worksheet(args.tab).get_all_values)
    labels = board_add.campaign_labels(grid)
    print(f"board tab {args.tab!r}: {len(labels)} campaign section(s) — "
          f"{', '.join(labels)}")

    bws = bank.open_bank(ss, campaigns=labels)
    lws = bank.open_log(ss)
    if args.init:
        bank.refresh_campaign_dropdown(bws, labels)
        print(f"✓ '{bank.BANK_TAB}' and '{bank.LOG_TAB}' are ready.")
        print(f"   Add a row per new owner: Name + Campaign (dropdown) + Org "
              f"Head. Everything else fills itself.")

    if args.scan:
        rc = _scan(ss, args)
        if rc:
            return rc

    if args.status:
        cmap, rows = bank.read(bws)
        waiting = [r for r in rows if r.waiting]
        print(f"\nBANK — {len(rows)} row(s), {len(waiting)} waiting:")
        for r in rows:
            print(f"  {r.row:>4}  {r.name:<28} {r.campaign:<20} "
                  f"{r.status or bank.WAITING:<18} {r.activated_on}")
        entries = bank.log_entries(lws)
        print(f"\nLOG — {len(entries)} line(s):")
        for e in entries[-25:]:
            print(f"  {e['date']:<12} {e['kind']:<12} {e['name']:<28} "
                  f"{e['scope']:<24} {e['action']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
