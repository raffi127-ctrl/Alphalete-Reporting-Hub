"""Board helper for Shikamaru's Slack commission review (Carlos, 2026-07-23).

Shikamaru posts the week's commission summary + workbook to Carlos on Slack;
Carlos replies with changes in plain English; Shikamaru parses them, gets a
button-confirm, then shells THIS helper to apply. All sheet logic lives here,
under the recruiting-report auth (same split as promo_checkin.helper).

  .venv/bin/python -m automations.payroll_review.helper summary
      -> {"week", "locked", "reps": [{"name","brought","paid"}...], "totals"}
  .venv/bin/python -m automations.payroll_review.helper xlsx /path/out.xlsx
      -> {"path", "reps", "week"}   (Summary + Payout Detail sheets)
  .venv/bin/python -m automations.payroll_review.helper png /path/out.png
      -> {"path", "week", "locked"}  screenshot of the Commission tab's
         left-side boxes (payout/P&L table, ACTIVE REPS - NO REVENUE,
         REVENUE - NOT ACTIVE, first/second-week paycheck counts) rendered
         via the Sheets PDF export -> pypdfium2 at high DPI. Carlos prefers
         this picture over a text summary in Slack (2026-07-23).
  .venv/bin/python -m automations.payroll_review.helper apply '<json>'
      -> applies [{"rep","amount","label","type"}] ATOMICALLY:
         * every rep must resolve EXACTLY (Commission roster + Name Aliases,
           prefix rule); any ambiguity/miss -> nothing applied, candidates
           returned (Carlos's if-unsure-ask-me rule)
         * type "Bonus" (default; amount may be negative) or "NOPAY"
           (-> REMOVEALL row)
         * labels written RAW (a numeric-looking label like "0" silently
           breaks REMOVELINE parsing — learned 2026-07-23)
         * refuses if Commission F1 says the current week is LOCKED
         * triggers the web-app refresh, returns before/after payouts
"""
from __future__ import annotations

import json
import sys
import time
import unicodedata

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"


def _nrm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _sheet():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID)


def _read_summary(sh):
    cm = sh.worksheet("Commission")
    week = str(cm.acell("B1").value or "").strip()
    locked_note = str(cm.acell("F1").value or "").strip()
    locked = week and week in locked_note and "LOCK" in locked_note.upper()
    reps, total = [], None
    for r in cm.get("A4:C120"):
        name = str(r[0]).strip() if r else ""
        if not name:
            continue
        if name == "TOTAL":
            total = {"brought": str(r[1]).strip() if len(r) > 1 else "",
                     "paid": str(r[2]).strip() if len(r) > 2 else ""}
            break
        reps.append({"name": name,
                     "brought": str(r[1]).strip() if len(r) > 1 else "",
                     "paid": str(r[2]).strip() if len(r) > 2 else ""})
    return cm, week, bool(locked), reps, total


def summary() -> dict:
    sh = _sheet()
    _cm, week, locked, reps, total = _read_summary(sh)
    return {"week": week, "locked": locked, "reps": reps, "totals": total}


def xlsx(path: str) -> dict:
    import openpyxl
    from openpyxl.styles import Font
    sh = _sheet()
    cm, week, _locked, reps, total = _read_summary(sh)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"Commission — week ending {week}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Rep", "Brought In", "Commission"])
    for c in ws[2]:
        c.font = Font(bold=True)
    for r in reps:
        ws.append([r["name"], r["brought"], r["paid"]])
    if total:
        ws.append(["TOTAL", total["brought"], total["paid"]])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    det = wb.create_sheet("Payout Detail")
    for row in cm.get("G3:N600"):
        vals = [str(c).strip() for c in (row + [""] * 8)[:8]]
        if any(vals):
            det.append(vals)
    det.column_dimensions["A"].width = 28
    det.column_dimensions["D"].width = 30
    wb.save(path)
    return {"path": path, "reps": len(reps), "week": week}


def png(path: str) -> dict:
    """Screenshot of the Commission tab's left-side boxes (cols A:E — the
    per-rep payout/P&L table with TOTAL, the no-revenue / not-active boxes,
    and the first/second-week paycheck counts). The rep payout sheets live
    in G:N and are deliberately excluded. Renders the sheet's own PDF export
    so it looks exactly like the tab (fills, borders, fonts)."""
    import io

    import pypdfium2 as pdfium
    sh = _sheet()
    cm, week, locked, _reps, _total = _read_summary(sh)
    # last non-empty row in A:E, padded a little, so the capture tracks
    # roster growth instead of hardcoding row 80
    last = 44
    for i, row in enumerate(cm.get("A1:E200"), 1):
        if any(str(c).strip() for c in row):
            last = max(last, i)
    url = (f"https://docs.google.com/spreadsheets/d/{sh.id}/export"
           f"?format=pdf&gid={cm.id}&range=A1:E{last + 2}"
           "&portrait=true&fitw=true&gridlines=false&size=letter"
           "&fzr=false"  # don't repeat the frozen row on page 2+
           "&top_margin=0.25&bottom_margin=0.25"
           "&left_margin=0.25&right_margin=0.25")
    from automations.recruiting_report.fill import _client
    r = _client().http_client.request("get", url)
    r.raise_for_status()
    if "pdf" not in str(r.headers.get("content-type", "")):
        return {"error": "export did not return a PDF (auth scope?)"}
    pdf = pdfium.PdfDocument(io.BytesIO(r.content))
    from PIL import Image, ImageChops

    def _trim(im):  # cut white margins top/bottom (keep a little air)
        bbox = ImageChops.invert(im.convert("L")).getbbox()
        if not bbox:
            return None  # fully blank page
        pad = 20
        return im.crop((0, max(0, bbox[1] - pad),
                        im.width, min(im.height, bbox[3] + pad)))

    pages = [p for p in (_trim(pg.render(scale=200 / 72).to_pil())
                         for pg in pdf) if p is not None]
    if len(pages) == 1:
        img = pages[0]
    else:  # stitch trimmed pages vertically (roster outgrew one page)
        img = Image.new("RGB", (max(p.width for p in pages),
                                sum(p.height for p in pages)), "white")
        y = 0
        for p in pages:
            img.paste(p, (0, y))
            y += p.height
    img.save(path, "PNG")
    return {"path": path, "week": week, "locked": locked,
            "rows": last, "pages": len(pdf),
            "size": [img.width, img.height]}


def _webapp_refresh() -> str:
    import pathlib

    import requests
    cfg = (pathlib.Path(__file__).resolve().parents[2]
           / "vantura-payroll-webapp.json")
    try:
        url = json.loads(cfg.read_text()).get("webapp_url", "")
    except Exception:  # noqa: BLE001
        url = ""
    if not url:
        return "refresh skipped (no web-app config)"
    r = requests.get(url, params={"action": "refresh"}, timeout=600)
    r.raise_for_status()
    return f"refresh: {r.text[:80]}"


def apply(payload: str) -> dict:
    items = json.loads(payload)
    if not isinstance(items, list) or not items:
        return {"error": "apply needs a non-empty JSON list"}
    sh = _sheet()
    _cm, week, locked, reps, _total = _read_summary(sh)
    if locked:
        return {"error": f"week {week} is LOCKED — no changes possible"}

    roster = {_nrm(r["name"]): r["name"] for r in reps}
    # Name Aliases: alias -> canonical
    try:
        for row in sh.worksheet("Name Aliases").get_all_values():
            if len(row) > 1 and str(row[0]).strip() and str(row[1]).strip():
                canon = _nrm(row[1])
                if canon in roster:
                    roster.setdefault(_nrm(row[0]), roster[canon])
    except Exception:  # noqa: BLE001
        pass

    def resolve(name):
        n = _nrm(name)
        if n in roster:
            return roster[n]
        hits = {v for k, v in roster.items()
                if k.startswith(n + " ") or n.startswith(k + " ") or n in k}
        return hits.pop() if len(hits) == 1 else sorted(hits)

    resolved, problems = [], []
    for it in items:
        who = resolve(it.get("rep", ""))
        if isinstance(who, str):
            resolved.append((who, it))
        else:
            problems.append({"rep": it.get("rep"), "candidates": who})
    if problems:
        return {"error": "ambiguous/unknown rep(s) — NOTHING applied",
                "problems": problems}

    before = {r["name"]: r["paid"] for r in reps}
    adj = sh.worksheet("Adjustments")
    rows = []
    for who, it in resolved:
        typ = str(it.get("type", "Bonus")).strip() or "Bonus"
        if typ.upper() == "NOPAY":
            rows.append([week, who, "REMOVEALL", "",
                         str(it.get("label", "no pay (Slack review)"))])
        else:
            rows.append([week, who, "Bonus", float(it.get("amount", 0)),
                         str(it.get("label", "Bonus (Slack review)"))])
    adj.append_rows(rows, value_input_option="RAW")
    note = _webapp_refresh()
    time.sleep(6)
    _cm2, _w2, _l2, reps2, total2 = _read_summary(sh)
    after = {r["name"]: r["paid"] for r in reps2}
    touched = sorted({who for who, _ in resolved})
    return {"applied": len(rows), "refresh": note, "week": week,
            "changes": [{"rep": w, "before": before.get(w, "(not listed)"),
                         "after": after.get(w, "(removed — no pay)")}
                        for w in touched],
            "new_total": total2}


def npa(payload: str) -> dict:
    """Reimbursement -> one NPA Adjustments row (Carlos 2026-09-06, Slack
    /reimbursement flow; NO approval step by design — the #a-players-b2b post
    is the audit trail). NPA = added to the check UNTAXED, never mixed into
    commission (Payroll.gs sums Adjustments rows whose Type contains 'NPA'
    into Commission col E).

    payload: {"rep": "<slack real name>", "amount": 45.0, "label": "..."}
    Week rule: submitted Mon-Wed (CT) -> the week being built (last Sunday);
    Thu-Sun -> next build (the coming Sunday). Only refreshes the board when
    the target week is the one currently in B1."""
    import datetime as dt
    it = json.loads(payload)
    amount = float(it.get("amount", 0))
    if not (0 < amount <= 2000):
        return {"error": f"amount ${amount:,.2f} out of range (0-2000)"}
    label = str(it.get("label", "Reimbursement (Slack)")).strip()[:180]

    now = dt.datetime.now()  # laptop runs America/Chicago
    wd = now.weekday()  # Mon=0
    days_since_sunday = (wd + 1) % 7          # Sun=0 Mon=1 Tue=2 Wed=3 Thu=4...
    last_sunday = now.date() - dt.timedelta(days=days_since_sunday)
    # WE <last Sunday> is built Wed EOD (+3 days). On/before that -> this
    # build; Thu-Sat -> the coming Sunday's build.
    target = last_sunday if days_since_sunday <= 3 else \
        last_sunday + dt.timedelta(days=7)
    week_str = f"{float(f'{target.month}.{target.day}'):g}"

    sh = _sheet()
    cm, b1_week, locked, reps, _total = _read_summary(sh)
    if week_str == b1_week and locked:
        # board already locked for this build -> roll to the next check
        target += dt.timedelta(days=7)
        week_str = f"{float(f'{target.month}.{target.day}'):g}"

    # roster: Commission reps + Sales Board + Roll Call names, alias-bridged —
    # a rep with no line this week must still resolve.
    roster = {_nrm(r["name"]): r["name"] for r in reps}
    try:
        for r in sh.worksheet("Sales Board").get("B5:B60"):
            nm = str(r[0]).strip() if r else ""
            if nm:
                roster.setdefault(_nrm(nm), nm)
    except Exception:  # noqa: BLE001
        pass
    try:
        for r in sh.worksheet("Roll Call").get("D3:D400"):
            nm = str(r[0]).strip() if r else ""
            if nm:
                roster.setdefault(_nrm(nm), nm)
    except Exception:  # noqa: BLE001
        pass
    try:
        for row in sh.worksheet("Name Aliases").get_all_values():
            if len(row) > 1 and str(row[0]).strip() and str(row[1]).strip():
                canon = _nrm(row[1])
                if canon in roster:
                    roster.setdefault(_nrm(row[0]), roster[canon])
                else:
                    # alias may BE the canonical paid name even if not rostered
                    roster.setdefault(_nrm(row[0]), str(row[1]).strip())
    except Exception:  # noqa: BLE001
        pass

    n = _nrm(it.get("rep", ""))
    who = roster.get(n)
    if not who:
        hits = {v for k, v in roster.items()
                if k.startswith(n + " ") or n.startswith(k + " ")
                or (n and n in k)}
        # a fuzzy hit must be at least as specific as what was asked for —
        # a stray short cell ("carlos") must never swallow a full name.
        if len(hits) == 1 and len(_nrm(next(iter(hits)))) >= len(n):
            who = hits.pop()
        else:
            return {"error": "could not match rep name",
                    "candidates": sorted(hits)[:6], "rep": it.get("rep")}

    sh.worksheet("Adjustments").append_rows(
        [[week_str, who, "NPA", amount, label]], value_input_option="RAW")
    note = "queued for next build"
    if week_str == b1_week:
        note = _webapp_refresh()
    return {"ok": True, "rep": who, "week": week_str, "amount": amount,
            "refreshed": week_str == b1_week, "note": note}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if mode == "summary":
        print(json.dumps(summary()))
    elif mode == "xlsx":
        print(json.dumps(xlsx(sys.argv[2])))
    elif mode == "png":
        print(json.dumps(png(sys.argv[2])))
    elif mode == "apply":
        print(json.dumps(apply(sys.argv[2])))
    elif mode == "npa":
        print(json.dumps(npa(sys.argv[2])))
    else:
        print(json.dumps({"error": f"unknown mode {mode}"}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
