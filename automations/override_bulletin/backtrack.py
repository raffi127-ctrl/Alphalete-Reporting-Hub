"""Re-read the last N weeks and correct any that have shifted.

Prior weeks do NOT stay put. The override sources keep settling after a week
closes, so a figure filled on Friday can be wrong by the following Friday. This
is not theoretical — between 2026-07-23 and 07-24 the VA's own 7.12 column moved
underneath us:

    Rafael Hidalgo   $78,595.49 -> $78,890.00
    Carlos Hidalgo   $19,386.17 -> $19,827.94
    Benjamin Burden     $985.35 ->  $1,465.53

So every run re-pulls the recent weeks and fixes what drifted (FILL_SOURCES:
"Backtrack the last 4 weeks every run").

    python -m automations.override_bulletin.backtrack                  # dry run
    python -m automations.override_bulletin.backtrack --write          # sandbox
    python -m automations.override_bulletin.backtrack --weeks 6

WHAT IT CORRECTS — the REGULAR override component only.

The DD Detail download carries just the ONE just-closed week, so a captain's
bonus for a week three back cannot be re-pulled at all. But it is already on the
sheet: section 2 holds the captain/special breakdown per week. So the section-1
cell is rebuilt as `freshly-pulled regular + the section-2 total ALREADY on the
sheet for that week`. Nothing is invented, and a week whose captain figure we
cannot re-source keeps the number it has.

RULES IT KEEPS
  * A person absent from the source for a week is REPORTED, never zeroed — a
    name mismatch looks exactly like a genuine zero (this is how Hammad silently
    lost $1,532.25 a week before the ICD-Aliases wiring).
  * Near month-end a week can appear in TWO periods; both are pulled and summed,
    and the contributing periods are printed.
  * Dry-run by default; a real write is refused against the live tab.

RUN ON LUCY 1 (Raf's org login).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from automations.override_bulletin import fill as F
from automations.override_bulletin import pulls as P
from automations.override_bulletin import run as R

# Weeks to re-check each run (FILL_SOURCES: "the last 4 weeks").
DEFAULT_WEEKS = 4
# Below this, a difference is rounding rather than a real correction.
TOLERANCE = 0.01
OUT_DIR = Path("output/override_bulletin/backtrack")


def periods_for(week_mdy):
    """Period-filter values that may carry this week's money.

    The period usually tracks the month, but near a month edge a week's rows can
    sit in period N *and* N-1 — so we try both and combine, rather than trusting
    the month alone (FILL_SOURCES)."""
    m, _d, y = (int(x) for x in week_mdy.split("."))
    year = 2000 + y if y < 100 else y
    prev_m, prev_y = (12, year - 1) if m == 1 else (m - 1, year)
    return ["Period {}-{}".format(year, m), "Period {}-{}".format(prev_y, prev_m)]


def regular_for_week(week_mdy, *, page=None, verbose=True, cache=None):
    """{canonical_owner: regular override} for one past week, combined across
    every period that carries it. Returns (amounts, periods_used).

    `cache` memoizes the parsed crosstab per period so re-checking four weeks in
    the same month costs ONE download, not four."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    cache = cache if cache is not None else {}
    m, d, y = week_mdy.split(".")
    week_header = "{}/{}/20{}".format(int(m), int(d), y[-2:])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    combined, used = {}, []
    for period in periods_for(week_mdy):
        if period not in cache:
            try:
                url = P._with_filter(P.ORG_SUMMARY_VIEW, "Period", period)
                out = OUT_DIR / ("org-{}.csv".format(period.replace(" ", "_")))
                download_crosstab_patchright(url, P.ORG_SUMMARY_SHEET, out,
                                             page=page, verbose=verbose)
                cache[period] = P.read_crosstab(out)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print("  ({} unavailable: {})".format(period, type(e).__name__))
                cache[period] = None
        rows = cache[period]
        if not rows:
            continue
        try:
            amts = P.parse_override_summary(rows, week_header)
        except ValueError:
            continue                     # this period doesn't carry the week
        if not amts:
            continue
        used.append(period)
        for k, v in amts.items():
            combined[k] = round(combined.get(k, 0) + v, 2)
    return combined, used


def _sheet_cell(vals, row, col):
    """Numeric value at (1-based row, 0-based col) on the sheet, or None."""
    if not row or row - 1 >= len(vals) or col >= len(vals[row - 1]):
        return None
    return P._num_locale(vals[row - 1][col])


def raf_fresh_for_week(week_mdy, *, period_num=None, page=None, verbose=True):
    """Rafael's freshly re-pulled (captain, special) for a past week.

    These are the two components backtrack could NOT re-source before — it trusted
    whatever section 2 already held, so a special the VA later REVISED sat stale
    (his 7.12-6.14 froze ~$3k high after a downward revision, 2026-08-01). Both are
    full-history sources, unlike the DD captains: captain from Raf PNL (by label),
    special from Payout-Raf-wow (matched by the week's Processed-Week date).

    `period_num` is the RETAIL period the week lives in — pass the value from the
    summary scan, NOT the calendar month: near a period edge a week (6.21, 6.28)
    sits in the NEXT retail period (7), so Raf-wow's month-6 export wouldn't carry
    it. We still try the month period as a fallback candidate. Best effort — a
    flaky/absent pull returns None and the caller keeps the on-sheet value."""
    cap = spec = None
    try:
        cap = P.raf_captain_override(week_mdy)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("  (raf captain unavailable: {})".format(type(e).__name__))
    try:
        m, d, y = week_mdy.split(".")
        wh = "{}/{}/20{}".format(int(m), int(d), y[-2:])
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # retail period first (from the scan), month as a fallback candidate
        periods = []
        if period_num:
            periods.append("Period {}".format(period_num))
        periods.append(P.period_for(week_mdy, style="num"))
        for per in dict.fromkeys(periods):        # de-dup, keep order
            spec = P.raf_special_override(wh, OUT_DIR / "raf-bt.csv",
                                          period=per, page=page, verbose=verbose)
            if spec is not None:
                break
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("  (raf special unavailable: {})".format(type(e).__name__))
    return cap, spec


def cap_special_on_sheet(vals, captains, key, col):
    """The captain/special total ALREADY on the sheet for this person + week.

    Read from section 2's leader row, which is the =SUM over their Captain /
    Special sub-rows. For a past week this is the only available source (the DD
    download only ever holds the just-closed week), and it is the same number
    that fed the original fill."""
    rows = captains.get(key)
    if not rows:
        return 0.0
    r = rows.get("total")
    if not r or r - 1 >= len(vals):
        return 0.0
    row = vals[r - 1]
    return (P._num_locale(row[col]) or 0.0) if col < len(row) else 0.0


def plan_week(ws, vals, week_mdy, roster, captains, regular, *, raf=None):
    """[(row, name, old, new)] cells whose value has drifted, plus [names] we
    couldn't source for this week.

    `raf` = (raf_key, fresh_captain, fresh_special) when Rafael's PNL/Raf-wow were
    re-pulled this run. His section-1 total is rebuilt from those fresh components
    (each falling back to its on-sheet sub-row if the pull came back None), and his
    Captain / Special sub-rows in section 2 are corrected too — the rest of the
    roster still rebuilds as `fresh regular + the section-2 total on the sheet`,
    because their captains (DD) can't be re-sourced for a past week."""
    col = F.week_col(ws, week_mdy, header=vals[0])
    if col is None:
        return [], [], None
    raf_key = raf[0] if raf else None
    changes, unmatched = [], []
    for key, (row, active, disp) in roster.items():
        if not active:
            continue
        reg = regular.get(key)
        if reg is None:
            unmatched.append(disp)
            continue                       # never zero a person out on a re-read
        if key == raf_key:
            rc = captains.get(raf_key, {})
            cap = raf[1] if raf[1] is not None else _sheet_cell(vals, rc.get("captain"), col)
            spc = raf[2] if raf[2] is not None else _sheet_cell(vals, rc.get("special"), col)
            capspec = (cap or 0) + (spc or 0)
        else:
            capspec = cap_special_on_sheet(vals, captains, key, col)
        new = round(reg + capspec, 2)
        old = P._num_locale(vals[row - 1][col]) if (
            row - 1 < len(vals) and col < len(vals[row - 1])) else None
        if old is None or abs(new - old) > TOLERANCE:
            changes.append((row, disp, old, new))
    # Rafael's section-2 Captain / Special sub-rows, when freshly re-pulled.
    if raf_key and raf_key in captains:
        for comp, val in (("captain", raf[1]), ("special", raf[2])):
            r = captains[raf_key].get(comp)
            if not r or val is None:
                continue
            old = _sheet_cell(vals, r, col)
            if old is None or abs(round(val, 2) - old) > TOLERANCE:
                changes.append((r, "Rafael Hidalgo ({})".format(comp), old, round(val, 2)))
    return changes, unmatched, col


def backtrack(*, tab=F.SANDBOX_TAB, weeks=DEFAULT_WEEKS, write=False, verbose=True):
    from automations.recruiting_report import fill as _fill
    from automations.shared.tableau_patchright import tableau_session

    wb = _fill._client().open_by_key(F.WORKBOOK_ID)
    ws = wb.worksheet(tab)
    aliases = F.load_alias_map()
    roster = F.read_roster(ws, aliases)
    captains = F.read_captains(ws, aliases)
    vals = ws.get_all_values()
    targets = R.sheet_weeks(ws)[:weeks]
    print("backtrack {} week(s) on {!r}: {}".format(
        len(targets), tab, ", ".join(targets)))

    raf_key = F.canon("Rafael Hidalgo", aliases)
    all_changes, cache = [], {}
    with tableau_session(headless=True, verbose=verbose) as page:
        # Retail-period map (week -> period) so Rafael's special is pulled from the
        # period that actually carries the week, not its calendar month (6.21/6.28
        # live in period 7, not 6). Best-effort; falls back to month per-week.
        try:
            _sw, week_period, _rb = R._scan_summary(page, OUT_DIR, verbose=verbose)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print("  (period scan unavailable: {}; using month)".format(
                    type(e).__name__))
            week_period = {}
        for wk in targets:
            regular, used = regular_for_week(wk, page=page, verbose=verbose,
                                             cache=cache)
            if not regular:
                print("\n{}: source carries no data for this week — left alone".format(wk))
                continue
            regular = F.rekey(regular, aliases)
            # Rafael's captain (PNL) + special (Raf-wow) are re-pullable for a past
            # week — re-source them so a revised special self-corrects instead of
            # sitting stale in section 2.
            raf_cap, raf_spec = raf_fresh_for_week(
                wk, period_num=week_period.get(wk), page=page, verbose=verbose)
            changes, unmatched, col = plan_week(ws, vals, wk, roster, captains,
                                                regular, raf=(raf_key, raf_cap, raf_spec))
            print("\n{} (from {}): {} cell(s) drifted".format(
                wk, " + ".join(used) or "?", len(changes)))
            for _row, name, old, new in changes:
                print("    {:<28} {} -> {}".format(name[:28], old, new))
            if unmatched:
                print("    no source row ({}): {}".format(
                    len(unmatched), ", ".join(unmatched)))
            all_changes += [(F._col_letter(col), r, n, o, v)
                            for r, n, o, v in changes]

    if not all_changes:
        print("\nnothing drifted — every checked week still matches its source.")
        return []
    if not write:
        print("\n[dry-run] would correct {} cell(s). Re-run with --write "
              "(sandbox only).".format(len(all_changes)))
        return all_changes
    if ws.title == F.LIVE_TAB:
        raise RuntimeError("refusing to write the live tab {!r} — sandbox only".format(
            F.LIVE_TAB))
    ws.batch_update([{"range": "{}{}".format(c, r), "values": [[v]]}
                     for c, r, _n, _o, v in all_changes],
                    value_input_option="USER_ENTERED")
    print("\ncorrected {} cell(s) on {!r}".format(len(all_changes), ws.title))
    return all_changes


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Re-read the last N weeks and correct any that drifted")
    ap.add_argument("--tab", default=F.SANDBOX_TAB)
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    ap.add_argument("--write", action="store_true",
                    help="apply the corrections (sandbox tab only)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    backtrack(tab=a.tab, weeks=a.weeks, write=a.write, verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
