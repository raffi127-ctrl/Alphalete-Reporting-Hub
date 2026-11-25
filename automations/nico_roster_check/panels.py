"""The three check panels on Nico's newest WE tab (Carlos 2026-11-24: "we need
to have the same thing built out for Nico. Same thing with the first and second
week paycheck stuff that we do").

Same rules as the Vantura commission sheet (Payroll.gs _commissionExtras):
  * ACTIVE REPS - NO REVENUE: Active on the Roll Call (campaign Verizon, no
    Date Gone, not a New Start), on the Verizon Sales Board past the 2nd week
    (the 3rd week is the first paycheck), and no Brought In on this WE tab.
    The owner is never listed.
  * REVENUE - NOT ACTIVE: Brought In on this WE tab, but the person's Roll Call
    row says Terminated or has a Date Gone. With the amount.
  * FIRST & SECOND WEEK PAYCHECKS: Field Status 3rd Wk (first check, orange) or
    4th Wk (second check, green) on the Verizon Sales Board, not gone. Orders
    and apps off the Verizon Order Log (apps = Port lines, cancelled out, dated
    through the Sunday before payday). Training bonuses = the 'Training Bonus'
    lines on EARLIER WE tabs.

Sits in A:D under everything else on the tab (below OWED TO NICO). Values only,
no merges, no formulas; nothing above it is touched. A rerun clears its own old
block and writes it again, so a rebuilt tab gets it back on the next run.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.vantura_payroll.cs_tidy import (
    BONUS_HDR, FIRST_SECOND, NO_REV, REV_NOT, _MED, _NONE, _rng, bonus_numbers,
    canon, name_match, order_counts)

OWNER_WORD = "murrugarra"
ORANGE = {"red": 0.9882, "green": 0.8980, "blue": 0.8039}
GREEN = {"red": 0.8510, "green": 0.9176, "blue": 0.8275}
YELLOW = {"red": 1.0, "green": 0.9490, "blue": 0.8}


def roll_call_people(vals, aliases=None, campaign: str = "VERIZON") -> Dict[str, dict]:
    """{lower name: {...}}, one row per person. A name can sit on the Roll Call
    more than once (Jayden: an old AT&T Terminated row above the live Verizon
    one; Giovanni: an undated Terminated row above his Active one, 11/24), so
    this campaign's rows beat other campaigns', a live Active row beats a
    Terminated one, and otherwise the top (newest) row wins."""
    best: Dict[str, tuple] = {}
    for r in vals[2:]:
        r = list(r) + [""] * (14 - len(r))
        name = str(r[4]).strip()
        if not name:
            continue
        st, camp, gone = str(r[1]).strip().lower(), str(r[3]).strip().upper(), str(r[13]).strip()
        p = {"name": name, "campaign": camp,
             "active": st == "active" and not gone,
             "departed": st == "terminated" or bool(gone),
             "new_start": "new" in st, "gone": gone}
        rank = (camp == campaign, p["active"] or (p["new_start"] and not gone))
        k = name.lower()
        if k not in best or rank > best[k][0]:
            best[k] = (rank, p)
    return {k: v[1] for k, v in best.items()}


def person_for(name, people: Dict[str, dict], aliases=None, campaign: str = "VERIZON"):
    """Roll Call person for a payroll/board name: exact first, then the same
    campaign, then anyone."""
    k = canon(name, aliases or {}).lower()
    if k in people:
        return people[k]
    pool = list(people.values())
    for group in ([p for p in pool if p["campaign"] == campaign], pool):
        hits = [p for p in group if name_match(name, p["name"], aliases)]
        if hits:
            return hits[0]
    return None


def board_field_weeks(vals) -> Dict[str, str]:
    """{board name: 'Field Status'} for the rep rows of the Verizon board."""
    hdr = None
    out = {}
    for r in vals:
        cells = [str(c).strip() for c in r]
        if hdr is None:
            if "REP" in cells and "Field Status" in cells:
                hdr = {"name": cells.index("REP"), "fw": cells.index("Field Status"),
                       "num": 0}
            continue
        name = cells[hdr["name"]] if len(cells) > hdr["name"] else ""
        if not cells or not cells[0].isdigit():
            if out:
                break               # the first row without a # ends the rep list
            continue
        if name:
            out[name] = cells[hdr["fw"]] if len(cells) > hdr["fw"] else ""
    return out


def tab_reps(grid) -> Dict[str, float]:
    """{rep: brought in} off a WE tab's summary block."""
    out = {}
    for r in grid[3:]:
        n = str(r[0]).strip() if r else ""
        if not n:
            continue
        if n.upper() == "TOTAL":
            break
        t = str(r[1] if len(r) > 1 else "").replace("$", "").replace(",", "").strip()
        neg = t.startswith("-") or t.startswith("(")
        try:
            v = float(t.strip("()-") or 0)
        except ValueError:
            v = 0.0
        out[n] = -v if neg else v
    return out


def itemized_columns(grid) -> tuple:
    """(rep column, description column) of a WE tab's itemized block, found by
    its 'REP Name' / 'Description' header, so a column added left of it (the
    spacer Carlos asked Nico for, 11/24) does not matter. Old layout: G and J."""
    for r in grid:
        cells = [str(c).strip().lower() for c in r]
        if "rep name" in cells:
            rep = cells.index("rep name")
            desc = [k for k, c in enumerate(cells) if k > rep and c == "description"]
            return rep, (desc[0] if desc else rep + 3)
    return 6, 9


def tab_training_bonuses(grids: List[list], names, aliases=None) -> Dict[str, str]:
    """Training bonus numbers named in the itemized lines of the given
    (earlier) WE tabs."""
    got = {n: {} for n in names}
    for g in grids:
        cr, cd = itemized_columns(g)
        for r in g:
            r = list(r) + [""] * (cd + 1 - len(r))
            rep, desc = str(r[cr]).strip(), str(r[cd]).strip()
            if not rep or not desc.lower().startswith("training bonus"):
                continue
            for n in names:
                if name_match(n, rep, aliases):
                    for k, v in bonus_numbers(desc).items():
                        if got[n].get(k) != "full":
                            got[n][k] = v
    out = {}
    for n, g in got.items():
        bits = [f"#{k}" + (" (partial)" if g[k] == "partial" else "") for k in (1, 2) if k in g]
        if 0 in g and 1 not in g:
            bits.insert(0, "#1" if 2 in g else "Yes (no # noted)")
        out[n] = " and ".join(bits) or "None"
    return out


def build(week: dt.date, reps: Dict[str, float], people, fieldwk, order_vals,
          earlier_grids, aliases=None) -> dict:
    """{'norev': [...], 'revnot': [(name, amount)], 'fs': [(name, wk, orders, apps, bonus)]}"""
    al = aliases or {}

    def fw(name):
        for b, w in fieldwk.items():
            if name_match(name, b, al):
                return w.lower()
        return ""

    paid = [n for n, v in reps.items() if v > 0]
    norev = []
    for p in people.values():
        if p["campaign"] != "VERIZON" or not p["active"] or p["departed"] or p["new_start"]:
            continue
        if OWNER_WORD in p["name"].lower():
            continue
        w = fw(p["name"])
        if not w or w.startswith("1st") or w.startswith("2nd"):
            continue
        if not any(name_match(p["name"], n, al) for n in paid):
            norev.append(p["name"])
    revnot = []
    for n in paid:
        p = person_for(n, people, al)
        if p and p["departed"]:
            revnot.append((n, reps[n]))
    fs = []
    for b, w in fieldwk.items():
        wk = 3 if w.lower().startswith("3rd") else 4 if w.lower().startswith("4th") else 0
        p = person_for(b, people, al)
        if not wk or (p and p["departed"]):
            continue
        fs.append((b, wk))
    fs.sort(key=lambda x: (x[1], x[0]))
    names = [b for b, _ in fs]
    through = week - dt.timedelta(days=6)         # WE is a Saturday; payday is the Friday before it
    counts = order_counts(order_vals, names, through, al, order_col="order #") if names else {}
    bons = tab_training_bonuses(earlier_grids, names, al)
    return {"norev": sorted(norev), "revnot": sorted(revnot),
            "fs": [(b, wk, *counts[b], bons[b]) for b, wk in fs]}


def rows_for(panels: dict) -> List[list]:
    norev = panels["norev"] or ["None"]
    revnot = panels["revnot"] or [("None", "")]
    rows = [[NO_REV, "", REV_NOT, ""]]
    for i in range(max(len(norev), len(revnot))):
        left = norev[i] if i < len(norev) else ""
        rn = revnot[i] if i < len(revnot) else ("", "")
        rows.append([left, "", rn[0], rn[1]])
    rows += [["", "", "", ""], ["", "", "", ""]]
    rows.append([FIRST_SECOND, "", "", ""])
    rows.append(["Rep", "Order Count", "Total Apps", BONUS_HDR])
    for b, _wk, orders, apps, bon in (panels["fs"] or [("None", 0, "", "", "")]):
        rows.append([b, orders, apps, bon])
    return rows


def old_block(grid):
    """(first, last) 0-based rows of a block written by an earlier run, or None."""
    a = [str(r[0]).strip() if r else "" for r in grid]
    if NO_REV not in a:
        return None
    s = a.index(NO_REV)
    if FIRST_SECOND not in a[s:]:
        return (s, s)
    e = s + a[s:].index(FIRST_SECOND) + 1
    while e + 1 < len(a) and a[e + 1]:
        e += 1
    return (s, e)


def format_requests(sid: int, start: int, panels: dict, row_count: int) -> list:
    n1, n2 = max(len(panels["norev"]), 1), max(len(panels["revnot"]), 1)
    fs0 = start + 1 + max(n1, n2) + 2
    nf = max(len(panels["fs"]), 1)

    def box(r0, r1, c0, c1):
        return {"updateBorders": {"range": _rng(sid, r0, r1, c0, c1), "top": _MED, "bottom": _MED,
                                  "left": _MED, "right": _MED, "innerHorizontal": _MED}}

    def fmt(r0, r1, c0, c1, f, fields):
        return {"repeatCell": {"range": _rng(sid, r0, r1, c0, c1), "cell": {"userEnteredFormat": f},
                               "fields": "userEnteredFormat(" + fields + ")"}}
    white = {"red": 1, "green": 1, "blue": 1}
    reqs = [
        {"updateBorders": {"range": _rng(sid, start - 1, row_count, 0, 4), "bottom": _NONE, "left": _NONE,
                           "right": _NONE, "innerHorizontal": _NONE, "innerVertical": _NONE}},
        fmt(start, fs0 + 2 + nf, 0, 4,
            {"backgroundColor": white, "horizontalAlignment": "CENTER",
             "textFormat": {"bold": False, "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
             "numberFormat": {"type": "TEXT"}},
            "backgroundColor,horizontalAlignment,textFormat.bold,textFormat.foregroundColor,numberFormat"),
        fmt(start, start + 1, 0, 4, {"textFormat": {"bold": True}}, "textFormat.bold"),
        fmt(fs0, fs0 + 2, 0, 4, {"textFormat": {"bold": True}}, "textFormat.bold"),
        fmt(fs0, fs0 + 1, 0, 1, {"horizontalAlignment": "LEFT"}, "horizontalAlignment"),
        fmt(start + 1, start + 1 + n2, 3, 4, {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}},
            "numberFormat"),
        fmt(fs0 + 2, fs0 + 2 + nf, 1, 3, {"numberFormat": {"type": "NUMBER", "pattern": "0"}}, "numberFormat"),
        box(start, start + 1 + n1, 0, 1), box(start, start + 1 + n2, 2, 4), box(fs0, fs0 + 2 + nf, 0, 4),
    ]
    if panels["revnot"]:
        reqs.append(fmt(start + 1, start + 1 + n2, 2, 4, {"backgroundColor": YELLOW}, "backgroundColor"))
    for i, row in enumerate(panels["fs"]):
        reqs.append(fmt(fs0 + 2 + i, fs0 + 3 + i, 0, 4,
                        {"backgroundColor": ORANGE if row[1] == 3 else GREEN}, "backgroundColor"))
    return reqs


def run(write: bool, log) -> dict:
    from automations.nico_roster_check.run import MASTER_ID, NICO_ID, _week_key
    from automations.recruiting_report import fill as _fill
    from automations.vantura_payroll.cs_tidy import _alias_map
    master, book = _fill.open_by_key(MASTER_ID), _fill.open_by_key(NICO_ID)
    tabs = sorted((w for w in book.worksheets() if _week_key(w.title)), key=lambda w: _week_key(w.title))
    if not tabs:
        raise SystemExit("no WE tabs found on Nico's book")
    ws = tabs[-1]
    y, mo, d = _week_key(ws.title)
    week = dt.date(y, mo, d)
    grid = ws.get("A1:T" + str(ws.row_count))
    al = _alias_map(master)
    panels = build(
        week, tab_reps(grid), roll_call_people(master.worksheet("Roll Call").get_all_values()),
        board_field_weeks(master.worksheet("Verizon Sales Board").get("A1:T80")),
        master.worksheet("Verizon Order Log").get_all_values(),
        [w.get("A1:T" + str(w.row_count)) for w in tabs[:-1]], al)
    log(f"panels for {ws.title}: no revenue {panels['norev']}; revenue-not-active {panels['revnot']}; "
        f"first/second {panels['fs']}")
    rows = rows_for(panels)
    old = old_block(grid)
    keep = [i for i, r in enumerate(grid)
            if any(str(c).strip() for c in r[:6]) and not (old and old[0] <= i <= old[1])]
    start = max(keep) + 3                      # 0-based; two blank rows under the last content
    log(f"block goes to A{start + 1}:D{start + len(rows)} (old block {old})")
    if not write:
        log("dry-run -- nothing written")
        return panels
    if start + len(rows) > ws.row_count:
        ws.add_rows(start + len(rows) - ws.row_count + 5)
    if old:
        ws.batch_clear([f"A{old[0] + 1}:D{old[1] + 1}"])
        book.batch_update({"requests": [{"repeatCell": {
            "range": _rng(ws.id, old[0], old[1] + 1, 0, 4),
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                           "textFormat": {"bold": False}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}}]})
    book.batch_update({"requests": format_requests(ws.id, start, panels, ws.row_count)})
    ws.update(range_name=f"A{start + 1}:D{start + len(rows)}", values=rows, value_input_option="RAW")
    log(f"wrote the three panels on {ws.title}")
    return panels
