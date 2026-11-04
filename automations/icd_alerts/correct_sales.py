"""Correct ONE rep's pinned sale count on the ICD relay row — a hand tool.

WHY (Carlos 2026-10-27): SaraPlus briefly showed Andrew De La Torre with 8 NL,
then went back to 4. decide_sales' ONLY-UP rule (max(now, was) — right for
never re-announcing a sale) kept the 8 in 'Last Posted Sales' for the rest of
the day, so every standings text after that said 8. The poster logged
"BACKSLID ... NL 8 -> 4" every pass and nothing could lower the number.

This rewrites the one metric for the one rep in column J (Last Posted Sales)
of that office's row for the day, leaving every other rep and the per-rep
credit-check state untouched. The next poster pass then sees relay 4 vs
posted 4: no announcement, and the next standings text carries 4.

    python -m automations.icd_alerts.correct_sales --office carlos-b2batt \
        --rep "Andrew De La Torre" --set NL=4 [--day YYYY-MM-DD] [--send]

Dry run without --send. Queue it from anywhere as
    icd_correct_sales carlos-b2batt "Andrew De La Torre" NL=4
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Dict, Optional, Tuple


def match_rep(keys, rep: str) -> Optional[str]:
    """The relay's rep key for `rep`: exact (case-insensitive) first, else the
    ONE key containing it. None when nothing or more than one matches."""
    want = " ".join(rep.split()).upper()
    keys = [str(k) for k in keys]
    exact = [k for k in keys if " ".join(k.split()).upper() == want]
    if len(exact) == 1:
        return exact[0]
    part = [k for k in keys if want in " ".join(k.split()).upper()]
    return part[0] if len(part) == 1 else None


def apply_correction(last: Dict, rep: str, metric: str, value: int
                     ) -> Tuple[Dict, Optional[str], Optional[int]]:
    """(new Last Posted Sales dict, matched rep key, old value). Only the one
    metric of the one rep changes; extra keys (credit state) are preserved."""
    key = match_rep((last or {}).keys(), rep)
    if key is None:
        return last, None, None
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in (last or {}).items()}
    old = int((out.get(key) or {}).get(metric, 0) or 0)
    out.setdefault(key, {})[metric] = int(value)
    return out, key, old


def parse_set(s: str) -> Tuple[str, int]:
    metric, _, val = (s or "").partition("=")
    metric, val = metric.strip(), val.strip()
    if not metric or not val.lstrip("-").isdigit():
        raise ValueError("--set wants METRIC=N, e.g. NL=4")
    return metric, int(val)


def run(office: str, rep: str, metric: str, value: int, *, day: Optional[dt.date] = None,
        send: bool = False, log=print) -> int:
    from automations.icd_alerts import post as P
    day = day or dt.date.today()
    office = (office or "").strip().lower()
    tab = P._relay_tab()
    rows = [(n, r) for n, r in P._rows_for(day, tab)
            if (r[P.COL_OFFICE] or "").strip().lower() == office]
    if not rows:
        log("no relay row for %s on %s -- nothing to correct" % (office, day.isoformat()))
        return 1
    rownum, row = rows[-1]
    row = list(row) + [""] * (P.COL_LAST_POSTED_SALES + 1 - len(row))
    last = P._loads(row[P.COL_LAST_POSTED_SALES]) or {}
    relay = P._loads(row[P.COL_SALES]) or {}
    new, key, old = apply_correction(last, rep, metric, value)
    if key is None:
        log("rep %r not found (or ambiguous) in Last Posted Sales for %s; reps: %s"
            % (rep, office, ", ".join(sorted(last)) or "(none)"))
        return 1
    relay_now = int((relay.get(key) or {}).get(metric, 0) or 0)
    log("%s row %d  %s  %s: posted %s -> %s  (relay says %s)"
        % (office, rownum, key, metric, old, value, relay_now))
    if old == value:
        log("already %s -- nothing to write" % value)
        return 0
    if not send:
        log("DRY RUN -- re-run with --send to write it")
        return 0
    tab.update_cell(rownum, P.COL_LAST_POSTED_SALES + 1, json.dumps(new))
    log("written. Next poster pass: relay %s vs posted %s -> %s"
        % (relay_now, value, "quiet" if relay_now <= value else "WILL announce the difference"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--office", required=True, help="office key, e.g. carlos-b2batt")
    ap.add_argument("--rep", required=True, help='rep name as the relay spells it, e.g. "Andrew De La Torre"')
    ap.add_argument("--set", required=True, help="METRIC=N, e.g. NL=4")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--send", action="store_true", help="write it (default: dry run)")
    a = ap.parse_args(argv)
    metric, value = parse_set(a.set)
    day = dt.date.fromisoformat(a.day) if a.day else None
    return run(a.office, a.rep, metric, value, day=day, send=a.send)


if __name__ == "__main__":
    sys.exit(main())
