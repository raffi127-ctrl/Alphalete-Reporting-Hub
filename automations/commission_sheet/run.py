"""The weekly payroll run, end to end.

Two phases, split where a person is genuinely needed (Megan, 2026-09-04):

  PHASE 1 — unattended, Wednesday morning before noon (JD, 2026-09-04).
      1  copy last week's workbook, name it RH M.D.YY, archive older ones
      2  clear the DD and order-log tabs
      3  clear the 4b bonuses and re-drag the 4a formulas
      4  fill the DD from Tableau
      5  fill the order log from Tableau
      8  reconcile the ATT Sales Transfers
      9  post the review call and tag JD
    All of it stays inside the week's OWN workbook, so a bad run costs a re-run
    and nothing else.

  PHASE 2 — JD, at his own keyboard, after he ticks the post.
     10  write the week into Raf PNL 2026   (gated on his tick)
     11  enter the payroll in Apex          (needs HIS logged-in session)

STEP 6 IS NOT IN EITHER PHASE. Adding reps and setting commission is JD's, and
it belongs between the two: phase 1 leaves the workbook filled and tells him it
is ready, he fixes tab 3 and reviews, then phase 2 runs. Step 8 still runs in
phase 1 against last week's roster — safely, because it reports anyone it
cannot place instead of guessing, and re-running it after he updates tab 3
picks them up.

    python -m automations.commission_sheet.run --phase1
    python -m automations.commission_sheet.run --phase1 --write
    python -m automations.commission_sheet.run --phase2 --write
    python -m automations.commission_sheet.run --phase1 --only 4,5 --write

Dry run by default, every step. A step that fails stops the phase — later steps
assume earlier ones landed, and half a payroll run is worse than none.
"""
from __future__ import annotations

import argparse
import datetime as dt
import traceback
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from automations.commission_sheet import config as C


@dataclass
class Step:
    num: int
    name: str
    run: Callable[[bool, dt.date], str]   # (write, week) -> one-line result


def _log(msg: str = "") -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# phase 1
# --------------------------------------------------------------------------
def _s1_newweek(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import newweek
    plan = newweek.plan(week=week)
    if not write:
        return (f"would copy {plan['source']['name']!r} -> {plan['new_name']!r}, "
                f"archive {len(plan['to_archive'])}")
    done = newweek.apply(plan)
    return f"created {done['name']!r}, archived {done['archived']}"


def _s23_prepare(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import prepare
    s = prepare.survey()
    if not write:
        return (f"would clear DD {s['dd_rows']}, order log {s['ol_rows']}, "
                f"bonuses {s['bonus_rows']}; re-drag to {s['extent']}")
    done = prepare.apply(s)
    return (f"cleared {done['dd_cleared']}/{done['ol_cleared']}/"
            f"{done['bonus_cleared']}, re-dragged to {done['redragged_to']}")


#: Crosstabs supplied on the command line, if any. Set by main().
_DD_FILE = None
_OL_FILE = None


def _s45_sources(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import sources
    # A dry run must not launch a browser. Pulling the DD live costs a Tableau
    # session and minutes, which is not what someone asking "what would this
    # do" is agreeing to — so without files to check, say so and move on.
    if not write and not (_DD_FILE or _OL_FILE):
        return ("would pull the DD + order log from Tableau (not attempted in a "
                "dry run — pass --dd-file/--order-log-file to check them)")
    p = sources.plan(week, dd_file=_DD_FILE, ol_file=_OL_FILE)
    blockers = sources._blockers(p)
    if blockers:
        raise RuntimeError("; ".join(blockers))
    if not write:
        return (f"would paste DD {p['dd']['data_rows']} rows "
                f"(week {p['dd']['week']}), order log {p['ol']['data_rows']}")
    done = sources.apply(p)
    return f"pasted DD {done['dd']}, order log {done['ol']}"


def _s8_transfers(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import transfers as T
    found = T.analyze()
    counts = {k: len(v) for k, v in found.items()}
    summary = (f"{counts[T.APPLY_TRANSFER]} transfer(s), "
               f"{counts[T.APPLY_BONUS]} bonus(es), "
               f"{counts[T.REVIEW]} for review, {counts[T.PENDING]} pending")
    if not write:
        return "would apply " + summary
    done = T.apply(found)
    return (f"wrote {done['transfers']} DD cell(s), {done['bonuses']} bonus "
            f"line(s) — {summary}")


def _s9_notify(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import notify
    if not write:
        return f"would post {notify.title_for(week)!r} and tag JD in-thread"
    ts = notify.post(week, verbose=False)
    return f"posted ts={ts}, JD tagged in-thread"


# --------------------------------------------------------------------------
# phase 2
# --------------------------------------------------------------------------
def _s10_pnl(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import notify, pnl
    plan = pnl.analyze()
    summary = (f"{len(plan.matched)} matched, {len(plan.extras)} new, "
               f"{len(plan.ambiguous)} ambiguous")
    if not write:
        return f"would write {summary} into {plan.banner}"
    notify.require_approval(plan.week)          # JD's tick gates the year P&L
    done = pnl.apply(plan)
    note = pnl.additions_message(plan)
    if note:
        try:
            notify.reply(plan.week, note)
        except Exception as e:                  # noqa: BLE001
            _log(f"       (could not post the additions note: {type(e).__name__})")
    return f"wrote {done['cells']} cell(s) — {summary}"


def _s11_apex(write: bool, week: dt.date) -> str:
    from automations.commission_sheet import apex
    plan = apex.plan()
    summary = (f"{len(plan.entries)} rep(s), {len(plan.bonuses)} partner-pay, "
               f"{len(plan.skipped)} skipped")
    if not write:
        return f"would enter {summary}"
    done = apex.apply(plan)
    return f"entered {done['entered']} — {summary}"


PHASE1: List[Step] = [
    Step(1, "start the week", _s1_newweek),
    Step(2, "reset the workbook", _s23_prepare),
    Step(4, "fill the DD + order log", _s45_sources),
    Step(8, "reconcile transfers", _s8_transfers),
    Step(9, "tell JD it is ready", _s9_notify),
]
PHASE2: List[Step] = [
    Step(10, "write Raf PNL 2026", _s10_pnl),
    Step(11, "enter payroll in Apex", _s11_apex),
]


def _last_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def run(steps: List[Step], week: dt.date, write: bool,
        only: Optional[set] = None) -> int:
    label = "WRITE" if write else "dry run"
    _log(f"\nWeek ending {week:%a %d %b %Y}   ({label})")
    _log("=" * 62)
    failed = 0
    for st in steps:
        if only and st.num not in only:
            _log(f"  {st.num:>2}. {st.name:<26} — skipped")
            continue
        try:
            result = st.run(write, week)
            _log(f"  {st.num:>2}. {st.name:<26} ✓ {result}")
        except Exception as e:                  # noqa: BLE001
            _log(f"  {st.num:>2}. {st.name:<26} ✗ {e}")
            if not isinstance(e, (RuntimeError, KeyError, ValueError)):
                _log(traceback.format_exc())
            failed = st.num
            break
    _log("=" * 62)
    if failed:
        _log(f"STOPPED at step {failed}. Later steps assume it landed, so "
             f"nothing after it ran.")
        return 1
    _log("all steps ok" + ("" if write else " — nothing was written"))
    return 0


def _parse_only(text: str) -> set:
    return {int(x) for x in text.replace(" ", "").split(",") if x}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase1", action="store_true",
                   help="unattended: steps 1-5, 8, 9")
    g.add_argument("--phase2", action="store_true",
                   help="after JD's tick: steps 10-11")
    ap.add_argument("--week", default=None, help="week ending as M.D")
    ap.add_argument("--only", type=_parse_only, help="run only these step numbers")
    ap.add_argument("--dd-file", help="use this crosstab instead of pulling")
    ap.add_argument("--order-log-file", help="ditto for the order log")
    ap.add_argument("--write", action="store_true", help="actually do it")
    args = ap.parse_args(argv)

    global _DD_FILE, _OL_FILE
    from pathlib import Path
    _DD_FILE = Path(args.dd_file) if args.dd_file else None
    _OL_FILE = Path(args.order_log_file) if args.order_log_file else None

    if args.week:
        from automations.commission_sheet.newweek import _parse_week
        week = _parse_week(args.week)
    else:
        week = _last_sunday()
    return run(PHASE1 if args.phase1 else PHASE2, week, args.write, args.only)


if __name__ == "__main__":
    raise SystemExit(main())
