"""Load and save a per-office pay structure.

A structure is: the office's leader levels, the campaigns it runs, and — for
each sale type under those campaigns — the dollars a rep earns per unit at each
level.

    levels    : ["Level 1", "Level 2", ...]
    campaigns : ["att_residential", "box", ...]         # what the office checked
    rates     : {campaign: {sale_type: {level: dollars}}}

Sale-type strings come from `catalog.py` (seeded from the real order logs), so
they are the exact join key the build prices against.

Two backends, chosen automatically:
  * Google Sheet — one tab per office, holding the structure as JSON (the editor
    is the interface; nobody hand-edits the tab). Used when a sheet id is
    configured (env PAY_STRUCTURE_SHEET_ID or the editor's secret).
  * Local JSON — automations/pay_structure/data/<office>.json, gitignored. The
    default while building, so nothing touches a live Sheet until we say go.

Cross-platform + Python 3.9-safe (the mini runs 3.9).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_DATA_DIR = Path(__file__).with_name("data")

# Optional gspread client the editor injects (built from Streamlit secrets), so
# the deployed app can reach the Sheet. Unset -> the Sheet backend falls back to
# recruiting_report.fill.open_by_key (how the mini's build reads the same Sheet).
_CLIENT = None


def set_client(gc) -> None:
    global _CLIENT
    _CLIENT = gc


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------
@dataclass
class Grid:
    office_key: str
    levels: "List[str]" = field(default_factory=list)
    campaigns: "List[str]" = field(default_factory=list)
    # campaign -> sale_type -> {level -> dollars}
    rates: "Dict[str, Dict[str, Dict[str, float]]]" = field(default_factory=dict)
    office_name: str = ""
    logo: str = ""             # data: URI (base64) of the office's logo, if set
    accent: str = ""           # brand accent hex (#RRGGBB), derived from the logo
    updated_at: str = ""
    updated_by: str = ""

    # --- lookups -----------------------------------------------------------
    def rate(self, campaign: str, sale_type: str, level: str) -> float:
        try:
            return float(self.rates[campaign][sale_type].get(level) or 0.0)
        except (KeyError, TypeError):
            return 0.0

    def sale_types(self, campaign: str) -> "List[str]":
        return list(self.rates.get(campaign, {}).keys())

    def is_empty(self) -> bool:
        return not self.levels or not self.campaigns

    # --- seeding -----------------------------------------------------------
    def ensure_campaign(self, campaign: str) -> None:
        self.rates.setdefault(campaign, {})
        if campaign not in self.campaigns:
            self.campaigns.append(campaign)

    def ensure_sale_types(self, campaign: str, sale_types) -> bool:
        """Add a blank row for any sale type not already present in a campaign.
        Returns True if anything was added."""
        bucket = self.rates.setdefault(campaign, {})
        have = {s.strip().lower() for s in bucket}
        changed = False
        for s in sale_types:
            s = (s or "").strip()
            if s and s.lower() not in have:
                bucket[s] = {lvl: 0.0 for lvl in self.levels}
                have.add(s.lower())
                changed = True
        return changed

    def normalize(self) -> None:
        """Give every priced row exactly the current level set; keep the
        campaigns list in sync with what actually has a rates bucket."""
        for camp, types in self.rates.items():
            for st, r in types.items():
                types[st] = {lvl: float(r.get(lvl) or 0.0) for lvl in self.levels}
        for camp in list(self.rates):
            if camp not in self.campaigns:
                self.campaigns.append(camp)

    # --- serialization -----------------------------------------------------
    def to_dict(self, include_logo: bool = True) -> dict:
        d = {"office_key": self.office_key, "levels": list(self.levels),
             "campaigns": list(self.campaigns),
             "rates": {c: {s: dict(r) for s, r in types.items()}
                       for c, types in self.rates.items()},
             "office_name": self.office_name, "accent": self.accent,
             "updated_at": self.updated_at, "updated_by": self.updated_by}
        if include_logo:
            d["logo"] = self.logo
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Grid":
        levels = [str(x) for x in (d.get("levels") or [])]
        rates: Dict[str, Dict[str, Dict[str, float]]] = {}
        for c, types in (d.get("rates") or {}).items():
            rates[str(c)] = {}
            for s, r in (types or {}).items():
                rates[str(c)][str(s)] = {str(k): float(v or 0.0)
                                         for k, v in (r or {}).items()}
        return cls(office_key=str(d.get("office_key", "")), levels=levels,
                   campaigns=[str(x) for x in (d.get("campaigns") or [])],
                   rates=rates, office_name=str(d.get("office_name", "")),
                   logo=str(d.get("logo", "")), accent=str(d.get("accent", "")),
                   updated_at=str(d.get("updated_at", "")),
                   updated_by=str(d.get("updated_by", "")))


def blank_grid(office_key: str) -> Grid:
    """A fresh structure: three levels, no campaigns checked yet."""
    return Grid(office_key=office_key, levels=["Level 1", "Level 2", "Level 3"],
                campaigns=[], rates={})


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def _sheet_id() -> "Optional[str]":
    sid = os.environ.get("PAY_STRUCTURE_SHEET_ID")
    if sid:
        return sid.strip()
    try:
        import streamlit as st  # type: ignore
        if "pay_structure_sheet_id" in st.secrets:
            return str(st.secrets["pay_structure_sheet_id"]).strip()
    except Exception:
        pass
    return None


def _json_path(office_key: str) -> Path:
    return _DATA_DIR / f"{office_key}.json"


# ---------------------------------------------------------------------------
# Public API — load / save
# ---------------------------------------------------------------------------
class SaveError(Exception):
    """Persistence isn't reachable (bad/missing Google creds, etc.)."""


def load(office_key: str) -> "Optional[Grid]":
    sid = _sheet_id()
    if sid:
        # A sheet we can't reach (missing creds, network) must NOT crash the
        # editor — treat it as "no structure yet" so the branded page still
        # loads. Saving surfaces the real error via SaveError.
        try:
            return _sheet_load(sid, office_key)
        except Exception:
            return None
    p = _json_path(office_key)
    if p.exists():
        return Grid.from_dict(json.loads(p.read_text()))
    return None


def save(grid: Grid) -> None:
    grid.normalize()
    sid = _sheet_id()
    if sid:
        try:
            _sheet_save(sid, grid)
        except Exception as e:                       # noqa: BLE001
            raise SaveError(
                "Couldn't reach the pay-structure sheet — the app's Google "
                "credentials ([gcp_oauth] secret) look missing or invalid. "
                "({}: {})".format(type(e).__name__, e))
        return
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _json_path(grid.office_key).write_text(json.dumps(grid.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# Google Sheet backend — one tab per office, structure stored as JSON. The
# editor is the only writer, so a JSON blob is simpler + lossless vs. trying to
# lay a nested campaign/sale-type/level cube out as a flat grid. A1 holds a human
# hint; A2 holds the JSON.
# ---------------------------------------------------------------------------
_SHEET_HINT = "Edited through the Pay Structure app — do not edit here."


def _retry(fn):
    try:
        from automations.recruiting_report.fill import _retry as _r
        return _r(fn)
    except Exception:
        return fn()


def _open_ss(sheet_id: str):
    if _CLIENT is not None:
        return _CLIENT.open_by_key(sheet_id)
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(sheet_id)


def _open_ws(sheet_id: str, office_key: str, create: bool):
    ss = _open_ss(sheet_id)
    try:
        return _retry(lambda: ss.worksheet(office_key))
    except Exception:
        if not create:
            return None
        return _retry(lambda: ss.add_worksheet(title=office_key, rows=10, cols=2))


def _sheet_load(sheet_id: str, office_key: str) -> "Optional[Grid]":
    ws = _open_ws(sheet_id, office_key, create=False)
    if ws is None:
        return None
    # A2 = grid JSON (no logo, stays small); A3 = logo data URI (own cell so the
    # base64 can't push the grid JSON over Sheets' 50k-char cell limit).
    vals = _retry(lambda: ws.get("A2:A3"))
    raw = (vals[0][0] if vals and vals[0] else "") if vals else ""
    if not raw:
        return None
    try:
        g = Grid.from_dict(json.loads(raw))
    except Exception:
        return None
    if len(vals) > 1 and vals[1]:
        g.logo = vals[1][0] or ""
    return g


def _sheet_save(sheet_id: str, grid: Grid) -> None:
    ws = _open_ws(sheet_id, grid.office_key, create=True)
    body = json.dumps(grid.to_dict(include_logo=False))
    _retry(lambda: ws.update([[_SHEET_HINT], [body], [grid.logo or ""]],
                             range_name="A1:A3"))
