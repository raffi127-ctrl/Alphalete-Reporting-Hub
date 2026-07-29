"""Pull the ABP % and the 6+-days-out % for each fiber captainship.

Same source as `captainship_activation_rate`: ONE crosstab of the Metrics
workbook's "Metrics Call Last week data (Internet)" sheet, already grouped by
`Captain's Bonus Teams`, downloaded once and sliced per team in Python.

Two columns are read, one per box on the tab:
  * 'New Internet ABP Mix % (Metrics)'          -> box 'ABP %'
  * '% of sales scheduled 6+ days out (4 wks)'  -> box '% of Ongoing 6+ Days Sales'

WHY THE SECOND COLUMN IS NOT THE ONE YOU SEE ON SCREEN
The visible 6-days-out column in the Tableau view is
'Intall Scheduled 6+ Days New Internet Count (4 wk)' (Tableau's own typo) and
it shows a COUNT — 834, 967. The percentage Eve wants is the one that appears
in the tooltip when you hover a cell. Tableau puts tooltip measures in the
crosstab export as their own column, so that % ships in the same download as
'% of sales scheduled 6+ days out (4 wks)' and no hovering is needed.

It is NOT derivable from the count: 834 6+-day sales against 513 'New Internet
Count (Metrics)' reads 41%, so the % runs over a denominator that isn't in the
export. Read the column or fail — never recompute it.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright as _dcp
from automations.captainship_activation_rate import pull as _act

VIEW_URL = _act.VIEW_URL
WORKSHEET = _act.WORKSHEET

# Box key -> crosstab column header. Box keys match fill.BOX_LABELS.
BOX_COLUMNS = {
    "abp":   "New Internet ABP Mix % (Metrics)",
    "6days": "% of sales scheduled 6+ days out (4 wks)",
}
BOXES = tuple(BOX_COLUMNS)

# Report slug -> `Captain's Bonus Teams` cell value. Shared with the sibling
# reports so an SFDC team rename is fixed in ONE place.
CAPTAIN_TEAM = _act.CAPTAIN_TEAM

# One download per PROCESS, shared by all captains — the view is identical for
# every one of them.
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
                            / "captainship_abp_6days_metrics.csv")
    if _METRICS_CSV is not None and _METRICS_CSV.exists():
        return _METRICS_CSV
    _dl(VIEW_URL, WORKSHEET, out_path, verbose=verbose, page=page)
    _METRICS_CSV = out_path
    return out_path


def parse(csv_path: Path, team_value: Optional[str] = None) -> dict:
    """Slice the crosstab to one captainship.

    Returns {"office_total": {box: {"pct": str}},
             "reps": {"Owner Name": {box: {"pct": str}}}}.

    Delegates to the activation report's parser with THIS report's two columns:
    the owner-subtotal rule it implements (keep only rows whose 'Rep Name' cell
    reads 'Total', or one rep's number lands in the owner's cell) is subtle
    enough that it gets exactly one implementation.

    The Captainship Avg is Tableau's OWN per-team `Total` row, not a recompute —
    an ABP mix % is not the mean of its owners' mixes. team_value=None returns
    the country `Grand Total` instead.
    """
    return _act.parse(csv_path, team_value, box_columns=BOX_COLUMNS)


def make_parser(slug: str):
    """A parse_fn bound to one captainship's team value."""
    team_value = CAPTAIN_TEAM[slug]

    def _parse(csv_path: Path) -> dict:
        return parse(csv_path, team_value)

    _parse.__name__ = f"parse_abp_6days_{slug}"
    return _parse
