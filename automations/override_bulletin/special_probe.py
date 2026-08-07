"""READ-ONLY: ask Tableau TODAY what it says for the last N weeks, and diff that
against what is already on the tab. Writes NOTHING, anywhere. LUCY 1.

Why this exists
---------------
`backtrack.py` re-pulls the REGULAR component only. Raf's Special Override and
the five DD captain bonuses are pulled ONCE, on the Friday the week is filled,
and never asked again. But the sources keep settling — backtrack's own docstring
records the VA's 7.12 column moving a day later.

On 2026-08-07 Eve's hand-maintained tab and our copy tab disagreed by $19,896.56
across 2026, $14,531.00 of it Raf's Special Override in 6.14 / 6.21 / 6.28 / 7.5.
Eve reads $40,284 for 6.14 in the Tableau view today; the value we filled back in
June was $36,222. Two candidate explanations:

  1. the source SETTLED after we filled it (and nothing ever re-asked), or
  2. `parse_raf_payout` reads a partial figure every time.

They demand different fixes, so this probe settles it before anything is built:
re-pull each week NOW and print Tableau-today vs copy-tab vs Eve's tab. If (1),
the numbers below match Eve and the fix is simply to widen the backtrack. If (2),
they still come back low and the parser is what needs fixing.

It also forces a PERIOD-filtered DD Detail download per period in the window and
dumps every (captain, week) it carries — the open question for extending the
backtrack to the captain bonuses, since `dd_captain_overrides` normally tries the
unfiltered current-week download FIRST and so never exercises the period path.

    lucy rerun override_special_probe
    lucy rerun override_special_probe --weeks 8
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from automations.override_bulletin import build as B
from automations.override_bulletin import fill as F
from automations.override_bulletin import pulls as P
from automations.override_bulletin import run as R

OUT_DIR = Path("output/override_bulletin/special_probe")
DEFAULT_WEEKS = 5          # the sweep window Eve asked for; 8 was gratuitous
TOLERANCE = 0.01


def _sheet_specials(tab):
    """{week label: Raf Special Override on that tab} — read straight off the row,
    so this works even for a tab the bulletin code would filter out."""
    _wl, _c, _r, _cap, prog = B.read_data(tab)
    row = next((p for p in prog if "rafael" in (p["name"] or "").lower()), None)
    if not row:
        return {}
    labels = _wl
    return {lbl: row["series"][i] for i, lbl in enumerate(labels)
            if i < len(row["series"])}


def probe(*, weeks=DEFAULT_WEEKS, tab=None, verbose=True):
    from automations.shared.tableau_patchright import tableau_session
    from automations.recruiting_report import fill as _fill

    tab = tab or F.SANDBOX_TAB
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ws = _fill._client().open_by_key(F.WORKBOOK_ID).worksheet(tab)
    tab_weeks = R.sheet_weeks(ws)[:weeks]
    print(f"tab={tab!r}  probing {len(tab_weeks)} week(s): {', '.join(tab_weeks)}")

    on_copy = _sheet_specials(tab)
    try:
        on_live = _sheet_specials(F.LIVE_TAB)
    except Exception as e:  # noqa: BLE001 — the live tab is a nicety, not required
        print(f"(could not read {F.LIVE_TAB!r}: {type(e).__name__}: {e})")
        on_live = {}

    year = dt.date.today().year
    rows, dd_dumps = [], {}
    with tableau_session(headless=True, verbose=verbose) as page:
        # The retail period that actually CARRIES each week — never the month
        # guess; 7.19 lives in period 8 (see run._scan_summary).
        _src_weeks, week_period, _rows_by = R._scan_summary(
            page, OUT_DIR, verbose=verbose, year=year)

        # ONE download per PERIOD, not per week. Raf-wow's crosstab carries every
        # week of the period as its own column, so `raf_special_override` per week
        # re-downloads the same file N times — the first run of this probe spent
        # 45 minutes doing that for 8 weeks and timed out with nothing to show,
        # blocking the mini's queue behind it. backtrack.regular_for_week solved
        # the same problem with a per-period cache; this is that.
        by_period = {}
        for wk in tab_weeks:
            by_period.setdefault(week_period.get(wk, int(wk.split(".")[0])),
                                 []).append(wk)
        for pnum, wks in sorted(by_period.items(), reverse=True):
            crosstab = None
            try:
                # accept=rows: take the download itself, then parse each week's
                # column out of the ONE file.
                crosstab, used = P._download_first_nonempty(
                    P.RAF_BONUS_VIEW, P.RAF_BONUS_SHEET,
                    OUT_DIR / f"raf-p{pnum}.csv",
                    P.period_candidates(f"Period {pnum}"),
                    page=page, verbose=verbose, accept=lambda rr: rr or None)
                print(f"  period {pnum}: downloaded once for {len(wks)} week(s)"
                      f" (filter {used})")
            except Exception as e:  # noqa: BLE001 — one dead period must not kill the probe
                print(f"  period {pnum}: download FAILED {type(e).__name__}: {e}")
            for wk in wks:
                m, d, y = wk.split(".")
                week_header = f"{int(m)}/{int(d)}/20{y[-2:]}"
                now = None
                if crosstab:
                    try:
                        now = P.parse_raf_payout(crosstab, label="Raf Payout Total",
                                                 week_header=week_header)
                    except Exception as e:  # noqa: BLE001
                        print(f"  {wk}: parse FAILED {type(e).__name__}: {e}")
                rows.append((wk, pnum, now, on_copy.get(wk), on_live.get(wk)))
        rows.sort(key=lambda r: tab_weeks.index(r[0]))

        # --- DD Detail, PERIOD-FORCED (skip the unfiltered current-week path) ---
        captains = list(R.DD_CAPTAINS)
        for pnum in sorted({week_period.get(w, int(w.split(".")[0]))
                            for w in tab_weeks}, reverse=True):
            per = f"Period {year}-{pnum}"
            try:
                got, used = P._download_first_nonempty(
                    P.DD_DETAIL_VIEW, P.DD_DETAIL_SHEET,
                    OUT_DIR / f"dd-{pnum}.csv", P.period_candidates(per),
                    page=page, verbose=verbose,
                    accept=lambda rr: P.parse_dd_captain(
                        rr, {P._norm_name(o) for o in captains}) or None)
            except Exception as e:  # noqa: BLE001
                print(f"  DD {per}: FAILED {type(e).__name__}: {e}")
                continue
            dd_dumps[used or per] = got or {}

    # ---------------------------------------------------------------- report
    print("\n=== RAF SPECIAL OVERRIDE — Tableau TODAY vs the tabs ===")
    print("  {:<9} {:<7} {:>14} {:>14} {:>14}  {}".format(
        "week", "period", "TABLEAU now", "copy tab", "Eve's tab", "verdict"))
    settled = stale = 0
    for wk, pnum, now, copy_v, live_v in rows:
        def f(v):
            return "—" if v is None else f"{v:,.2f}"
        if now is None:
            verdict = "no pull"
        elif live_v is not None and abs(now - live_v) < TOLERANCE:
            verdict = "matches Eve"
            settled += 1
        elif copy_v is not None and abs(now - copy_v) < TOLERANCE:
            verdict = "matches the copy — parser suspect"
            stale += 1
        else:
            verdict = "matches NEITHER"
        print("  {:<9} P{:<6} {:>14} {:>14} {:>14}  {}".format(
            wk, pnum, f(now), f(copy_v), f(live_v), verdict))

    print("\n=== DD DETAIL, period-forced — which weeks does each period carry? ===")
    for per, got in dd_dumps.items():
        wks = sorted({w for d in got.values() for w in d})
        print(f"  {per}: {len(got)} captain(s), weeks: "
              f"{', '.join(wks) if wks else '(none)'}")
        for owner, byweek in sorted(got.items()):
            print("    {:<24} {}".format(
                owner[:24], "  ".join(f"{w}={v:,.0f}" for w, v in
                                      sorted(byweek.items()))))

    print(f"\nVERDICT: {settled} week(s) now match Eve, {stale} still match the "
          f"stale copy.")
    if settled and not stale:
        print("→ The sources SETTLED after we filled them. The pull is healthy; "
              "it just never gets asked twice. Fix = widen the backtrack.")
    elif stale and not settled:
        print("→ Tableau still returns the low figure. The PARSER is what needs "
              "fixing; a wider backtrack alone would change nothing.")
    print("\n(read-only — nothing was written to any tab)")
    return rows, dd_dumps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    ap.add_argument("--tab", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    probe(weeks=a.weeks, tab=a.tab, verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
