"""Rep Sales Fill -- write ONE rep's daily sales onto the Alphalete Sales Board
from Tableau, for the reps the ordinary feeds read as zero.

WHY THIS EXISTS. Andrew Sanborn sits on Rafael's `Alphalete SALES BOARD 2025`
but his sales are credited to ANOTHER ICD -- in the Daily Rep Breakdown he is
"Andrew Sanborn Roadtrip" under Rafael with a whole week of zeros, while the
same week's sales sit under John Richard Young as "Andrew Sanborn". So every
office-scoped feed reads him as zero and his row is the one that lands late or
not at all (8/13: his 4 sales reached the board at 07:38, three hours after the
04:33 production post, so he went out inside the Zero Streak callout).

PRODUCT SALES SUMMARY is scoped by REP, not by owner, so it sees those sales
wherever they land. Filtered to one rep and one week, its
"Sales By ICD (+/-) REP - (+/-) Weekdays" table is exactly the four measures
the board carries -- see parse.PRODUCT_TO_METRIC for the mapping.

SOURCE, spelled out:
  workbook  ATT Tracker 2.1 - D2D
  view      PRODUCT SALES SUMMARY 4WK
  sheet     "Sales By ICD (+/-) REP - (+/-) Weekdays"  (the lower table)
  filters   Rep = the rep -- this one works.
            Sale Date Week Ending = the week's SUNDAY -- THIS ONE DOES NOT
            WORK IN THE URL, in either format. ISO leaves the viz unrendered
            (the Crosstab dialog then offers zero sheets); '8/16/2026' renders
            but is ignored, and two different weeks return identical data.
            See view_url() -- the module is off the scheduler over this.
  target    'Alphalete SALES BOARD 2025' -> tab 'Sales Board WE m.d' ->
            rep's row in col C -> that day's Int / Int Up / DTV / NL cells

WHAT IT WILL NOT DO
  * touch the day's Apps cell -- it is a formula (=Int+DTV+NL+EN, upgrades out);
  * overwrite a roll-call status ('X', 'T', 'RT', 'STF', ...) sitting in a day
    cell, because those share the cells with the counts;
  * write anybody but the rep asked for.
WHICH DAYS IT TOUCHES (Eve 2026-08-14):
  * the TARGET day (--date, default yesterday) is the day being closed, so
    Tableau wins outright and the four cells are written to match it;
  * any EARLIER day in the week is filled only when it is completely empty. A
    day already carrying numbers may have been corrected by hand, so the
    disagreement is printed and nothing moves -- e.g. 8/10 reads 2 Int + 1 DTV
    where Tableau says 1 NEW INTERNET + 1 UPGRADE + 1 WIRELESS (same three
    units, different columns; and since the Apps formula drops upgrades,
    "correcting" it would take that Monday from 3 apps to 2);
  * TODAY and later are never written. The export carries the running count of
    a day still in progress, and filling it would freeze a partial number the
    "only empty days" rule can never revisit.
Pass --overwrite to force an older day you know is wrong.

  python -m automations.rep_sales_fill.run                    # preview yesterday's week
  python -m automations.rep_sales_fill.run --date 2026-08-13
  python -m automations.rep_sales_fill.run --rep "Andrew Sanborn" --apply
  python -m automations.rep_sales_fill.run --from-file out.csv # offline, no Tableau
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.rep_sales_fill import board as B
from automations.rep_sales_fill import parse as P

VIEW = ("https://us-east-1.online.tableau.com/t/sci/views/"
        "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK")
# The WORKSHEET name in the Crosstab dialog, which is NOT the title drawn on the
# dashboard. On screen the lower table reads "Sales By ICD (+/-) REP - (+/-)
# Weekdays"; the dialog calls it this. (Eve's screenshot 2026-08-14 -- the
# dialog offers "Last Refresh (2)", "Product Sales Summary by ORG" and this.)
CROSSTAB_SHEET = "Sales By ICD (Weekly View)"
DEFAULT_REP = "Andrew Sanborn"

# A single rep's week. Anything past this means the Rep filter did not apply
# and we are looking at the whole org -- refuse rather than paint the row.
SANE_WEEK_MAX = 60

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "rep_sales_fill"


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def week_ending(day: dt.date) -> dt.date:
    """The Sunday that closes `day`'s Mon-Sun week -- the board's tab name and
    the view's 'Sale Date Week Ending' value are both this date."""
    return day + dt.timedelta(days=6 - day.weekday())


def week_value(sunday: dt.date, fmt: str = "mdy") -> str:
    """The 'Sale Date Week Ending' value as the filter expects it.

    THIS FILTER IS A DISCRETE DROPDOWN, not a date range -- on screen it reads
    '8/16/2026'. Sending ISO ('2026-08-16') does not merely get ignored here:
    it leaves the viz unrendered, and the Crosstab dialog then offers ZERO
    sheets. Proved one filter at a time on Lucy 2 (2026-08-14): :refresh=yes
    alone -> 3 sheets, Rep alone -> 3 sheets, ISO week alone -> 0.
    (The house note that Tableau url date filters want ISO holds for RANGE
    filters -- Start Date / End Date on the order log. Not for this one.)

    Built by hand, never strftime('%-m/%-d/%Y'): that flag is glibc-only and
    this has to run on macOS and Windows both.
    """
    if fmt == "iso":
        return sunday.isoformat()
    return f"{sunday.month}/{sunday.day}/{sunday.year}"


def view_url(sunday: dt.date, rep: str, filters: str = "both",
             refresh: bool = True, week_format: str = "mdy") -> str:
    """The view URL, with the filters named by `filters`.

    WHY THIS IS A DIAL. On Lucy 2 the Crosstab dialog came back with ZERO
    sheets on this view, while the same dialog opened by hand lists three
    ("Last Refresh (2)", "Product Sales Summary by ORG", "Sales By ICD (Weekly
    View)"). Dropping every url parameter made all three appear -- so something
    in the query string leaves the viz unrendered, and an unrendered viz has no
    worksheets to offer. Three suspects: the week filter's field name, the Rep
    filter's field name, and `:refresh=yes` (a forced re-query on a 4-week
    dashboard). This picks one at a time so the culprit is named, not guessed.

    Pulling unfiltered and selecting the rep in code is NOT an option here: the
    unfiltered sheet comes back one row per ICD ('Aron Corral', 'Total', ...),
    with REP collapsed, so Andrew's numbers are buried inside his owner's.

    The values are fully escaped (safe=""), because `quote()` leaves '/' alone
    by default and '8/16/2026' was going into the query string with raw
    slashes. That is correct hygiene but it is NOT what is broken here -- see
    below; the escaped url returns exactly the same export as the raw one.

    THE WEEK FILTER IS INERT (proved on Lucy 2, 2026-08-14). Asking for WE
    8/16 and for WE 7/19 -- four weeks apart -- returns byte-identical data:

        Tue {Int 1, NL 5} · Wed {Int 1, NL 9} · Thu {NL 2} · Fri {NL 3}

    So Tableau is not reading 'Sale Date Week Ending' as a url-filterable
    field at all; it serves the same default window whatever we ask for. The
    Rep filter DOES apply -- the export comes back with a single owner, John
    Richard Young, which is the ICD Andrew's sales are credited to.

    How to tell the wrong week apart from a quiet one, without another pull:
    that export carries no UPGRADE INTERNET and no VIDEO row at all, while
    Andrew's real WE 8/16 is 10 units WITH an upgrade on Monday and a video on
    Thursday (and no Monday column at all, though he sold 3 that Monday).
    Writing from it blanked his real Thursday from 4 apps down to 2.

    NEXT SUSPECT is the field NAME, not the value: it may be a dashboard
    PARAMETER rather than a filter, or carry a different caption. Until that is
    settled the module stays off the scheduler -- and whatever replaces it has
    to be validated against a known figure of the week asked for, not just
    against the export's own total row (that reconciles fine here: 2 + 19 = 21).
    """
    parts = []
    if refresh:
        parts.append(":refresh=yes")
    if filters in ("both", "week"):
        parts.append("Sale%20Date%20Week%20Ending="
                     + quote(week_value(sunday, week_format), safe=""))
    if filters in ("both", "rep"):
        parts.append(f"Rep={quote(rep, safe='')}")
    return VIEW + ("?" + "&".join(parts) if parts else "")


def pull(sunday: dt.date, rep: str, dest: Path, sheet: str) -> Path:
    from automations.shared.tableau_patchright import download_crosstab_patchright
    dest.parent.mkdir(parents=True, exist_ok=True)
    _log(f"  pulling {sheet!r}")
    _log(f"  {view_url(sunday, rep)}")
    return download_crosstab_patchright(view_url(sunday, rep), sheet,
                                        dest, verbose=True)


def probe_filters(sunday: dt.date, rep: str) -> int:
    """Print every filter control on the dashboard, with its aria-label.

    WHY. The week filter is silently DISCARDED when sent in the url -- the
    export comes back from Tableau's own default window (21 units Tue-Fri for
    an owner whose asked-for week is 10 units Mon-Thu), which is how another
    period's numbers landed in Sanborn's row. Rep= applies fine, so it is this
    one field. Guessing the field name a pull at a time costs ~7 minutes an
    attempt, so read the DOM once instead: Tableau puts the filter's real
    caption in aria-label, which is both the url parameter name AND the
    selector a pre_export hook would drive (see box_order_log.window
    .date_window_hook, which fills textarea[aria-label="Start Date"]).
    """
    from automations.shared.tableau_patchright import (
        tableau_session, _ensure_tableau_authenticated)
    with tableau_session(verbose=True) as page:
        _ensure_tableau_authenticated(page, verbose=False, allow_form_login=True)
        page.goto(VIEW, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(25_000)          # let the viz hydrate
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        _log("")
        _log("--- controles con aria-label dentro de la viz ---")
        seen = []
        for sel in ("[aria-label]",):
            try:
                els = viz.locator(sel)
                n = min(els.count(), 120)
            except Exception as exc:  # noqa: BLE001
                _log(f"  {sel}: {exc}")
                continue
            for i in range(n):
                try:
                    el = els.nth(i)
                    lab = el.get_attribute("aria-label") or ""
                    tag = el.evaluate("e => e.tagName.toLowerCase()")
                    role = el.get_attribute("role") or ""
                    txt = (el.inner_text() or "").strip().replace("\n", " ")[:40]
                except Exception:  # noqa: BLE001
                    continue
                if lab and (lab, tag) not in seen:
                    seen.append((lab, tag))
                    _log(f"  <{tag}{' role=' + role if role else ''}> "
                         f"aria-label={lab!r}  texto={txt!r}")
        _log(f"--- {len(seen)} control(es) ---")
    return 0


def list_sheets(sunday: dt.date, rep: str, filters: str = "both",
                refresh: bool = True, week_format: str = "mdy") -> int:
    """Print the worksheet names the Crosstab dialog actually offers.

    The dialog lists Tableau WORKSHEET names, which are not the titles drawn on
    the dashboard -- 'Sales By ICD (+/-) REP - (+/-) Weekdays' is what the user
    reads on screen and is NOT what the dialog calls it (that mismatch is what
    made the first live run fail). Asking for a sheet that cannot exist makes
    the helper raise with the real list attached, which is the only way to see
    the names without a human at the browser.
    """
    from automations.shared.tableau_patchright import download_crosstab_patchright
    try:
        _log(f"  url: {view_url(sunday, rep, filters, refresh, week_format)}")
        download_crosstab_patchright(view_url(sunday, rep, filters, refresh, week_format),
                                     "__LIST_SHEETS__ (deliberate miss)",
                                     OUT_DIR / "_list_sheets.csv", verbose=True)
    except Exception as exc:  # noqa: BLE001 -- the message IS the payload
        _log("")
        _log("--- hojas que ofrece el Crosstab dialog ---")
        _log(str(exc))
        return 0
    _log("!! the sentinel sheet name somehow matched -- nothing to report")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rep", default=DEFAULT_REP)
    ap.add_argument("--date", help="any day in the target week (YYYY-MM-DD); "
                                   "default yesterday")
    ap.add_argument("--from-file", help="parse this crosstab instead of pulling")
    ap.add_argument("--sheet", default=CROSSTAB_SHEET,
                    help="worksheet name in the Crosstab dialog")
    ap.add_argument("--probe-filters", action="store_true",
                    help="print the dashboard's filter controls + aria-labels, "
                         "then stop (to learn the week filter's real name)")
    ap.add_argument("--list-sheets", action="store_true",
                    help="print the worksheet names the dialog offers, then stop")
    ap.add_argument("--dump", action="store_true",
                    help="diagnostic: pull and print the crosstab's first rows "
                         "raw, to see which columns it actually carries")
    ap.add_argument("--filters", choices=("both", "none", "rep", "week"),
                    default="both",
                    help="which url filters to send. Diagnostic dial: the "
                         "Crosstab dialog comes back empty with 'both' and full "
                         "with 'none', so one of them leaves the viz unrendered")
    ap.add_argument("--week-format", choices=("mdy", "iso"), default="mdy",
                    help="how to write the week-ending value (the filter is a "
                         "discrete dropdown, so 'mdy' is what it expects)")
    ap.add_argument("--no-refresh", action="store_true",
                    help="drop ':refresh=yes' (a forced re-query -- the third "
                         "suspect for the empty dialog)")
    ap.add_argument("--sheet-id", help="write to a different workbook (a copy)")
    ap.add_argument("--apply", action="store_true", help="write (default: preview)")
    ap.add_argument("--overwrite", action="store_true",
                    help="also re-write days that already carry numbers "
                         "(default: fill only the empty days, and report "
                         "disagreements without touching them)")
    a = ap.parse_args(argv)

    from automations.alphalete_production.capture import SHEET_ID, find_week_tab
    from automations.recruiting_report.fill import open_by_key, _retry

    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.date.today() - dt.timedelta(days=1))
    sunday = week_ending(day)
    _log(f"rep: {a.rep}   week ending {sunday.isoformat()}")

    if a.probe_filters:
        return probe_filters(sunday, a.rep)

    if a.list_sheets:
        return list_sheets(sunday, a.rep, filters=a.filters,
                           refresh=not a.no_refresh, week_format=a.week_format)

    if a.dump:
        # The URL filters break this view: with them the viz never renders and
        # the Crosstab dialog offers zero sheets (proved on Lucy 2 2026-08-14,
        # --no-filters lists all three). So the plan is to pull UNFILTERED and
        # select the rep in code -- this prints the raw shape to confirm the
        # sheet carries a Rep column and which week it defaults to.
        from automations.shared.tableau_patchright import download_crosstab_patchright
        dest = OUT_DIR / "_dump.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        _log(f"  url: {view_url(sunday, a.rep, a.filters, not a.no_refresh, a.week_format)}")
        download_crosstab_patchright(view_url(sunday, a.rep, a.filters, not a.no_refresh, a.week_format),
                                     a.sheet, dest, verbose=True)
        rows = P.read_rows(dest)
        _log("")
        _log(f"--- {dest.name}: {len(rows)} filas, ancho max "
             f"{max((len(r) for r in rows), default=0)} ---")
        for i, r in enumerate(rows[:20], start=1):
            _log(f"  {i:>3}: {r}")
        # LAST, because only the tail of the log survives the queue's result
        # cell -- and this summary is the whole point of the diagnostic.
        try:
            d, t = P.parse(dest)
            _log(f"HEADER: {rows[0] if rows else '(vacio)'}")
            _log(f"DAYCOLS: {P.find_weekday_columns(rows)}")
            _log(f"DAYS: {d}")
            _log(f"TOTALS: {t}")
        except Exception as exc:  # noqa: BLE001
            _log(f"PARSE FALLO: {exc}")
        return 0

    # ---- source -----------------------------------------------------------
    if a.from_file:
        src = Path(a.from_file)
        _log(f"  reading {src} (offline)")
    else:
        src = pull(sunday, a.rep, OUT_DIR / f"{sunday.isoformat()}_"
                   f"{a.rep.replace(' ', '_').lower()}.csv", a.sheet)
    days, totals = P.parse(src)

    # RECONCILE AGAINST THE CROSSTAB'S OWN TOTAL ROW before anything is
    # written. A pull of this view can come back with a day's product rows
    # missing (2026-08-14: 13:14 gave Thursday 1 Int + 1 DTV + 2 NL, 13:20 gave
    # the same Thursday as 2 NL alone), and a partial day looks exactly like a
    # quiet day. The total row is the independent check that tells them apart.
    if not totals:
        _log("  !! the export carries no 'Sales Total' / 'Total' row -- nothing "
             "can confirm these numbers. HOLDING, nothing written.")
        return 75
    bad = {d: (sum(m.values()), totals.get(d, 0))
           for d, m in days.items()
           if sum(m.values()) != totals.get(d, 0)}
    if bad:
        _log("")
        _log("  !! el export vino INCOMPLETO -- las filas de producto no suman "
             "el total que declara la propia hoja:")
        for d, (got, want) in sorted(bad.items()):
            _log(f"     {d:<10} product rows {got}  vs  total row {want}")
        _log("     HOLDING, nothing written. Re-correr: el pull no es estable "
             "y una pasada parcial borraria datos buenos.")
        return 75

    week_total = sum(P.day_total(m) for m in days.values())
    units = sum(sum(m.values()) for m in days.values())
    _log("")
    _log("--- Tableau ---")
    for d in P.WEEKDAYS:
        if d in days and days[d]:
            bits = ", ".join(f"{k} {v}" for k, v in sorted(days[d].items()))
            _log(f"  {d:<10} {P.day_total(days[d]):>2} apps   ({bits})")
    _log(f"  {'WEEK':<10} {week_total:>2} apps, {units} units")
    if units > SANE_WEEK_MAX:
        _log(f"  !! {units} units for one rep is not credible -- the Rep filter "
             "almost certainly did not apply. Nothing written.")
        return 75
    # THE TARGET DAY MUST BE IN THE EXPORT. This runs at ~4am inside the
    # morning chain, ahead of the single production post, and Tableau publishes
    # the previous day on its own schedule -- if yesterday has not landed yet
    # the crosstab simply has no column for it, which is indistinguishable from
    # "he sold nothing". Holding (75) makes the orchestrator say so and re-run;
    # writing nothing silently would let the post go out with him at zero,
    # which is the exact failure this module exists to stop.
    target_day = P.WEEKDAYS[day.weekday()]
    if target_day not in days:
        _log(f"  !! {target_day} ({day.isoformat()}) is not a column in the "
             "export -- Tableau has not published that day yet. HOLDING, "
             "nothing written.")
        return 75
    if not any(days.values()):
        _log("  no sales in this week's export -- nothing to write")
        return 0

    # ---- target -----------------------------------------------------------
    ss = open_by_key(a.sheet_id or SHEET_ID)
    ws = find_week_tab(ss, day)
    grid = ws.get_all_values()
    _log("")
    _log(f"sheet: {ss.title!r}  tab: {ws.title!r}"
         + ("" if not a.sheet_id else "   (NOT the prod workbook)"))

    row, note = B.find_rep_row(grid, a.rep)
    if row is None:
        _log(f"  !! {note}")
        return 75
    _log(f"  row {row}: {B.cell(grid, row, B.NAME_COL).strip()!r}"
         + (f"   ({note})" if note else ""))

    blocks = B.day_blocks(grid)
    missing = [d for d in days if d not in blocks]
    if missing:
        _log(f"  !! no day block on this tab for: {', '.join(missing)}")
        return 75

    # ---- plan -------------------------------------------------------------
    from gspread.utils import rowcol_to_a1
    plan, held = [], []
    _log("")
    _log("--- board vs Tableau ---")
    monday = day - dt.timedelta(days=day.weekday())
    today = dt.date.today()
    for d in P.WEEKDAYS:
        if d not in blocks:
            continue
        d_date = monday + dt.timedelta(days=P.WEEKDAYS.index(d))
        # NEVER write a day that is not over. The export carries today's
        # running count, and the "only fill empty days" rule would freeze that
        # partial number forever -- the first live run wrote Friday NL=3 at
        # 13:15 with the day still going.
        if d_date >= today:
            if days.get(d):
                _log(f"  {d:<10} en curso ({d_date.isoformat()}) -- no se toca")
            continue
        wanted = days.get(d, {})
        cols = blocks[d]
        # THE TARGET DAY IS THE ONE WE ARE CLOSING, so Tableau wins outright:
        # that is what "de ahora en mas usa Tableau para Sanborn" means. Every
        # OTHER day is only filled when empty, so a hand correction on an older
        # day (8/10) survives.
        is_target = d_date == day
        writes, notes = B.plan_day(grid, row, cols, wanted,
                                   overwrite=a.overwrite or is_target)
        cur = {m: B.cell(grid, row, c).strip() for m, c in sorted(cols.items())}
        shown = ", ".join(f"{m} {v or '-'}" for m, v in cur.items())
        want = ", ".join(f"{m} {wanted.get(m, 0) or '-'}" for m in sorted(cols))
        mark = "  <<< CAMBIA" if writes else ""
        _log(f"  {d:<10} board [{shown}]")
        _log(f"  {'':<10} tabl. [{want}]{mark}")
        for n in notes:
            _log(f"      ! {n}")
            if "LEFT AS IS" in n:
                held.append(d)
        for metric, col, old, new in writes:
            plan.append((rowcol_to_a1(row, col), metric, old, new))

    _log("")
    if held:
        _log(f"{len(held)} day(s) already filled and DISAGREEING with Tableau, "
             f"left untouched: {', '.join(held)}")
        _log("  (re-run with --overwrite for a day you know the board has wrong)")
    if not plan:
        _log("nothing to write -- every empty day is already accounted for")
        return 0
    _log(f"{len(plan)} cell(s) would change:")
    for a1, metric, old, new in plan:
        _log(f"  {a1:<8} {metric:<7} {old or '(blank)':>8} -> {new or '(blank)'}")

    if not a.apply:
        _log("")
        _log("PREVIEW -- re-run with --apply to write")
        return 0

    _retry(ws.batch_update, [{"range": a1, "values": [[new]]}
                             for a1, _m, _o, new in plan])
    _log(f"wrote {len(plan)} cell(s) to {ws.title!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
