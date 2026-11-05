"""Fiber churn tier per owner, for the 'Nov Tier / $ per sale' column on the
New Internet churn images (Raf's Loom 2026-10-29, all Fiber captainships since 2026-11-05).

SOURCE OF THE TIER (Chris Williford 2026-11-04, "Churn tiers for whole
captainship on Fiber"; refreshed the Monday new tiers start):
  workbook  ATT Tracker 2.1 - D2D
  view      D2D 1-PAGERV2 (Internet Only)
  worksheet 'ICD Summary - ATT (V2) (2)' (this week)
            'ICD Summary - ATT (V2) (LW) (3)' (last week)
  columns   ICD Owner Name | '<Month> Churn Tier'
The tracker's tier is the official one: it carries exceptions a calculation
could not know (Joe Logan was placed in Tier 4 for November by hand).

SOURCE OF THE $: the 'Impact to ICD' row of the CHURN TIERS block on the tab
being drawn (rows 1-3), same numbers as Chart 4 of Smart Circle's Churn Notice.

An owner with no sales in a week is missing from that week's sheet, so both
sheets are merged. This never blocks an email: no data = no column.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

WORKSPACE = Path(__file__).resolve().parents[2]
CACHE_PATH = WORKSPACE / "output" / "fiber_churn_tiers.json"

_TIER_COL_RE = re.compile(r"^\s*([A-Za-z]+)\s+Churn\s+Tier\s*$", re.I)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]


def norm_name(name: str) -> str:
    s = (name or "").replace("’", "'").strip().upper()
    return re.sub(r"\s+", " ", s)


def parse_crosstab(path: Path) -> Tuple[str, Dict[str, str]]:
    """Return (month, {NORMALIZED OWNER: 'Tier 3'}) from the UTF-16 crosstab.

    The tier column is found by NAME and its month read from that name, because
    the header changes every month ('July Churn Tier', 'November Churn Tier')."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        raise RuntimeError("crosstab is empty")
    head = rows[0]
    owner_col = next((i for i, h in enumerate(head)
                      if "icd owner name" in h.strip().lower()), None)
    tier_col = next((i for i, h in enumerate(head)
                     if _TIER_COL_RE.match(h)), None)
    if owner_col is None or tier_col is None:
        raise RuntimeError(f"no owner / churn tier column in: {head}")
    month = _TIER_COL_RE.match(head[tier_col]).group(1).capitalize()
    tiers: Dict[str, str] = {}
    for r in rows[1:]:
        owner = norm_name(r[owner_col] if len(r) > owner_col else "")
        tier = (r[tier_col] if len(r) > tier_col else "").strip()
        if owner and owner != "GRAND TOTAL" and re.match(r"^Tier\s*\d$", tier, re.I):
            tiers[owner] = "Tier " + tier[-1]
    return month, tiers


def merge_pulls(pulls: List[Tuple[str, Dict[str, str]]]) -> Tuple[str, Dict[str, str]]:
    """Merge sheets, first one wins. A sheet from an OLDER tier month is dropped:
    an owner with no sales yet must show blank, never last month's tier."""
    pulls = [p for p in pulls if p[1]]
    if not pulls:
        return "", {}

    def _rank(month: str) -> int:
        m = month.lower()
        return _MONTHS.index(m) if m in _MONTHS else -1

    # December -> January: the year rolled, so January is the newer one.
    ranks = [_rank(m) for m, _ in pulls]
    newest = 0 if 0 in ranks and 11 in ranks else max(ranks)
    month = next(m for m, _ in pulls if _rank(m) == newest)
    out: Dict[str, str] = {}
    for m, tiers in pulls:
        if _rank(m) == newest:
            for owner, tier in tiers.items():
                out.setdefault(owner, tier)
    return month, out


def pull(out_dir: Optional[Path] = None, *, today: Optional[dt.date] = None,
         logfn=print) -> dict:
    """Download both sheets through Tableau and save the merged cache."""
    from automations.recruiting_report import opt_phase as _opt
    out_dir = out_dir or (WORKSPACE / "output")
    today = today or dt.date.today()
    pulls = []
    for sheet, name in ((_opt.INT_SHEET, "this_week"), (_opt.INT_SHEET_LW, "last_week")):
        path = Path(out_dir) / f"fiber_churn_tiers_{name}.csv"
        try:
            _opt.download_crosstab(_opt.INT_VIEW_URL, sheet, path, verbose=False)
            pulls.append(parse_crosstab(path))
        except Exception as e:  # noqa: BLE001 - an empty week hides its sheet
            logfn(f"  churn tiers: couldn't read '{sheet}': {str(e)[:150]}")
    month, tiers = merge_pulls(pulls)
    if not tiers:
        raise RuntimeError("no churn tiers in either tracker sheet")
    data = {"month": month, "pulled": today.isoformat(), "tiers": tiers}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    logfn(f"  churn tiers: {len(tiers)} owners, {month}")
    return data


def load_or_pull(today: dt.date, *, logfn=print) -> Optional[dict]:
    """Today's tiers. Pulls once per day per machine; if the pull fails, falls
    back to a copy up to 7 days old. None = draw no column."""
    cached = None
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no cache yet
        pass
    if cached and cached.get("pulled") == today.isoformat():
        return cached
    try:
        return pull(today=today, logfn=logfn)
    except Exception as e:  # noqa: BLE001 - a dead source never holds the email
        logfn(f"  churn tiers: pull failed ({str(e)[:150]})")
        if cached and (today - dt.date.fromisoformat(cached["pulled"])).days <= 7:
            logfn("  churn tiers: using the last good copy")
            return cached
        logfn("  churn tiers: no tier column today")
        return None


def impact_from_sheet(rows: List[List[str]]) -> Dict[str, str]:
    """{'Tier 1': '-$40', ...} from the CHURN TIERS block (rows 1-3 of the tab),
    found by its labels so a moved or added tier can't shift the numbers."""
    head = next((r for r in rows if r and r[0].strip().lower() == "churn tiers"), None)
    impact = next((r for r in rows if r and r[0].strip().lower().startswith("impact")), None)
    if not head or not impact:
        return {}
    return {t.strip(): v.strip() for t, v in zip(head[1:], impact[1:])
            if t.strip() and v.strip()}


class TierColumn:
    """What the renderer draws: one (tier, $) per owner."""

    def __init__(self, month: str, tiers: Dict[str, str], impact: Dict[str, str],
                 candidates: Optional[Callable[[str], List[str]]] = None):
        self.header = f"{month[:3]} Tier" if month else "Tier"
        self.tiers = tiers
        self.impact = impact
        self.candidates = candidates

    def for_owner(self, name: str) -> Tuple[str, str]:
        """('Tier 3', '-$20'), or ('', '') when the tracker doesn't list them."""
        names = [name]
        if self.candidates:
            try:
                names += list(self.candidates(name))
            except Exception:  # noqa: BLE001 - alias sheet down: exact name only
                pass
        for n in names:
            tier = self.tiers.get(norm_name(n))
            if tier:
                return tier, self.impact.get(tier, "")
        return "", ""


def build_column(ws, today: dt.date, *, logfn=print) -> Optional[TierColumn]:
    """The column for tab `ws`, or None: the image then draws as it always did."""
    data = load_or_pull(today, logfn=logfn)
    if not data:
        return None
    try:
        impact = impact_from_sheet(ws.get("A1:G3"))
    except Exception as e:  # noqa: BLE001
        logfn(f"  churn tiers: couldn't read CHURN TIERS block: {str(e)[:150]}")
        return None
    if not impact:
        logfn("  churn tiers: no 'Impact to ICD' row on the tab; no tier column")
        return None
    candidates = None
    try:
        from automations.focus_office_att import aliases as _al
        raw = _al.load_aliases()
        candidates = lambda n: _al.get_search_candidates(n, raw)  # noqa: E731
    except Exception as e:  # noqa: BLE001
        logfn(f"  churn tiers: alias sheet unavailable: {str(e)[:120]}")
    return TierColumn(data.get("month", ""), data.get("tiers", {}), impact, candidates)


if __name__ == "__main__":
    print(json.dumps(pull(), indent=1))
