"""Get {campaign: {ICD: active headcount}} — one adapter per box.

EVERY ADAPTER REUSES AN EXISTING PULL. Six of the seven campaigns are already
downloaded from Tableau every Monday by the focus reports; this module calls
those same downloaders and those same parsers rather than re-implementing the
crosstab shapes, so a view that gets rebuilt is fixed in ONE place and both
reports move together. `sources.py` records which module each one belongs to.

WHY IT NEVER WRITES A ZERO IT DIDN'T SEE. An ICD the source does not mention is
returned as ABSENT, not as 0. Absent and zero are different facts — one means
"the view didn't carry them", the other "they sold nothing" — and only the fill
gets to decide what to do about it (it leaves the cell alone and reports the
name). Writing 0 for a missing ICD is how a whole campaign silently reads as
dead, which is the failure mode `delta_manual_fill` was built to avoid.

CACHING. Each adapter writes its crosstab under `output/org_active_headcount/`
and `--skip-download` re-parses whatever is there. That is what makes it
possible to check a parser against real data without opening a browser — and it
matters here, because a Tableau download takes over the one Chrome profile this
machine has [[feedback_one-chrome-profile-serialize-browser-runs]].
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict, Optional

from automations.org_active_headcount import sources as src

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

WORKSPACE = Path(__file__).resolve().parents[2]
CACHE_DIR = WORKSPACE / "output" / "org_active_headcount"


def _to_int(s) -> Optional[int]:
    """A Tableau count cell -> int. '-'/'' are a real zero; junk is None so the
    caller can tell "no number here" from "the number is nought"."""
    t = str(s or "").replace(",", "").strip()
    if t in ("", "-", "–", "—"):
        return 0
    try:
        return int(float(t))
    except ValueError:
        return None


STALE_DAYS = 8      # a weekly report's crosstab is stale the moment it's a week old

# The B2B one-pager, ALLTEAMS custom view (team filter pinned to All). Same URL
# `carlos_captainship_headcount` uses; its two ICD Summary sheets are named with
# an explicit (TW)/(LW) suffix PLUS Tableau's dedup counter, and the counter has
# to be written out here. opt_phase's matcher strips exactly ONE trailing
# parenthetical, so 'ICD Summary - ATT (V2) (TW)' normalises to
# 'ICD Summary - ATT (V2)' while the real thumbnail '... (TW) (3)' normalises to
# '... (TW)' — they never meet, and the run dies saying the sheet is missing.
# With the counter spelled out the exact match wins, and if Tableau ever bumps
# it the rename-tolerant fallback still lands on the right sheet.
B2B_VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER-B2B/D2D1-PAGERV3/"
                "49e48afc-de23-4d5d-98ad-e8b1b246d640/ALLTEAMS")
B2B_SHEET_TW = "ICD Summary - ATT (V2) (TW) (3)"
B2B_SHEET_LW = "ICD Summary - ATT (V2) (LW) (2)"

# Retail JE. Same workbook + custom view `org_sales_board/je_pull` uses for
# the ORG board's JE section, a different worksheet on it.
JE_WEEKLY_SHEET = "Weekly Metrics by ICD"
JE_HEADCOUNT_COL = "Productive Rep Count"

# BOX. The DAILY tracker, not the Sales Metrics view `opt_box` reads — Eve,
# 2026-09-07: "podes seleccionar la semana y levantar el 'Total rep count' de
# BOX por ICD". Its week filter caption is this view's OWN wording; sending the
# usual '(mon-sun)' one is ignored without an error.
BOX_TRACKER_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                   "B2BBOXEnergyTracker/BoxDailyTracker?:iid=1")
BOX_SHEET = "Daily Tracker Metrics"
BOX_WEEK_FIELD = "Sale Date Weekending"
# The sheet also carries 'Selling Rep Count' (reps who actually sold), which is
# what the other six campaigns count. Eve named 'Total Rep Count', so that is
# what is written; the difference is real (Roshan Ahmad 19 selling vs 22 total
# in WE 09.06) and worth revisiting if the boxes should all mean one thing.
BOX_HEADCOUNT_COL = "Total Rep Count"


def _warn_stale(path: Path, logfn) -> None:
    """Say so when --skip-download is about to parse an OLD crosstab.

    This is the one way this report can be confidently wrong: a cached CSV
    parses perfectly and fills the current week's column with some other week's
    numbers, and nothing anywhere looks broken. On 2026-09-07 the NDS, BOX and
    SARA caches on this machine were from JUNE 29 — Frank Matos and Abel Draper
    read as 'not in source' purely because they had not joined yet when those
    files were written. Loud beats silent [[project_alert-wording-and-manifest-id-traps]].
    """
    import datetime as _dt
    p = Path(path)
    if not p.exists():
        return
    age = (_dt.datetime.now()
           - _dt.datetime.fromtimestamp(p.stat().st_mtime)).days
    if age >= STALE_DAYS:
        logfn(f"  [STALE] {p.name} is {age} days old - these are NOT this "
              f"week's numbers. Re-run without --skip-download.")


def _by_norm(pairs) -> Dict[str, int]:
    """[(name, value)] -> {normalised name: int}, dropping unparseable values."""
    out: Dict[str, int] = {}
    for name, value in pairs:
        key = src.norm(name)
        n = _to_int(value)
        if key and n is not None:
            out[key] = n
    return out


# ---------------------------------------------------------------- adapters --

def _monday_run(today=None) -> bool:
    """Is this a Monday run — the day these dashboards' 'This Week' IS the week
    that just closed?

    THE ONE-WEEK TRAP. Every ATT dashboard here carries a 'this week' sheet and
    a '(LW)' sheet, and which one holds the week we want depends on the DAY:

      Monday      'This Week' = Mon..Sun of the week that ended yesterday  <-- ours
                  '(LW)'      = the week before that
      Tue..Sun    'This Week' = the week in progress
                  '(LW)'      = the week that closed                       <-- ours

    Measured, not assumed (2026-09-07): the pager's 'Summary Product by Day'
    sheet labelled its This Week columns 'Mon (08-31)' .. 'Sun (09-06)' on a
    Monday, and the '(LW)' crosstab came back byte-for-byte identical to the one
    downloaded the previous TUESDAY — same 10,446 bytes, same 102 rows. So on a
    Monday '(LW)' is two weeks back, and reading it would have filled every
    Fiber and B2B cell with a week-old number that looks perfectly plausible.

    `carlos_captainship_headcount` reached the same conclusion from the other
    side: its Monday run takes the CURRENT-week sheet, and `--last-week` exists
    only for catching up a week that has already scrolled past.
    """
    import datetime as _dt
    return (today or _dt.date.today()).weekday() == 0


def fiber(*, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """ATT Fiber Team — the ATT ICD Summary crosstab the Focus Report pulls."""
    from automations.recruiting_report import opt_phase as op
    path = op.ATT_PATH
    # 'ICD Summary - ATT (V2)' on a Monday, the (LW) twin the rest of the week —
    # see _monday_run. The dialog has no '(TW)' thumbnail on this pager; the
    # unsuffixed name IS the current-week sheet.
    sheet = op.ATT_SHEET if _monday_run() else op.ATT_SHEET_LW
    if not skip_download:
        logfn(f"  fiber: crosstab sheet {sheet!r}")
        op.download_crosstab(op.ATT_VIEW_URL, sheet, path)
    else:
        _warn_stale(path, logfn)
    rows = _read_crosstab(path)
    if not rows:
        logfn(f"  fiber: no crosstab at {path}")
        return {}
    owner_i, count_i = _cols(rows[0], "ICD Owner Name", "Rep Count")
    if owner_i is None or count_i is None:
        raise ValueError(f"{path.name}: no 'ICD Owner Name' + 'Rep Count' header")
    return _by_norm((r[owner_i], r[count_i]) for r in rows[1:]
                    if len(r) > max(owner_i, count_i)
                    and r[owner_i].strip().lower() != "grand total")


def nds(*, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """ATT NDS Team — 'Rep Count' off TT-LineN/P Detail, via opt_nds' parser."""
    from automations.alphalete_org_report import opt_nds as on
    url, sheet, filename = on.NDS_VIEWS[0]
    path = on.OUTPUT_DIR / filename
    if not skip_download:
        on._download_crosstab_subprocess(url, sheet, path)
    else:
        _warn_stale(path, logfn)
    detail = on.parse_tt_detail(path)
    if not detail:
        logfn(f"  nds: nothing parsed from {path}")
        return {}
    return _by_norm((name, rec.get("rep_count", ""))
                    for name, rec in detail.items())


def b2b(*, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """B2B — 'Rep Count' off the B2B one-pager's ICD Summary.

    Which of its two sheets holds the closed week depends on the day: see
    `_monday_run`. On a Monday that is the (TW) sheet, which is exactly the
    choice `carlos_captainship_headcount`'s own Monday run makes."""
    from automations.recruiting_report import opt_phase as op
    from automations.carlos_captainship_headcount import tableau_pull as tp
    last_week = not _monday_run()
    path = tp.cache_path(last_week=last_week)
    sheet = B2B_SHEET_LW if last_week else B2B_SHEET_TW
    if not skip_download:
        logfn(f"  b2b: crosstab sheet {sheet!r}")
        # opt_phase's downloader, NOT tableau_pull's own. Both drive the same
        # dialog on the same dashboard, but tableau_pull's died at `save_as`
        # with TargetClosedError on three separate runs on 2026-09-07 (twice
        # chained after another pull, once alone in a fresh process) — the
        # browser context drops right as the file lands. opt_phase's version
        # re-navigates and retries, and recovered from the same crash twice on
        # the Fiber pull minutes earlier [[project_chrome-crash-dead-context-rebuild]].
        op.download_crosstab(B2B_VIEW_URL, sheet, path)
    else:
        _warn_stale(path, logfn)
    counts = tp.parse_counts(path)
    if not counts:
        logfn(f"  b2b: nothing parsed from {path}")
        return {}
    return _by_norm(counts.items())


def box(*, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """BOX — 'Total Rep Count' per ICD off the Box DAILY Tracker."""
    return box_week(_target_week(), skip_download=skip_download, logfn=logfn)


def box_week(week_end, *, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """BOX active headcount for ONE week, week PINNED in the URL.

    Eve pointed at this view on 2026-09-07 and it replaced the one this module
    started with. The old source (`BoxSalesMetrics` / 'Sales Metrics', which is
    what `opt_box` reads) disagreed with it badly — Carlos Hidalgo came back as
    3 there against 16 here — and it had no way to ask for a past week at all,
    which is why BOX was the one campaign written off as unrecoverable. This
    view carries every BOX ICD including Carlos Hidalgo and Abel Draper, both of
    whom had no history anywhere else.

    THE WEEK IS PINNED, NOT ASSUMED. Left alone on a Monday this dashboard sits
    on the NEW week and returns a day of data dressed as a week — the same trap
    `section_pull.BOX_SPEC` documents, down to the caption: the filter here is
    'Sale Date Weekending', NOT the '(mon-sun)' wording every other view uses,
    and Tableau ignores a wrong caption in SILENCE. Pin it and the sheet is
    whatever week you asked for, which is also what makes the history reachable.
    """
    from urllib.parse import quote
    from pathlib import Path as _P
    from automations.recruiting_report import opt_phase as op
    from automations.alphalete_org_report.opt_nds import OUTPUT_DIR
    path = _P(OUTPUT_DIR) / f"_hc_box_{week_end:%Y%m%d}.csv"
    if not skip_download and not (path.exists() and path.stat().st_size > 300):
        url = (f"{BOX_TRACKER_URL}&{quote(BOX_WEEK_FIELD)}"
               f"={quote(week_end.isoformat())}")
        logfn(f"  box: {BOX_SHEET!r} pinned to WE {week_end}")
        op.download_crosstab(url, BOX_SHEET, path)
    else:
        _warn_stale(path, logfn)
    rows = _read_crosstab(path)
    if not rows:
        logfn(f"  box: no crosstab at {path}")
        return {}
    owner_i, count_i = _cols(rows[0], "Owner Name", BOX_HEADCOUNT_COL)
    if owner_i is None or count_i is None:
        raise ValueError(f"{path.name}: no 'Owner Name' + {BOX_HEADCOUNT_COL!r} "
                         f"header - saw {rows[0]}")
    return _by_norm((r[owner_i], r[count_i]) for r in rows[1:]
                    if len(r) > max(owner_i, count_i)
                    and r[owner_i].strip().lower() not in ("total", "grand total"))


def retail(*, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """Retail NL + Retail Internet — DISTINCT reps with a sale, off ONE SARA
    scrape. Both boxes read this same dict, exactly as the ORG Sales Board's two
    retail sections share a single `sara_retail` pull."""
    from automations.alphalete_org_report import opt_retail as orl
    path = _sara_path(orl)
    if not skip_download:
        _scrape_sara(orl, path)
    else:
        _warn_stale(path, logfn)
    totals = orl.parse_sara_view_data(path)
    if not totals:
        logfn(f"  retail: nothing parsed from {path}")
        return {}
    return _by_norm((name, rec.get("_active_reps", 0))
                    for name, rec in totals.items())


def je(*, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """Retail JE — count the ICD's reps that sold, off the 6-week tracker.

    The only campaign with no existing headcount pull: `opt_je.py` reads JE
    per STORE, which cannot answer "how many heads". This view can — it is one
    row per (ICD, rep) with Total Sales per week — so active heads = the ICD's
    rep rows with sales > 0, the same rule `opt_retail` uses for SARA.
    """
    return je_week(_target_week(), skip_download=skip_download, logfn=logfn)


def _target_week():
    """The week this run is about — the board's reporting Sunday."""
    import datetime as _dt
    from automations.org_sales_board.week import reporting_sunday
    return reporting_sunday(_dt.date.today())


def je_week(week_end, *, skip_download: bool = False, logfn=print) -> Dict[str, int]:
    """Retail JE active heads for ONE week — 'Productive Rep Count' per ICD.

    THE FIRST TWO SOURCES WERE BOTH WRONG, and the way they were wrong is worth
    keeping (2026-09-07):

      • The JE focus tabs have NO headcount row at all. Brandon Stallkamp's tab
        read 0/7 weeks not because nobody filled it but because the JE template
        never had the row. Nothing to fix there.
      • The 6-week conversion tracker (`opt_je.JE_CONV_*`) parses fine and is
        week-pinnable, but it only knows Brandon Stallkamp and Cinthya Reyes,
        and it returned NOTHING at all from the week of 08-02 onward. Two of the
        board's three JE ICDs — Aiysha Mariano and Alex Nicholas — never appear
        in it. Meanwhile the ORG Sales Board shows all three selling (Aiysha 46
        units, Alex 35, Brandon 3 in WE 09.06), so an empty answer there was
        never "JE is quiet", it was the wrong table.

    The right one is the workbook the ORG board's own JE section already reads:
    `JustEnergyRTL-SalesStaffingProductivityWorkbook`, worksheet
    'Weekly Metrics by ICD', column `Productive Rep Count`. All three board ICDs
    are on it.

    THE WEEK IS DRIVEN, NOT ASSUMED. That view's saved week goes stale silently
    — it is exactly why `je_pull` sets the 'Sales Week Ending' dropdown itself on
    every run — so this reuses `je_pull`'s dropdown driver rather than trusting
    whatever week the view happens to open on.
    """
    from pathlib import Path as _P
    from automations.org_sales_board import je_pull
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.alphalete_org_report.opt_nds import OUTPUT_DIR
    path = _P(OUTPUT_DIR) / f"_hc_je_weekly_{week_end:%Y%m%d}.csv"
    if not skip_download and not (path.exists() and path.stat().st_size > 500):
        label = je_pull._week_label(week_end)
        logfn(f"  je: 'Weekly Metrics by ICD', Sales Week Ending={label}")
        download_crosstab_patchright(
            je_pull.CV_URL, JE_WEEKLY_SHEET, path, verbose=False,
            pre_export=je_pull._drive_week_selection(label, False))
    else:
        _warn_stale(path, logfn)
    rows = _read_crosstab(path)
    if not rows:
        logfn(f"  je: no crosstab at {path}")
        return {}
    name_i, count_i = _cols(rows[0], "ICD Name", JE_HEADCOUNT_COL)
    if name_i is None or count_i is None:
        raise ValueError(f"{path.name}: no 'ICD Name' + {JE_HEADCOUNT_COL!r} "
                         f"header - saw {rows[0]}")
    return _by_norm((r[name_i], r[count_i]) for r in rows[1:]
                    if len(r) > max(name_i, count_i)
                    and r[name_i].strip().lower() not in ("total", "grand total"))


ADAPTERS: Dict[str, Callable[..., Dict[str, int]]] = {
    "fiber": fiber, "nds": nds, "b2b": b2b,
    "box": box, "retail": retail, "je": je,
}


# ------------------------------------------------------------------ helpers --

def _read_crosstab(path: Path):
    """Tableau crosstab -> rows. Shared with opt_nds so the UTF-16/XLSX
    sniffing lives in exactly one place."""
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    return _read_tab_csv(Path(path))


def _cols(header, *labels):
    """Column index per label, matched case-insensitively on the header text.
    Returns None for a label that isn't there — never a guessed position."""
    lower = [(h or "").strip().lower() for h in header]
    return tuple(lower.index(l.lower()) if l.lower() in lower else None
                 for l in labels)


def _sara_path(orl) -> Path:
    """The file opt_retail's Retail OPT phase parks its SARA View-Data scrape
    in. Same directory + same filename it uses, so a run right after the Retail
    OPT phase can re-read it with --skip-download instead of scraping twice."""
    return Path(orl.OUTPUT_DIR) / orl.RETAIL_SARA_PLUS_OFFICE_FILENAME


def _scrape_sara(orl, path: Path) -> None:
    """Scrape SARA Plus for the reporting week, the way opt_retail does it.

    Same URL builder, same activate_xy and same scrape kwargs — that (0.5, 0.5)
    activate is not cosmetic: without it Tableau leaves 'Download -> Data'
    disabled on this multi-worksheet dashboard and the scrape dies as a bare
    30s click timeout, which is exactly how the two Retail ICDs lost three
    weeks of numbers in August 2026."""
    import datetime as dt
    from automations.shared.tableau_patchright import scrape_view_data_patchright
    from automations.org_sales_board.week import reporting_sunday

    # '%m/%d/%y' (never '%-m' — that is a Mac-only strftime and this has to run
    # on Windows too). opt_retail's builder parses it with strptime, which takes
    # the zero-padded form just as happily.
    week_label = reporting_sunday(dt.date.today()).strftime("%m/%d/%y")
    scrape_view_data_patchright(
        orl._sara_view_data_url(week_label), path, verbose=False,
        activate_xy=orl.RETAIL_SARA_ACTIVATE_XY,
        # Same scroll tuning opt_retail uses on this grid: the default
        # alternating incremental+jump strategy skips middle rows on SARA's
        # 3-owner table, and a skipped owner reads as a missing ICD.
        scrape_kwargs=dict(jump_every=None, scroll_step=0.35,
                           scroll_wait_ms=1800, stale_max=30))


def collect(*, skip_download: bool = False, only: Optional[list] = None,
            logfn=print) -> tuple:
    """{box: {ICD: headcount}} for every campaign, plus what went wrong.

    One download per SHARED adapter, not per box — Retail NL and Retail
    Internet come out of a single SARA scrape. A campaign whose pull fails is
    recorded in `errors` and left out; the rest still fill, because one dead
    view must not cost the other six their week
    [[feedback_dead-source-pings-not-fails-the-card]].
    """
    by_box: Dict[str, Dict[str, int]] = {}
    errors: Dict[str, str] = {}
    cache: Dict[str, Dict[str, int]] = {}
    for campaign in src.CAMPAIGNS:
        if only and campaign.box not in only:
            continue
        key = campaign.shared_key or campaign.adapter
        if key in cache:
            by_box[campaign.box] = cache[key]
            logfn(f"  {campaign.box}: reusing the {key} pull")
            continue
        try:
            got = ADAPTERS[campaign.adapter](skip_download=skip_download,
                                             logfn=logfn)
        except Exception as e:                                   # noqa: BLE001
            errors[campaign.box] = f"{type(e).__name__}: {e}"
            logfn(f"  {campaign.box}: SKIPPED - {type(e).__name__}: {e}")
            continue
        cache[key] = got
        by_box[campaign.box] = got
        logfn(f"  {campaign.box}: {len(got)} ICD(s) from {campaign.workbook}")
    return by_box, errors
