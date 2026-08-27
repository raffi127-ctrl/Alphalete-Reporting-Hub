"""Where an onboarding submission goes: the 'Office Onboarding' tab of the
AUTOMATION MASTER sheet — the config store the reports + Hub read from — with a
local-JSON fallback so the form works while building (no creds, no writes to the
real master sheet).

Also reads the CURRENT registries (office_metrics + b2b_metrics) so the form can
flag a collision with an already-wired office before Megan submits.

The master sheet id is fixed (it's THE config store), but it's only WRITTEN when
a gspread client is injected — during local preview the fallback keeps the draft
in output/ and never touches the live sheet (sandbox-first).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.office_onboarding.schema import (
    OnboardingRecord, EnrolledReport, ChannelPlan)

# THE config store. A new "Office Onboarding" tab in the AUTOMATION MASTER sheet.
MASTER_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
ONBOARDING_TAB = "Office Onboarding"

# The OWNER-facing intake lands here first (a partial record — no sheet/wiring).
# Megan finalizes it in the Office Onboarding form, which writes ONBOARDING_TAB.
REQUESTS_TAB = "Metric Requests"

# One JSON blob per office in column B keeps the tab future-proof (new fields
# never need a schema migration); column A is the key for at-a-glance reading.
_HEADER = ["office_key", "config_json", "machine", "report_id", "submitted_at",
           "submitted_by"]

# The requests tab: same config_json blob + a status the finalize step flips
# ("new" -> "wired") so a request is never silently re-finalized.
_REQ_HEADER = ["office_key", "config_json", "family", "status", "submitted_at",
               "submitted_by"]

_LOCAL_FALLBACK = (Path(__file__).resolve().parents[2] / "output"
                   / "office_onboarding_submissions.json")
_LOCAL_REQUESTS = (Path(__file__).resolve().parents[2] / "output"
                   / "office_metric_requests.json")

_CLIENT = None


# gspread raises WorksheetNotFound for "no tab by that name" and APIError for
# everything else (429 rate limits, 403s, transient 5xx). Only the first means
# "create it". Older gspread versions lack the symbol — fall back to a sentinel
# that matches nothing, so a missing symbol can never widen the except.
try:                                     # gspread >= 5
    from gspread.exceptions import WorksheetNotFound as _WorksheetNotFound
except Exception:                        # noqa: BLE001
    class _WorksheetNotFound(Exception):
        pass


def set_client(gspread_client) -> None:
    global _CLIENT
    _CLIENT = gspread_client


def get_client():
    """The injected gspread client (None if unset). Lets the form reuse the same
    client to enqueue a mini_control job (the queue is a tab on this same sheet)."""
    return _CLIENT


def _ws():
    """The 'Office Onboarding' worksheet, created (with header) if missing.
    None when no client is injected — callers fall back to local JSON."""
    if _CLIENT is None:
        return None
    ss = _CLIENT.open_by_key(MASTER_SHEET_ID)
    try:
        return ss.worksheet(ONBOARDING_TAB)
    except _WorksheetNotFound:
        # ONLY a genuinely absent tab is created. A bare `except Exception` here
        # turned a transient Sheets 429 ("Read requests per minute per user")
        # into an attempt to CREATE a tab that already exists — which fails 400
        # and blocked auto_commit's schedule self-heal on 2026-08-26. Worse, had
        # the create ever landed, a second empty 'Office Onboarding' would shadow
        # the real one. Anything that is not "no such worksheet" re-raises.
        ws = ss.add_worksheet(title=ONBOARDING_TAB, rows=200, cols=len(_HEADER))
        ws.append_row(_HEADER)
        return ws


def save(rec: OnboardingRecord) -> str:
    """Append the record. Returns 'sheet' or 'local' so the form can tell Megan
    where it landed. Append-only — never overwrites another office's row."""
    row = [rec.key, json.dumps(rec.to_json()), rec.machine(), rec.report_id(),
           rec.submitted_at, rec.submitted_by]
    ws = _ws()
    if ws is not None:
        if not ws.get_all_values():
            ws.append_row(_HEADER)
        ws.append_row(row)
        return "sheet"
    # local fallback (durable when run locally, ephemeral on Cloud)
    _LOCAL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    data = []
    if _LOCAL_FALLBACK.exists():
        try:
            data = json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:
            data = []
    data.append(rec.to_json())
    _LOCAL_FALLBACK.write_text(json.dumps(data, indent=2))
    return "local"


def load_all() -> List[dict]:
    """Every onboarded office's config json (from the sheet, else local file).
    This is what apply.py materializes into the registries."""
    ws = _ws()
    if ws is not None:
        out = []
        for r in ws.get_all_records():
            raw = r.get("config_json") or ""
            if raw:
                try:
                    out.append(json.loads(raw))
                except Exception:
                    continue
        return out
    if _LOCAL_FALLBACK.exists():
        try:
            return json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:
            return []
    return []


# --------------------------------------------------------------------------
# Metric Requests tab — the OWNER-facing intake (partial records Megan finalizes).
# --------------------------------------------------------------------------
def _requests_ws():
    """The 'Metric Requests' worksheet, created (with header) if missing. None
    when no client is injected — callers fall back to local JSON."""
    if _CLIENT is None:
        return None
    ss = _CLIENT.open_by_key(MASTER_SHEET_ID)
    try:
        return ss.worksheet(REQUESTS_TAB)
    except _WorksheetNotFound:              # see _ws() — never on a rate limit
        ws = ss.add_worksheet(title=REQUESTS_TAB, rows=200, cols=len(_REQ_HEADER))
        ws.append_row(_REQ_HEADER)
        return ws


def save_request(rec: OnboardingRecord) -> str:
    """Append an owner's partial request. Returns 'sheet' or 'local'. Append-only —
    never overwrites another office's row; status starts 'new'."""
    row = [rec.key, json.dumps(rec.to_json()), rec.family, "new",
           rec.submitted_at, rec.submitted_by]
    ws = _requests_ws()
    if ws is not None:
        if not ws.get_all_values():
            ws.append_row(_REQ_HEADER)
        ws.append_row(row)
        return "sheet"
    _LOCAL_REQUESTS.parent.mkdir(parents=True, exist_ok=True)
    data = []
    if _LOCAL_REQUESTS.exists():
        try:
            data = json.loads(_LOCAL_REQUESTS.read_text())
        except Exception:
            data = []
    blob = rec.to_json()
    blob["_status"] = "new"
    data.append(blob)
    _LOCAL_REQUESTS.write_text(json.dumps(data, indent=2))
    return "local"


def load_requests(status: Optional[str] = None) -> List[dict]:
    """Every owner request's config json (sheet, else local). Each dict carries a
    `_status` key. Pass status='new' to get only the not-yet-finalized ones."""
    out: List[dict] = []
    ws = _requests_ws()
    if ws is not None:
        for r in ws.get_all_records():
            raw = r.get("config_json") or ""
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except Exception:
                continue
            d["_status"] = (r.get("status") or "new").strip() or "new"
            out.append(d)
    elif _LOCAL_REQUESTS.exists():
        try:
            for d in json.loads(_LOCAL_REQUESTS.read_text()):
                d.setdefault("_status", "new")
                out.append(d)
        except Exception:
            out = []
    if status is not None:
        out = [d for d in out if d.get("_status") == status]
    return out


def mark_request_wired(office_key: str) -> bool:
    """Flip a request's status to 'wired' once Megan finalizes it, so it drops out
    of the pending list. Best-effort; returns True if a row was updated."""
    ws = _requests_ws()
    if ws is not None:
        try:
            values = ws.get_all_values()
        except Exception:
            return False
        if not values:
            return False
        header = values[0]
        try:
            key_col = header.index("office_key")
            status_col = header.index("status")
        except ValueError:
            return False
        updated = False
        for i, row in enumerate(values[1:], start=2):
            if len(row) > key_col and row[key_col] == office_key:
                ws.update_cell(i, status_col + 1, "wired")
                updated = True
        return updated
    # local fallback
    if not _LOCAL_REQUESTS.exists():
        return False
    try:
        data = json.loads(_LOCAL_REQUESTS.read_text())
    except Exception:
        return False
    updated = False
    for d in data:
        if d.get("key") == office_key:
            d["_status"] = "wired"
            updated = True
    if updated:
        _LOCAL_REQUESTS.write_text(json.dumps(data, indent=2))
    return updated


def record_from_json(d: dict) -> OnboardingRecord:
    """Rebuild an OnboardingRecord from a stored config json (drops _derived)."""
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    reps = [EnrolledReport(**er) if isinstance(er, dict) else er
            for er in d.pop("reports", [])]
    plans = [ChannelPlan(**cp) if isinstance(cp, dict) else cp
             for cp in d.pop("channel_plans", [])]
    return OnboardingRecord(reports=reps, channel_plans=plans, **d)


# --------------------------------------------------------------------------
# Current registry snapshot — so the form flags collisions with LIVE offices.
# --------------------------------------------------------------------------
def existing_registry(exclude_key: Optional[str] = None) -> Dict[str, object]:
    """{'keys': [...], 'channels': {channel_id: key}, 'views': {url: 'key.report'}}
    across office_metrics + b2b_metrics, plus already-onboarded rows. Best-effort:
    an import that fails just contributes nothing (never blocks the form).

    `exclude_key` drops that office from the pending-submission scan so a record
    never collides with ITSELF when it's already saved to the tab (validation of
    a resubmission / an already-stored row)."""
    keys: List[str] = []
    channels: Dict[str, str] = {}
    views: Dict[str, str] = {}

    def _scan_offices(mod_offices):
        for k, o in getattr(mod_offices, "OFFICES", {}).items():
            # An office already applied into OFFICES must not collide with ITSELF
            # on a re-apply (idempotent onboard_apply / a Post-now re-click).
            if exclude_key and k == exclude_key:
                continue
            keys.append(k)
            cid = getattr(o, "channel_id", "")
            if cid:
                channels.setdefault(cid, k)
            for vname, url in (getattr(o, "views", {}) or {}).items():
                if url:
                    views.setdefault(url, f"{k}.{vname}")

    for path in ("automations.office_metrics.offices",
                 "automations.b2b_metrics.offices"):
        try:
            mod = __import__(path, fromlist=["OFFICES"])
            _scan_offices(mod)
        except Exception:
            pass

    # already-submitted (not-yet-applied) offices count too, minus the one being
    # validated (so it never collides with itself).
    for d in load_all():
        k = d.get("key")
        if k and k == exclude_key:
            continue
        if k:
            keys.append(k)
        cid = d.get("channel_id")
        if cid:
            channels.setdefault(cid, k or "(onboarded)")
        for er in d.get("reports", []):
            url = (er.get("view_url") if isinstance(er, dict) else "") or ""
            if url:
                views.setdefault(url, f"{k}.{er.get('key')}")

    return {"keys": keys, "channels": channels, "views": views}
