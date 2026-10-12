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
  b2b   ✅ TWO pulls since 2026-10-12, because no B2B sheet carries both the
        team and this week's sales any more:
          · WHO IS ON THE TEAM: `ATTTRACKER-B2B/CaptainsTeam` + sheet
            `CB-Owner Metrics` + `?B2B Captain's Teams (SFDC)=<X>'s Team`
            (team | owner | two rate %s — no sales count).
          · WHO SOLD: the board's own B2B sales pull (section_pull.B2B_SPEC,
            'Sales By ICD (ATT) (V2)', week-pinned) — once per scan, to its
            own file. A team member is kept only if they sold that week.
        History: saved views on `B2B1-PAGER_CaptainView` (died 2026-10-10),
        then `CB-Owner Sales` on CaptainsTeam (gone 2026-10-12; the view now
        offers CB-Owner Metrics, CB-Owners Non PMT, Captain Team Check (2)/(4)).
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
    # b2b: one BASE view + the URL filter, same as nds, since 2026-10-10. The
    # old route (one saved custom view per captain on B2B1-PAGER_CaptainView,
    # Eve 2026-08-10) died with that view — "That page could not be accessed".
    # CaptainsTeam is back with its pre-08-13 worksheets, and on it the filter
    # DOES reach the export: CB-Owner Sales + Carlos's Team -> his 11 owners,
    # team column included (probe_carlos_bonus_sheets on Lucy 3, 2026-10-10).
    # That sheet calls the column 'Owner Name', not the board's 'ICD Owner Name'.
    # 2026-10-12: CB-Owner Sales vanished from CaptainsTeam overnight (same
    # churn as 08-13). CB-Owner Metrics is the team list, with no sales in it,
    # so `sold_this_week` intersects it with the board's B2B sales pull.
    "b2b": {
        "view": _V + "ATTTRACKER-B2B/CaptainsTeam",
        "sheet": "CB-Owner Metrics",
        "field": "B2B Captain's Teams (SFDC)",
        # Its owner column has NO header: the export is
        # ['', '', 'Churn Rate (0-30 days)', 'Activation Rate (31-60 days)'] then
        # ["Carlos's Team", 'Carlos Hidalgo', '8.1%', '72.6%'] — so the owner
        # is read as the cell beside the team cell (_team_list_owners).
        "team_list": True,
        "sold_this_week": True,
    },
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
    # Atef, 2026-10-10 (Eve). "Atef's Team" has been in the SFDC filter since
    # 2026-09-03; the saved-view route needed a view per captain and nobody saved
    # his, so he was never scanned.
    "Atef":   ("b2b", "Atef's Team"),
    "Khalil": ("nds", "Khalil's Team"),
    "Colten": ("nds", "Colten's Team"),
    "Jairo":  ("nds", "Jairo's Team"),
}

DEFAULT_PROGRAMS = tuple(PROGRAM_PULLS)


def _pullable(captain: str) -> bool:
    """Can this captain's roster actually be pulled? A per-captain-view program
    also needs THAT captain's view saved — a missing one must never fall back to
    an unfiltered export, which would read as "the whole program is new" and ask
    for 70 checkmarks."""
    prog, _team = TEAMS[captain]
    pull = PROGRAM_PULLS.get(prog)
    if not pull:
        return False
    return captain in pull["views"] if "views" in pull else True


def captains_for(programs=None) -> List[str]:
    """Captains we can actually roster."""
    progs = {p for p in (programs or DEFAULT_PROGRAMS) if p in PROGRAM_PULLS}
    return [c for c, (p, _v) in TEAMS.items() if p in progs and _pullable(c)]


def unsupported(programs=None) -> Dict[str, str]:
    """{captain: program} for the ones asked for but not wired."""
    progs = set(programs or DEFAULT_PROGRAMS)
    return {c: p for c, (p, _v) in TEAMS.items()
            if p in progs and not _pullable(c)}


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
    header = [(c or "").strip() for c in rows[hdr_i]] if hdr_i is not None else []
    oi = tableau_http.col_idx(header, spec.owner_col) if header else None
    if oi is None:
        # A renamed column must FAIL, never read as "nobody on this team" —
        # an empty roster is a silent "0 new reps". [[feedback_empty_means_proven_zero]]
        raise RuntimeError(
            f"no {spec.owner_col!r} column in {path.name} — first rows: "
            f"{[r[:5] for r in rows[:3]]}")
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


def _team_list_owners(path: Path, team: str) -> Dict[str, str]:
    """{normalized owner -> display} from a headerless team list: each data row
    is `<team> | <owner> | …`. Every row must carry the team we asked for — a
    row from another team means the URL filter didn't take, and reading on
    would propose the whole program."""
    from automations.org_sales_board import sara_pull
    rows = sara_pull._read_rows(path)
    out: Dict[str, str] = {}
    other = set()
    for r in rows:
        cells = [(c or "").strip() for c in r]
        if len(cells) < 2 or not _TEAM_OPTION.match(cells[0]):
            continue
        if cells[0].replace("’", "'").lower() != team.replace("’", "'").lower():
            other.add(cells[0])
            continue
        raw = cells[1]
        if not raw or raw.lower() in ("total", "grand total"):
            continue
        key = sp._norm_section_owner(raw, False)
        if key:
            out.setdefault(key, _display(raw))
    if other:
        raise RuntimeError(f"the team filter didn't take — export also has "
                           f"{sorted(other)}")
    if not out:
        raise RuntimeError(f"no '<team> | <owner>' rows for {team!r} in "
                           f"{path.name} — first rows: "
                           f"{[r[:4] for r in rows[:3]]}")
    return out


_SELLERS: Dict[tuple, set] = {}


def _b2b_sellers(page, today: dt.date, out_dir: Path, logfn=print) -> set:
    """Normalized owners with B2B sales in the board's reporting week — ONE
    pull per scan, shared by every b2b captain. Same spec, week pin and parser
    as the board's B2B section, written to this report's own file."""
    key = (today, str(out_dir))
    if key in _SELLERS:
        return _SELLERS[key]
    import dataclasses
    spec = dataclasses.replace(sp.B2B_SPEC, out_name="new_owners_b2b_sales.csv")
    logfn("  pulling who sold B2B this week (board's B2B sales sheet)…")
    path = sp.pull_section_byday(spec, out_dir, page, logfn=lambda *_: None,
                                 today=today)
    per = sp.parse_byday(spec, path, today)
    sellers = {o for o, m in per.items()
               if sum(int(v or 0) for v in (m.get(spec.metric) or {}).values()) > 0}
    if not sellers:
        raise RuntimeError("the B2B sales pull came back with nobody selling — "
                           "refusing to call every b2b captain 'nobody new'")
    logfn(f"    {len(sellers)} B2B owner(s) with sales this week")
    _SELLERS[key] = sellers
    return sellers


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
    if "views" in pull:                      # a saved custom view per captain
        url = pull["views"].get(captain)
        if not url:
            raise ValueError(f"no saved roster view for {captain} — save one on "
                             f"the captain-view tab and add it to PROGRAM_PULLS")
        how = "saved view"
    else:                                    # one view + a URL filter
        url = f"{pull['view']}?{quote(pull['field'])}={quote(team)}"
        how = f"{pull['field']}={team!r}"
    parse = dict(t["parse"], **({"owner_col": pull["owner_col"]}
                                if "owner_col" in pull else {}))
    spec = cap._spec(f"ROSTER_{captain}", url, parse, t["metric"])
    out = out_dir / f"new_owners_roster_{prog}_{captain.lower()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import download_crosstab_patchright
    logfn(f"  pulling {captain}'s roster ({prog}, {how})…")
    download_crosstab_patchright(url, pull["sheet"], out, page=page,
                                 verbose=False)
    owners = (_team_list_owners(out, team) if pull.get("team_list")
              else _raw_owners(spec, out))
    if pull.get("sold_this_week"):
        if not owners:
            raise RuntimeError(f"{captain}'s team list came back empty")
        sold = _b2b_sellers(page, today, out_dir, logfn)
        on_team = len(owners)
        owners = {k: v for k, v in owners.items() if k in sold}
        logfn(f"    {on_team} on {captain}'s team, {len(owners)} with sales "
              f"this week")
        return owners
    logfn(f"    {len(owners)} owner(s) with sales this week under {captain}")
    return owners


def scan(page, captains: Optional[List[str]] = None, *,
         today: Optional[dt.date] = None, logfn=print) -> Dict[str, dict]:
    """Roster every requested captainship. One failure never stops the rest — a
    captain whose pull failed is reported with its error instead of being read
    as 'nobody new'."""
    today = today or dt.date.today()
    out: Dict[str, dict] = {}
    # NDS first. A B2B pull that dies on its dialog (10/10, 10/12) can leave the
    # Tableau session half signed-out, and the NDS pull behind it then hangs
    # until the 20m kill — so one broken B2B sheet cost every roster.
    order = sorted(captains or captains_for(),
                   key=lambda c: TEAMS.get(c, ("",))[0] != "nds")
    # The B2B sales list goes FIRST, on the fresh page. Pulled after a
    # CaptainsTeam team-list download in the same session, the browser closed
    # on the next goto/save_as every time (laptop, 2026-10-12, 3 of 3); pulled
    # first it came back clean (74 sellers). A failure here is left for
    # roster_for to re-raise per b2b captain.
    if any(PROGRAM_PULLS.get(TEAMS.get(c, ("",))[0], {}).get("sold_this_week")
           for c in order):
        try:
            _b2b_sellers(page, today, Path("output"), logfn)
        except Exception as e:  # noqa: BLE001
            logfn(f"    ⚠ B2B sales pull FAILED ({type(e).__name__}: "
                  f"{str(e)[:100]})")
    for captain in order:
        if captain not in TEAMS:
            out[captain] = {"error": "not a captainship in TEAMS"}
            continue
        try:
            out[captain] = {"owners": roster_for(captain, page, today=today,
                                                 logfn=logfn)}
        except Exception as e:  # noqa: BLE001 — one captain must not stop the scan
            # Full text: a "Couldn't find the sheet" error carries the dialog's
            # sheet list, and that list is the whole fix when Tableau renames.
            logfn(f"    ⚠ {captain}: roster pull FAILED "
                  f"({type(e).__name__}: {str(e)[:600]})")
            out[captain] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return out
