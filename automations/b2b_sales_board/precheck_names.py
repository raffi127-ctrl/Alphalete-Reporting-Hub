"""Name-mapping pre-check: pull Sara Plus agents over a wide window, map each to
a B2B board rep, and report matches + anything unmatched (either side).

Run:
  PYTHONUTF8=1 .venv/Scripts/python.exe -m automations.b2b_sales_board.precheck_names
"""
from __future__ import annotations

import argparse
import datetime as dt

from automations.b2b_sales_board import saraplus, names, sheet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-06-17")
    ap.add_argument("--tab", default="Copy of B2B WE 6.21")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--otp", action="store_true",
                    help="Allow a human to clear the device-verification code in the window.")
    args = ap.parse_args()
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    sh = sheet.open_sheet()
    ws = sh.worksheet(args.tab)
    values = ws.get_all_values()
    reps = sheet.find_rep_rows(values)
    board_names = [n for _, n in reps]
    print(f"Board '{args.tab}': {len(board_names)} reps")

    agents = saraplus.pull_agents(start, end=end, headless=not args.headed,
                                  allow_human_otp=args.otp)
    sara_names = sorted(agents)
    print(f"Sara Plus {start}..{end}: {len(sara_names)} agents with sales\n")

    mapping = names.build_mapping(sara_names, board_names)
    matched_board = set()
    print("=== SARA AGENT -> BOARD REP ===")
    for s in sara_names:
        board, reason = mapping[s]
        if board:
            matched_board.add(board)
        flag = "OK " if board else "!! "
        print(f" {flag}{s:38s} -> {board or '(NO MATCH)':28s} [{reason}]")

    unmatched_sara = [s for s in sara_names if mapping[s][0] is None]
    unseen_board = [b for b in board_names if b not in matched_board]
    print(f"\n=== UNMATCHED SARA AGENTS ({len(unmatched_sara)}) ===")
    for s in unmatched_sara:
        print("  ", s, " agg:", agents[s])
    print(f"\n=== BOARD REPS NOT SEEN IN SARA ({len(unseen_board)}) ===")
    for b in unseen_board:
        print("  ", b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
