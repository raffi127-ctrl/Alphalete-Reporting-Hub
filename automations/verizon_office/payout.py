"""The Verizon payout grid -- what every line, add-on and bonus pays, in the
B2B Vantura doc's "NDS Payout" layout. Carlos 2026-11-15: "make me a comp grid
that looks similar to the one that we have on the B2B Vantura Google Doc, in
the tab called NDS payout ... makes it just easy to see what everyone gets
paid out for everything. Send it to me on Slack, and then add it into that B2B
Vantura doc and also into the Vantura master sales board sheet."

Every number comes from verizon_office/comp.py, which is the four Credico
PDFs in resources/verizon_comp/ (SOW Schedule A 6.16.26, Churn Schedule 2026,
Activation Bonus, AutoPay Bonus). The "where the office sits" line is live:
the Verizon Order Log tab's approval dates against Credico's churn calendar.

Three outputs, same content:
  * the 'Verizon Payout' tab on the Vantura Master Sales Board (--write-tab)
  * a PNG for Slack (--png / revenue --board payout --dm)
  * a section at the end of the B2B Vantura doc's "Verizon Breakdowns" tab
    (--doc; needs a Google Docs token, which lives on Carlos's Mac)

    python -m automations.verizon_office.payout --png                    # output/verizon_office/verizon_payout.png
    python -m automations.verizon_office.payout --write-tab              # the Vantura Master tab
    python -m automations.verizon_office.payout --doc                    # the Google Doc section
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.verizon_office import comp as C

ROOT = Path(__file__).resolve().parents[2]
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"       # Vantura Master Sales Board
TAB = "Verizon Payout"
DOC_ID = "12LSUQ10vb-vdOfbbvL6USBuAfXxVV9lp0I25Osmt2u0"          # B2B Vantura (Google Doc)
DOC_TAB_ID = "t.jf6uam6tjkig"                                     # its "Verizon Breakdowns" tab
GDOCS_TOKEN = Path.home() / ".config" / "brand-audit" / "gdocs-token.json"
TITLE = "Verizon Wireless (Credico / SCI) — Payout — eff 6/16/2026"
LEAD = ("Port pay floats on the office's 30-day churn tier, locked 4 weeks at a time off Credico's churn calendar. "
        "Everything that is not a new port-in smartphone is a flat $25. Pay triggers on the APPROVAL date and runs ~2 weeks behind.")

TIER_BANDS = {1: "0 – 4.99%", 2: "5 – 6.99%", 3: "7 – 8.99%", 4: "9 – 14.99%", 5: "15 – 19.99%",
              6: "20 – 26.99%", 7: "27 – 33.99%", 8: "34%+"}


def tables() -> List[Tuple[str, List[List[str]], Optional[str]]]:
    """[(heading, rows incl. header row, footnote)] in the NDS Payout order:
    the churn-tier grid, the rep tier bonus, everything else."""
    tier_rows = [["0–30 Day Churn (office)", "Tier", "New PORT smartphone"]]
    for t in range(1, 9):
        tier_rows.append([TIER_BANDS[t], "Tier %d%s" % (t, " (neutral)" if t == C.NEUTRAL_TIER else ""),
                          "$%d" % C.PORT_TIER_PAY[t]])
    bonus_rows = [["< 4 orders", "4 orders", "5–6 orders", "7–8 orders", "9+ orders"],
                  ["$0"] + ["$%d" % rate for thr, _n, rate in sorted(C.WEEKLY_TIERS) if thr > 0]]
    else_rows = [["Item", "Pay", "Item", "Pay"],
                 ["New line — no port", "$%d" % C.FLAT_LINE, "AutoPay enrolled (shows usage)", "+$%d" % C.AUTOPAY],
                 ["CPO — port or no port", "$%d" % C.FLAT_LINE, "Unlimited Plus / Unlimited Ultimate", "+$%d" % C.PREMIUM_PLAN],
                 ["BYOD — port or no port", "$%d" % C.FLAT_LINE, "Mobile Protect / Mobile Secure (any size)", "+$%d" % C.PROTECT],
                 ["Unlimited Welcome / Simplicity plan", "$0", "Tablet, watch, hotspot lines", "not on the grid"]]
    return [
        ("NEW PORT-IN SMARTPHONE — by the office's churn tier (SOW Table 1 + 2)", tier_rows,
         "One churn rate for the office: of every line activated AND approved in the window, the share that cancelled within 30 days of "
         "activating -- BYOD and no-port lines count in it, they just pay flat. Under 15 activations in the window = Tier 4 neutral. "
         "The window is on APPROVAL dates and is processed ~5 weeks before the sales weeks it prices."),
        ("REP TIER BONUS — per line activated with an approval date, by unique customer orders in the Mon–Sun week", bonus_rows,
         "Option 1, wireless-only mix (75%+ VZ Wireless). DQ: a 90-day cancel rate of 40%+ (lines cancelled with no approval date vs. "
         "compensable lines; 0% until the rep has placed 20 lines)."),
        ("EVERYTHING ELSE", else_rows,
         "Plan and protection add-ons stack on the line. A line cancelled within 90 days of activation is not paid (or is charged back); "
         "so are number swaps and equipment downgrades inside 90 days. Credico pays when Verizon pays them."),
    ]


def office_status(today: Optional[dt.date] = None, log=print) -> List[str]:
    """Where the office sits: the block paying now, the next block (processed
    ~5 weeks ahead), and the one forming -- off the Verizon Order Log tab's
    approval dates against comp.CHURN_CALENDAR. [] if the tab can't be read."""
    today = today or dt.date.today()
    try:
        from automations.recruiting_report.fill import open_by_key
        from automations.verizon_office import order_log_tab as OL
        rows = open_by_key(OL.PROD_SHEET_ID).worksheet(OL.TAB).get_all_values()
    except Exception as e:  # noqa: BLE001
        log("[payout] office status skipped (%s)" % e)
        return []
    col = {h: i for i, h in enumerate(rows[0])}

    def d(s):
        try:
            return dt.datetime.strptime(s, "%m/%d/%Y").date()
        except (ValueError, TypeError):
            return None
    out = []
    blocks = sorted(C.CHURN_CALENDAR)
    cur = max((b for b in blocks if b[0] <= today), default=None, key=lambda b: b[0])
    if not cur:
        return []
    idx = blocks.index(cur)
    for label, (start, w0, w1) in (("Paying now", cur),) + tuple(
            (lab, blocks[idx + k]) for k, lab in ((1, "Next block"), (2, "After that")) if idx + k < len(blocks)):
        end = start + dt.timedelta(days=27)
        base = [r for r in rows[1:] if d(r[col["Activation Date"]]) and d(r[col["Approval Date"]]) and w0 <= d(r[col["Approval Date"]]) <= w1]
        gone = [r for r in base if r[col["Line Status"]] == "Disconnected" and d(r[col["Cancel Date"]])
                and (d(r[col["Cancel Date"]]) - d(r[col["Activation Date"]])).days <= 30]
        if len(base) < C.NEUTRAL_UNTIL_ACTIVATIONS:
            tier, why = C.NEUTRAL_TIER, "%d approved line(s) in the window, under %d" % (len(base), C.NEUTRAL_UNTIL_ACTIVATIONS)
        else:
            rate = len(gone) / len(base)
            tier = next(t for ceil, t in C.CHURN_TIERS if rate < ceil)
            why = "%.1f%% churn (%d of %d approved lines)" % (100 * rate, len(gone), len(base))
        out.append("%s — sales weeks %d/%d–%d/%d, scored on approvals %d/%d–%d/%d: %s → Tier %d, $%d per port line%s"
                   % (label, start.month, start.day, end.month, end.day, w0.month, w0.day, w1.month, w1.day, why, tier,
                      C.PORT_TIER_PAY[tier], "" if label == "Paying now" else " (still moving until Credico processes it)"))
    return out


# ------------------------------------------------------------------ html ----

def render_html(status: List[str], today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    parts = []
    for heading, rows, note in tables():
        body = "".join("<tr>" + "".join(("<th>%s</th>" if i == 0 else "<td>%s</td>") % html.escape(c) for c in r) + "</tr>"
                       for i, r in enumerate(rows))
        parts.append(f'<h2>{html.escape(heading)}</h2><table>{body}</table>'
                     + (f'<div class="note">{html.escape(note)}</div>' if note else ""))
    stat = "".join(f"<li>{html.escape(s)}</li>" for s in status)
    return f"""<html><head><style>
body{{margin:0;background:#fff;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222}}
#card{{padding:26px 30px;display:inline-block;max-width:1180px}} h1{{font:800 24px Georgia;margin:0 0 4px}}
.lead{{font-size:13px;color:#555;margin:0 0 14px;max-width:1100px}} h2{{font-size:14px;margin:18px 0 6px;color:#1f2a44;letter-spacing:.02em}}
table{{border-collapse:collapse}} th{{background:#1f2a44;color:#fff;font-size:12.5px;padding:7px 14px;border:1px solid #1f2a44}}
td{{border:1px solid #c9ced6;padding:6px 14px;text-align:center;font-size:13.5px;font-weight:600}}
tr td:first-child{{text-align:left;font-weight:600}} .note{{font-size:11.5px;color:#555;margin-top:5px;max-width:1100px}}
.status{{margin-top:16px;padding:10px 14px;background:#f3f5f8;border-left:4px solid #1f2a44;font-size:12.5px}}
.status li{{margin:3px 0}} .foot{{font-size:11px;color:#777;margin-top:12px}}
</style></head><body><div id="card">
<h1>{html.escape(TITLE)}</h1><div class="lead">{html.escape(LEAD)}</div>
{''.join(parts)}
{('<div class="status"><b>Where the office sits (approval-date windows, Order Log as of %s)</b><ul>%s</ul></div>' % (today.strftime('%-m/%-d') if sys.platform != 'win32' else today.strftime('%#m/%#d'), stat)) if status else ''}
<div class="foot">Source: Credico SOW Schedule A (6.16.26), Churn Schedule Wireless 2026, Activation Bonus (4.19.26–12.31.26), AutoPay Bonus (1.1.26) — resources/verizon_comp. Estimates; Credico's statement is the pay.</div>
</div></body></html>"""


def render_png(out: Path, status: Optional[List[str]] = None, today: Optional[dt.date] = None) -> Path:
    from automations.tableau_screenshots.email_tracker import _screenshot_html
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    return _screenshot_html(render_html(office_status(today) if status is None else status, today), out)


# ----------------------------------------------------------------- sheet ----

def grid(status: List[str]) -> Tuple[List[List[str]], dict]:
    """The tab as rows + marks for formatting."""
    W = 5
    g: List[List[str]] = []
    marks = {"title": [], "headers": [], "notes": [], "tables": []}

    def row(vals=(), at=0):
        r = [""] * W
        for i, v in enumerate(vals):
            r[at + i] = str(v)
        g.append(r)
        return len(g)
    marks["title"].append(row([TITLE]))
    marks["notes"].append(row([LEAD]))
    row()
    for heading, rows, note in tables():
        marks["headers"].append(row([heading]))
        first = len(g) + 1
        for i, r in enumerate(rows):
            n = row(r)
            if i == 0:
                marks["headers"].append(n)
        marks["tables"].append((first, len(g), len(rows[0])))
        if note:
            marks["notes"].append(row([note]))
        row()
    if status:
        marks["headers"].append(row(["WHERE THE OFFICE SITS (approval-date windows, off the Verizon Order Log)"]))
        for s in status:
            marks["notes"].append(row([s]))
        row()
    marks["notes"].append(row(["Source: Credico SOW Schedule A (6.16.26), Churn Schedule Wireless 2026, Activation Bonus, AutoPay Bonus "
                              "(resources/verizon_comp). Estimates; Credico's statement is the pay."]))
    return g, marks


def write_tab(sheet_id: str = SHEET_ID, status: Optional[List[str]] = None, log=print) -> int:
    import gspread
    from automations.recruiting_report.fill import _retry, open_by_key
    status = office_status() if status is None else status
    g, marks = grid(status)
    sh = open_by_key(sheet_id)
    try:
        ws = sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = _retry(lambda: sh.add_worksheet(title=TAB, rows=max(60, len(g) + 10), cols=5))
    _retry(lambda: ws.resize(rows=max(60, len(g) + 10), cols=5))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(g, "A1", value_input_option="RAW"))
    sid = ws.id
    NAVY, LIGHT = (0.12, 0.23, 0.37), (0.95, 0.96, 0.97)

    def rng(r0, r1, c0, c1):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}
    solid = {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}}
    reqs = [{"repeatCell": {"range": rng(0, len(g) + 5, 0, 5), "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 1, "green": 1, "blue": 1}, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE",
                "horizontalAlignment": "CENTER", "textFormat": {"bold": False, "italic": False, "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}}},
             "fields": "userEnteredFormat(backgroundColor,wrapStrategy,verticalAlignment,horizontalAlignment,textFormat)"}},
            {"updateBorders": {"range": rng(0, len(g) + 5, 0, 5), "top": {"style": "NONE"}, "bottom": {"style": "NONE"}, "left": {"style": "NONE"},
                               "right": {"style": "NONE"}, "innerHorizontal": {"style": "NONE"}, "innerVertical": {"style": "NONE"}}}]
    for r in marks["title"]:
        reqs.append({"mergeCells": {"range": rng(r - 1, r, 0, 5), "mergeType": "MERGE_ALL"}})
        reqs.append({"repeatCell": {"range": rng(r - 1, r, 0, 5), "cell": {"userEnteredFormat": {"backgroundColor": {"red": NAVY[0], "green": NAVY[1], "blue": NAVY[2]},
                     "horizontalAlignment": "LEFT", "textFormat": {"bold": True, "fontSize": 13, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                     "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}})
    for r in marks["notes"]:
        reqs.append({"mergeCells": {"range": rng(r - 1, r, 0, 5), "mergeType": "MERGE_ALL"}})
        reqs.append({"repeatCell": {"range": rng(r - 1, r, 0, 5), "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT", "wrapStrategy": "WRAP",
                     "textFormat": {"italic": True, "fontSize": 9, "foregroundColor": {"red": 0.3, "green": 0.3, "blue": 0.3}}}},
                     "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy,textFormat)"}})
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
                                                   "properties": {"pixelSize": 44}, "fields": "pixelSize"}})
    for r in marks["headers"]:
        width = 5
        reqs.append({"repeatCell": {"range": rng(r - 1, r, 0, width), "cell": {"userEnteredFormat": {"backgroundColor": {"red": NAVY[0], "green": NAVY[1], "blue": NAVY[2]},
                     "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    for first, last, ncols in marks["tables"]:
        reqs.append({"updateBorders": {"range": rng(first - 1, last, 0, ncols), "top": solid, "bottom": solid, "left": solid, "right": solid,
                                       "innerHorizontal": solid, "innerVertical": solid}})
        reqs.append({"repeatCell": {"range": rng(first, last, 0, ncols), "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                     "fields": "userEnteredFormat.textFormat.bold"}})
        reqs.append({"repeatCell": {"range": rng(first, last, 0, 1), "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT", "backgroundColor": {"red": LIGHT[0], "green": LIGHT[1], "blue": LIGHT[2]}}},
                     "fields": "userEnteredFormat(horizontalAlignment,backgroundColor)"}})
    for c, px in ((0, 300), (1, 150), (2, 230), (3, 300), (4, 150)):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    _retry(lambda: sh.batch_update({"requests": reqs}))
    log("[payout] '%s' tab written on %s (%d rows)" % (TAB, sh.title, len(g)))
    return len(g)


# ------------------------------------------------------------ google doc ----

def _docs_token() -> str:
    import json
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    d = json.loads(GDOCS_TOKEN.read_text())
    creds = Credentials.from_authorized_user_info(d, d.get("scopes"))
    creds.refresh(Request())
    return creds.token


def write_doc(status: Optional[List[str]] = None, doc_id: str = DOC_ID, tab_id: str = DOC_TAB_ID, log=print) -> bool:
    """Append the payout section (heading, lead, the three tables with their
    notes, the status lines) at the END of the doc tab. Tables are built the
    way the Docs API wants: insert the table, then fill cells back-to-front so
    earlier indexes never shift."""
    import requests
    status = office_status() if status is None else status
    token = _docs_token()
    hdr = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    base = "https://docs.googleapis.com/v1/documents/%s" % doc_id

    def doc():
        r = requests.get(base + "?includeTabsContent=true", headers=hdr, timeout=60)
        r.raise_for_status()
        return r.json()

    def tab_body(j):
        for t in j.get("tabs", []):
            if t["tabProperties"]["tabId"] == tab_id:
                return t["documentTab"]["body"]["content"]
            for c in t.get("childTabs", []):
                if c["tabProperties"]["tabId"] == tab_id:
                    return c["documentTab"]["body"]["content"]
        raise RuntimeError("doc tab %s not found" % tab_id)

    def end_index(j):
        return tab_body(j)[-1]["endIndex"] - 1

    def batch(reqs):
        r = requests.post(base + ":batchUpdate", headers=hdr, json={"requests": reqs}, timeout=60)
        if not r.ok:
            raise RuntimeError("docs batchUpdate %s: %s" % (r.status_code, r.text[:300]))
        return r.json()

    loc = lambda i: {"index": i, "tabId": tab_id}  # noqa: E731
    # 1. heading + lead
    j = doc()
    i = end_index(j)
    text = "\n" + TITLE + "\n" + LEAD + "\n"
    batch([{"insertText": {"location": loc(i), "text": text}},
           {"updateParagraphStyle": {"range": {"startIndex": i + 1, "endIndex": i + 1 + len(TITLE), "tabId": tab_id},
                                     "paragraphStyle": {"namedStyleType": "HEADING_1"}, "fields": "namedStyleType"}}])
    # 2. each table: heading line, then the table, then cells, then note
    for heading, rows, note in tables():
        j = doc(); i = end_index(j)
        batch([{"insertText": {"location": loc(i), "text": heading + "\n"}},
               {"updateTextStyle": {"range": {"startIndex": i, "endIndex": i + len(heading), "tabId": tab_id},
                                    "textStyle": {"bold": True}, "fields": "bold"}}])
        j = doc(); i = end_index(j)
        batch([{"insertTable": {"rows": len(rows), "columns": len(rows[0]), "location": loc(i)}}])
        # find the table we just made (the last table in the tab) and fill it back-to-front
        j = doc()
        tbl = [el for el in tab_body(j) if "table" in el][-1]["table"]
        cells = []
        for ri, trow in enumerate(tbl["tableRows"]):
            for ci, cell in enumerate(trow["tableCells"]):
                cells.append((cell["content"][0]["startIndex"], rows[ri][ci], ri == 0))
        reqs = []
        for start, val, is_hdr in sorted(cells, key=lambda c: -c[0]):
            if val:
                reqs.append({"insertText": {"location": loc(start), "text": val}})
                if is_hdr:
                    reqs.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": start + len(val), "tabId": tab_id},
                                                     "textStyle": {"bold": True}, "fields": "bold"}})
        if reqs:
            batch(reqs)
        if note:
            j = doc(); i = end_index(j)
            batch([{"insertText": {"location": loc(i), "text": note + "\n"}},
                   {"updateTextStyle": {"range": {"startIndex": i, "endIndex": i + len(note), "tabId": tab_id},
                                        "textStyle": {"italic": True, "fontSize": {"magnitude": 9, "unit": "PT"}}, "fields": "italic,fontSize"}}])
    if status:
        j = doc(); i = end_index(j)
        text = "Where the office sits (approval-date windows, off the Verizon Order Log, %s):\n" % dt.date.today().strftime("%m/%d/%Y") + "\n".join("• " + s for s in status) + "\n"
        batch([{"insertText": {"location": loc(i), "text": text}}])
    j = doc(); i = end_index(j)
    batch([{"insertText": {"location": loc(i), "text": "Source: Credico SOW Schedule A (6.16.26), Churn Schedule Wireless 2026, Activation Bonus, AutoPay Bonus. Estimates — Credico's statement is the pay.\n"}}])
    log("[payout] section appended to the B2B Vantura doc tab %s" % tab_id)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--write-tab", action="store_true")
    ap.add_argument("--sheet-id", default=SHEET_ID)
    ap.add_argument("--doc", action="store_true")
    ap.add_argument("--no-status", action="store_true", help="skip the live 'where the office sits' lines")
    a = ap.parse_args(argv)
    status = [] if a.no_status else office_status()
    for s in status:
        print("  " + s)
    if a.png:
        print("✓ %s" % render_png(ROOT / "output" / "verizon_office" / "verizon_payout.png", status))
    if a.write_tab:
        write_tab(a.sheet_id, status)
    if a.doc:
        write_doc(status)
    if not (a.png or a.write_tab or a.doc):
        for heading, rows, note in tables():
            print("\n" + heading)
            for r in rows:
                print("   " + " | ".join(r))
            if note:
                print("   (" + note + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
