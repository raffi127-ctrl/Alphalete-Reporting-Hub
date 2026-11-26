"""Interviewers Retention -> the ARS Interview Tracker web (Raf, 2026-11-20).

Raf: "Can we add this report to the website ... a tab or a dropdown where we
can select people that are using our service specifically, and also people
that are just within our org?"

The daily run already builds the four boards of the email. This file turns
them into one JSON document, written to a tab of the web's Google Sheet
(WEB_TAB); the web's Code.gs reads that tab and draws the four tables with a
menu of two views:

  service  "Use our service" -- the offices Camila's team interviews for
           (the owners on ARS Management 2.0's weekly tab). Same four boards
           as the email, same numbers.
  org      "Our org" -- every office of ours, whether it uses the service or
           not. Offices come from AppStream (the same 'Datos' tab the email's
           office tables use), kept when the office id is on one of the Hub's
           office lists (automations/recruiting_report/office-mapping*.json:
           confirmed / needs_review / sales_only; a 'skip' entry counts only
           when it isn't retired). Interviewer tables: the service's
           interviewers whose office is ours -- only the service records who
           interviewed, so there is no interviewer data for other offices.

office-groups.json (optional, next to this file) forces one owner in or out
of the org by hand: {"Owner Name": "org" | "not-org"}.

THE SHEET
    Sandbox first (CLAUDE.md): until Eve says "use the real Sheet", run with
    --web-sheet <test copy id>. The live target is the web's data sheet,
    WEB_SHEET_ID. Only the WEB_TAB tab is written -- created when missing,
    its column A replaced each run; no other tab is touched. The JSON is split
    over rows of column A (one cell holds at most 50,000 characters).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from automations.interviewers_retention import build

HERE = Path(__file__).resolve().parent
MAPPINGS = HERE.parent / "recruiting_report"
GROUPS_FILE = HERE / "office-groups.json"

# "ARS Interview Tracker - data" (Camila's web app is bound to it).
WEB_SHEET_ID = "1hdsOTlu-HLVjybwOzDPVg07EgvXTHZfQhgsTTu7q8mY"
WEB_TAB = "Retention Report"
CHUNK = 45000                 # characters per cell (Sheets limit is 50,000)

VIEW_LABELS = {"service": "Use our service", "org": "Our org (all offices)"}


# ------------------------------------------------------------ who is ours
def short(name: str) -> str:
    """'Drew Tepper - NDS' -> 'drew tepper'; 'COLTEN WRIGHT' -> 'colten wright'."""
    return build.name_key(re.sub(r"\s+-\s+[A-Za-z0-9 ]+$", "", str(name or "")))


class Org:
    """The Hub's office lists: office ids -> a display name, plus every name
    spelling, for owners with no AppStream office."""

    def __init__(self, folder: Path = MAPPINGS, overrides: Optional[Dict[str, str]] = None):
        self.ids: Dict[str, str] = {}
        self.names: Set[str] = set()
        for f in sorted(folder.glob("office-mapping*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:                        # noqa: BLE001
                continue
            for sec in ("confirmed", "needs_review", "sales_only", "skip"):
                for e in d.get(sec) or []:
                    if sec == "skip" and e.get("retired"):
                        continue                     # closed office
                    oid = str(e.get("office_id") or "").strip()
                    tab = re.sub(r"\s+-\s+[A-Za-z0-9 ]+$", "", str(e.get("sheet_tab") or "")).strip()
                    if oid and tab and sec != "skip":
                        self.ids.setdefault(oid, tab)
                    for k in ("sheet_tab", "as_owner"):
                        if e.get(k):
                            self.names.add(short(e[k]))
        self.names.discard("")
        if overrides is None:
            overrides = {}
            if GROUPS_FILE.exists():
                overrides = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
        self.force = {short(k): v for k, v in overrides.items() if v in ("org", "not-org")}

    def has_name(self, owner: str) -> bool:
        k = short(owner)
        if k in self.force:
            return self.force[k] == "org"
        k = build.OWNER_ALIASES.get(k, k)
        for o in self.names:
            if k == o or build.OWNER_ALIASES.get(o, o) == k:
                return True
            a, b = k.split(), o.split()
            # same first word + one name inside the other ('andre burton' /
            # 'andre burton jr'), or same first + same last word.
            if len(a) >= 2 and len(b) >= 2 and a[0] == b[0] and (
                    set(a) <= set(b) or set(b) <= set(a) or a[-1] == b[-1]):
                return True
        return False


def org_rows(datos_all: List["build.DayRow"], service_rows: List["build.DayRow"],
             org: Org) -> List["build.DayRow"]:
    """AppStream rows of every org office. A service office keeps the name the
    email gives it; any other office takes its Hub tab name."""
    svc_name = {r.office_id: r.owner for r in service_rows}
    out = []
    for r in datos_all:
        if r.office_id in svc_name:
            name = svc_name[r.office_id]
            if not org.has_name(name) and r.office_id not in org.ids:
                continue
        elif r.office_id in org.ids and org.force.get(short(org.ids[r.office_id])) != "not-org":
            name = org.ids[r.office_id]
        else:
            continue
        out.append(build.DayRow(r.week, r.date, r.office_id, name, r.booked, r.showed, r.company))
    return out


# ------------------------------------------------------------------ to JSON
def _p(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 4)


def board_json(b, keep=None) -> dict:
    """One board (DayBoard or Board). keep(line) -> False drops a row."""
    days = getattr(b, "days", None)
    lines = []
    for l in b.lines:
        if keep is not None and not keep(l):
            continue
        row = {"name": l.name, "owner": getattr(l, "owner", "") or "",
               "detail": list(l.detail), "booked": l.booked, "showed": l.showed,
               "pct": _p(l.pct), "history": [_p(h) for h in l.history]}
        if days is not None:
            row["days"] = [list(l.days.get(d, [0, 0])) for d in days]
        lines.append(row)
    out = {"title": b.title, "subtitle": b.subtitle, "header": b.name_header,
           "history_labels": list(b.history_labels), "lines": lines}
    if days is not None:
        out["days"] = [d.isoformat() for d in days]
    return out


def to_json(*, service: Tuple, org_boards: Optional[Tuple], org: Org, intro: str,
            notes: List[str], generated: dt.datetime) -> dict:
    """service / org_boards = (week by day interviewers, week by day offices,
    podium interviewers, podium offices). org_boards' interviewer boards are
    the service ones; their rows are filtered to org offices here."""
    wk_int, wk_off, pod_int, pod_off = service
    views = {"service": {"label": VIEW_LABELS["service"],
                         "boards": [board_json(b) for b in service]}}
    if org_boards:
        o_wk_off, o_pod_off = org_boards
        ours = lambda l: org.has_name(getattr(l, "owner", ""))      # noqa: E731
        views["org"] = {"label": VIEW_LABELS["org"],
                        "boards": [board_json(wk_int, ours), board_json(o_wk_off),
                                   board_json(pod_int, ours), board_json(o_pod_off)]}
    return {
        "generated": generated.strftime("%Y-%m-%d %H:%M"),
        "goal": build.GOAL,
        "intro": re.sub(r"<[^>]+>", "", intro.replace("<br>", "\n")),
        "notes": [re.sub(r"<[^>]+>", "", n) for n in notes],
        "views": views,
    }


def chunks(doc: dict) -> List[str]:
    s = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return [s[i:i + CHUNK] for i in range(0, len(s), CHUNK)] or [""]


# ------------------------------------------------------------------ writing
def write(doc: dict, sheet_id: str, logfn=print) -> int:
    """Replace the WEB_TAB tab's column A with the JSON pieces. Creates the
    tab when missing; touches no other tab."""
    from automations.recruiting_report import fill
    sh = fill.open_by_key(sheet_id)
    try:
        ws = fill.worksheet_ci(sh, WEB_TAB)
    except Exception:                                # noqa: BLE001
        ws = sh.add_worksheet(title=WEB_TAB, rows=50, cols=2)
        logfn(f"  web: created tab '{WEB_TAB}'")
    parts = chunks(doc)
    rows = [["json"]] + [[p] for p in parts]
    ws.batch_clear(["A:A"])
    if ws.row_count < len(rows):
        ws.add_rows(len(rows) - ws.row_count)
    ws.update(values=rows, range_name=f"A1:A{len(rows)}", value_input_option="RAW")
    logfn(f"  web: wrote {len(parts)} piece(s) to '{WEB_TAB}' in sheet {sheet_id}")
    return len(parts)
