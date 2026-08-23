"""Captainship boards — daily order-log fill (Carlos, 2026-08-23).

Every morning, for each of the 11 captainship owner boards:
  1. SALES BOARD: upsert the current week's rep-day counts into the hidden
     WeekData archive (`Rep|WE` keys, Mon..Sun in B:H) — the visible grid,
     week dropdowns and Last-Wk column are lookups and light up on their own.
     New sellers are appended to the Sales Board roster and Roll Call.
  2. ROLL CALL: raise-only 'Here' marks into RollCallData (sale day => Here;
     a manual Off/NoShow is never overwritten; no sale != absent).
  3. FOCUS REPORT (the hidden 'MT · <First>' tabs on the Captainship
     Dashboard — boards display them via IMPORTRANGE): current-week campaign
     rows from the order log (apps, product mix, VoIP, rolling headcount /
     sales-per-rep, cumulative CRU/ABP/BYOD %s, rolling rank among all
     owners) + recruiting rows 5-27 from the org Daily Log.
  4. Monday: rolls the week forward everywhere (new WeekData/RCD labels, new
     Focus Report week column block; the oldest week block is dropped).

Counting rule (verified 1:1 vs a Sara-finalized board): a rep's day count =
SUM of `Unit Count` over export rows with `sp.Order Date (copy)` = that day,
all product types. Names are the export's legal names (no alias table —
Carlos's rule for outside-org owners; the one quirk: Jeff Starr exports as
JEFFREY STARR).

DRY-RUN by default — pulls, computes and reports; nothing is written.
    python -m automations.captainship_boards.run                # dry-run
    python -m automations.captainship_boards.run --write        # apply
    python -m automations.captainship_boards.run --from-file X  # offline CSV

MUST RUN ON LUCY 2 for the live pull (Carlos's Tableau identity via the
shared CDP Chrome, same as att_order_log; the pull takes the same 9246 lock).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
import time
from pathlib import Path

from automations.captainship_boards import config as C

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

OUT = Path("output/captainship_boards")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


# ---------------------------------------------------------------- pull
def csv_url(start: dt.date, end: dt.date) -> str:
    return ("https://us-east-1.online.tableau.com/t/sci/views/"
            "ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
            f"&Start%20Date={start.isoformat()}&End%20Date={end.isoformat()}")


def pull_orderlog(start: dt.date, end: dt.date, dest: Path) -> Path:
    """Direct .csv through Carlos's real-Chrome Tableau session (Lucy 2)."""
    from patchright.sync_api import sync_playwright

    from automations.att_order_log.run import _fetch_csv
    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    with cdp_pull._cdp_lock(label="captainship orderlog", log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        log(f"  [cdp] real Chrome pid={proc.pid}; waiting 20s")
        time.sleep(20)
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{cdp_pull.CDP_PORT}")
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                log("  [cdp] auth OK")
                body = _fetch_csv(page, csv_url(start, end), log=log)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                return dest
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            cdp_pull._kill_ours()


# ---------------------------------------------------------------- parse
def _n(s) -> str:
    return " ".join(str(s or "").split()).strip()


def parse_orderlog(path: Path, monday: dt.date, upto: dt.date):
    """-> (per-owner {export_name: {rep: {date: units}}},
           per-owner day aggregates Counter, all-owner cumulative apps)"""
    from automations.att_order_log import clean

    wanted = {v[0] for v in C.OWNERS.values()}
    reps = {w: collections.defaultdict(lambda: collections.defaultdict(float))
            for w in wanted}
    agg = {w: collections.defaultdict(collections.Counter) for w in wanted}
    all_owner_day = collections.defaultdict(lambda: collections.defaultdict(float))
    nrows = 0
    for r in clean.load_rows(str(path), owner_prefix=None):
        raw = str(r.get("Owner & Office", "") or "").replace("\r", "\n").split("\n")
        owner = _n(raw[0]).upper()
        s = _n(r.get("sp.Order Date (copy)", ""))
        try:
            d = dt.datetime.strptime(s, "%m/%d/%Y").date()
        except ValueError:
            continue
        if not (monday <= d <= upto):
            continue
        try:
            u = float(r.get("Unit Count") or 0)
        except (TypeError, ValueError):
            continue
        if not u:
            continue
        nrows += 1
        all_owner_day[owner][d] += u
        if owner not in wanted:
            continue
        rep = _n(r.get("Rep", ""))
        if rep:
            reps[owner][rep][d] += u
        a = agg[owner][d]
        a["total"] += u
        prod = _n(r.get("Product Type (Broken Out)", "")).upper()
        cru = _n(r.get("CRU/IRU", "")).upper()
        wip = _n(r.get("Wireless Installment Plan", "")).upper()
        abp = _n(r.get("Auto Bill Pay", "")).upper()
        try:
            a["voip"] += float(r.get("Voice Line Count") or 0)
        except (TypeError, ValueError):
            pass
        if prod == "NEW INTERNET":
            a["ni"] += u
            if cru == "CRU":
                a["ni_cru"] += u
        elif prod == "WIRELESS":
            a["wl"] += u
            if wip == "BYOD":
                a["byod"] += u
                if cru == "CRU":
                    a["byod_cru"] += u
                elif cru == "IRU":
                    a["byod_iru"] += u
        elif prod == "AIR/AWB":
            a["air"] += u
        if cru == "CRU":
            a["cru"] += u
        elif cru == "IRU":
            a["iru"] += u
        if abp in ("Y", "YES"):
            a["abp_y"] += u
            a["abp_f"] += u
        elif abp in ("N", "NO"):
            a["abp_f"] += u
    log(f"  parsed {nrows:,} sale-rows in window {monday}..{upto}")
    return reps, agg, all_owner_day


# ---------------------------------------------------------------- sheets
def open_sheet(sheet_id: str):
    from automations.recruiting_report.fill import _retry, open_by_key
    return _retry(lambda: open_by_key(sheet_id))


def values_get(sh, rng: str, render: str = "FORMATTED_VALUE"):
    return sh.values_get(rng, params={"valueRenderOption": render}).get("values", [])


def values_batch_update(sh, data, raw=True):
    sh.values_batch_update(body={
        "valueInputOption": "RAW" if raw else "USER_ENTERED", "data": data})


# ---------------------------------------------------------------- sales board
def update_board(label, board_id, rep_days, monday, upto, write):
    we = C.week_label(monday)
    sh = open_sheet(board_id)
    wd = values_get(sh, "WeekData!A1:H5000")
    keymap = {row[0]: i + 1 for i, row in enumerate(wd) if row}
    weeks = [r[0] for r in values_get(sh, "WeekData!J1:J60")[1:] if r]

    data, appended = [], 0
    for rep, days in sorted(rep_days.items()):
        cells = [int(days.get(monday + dt.timedelta(days=i), 0)) or ""
                 for i in range(7)]
        if not any(v != "" for v in cells):
            continue
        key = f"{rep}|{we}"
        if key in keymap:
            data.append({"range": f"WeekData!B{keymap[key]}:H{keymap[key]}",
                         "values": [cells]})
        else:
            row = len(wd) + 1 + appended
            data.append({"range": f"WeekData!A{row}:H{row}",
                         "values": [[key] + cells]})
            appended += 1
    if we not in weeks:
        data.append({"range": f"WeekData!J{len(weeks) + 2}", "values": [[we]]})
        data.append({"range": "Sales Board!B2", "values": [[we]]})

    # LAST WEEK row (Sales Board r45, Carlos 8/24): the finished week's
    # day-by-day totals, refreshed every morning so Monday's fresh board
    # still answers "what did we do last Tuesday?".
    last_lbl = C.week_label(monday - dt.timedelta(days=7))
    lw = [0] * 7
    for row in wd:
        if row and row[0].endswith(f"|{last_lbl}"):
            for i in range(7):
                v = row[i + 1] if len(row) > i + 1 else ""
                try:
                    lw[i] += int(float(v or 0))
                except (TypeError, ValueError):
                    pass
    data.append({"range": "Sales Board!B45",
                 "values": [[f"LAST WEEK ({last_lbl})"]]})
    # D45 = last week's TOTAL, then the Mon-Sun day cells (Carlos 8/24)
    data.append({"range": "Sales Board!D45:K45",
                 "values": [[sum(lw)] + [v or 0 for v in lw]]})

    # roster append (Sales Board B4:B43 + Roll Call D)
    roster = [(_n(r[0]) if r else "") for r in values_get(sh, "Sales Board!B4:B43")]
    roster += [""] * (40 - len(roster))
    have = {r for r in roster if r}
    missing = [r for r in sorted(rep_days, key=lambda x: -sum(rep_days[x].values()))
               if r not in have and any(d >= monday for d in rep_days[r])]
    added_roster = []
    for rep in missing:
        try:
            slot = roster.index("")
        except ValueError:
            log(f"  !! {label}: roster full, cannot add {rep}")
            break
        roster[slot] = rep
        added_roster.append(rep)
        data.append({"range": f"Sales Board!B{4 + slot}", "values": [[rep]]})
    if added_roster:
        rc_d = [(_n(r[0]) if r else "") for r in values_get(sh, "Roll Call!D3:D210")]
        rc_have = {r for r in rc_d if r}
        for rep in added_roster:
            if rep in rc_have:
                continue
            try:
                slot = rc_d.index("")
            except ValueError:
                log(f"  !! {label}: Roll Call full, cannot add {rep}")
                break
            rc_d[slot] = rep
            data.append({"range": f"Roll Call!A{3 + slot}:D{3 + slot}",
                         "values": [["", "Active", "AT&T B2B", rep]]})

    # RollCallData raise-only (Mon..Sat)
    rcd = values_get(sh, "RollCallData!A1:G5000")
    rcd_map = {row[0]: (i + 1, row) for i, row in enumerate(rcd) if row}
    rcd_append = 0
    for rep, days in sorted(rep_days.items()):
        marks_new = ["Here" if days.get(monday + dt.timedelta(days=i), 0) > 0
                     else "" for i in range(6)]
        if not any(marks_new):
            continue
        key = f"{rep}|{we}"
        if key in rcd_map:
            rowi, row = rcd_map[key]
            cur = [(row[i + 1] if len(row) > i + 1 else "") for i in range(6)]
            merged = [cur[i] if _n(cur[i]) else marks_new[i] for i in range(6)]
            if merged != cur:
                data.append({"range": f"RollCallData!B{rowi}:G{rowi}",
                             "values": [merged]})
        else:
            row = len(rcd) + 1 + rcd_append
            data.append({"range": f"RollCallData!A{row}:G{row}",
                         "values": [[key] + marks_new]})
            rcd_append += 1

    log(f"  {label:<17} WD writes={len(data):>3} newreps={len(added_roster)}"
        + ("" if write else "  (dry-run)"))
    if write and data:
        values_batch_update(sh, data)
    if write:
        # Blank-rep filter (Carlos 8/24): hide empty roster slots on every
        # refresh, so newly-added reps surface and the board stays compact.
        # Owners can Data > Remove filter to type a name into a blank slot;
        # the next morning's run re-applies it.
        try:
            sb_id = sh.worksheet("Sales Board").id
            sh.batch_update({"requests": [{"setBasicFilter": {"filter": {
                "range": {"sheetId": sb_id, "startRowIndex": 3,
                          "endRowIndex": 43, "startColumnIndex": 0,
                          "endColumnIndex": 16},
                "criteria": {"1": {"condition": {"type": "NOT_BLANK"}}}}}}]})
        except Exception as e:  # noqa: BLE001
            log(f"  !! {label}: blank-filter reapply failed: {str(e)[:80]}")
    return len(data)


# ---------------------------------------------------------------- focus report
def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def ensure_week_block(master, label, monday, write):
    """Roll the MT tab's week columns forward if C isn't the current week."""
    tab = C.mt_tab(label)
    hdr = values_get(master, f"'{tab}'!C3")
    want = f"WK {monday.month + 0}/{0 + (monday + dt.timedelta(days=6)).day}"
    we = monday + dt.timedelta(days=6)
    want = f"WK {we.month}/{we.day}"
    got = (hdr[0][0] if hdr and hdr[0] else "")
    if got == want:
        return False
    log(f"  {label}: rolling week block (C3={got!r} -> {want!r})"
        + ("" if write else "  (dry-run)"))
    if not write:
        return True
    meta = master.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId,title),conditionalFormats)"})
    sid = cfs = None
    for s in meta["sheets"]:
        if s["properties"]["title"] == tab:
            sid = s["properties"]["sheetId"]
            cfs = s.get("conditionalFormats", [])
    tail0 = 2 + 8 * C.N_WEEKS
    reqs = [
        {"insertDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS",
         "startIndex": 2, "endIndex": 10}, "inheritFromBefore": False}},
        # clone the (now-shifted) old current block's formats K..R -> C..J
        {"copyPaste": {
            "source": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 103,
                       "startColumnIndex": 10, "endColumnIndex": 18},
            "destination": {"sheetId": sid, "startRowIndex": 0,
                            "endRowIndex": 103, "startColumnIndex": 2,
                            "endColumnIndex": 10},
            "pasteType": "PASTE_FORMAT"}},
        # drop the oldest block off the tail (keeps 34 weeks)
        {"deleteDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS",
         "startIndex": tail0, "endIndex": tail0 + 8}}},
        # collapsible day group for the new block
        {"addDimensionGroup": {"range": {"sheetId": sid, "dimension": "COLUMNS",
         "startIndex": 3, "endIndex": 10}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid,
         "dimension": "COLUMNS", "startIndex": 3, "endIndex": 10},
         "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
    ]
    master.batch_update({"requests": reqs})
    # header/date strip for the new block
    hdr_row = [want, "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dates = [C.serial(we)] + [C.serial(monday + dt.timedelta(days=i))
                              for i in range(7)]
    values_batch_update(master, [
        {"range": f"'{tab}'!C2:J2", "values": [dates]},
        {"range": f"'{tab}'!C3:J3", "values": [hdr_row]},
    ])
    # goal formulas shifted with the insert — re-point ONLY formula cells
    for cell, formula in (
        ("B37", '=IF(AND(ISNUMBER($B$32),ISNUMBER(C57)),ROUND($B$32*C57,0),"")'),
        ("B38", '=IF(ISNUMBER(C57),C57,"")'),
    ):
        cur = values_get(master, f"'{tab}'!{cell}", render="FORMULA")
        v = (cur[0][0] if cur and cur[0] else "")
        if isinstance(v, str) and v.startswith("="):
            values_batch_update(master, [{"range": f"'{tab}'!{cell}",
                                          "values": [[formula]]}], raw=False)
    # campaign CF rules: delete + re-add with fresh 34 WK ranges
    idx_del = [i for i, r in enumerate(cfs or [])
               if any(rg.get("startRowIndex", 0) + 1 in (32, 37, 38)
                      and rg.get("startColumnIndex", 0) >= 2
                      for rg in r.get("ranges", []))]
    reqs2 = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
             for i in sorted(idx_del, reverse=True)]
    GREEN, GREENT = {"red": .84, "green": .96, "blue": .87}, {"red": .08, "green": .33, "blue": .18}
    YELLOW, YELLOWT = {"red": .99, "green": .94, "blue": .78}, {"red": .52, "green": .30, "blue": .05}
    RED, REDT = {"red": .98, "green": .87, "blue": .87}, {"red": .60, "green": .11, "blue": .11}
    for row, goal, guards in (
        (32, "$B$32", "ISNUMBER(C32),ISNUMBER($B$32)"),
        (37, "$B$37", "ISNUMBER(C37),ISNUMBER($B$37)"),
        (38, "$B$38", "ISNUMBER(C38),ISNUMBER($B$38)"),
    ):
        anchor = f"C{row}"
        ranges = [{"sheetId": sid, "startRowIndex": row - 1, "endRowIndex": row,
                   "startColumnIndex": 2 + 8 * k, "endColumnIndex": 3 + 8 * k}
                  for k in range(C.N_WEEKS)]
        for frm, bg, fg in (
            (f"=AND({guards},{anchor}>=({goal})*0.95)", GREEN, GREENT),
            (f"=AND({guards},{anchor}>=({goal})*0.9,{anchor}<({goal})*0.95)",
             YELLOW, YELLOWT),
            (f"=AND({guards},{anchor}<({goal})*0.9)", RED, REDT),
        ):
            reqs2.append({"addConditionalFormatRule": {"rule": {
                "ranges": ranges,
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                    "values": [{"userEnteredValue": frm}]},
                    "format": {"backgroundColor": bg,
                               "textFormat": {"foregroundColor": fg}}}}}})
    master.batch_update({"requests": reqs2})
    return True


def update_focus(master, label, rep_days, agg, all_owner_day, monday, upto, write):
    tab = C.mt_tab(label)
    nd = (upto - monday).days + 1          # days elapsed in the week
    daycols = [col_letter(3 + i) for i in range(7)]

    def day_series(fn):
        return [fn(i) for i in range(nd)]

    cum = collections.Counter()
    cum_sellers: set = set()
    hc, spr, apps_d = [], [], []
    prod_d = {k: [] for k in ("ni", "ni_cru", "wlx", "byod", "byod_cru",
                              "byod_iru", "air", "voip")}
    pct_d = {k: [] for k in ("cru", "abp", "byodp")}
    rank_d = []
    # all-owner cumulative for rank
    owners_cum = collections.Counter()
    for i in range(nd):
        d = monday + dt.timedelta(days=i)
        a = agg.get(d, collections.Counter())
        cum.update(a)
        for rep, days in rep_days.items():
            if days.get(d, 0) > 0:
                cum_sellers.add(rep)
        for o, dd in all_owner_day.items():
            owners_cum[o] += dd.get(d, 0)
        me = C.OWNERS[label][0]
        my = owners_cum.get(me, 0)
        rank_d.append(1 + sum(1 for o, v in owners_cum.items() if v > my)
                      if my else "")
        hc.append(len(cum_sellers) or "")
        apps_d.append(int(a.get("total", 0)))
        spr.append(round(cum["total"] / len(cum_sellers), 1)
                   if cum_sellers else "")
        prod_d["ni"].append(int(a.get("ni", 0)))
        prod_d["ni_cru"].append(int(a.get("ni_cru", 0)))
        prod_d["wlx"].append(int(a.get("wl", 0) - a.get("byod", 0)))
        prod_d["byod"].append(int(a.get("byod", 0)))
        prod_d["byod_cru"].append(int(a.get("byod_cru", 0)))
        prod_d["byod_iru"].append(int(a.get("byod_iru", 0)))
        prod_d["air"].append(int(a.get("air", 0)))
        prod_d["voip"].append(int(a.get("voip", 0)))
        cden = cum["cru"] + cum["iru"]
        pct_d["cru"].append(round(cum["cru"] / cden, 4) if cden else "")
        pct_d["abp"].append(round(cum["abp_y"] / cum["abp_f"], 4)
                            if cum["abp_f"] else "")
        pct_d["byodp"].append(round(cum["byod"] / cum["wl"], 4)
                              if cum["wl"] else "")

    wk_apps = int(cum["total"])
    data = []

    def put(row, wk, days):
        if wk is not None:
            data.append({"range": f"'{tab}'!C{row}", "values": [[wk]]})
        data.append({"range": f"'{tab}'!D{row}:{daycols[nd - 1]}{row}",
                     "values": [days]})

    put(C.R_ACTIVE_HC, len(cum_sellers) or "", hc)
    put(C.R_APPS, wk_apps, apps_d)
    put(C.R_SPR, (round(wk_apps / len(cum_sellers), 1) if cum_sellers else ""),
        spr)
    put(C.R_RANK, rank_d[-1] if rank_d else "", rank_d)
    for row, key in ((C.R_NI, "ni"), (C.R_CRU_NI, "ni_cru"),
                     (C.R_WL_XBYOD, "wlx"), (C.R_BYOD, "byod"),
                     (C.R_CRU_BYOD, "byod_cru"), (C.R_IRU_BYOD, "byod_iru"),
                     (C.R_AIR, "air"), (C.R_VOIP, "voip")):
        put(row, int(sum(prod_d[key])), prod_d[key])
    put(C.R_CRU_PCT, pct_d["cru"][-1] if pct_d["cru"] else "", pct_d["cru"])
    put(C.R_ABP_PCT, pct_d["abp"][-1] if pct_d["abp"] else "", pct_d["abp"])
    put(C.R_BYOD_PCT, pct_d["byodp"][-1] if pct_d["byodp"] else "",
        pct_d["byodp"])

    log(f"  {label:<17} focus: apps={wk_apps:>3} hc={len(cum_sellers):>2} "
        f"rank={rank_d[-1] if rank_d else '-'}"
        + ("" if write else "  (dry-run)"))
    if write:
        values_batch_update(master, data)
    return wk_apps


def update_recruiting(master, monday, write):
    time.sleep(20)   # let the per-board read burst's quota window clear
    org = open_sheet(C.ORG_TRACKER_ID)
    rows = values_get(org, "'Daily Log'!A2:Q9000", render="UNFORMATTED_VALUE")
    daily = {label: {} for label in C.OWNERS}
    for r in rows:
        if len(r) < 17:
            continue
        try:
            d = int(r[0])
        except (TypeError, ValueError):
            continue
        m = _n(r[2])
        if m in daily:
            daily[m][d] = [float(x) if _n(x) not in ("", "None") else 0
                           for x in r[4:17]]
    for label in C.OWNERS:
        tab = C.mt_tab(label)
        data = []
        for row, (kind, spec) in C.RECRUIT_ROWS.items():
            vals, nums, dens = [], 0.0, 0.0
            for i in range(7):
                rec = daily[label].get(C.serial(monday + dt.timedelta(days=i)))
                if kind == "count":
                    v = int(rec[spec]) if rec else 0
                    vals.append(v)
                    nums += v
                else:
                    n_, d_ = spec
                    if rec and rec[d_]:
                        vals.append(round(rec[n_] / rec[d_], 4))
                        nums += rec[n_]
                        dens += rec[d_]
                    else:
                        vals.append("")
                        if rec:
                            nums += rec[n_]
            wk = (int(nums) if kind == "count"
                  else (round(nums / dens, 4) if dens else ""))
            data.append({"range": f"'{tab}'!C{row}:J{row}",
                         "values": [[wk] + vals]})
        if write:
            values_batch_update(master, data)
    log(f"  recruiting rows {'written' if write else 'computed (dry-run)'} "
        f"for {len(C.OWNERS)} owners")


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="apply the writes (default: dry-run report only)")
    ap.add_argument("--from-file", default=None,
                    help="offline: parse this ORDERLOG csv instead of pulling")
    ap.add_argument("--day", default=None,
                    help="pretend today is YYYY-MM-DD (Central)")
    ap.add_argument("--skip-sales", action="store_true")
    ap.add_argument("--skip-focus", action="store_true")
    ap.add_argument("--skip-recruiting", action="store_true")
    args = ap.parse_args(argv)

    today = (dt.date.fromisoformat(args.day) if args.day
             else dt.datetime.now(C.CENTRAL).date())
    monday = C.monday_of(today)
    upto = today                       # export lags; rows just won't exist yet
    log(f"=== captainship boards | week of {monday} (WE "
        f"{C.week_label(monday)}) | through {upto} | "
        f"{'WRITE' if args.write else 'DRY-RUN'} ===")

    if args.from_file:
        src = Path(args.from_file)
    else:
        src = OUT / f"orderlog_{monday.isoformat()}_{upto.isoformat()}.csv"
        pull_orderlog(monday, upto, src)
    reps_all, agg_all, all_owner_day = parse_orderlog(src, monday, upto)

    try:
        master = open_sheet(C.MASTER_ID)
    except Exception as e:  # noqa: BLE001 — dashboard not shared to this
        # machine's Sheets user yet: still update the 11 sales boards, skip
        # the Focus Report sections loudly.
        master = None
        log(f"!! cannot open the Captainship Dashboard ({type(e).__name__}) "
            "— Focus Report sections SKIPPED; share the dashboard to this "
            "machine's Sheets account to enable them")
    failures = []
    for label, (export_name, board_id) in C.OWNERS.items():
        rep_days = reps_all.get(export_name, {})
        try:
            if not args.skip_focus and master is not None:
                ensure_week_block(master, label, monday, args.write)
                update_focus(master, label, rep_days,
                             agg_all.get(export_name, {}), all_owner_day,
                             monday, upto, args.write)
            if not args.skip_sales:
                update_board(label, board_id, rep_days, monday, upto,
                             args.write)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{label}: {type(e).__name__}: {e}")
            log(f"  !! {label} FAILED: {type(e).__name__}: {e}")
        time.sleep(2)   # pace reads too — a dry-run burst can 403-quota
    if not args.skip_recruiting and master is not None:
        try:
            update_recruiting(master, monday, args.write)
        except Exception as e:  # noqa: BLE001
            failures.append(f"recruiting: {type(e).__name__}: {e}")
            log(f"  !! recruiting FAILED: {type(e).__name__}: {e}")

    if failures:
        log(f"finished with {len(failures)} FAILURE(S): {failures}")
        return 1
    log("finished clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
