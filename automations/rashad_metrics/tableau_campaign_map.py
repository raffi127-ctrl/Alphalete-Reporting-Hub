"""Which ICDs run which campaigns, read off Tableau instead of OwnerVille.

WHY NOT THE OWNERVILLE PICKER. `disposition_signup.campaign_scan` reads the
campaign ids an office's OV page OFFERS, and offered is not knocked. Every
derived answer it gave moved once an owner looked at it (2026-09-10): Carlos's
links carried BASE Energy and he runs two campaigns; Calvin's carried Box and
the code had him down as Energy Wells only. It also cannot see the offices whose
OV is recruiting-only — Michael Antidormi, Fabian Diaz, Carl Foss, Ty Singkhek
have no Disposition module at all, so there is no picker to read.

WHAT THIS READS INSTEAD. An owner appears wherever they work, and the set of
places they appear IS their campaign list (Megan 2026-09-10: "someone can be on
multiple tabs so we need to look at all") — read from the system that bills the
work, not the one that lists what the UI offers.

THE SPLIT IS BY WORKBOOK, NOT BY TAB. First guess was that D2D1-PAGERV4 held one
ICD Summary per campaign; --list-sheets on 2026-09-10 disproved it. All 14 of
its worksheets are ATT — two ICD Summary tabs that are the SAME campaign at two
time frames (this week / "(LW)"), two Sales By ICD, and charts. Treating tabs as
campaigns would have invented a campaign called "ATT (2)" out of a Last Week
tab. The campaigns are separate WORKBOOKS: ATTTRACKER2_1-D2D is ATT-D2D,
ATTTRACKER-B2B is B2B, NDS-SNRES-ATT-OOFWorkbook is the NDS side.

Checked against the ATT tab alone on the 2026-08-19 crosstab, membership agreed
with all seven offices whose campaign we know: Christian, Jay and Chan Park
present (all knock RES AT&T), Carlos, Benjamin, Calvin and Isaiah absent.

THE ONE THING IT CANNOT DO IS REMOVE A CAMPAIGN. Each crosstab is a SNAPSHOT of
one completed week, so an owner who worked a campaign but had no reps on it that
week is simply absent — indistinguishable from an owner who does not run it at
all. Absence is therefore never evidence. That is why --weeks unions several
weeks (a quiet week cannot drop a campaign) and why the output is proposed
ADDITIONS only: removing one stays a question for the owner.

    python -m automations.rashad_metrics.tableau_campaign_map --list-workbooks
    python -m automations.rashad_metrics.tableau_campaign_map --list-sheets <url>
    python -m automations.rashad_metrics.tableau_campaign_map --weeks 3
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAGER_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "ATTTRACKER2_1-D2D/D2D1-PAGERV4/"
             "b5402a05-ab18-4b6a-8ad2-ddeede0b60d5/Personalsalesexp")

OUT_DIR = Path(__file__).resolve().parents[2] / "output"
OWNER_COL = "ICD Owner Name"

# The per-campaign tabs are the ones that summarise BY ICD. The workbook also
# holds rep-level and housekeeping sheets ("zzz Last Refresh"), which carry no
# campaign meaning and would each become a fake campaign.
SHEET_PREFIX = "ICD Summary"


def _log(msg: str) -> None:
    print(f"[tableau-campaigns] {msg}", flush=True)


def campaign_of_sheet(name: str) -> str:
    """"ICD Summary - ATT (V2) (TW)" -> "ATT". The tab name IS the campaign;
    the version and time-frame suffixes are Tableau's, not the campaign's."""
    label = name.split("-", 1)[1] if "-" in name else name
    for junk in ("(V2)", "(V3)", "(V4)", "(TW)", "(LW)", "(Weekly View)"):
        label = label.replace(junk, "")
    return " ".join(label.split()).strip(" -")


WORKBOOKS_URL = "https://us-east-1.online.tableau.com/#/site/sci/workbooks"


def list_workbooks(page) -> list:
    """Every workbook name this Tableau login can see.

    The campaign list has to come from here rather than from the three
    workbooks that happen to be wired into reports already — those are the ones
    somebody needed, not the ones that exist, and an unwired campaign is exactly
    where an unmapped multi-campaign office would hide.
    """
    page.goto(WORKBOOKS_URL, wait_until="networkidle", timeout=120_000)
    page.wait_for_timeout(6000)
    for sel in ('a[href*="/workbooks/"]',
                '[data-tb-test-id*="workbook"] a',
                '[class*="tb-card"] a'):
        try:
            names = page.eval_on_selector_all(
                sel, "els => els.map(e => (e.innerText||'').trim())") or []
            names = sorted({n for n in names if n and len(n) < 120})
            if names:
                return names
        except Exception:  # noqa: BLE001 — try the next shape of the page
            continue
    return []


def list_sheets(page, url: str = PAGER_URL) -> list:
    """Every worksheet name in this view's Download → Crosstab dialog.

    NEVER PRESSES ESCAPE. On this canvas dashboard Escape clears the applied
    'Time Frame' quick filter, which silently widens every later export from one
    week to all weeks (Megan 2026-06-08, ~7k rows). Recover by re-clicking the
    toolbar button instead.
    """
    page.goto(url, wait_until="networkidle", timeout=120_000)
    page.wait_for_timeout(6000)
    viz = page.frame_locator('[title="Data Visualization"]')
    dl = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
    xtab = viz.locator(
        '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]')
    thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
    for attempt in range(1, 8):
        try:
            if not xtab.is_visible(timeout=1500):
                dl.click(force=True, timeout=30_000)
                page.wait_for_timeout(1800)
            xtab.click(force=True, timeout=10_000)
            page.wait_for_timeout(2500)
        except Exception:  # noqa: BLE001 — the flyout is flaky under the overlay
            page.wait_for_timeout(3500 * attempt)
            continue
        n = thumbs.count()
        if n:
            out = []
            for i in range(n):
                try:
                    out.append(thumbs.nth(i).inner_text(timeout=2000).strip())
                except Exception:  # noqa: BLE001
                    pass
            return out
        page.wait_for_timeout(3000 * attempt)
    return []


def _owners(path: Path) -> set:
    """Owner names in a crosstab CSV. UTF-16 / tab-delimited, per the
    downloader's own note; the fallbacks are for a re-saved export."""
    raw = path.read_bytes()
    text = ""
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except Exception:  # noqa: BLE001
            continue
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows or len(rows[0]) < 2:
        rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return set()
    try:
        col = rows[0].index(OWNER_COL)
    except ValueError:
        col = 0
    return {" ".join(r[col].split()).strip()
            for r in rows[1:] if len(r) > col and r[col].strip()}


def pull(sheets: list, weeks: list, *, headless: bool = True) -> dict:
    """{owner: {campaign: [weeks seen]}} across every sheet and week."""
    from automations.recruiting_report.opt_phase_carlos import (
        ViewConfig, download_view_crosstab,
    )
    from automations.shared.tableau_patchright import tableau_session

    found: dict = {}
    with tableau_session(verbose=False, headless=headless) as page:
        for week in weeks:
            for sheet in sheets:
                camp = campaign_of_sheet(sheet)
                out = OUT_DIR / "campaign_tabs" / f"{camp}-{week}.csv"
                out.parent.mkdir(parents=True, exist_ok=True)
                view = ViewConfig(key=f"camp-{camp}", url=PAGER_URL,
                                  sheet_thumbnail_match=sheet)
                try:
                    download_view_crosstab(view, out, verbose=False,
                                           week=week, page=page)
                except Exception as e:  # noqa: BLE001 — one tab, not the run
                    _log(f"  {camp} {week}: {type(e).__name__} — skipped")
                    continue
                owners = _owners(out)
                _log(f"  {camp} {week}: {len(owners)} owner(s)")
                for o in owners:
                    found.setdefault(o, {}).setdefault(camp, []).append(
                        week.isoformat())
    return found


def _recent_sundays(count: int) -> list:
    """The last `count` COMPLETED Mon–Sun weeks, newest first. The in-progress
    week is excluded on purpose: it holds partial reps, so a campaign worked
    only on Saturday looks unworked."""
    today = dt.date.today()
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    if sunday >= today:
        sunday -= dt.timedelta(days=7)
    return [sunday - dt.timedelta(days=7 * i) for i in range(count)]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Campaigns per ICD, from the D2D pager's per-campaign "
                    "tabs. Proposes additions; never removes.")
    ap.add_argument("--list-workbooks", action="store_true",
                    help="print every workbook this login can see and stop — "
                         "the campaigns are workbooks, not tabs")
    ap.add_argument("--list-sheets", nargs="?", const=PAGER_URL,
                    help="print one workbook view's worksheet names and stop "
                         "(defaults to the ATT pager)")
    ap.add_argument("--weeks", type=int, default=3,
                    help="how many completed weeks to union (default 3) — a "
                         "campaign worked in only one of them still counts")
    ap.add_argument("--only", action="append", default=[],
                    help="report just these owners (repeatable)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    from automations.shared.tableau_patchright import tableau_session
    if a.list_workbooks:
        with tableau_session(verbose=False, headless=not a.headed) as page:
            books = list_workbooks(page)
        _log(f"{len(books)} workbook(s) visible:")
        for b in books:
            print(f"    {b}")
        if not books:
            _log("none read — the workbooks page may render differently; try "
                 "--headed to see what loaded.")
        return 0

    if a.list_sheets:
        with tableau_session(verbose=False, headless=not a.headed) as page:
            names = list_sheets(page, a.list_sheets)
        _log(f"{len(names)} worksheet(s):")
        for n in names:
            mark = "*" if n.startswith(SHEET_PREFIX) else " "
            print(f"  {mark} {n}   -> campaign {campaign_of_sheet(n)!r}"
                  if mark == "*" else f"  {mark} {n}")
        _log("* = per-campaign ICD tab, the ones a full run reads")
        return 0

    with tableau_session(verbose=False, headless=not a.headed) as page:
        sheets = [s for s in list_sheets(page) if s.startswith(SHEET_PREFIX)]
    if not sheets:
        _log("no 'ICD Summary' worksheets found — run --list-sheets and check "
             "whether the tabs were renamed.")
        return 0
    weeks = _recent_sundays(max(1, a.weeks))
    _log(f"{len(sheets)} campaign tab(s) x {len(weeks)} week(s): "
         f"{[campaign_of_sheet(s) for s in sheets]}")

    found = pull(sheets, weeks, headless=not a.headed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"tableau-campaign-map-{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(found, indent=2, sort_keys=True),
                   encoding="utf-8")
    _log(f"findings -> {out}")

    from automations.focus_office_att.aliases import _norm_name
    from automations.rashad_metrics import knocks_pull as KP

    wanted = {_norm_name(o) for o in a.only} if a.only else None
    multi, news = [], []
    for owner, camps in sorted(found.items()):
        key = _norm_name(owner)
        if wanted and key not in wanted:
            continue
        if len(camps) > 1:
            multi.append((owner, camps))
            if key not in KP.MULTI_CAMPAIGN:
                news.append((owner, camps))

    _log(f"{len(multi)} owner(s) on more than one campaign tab")
    for owner, camps in multi:
        flag = "NEW" if _norm_name(owner) not in KP.MULTI_CAMPAIGN else "known"
        print(f"  [{flag}] {owner}: "
              + ", ".join(f"{c} ({len(w)}wk)" for c, w in sorted(camps.items())))
    if news:
        _log("NOT in knocks_pull.MULTI_CAMPAIGN — read these, then map the "
             "ones whose campaigns you can name an invD2DClientId for.")
    # Said explicitly, because a reader will otherwise take the list as the
    # whole answer: an owner absent from a tab may simply have had no reps on
    # that campaign in these weeks.
    _log("Absence is NOT evidence: a campaign with no reps in these weeks "
         "looks identical to one the owner does not run. Additions only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
