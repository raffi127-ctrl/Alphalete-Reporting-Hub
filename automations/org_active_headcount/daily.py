"""Org Active Headcount — the DAILY run on the 'Org Active Headcount' tab.

Eve, 2026-09-13: "armá la corrida diaria automática ... mayormente necesitás los
datos de los trackers que posteás en la mañana", and "el roleo de esta tabla se
hace los martes también y se carga ese mismo día la info del lunes nuevo ...
igual que los otros reportes con estructura parecida" (ORG Sales Board, Country
Sales Board, All Campaigns Units).

ONE RUN, EVERY DAY, TWO STEPS — the same shape as those boards:
  1. ROLL, only when the tab's week is behind the reporting week (that first
     happens on TUESDAY: `org_sales_board.week` keeps Monday on the week that
     just closed). Their roll code cannot be pointed here — it looks for labels
     this tab renamed and would overwrite Eve's same-day delta formulas — so the
     same steps are re-done here, found by label:
       snapshot -> ongoing WE columns shift -> daily K/L freeze -> delta box
       'Last week' <- this week -> clear days + new day numbers -> insert the
       new 'WE M.D' history row -> re-point the summary's Last Week / 4 Week AVG.
  2. FILL every completed day of the reporting week whose cells are still empty
     (normally yesterday; on Tuesday, Monday).

WHERE EACH DAY'S NUMBER COMES FROM (a tracker posted on day D shows D-1):
  - Fiber / NDS / B2B / BOX: the Country Tracker PNGs of the NEXT day's thread,
    column Rep Count ('Total Rep Count' on BOX, joined to its owner by
    ELE+Gas = Grand Total). Fiber and B2B are read two ways; they must agree,
    or the one that fits yesterday's number wins, or the day is '-'.
    An ICD missing from an image that WAS read is 0 (Eve: "si no están = 0");
    BOX is the exception (a failed join is not a zero) -> '-'.
  - Carlos Hidalgo: B2B + BOX (he is on both; '-' if either is '-').
  - Retail NL: SARA Plus, distinct reps Monday..day (the Monday focus report's
    own count, retail_daily). Not in SARA = 0.
  - Retail JE: 'Productive Rep Count' of the reporting week — it only knows
    "through yesterday", so it is written only for yesterday; an older empty
    JE day is '-'.

RULES THAT SHAPE THE WRITE (Eve 2026-09-13):
  - a day that could not be collected CARRIES the ICD's last number (Eve
    2026-09-24: "si no encuentra en el tracker tiene que llenar con el mismo
    último valor disponible") — the day before, or LAST WEEK'S on a Monday.
    '-' is left only when there is no earlier number at all, never a 0 that
    looks real. A source that simply has not posted yet leaves the cell EMPTY
    (a later run fills it) — '-' is only for "tried and could not".
  - only empty cells are written; nothing a person typed is overwritten.
  - the delta box keeps a BLANK (not '-') for a missing last-week day, because
    '-' would move its %.

    python -m automations.org_active_headcount.daily            # dry run
    python -m automations.org_active_headcount.daily --apply
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
# The production tab — built as 'Org Active Headcount Test 2' and renamed
# 'Org Active Headcount' by Eve on 2026-09-13 (the old 'Org Active Headcount
# Board', gid 1937067034, is hidden). Opened by GID so the next rename cannot
# silently point the run at nothing; the name is only the fallback + log label.
TAB = "Org Active Headcount"
TAB_GID = 1529537631
# A duplicate of the live tab, for trying a change before it touches the real
# one (Eve 2026-09-20, the J/K/L redesign). Opened BY NAME: it is made by hand
# with 'Duplicate', so its gid is different on every copy. It does not exist
# unless somebody duplicated the tab under exactly this name.
SANDBOX_TAB = "Org Active Headcount SANDBOX"
BACKUP_TAB = "backup_pre_rollover_headcount"


def open_tab(sandbox: bool = False):
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    if sandbox:
        try:
            return next(w for w in sh.worksheets() if w.title.strip() == SANDBOX_TAB)
        except StopIteration:
            raise SystemExit(f"no hay tab {SANDBOX_TAB!r} — duplicá {TAB!r} con ese nombre")
    try:
        return sh.get_worksheet_by_id(TAB_GID)
    except Exception:                                              # noqa: BLE001
        return next(w for w in sh.worksheets() if w.title.strip() == TAB)
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WE_LONG = re.compile(r"^WE\s+(\d{2})\.(\d{2})$", re.I)
WE_ANY = re.compile(r"^WE\s+(\d{1,2})\.(\d{1,2})$", re.I)

# daily block 'Campaign' value -> source
CAMPAIGN_SOURCE = {"fiber": "att_country", "nds": "nds", "b2b": "b2b_att_country",
                   "box": "b2b_box", "je": "je", "retail nl": "retail"}
# ICDs that run on TWO campaigns and are ONE row on the daily block
DUAL = {"carlos hidalgo": ("b2b_att_country", "b2b_box")}


# ------------------------------------------------------------------ layout --

def _c(g, r, k) -> str:
    if r < 1 or r > len(g):
        return ""
    row = g[r - 1]
    return str(row[k - 1]).strip() if 0 < k <= len(row) else ""


def _num(s):
    t = str(s).replace(",", "").strip()
    return int(float(t)) if re.fullmatch(r"-?\d+(\.\d+)?", t) else None


def A(k: int) -> str:
    s = ""
    while k > 0:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def _last_number(vals) -> str:
    """The last of these cells that actually holds a number — the week's figure
    when the days after it have not happened (or came in as '-')."""
    for v in reversed(list(vals)):
        if _num(v) is not None:
            return str(v).strip()
    return ""


def carried(g, dl: dict, r: int, day_idx: int) -> Optional[int]:
    """The number an ICD's row carries INTO day `day_idx` (0 = Monday): the last
    earlier day of the week with a number, else LAST WEEK'S (the closed week's
    final, hidden black-on-black), else None.

    Eve 2026-09-24: Brandon Stallkamp read 3 on Monday and '-' on Tuesday, and
    the '-' pulled his week down to nothing. A tracker that misses someone for a
    day is not a headcount of zero or of unknown — he still has his 3."""
    for k in reversed(dl["days"][:day_idx]):
        v = _num(_c(g, r, k))
        if v is not None:
            return v
    return _num(_c(g, r, dl["lastw"])) if dl.get("lastw") else None


def campaign_by_name(g) -> Dict[str, str]:
    """{icd: campaign} read off the 'Campaign' helper column, WHEREVER it sits.

    It used to be one column right of the daily block's week totals, and
    `find_daily` took it by that position. Eve moved it out to the delta box on
    2026-09-20 while tidying the tab — and every ICD silently lost the tracker
    it reads: `plan_day` went from 33 cells a day to 1, because only Carlos
    Hidalgo is matched by NAME (he is in DUAL). The run still exits 0, so
    nothing would have said the tab had stopped filling.

    Looked up by its own header, one block of names at a time, so moving the
    column again is a non-event."""
    for r in range(1, len(g) + 1):
        for k in range(1, len(g[r - 1]) + 1):
            if _c(g, r, k).lower() != "campaign":
                continue
            out: Dict[str, str] = {}
            rr = r + 1
            while rr <= len(g) and not _c(g, rr, 2):
                rr += 1
            while rr <= len(g) and _c(g, rr, 2):
                if _c(g, rr, k):
                    out.setdefault(_c(g, rr, 2).lower(), _c(g, rr, k).lower())
                rr += 1
            if out:
                return out
    return {}


def find_daily(g) -> dict:
    """The per-day block, found BY SHAPE: the row carrying all seven day names
    whose roster is closed by a col-A 'Totals' row.

    It used to anchor on the 'RUNNING WEEK TOTALS' header. Eve painted that
    column — and LAST WEEK'S / PREVIOUS WEEK'S — black on black on 2026-09-20 so
    the numbers stay in the tab without showing; a cell that reads as empty is a
    cell somebody eventually clears, and that would have taken the whole block
    with it. The col-A title is no anchor either: it has already been renamed
    twice ('All Units' -> 'All Campaigns HC'). The day names and the 'Totals'
    row are the two things that cannot go without the block itself going.

    The three blocks above and below also carry seven day names — the Headcount
    Summary, 'Current vs Prior Weeks' and the delta box — and are rejected
    because none of them is closed by a col-A 'Totals' row."""
    last_err: Optional[Exception] = None
    for hdr in range(1, len(g) + 1):
        cols: Dict[str, int] = {}
        for k in range(1, len(g[hdr - 1]) + 1):
            cols.setdefault(_c(g, hdr, k).lower(), k)
        if not all(d in cols for d in DAYS):
            continue
        try:
            return _daily_block(g, hdr, cols, campaign_by_name(g))
        except ValueError as e:
            last_err = e
    raise ValueError(f"daily block: no day-header row closed by a 'Totals' row "
                     f"({last_err})")


def _daily_block(g, hdr: int, cols: Dict[str, int],
                 camp_map: Optional[Dict[str, str]] = None) -> dict:
    def opt(prefix: str) -> Optional[int]:
        return next((k for l, k in cols.items() if l.startswith(prefix)), None)
    out = {"hdr": hdr, "daynum": hdr + 1,
           "days": [cols[d] for d in DAYS],
           # OPTIONAL: present on the live tab (hidden behind black-on-black
           # text, still read here), None if they are ever really taken off.
           "run": opt("running week"),
           "lastw": opt("last week"),
           "prevw": opt("previous week"),
           "camp": cols.get("campaign")}
    r = hdr + 1
    while r <= len(g) and not _c(g, r, 2):
        r += 1
    rows = []
    while r <= len(g) and _c(g, r, 2) and _c(g, r, 1).lower() != "totals":
        name = _c(g, r, 2)
        camp = _c(g, r, out["camp"]).lower() if out["camp"] else ""
        rows.append((r, name, camp or (camp_map or {}).get(name.lower(), "")))
        r += 1
    if _c(g, r, 1).lower() != "totals":
        raise ValueError(f"daily block: no 'Totals' row after the ICDs (row {r})")
    out["rows"], out["totals"] = rows, r
    return out


def find_stack(g, totals_row: int) -> List[int]:
    out, r = [], totals_row + 1
    while r <= len(g) and WE_ANY.match(_c(g, r, 1)):
        out.append(r)
        r += 1
    return out


def find_delta(g) -> dict:
    """The delta box, by its col-A title plus the 'This week' sub-header under
    it. The col-C cell used to be the anchor ('Total for week'); Eve turned it
    into a live 'by <last day filled>' caption on 2026-09-20, and an exact-match
    anchor on a cell whose whole job is to change its text is a trap — it took
    the Tuesday roll down with a bare StopIteration."""
    dh = next(r for r in range(1, len(g))
              if "ongoing headcount" in _c(g, r, 1).lower()
              and any(_c(g, r + 1, k).lower() == "this week"
                      for k in range(1, len(g[r]) + 1)))
    sub = dh + 1
    this_c, last_c = [], []
    for d in DAYS:
        k = next(k for k in range(1, len(g[dh - 1]) + 1) if _c(g, dh, k).lower() == d)
        if not (_c(g, sub, k).lower() == "this week" and _c(g, sub, k + 1).lower() == "last week"):
            raise ValueError(f"delta box: '{d}' is not This week / Last week")
        this_c.append(k)
        last_c.append(k + 1)
    r, rows = sub + 1, []
    while r <= len(g) and _c(g, r, 2):
        rows.append((r, _c(g, r, 2)))
        r += 1
    return {"hdr": dh, "sub": sub, "this": this_c, "last": last_c, "rows": rows, "totals": r}


def find_ongoing(g) -> dict:
    hdr = next(r for r in range(1, len(g) + 1)
               if "ongoing headcount" in _c(g, r, 1).lower() and WE_LONG.match(_c(g, r, 3)))
    wcols, k = [], 3
    while WE_LONG.match(_c(g, hdr, k)):
        wcols.append((k, _c(g, hdr, k)))
        k += 1
    r = hdr + 1
    while r <= len(g) and not _c(g, r, 2):
        r += 1
    rows = []
    while r <= len(g) and _c(g, r, 2):
        rows.append(r)
        r += 1
    if _c(g, r, 1).lower() != "totals":
        raise ValueError(f"ongoing block: no 'TOTALS' row after the ICDs (row {r})")
    return {"hdr": hdr, "wcols": wcols, "rows": rows, "totals": r}


def find_summary(g, below: int) -> dict:
    labels = {" ".join(_c(g, r, 2).lower().split()): r for r in range(1, below)}
    hdr = next(r for k, r in labels.items() if k.startswith("all campaigns"))
    hk = {_c(g, hdr, k).lower(): k for k in range(3, 12)}
    return {"days": [hk[d] for d in DAYS],
            "last": next(r for k, r in labels.items() if k.startswith("hc (last week")),
            "avg": next(r for k, r in labels.items() if k.startswith("hc ( 4 week") or k.startswith("hc (4 week"))}


def board_sunday(g, today: dt.date) -> dt.date:
    og = find_ongoing(g)
    m = WE_LONG.match(og["wcols"][0][1])
    d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
    return d if d <= today + dt.timedelta(days=180) else d.replace(year=today.year - 1)


# ------------------------------------------------------------------- roll --

def plan_roll(V, F, closed: dt.date, new_sunday: dt.date) -> dict:
    """Everything the Tuesday roll writes, computed from the PRE-roll grid.
    Pure — no I/O. Returns {'values': [(a1, v)], 'clear': [range],
    'stack_top': row, 'stack_values': [...], 'last_col': col, 'summary': {...}}."""
    values: List[Tuple[str, object]] = []
    # 1 ongoing WE columns: shift C..last -> D..last+1 (ICD rows), new header in C
    og = find_ongoing(V)
    wc = og["wcols"]
    values.append((f"{A(wc[0][0])}{og['hdr']}", f"WE {new_sunday.month:02d}.{new_sunday.day:02d}"))
    for col, label in wc:
        values.append((f"{A(col + 1)}{og['hdr']}", label))
    for r in og["rows"]:
        for col, _ in reversed(wc):
            values.append((f"{A(col + 1)}{r}", _c(V, r, col)))
    new_last = wc[-1][0] + 1
    first, last = og["rows"][0], og["rows"][-1]
    if not _c(F, og["totals"], new_last):
        values.append((f"{A(new_last)}{og['totals']}", f"=SUM({A(new_last)}{first}:{A(new_last)}{last})"))
    # 2 daily K/L freeze: L <- K, K <- J (ICD rows + Totals row). Skipped if the
    # columns are ever taken off the tab — step 1 above is what actually saves
    # the closed week, into the Ongoing block's new WE column.
    dl = find_daily(V)
    if dl["run"] and dl["lastw"] and dl["prevw"]:
        for r in [x[0] for x in dl["rows"]] + [dl["totals"]]:
            values.append((f"{A(dl['prevw'])}{r}", _c(V, r, dl["lastw"])))
            values.append((f"{A(dl['lastw'])}{r}", _c(V, r, dl["run"])))
    # 3 delta box 'Last week' <- this week's daily values. A day that is not a
    # number carries the row's last one (Eve 2026-09-24: Carlos Hidalgo and
    # Brandon Stallkamp had '-' on Tue 9/15, so 'by Tuesday 9/22' showed them
    # with NO last week at all). Blank only when there is no number to carry.
    dx = find_delta(V)
    by_name = {name.lower(): r for r, name, _ in dl["rows"]}
    for r, name in dx["rows"]:
        src = by_name.get(name.lower())
        for i, k in enumerate(dx["last"]):
            v = _num(_c(V, src, dl["days"][i])) if src else None
            if src and v is None:
                v = carried(V, dl, src, i)
            values.append((f"{A(k)}{r}", "" if v is None else v))
    for k in dx["last"]:
        if not _c(F, dx["totals"], k).upper().startswith("=SUM"):
            values.append((f"{A(k)}{dx['totals']}",
                           f"=SUM({A(k)}{dx['rows'][0][0]}:{A(k)}{dx['rows'][-1][0]})"))
    # 4 the closed week's daily totals, read BEFORE the clear. The trailing
    # figure comes out of RUNNING WEEK TOTALS; without that column the history
    # row ends on Sunday, because the week's final is also in the Ongoing
    # block's TOTALS row under that same week (WE 9.13 -> 548 in both).
    day_vals = [_c(V, dl["totals"], k) for k in dl["days"]]
    stack_values = day_vals + ([_c(V, dl["totals"], dl["run"])] if dl["run"] else [])
    # 5 clear the days + the new week's day numbers
    clear = [f"{A(dl['days'][0])}{dl['rows'][0][0]}:{A(dl['days'][-1])}{dl['rows'][-1][0]}"]
    monday = new_sunday - dt.timedelta(days=6)
    for i, k in enumerate(dl["days"]):
        values.append((f"{A(k)}{dl['daynum']}", (monday + dt.timedelta(days=i)).day))
    stack = find_stack(V, dl["totals"])
    return {"values": values, "clear": clear,
            "stack_top": stack[0] if stack else dl["totals"] + 1,
            "stack_label": f"WE {closed.month}.{closed.day}",
            "stack_values": stack_values,
            "last_col": dl["run"] or dl["days"][-1],
            "summary": find_summary(V, dl["hdr"]),
            "stack_already": bool(stack) and _c(V, stack[0], 1) == f"WE {closed.month}.{closed.day}"}


def apply_roll(ws, V, F, closed, new_sunday, logfn=print) -> None:
    from automations.recruiting_report.fill import _retry
    from automations.org_sales_board.rollover import we_row_format_requests
    p = plan_roll(V, F, closed, new_sunday)
    sh = ws.spreadsheet
    # 0 snapshot — must succeed before any write
    try:
        bws = sh.worksheet(BACKUP_TAB)
    except Exception:                                              # noqa: BLE001
        bws = sh.add_worksheet(title=BACKUP_TAB, rows=len(V) + 5, cols=40)
    width = max(len(r) for r in V)
    bws.resize(rows=len(V) + 5, cols=max(width, 1))
    _retry(bws.update, range_name="A1", values=[r + [""] * (width - len(r)) for r in V],
           value_input_option="RAW")
    logfn(f"  roll 0/5 snapshot -> {BACKUP_TAB!r}")
    _retry(ws.batch_update, [{"range": a, "values": [[v]]} for a, v in p["values"]],
           value_input_option="USER_ENTERED")
    logfn(f"  roll 1-3/5 ongoing WE columns, K/L freeze, delta 'Last week': {len(p['values'])} cell(s)")
    _retry(ws.batch_clear, p["clear"])
    logfn(f"  roll 4/5 cleared {p['clear']} and wrote the new day numbers")
    if p["stack_already"]:
        logfn(f"  roll 5/5 history row {p['stack_label']} already there — not inserted twice")
        return
    top = p["stack_top"]
    _retry(sh.batch_update, {"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "ROWS", "startIndex": top - 1, "endIndex": top},
        "inheritFromBefore": False}}]})
    row = [p["stack_label"], ""] + p["stack_values"]
    _retry(ws.update, range_name=f"A{top}", values=[row], value_input_option="USER_ENTERED")
    try:
        _retry(sh.batch_update, {"requests": we_row_format_requests(ws.id, top, p["last_col"])})
    except Exception as e:                                         # noqa: BLE001
        logfn(f"  (format of the new history row skipped: {type(e).__name__})")
    s = p["summary"]
    formulas = []
    for k in s["days"]:
        formulas.append({"range": f"{A(k)}{s['last']}", "values": [[f"={A(k)}${top}"]]})
        formulas.append({"range": f"{A(k)}{s['avg']}",
                         "values": [[f"=AVERAGE({A(k)}${top}:{A(k)}${top + 3})"]]})
    _retry(ws.batch_update, formulas, value_input_option="USER_ENTERED")
    logfn(f"  roll 5/5 inserted history row {p['stack_label']} at row {top}; "
          f"HC (Last Week) / 4 Week AVG now read rows {top}..{top + 3}")


# ---------------------------------------------------------------- sources --

def _read_bands(png, tid) -> dict:
    """The whole-band reading of a strip-read tracker — the SECOND opinion."""
    import json
    from automations.org_active_headcount import tracker_readings as tr
    cached = png.with_suffix(".json")
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    bands = tr._bands(png)
    data = tr._ask(bands, tr._PROMPT.format(n=len(bands), col=tr.COLUMN.get(tid, "Rep Count")),
                   tr._SCHEMA)
    cached.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def tracker_readings_for(post: dt.date, logfn=print) -> Dict[str, Optional[dict]]:
    """{tid: {'A': rows, 'B': rows|None} | None if that board is not posted}."""
    from automations.org_active_headcount import tracker_readings as tr
    from automations.shared import slack_metrics_post as smp
    from automations.tableau_screenshots.slack_post import ORG_CHANNELS
    from automations.owner_chat_texts.slack_fetch import _download
    client, token = smp._client(), smp._load_token()
    thread, files = tr._latest_files(client, ORG_CHANNELS["alphalete"][0], post)
    out: Dict[str, Optional[dict]] = {}
    for tid in tr.TRACKERS:
        if tid not in files:
            logfn(f"    {tid}: no image in the {post} thread")
            out[tid] = None
            continue
        # Cached PER SLACK FILE, not per day (2026-09-18): the 4:50 B2B Box
        # Tracker went out with the day before's numbers and was re-posted at
        # 8:55 in an UPDATED thread. A per-day cache kept the 08:26 read of the
        # stale picture, so every later run re-read Wednesday as Thursday.
        fid = files[tid]["file"].get("id") or "nofid"
        png = tr.CACHE / post.isoformat() / f"{tid}-{fid}.png"
        if not png.exists():
            _download(files[tid]["file"]["url_private"], token, png)
        a = tr.read_image(png, tid).get("rows") or []
        b = (_read_bands(png, tid).get("rows") or []) if tid in tr.STRIPS else None
        out[tid] = {"A": a, "B": b}
    return out


def pick_tracker(icd: str, tid: str, reading: Optional[dict], prev) -> object:
    """One ICD's number off one tracker: int, '-' (tried, could not), or None
    (board not posted — leave the cell for a later run). Pure."""
    from automations.org_active_headcount import tracker_readings as tr
    if reading is None:
        return None

    def one(rows):
        hits = tr.match(icd, rows)
        if not hits:
            return "-" if tid == tr.BOX else 0
        nums = [h.get("rep_count") for h in hits if isinstance(h.get("rep_count"), int)]
        return nums[0] if nums else "-"
    a = one(reading["A"])
    if reading.get("B") is None:
        return a
    b = one(reading["B"])
    if a == b:
        return a
    cands = [x for x in (a, b) if isinstance(x, int)]
    if isinstance(prev, int):
        fits = sorted({x for x in cands if prev - 3 <= x <= prev + 25})
        if len(fits) == 1:
            return fits[0]
        # BOTH readings fit the window (2026-09-18: Muhammad Haque and Salik
        # Mallick went '-' on Wed/Thu this way). A week's count moves by a few
        # heads a day, so the reading nearer yesterday's wins; an exact tie in
        # distance is still '-'.
        if len(fits) > 1:
            by_gap = sorted(fits, key=lambda x: abs(x - prev))
            if abs(by_gap[0] - prev) < abs(by_gap[1] - prev):
                return by_gap[0]
    return "-"


def pick_dual(pick, srcs, prev) -> list:
    """One value per source for an ICD on TWO boards (Carlos: B2B + BOX). Pure.

    Yesterday's cell is the SUM, so it cannot break a tie on either board by
    itself — but yesterday's total minus today's reading of the OTHER board is
    that board's yesterday, near enough for pick_tracker's window. 9/13: B2B read
    6 (strips) against its band reading, BOX 14, Saturday 30 -> B2B ~16 -> the 6
    is thrown out. Before this every such tie was '-' (Carlos Thu 9/10, Sun 9/13)."""
    first = [pick(s, None) for s in srcs]
    if not isinstance(prev, int):
        return first
    out = []
    for i, s in enumerate(srcs):
        others = first[:i] + first[i + 1:]
        if first[i] == "-" and all(isinstance(x, int) for x in others):
            out.append(pick(s, prev - sum(others)))
        else:
            out.append(first[i])
    return out


def retail_values(day: dt.date, icds: List[str], logfn=print) -> Dict[str, object]:
    from automations.org_active_headcount import retail_daily as rd
    try:
        got = rd.day_counts(day, logfn=logfn)
    except Exception as e:                                         # noqa: BLE001
        logfn(f"    retail {day}: SARA failed ({type(e).__name__}: {e}) — left empty")
        return {}
    out = {}
    for icd in icds:
        hits = rd.owner_for(icd, list(got))
        out[icd] = sum(got[h] for h in hits) if hits else 0
    return out


def je_values(today: dt.date, icds: List[str], logfn=print) -> Dict[str, object]:
    """Productive Rep Count of the reporting week, per board owner — always a
    FRESH download (a per-week cache would repeat day one's number all week)."""
    from automations.org_sales_board import je_pull
    from automations.org_sales_board.week import reporting_sunday
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.org_active_headcount import pull
    from automations.org_active_headcount import sources as src
    from automations.org_active_headcount.je_scorecard import OUT
    week_end = reporting_sunday(today)
    path = OUT / f"je_productive_WE{week_end:%Y%m%d}_read{dt.datetime.now():%Y%m%d-%H%M}.csv"
    try:
        download_crosstab_patchright(je_pull.CV_URL, pull.JE_WEEKLY_SHEET, path, verbose=False,
                                     pre_export=je_pull._drive_week_selection(
                                         je_pull._week_label(week_end), False))
        rows = pull._read_crosstab(path)
        ni, ci = pull._cols(rows[0], "ICD Name", pull.JE_HEADCOUNT_COL)
    except Exception as e:                                         # noqa: BLE001
        logfn(f"    JE: Weekly Metrics by ICD failed ({type(e).__name__}: {e}) — left empty")
        return {}
    by_norm = {src.norm(r[ni]): _num(r[ci]) for r in rows[1:] if len(r) > max(ni, ci)}
    return {icd: (by_norm.get(src.norm(src.source_name(icd)))
                  if by_norm.get(src.norm(src.source_name(icd))) is not None else "-")
            for icd in icds}


# ------------------------------------------------------------------- fill --

def plan_day(V, day: dt.date, today: dt.date, logfn=print,
             trackers=None, retail=None, je=None) -> List[Tuple[str, object]]:
    """[(a1, value)] for the EMPTY cells of `day`'s column. Sources are fetched
    only when an empty cell needs them (and can be injected for tests)."""
    dl = find_daily(V)
    col = dl["days"][day.weekday()]
    if _num(_c(V, dl["daynum"], col)) != day.day:
        raise ValueError(f"{day}: the day-number cell {A(col)}{dl['daynum']} says "
                         f"{_c(V, dl['daynum'], col)!r} — the tab is not on this week")
    i = day.weekday()
    # a '-' this run (or an older one) already wrote: no source to re-ask, the
    # day just takes the last number the row had.
    out = [(f"{A(col)}{r}", carried(V, dl, r, i)) for r, _, _ in dl["rows"]
           if _c(V, r, col) == "-" and carried(V, dl, r, i) is not None]
    empty = [(r, name, camp) for r, name, camp in dl["rows"] if _c(V, r, col) == ""]
    if not empty:
        return out
    need = {CAMPAIGN_SOURCE.get(camp) for _, _, camp in empty} | \
           {s for _, name, _ in empty for s in DUAL.get(name.lower(), ())}
    if trackers is None and need & {"att_country", "nds", "b2b_att_country", "b2b_box"}:
        trackers = tracker_readings_for(day + dt.timedelta(days=1), logfn=logfn)
    if retail is None and "retail" in need:
        retail = retail_values(day, [n for _, n, c in empty if CAMPAIGN_SOURCE.get(c) == "retail"], logfn)
    if je is None and "je" in need:
        je = (je_values(today, [n for _, n, c in empty if CAMPAIGN_SOURCE.get(c) == "je"], logfn)
              if day == today - dt.timedelta(days=1) else {})
    for r, name, camp in empty:
        prev = _num(_c(V, r, dl["days"][day.weekday() - 1])) if day.weekday() else None
        srcs = DUAL.get(name.lower()) or (CAMPAIGN_SOURCE.get(camp),)

        def pick(s, p, name=name):
            if s in ("att_country", "nds", "b2b_att_country", "b2b_box"):
                return pick_tracker(name, s, (trackers or {}).get(s), p)
            if s == "retail":
                return (retail or {}).get(name)
            if s == "je":
                return (je or {}).get(name, "-") if day == today - dt.timedelta(days=1) else "-"
            return None
        parts = pick_dual(pick, srcs, prev) if len(srcs) > 1 else [pick(srcs[0], prev)]
        if any(p is None for p in parts):
            continue                        # a source not there yet: a later run fills it
        v = "-" if any(p == "-" for p in parts) else sum(int(p) for p in parts)
        if v == "-" and carried(V, dl, r, i) is not None:
            v = carried(V, dl, r, i)
        out.append((f"{A(col)}{r}", v))
    return out


# ------------------------------------------------------------------- sort --

def _block_last_col(g, rows: List[int], floor: int) -> int:
    """The rightmost column any row of the block actually uses. The sort has to
    carry the WHOLE row — a helper column left outside the range stays put while
    the names move under it, which is how the Campaign column would come to
    point at the wrong ICD."""
    last = floor
    for r in rows:
        row = g[r - 1] if r <= len(g) else []
        for k in range(len(row), 0, -1):
            if str(row[k - 1]).strip():
                last = max(last, k)
                break
    return last


def sort_requests(sheet_id: int, g) -> List[dict]:
    """A `sortRange` for each of the three owner blocks: biggest current week
    first, ties by name. Eve 2026-09-20, after re-ordering them by hand:
    "acordate de con cada corrida ordenar de mayor a menor quien tiene numero
    mas grande".

    NEVER a value-write. The Ongoing box's column C is `=SUMIF(...)`, and the
    delta box's This week / Delta are formulas pointing at their own row;
    reading those and writing them back in a new order would store what they
    happen to DISPLAY, freezing every one of them on today's number — and
    nothing would look wrong afterwards, because a frozen value is the correct
    value for the moment it froze. That is how the ORG Sales Board's delta
    boxes sat frozen for a week (`org_sales_board/delta_sort.py` has the
    story). `sortRange` makes the SERVER move the cells and re-point the
    references, which a value-write cannot do.

    COLUMN A STAYS OUT: it is the rank gutter, so 1..N keeps counting down the
    page while the people move underneath it.

    Idempotent — a block already in order sorts to itself."""
    dl, og, dx = find_daily(g), find_ongoing(g), find_delta(g)
    # the daily block ranks on RUNNING WEEK TOTALS; with that column gone, on
    # the last day the Totals row actually has a number for.
    filled = sum(1 for k in dl["days"] if _num(_c(g, dl["totals"], k)) is not None)
    day_key = dl["days"][max(filled, 1) - 1]
    blocks = [
        (og["rows"], og["wcols"][0][0], og["wcols"][-1][0]),
        ([r for r, _, _ in dl["rows"]], dl["run"] or day_key,
         max(dl["days"][-1], dl["prevw"] or 0)),
        # the delta box ranks on its WEEK triplet (This week / Last week /
        # Delta), which is the one sitting immediately left of Monday's — three
        # columns over. Not matched by its caption: Eve renamed that header
        # from 'Total this week' to 'This week' on 2026-09-20.
        ([r for r, _ in dx["rows"]], dx["this"][0] - 3, dx["last"][-1] + 1),
    ]
    out = []
    for rows, key, floor in blocks:
        if not rows:
            continue
        out.append({"sortRange": {
            "range": {"sheetId": sheet_id,
                      "startRowIndex": rows[0] - 1, "endRowIndex": rows[-1],
                      "startColumnIndex": 1,          # col B — col A is the rank
                      "endColumnIndex": _block_last_col(g, rows, floor)},
            "sortSpecs": [{"dimensionIndex": key - 1, "sortOrder": "DESCENDING"},
                          {"dimensionIndex": 1, "sortOrder": "ASCENDING"}]}})
    return out


def run(apply_changes: bool = False, today: Optional[dt.date] = None,
        sandbox: bool = False, logfn=print) -> int:
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.org_sales_board.week import reporting_sunday, completed_days
    today = today or dt.date.today()
    ws = open_tab(sandbox)
    V = ws.get_all_values()
    F = ws.get_all_values(value_render_option="FORMULA")
    target = reporting_sunday(today)
    on = board_sunday(V, today)
    logfn(f"{ws.title}: tab is on WE {on}, reporting week WE {target} (today {today})")
    if on < target:
        closed = on
        if (target - on).days > 7:
            logfn(f"  ⚠ the tab is {(target - on).days // 7} weeks behind — rolling ONE week; "
                  "run again to roll the next")
            target = on + dt.timedelta(days=7)
        p = plan_roll(V, F, closed, target)
        logfn(f"  ROLL WE {closed} -> WE {target}: {len(p['values'])} cell(s), clear {p['clear']}, "
              f"history row {p['stack_label']} at {p['stack_top']}"
              + (" (already there)" if p["stack_already"] else ""))
        if not apply_changes:
            logfn("  dry run — not rolling, so the fill below is not planned "
                  "(it needs the rolled tab)")
            return 0
        apply_roll(ws, V, F, closed, target, logfn=logfn)
        V = ws.get_all_values()
    total = 0
    broken = []
    for day in completed_days(today):
        if day > today - dt.timedelta(days=1):
            continue
        try:
            ups = plan_day(V, day, today, logfn=logfn)
        except Exception as e:                                     # noqa: BLE001
            logfn(f"  {day}: NOT filled — {type(e).__name__}: {e}")
            broken.append(day)
            continue
        logfn(f"  {day:%a %m/%d}: {len(ups)} cell(s)" + ("" if ups else " (nothing empty)"))
        for a1, v in ups:
            logfn(f"      {a1:>5} <- {v}")
        if apply_changes and ups:
            _retry(ws.batch_update, [{"range": a, "values": [[v]]} for a, v in ups],
                   value_input_option="USER_ENTERED")
            V = ws.get_all_values()
        total += len(ups)
    logfn(f"{'wrote' if apply_changes else 'would write'} {total} day cell(s)")

    # LAST: the boxes rank on the numbers the fill just wrote.
    reqs = sort_requests(ws.id, V)
    logfn(f"{'sorting' if apply_changes else 'would sort'} {len(reqs)} box(es) "
          "by this week, descending")
    if apply_changes and reqs:
        _retry(ws.spreadsheet.batch_update, {"requests": reqs})
    # A day that could not be READ is a failure, not a quiet day (2026-09-24:
    # the tracker reader got "credit balance is too low" from the Anthropic API,
    # Wednesday stayed empty, the run exited 0 and nobody was told). Failing
    # here fires the orchestrator's alert AND holds the email, which
    # depends_on this run. A source that simply has not posted yet does not
    # land here — it leaves the cell empty without raising.
    if broken:
        logfn(f"FAILED: {', '.join(f'{d:%a %m/%d}' for d in broken)} could not be read")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="pretend today is this date")
    ap.add_argument("--sandbox", action="store_true",
                    help=f"write the {SANDBOX_TAB!r} copy instead of the live tab")
    a = ap.parse_args(argv)
    return run(apply_changes=a.apply, today=a.today, sandbox=a.sandbox)


if __name__ == "__main__":
    raise SystemExit(main())
