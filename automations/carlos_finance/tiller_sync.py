"""Daily Tiller → Ledger sync for Carlos's Business & Personal P&L sheet.

WHAT IT DOES (no browser — Sheets API only):
  1. Reads Tiller's Transactions tab (Tiller refreshes it from the banks every day).
  2. Finds transactions whose Tiller Transaction ID is not on the Ledger yet, categorizes them with
     automations.carlos_finance.categorize, and adds them to the Ledger (newest first).
  3. EXISTING rows keep whatever Category is on the sheet — a category Carlos changed by hand is
     never overwritten.  Group / Side / Flag are recomputed from the Category for every row, so a
     manual category change flows through to the P&L.
  4. Smart Circle pays sales once a week; any other SCI deposit that week is a Security payout.
     For weeks that received new rows the largest SCI ACH stays "Sales Deposits (SCI)" and the
     rest become "Transfer from Security to checking".
  5. When the calendar rolls it adds the new week column to Business Weekly / Personal Weekly and
     the new month column to Business Monthly (copying the newest column's formulas), and points
     the Dashboard at the latest full week.

  python -m automations.carlos_finance.tiller_sync            # live
  python -m automations.carlos_finance.tiller_sync --dry-run  # report only, write nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from automations.carlos_finance import categorize as C

PNL = os.environ.get("CARLOS_PNL_SHEET_ID", "1ngQtKRNeuGV_FDBp-d9boZmxp6cO3T4IKa7k2NdiLq0")
TILLER = os.environ.get("CARLOS_TILLER_SHEET_ID", "1D2mjKSRNCM3fleq8e7uJyRuIotVqMfEW6baC7DV9fAE")
TOKEN = Path.home() / ".config/recruiting-report/oauth-token.json"
EPOCH = dt.date(1899, 12, 30)
START = dt.date(2025, 1, 1)
HEADER = ["Date", "Week Ending", "Month", "Account", "Side", "Description", "Amount", "Category", "Group", "Flag", "Txn ID", "Full Description"]
SALES, SEC_XFER = "Sales Deposits (SCI)", "Transfer from Security to checking"
BIZ_CHK = C.ACCOUNTS["0573"][0]
WEEK_TABS = ["Business Weekly", "Personal Weekly"]
MONTH_TABS = ["Business Monthly"]
NAVY = {"red": 0.07, "green": 0.13, "blue": 0.25}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}", flush=True)


def ser(d: dt.date) -> int:
    return (d - EPOCH).days


def unser(n) -> dt.date:
    return EPOCH + dt.timedelta(days=int(n))


class _Retrying:
    """Wraps the Sheets `spreadsheets()` resource so every .execute() retries on 429 / 5xx with backoff
    (the Lucy orchestrator can run several Sheets-heavy jobs close together)."""
    def __init__(self, inner): self._inner = inner
    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if callable(attr):
            def wrapped(*a, **k):
                res = attr(*a, **k)
                return _Retrying(res) if hasattr(res, "execute") or hasattr(res, "get") else res
            return wrapped
        return attr
    def execute(self, *a, **k):
        import time as _t
        from googleapiclient.errors import HttpError
        delay = 5
        for attempt in range(6):
            try:
                return self._inner.execute(*a, **k)
            except HttpError as e:
                if e.resp.status in (429, 500, 502, 503) and attempt < 5:
                    log(f"Sheets API {e.resp.status} — retrying in {delay}s"); _t.sleep(delay); delay *= 2; continue
                raise


def _svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.load(open(TOKEN)))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return _Retrying(build("sheets", "v4", credentials=creds).spreadsheets())


def _parse_date(s) -> dt.date | None:
    if isinstance(s, (int, float)):
        return unser(s)
    for f in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(s).strip(), f).date()
        except ValueError:
            pass
    return None


def col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ------------------------------------------------------------------ ledger merge
def read_tiller(svc) -> list[dict]:
    v = svc.values().get(spreadsheetId=TILLER, range="Transactions!A1:P20000", valueRenderOption="UNFORMATTED_VALUE",
                         dateTimeRenderOption="FORMATTED_STRING").execute().get("values", [])
    hdr = v[0]
    ix = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in v[1:]:
        g = lambda k: (r[ix[k]] if k in ix and ix[k] < len(r) else "")  # noqa: E731
        d = _parse_date(g("Date"))
        acct = str(g("Account #")).strip().zfill(4)
        tid = str(g("Transaction ID")).strip()
        if not d or d < START or not tid or acct not in C.ACCOUNTS:
            continue
        try:
            amt = round(float(g("Amount")), 2)
        except (TypeError, ValueError):
            continue
        out.append({"date": d, "acct": acct, "desc": str(g("Description")), "full": str(g("Full Description")), "amt": amt, "id": tid})
    return out


def read_ledger(svc) -> list[list]:
    v = svc.values().get(spreadsheetId=PNL, range="Ledger!A1:L20000", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    return [r + [""] * (12 - len(r)) for r in v[1:] if r and r[0] != ""]


def build_rows(ledger: list[list], tiller: list[dict]) -> tuple[list[list], list[list]]:
    have = {str(r[10]) for r in ledger}
    new = []
    for t in tiller:
        if t["id"] in have:
            continue
        name, _side = C.ACCOUNTS[t["acct"]]
        cat = C.category_for(t["full"], t["desc"], t["acct"], t["amt"])
        new.append([ser(t["date"]), ser(C.week_end(t["date"])), t["date"].strftime("%Y-%m"), name, "", t["desc"][:80], t["amt"], cat, "", "", t["id"], t["full"][:120]])
        have.add(t["id"])
    rows = [list(r[:12]) for r in ledger] + new
    # SCI weekly split, only in weeks that received new rows
    touched = {r[1] for r in new}
    for wk in touched:
        sci = [r for r in rows if r[1] == wk and r[3] == BIZ_CHK and r[7] in (SALES, SEC_XFER) and isinstance(r[6], (int, float)) and r[6] > 0
               and "FEDWIRE" not in str(r[11]).upper()]
        if sci:
            top = max(sci, key=lambda r: r[6])
            for r in sci:
                r[7] = SALES if r is top else SEC_XFER
    # derived fields for every row (manual category edits flow through)
    for r in rows:
        _num, side = C.ACCT_BY_NAME.get(r[3], ("", "B"))
        r[8], r[4], r[9] = C.derived(str(r[7]), side)
    rows.sort(key=lambda r: (r[0] if isinstance(r[0], (int, float)) else 0), reverse=True)
    return rows, new


def write_ledger(svc, rows: list[list]) -> None:
    n = len(rows)
    svc.values().update(spreadsheetId=PNL, range=f"Ledger!A1:L{n + 1}", valueInputOption="RAW", body={"values": [HEADER] + rows}).execute()
    meta = svc.get(spreadsheetId=PNL, fields="sheets(properties(sheetId,title,gridProperties),conditionalFormats)").execute()
    sh = next(s for s in meta["sheets"] if s["properties"]["title"] == "Ledger")
    sid = sh["properties"]["sheetId"]
    reqs = [{"setBasicFilter": {"filter": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": n + 1, "startColumnIndex": 0, "endColumnIndex": 12}}}},
            {"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": n + 1, "startColumnIndex": 7, "endColumnIndex": 8},
                                   "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Rules!$A$2:$A$60"}]}, "showCustomUi": True, "strict": False}}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": n + 1, "startColumnIndex": 0, "endColumnIndex": 2},
                            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "mmm d, yyyy"}}}, "fields": "userEnteredFormat.numberFormat"}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": n + 1, "startColumnIndex": 6, "endColumnIndex": 7},
                            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": '_($* #,##0.00_);[Red]_($* (#,##0.00);_($* "-"_);_(@_)'}}}, "fields": "userEnteredFormat.numberFormat"}}]
    for i, cf in enumerate(sh.get("conditionalFormats", [])):
        rule = dict(cf)
        rule["ranges"] = [dict(rg, endRowIndex=max(rg.get("endRowIndex", 0), n + 1)) for rg in cf["ranges"]]
        reqs.append({"updateConditionalFormatRule": {"index": i, "sheetId": sid, "rule": rule}})
    svc.batchUpdate(spreadsheetId=PNL, body={"requests": reqs}).execute()


# ------------------------------------------------------------------ calendar roll
def _sheet_meta(svc) -> dict:
    meta = svc.get(spreadsheetId=PNL, fields="sheets.properties").execute()
    return {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}


def _roll_column(svc, props: dict, new_c4_user_entered, week_tab: bool) -> None:
    """Insert a column right after C, copy C into it (so the old newest period moves to D), then give C the new period."""
    sid = props["sheetId"]
    rows = props["gridProperties"]["rowCount"]
    rng = lambda c0, c1, r0=0, r1=rows: {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}  # noqa: E731
    reqs = [{"insertDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4}, "inheritFromBefore": True}},
            {"copyPaste": {"source": rng(2, 3), "destination": rng(3, 4), "pasteType": "PASTE_NORMAL"}}]
    svc.batchUpdate(spreadsheetId=PNL, body={"requests": reqs}).execute()
    title = props["title"]
    data = [{"range": f"'{title}'!C4", "values": [[new_c4_user_entered]]}]
    if week_tab:
        data += [{"range": f"'{title}'!C3", "values": [['="In progress"']]},
                 {"range": f"'{title}'!D3", "values": [['="Latest full week: "&TEXT(D4-6,"mmm d")&" – "&TEXT(D4,"mmm d")']]},
                 {"range": f"'{title}'!E3", "values": [['=TEXT(E4-6,"mmm d")&" – "&TEXT(E4,"mmm d")']]}]
    svc.values().batchUpdate(spreadsheetId=PNL, body={"valueInputOption": "USER_ENTERED", "data": data}).execute()
    if week_tab:   # move the "latest full week" outline from E to D
        none = {"style": "NONE"}
        med = {"style": "SOLID_MEDIUM", "width": 2, "color": NAVY}
        svc.batchUpdate(spreadsheetId=PNL, body={"requests": [
            {"updateBorders": {"range": rng(4, 5, 3), "left": none, "right": none}},
            {"updateBorders": {"range": rng(2, 3, 3), "left": none, "right": none}},
            {"updateBorders": {"range": rng(3, 4, 3), "left": med, "right": med}}]}).execute()


def roll_calendar(svc, today: dt.date, dry_run: bool) -> list[str]:
    msgs = []
    props = _sheet_meta(svc)
    need_week = ser(C.week_end(today))
    rolled_week = False
    for tab in WEEK_TABS:
        if tab not in props:
            continue
        for _ in range(8):   # at most 8 weeks of catch-up per run
            c4 = svc.values().get(spreadsheetId=PNL, range=f"'{tab}'!C4", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [[0]])[0][0]
            if not isinstance(c4, (int, float)) or c4 >= need_week:
                break
            nxt = int(c4) + 7
            msgs.append(f"{tab}: add week ending {unser(nxt)}")
            if dry_run:
                break
            _roll_column(svc, props[tab], nxt, True)
            rolled_week = True
            props = _sheet_meta(svc)
    need_month = today.strftime("%Y-%m")
    for tab in MONTH_TABS:
        if tab not in props:
            continue
        for _ in range(6):
            c4 = str(svc.values().get(spreadsheetId=PNL, range=f"'{tab}'!C4", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [[""]])[0][0])
            if len(c4) != 7 or c4 >= need_month:
                break
            y, m = int(c4[:4]), int(c4[5:])
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            nxt = f"{y:04d}-{m:02d}"
            msgs.append(f"{tab}: add month {nxt}")
            if dry_run:
                break
            _roll_column(svc, props[tab], f'="{nxt}"', False)
            props = _sheet_meta(svc)
    if rolled_week and not dry_run:
        # Dashboard follows the in-progress week ("this week so far"); picking another week in B4 still works
        svc.values().update(spreadsheetId=PNL, range="Dashboard!B4", valueInputOption="USER_ENTERED", body={"values": [["='Business Weekly'!C4"]]}).execute()
        msgs.append("Dashboard reset to the in-progress week")
    return msgs


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", help="override today's date YYYY-MM-DD (testing)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    svc = _svc()
    tiller = read_tiller(svc)
    ledger = read_ledger(svc)
    rows, new = build_rows(ledger, tiller)
    log(f"Tiller {len(tiller)} txns (since {START}); Ledger had {len(ledger)}; new {len(new)}")
    if new:
        dts = [unser(r[0]) for r in new]
        by_cat: dict = {}
        for r in new:
            by_cat[r[7]] = by_cat.get(r[7], 0) + 1
        log(f"  new rows {min(dts)} → {max(dts)}; uncategorized {by_cat.get('Uncategorized', 0)}; top: "
            + ", ".join(f"{k} {v}" for k, v in sorted(by_cat.items(), key=lambda x: -x[1])[:6]))
    if not args.dry_run:
        write_ledger(svc, rows)
        log(f"Ledger written: {len(rows)} rows")
    for m in roll_calendar(svc, today, args.dry_run):
        log(("DRY-RUN " if args.dry_run else "") + m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
