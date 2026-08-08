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

EVERY component, as of 2026-08-07 — this used to be the regular override alone:

  regular            ORG Override Summary, by retail period
  Raf captain        Raf PNL 2026, row "Captain Override"
  Raf special        Payout- Raf wow, by retail period
  5 DD captains      ORG DD Detail, PERIOD-forced (--apply-dd to write)
  Credico / special  the NetSuite ledger, via the red P#-YYYY markers
  Credico ALREADY placed (black marker) — re-read and CARRIED BACK into the
    rebuilt cell (placed_credico). It lives inside the section-1 regular
    component but is absent from the Tableau summary we re-pull, so without
    this every backtrack silently erased it.

The DD line was long believed impossible: the DEFAULT download carries only the
just-closed week. But it is the WEEK filter that breaks that view, not the
PERIOD filter — one period download carries every week in it (dd_search.py).

Anyone whose components could NOT be re-sourced still rebuilds as `freshly-pulled
regular + the section-2 total ALREADY on the sheet`. Nothing is invented, and a
week whose captain figure we cannot re-source keeps the number it has.

RULES IT KEEPS
  * A person absent from the source for a week is REPORTED, never zeroed — a
    name mismatch looks exactly like a genuine zero (this is how Hammad silently
    lost $1,532.25 a week before the ICD-Aliases wiring).
  * Near month-end a week can appear in TWO periods; both are pulled and summed,
    and the contributing periods are printed.
  * A cell that holds a FORMULA is never overwritten — the tab mixes typed
    numbers and formulas irregularly inside a single row, and a value written
    over one destroys it silently. Reported instead.
  * A week carrying a PLACED credico we cannot re-resource is SKIPPED WHOLE —
    rebuilding it without the credico is how the money vanished on 2026-08-07.
    Stale beats erased, and a black marker is never re-placed by anything else.
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

# Weeks to re-check each run. Eve 2026-08-07 raised this from 4 to 5: on 8/07 the
# copy tab sat $19,896.56 below her hand-kept tab across 2026, and every stale
# week (6.14, 6.21, 6.28, 7.5) was OUTSIDE a 4-week window, so nothing ever
# re-read them. The window is the whole guarantee — a source that settles after a
# week falls out of it stays wrong forever.
DEFAULT_WEEKS = 5
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


def regular_for_week(week_mdy, *, period=None, page=None, verbose=True, cache=None):
    """{canonical_owner: regular override} for one past week. Returns (amounts,
    periods_used).

    `period` (from the summary scan) is the RETAIL period that actually carries
    the week — when given it is used ALONE and is authoritative. 7.19 lives in
    period 8, so the old month-based guess pulled period 7's crosstab, which hands
    back an EMPTY/partial 7.19 column and made the backtrack propose ZEROING real
    values (the 7.19 corruption). Only when the retail period is unknown do we fall
    back to periods_for's month guess (and combine, in case the week splits).

    `cache` memoizes the parsed crosstab per period so re-checking four weeks in
    the same period costs ONE download, not four."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    cache = cache if cache is not None else {}
    m, d, y = week_mdy.split(".")
    week_header = "{}/{}/20{}".format(int(m), int(d), y[-2:])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    combined, used = {}, []
    for period in ([period] if period else periods_for(week_mdy)):
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


def dd_captains_for_period(period_num, year, *, page=None, verbose=True, cache=None):
    """{owner_norm: {dd_week: amount}} for a PERIOD-FORCED DD Detail download.

    The old belief — written into this module's docstring and FILL_SOURCES — was
    that a past week's captain bonus "cannot be re-pulled at all" because the DD
    download only carries the just-closed week. That is true of the DEFAULT
    download, and `pulls.dd_captain_overrides` tries that one FIRST, so the period
    path never gets exercised. But dd_search.py records the working rule:

        "the crosstab's default download carries only the just-closed week, so
         history needs the Period filter: July covers 7.5 / 7.12 / 7.19"

    It is the WEEK filter that breaks the view, not the PERIOD filter. So we skip
    the unfiltered candidate entirely and force the period — one download per
    period yields every week in it, since parse_dd_captain already returns a
    per-week dict.

    Cached per (year, period): re-checking five weeks that share a period costs
    ONE download, not five."""
    cache = cache if cache is not None else {}
    ck = ("dd", year, period_num)
    if ck in cache:
        return cache[ck]
    per = "Period {}-{}".format(year, period_num)
    want = {P._norm_name(o) for o in R.DD_CAPTAINS}
    got, used = None, None
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        got, used = P._download_first_nonempty(
            P.DD_DETAIL_VIEW, P.DD_DETAIL_SHEET,
            OUT_DIR / "dd-p{}.csv".format(period_num),
            P.period_candidates(per), page=page, verbose=verbose,
            accept=lambda rr: P.parse_dd_captain(rr, want) or None)
    except Exception as e:  # noqa: BLE001 — a dead DD period must never fail the run
        if verbose:
            print("  (DD {} unavailable: {})".format(per, type(e).__name__))
    cache[ck] = (got or {}, used)
    return cache[ck]


def ledger_reconcile(ws, *, aliases, roster, captains, page=None, verbose=True,
                     write=False, led_rows=None):
    """Place any PENDING (red) P#-YYYY marker whose money has now landed.

    Credico and the Carlos/Colten special arrive LATE — weeks after the column is
    filled. `run.py` already knows how to place them, but only on a pass that
    actually fills a week: a HOLD pass returns before the marker step, and once
    the week is filled every later pass HOLDS. So on a normal Friday the late
    money is never placed. Running it here means it is retried on every backtrack,
    hold or not, which is exactly when it should be.

    Reuses markers.plan_placements / apply_placements verbatim — placement is
    marker-driven, never derived, and a period with no marker is reported rather
    than guessed."""
    from automations.override_bulletin import markers as M
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # placed_credico already downloaded it this run — one crosstab is ~3min,
        # and the two passes want the SAME snapshot anyway.
        led = led_rows if led_rows else P.ledger_rows(
            OUT_DIR / "ledger.csv", page=page, verbose=verbose)
        to_place, pending, orphans = M.plan_placements(
            ws, led, aliases=aliases, owner_col=P.LEDGER_OWNER_COL,
            expl_col=P.LEDGER_EXPL_COL, amt_col=P.LEDGER_AMT_COL)
    except Exception as e:  # noqa: BLE001 — never let the ledger fail the backtrack
        print("  ⚠ ledger reconcile skipped: {}: {}".format(
            type(e).__name__, str(e).splitlines()[0][:140]))
        return
    if to_place:
        print("\nlate override(s) landed ({}):".format(len(to_place)))
        M.apply_placements(ws, to_place, roster=roster, captains=captains,
                           dry_run=not write)
    for mk in pending:
        print("  still pending: {} {} (marked at {}) — left red".format(
            mk["kind"], mk["period"], mk["week"]))
    for o in orphans:
        print("  ⚠ {} {} is in the ledger but has NO marker — NOT placed".format(
            o["kind"], o["period"]))


def drop_formula_cells(ws, changes, *, verbose=True):
    """(writable, skipped) — never overwrite a cell that holds a FORMULA.

    The tab mixes typed numbers and formulas IRREGULARLY, even inside one row:
    on 2026-08-07 Carlos's section-1 row was typed at 7.19 and 7.5 but `=`
    formulas at 6.28 / 6.21 / 6.14. Writing a value over one of those destroys
    it silently, and the wider the window the more of them a sweep reaches. So
    every planned write is checked against a FORMULA render first, and a formula
    cell is reported instead of written — a drifted formula is a human's call.

    `changes` are (col_idx0, row1, name, old, new)."""
    try:
        forms = ws.get_values(value_render_option="FORMULA")
    except Exception as e:  # noqa: BLE001 — if we cannot check, do not write blind
        print("  ⚠ could not read formulas ({}: {}) — refusing to write".format(
            type(e).__name__, str(e)[:100]))
        return [], list(changes)
    writable, skipped = [], []
    for ch in changes:
        c, r = ch[0], ch[1]
        raw = forms[r - 1][c] if (r - 1 < len(forms) and c < len(forms[r - 1])) else ""
        (skipped if str(raw).startswith("=") else writable).append(ch)
    if skipped and verbose:
        print("\n⚠ {} cell(s) hold a FORMULA — left alone:".format(len(skipped)))
        for c, r, name, old, new in skipped:
            print("    {}{:<6} {:<28} {} -> {} (not written)".format(
                F._col_letter(c), r, name[:28], old, new))
    return writable, skipped


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


def placed_credico(ws, *, aliases, page=None, verbose=True):
    """({week label: {key: amount}}, {week labels we could NOT resource}).

    THE CELL IS NOT `regular + section 2`. Credico is folded into the section-1
    REGULAR component (FILL_SOURCES) — `markers.apply_placements` ADDS it straight
    into the person's section-1 row and flips the marker black. But the Tableau
    ORG Override Summary that `regular_for_week` re-pulls has never carried it, so
    a rebuild of `fresh regular + section-2 total` SILENTLY DROPS every credico
    ever placed, and the black marker means `ledger_reconcile` will never put it
    back: a black marker is deliberately never re-placed. The money leaves and
    nothing says so.

    Measured on 2026-08-07: the 18:26 `--write` pass took $4,280.69 of P6-2026
    credico off the 7.5.26 column (Burden -1,689.75, Carlos -1,554.57, Rafael
    -1,036.37) and 7.19.26 had already lost $1,081.57 the same way on an earlier
    pass — the SAME three people, splitting each month's pool in the SAME
    proportions (39.474% / 36.316% / 24.210%), which is what gave it away.

    So: re-read the ledger for every PLACED (black) credico marker and hand the
    amounts back to plan_week, which adds them on top of the fresh regular. Same
    source, same placement rule, just re-applied. Pending (red) markers are NOT
    included — their money has not landed, ledger_reconcile owns them, and adding
    them here would place money the sheet has never shown.

    The second return value is the guard that matters: a week whose credico we
    could not re-resource (ledger download failed, view moved, ledger no longer
    carries that month) is NOT rebuilt at all. Erasing it again would be worse
    than leaving it stale."""
    from automations.override_bulletin import markers as M
    by_week, unresolved = {}, set()
    try:
        marks = [m for m in M.read_markers(ws)
                 if m["kind"] == M.CREDICO and not m["pending"] and m["week"]]
    except Exception as e:  # noqa: BLE001
        print("  ⚠ could not read the credico markers ({}: {}) — every week that "
              "carries one will be left alone".format(
                  type(e).__name__, str(e).splitlines()[0][:120]))
        return {}, {"*"}, None
    if not marks:
        return {}, set(), None
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        led = P.ledger_rows(OUT_DIR / "ledger.csv", page=page, verbose=verbose)
    except Exception as e:  # noqa: BLE001
        print("  ⚠ ledger unavailable ({}: {}) — leaving the {} week(s) that carry "
              "a placed credico alone: {}".format(
                  type(e).__name__, str(e).splitlines()[0][:120], len(marks),
                  ", ".join(sorted({m["week"] for m in marks}))))
        return {}, {m["week"] for m in marks}, None
    for mk in marks:
        amounts = M.amounts_for(led, M.CREDICO, mk["period"],
                                owner_col=P.LEDGER_OWNER_COL,
                                expl_col=P.LEDGER_EXPL_COL,
                                amt_col=P.LEDGER_AMT_COL)
        if not amounts:
            print("  ⚠ credico {} is marked PLACED at {} but the ledger no longer "
                  "carries it — that week is left alone".format(
                      mk["period"], mk["week"]))
            unresolved.add(mk["week"])
            continue
        got = F.rekey(amounts, aliases)
        tot = sum(got.values())
        by_week.setdefault(mk["week"], {})
        for k, v in got.items():
            by_week[mk["week"]][k] = round(by_week[mk["week"]].get(k, 0) + v, 2)
        if verbose:
            print("  credico {} placed at {}: {} owner(s), ${:,.2f} carried back "
                  "into the rebuild".format(mk["period"], mk["week"], len(got), tot))
    return by_week, unresolved, led


def plan_week(ws, vals, week_mdy, roster, captains, regular, *, fresh=None,
              credico=None):
    """[(row, name, old, new)] cells whose value has drifted, plus [names] we
    couldn't source for this week.

    `credico` = {canonical_key: amount} already PLACED into this week's column
    (see placed_credico). It is part of the section-1 number and is added on top
    of the fresh regular; without it every rebuild erases it.

    `fresh` = {canonical_key: {"captain": v|None, "special": v|None}} for whoever
    had their section-2 components RE-SOURCED this run. Rafael gets both (PNL +
    Raf-wow); the five DD captains get "captain" when the period-forced DD pull
    carried their week. For those people the section-1 cell is rebuilt from the
    fresh components (each falling back to its on-sheet sub-row when the pull
    returned None) and their section-2 sub-rows are corrected too. Anyone not in
    `fresh` still rebuilds as `fresh regular + the section-2 total on the sheet`,
    which invents nothing and keeps the number they have."""
    col = F.week_col(ws, week_mdy, header=vals[0])
    if col is None:
        return [], [], [], None
    fresh = fresh or {}
    credico = credico or {}
    changes, unmatched, suspicious = [], [], []
    for key, (row, active, disp) in roster.items():
        if not active:
            continue
        reg = regular.get(key)
        if reg is None:
            unmatched.append(disp)
            continue                       # never zero a person out on a re-read
        if key in fresh:
            rc = captains.get(key, {})
            fc, fs = fresh[key].get("captain"), fresh[key].get("special")
            cap = fc if fc is not None else _sheet_cell(vals, rc.get("captain"), col)
            spc = fs if fs is not None else _sheet_cell(vals, rc.get("special"), col)
            capspec = (cap or 0) + (spc or 0)
        else:
            capspec = cap_special_on_sheet(vals, captains, key, col)
        new = round(reg + capspec + (credico.get(key) or 0.0), 2)
        old = P._num_locale(vals[row - 1][col]) if (
            row - 1 < len(vals) and col < len(vals[row - 1])) else None
        # SAFETY GUARD: never let a re-pull ZERO a cell that holds a real value.
        # A regular that comes back ~0 for someone who had a real override is the
        # signature of a PARTIAL / wrong-PERIOD pull (Period 7 handing back an empty
        # 7.19 column), NOT a genuine correction — that is what silently corrupted
        # 7.19. Skip it and REPORT rather than write the zero. A real drop-to-zero
        # is rare and safer surfaced than auto-applied.
        if abs(new) < 1.0 and old is not None and abs(old) > 1.0:
            suspicious.append((disp, old, new))
            continue
        if old is None or abs(new - old) > TOLERANCE:
            changes.append((row, disp, old, new))
    # Section-2 Captain / Special sub-rows for everyone re-sourced this run.
    for key, comps in fresh.items():
        if key not in captains:
            continue
        disp = comps.get("display") or key
        for comp in ("captain", "special"):
            val = comps.get(comp)
            r = captains[key].get(comp)
            if not r or val is None:
                continue
            old = _sheet_cell(vals, r, col)
            label = "{} ({})".format(disp, comp)
            if abs(round(val, 2)) < 1.0 and old is not None and abs(old) > 1.0:
                suspicious.append((label, old, val))
                continue
            if old is None or abs(round(val, 2) - old) > TOLERANCE:
                changes.append((r, label, old, round(val, 2)))
    return changes, unmatched, suspicious, col


def backtrack(*, tab=F.SANDBOX_TAB, weeks=DEFAULT_WEEKS, write=False, verbose=True,
              apply_dd=False, ledger=True):
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

        # Credico already placed into these columns. Read ONCE (one ledger
        # download for the whole run) BEFORE any week is planned, because a week
        # we cannot resource must be skipped rather than rebuilt without it.
        credico_by_week, credico_blocked, led_rows = placed_credico(
            ws, aliases=aliases, page=page, verbose=verbose)

        for wk in targets:
            if "*" in credico_blocked or wk in credico_blocked:
                print("\n{}: carries a PLACED credico we could not re-resource — "
                      "left alone (rebuilding it would erase the credico)".format(wk))
                continue
            m, _d, y = wk.split(".")
            wk_year = 2000 + int(y) if int(y) < 100 else int(y)
            per_num = week_period.get(wk)
            retail_period = "Period {}-{}".format(wk_year, per_num) if per_num else None
            regular, used = regular_for_week(wk, period=retail_period, page=page,
                                             verbose=verbose, cache=cache)
            if not regular:
                print("\n{}: source carries no data for this week — left alone".format(wk))
                continue
            regular = F.rekey(regular, aliases)
            # Rafael's captain (PNL) + special (Raf-wow) are re-pullable for a past
            # week — re-source them so a revised special self-corrects instead of
            # sitting stale in section 2.
            raf_cap, raf_spec = raf_fresh_for_week(
                wk, period_num=per_num, page=page, verbose=verbose)
            fresh = {raf_key: {"captain": raf_cap, "special": raf_spec,
                               "display": "Rafael Hidalgo"}}

            # The other five captains' bonuses, from a PERIOD-FORCED DD download.
            # REPORTED but not written unless --apply-dd: this path has never run
            # against production, and a wrong captain figure moves the whole
            # section-1 cell. Read the log once, then turn it on.
            if per_num:
                dd_by_owner, dd_used = dd_captains_for_period(
                    per_num, wk_year, page=page, verbose=verbose, cache=cache)
                if dd_by_owner:
                    print("  DD {} ({}): {} captain(s)".format(
                        wk, dd_used, len(dd_by_owner)))
                for name in R.DD_CAPTAINS:
                    key = F.canon(name, aliases)
                    byweek = dd_by_owner.get(P._norm_name(name)) or \
                        dd_by_owner.get(P._norm_name(key)) or {}
                    amt = R._dd_week_for(byweek, wk) if byweek else None
                    if amt is None:
                        continue
                    on_sheet = _sheet_cell(
                        vals, captains.get(key, {}).get("captain"),
                        F.week_col(ws, wk, header=vals[0]))
                    same = on_sheet is not None and abs(amt - on_sheet) <= TOLERANCE
                    print("    DD {:<18} sheet={} tableau={}{}".format(
                        name[:18], on_sheet, round(amt, 2),
                        "" if same else "   <-- DIFFERS"))
                    if apply_dd and not same:
                        fresh.setdefault(key, {})
                        fresh[key].update({"captain": amt, "display": name})
                if dd_by_owner and not apply_dd:
                    print("    (report only — re-run with --apply-dd to write these)")

            changes, unmatched, suspicious, col = plan_week(
                ws, vals, wk, roster, captains, regular, fresh=fresh,
                credico=credico_by_week.get(wk))
            print("\n{} (from {}): {} cell(s) drifted".format(
                wk, " + ".join(used) or "?", len(changes)))
            for _row, name, old, new in changes:
                print("    {:<28} {} -> {}".format(name[:28], old, new))
            if suspicious:
                # A real value re-pulled as ~0 = partial/wrong-period pull. NOT
                # written; surfaced so a human (or the next clean pass) handles it.
                print("    ⚠ SKIPPED {} suspicious zero(s) — kept the on-sheet "
                      "value: {}".format(len(suspicious), ", ".join(
                          "{} ({}→{})".format(n, o, nw) for n, o, nw in suspicious)))
            if unmatched:
                print("    no source row ({}): {}".format(
                    len(unmatched), ", ".join(unmatched)))
            all_changes += [(col, r, n, o, v) for r, n, o, v in changes]

        # Late Credico / Carlos-Colten special: retried on EVERY backtrack, which
        # is the only pass that reliably runs once a week is filled.
        if ledger:
            ledger_reconcile(ws, aliases=aliases, roster=roster, captains=captains,
                             page=page, verbose=verbose, write=write,
                             led_rows=led_rows)

    if not all_changes:
        print("\nnothing drifted — every checked week still matches its source.")
        return []
    # A formula cell is never overwritten — checked BEFORE the dry-run report too,
    # so a dry run says what would really happen rather than promising writes that
    # the real run would skip.
    writable, skipped = drop_formula_cells(ws, all_changes, verbose=verbose)
    if not write:
        print("\n[dry-run] would correct {} cell(s){}. Re-run with --write "
              "(sandbox only).".format(
                  len(writable),
                  " and skip {} formula cell(s)".format(len(skipped)) if skipped else ""))
        return writable
    if ws.title == F.LIVE_TAB:
        raise RuntimeError("refusing to write the live tab {!r} — sandbox only".format(
            F.LIVE_TAB))
    if not writable:
        print("\nnothing writable — every drifted cell holds a formula.")
        return []
    ws.batch_update([{"range": "{}{}".format(F._col_letter(c), r), "values": [[v]]}
                     for c, r, _n, _o, v in writable],
                    value_input_option="USER_ENTERED")
    print("\ncorrected {} cell(s) on {!r}{}".format(
        len(writable), ws.title,
        " ({} formula cell(s) left alone)".format(len(skipped)) if skipped else ""))
    return writable


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Re-read the last N weeks and correct any that drifted")
    ap.add_argument("--tab", default=F.SANDBOX_TAB)
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    ap.add_argument("--write", action="store_true",
                    help="apply the corrections (sandbox tab only)")
    ap.add_argument("--apply-dd", action="store_true",
                    help="also WRITE the five DD captains' re-pulled bonuses. "
                         "Without it they are pulled and reported only — read the "
                         "log once before trusting a path that has never run.")
    ap.add_argument("--no-ledger", action="store_true",
                    help="skip the late Credico / special reconcile")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    backtrack(tab=a.tab, weeks=a.weeks, write=a.write, verbose=not a.quiet,
              apply_dd=a.apply_dd, ledger=not a.no_ledger)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
