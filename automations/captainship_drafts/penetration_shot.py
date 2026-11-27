"""Penetration Report section of the fiber Captainship drafts (Raf's Loom 11/26).

Raf: "add a 10th item that says Penetration Report, with a screenshot of this"
— Tableau ATT Tracker 2.1 - D2D → Fiber Lead Performance → Penetration View
"Market Expectations" (one row per owner: active reps, target weekly sales,
office lead penetration, weekly sales heat-map) — for the captain's owners and
WITHOUT the captain's own office (captains get more leads: road trips, big
cities).

HOW IT IS FILTERED — proven live in Chrome 11/26 after six blank samples:
  * 'Account Captain Email' (SmartCircle 11/26) only reaches the by-zip view;
    on Market Expectations its dropdown is EMPTY (Eve confirmed by hand). So
    the captain's owners come from that column in the by-zip CROSSTAB
    (captainship_penetration.core), captain left out.
  * The view is opened with ONE URL filter, `Owner Name=<owners>` — that binds.
  * 'Penetration View' must NOT go in the URL: `Penetration View=Market
    Expectations` blanks the whole board. It is chosen in its dropdown instead,
    like a person would.
  * Before shooting, the board text is checked: the Market Expectations table
    ('Sale Date Weekending') is there, at least one owner is in it, and the
    captain is NOT. Anything else raises → the section's pending note, never a
    wrong picture.

    python -m automations.captainship_drafts.penetration_shot rafael [out_dir]
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List
from urllib.parse import quote

BASE_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "ATTTRACKER2_1-D2D/FiberLeadPerformance")
P_OWNER = "Owner Name"
VIEW_LABEL = "Market Expectations"
TABLE_MARK = "Sale Date Weekending"      # header only the ME table has
HYDRATE_MS = 20_000


def view_url(owners: List[str]) -> str:
    return (f"{BASE_VIEW}?{quote(P_OWNER)}="
            f"{','.join(quote(o) for o in owners)}&:iid=1")


def _crosstab_text(today: dt.date) -> str:
    """Today's by-zip crosstab: the copy captainship_penetration saved this
    morning on this machine if there is one, else a fresh download."""
    from automations.captainship_penetration import core, run as prun
    kept = Path("output") / "captainship_penetration" / f"crosstab_{today}.csv"
    if kept.exists():
        text = kept.read_text(encoding="utf-8")
        if len(core.parse_owners(text)) >= core.MIN_OWNERS:
            return text
    return prun._download()


def team(captain_key: str, today: dt.date) -> List[str]:
    """The captain's owners (Tableau spelling), captain left out."""
    from automations.captainship_penetration import core
    owners = core.parse_owners(_crosstab_text(today))
    if len(owners) < core.MIN_OWNERS:
        raise RuntimeError(f"crosstab has {len(owners)} owners — a Tableau "
                           f"filter is stuck")
    names = sorted(core.captainship(captain_key, owners)["owners"])
    if not names:
        raise RuntimeError(f"{captain_key}: no owners besides the captain")
    return names


def _pick_market_expectations(page, logfn=print) -> None:
    """Open the Penetration View dropdown and choose Market Expectations."""
    from automations.captainship_drafts.tableau_shot import _VIZ_IFRAME
    fr = page.frame_locator(_VIZ_IFRAME)
    box = None
    for sel in (".tabComboBoxNameContainer", "[role=combobox]",
                ".tabComboBox"):
        cand = fr.locator(sel).filter(has_text="Penetration by Zip")
        if cand.count():
            box = cand.first
            break
    if box is None:
        raise RuntimeError("could not find the 'Penetration View' dropdown "
                           "(showing 'Office Penetration by Zip')")
    box.click()
    page.wait_for_timeout(1_500)
    opt = fr.get_by_text(VIEW_LABEL, exact=True)
    # the last match is the menu entry (the first can be the view's caption)
    for i in reversed(range(opt.count())):
        try:
            opt.nth(i).click(timeout=5_000)
            break
        except Exception:  # noqa: BLE001 — try the next match
            continue
    else:
        raise RuntimeError(f"'{VIEW_LABEL}' not offered in the dropdown")
    page.wait_for_timeout(HYDRATE_MS)


def captain_penetration_shot(captain_key: str, today: dt.date, out_dir: Path,
                             *, logfn=print, verbose: bool = False) -> Path:
    """PNG of Market Expectations for this captain's owners. Raises on
    anything off (run.py turns it into the section's pending note)."""
    from automations.captainship_penetration.core import CAPTAIN_OWNER
    from automations.captainship_drafts import tableau_shot as ts
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture

    owners = team(captain_key, today)
    captain = CAPTAIN_OWNER[captain_key]
    logfn(f"   · penetration {captain_key}: {len(owners)} owners "
          f"(minus {captain}): {', '.join(owners)}")
    out = Path(out_dir) / f"captainship_{captain_key}_penetration.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tableau_session(headless=True, verbose=verbose) as page:
        page.goto(view_url(owners), wait_until="domcontentloaded")
        page.wait_for_timeout(HYDRATE_MS)
        board = page.frame_locator(ts._VIZ_IFRAME).locator(ts._DASHBOARD).first
        board.wait_for(state="visible", timeout=ts._DASHBOARD_TIMEOUT_MS)
        _pick_market_expectations(page, logfn=logfn)
        text = board.inner_text()
        if TABLE_MARK not in text:
            raise RuntimeError("the Market Expectations table did not render "
                               "(no 'Sale Date Weekending' on the board)")
        shown = [o for o in owners if o in text]
        if not shown:
            raise RuntimeError("none of the captain's owners is on the board — "
                               "the Owner Name filter did not bind")
        if captain in text:
            raise RuntimeError(f"{captain} is on the board — the captain's own "
                               f"office must be left out")
        logfn(f"   · penetration {captain_key}: {len(shown)}/{len(owners)} "
              f"owners on the board")
        board.screenshot(path=str(out))
    ts._trim_right(out)
    capture._trim_bottom(out, verbose, spec_id=f"penetration_{captain_key}",
                         peel_footer=False)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    key = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    p = captain_penetration_shot(key, dt.date.today(), out, verbose=True)
    print(f"✓ {key}: {p}")
