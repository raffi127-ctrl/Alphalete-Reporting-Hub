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
  - a day that could not be collected is '-', never blank and never a 0 that
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
BACKUP_TAB = "backup_pre_rollover_headcount"


def open_tab():
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
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


def find_daily(g) -> dict:
    """The per-day block, by its 'RUNNING WEEK TOTALS' header (its col-A title
    was renamed 'All Units' -> 'All Campaigns HC' on 2026-09-13)."""
    hdr = next(r for r in range(1, len(g) + 1)
               if any(str(x).strip().lower().startswith("running week") for x in g[r - 1]))
    cols: Dict[str, int] = {}
    for k in range(1, len(g[hdr - 1]) + 1):
        cols.setdefault(_c(g, hdr, k).lower(), k)
    out = {"hdr": hdr, "daynum": hdr + 1,
           "days": [cols[d] for d in DAYS],
           "run": next(k for l, k in cols.items() if l.startswith("running week")),
           "lastw": next(k for l, k in cols.items() if l.startswith("last week")),
           "prevw": next(k for l, k in cols.items() if l.startswith("previous week")),
           "camp": cols.get("campaign")}
    r = hdr + 1
    while r <= len(g) and not _c(g, r, 2):
        r += 1
    rows = []
    while r <= len(g) and _c(g, r, 2) and _c(g, r, 1).lower() != "totals":
        rows.append((r, _c(g, r, 2), _c(g, r, out["camp"]).lower() if out["camp"] else ""))
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
    dh = next(r for r in range(1, len(g) + 1)
              if "ongoing headcount" in _c(g, r, 1).lower() and _c(g, r, 3).lower() == "total for week")
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
    # 2 daily K/L freeze: L <- K, K <- J (ICD rows + Totals row)
    dl = find_daily(V)
    for r in [x[0] for x in dl["rows"]] + [dl["totals"]]:
        values.append((f"{A(dl['prevw'])}{r}", _c(V, r, dl["lastw"])))
        values.append((f"{A(dl['lastw'])}{r}", _c(V, r, dl["run"])))
    # 3 delta box 'Last week' <- this week's daily values (blank when not a number)
    dx = find_delta(V)
    by_name = {name.lower(): r for r, name, _ in dl["rows"]}
    for r, name in dx["rows"]:
        src = by_name.get(name.lower())
        for i, k in enumerate(dx["last"]):
            v = _num(_c(V, src, dl["days"][i])) if src else None
            values.append((f"{A(k)}{r}", "" if v is None else v))
    for k in dx["last"]:
        if not _c(F, dx["totals"], k).upper().startswith("=SUM"):
            values.append((f"{A(k)}{dx['totals']}",
                           f"=SUM({A(k)}{dx['rows'][0][0]}:{A(k)}{dx['rows'][-1][0]})"))
    # 4 the closed week's daily totals, read BEFORE the clear
    stack_values = [_c(V, dl["totals"], k) for k in dl["days"]] + [_c(V, dl["totals"], dl["run"])]
    # 5 clear the days + the new week's day numbers
    clear = [f"{A(dl['days'][0])}{dl['rows'][0][0]}:{A(dl['days'][-1])}{dl['rows'][-1][0]}"]
    monday = new_sunday - dt.timedelta(days=6)
    for i, k in enumerate(dl["days"]):
        values.append((f"{A(k)}{dl['daynum']}", (monday + dt.timedelta(days=i)).day))
    stack = find_stack(V, dl["totals"])
    return {"values": values, "clear": clear,
            "stack_top": stack[0] if stack else dl["totals"] + 1,
            "stack_label": f"WE {closed.month}.{closed.day}",
            "stack_values": stack_values, "last_col": dl["run"],
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
    empty = [(r, name, camp) for r, name, camp in dl["rows"] if _c(V, r, col) == ""]
    if not empty:
        return []
    need = {CAMPAIGN_SOURCE.get(camp) for _, _, camp in empty} | \
           {s for _, name, _ in empty for s in DUAL.get(name.lower(), ())}
    if trackers is None and need & {"att_country", "nds", "b2b_att_country", "b2b_box"}:
        trackers = tracker_readings_for(day + dt.timedelta(days=1), logfn=logfn)
    if retail is None and "retail" in need:
        retail = retail_values(day, [n for _, n, c in empty if CAMPAIGN_SOURCE.get(c) == "retail"], logfn)
    if je is None and "je" in need:
        je = (je_values(today, [n for _, n, c in empty if CAMPAIGN_SOURCE.get(c) == "je"], logfn)
              if day == today - dt.timedelta(days=1) else {})
    out = []
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
        out.append((f"{A(col)}{r}", v))
    return out


def run(apply_changes: bool = False, today: Optional[dt.date] = None, logfn=print) -> int:
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.org_sales_board.week import reporting_sunday, completed_days
    today = today or dt.date.today()
    ws = open_tab()
    V = ws.get_all_values()
    F = ws.get_all_values(value_render_option="FORMULA")
    target = reporting_sunday(today)
    on = board_sunday(V, today)
    logfn(f"{TAB}: tab is on WE {on}, reporting week WE {target} (today {today})")
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
    for day in completed_days(today):
        if day > today - dt.timedelta(days=1):
            continue
        try:
            ups = plan_day(V, day, today, logfn=logfn)
        except Exception as e:                                     # noqa: BLE001
            logfn(f"  {day}: NOT filled — {type(e).__name__}: {e}")
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
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="pretend today is this date")
    a = ap.parse_args(argv)
    return run(apply_changes=a.apply, today=a.today)


if __name__ == "__main__":
    raise SystemExit(main())
