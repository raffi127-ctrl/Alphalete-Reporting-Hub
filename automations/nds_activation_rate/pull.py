"""Pull the NDS activation rates by rep, one download per captainship.

SOURCE (full path)
  Tableau -> NDS-SN (RES-ATT-OOF) Workbook -> Churn & Activation Rate (Rep)
          -> custom view "NDS Activation by Rep" (Eve, 2026-11-10: the same
             view with the Owner Name hierarchy expanded to Rep Name)
          -> worksheet "Churn % and Activation %"
          -> URL filter  NDS Captain Teams = <Captain>'s Team
  Columns used: Owner Name | Rep Name | New/Port Trailing Act. Rate (10-19 /
  20-29 / 30-60 Days). The 'Grand Total' row is the captainship average and
  each owner's 'Total' row is that owner's number — both are Tableau's own
  rollups, never an average of the rep cells (different denominators).

The custom view is saved on Eve's account; Lucy's account (RH) opens it. If
Dylan republishes the workbook the custom view can break: the download then
fails loudly and the fix is to re-save the view (expand Owner Name with the
'+', View -> Save custom view) and update CUSTOM_VIEW below.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

CUSTOM_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "NDS-SNRES-ATT-OOFWorkbook/ChurnActivationRateRep/"
               "53fa5d26-d645-4da8-b0fd-e1a2f0745dea/NDSActivationbyRep")
WORKSHEET = "Churn % and Activation %"
TEAM_FIELD = "NDS Captain Teams"

# window key -> column header in the crosstab
WINDOWS = (
    ("10-19", "New/Port Trailing Act. Rate (10-19 Days)"),
    ("20-29", "New/Port Trailing Act. Rate (20-29 Days)"),
    ("30-60", "New/Port Trailing Act. Rate (30-60 Days)"),
)

# A filtered download has one captainship's owners (7-12 on 2026-11-10). The
# unfiltered view has ~61. More than this means the URL filter was ignored and
# we would be writing the whole NDS site under one captain.
MAX_OWNERS_PER_TEAM = 30


def team_url(team: str) -> str:
    return f"{CUSTOM_VIEW}?{quote(TEAM_FIELD)}={quote(team)}&:iid=1"


def read_rows(path: Path) -> List[List[str]]:
    raw = Path(path).read_bytes()
    text = None
    for enc in ("utf-16", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            if "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return [r for r in csv.reader(text.splitlines(), delimiter=delim)]


def _col(header: List[str], *starts: str) -> Optional[int]:
    norm = [" ".join(h.split()).lower().rstrip(". ") for h in header]
    for s in starts:
        s = s.lower()
        for i, h in enumerate(norm):
            if h.startswith(s):
                return i
    return None


def _pct(cell: str) -> str:
    cell = (cell or "").strip()
    return cell if cell.endswith("%") else ""


def parse(rows: List[List[str]]) -> Dict:
    """-> {"avg": {win: "70.3%"}, "owners": {owner: {"total": {win: pct},
    "reps": {rep: {win: pct}}}}}. Owner order follows Tableau's."""
    if not rows:
        raise RuntimeError("empty crosstab")
    header = rows[0]
    c_owner = _col(header, "owner name")
    c_rep = _col(header, "rep name")
    c_win = {k: _col(header, h) for k, h in WINDOWS}
    missing = [n for n, c in [("Owner Name", c_owner), ("Rep Name", c_rep)]
               + [(h, c_win[k]) for k, h in WINDOWS] if c is None]
    if missing:
        raise RuntimeError(
            f"crosstab is missing column(s) {missing}; header was {header}. "
            "If 'Rep Name' is missing the custom view lost its expanded "
            "Owner -> Rep hierarchy (re-save it).")
    out: Dict = {"avg": {}, "owners": {}}
    last_owner = ""
    for r in rows[1:]:
        r = r + [""] * (len(header) - len(r))
        owner = (r[c_owner] or "").strip() or last_owner
        last_owner = owner
        rep = (r[c_rep] or "").strip()
        vals = {k: _pct(r[c]) for k, c in c_win.items()}
        if not owner:
            continue
        if owner.lower() == "grand total":
            out["avg"] = vals
            continue
        o = out["owners"].setdefault(owner, {"total": {}, "reps": {}})
        if rep.lower() in ("total", ""):
            o["total"] = vals
        else:
            o["reps"][rep] = vals
    return out


def download_team(page, team: str, out_path: Path) -> Dict:
    from automations.shared.tableau_patchright import download_crosstab_patchright
    p = download_crosstab_patchright(team_url(team), WORKSHEET, out_path,
                                     verbose=False, page=page)
    data = parse(read_rows(p))
    n = len(data["owners"])
    if n == 0:
        raise RuntimeError(f"{team}: the download has no owners")
    if n > MAX_OWNERS_PER_TEAM:
        raise RuntimeError(
            f"{team}: {n} owners — the '{TEAM_FIELD}' URL filter was ignored "
            "(the whole NDS site came back). Not writing anything.")
    return data
