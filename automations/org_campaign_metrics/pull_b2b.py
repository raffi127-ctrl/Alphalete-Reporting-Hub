"""B2B block for Atef — a straight copy of 'MT · Atef' on the Captainship
Dashboard. That tab is already filled daily by automations/captainship_boards
(order log + tracker + email stamps), and Carlos types the manual TEAM numbers
THERE — so for b2b the copy wins, manual rows included (layout.
STAMPER_OWNS_MANUAL). No Tableau involved: one FORMATTED_VALUE read.

Matching is by LABEL (col A), never by row number: the MT block has been
re-rowed three times in one day before (see captainship-sales-boards README).
"""
from __future__ import annotations

import datetime as _dt
import re

from automations.org_campaign_metrics import layout as L

CAPTAINSHIP_DASHBOARD = "14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8"
MT_TAB = "MT · Atef"
MANAGER = "Atef Choudhury"          # org Focus Report picker spelling

# MT col-A label (normalized) -> our layout label. The ✎ glyph and spacing
# vary; normalization strips both.
_MT_TO_OURS = {
    "head count": "Head Count  ✎",
    "leaders": "Leaders  ✎",
    "people in training": "People in Training  ✎",
    "active headcount on tableau": "Active Headcount on Tableau",
    "total apps": "Total Apps",
    "sales per rep": "Sales per Rep",
    "rank on the tracker": "Rank on the Tracker",
    "new internet": "New Internet Sales",
    "new internet sales": "New Internet Sales",
    "cru internet": "CRU Internet Sales",
    "cru internet sales": "CRU Internet Sales",
    "wireless (excl. byod)": "Wireless Sales (excl. BYOD)",
    "wireless sales (excl. byod)": "Wireless Sales (excl. BYOD)",
    "byod": "BYOD Sales",
    "byod sales": "BYOD Sales",
    "cru byod": "CRU BYOD Sales",
    "cru byod sales": "CRU BYOD Sales",
    "iru byod": "IRU BYOD Sales",
    "iru byod sales": "IRU BYOD Sales",
    "air/awb": "AIR/AWB Sales",
    "air/awb sales": "AIR/AWB Sales",
    "voip line count": "VoIP Line Count",
    "cru %": "CRU %",
    "abp %": "ABP %",
    "byod %": "BYOD %",
    "activation rate (31-60 day)": "Activation Rate (31–60 Day)",
    "activation 31-60": "Activation Rate (31–60 Day)",
    "0-30 day churn rate": "0–30 Day Churn Rate",
    "0-30 churn": "0–30 Day Churn Rate",
    "national avg headcount": "National AVG Headcount",
    "national sales per rep": "National Sales per Rep",
}
# labels whose goal cell (col B) we also carry across
_GOAL_LABELS = ["Head Count  ✎", "Total Apps", "Sales per Rep"]

_WEEKS_TO_COPY = 4


def _norm(label):
    s = str(label or "")
    s = s.replace("✎", "").replace("✎", "")          # pencil glyph
    s = s.replace("–", "-").replace("—", "-")   # en/em dash -> hyphen
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def collect(S, today=None, log=print):
    """-> (values, goals) for the Campaign Log upsert.

    S is an authorized Sheets session (funnel_board.auth). Reads the MT tab
    once with FORMATTED values — the display strings ("98%", "6.4") ARE our
    store format, so nothing is reparsed.
    """
    api = ("https://sheets.googleapis.com/v4/spreadsheets/"
           + CAPTAINSHIP_DASHBOARD)
    r = S.get(api + "/values/'%s'!A1:AZ70" % MT_TAB,
              params={"valueRenderOption": "FORMATTED_VALUE",
                      "dateTimeRenderOption": "FORMATTED_STRING"})
    if r.status_code != 200:
        raise RuntimeError("MT tab read failed: %s %s"
                           % (r.status_code, r.text[:300]))
    grid = r.json().get("values", [])
    if len(grid) < 4:
        raise RuntimeError("MT tab came back empty")

    def cell(rw, cl):
        row = grid[rw] if rw < len(grid) else []
        return row[cl] if cl < len(row) else ""

    # week blocks: row 3 (index 2) holds "WK m/d"; row 2 (index 1) the date —
    # formatted "m/d" with no year, so read that one row again as raw serials.
    # Block layout is [WK][Mon..Sun] starting at C, so WK columns are C, K, S…
    week_cols = []
    hdr = grid[2] if len(grid) > 2 else []
    for c, h in enumerate(hdr):
        if str(h).startswith("WK "):
            week_cols.append(c)
        if len(week_cols) >= _WEEKS_TO_COPY:
            break
    r2 = S.get(api + "/values/'%s'!2:2" % MT_TAB,
               params={"valueRenderOption": "UNFORMATTED_VALUE"})
    serials = (r2.json().get("values", [[]]) or [[]])[0] if r2.status_code == 200 else []
    weeks = []
    for c in week_cols:
        sv = serials[c] if c < len(serials) else None
        if not isinstance(sv, (int, float)):
            log("  [skip-week] col %d has no date serial (%r)" % (c, sv))
            continue
        d = _dt.date(1899, 12, 30) + _dt.timedelta(days=int(sv))
        weeks.append((c, d.isoformat()))
    if not weeks:
        raise RuntimeError("no week columns recognized on %s" % MT_TAB)

    slots = L.slots_by_label("b2b_att")
    values, goals, matched = [], [], set()
    for rw in range(len(grid)):
        ours = _MT_TO_OURS.get(_norm(cell(rw, 0)))
        if not ours or ours in matched or ours not in slots:
            continue
        matched.add(ours)
        s = slots[ours]
        for c, week_iso in weeks:
            v = str(cell(rw, c)).strip()
            if v != "":
                values.append((MANAGER, week_iso, s, v))
        if ours in _GOAL_LABELS:
            gv = str(cell(rw, 1)).strip()
            if gv != "":
                goals.append((MANAGER, s, gv))
    missing = set(_MT_TO_OURS.values()) - matched
    if missing:
        log("  [b2b] labels not found on MT tab (layout drift?): %s"
            % ", ".join(sorted(missing)))
    log("  [b2b] %d values (%d weeks), %d goals"
        % (len(values), len(weeks), len(goals)))
    return values, goals
