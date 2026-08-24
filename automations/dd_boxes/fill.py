"""Write one week into every DD-style box.

Rules, all of them deliberate:
  * weekly sales are APPEND-ONLY per cell — a week already filled is never
    overwritten, so a hand-corrected number survives a re-run
  * cancel / churn / start date are RE-SEEDED every week: they're rolling
    measures, so last week's value is stale, not history
  * a rep the sources don't carry gets 0, never a blank — a blank reads as
    "the report didn't run" (Eve 2026-08-17)
  * the averages move to the newest 8 / newest 4 weeks that carry data, or the
    '8 WK Average' silently freezes on an old window
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import gspread

from automations.recruiting_report import fill as rfill
from . import boxes as B

METRIC_KEYS = ("c030", "c3060", "churn_0-30", "churn_30", "churn_60", "churn_90")
AVG8_WINDOW, AVG4_WINDOW = 8, 4
LOW_WEEKS_WARN = 4          # warn when this few empty week columns remain


def _a1(row: int, col: int) -> str:
    return gspread.utils.rowcol_to_a1(row, col)


def resolve_rep(name: str, roster: Dict[str, str]) -> Optional[str]:
    """Sheet spelling -> roster key. Goes through the shared ICD alias list
    first, so a fix lands in one place instead of per-report."""
    from automations.due_diligence.pull import _match_name
    try:
        from automations.focus_office_att import aliases
        canonical = aliases.alias_to_canonical(name, aliases.load_aliases()) or name
    except Exception:       # noqa: BLE001 — the alias sheet must not sink a run
        canonical = name
    return _match_name(canonical, roster) or _match_name(name, roster)


def plan_box(box: B.Box, grid: List[List[str]], we: dt.date, src,
             roster: Dict[str, str],
             backfill: Optional[List[dt.date]] = None
             ) -> Tuple[List[Tuple[str, object]], List[str]]:
    """(updates, notes) for one box. Pure — touches no Sheet."""
    ups: List[Tuple[str, object]] = []
    notes: List[str] = []

    week_col = box.weeks.get(we)
    if not week_col:
        notes.append(f"{box.tab} r{box.header_row}: no column for WE {we} — "
                     f"the box ends at {max(box.weeks)}; add more week columns")
        return ups, notes

    filled_weeks = sorted(d for d in box.weeks if d <= we)
    if backfill:
        filled_weeks = sorted(set(filled_weeks) | {d for d in backfill
                                                   if d in box.weeks})
    remaining = len([d for d in box.weeks if d > we])
    if remaining <= LOW_WEEKS_WARN:
        notes.append(f"{box.tab} r{box.header_row}: only {remaining} empty week "
                     f"column(s) left after this one")

    for row, name in box.reps:
        key = resolve_rep(name, roster)
        if key is None:
            notes.append(f"{box.tab} r{row}: '{name}' matched no rep in any "
                         f"source — left untouched (check the spelling)")
            continue

        # --- weekly units: append-only -----------------------------------
        cur = B._cell(grid, row, week_col)
        if cur:
            notes.append(f"{box.tab} r{row} WE {we}: already has {cur!r} — kept")
        else:
            units = src.units(key, box.side)
            ups.append((_a1(row, week_col), 0 if units is None else units))

        # --- backfill: past weeks still empty ----------------------------
        for past in backfill or []:
            col = box.weeks.get(past)
            if not col or col == week_col or B._cell(grid, row, col):
                continue
            u = src.units_for_week(key, box.side, past)
            if u is None and past not in getattr(src, "_week_csv", {}):
                continue            # no crosstab for that week — leave it alone
            ups.append((_a1(row, col), 0 if u is None else u))

        # --- rolling metrics: re-seeded ----------------------------------
        if box.side != "ts":        # a Total-Sales box carries no cancel/churn
            vals = {}
            vals.update(src.metrics(key, box.side))
            vals.update(src.churn(key, box.side))
            for k in METRIC_KEYS:
                col = box.cols.get(k)
                if col:
                    ups.append((_a1(row, col), vals[k]))
        start_col = box.cols.get("start")
        if start_col:
            sd = src.start_date(key)
            if sd:
                ups.append((_a1(row, start_col), sd))

        # --- averages over the newest 8 / newest 4 filled weeks -----------
        for avg_key, window in (("avg8", AVG8_WINDOW), ("avg4", AVG4_WINDOW)):
            col = box.cols.get(avg_key)
            if not col:
                continue
            span = filled_weeks[-window:]
            if not span:
                continue
            ups.append((_a1(row, col),
                        f"=AVERAGE({_a1(row, box.weeks[span[0]])}:"
                        f"{_a1(row, box.weeks[span[-1]])})"))

    # --- Total / Per rep AVG rows ----------------------------------------
    # The SAME columns the rep rows above just got: the current week always,
    # plus every backfilled week. Until 2026-08-24 both rows were written for
    # week_col ONLY, so a --backfill filled the rep cells of an old week and
    # left its Total / Per rep AVG blank -- Tony Chavez's Total Sales box came
    # back with WE 8/02-8/16 filled per rep and those two rows empty, which
    # reads as a half-done backfill. A past week is append-only here for the
    # same reason the rep cells are: never overwrite a hand-entered total.
    past_cols = [c for c in (box.weeks.get(d) for d in (backfill or []))
                 if c and c != week_col]

    def _week_rows(row: int, formula) -> None:
        ups.append((_a1(row, week_col), formula(week_col)))
        for col in past_cols:
            if not B._cell(grid, row, col):
                ups.append((_a1(row, col), formula(col)))

    if box.total_row and box.reps:
        r0, r1 = box.reps[0][0], box.reps[-1][0]
        _week_rows(box.total_row,
                   lambda c: f"=SUM({_a1(r0, c)}:{_a1(r1, c)})")
        for avg_key, window in (("avg8", AVG8_WINDOW), ("avg4", AVG4_WINDOW)):
            col = box.cols.get(avg_key)
            span = filled_weeks[-window:]
            if col and span:
                ups.append((_a1(box.total_row, col),
                            f"=AVERAGE({_a1(box.total_row, box.weeks[span[0]])}:"
                            f"{_a1(box.total_row, box.weeks[span[-1]])})"))
    if box.avg_row and box.reps:
        r0, r1 = box.reps[0][0], box.reps[-1][0]
        _week_rows(box.avg_row,
                   lambda c: f"=AVERAGE({_a1(r0, c)}:{_a1(r1, c)})")
        for avg_key in ("avg8", "avg4"):
            col = box.cols.get(avg_key)
            if col:
                ups.append((_a1(box.avg_row, col),
                            f"=AVERAGE({_a1(r0, col)}:{_a1(r1, col)})"))
    return ups, notes


def fill_tab(ws, we: dt.date, src, roster: Dict[str, str],
             dry_run: bool = False,
             backfill: Optional[List[dt.date]] = None) -> dict:
    grid = rfill._retry(ws.get_all_values)
    found = B.find_boxes(grid, ws.title)
    if not found:
        return {"tab": ws.title, "status": "NO_BOX", "boxes": 0}
    real_weeks = [we - dt.timedelta(days=7 * i) for i in range(60)]
    all_ups, all_notes = [], []
    for box in found:
        B.reconcile_week_years(box, real_weeks)
        ups, notes = plan_box(box, grid, we, src, roster, backfill=backfill)
        all_ups += ups
        all_notes += notes
    if all_ups and not dry_run:
        rfill._retry(ws.batch_update,
                     [{"range": a, "values": [[v]]} for a, v in all_ups],
                     value_input_option="USER_ENTERED")
    return {"tab": ws.title, "status": "OK", "boxes": len(found),
            "cells": len(all_ups), "notes": all_notes,
            "detail": [str(b) for b in found]}
