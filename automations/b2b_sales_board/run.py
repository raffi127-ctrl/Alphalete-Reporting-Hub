"""B2B WE sales board — orchestrator.

Pulls the prior day from the Sara Plus web app and fills that weekday's block on
the 'B2B WE <M.D>' board (the weekly tab Megan/Carlos creates by hand). Default
target = YESTERDAY anchored to Central Time (the team is in Texas, so the date is
correct regardless of where the run fires) [[project_central-time-for-texas-reports]].

Sara Plus demands a device-verification code on any new browser, so the pull runs
HEADED by default and waits for a human to clear the OTP if asked (not fully
unattended — same constraint as the Tableau/Cloudflare sessions).

Sandbox-first while building: --sandbox targets 'Copy of B2B WE <M.D>'. Preview by
default; --write applies the cells (nl/int/voip only; AIR + Apps never touched;
only reps WITH sales that day).

Examples:
  # preview yesterday into the sandbox (uses the cached pull, no Sara login)
  PYTHONUTF8=1 .venv/Scripts/python.exe -m automations.b2b_sales_board.run \
      --sandbox --use-cache --day 2026-06-17
  # real run: pull yesterday live and write production
  PYTHONUTF8=1 .venv/Scripts/python.exe -m automations.b2b_sales_board.run --write
"""
from __future__ import annotations

import argparse
import datetime as dt
from zoneinfo import ZoneInfo

from automations.b2b_sales_board import fill, saraplus, sheet

CENTRAL = ZoneInfo("America/Chicago")


def central_today() -> dt.date:
    return dt.datetime.now(CENTRAL).date()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None,
                    help="Target day YYYY-MM-DD (default: yesterday, Central).")
    ap.add_argument("--sandbox", action="store_true",
                    help="Target the 'Copy of B2B WE <M.D>' sandbox tab.")
    ap.add_argument("--write", action="store_true",
                    help="Apply the writes (default: preview only).")
    ap.add_argument("--headless", action="store_true",
                    help="Run Sara Plus headless (no human OTP help — usually fails the "
                         "device check; for debugging only).")
    ap.add_argument("--use-cache", action="store_true",
                    help="Reuse output/saraplus_cache.json instead of pulling Sara Plus "
                         "(no login; the cache's day must equal the target day).")
    args = ap.parse_args()

    day = (dt.date.fromisoformat(args.day) if args.day
           else central_today() - dt.timedelta(days=1))
    code = sheet.DAY_CODES[day.weekday()]
    print(f"=== B2B WE sales board | day {day} ({code}) | "
          f"{'SANDBOX' if args.sandbox else 'PRODUCTION'} | "
          f"{'WRITE' if args.write else 'preview'} ===", flush=True)

    # 1) Locate the weekly tab (created manually each week; clear error if missing).
    sh = sheet.open_sheet()
    ws = sheet.find_week_tab(sh, day, sandbox=args.sandbox)
    values = ws.get_all_values()
    print(f"tab '{ws.title}' | week {sheet.week_range_label(values)}", flush=True)

    # 2) Get the day's per-agent sales (cache for testing, else a live Sara pull).
    if args.use_cache:
        cache_day, agents_day = fill.load_cache_day()
        if cache_day != day:
            print(f"!! cache holds {cache_day}, target is {day} — pull fresh "
                  f"(drop --use-cache) or pass --day {cache_day}.")
            return 2
        print(f"using cache: {len(agents_day)} sales reps", flush=True)
    else:
        agents_day = saraplus.pull_agents(
            day, headless=args.headless, allow_human_otp=not args.headless,
            logfn=lambda m: print(m, flush=True))

    # 3) Plan, preview, and (optionally) write.
    writes, skipped, protected, cols = fill.plan_fill(values, day, agents_day)
    fill.print_plan(values, writes, skipped, protected, cols)

    if not args.write:
        print("\n(preview only — re-run with --write to apply.)")
        return 0

    n = fill.apply_writes(ws, writes)
    print(f"\nWROTE {n} cells across {len(writes)} reps to '{ws.title}'.")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
