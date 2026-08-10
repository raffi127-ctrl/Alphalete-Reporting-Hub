"""Who is on a captainship, read from Tableau's own captain filter.

Every program tags its teams, and each workbook names the dropdown differently
(values read off the live views, 2026-08-10):

    fiber  ATT Tracker 2.1 - D2D        "Captain's Bonus Teams"
    b2b    ATT TRACKER - B2B            "B2B Captain's Teams"
    nds    NDS-SN (RES-ATT-OOF)         "NDS Captain Teams"

The team is a FILTER, never a column, so a roster is one crosstab export per
captain with that filter applied — which is why this is its own step and not
part of the 4am board fill: the board must not wait on it.

WHAT IS WIRED, AND WHAT IS NOT (measured, not assumed):

  nds   ✅ the URL filter narrows the export. `ProductSalesSummaryRep` +
        `?NDS Captain Teams=Colten's Team` returns exactly Colten's 12 owners,
        the same roster his board block carries.
  b2b   ❌ NOT wired yet, and here is exactly how far it got, so nobody repeats
        the search:
          · the captain-scoped sheets live on a SEPARATE workbook tab,
            `B2B 1-PAGER_Captain View`
            (`…/views/ATTTRACKER-B2B/B2B1-PAGER_CaptainView`), whose Crosstab
            dialog offers 'Sales By ICD (ATT) (V2)_Captain View',
            "ICD Summary - ATT (V2) (LW)_Captain's View", etc.
          · the filter STILL doesn't reach the export: with "B2B Captain's
            Teams" driven to Carlos's Team — by URL param AND by clicking the
            options (the checked set really does end up `["Carlos's Team"]`) —
            that sheet exports all 74 program owners, and the dropdown on screen
            snaps back to "(All)".
          · the account also opens this workbook on a default custom view
            (`ALLTEAMsALLREPS`), which is the likeliest thing re-imposing "all".
        THE CHEAP FIX is the pattern the fiber pulls already use: save a custom
        view per captain on that tab (filter applied, visible to others) and
        point PROGRAM_PULLS at those URLs — no filter driving at all.
        Meanwhile Carlos is covered by the Carlos Captainship Bonus report.
        (Also seen on the way: the b2b `ALL TEAMS` custom view now errors with
        "An error occurred while loading the custom view" —
        [[project_broken-custom-view-failure-mode]] — worth re-creating, it is
        the view the daily board pull uses.)
  fiber — deliberately not scanned: its six captainships are already detected
        every day by their own per-captain reports (Cancel Rate, Activation
        Rate, ABP & 6 days, Raf Metrics), so scanning here pays twice for the
        same answer.

WHAT A ROSTER MEANS HERE: the crosstab lists the team's owners WITH SALES this
week. Someone who sold nothing all week isn't in it — the same bar the campaign
side uses, and the right one: a name with no production anywhere isn't yet a row
anyone can fill.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from automations.org_sales_board import captainship as cap
from automations.org_sales_board import section_pull as sp

_V = "https://us-east-1.online.tableau.com/#/site/sci/views/"

_TEAM_OPTION = re.compile(r"^.+['’]s\s+Team$", re.I)
ALL_OPTION = "(All)"


def select_team_hook(team: str, logfn=print):
    """pre_export hook: drive a captain-team quick filter to exactly `team`.

    For the workbooks whose filter can't be set from the URL (b2b's "B2B
    Captain's Teams" ignores the URL param, while nds' does honour it).

    THE (All) TRAP: while a categorical filter sits on "(All)", EVERY option
    renders as checked. Clicking the target first therefore UNchecks it, and the
    "uncheck the others" pass that follows leaves the filter back where it
    started — the export comes out with the whole program in it and nothing
    anywhere says the filter didn't take. So: clear via "(All)" FIRST, then
    check the one team, then verify the box no longer reads "(All)".

    The box is found by its OPTIONS ("<Name>'s Team"), never by position —
    b2b's is index 1 and nds' is index 5, and a dashboard reorder would
    otherwise silently filter on the wrong field."""
    def _items(fr):
        return fr.locator('div.FIItem[role="checkbox"]')

    def _texts(fr):
        it = _items(fr)
        return [(it.nth(j).inner_text() or "").strip() for j in range(it.count())]

    def _checked(fr):
        c = fr.locator('div.FIItem[role="checkbox"][aria-checked="true"]')
        return [(c.nth(j).inner_text() or "").strip() for j in range(c.count())]

    def _click(fr, value, page):
        item = _items(fr).filter(
            has_text=re.compile(rf"^{re.escape(value)}$")).first
        glyph = item.locator(".FICheckRadio").first
        glyph.scroll_into_view_if_needed()
        glyph.click(timeout=10000)
        page.wait_for_timeout(900)

    def pre_export(page, viz):
        boxes = viz.locator('span.tabComboBox[role="combobox"]')
        for _ in range(20):                    # let the filter cards hydrate
            if boxes.count():
                break
            page.wait_for_timeout(1000)
        for i in range(boxes.count()):
            box = boxes.nth(i)
            try:
                if (box.inner_text() or "").strip() == team:
                    return                     # already on this team
                box.click(timeout=10000)
                page.wait_for_timeout(1200)
                opts = _texts(viz)
            except Exception:                  # noqa: BLE001 — try the next box
                continue
            if not any(_TEAM_OPTION.match(o) for o in opts):
                try:                           # not the captain filter — close
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:              # noqa: BLE001
                    pass
                continue
            if team not in opts:
                logfn(f"    ⚠ {team!r} is not one of the "
                      f"{len([o for o in opts if _TEAM_OPTION.match(o)])} teams "
                      f"offered — renamed in Tableau?")
                page.keyboard.press("Escape")
                raise RuntimeError(f"team {team!r} not in the filter")
            if ALL_OPTION in opts and ALL_OPTION in _checked(viz):
                _click(viz, ALL_OPTION, page)  # clear everything first
            for _ in range(3):                 # then leave ONLY the target on
                now = _checked(viz)
                if now == [team]:
                    break
                for other in [o for o in now if o != team]:
                    try:
                        _click(viz, other, page)
                    except Exception:          # noqa: BLE001
                        pass
                if team not in _checked(viz):
                    _click(viz, team, page)
            final = _checked(viz)
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)
            except Exception:                  # noqa: BLE001
                pass
            if final != [team]:
                # Never export a filter that didn't take: the result would be
                # the whole program, read downstream as "everyone is new".
                raise RuntimeError(
                    f"the captain filter didn't take for {team!r} "
                    f"(checked={final})")
            # The CHECKED set is the authority, not the combobox caption: it
            # still reads '(All)' for a beat after the menu closes, and asserting
            # on it turned a filter that HAD taken into a failed pull.
            logfn(f"    filter set to {team!r}")
            return
        raise RuntimeError(f"no captain-team filter on this view for {team!r}")

    return pre_export

# Program -> how to pull ONE captain's roster. `field` is the URL filter name
# (Tableau matches the caption shown on the dropdown). A program that isn't here
# can't be scanned — captains_for() simply won't return its captains.
PROGRAM_PULLS: Dict[str, dict] = {
    "nds": {
        "view": _V + "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep",
        "sheet": "Sales By ICD (Weekly View)",
        "field": "NDS Captain Teams",
    },
    # "b2b": see the module docstring — the filter doesn't reach these sheets.
    # "fiber": covered by the per-captain reports; add here if that ever changes.
}

# Board captainship -> (program, the exact value in that program's team filter).
# Kept for EVERY captainship, including the programs that aren't wired yet, so
# the mapping is written down once and wiring a program is a one-line change.
TEAMS: Dict[str, tuple] = {
    "Raf":    ("fiber", "Raf's Team"),
    "Wayne":  ("fiber", "Wayne's Team"),
    "Starr":  ("fiber", "Starr's Team"),
    "Chan":   ("fiber", "Chan's Team"),
    "Tony":   ("fiber", "Tony's Team"),
    "Sahil":  ("fiber", "Sahil's Team"),
    "Carlos": ("b2b", "Carlos's Team"),
    "Eveliz": ("b2b", "Eveliz's Team"),
    "Luis":   ("b2b", "Luis's Team"),
    "Khalil": ("nds", "Khalil's Team"),
    "Colten": ("nds", "Colten's Team"),
    "Jairo":  ("nds", "Jairo's Team"),
}

DEFAULT_PROGRAMS = tuple(PROGRAM_PULLS)


def captains_for(programs=None) -> List[str]:
    """Captains we can actually roster. A program with no PROGRAM_PULLS entry
    is skipped rather than pulled unfiltered — an unfiltered export would read
    as "the whole program is new" and ask for 70 checkmarks."""
    progs = {p for p in (programs or DEFAULT_PROGRAMS) if p in PROGRAM_PULLS}
    return [c for c, (p, _v) in TEAMS.items() if p in progs]


def unsupported(programs=None) -> Dict[str, str]:
    """{captain: program} for the ones asked for but not wired."""
    progs = set(programs or DEFAULT_PROGRAMS)
    return {c: p for c, (p, _v) in TEAMS.items()
            if p in progs and p not in PROGRAM_PULLS}


def _display(raw: str) -> str:
    """Tableau's spelling, cleaned for a human: drop the '[office, inc.]' tail
    and de-shout an ALL-CAPS name ('COLTEN WRIGHT' -> 'Colten Wright') so the
    approval line and the board row read like every other name."""
    s = re.split(r"[|\[]", raw or "", maxsplit=1)[0].strip()
    if s and s == s.upper():
        s = " ".join(w.capitalize() for w in s.split())
    return s


def _raw_owners(spec, path: Path) -> Dict[str, str]:
    """{normalized owner -> display spelling}. The normalized key is what the
    board matches on; the display spelling is what a person reads."""
    from automations.org_sales_board import sara_pull
    from automations.alphalete_org_report import tableau_http
    rows = sara_pull._read_rows(path)
    if not rows:
        return {}
    hdr_i = next((i for i, r in enumerate(rows[:8])
                  if any((c or "").strip() == spec.owner_col for c in r)), None)
    if hdr_i is None:
        return {}
    header = [(c or "").strip() for c in rows[hdr_i]]
    oi = tableau_http.col_idx(header, spec.owner_col)
    if oi is None:
        return {}
    skip = {s.lower() for s in (spec.skip_owners or ())} | {"", "total",
                                                            "grand total"}
    out: Dict[str, str] = {}
    for r in rows[hdr_i + 1:]:
        raw = (r[oi] if oi < len(r) else "").strip()
        if not raw or raw.split("\r")[0].strip().lower() in skip:
            continue
        key = sp._norm_section_owner(raw, spec.strip_office)
        if key and key not in skip:
            out.setdefault(key, _display(raw))
    return out


def roster_for(captain: str, page, *, today: Optional[dt.date] = None,
               out_dir: Path = Path("output"), logfn=print) -> Dict[str, str]:
    """One captain's roster: {normalized name -> display name}."""
    today = today or dt.date.today()
    prog, team = TEAMS[captain]
    pull = PROGRAM_PULLS.get(prog)
    if not pull:
        raise ValueError(f"{prog} has no verified captain-filter pull "
                         f"(see the module docstring)")
    t = cap.TYPES[prog]
    spec = cap._spec(f"ROSTER_{captain}", pull["view"], t["parse"], t["metric"])
    url = f"{pull['view']}?{quote(pull['field'])}={quote(team)}"
    out = out_dir / f"new_owners_roster_{prog}_{captain.lower()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import download_crosstab_patchright
    logfn(f"  pulling {captain}'s roster ({prog}, {pull['field']}={team!r})…")
    download_crosstab_patchright(url, pull["sheet"], out, page=page,
                                 verbose=False)
    owners = _raw_owners(spec, out)
    logfn(f"    {len(owners)} owner(s) with sales this week under {captain}")
    return owners


def scan(page, captains: Optional[List[str]] = None, *,
         today: Optional[dt.date] = None, logfn=print) -> Dict[str, dict]:
    """Roster every requested captainship. One failure never stops the rest — a
    captain whose pull failed is reported with its error instead of being read
    as 'nobody new'."""
    today = today or dt.date.today()
    out: Dict[str, dict] = {}
    for captain in (captains or captains_for()):
        if captain not in TEAMS:
            out[captain] = {"error": "not a captainship in TEAMS"}
            continue
        try:
            out[captain] = {"owners": roster_for(captain, page, today=today,
                                                 logfn=logfn)}
        except Exception as e:  # noqa: BLE001 — one captain must not stop the scan
            logfn(f"    ⚠ {captain}: roster pull FAILED "
                  f"({type(e).__name__}: {str(e)[:100]})")
            out[captain] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return out
