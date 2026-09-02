"""Tableau pull for the Captainship Cancel Rate report.

SOURCE (one crosstab, one download, all 5 captains):
  workbook   ATT TRACKER 2_1 - D2D
  view       Metrics
             https://us-east-1.online.tableau.com/#/site/sci/views/
             ATTTRACKER2_1-D2D/Metrics
  worksheet  "Metrics Call Last week data (Internet)"
  filter     none applied by us — the view's own default state is what the
             link shows. The crosstab already comes fully EXPANDED (the '+'
             on the dashboard), i.e. one row per
             Captain's Bonus Teams -> ICD Owner Name (rep) -> Rep Name.

ROWS WE READ (the tabs list ICD OWNERS, not individual reps):
  "Captain's Bonus Teams"       -> "Wayne's Team" / "Starr's Team" / ...
  "ICD Owner Name (rep)"        -> the owner ('Total' = the whole team)
  "Rep Name"                    -> we keep ONLY 'Total' (the owner roll-up)

TWO ROW SHAPES — both fine, "Rep Name" is OPTIONAL (2026-08-08):
  This worksheet exports at whatever depth the viz is left at, and the
  Download -> Crosstab export DROPS the "Rep Name" column entirely when the
  rep hierarchy is COLLAPSED (the '+' above the ICD name is not expanded).
  The dashboard still SHOWS Rep Name when collapsed, so eyeballing the viz
  proves nothing — only the crosstab does. Same trap that broke New Internet
  ABP on 2026-08-07 (it was fixed by pinning the rep-expanded ALLEXP view).

    EXPANDED  -> "Rep Name" present; one row per rep, plus a 'Total' row per
                 owner. We keep only rep == 'Total' (the owner roll-up).
    COLLAPSED -> "Rep Name" absent; every row is ALREADY an owner roll-up.

  A missing "Rep Name" is therefore a shape difference, not missing data — we
  handle it instead of failing. The DATA columns below stay hard-required: if
  one of those disappears we still fail loudly rather than half-fill a tab.

  WE WANT THE COLLAPSED (default-view) NUMBERS. Verified 2026-08-08 by pulling
  both shapes the same minute: the 0-30 cancel rate and its cancels/sales
  counts are byte-identical either way, but the 30-60 activation rate is NOT.
  Expanding to rep level restricts the rows to reps with current-week data,
  and the 30-60 metric is a 30-60-days-ago COHORT — reps who sold then but
  not this week drop out, so the owner subtotal is computed over a partial
  cohort. Wayne's Team owners drifted 0.1-1.0 pt; Mason Davis (1 rep row this
  week) read 100.0% expanded vs the true 74.6% collapsed. The default view's
  own owner-level roll-up is the honest number, so this report stays pointed
  at the plain view URL below — do NOT "fix" a future missing 'Rep Name' by
  switching to a rep-expanded custom view (that's the right fix for New
  Internet ABP, which genuinely needs per-rep rows; it is the wrong one here).

COLUMNS WE READ:
  "0-30 day New Internet cancel rate"        -> the 0-30 section, verbatim.
  "30-60 day New Internet activation rate"   -> the 30-60 section, INVERTED:
        30-60 cancel rate = 100% - 30-60 activation rate
     because the workbook carries no 30-60 cancel-rate column. A blank
     activation rate stays BLANK (not 100%) — no data is not a 100% cancel.

  NOTE: there is also a "0-30 day new internet churn rate" column right
  next to the cancel rate. It is a DIFFERENT metric and is NOT what this
  report fills (churn is automations.captainship_churn). Match on the exact
  header text.
"""
from __future__ import annotations

import csv
import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.recruiting_report import opt_phase
from automations.focus_office_att import aliases as _aliases
from automations.shared import captainship_pins as _pins

# Base Metrics dashboard with 'Metrics View' PINNED to Internet (2026-08-20 —
# see opt_phase.pin_internet_metrics). Stays the BASE, collapsed view for the
# 30-60 cohort reason spelled out in the module docstring above.
METRICS_URL = opt_phase.pin_internet_metrics(
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics")
METRICS_SHEET = "Metrics Call Last week data (Internet)"

COL_TEAM = "Captain's Bonus Teams"
COL_OWNER = "ICD Owner Name (rep)"
COL_REP = "Rep Name"
COL_CANCEL_030 = "0-30 day New Internet cancel rate"
COL_ACT_3060 = "30-60 day New Internet activation rate"
# OPTIONAL count columns behind the 0-30 rate. Present in the view today; the
# parse degrades to rates-only if they ever disappear, because the only thing
# that needs them is the adopted-rep average recompute in `for_team`.
COL_CANCELS_030 = "0-30 day new internet cancels"
COL_SALES_030 = "0-30 day new internet sales"

# Extra header spellings we'll accept for the two DIMENSION columns, so a
# cosmetic rename in Tableau doesn't hard-fail the whole run. Deliberately
# NOT extended to the two measure columns: '0-30 day new internet churn rate'
# sits right next to the cancel rate and is a different metric, so those two
# match on their exact header text only.
COL_ALIASES: dict[str, tuple[str, ...]] = {
    COL_TEAM: ("Captains Bonus Teams", "Captain's Bonus Team",
               "Captain's Bonus Teams (group)"),
    COL_OWNER: ("ICD Owner Name", "ICD Owner Name (rep) (group)",
                "ICD Owner"),
    COL_REP: ("Rep", "Rep Name (group)"),
}

# Canonical period keys — must match fill.SECTION_LABELS.
P_030 = "0-30"
P_3060 = "30-60"


def _norm(s: str) -> str:
    """Fold the cosmetic differences only: BOM, curly quotes, inner runs of
    whitespace, case. NOT a fuzzy match — two different metrics never collide."""
    s = (s or "").lstrip("﻿").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s.strip()).upper()


def _read_crosstab(path: Path) -> list[list[str]]:
    """Tableau crosstab CSVs are UTF-16, tab-delimited."""
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.reader(f, delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            continue
    return []


def _col_index(header: list[str], wanted: str) -> Optional[int]:
    """Index of `wanted` in the header. The exact name wins; only if it isn't
    there do we fall back to that column's known aliases (COL_ALIASES), so a
    renamed column can never steal a slot from the column it's named after."""
    norm = [_norm(h) for h in header]
    for candidate in (wanted, *COL_ALIASES.get(wanted, ())):
        c = _norm(candidate)
        for i, h in enumerate(norm):
            if h == c:
                return i
    return None


def _pct_to_float(raw: str) -> Optional[float]:
    """'84.3%' -> 84.3 ; '' / '-' / junk -> None."""
    s = (raw or "").strip().replace(",", "")
    if not s or s in {"-", "%"}:
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*%?", s)
    return float(m.group(1)) if m else None


def _invert(raw: str) -> str:
    """30-60 cancel rate = 100% - 30-60 activation rate. Blank stays blank."""
    v = _pct_to_float(raw)
    if v is None:
        return ""
    return f"{round(100.0 - v, 1)}%"


def _display_name(tableau_name: str, alias_raw: dict) -> str:
    """Tableau shouts owner names ('ALEX TURZYNSKI'). Resolve through the ICD
    Aliases sheet first — a hit already carries the exact Sheet-tab spelling
    ('JC Gerard Pascual' -> 'JC Pascual'), so don't re-case it. A miss gets
    title-cased, which is the spelling these tabs use."""
    canonical = _aliases.alias_to_canonical(tableau_name, alias_raw)
    if canonical != tableau_name:
        return canonical          # alias/canonical hit — already spelled right
    return tableau_name.title()


def fetch(out_path: Optional[Path] = None, *, page=None,
          verbose: bool = False) -> Path:
    """Download the Metrics crosstab. `page` = an open tableau_session page."""
    out = out_path or (Path(tempfile.gettempdir()) / "captainship_cancel_rate.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    opt_phase.download_crosstab(METRICS_URL, METRICS_SHEET, out,
                                verbose=verbose, page=page)
    return out


def parse(path: Path, alias_raw: Optional[dict] = None) -> dict:
    """Parse the crosstab into:

        {"teams": {"Wayne's Team": {"avg":  {"0-30": "7.7%", "30-60": "15.7%"},
                                    "reps": {"Wayne Rude": {"0-30": ..., ...}}}},
         "missing_cols": [...],
         "teams_seen": [...],
         "shape": "rep-expanded" | "owner-collapsed"}

    Only owner-level rows are kept — the tabs list ICD owners. When the export
    carries 'Rep Name' that means keeping rep == 'Total'; when it doesn't, the
    export is already owner-level and every row qualifies (module docstring). Values are kept as '12.3%' STRINGS so USER_ENTERED writes land as
    real percents in the Sheet (and the tabs' conditional formatting fires).
    """
    if alias_raw is None:
        try:
            alias_raw = _aliases.load_aliases()
        except Exception:
            alias_raw = {}

    rows = _read_crosstab(path)
    if not rows:
        raise RuntimeError(f"Empty / unreadable crosstab: {path}")

    header = rows[0]
    required = {"team": COL_TEAM, "owner": COL_OWNER,
                P_030: COL_CANCEL_030, "act3060": COL_ACT_3060}
    idx = {k: _col_index(header, name) for k, name in required.items()}

    missing = [required[k] for k, v in idx.items() if v is None]
    if missing:
        # A renamed/removed source column must be LOUD — silently filling half
        # the tab is the failure mode we never want (the DD 1-row scrape).
        raise RuntimeError(
            "The Metrics crosstab is missing these column(s): "
            + ", ".join(repr(m) for m in missing)
            + ". The Tableau view changed — update pull.py's column constants."
            + " Headers present: " + ", ".join(repr(h) for h in header))

    # 'Rep Name' is OPTIONAL — see the module docstring. Present = the export
    # is rep-expanded and we keep only the owner roll-ups; absent = the export
    # is already collapsed to owner level, so every row IS a roll-up.
    rep_idx = _col_index(header, COL_REP)
    shape = "rep-expanded" if rep_idx is not None else "owner-collapsed"
    cnt_i = _col_index(header, COL_CANCELS_030)
    sal_i = _col_index(header, COL_SALES_030)

    last_col = max(list(idx.values()) + ([rep_idx] if rep_idx is not None else []))
    teams: dict = {}
    for r in rows[1:]:
        if len(r) <= last_col:
            continue
        team = (r[idx["team"]] or "").strip()
        owner = (r[idx["owner"]] or "").strip()
        rep = (r[rep_idx] or "").strip() if rep_idx is not None else "Total"
        if not team or rep != "Total":
            continue          # per-rep detail rows — the tabs are owner-level
        # An ICD whose captain changed in real life before SmartCircle re-filed
        # the team value is read onto the captain they actually report to. No-op
        # for every other row; the team's own 'Total' row can't match (it is
        # keyed on the owner name). See captainship_pins.ADOPTED.
        team = _pins.route_team(team, owner)
        slot = {
            P_030: (r[idx[P_030]] or "").strip(),
            P_3060: _invert(r[idx["act3060"]]),
        }
        # Counts behind the 0-30 rate, when the view exports them. Only the
        # adopted-rep recompute reads these; nothing else changes.
        if cnt_i is not None and sal_i is not None and len(r) > max(cnt_i, sal_i):
            n, d = _pct_to_float(r[cnt_i]), _pct_to_float(r[sal_i])
            if n is not None and d is not None:
                slot["counts_030"] = (n, d)
        bucket = teams.setdefault(team, {"avg": {}, "reps": {}})
        if owner == "Total":
            bucket["avg"] = slot
        elif owner:
            bucket["reps"][_display_name(owner, alias_raw)] = slot

    return {"teams": teams, "missing_cols": [], "teams_seen": sorted(teams),
            "shape": shape}


def _recomputed_030_avg(reps: dict) -> Optional[str]:
    """0-30 cancel rate for a slice, from its own cancels/sales counts.

    Returns None unless EVERY rep in the slice carries counts — a partial sum
    would be a rate over the wrong denominator, which is worse than Tableau's
    slightly-off total. Verified against the view 2026-09-01: Chan's eight
    owners sum to 229/2,264 = 10.1%, the exact text of Tableau's own Total row.
    """
    if not reps:
        return None
    pairs = [d.get("counts_030") for d in reps.values()]
    if not all(pairs):
        return None
    num = sum(n for n, _ in pairs)
    denom = sum(d for _, d in pairs)
    if not denom:
        return None
    return f"{round(100.0 * num / denom, 1)}%"


def for_team(parsed: dict, team: str) -> dict:
    """One captain's slice: {"avg": {...}, "reps": {name: {...}}}.

    Reps Tableau files under a captain they are not on are dropped here — the
    fill appends a row for every owner in the slice, so the pin has to land
    before it. `avg` is Tableau's own team row and still carries them; see
    automations/shared/captainship_pins.py.

    ONE EXCEPTION, added 2026-09-01: when the slice carries an ADOPTED rep
    (someone Tableau still files under another captain — captainship_pins.
    ADOPTED), Tableau's own Total row cannot know about them, so the 0-30
    average is recomputed from the slice's cancels/sales counts. That is an
    exact arithmetic identity, not an average of averages, and it reproduces
    Tableau's own number when nobody is adopted. The 30-60 rate is left alone:
    the view exports no counts behind it, so there is nothing honest to sum.
    """
    slice_ = parsed.get("teams", {}).get(team, {"avg": {}, "reps": {}})
    slice_["reps"] = _pins.drop_reps(slice_.get("reps", {}), team, logfn=print)
    adopted = [n for n in slice_["reps"] if _pins.adopted_from(team, n)]
    if adopted:
        avg = _recomputed_030_avg(slice_["reps"])
        if avg:
            was = (slice_.get("avg") or {}).get(P_030)
            slice_.setdefault("avg", {})[P_030] = avg
            print(f"  ↺ {team}: 0-30 Captainship Avg recomputed {was} -> {avg} "
                  f"(includes adopted {', '.join(sorted(adopted))})")
        else:
            print(f"  ⚠ {team}: adopted rep(s) {', '.join(sorted(adopted))} are "
                  f"in the slice but the view exported no cancels/sales counts "
                  f"— Captainship Avg left as Tableau's (excludes them)")
    # The counts have done their job; drop them so every remaining value in the
    # slice is a display string, which is all the fill ever expects.
    for slot in [slice_.get("avg") or {}] + list(slice_["reps"].values()):
        slot.pop("counts_030", None)
    return slice_
