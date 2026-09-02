"""Pull the two activation-rate percentages for each fiber captainship.

ONE Tableau crosstab feeds all five captains. The Metrics workbook's
"Metrics Call Last week data (Internet)" sheet is already grouped by
`Captain's Bonus Teams`: each team block carries one row per ICD owner plus a
`Total` row that IS that captainship's average, and a `Grand Total`/`Total`
row for the whole country. So we download once and slice per team in Python
rather than opening five per-captain views (there are none for this workbook).

Two columns are read, one per box on the sheet:
  * 'Rolling 4 Weeks'                          -> box 'ACTIVATION 0-30 DAYS'
  * '30-60 day New Internet activation rate'   -> box 'ACTIVATION RATE 30-60 DAYS'

Both column names are the same ones `country_metrics.pull` reads from this
workbook (METRICS_RATE_COLS 'rolling4' / 'act3060'), so a Tableau rename breaks
both reports at once and gets caught here too.

The view is opened at its DEFAULT 'Week's Metrics' filter, unlike
country_metrics which forces 'Last Week' because it fills a week behind. This
report is daily and both metrics are rolling windows, so the default (current)
reading is the one we want — Eve pointed at the bare view URL for exactly that.
"""
from __future__ import annotations

import csv
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright as _dcp
from automations.captainship_churn import pull as _cs   # _smart_title
from automations.recruiting_report import opt_phase as _opt
from automations.shared import captainship_pins as _pins

# The base Metrics dashboard, with its 'Metrics View' selector PINNED to
# Internet (2026-08-20 — a stray flip to Wireless killed this report and four
# siblings; see opt_phase.pin_internet_metrics). It has to stay the BASE view:
# the Internet-baked custom views expand to Rep Name, and that drifts the
# 30-60 activation by 0.1-1.5 pts. captainship_raf_metrics imports this URL.
VIEW_URL = _opt.pin_internet_metrics(
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics?:iid=1"
)
WORKSHEET = "Metrics Call Last week data (Internet)"

TEAM_COL = "Captain's Bonus Teams"
OWNER_COL = "ICD Owner Name (rep)"
# The live view breaks each owner down by individual REP as well, so the
# crosstab carries a third dimension column. The row we want is the owner's
# SUBTOTAL, where this cell reads 'Total'; the rep-level rows underneath it are
# individual reps and must be dropped. This column is OPTIONAL — the same
# worksheet exports without it when the view's rep breakdown is collapsed
# (country_metrics' cached pulls have no 'Rep Name' column at all), so its
# absence means every row is already owner-level.
REP_COL = "Rep Name"
# The subtotal marker, used in BOTH the owner column (per-team subtotal) and
# the rep column (per-owner subtotal).
TOTAL_ROW = "Total"

# Box key -> crosstab column header. Box keys match fill.BOX_LABELS.
BOX_COLUMNS = {
    "0-30":  "Rolling 4 Weeks",
    "30-60": "30-60 day New Internet activation rate",
}
BOXES = tuple(BOX_COLUMNS)

# Report slug -> `Captain's Bonus Teams` cell value. Same five fiber captains
# (and same team spellings) as owners_metrics_churn.FIBER_WIRELESS_TEAM.
CAPTAIN_TEAM = {
    "wayne": "Wayne's Team",
    "starr": "Starr's Team",
    "chan":  "Chan's Team",
    "tony":  "Tony's Team",
    "sahil": "Sahil's Team",
    "pat":   "Pat's Team",
    "jess":  "Jess's Team",
}

# One download per PROCESS, shared by all five captains — run.py calls the
# fetch fn once per selected report and this view is identical for all of them.
_METRICS_CSV: Optional[Path] = None


def _dl(view_url, crosstab_sheet, out_path, verbose=False, page=None, pre_export=None):
    """Harvest cutover (DEFAULT-OFF): read the dated cache when HARVEST_MODE=on,
    else scrape live. A cache miss/stale/error falls through to the live pull."""
    if os.environ.get("HARVEST_MODE", "off").strip().lower() == "on":
        from automations.harvest import adapter
        cached = adapter.try_cache_view(view_url, crosstab_sheet, out_path)
        if cached is not None:
            return cached
    return _dcp(view_url, crosstab_sheet, out_path,
                verbose=verbose, page=page, pre_export=pre_export)


def fetch(out_path: Optional[Path] = None, verbose: bool = False,
          page=None) -> Path:
    """Download the Metrics crosstab (all teams). Cached per process."""
    global _METRICS_CSV
    out_path = out_path or (Path(tempfile.gettempdir())
                            / "captainship_activation_metrics.csv")
    if _METRICS_CSV is not None and _METRICS_CSV.exists():
        return _METRICS_CSV
    _dl(VIEW_URL, WORKSHEET, out_path, verbose=verbose, page=page)
    _METRICS_CSV = out_path
    return out_path


def _read_crosstab(path: Path) -> list:
    """Crosstab CSVs are UTF-16 tab-delimited, but the encoding has drifted
    between utf-16-le and utf-16 (BOM) across Tableau versions — try each."""
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.reader(f, delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:  # noqa: BLE001 — try the next encoding
            continue
    return []


_PCT_RE = re.compile(r"^-?[\d,.]+%$")


def _pct(cell: str) -> str:
    """Keep a percentage cell as Tableau printed it ('80.5%'); anything that
    isn't a percentage (blank, '-', 'Null') becomes ''. The sheet's cells are
    PERCENT-formatted, so USER_ENTERED parses '80.5%' straight to 0.805."""
    v = (cell or "").strip()
    return v if _PCT_RE.match(v) else ""


def parse(csv_path: Path, team_value: Optional[str] = None,
          box_columns: Optional[dict] = None) -> dict:
    """Slice the crosstab to one captainship.

    `box_columns` ({box key: crosstab column header}) defaults to this
    report's two activation columns. Sibling reports off the SAME Metrics
    crosstab (captainship_abp_6days) pass their own pair rather than fork this
    function — the owner-subtotal rule below is the delicate part and must have
    exactly one implementation.

    Returns {"office_total": {box: {"pct": str}},
             "reps": {"Owner Name": {box: {"pct": str}}}} — the same shape the
    churn fills use, so the writer stays familiar.

    The Captainship Avg is Tableau's OWN per-team `Total` row, not a recompute:
    these are rates over different denominators (a rolling-4-week activation
    rate is not the mean of its owners' rates), so averaging the owner cells
    would be wrong. team_value=None returns the country `Grand Total` instead.
    """
    box_columns = box_columns or BOX_COLUMNS
    rows = _read_crosstab(csv_path)
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    team_i = header.index(TEAM_COL)
    owner_i = header.index(OWNER_COL)
    rep_i = header.index(REP_COL) if REP_COL in header else None
    missing = [c for c in box_columns.values() if c not in header]
    if missing:
        raise ValueError(
            f"Metrics crosstab is missing column(s) {missing}. Columns present: "
            f"{header}. A Tableau rename here also breaks country_metrics."
        )
    box_i = {b: header.index(c) for b, c in box_columns.items()}

    office_total: dict = {}
    reps: dict = {}
    matched_rows = 0

    for r in rows[1:]:
        if len(r) <= max(box_i.values()):
            continue
        team = (r[team_i] or "").strip()
        owner = (r[owner_i] or "").strip()
        # Read an ICD onto the captain they actually report to when Tableau
        # still files them under the old team — see captainship_pins.ADOPTED.
        # Feeds this report AND captainship_abp_6days, which reuses this parser.
        team = _pins.route_team(team, owner)
        # Keep ONLY the owner-level subtotal. Without this every individual
        # rep row under an owner is read as that owner, and the last one wins —
        # which silently writes one rep's rate into the owner's cell.
        if rep_i is not None and (r[rep_i] or "").strip() != TOTAL_ROW:
            continue
        if team_value is None:
            is_total = team == "Grand Total"
            if not is_total:
                continue
        else:
            if team != team_value:
                continue
            is_total = owner == TOTAL_ROW
        matched_rows += 1

        target = office_total if is_total else \
            reps.setdefault(_cs._smart_title(owner), {})
        for box, ci in box_i.items():
            pct = _pct(r[ci])
            if pct:
                target.setdefault(box, {})["pct"] = pct

    if team_value is not None and not matched_rows:
        # A silent empty slice would fill nothing and still read green. Almost
        # always an SFDC team rename -> CAPTAIN_TEAM must follow it.
        raise ValueError(
            f"No rows for {TEAM_COL} == {team_value!r} in {csv_path.name}. "
            f"Teams present: "
            f"{sorted({(r[team_i] or '').strip() for r in rows[1:] if len(r) > team_i})}"
        )

    # A rep Tableau still files under a captain they are not on would get an
    # owner row appended to the tab tomorrow even after the row is deleted, so
    # the pin is applied HERE, once, for every report off this parser
    # (activation rate + captainship_abp_6days). The office_total is Tableau's
    # own team row and still carries them — see the pins module.
    reps = _pins.drop_reps(reps, team_value or "Grand Total",
                           logfn=print, where=csv_path.name)

    return {"office_total": office_total, "reps": reps}


def make_parser(slug: str):
    """A parse_fn bound to one captainship's team value, for run.REPORTS."""
    team_value = CAPTAIN_TEAM[slug]

    def _parse(csv_path: Path) -> dict:
        return parse(csv_path, team_value)

    _parse.__name__ = f"parse_activation_{slug}"
    return _parse
