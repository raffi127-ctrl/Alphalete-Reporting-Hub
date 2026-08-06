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


def estimate_live() -> bool:
    """Master switch for the DAILY ORDER-LOG pay estimate. Default OFF — the posted
    order logs must NOT show rep paycheck estimates until Megan flips this on (set
    env PAY_ESTIMATE_LIVE=1 on the runner). Keeps estimates out of the live posts
    while the pay-structure/payout build is still being locked down, even if an ICD
    fills in their structure during review. The EDITOR is unaffected — offices can
    fill in and preview; only the order-log integration is gated."""
    return os.environ.get("PAY_ESTIMATE_LIVE", "").strip().lower() in (
        "1", "true", "yes", "on")

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
# Google Sheet backend — ONE shared tab, one ROW per office (Megan 2026-07-24:
# keep the master workbook to a single tab, not a tab per ICD). Columns give a
# readable at-a-glance view; the last column holds the structure as JSON (the
# source of truth the editor writes + the Order Log reads). Logo is NOT stored
# here — it ships in the committed branding.json — so the JSON stays small.
# ---------------------------------------------------------------------------
_STRUCT_TAB = "Lucy Pay Structures"
_STRUCT_HEADER = ["Office", "Business Name", "Campaigns", "Updated (UTC)",
                  "Data (JSON) — do not edit"]
_DATA_COL = len(_STRUCT_HEADER)          # 1-based index of the JSON column


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


def _open_struct_ws(sheet_id: str, create: bool):
    ss = _open_ss(sheet_id)
    try:
        return _retry(lambda: ss.worksheet(_STRUCT_TAB))
    except Exception:
        if not create:
            return None
        ws = _retry(lambda: ss.add_worksheet(title=_STRUCT_TAB, rows=60,
                                             cols=len(_STRUCT_HEADER)))
        _retry(lambda: ws.update([_STRUCT_HEADER], range_name="A1"))
        return ws


def _sheet_load(sheet_id: str, office_key: str) -> "Optional[Grid]":
    ws = _open_struct_ws(sheet_id, create=False)
    if ws is None:
        return None
    values = _retry(lambda: ws.get_all_values())
    if not values:
        return None
    di = _DATA_COL - 1
    want = office_key.strip().lower()
    for row in values[1:]:
        if row and row[0].strip().lower() == want:
            raw = row[di] if di < len(row) else ""
            if not raw:
                return None
            try:
                return Grid.from_dict(json.loads(raw))
            except Exception:
                return None
    return None


def _sheet_save(sheet_id: str, grid: Grid) -> None:
    ws = _open_struct_ws(sheet_id, create=True)
    values = _retry(lambda: ws.get_all_values()) or []
    if not values or (values[0][:1] or [""])[0] != _STRUCT_HEADER[0]:
        _retry(lambda: ws.update([_STRUCT_HEADER], range_name="A1"))
        values = [_STRUCT_HEADER]
    body = json.dumps(grid.to_dict(include_logo=False))
    rowvals = [grid.office_key, grid.office_name, ", ".join(grid.campaigns),
               grid.updated_at, body]
    want = grid.office_key.strip().lower()
    row_num = None
    for i, row in enumerate(values[1:], start=2):
        if row and row[0].strip().lower() == want:
            row_num = i
            break
    if row_num:
        _retry(lambda: ws.update([rowvals], range_name="A%d" % row_num,
                                 value_input_option="RAW"))
    else:
        _retry(lambda: ws.append_row(rowvals, value_input_option="RAW"))


# ---------------------------------------------------------------------------
# Access codes + progress, managed in the master workbook so Megan can add a
# password from the admin panel without touching Streamlit Cloud secrets.
# ---------------------------------------------------------------------------
_CODES_TAB = "Pay Structure Codes"
_CODES_HEADER = ["Office", "Business Name", "Access Code"]


def _open_codes_ws(sheet_id: str, create: bool):
    ss = _open_ss(sheet_id)
    try:
        return _retry(lambda: ss.worksheet(_CODES_TAB))
    except Exception:
        if not create:
            return None
        ws = _retry(lambda: ss.add_worksheet(title=_CODES_TAB, rows=40, cols=3))
        _retry(lambda: ws.update([_CODES_HEADER], range_name="A1"))
        return ws


def load_codes() -> "Dict[str, str]":
    """{office_key: access_code} from the codes tab, or {} if none/unreachable."""
    sid = _sheet_id()
    if not sid:
        return {}
    try:
        ws = _open_codes_ws(sid, create=False)
        if ws is None:
            return {}
        out: Dict[str, str] = {}
        for row in (_retry(lambda: ws.get_all_values()) or [])[1:]:
            if row and row[0].strip() and len(row) >= 3 and row[2].strip():
                out[row[0].strip()] = row[2].strip()
        return out
    except Exception:
        return {}


def save_codes(mapping: "Dict[str, str]", business: "Dict[str, str]",
               order: "List[str]") -> None:
    """Rewrite the codes tab from {office_key: code} (+ business names, in the
    given office order)."""
    sid = _sheet_id()
    if not sid:
        raise SaveError("No pay-structure sheet configured.")
    try:
        ws = _open_codes_ws(sid, create=True)
        rows = [_CODES_HEADER]
        for key in order:
            rows.append([key, business.get(key, ""), mapping.get(key, "")])
        _retry(lambda: ws.clear())
        _retry(lambda: ws.update(rows, range_name="A1", value_input_option="RAW"))
    except Exception as e:                           # noqa: BLE001
        raise SaveError("Couldn't save codes: {}".format(e))


_GROSS_TAB = "Pay Structure Gross Revenue"


def _open_gross_ws(sheet_id: str, create: bool):
    ss = _open_ss(sheet_id)
    try:
        return _retry(lambda: ss.worksheet(_GROSS_TAB))
    except Exception:
        if not create:
            return None
        ws = _retry(lambda: ss.add_worksheet(title=_GROSS_TAB, rows=40, cols=2))
        _retry(lambda: ws.update([["Office", "Gross revenue (JSON) — set by dd_pull"]],
                                 range_name="A1"))
        return ws


def save_gross_revenue(by_office: "Dict[str, dict]") -> None:
    """Write each office's parsed gross revenue ({office_key: {raw, main}})."""
    sid = _sheet_id()
    if not sid:
        raise SaveError("No pay-structure sheet configured.")
    ws = _open_gross_ws(sid, create=True)
    rows = [["Office", "Gross revenue (JSON) — set by dd_pull"]]
    for k, v in by_office.items():
        rows.append([k, json.dumps(v)])
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(rows, range_name="A1", value_input_option="RAW"))


def load_gross_revenue_all() -> "Dict[str, dict]":
    """{office_key: {raw, main, ...}} for every office (one Sheet read)."""
    sid = _sheet_id()
    if not sid:
        return {}
    out: "Dict[str, dict]" = {}
    try:
        ws = _open_gross_ws(sid, create=False)
        if ws is None:
            return {}
        for row in (_retry(lambda: ws.get_all_values()) or [])[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                try:
                    out[row[0].strip().lower()] = json.loads(row[1])
                except Exception:
                    pass
    except Exception:
        pass
    return out


def load_gross_revenue(office_key: str) -> dict:
    """The office's parsed gross revenue {raw:{...}, main:{...}}, or {}."""
    return load_gross_revenue_all().get(office_key.strip().lower(), {})


_WEEKLY_TAB = "Pay Structure Weekly"


def _open_weekly_ws(sheet_id: str, create: bool):
    ss = _open_ss(sheet_id)
    try:
        return _retry(lambda: ss.worksheet(_WEEKLY_TAB))
    except Exception:
        if not create:
            return None
        ws = _retry(lambda: ss.add_worksheet(title=_WEEKLY_TAB, rows=40, cols=2))
        _retry(lambda: ws.update([["Office", "Per-week sale types (JSON) — set by dd_pull"]],
                                 range_name="A1"))
        return ws


def save_weekly(by_office: "Dict[str, dict]") -> None:
    """Write each office's per-DD-week sale types: {office_key: {dd_week: {desc: $}}}."""
    sid = _sheet_id()
    if not sid:
        raise SaveError("No pay-structure sheet configured.")
    ws = _open_weekly_ws(sid, create=True)
    rows = [["Office", "Per-week sale types (JSON) — set by dd_pull"]]
    for k, v in by_office.items():
        rows.append([k, json.dumps(v)])
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(rows, range_name="A1", value_input_option="RAW"))


def load_weekly_all() -> "Dict[str, dict]":
    """{office_key: {dd_week: {desc: $}}} for every office (one Sheet read)."""
    sid = _sheet_id()
    if not sid:
        return {}
    out: "Dict[str, dict]" = {}
    try:
        ws = _open_weekly_ws(sid, create=False)
        if ws is None:
            return {}
        for row in (_retry(lambda: ws.get_all_values()) or [])[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                try:
                    out[row[0].strip().lower()] = json.loads(row[1])
                except Exception:
                    pass
    except Exception:
        pass
    return out


def load_weekly(office_key: str) -> dict:
    """One office's {dd_week: {desc: $}}, or {}."""
    return load_weekly_all().get(office_key.strip().lower(), {})


def list_structures() -> "List[dict]":
    """Who's filled in — [{office, business, campaigns, updated}] from the
    structures tab, for the admin 'progress' view."""
    sid = _sheet_id()
    if not sid:
        return []
    try:
        ws = _open_struct_ws(sid, create=False)
        if ws is None:
            return []
        out: List[dict] = []
        for row in (_retry(lambda: ws.get_all_values()) or [])[1:]:
            if row and row[0].strip():
                out.append({"office": row[0].strip(),
                            "business": row[1] if len(row) > 1 else "",
                            "campaigns": row[2] if len(row) > 2 else "",
                            "updated": row[3] if len(row) > 3 else ""})
        return out
    except Exception:
        return []
