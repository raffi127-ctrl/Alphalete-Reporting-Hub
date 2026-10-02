"""Carlos office payroll pull — Apex (apex.herbjoyent.com) → "Payroll (Apex)" tab of
Carlos's Business & Personal P&L sheet.  Runs Thursdays 13:00 CT.

WHAT IT DOES
  1. Makes sure the dedicated Chrome (profile /tmp/carlos_apex_cdp_profile, CDP port
     9248) is running.  That profile holds Carlos's Apex login — he signed in there
     himself (2026-09-27).  NO credentials are ever typed by this code.
  2. Attaches over CDP, navigates IN-APP to Payroll → Payroll Entry.  Apex forces a
     "set up 2FA" interstitial on every full page load, so we never navigate by URL;
     we click the SPA link (a[href="/payrolls"]) which routes past the gate.
  3. Opens the pay-period dropdown (Kendo), picks the newest COMPLETED period
     (index 1 — index 0 is the week in progress), clicks Export, saves the CSV.
  4. Parses the CSV (sections Owner / Office Admins / Sales Reps, "Total," lines,
     "Company Total,") and upserts one row into 'Payroll (Apex)' keyed on period end.
  5. Never touches "Save & Recalculate" or "Submit Payroll".

  python -m automations.carlos_payroll_pull.run              # live
  python -m automations.carlos_payroll_pull.run --dry-run    # export + parse, no sheet write
  python -m automations.carlos_payroll_pull.run --period 2026-09-20   # a specific period end
  python -m automations.carlos_payroll_pull.run --backfill 8 # newest 8 completed periods

IF THE SESSION IS DEAD the page shows the Apex login form (USER NAME / PASSWORD).
We stop with exit 2 and a clear message: Carlos must sign in once in that Chrome
window (it is left open for him).  Same pattern as apex_payroll / ownerville.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PROFILE = os.environ.get("CARLOS_APEX_PROFILE", str(Path.home() / "Library/Application Support/carlos_payroll_pull/chrome_profile"))  # NOT /tmp: macOS wipes it and the login is lost
CDP_PORT = os.environ.get("CARLOS_APEX_PORT", "9248")
APEX_URL = "https://apex.herbjoyent.com/"
PNL_SHEET_ID = os.environ.get("CARLOS_PNL_SHEET_ID", "1ngQtKRNeuGV_FDBp-d9boZmxp6cO3T4IKa7k2NdiLq0")
TAB = "Payroll (Apex)"
DETAIL_TAB = "Apex Net Pay Detail"
DETAIL_HEADER = ["Period start", "Period end (Sun)", "Paid in week ending (Sat)", "Section", "Name", "Gross pay", "Net pay addition", "Net pay deduction", "Comment", "Kind", "Source file"]
OUT_DIR = Path(os.environ.get("CARLOS_APEX_OUT", str(Path.home() / "Library/Application Support/carlos_payroll_pull")))
TOKEN = Path.home() / ".config/recruiting-report/oauth-token.json"
PER = re.compile(r"(\d{2}/\d{2}/\d{4}).(\d{2}/\d{2}/\d{4})")
EPOCH = dt.date(1899, 12, 30)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}", flush=True)


# ----------------------------------------------------------------- browser
def _chrome_up() -> bool:
    r = subprocess.run(["pgrep", "-f", "carlos_payroll_pull/chrome_profile"], capture_output=True)
    return r.returncode == 0


def ensure_chrome() -> None:
    if _chrome_up():
        return
    log("Chrome not running on the Apex profile — launching")
    subprocess.Popen([CHROME, f"--user-data-dir={CDP_PROFILE}", "--profile-directory=Default",
                      f"--remote-debugging-port={CDP_PORT}", "--no-first-run", "--no-default-browser-check",
                      "--disable-sync", "--restore-last-session=false", "--disable-session-crashed-bubble",
                      "--disable-infobars", "--window-size=1600,1000", APEX_URL],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)


def period_on_page(page):
    try:
        m = PER.search(page.inner_text("body", timeout=5000))
        return (m.group(1), m.group(2)) if m else None
    except Exception:  # noqa: BLE001
        return None


def logged_out(page) -> bool:
    try:
        if page.locator('input[type="password"]').count() > 0:
            return True
        body = (page.inner_text("body", timeout=5000) or "").lower()
        return "please login" in body and "user name" in body
    except Exception:  # noqa: BLE001
        return False


def goto_payroll_entry(page) -> None:
    """In-app route to Payroll Entry (survives the 2FA interstitial)."""
    try:
        page.set_viewport_size({"width": 1600, "height": 1000})   # narrow windows get Apex's mobile layout: the menu covers the page
    except Exception:  # noqa: BLE001
        pass
    if period_on_page(page) and "/payrolls" in page.url:
        return
    page.goto(APEX_URL, wait_until="domcontentloaded")
    time.sleep(4)
    if logged_out(page):
        raise SystemExit("APEX SESSION EXPIRED — Carlos must sign in once in the Apex Chrome window "
                         "(profile /tmp/carlos_apex_cdp_profile). Nothing was typed by this job.")
    _dismiss_modal(page)
    page.evaluate("""() => { const a = document.querySelector('a[href="/payrolls"]'); a && a.click(); }""")
    for _ in range(40):
        if period_on_page(page):
            return
        time.sleep(1)
    raise RuntimeError("Payroll Entry did not load (no pay-period text on page)")


def _dismiss_modal(page) -> None:
    """Apex shows a 'set up 2FA' modal on fresh sessions; it swallows clicks until closed."""
    try:
        btn = page.locator('button:has-text("Close")')
        if btn.count() and btn.first.is_visible():
            btn.first.click(); time.sleep(1)
    except Exception:  # noqa: BLE001
        pass


def _collapse_sidebar(page) -> None:
    """After a fresh sign-in the left menu is expanded and overlaps the pay-period picker."""
    try:
        page.evaluate("""() => { const el = Array.from(document.querySelectorAll('div,button,a,span'))
            .find(e => e.children.length < 3 && /COLLAPSE MENU/i.test(e.innerText || '')); if (el) el.click(); }""")
        time.sleep(1)
    except Exception:  # noqa: BLE001
        pass


def _open_dropdown(page):
    _dismiss_modal(page)
    _collapse_sidebar(page)
    wrap = page.locator('span.k-dropdown[aria-owns$="_listbox"]').first
    try:
        wrap.click(timeout=10000)
    except Exception:  # noqa: BLE001
        wrap.scroll_into_view_if_needed(); wrap.click(force=True, timeout=10000)
    time.sleep(1.2)
    owns = wrap.get_attribute("aria-owns") or ""
    items = page.locator(f'[id="{owns}"] li') if owns else page.locator("ul[role=listbox]:visible li")   # ids start with a digit → attribute selector
    try:
        items.first.wait_for(state="visible", timeout=6000)
    except Exception:  # noqa: BLE001                                 # popup did not open — click once more
        wrap.click(force=True, timeout=10000)
        items.first.wait_for(state="visible", timeout=8000)
    return items


def list_periods(page):
    """Open the Kendo dropdown, return [(index, start, end)] for every entry, close it."""
    _open_dropdown(page)
    time.sleep(1.2)
    items = page.locator("ul[role=listbox] li")
    out = []
    for i in range(items.count()):
        m = PER.search(items.nth(i).inner_text())
        if m:
            out.append((i, dt.datetime.strptime(m.group(1), "%m/%d/%Y").date(),
                        dt.datetime.strptime(m.group(2), "%m/%d/%Y").date()))
    page.keyboard.press("Escape")
    time.sleep(0.5)
    return out


def export_period(page, idx: int, end: dt.date) -> Path:
    items = _open_dropdown(page)
    items.nth(idx).click(force=True, timeout=15000)
    want = end.strftime("%m/%d/%Y")
    for _ in range(60):
        pr = period_on_page(page)
        if pr and pr[1] == want:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(f"pay period did not switch to {want}")
    time.sleep(1.5)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with page.expect_download(timeout=60000) as dl:
        page.get_by_role("button", name="Export").first.click()
    d = dl.value
    path = OUT_DIR / f"Payroll_{end.isoformat()}.csv"
    d.save_as(str(path))
    return path


# ----------------------------------------------------------------- parse / sheet
DRAW_RE = re.compile(r"draw|distribution|dividend", re.I)


def parse_apex(path: Path) -> tuple[tuple[dt.date, dt.date], dict]:
    """Section totals from an Apex export. Gross per section, plus Net Pay Additions split into
    owner draws (comment says draw/distribution/dividend) vs everything else (reimbursements,
    road trips, supplies, rep bonuses), plus Net Pay Deductions."""
    import csv as _csv
    tot = {"Owner": 0.0, "Office Admins": 0.0, "Sales Reps": 0.0, "Contractors": 0.0, "Company": 0.0,
           "OwnerDraw": 0.0, "OwnerOther": 0.0, "AdminAdd": 0.0, "RepAdd": 0.0, "Deduct": 0.0}
    sec = None
    hdr = None
    per = None
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        t = line.strip()
        if t.startswith("Pay Period,"):
            a, b = t.split(",", 1)[1].split(" - ")
            per = (dt.datetime.strptime(a.strip(), "%m/%d/%Y").date(), dt.datetime.strptime(b.strip(), "%m/%d/%Y").date())
        elif t in ("Owner", "Office Admins", "Sales Reps", "Contractors"):
            sec = t; hdr = None
        elif t.startswith("Total,") and sec:
            tot[sec] = float(t.split(",")[1]); sec = None; hdr = None
        elif t.startswith("Company Total,"):
            tot["Company"] = float(t.split(",")[1])
        elif sec and hdr is None and t.startswith("First Name"):
            hdr = next(_csv.reader([t]))
        elif sec and hdr and t:
            d = dict(zip(hdr, next(_csv.reader([t]))))
            add = float(d.get("Net Pay Addition") or 0); ded = float(d.get("Net Pay Deduction") or 0)
            tot["Deduct"] += ded
            if sec == "Owner":
                if DRAW_RE.search(d.get("Comments", "") or ""): tot["OwnerDraw"] += add
                else: tot["OwnerOther"] += add
            elif sec == "Office Admins": tot["AdminAdd"] += add
            else: tot["RepAdd"] += add
    if not per:
        raise RuntimeError(f"no Pay Period header in {path}")
    return per, tot


def parse_apex_people(path: Path) -> list[list]:
    """One row per person with a net-pay addition or deduction (who got what, and why)."""
    import csv as _csv
    per, _ = parse_apex(path)
    start, end = per
    land = end + dt.timedelta(days=6)
    out = []
    sec = None; hdr = None
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        t = line.strip()
        if t in ("Owner", "Office Admins", "Sales Reps", "Contractors"):
            sec = t; hdr = None
        elif t.startswith("Total,") or t.startswith("Company Total"):
            sec = None; hdr = None
        elif sec and hdr is None and t.startswith("First Name"):
            hdr = next(_csv.reader([t]))
        elif sec and hdr and t:
            d = dict(zip(hdr, next(_csv.reader([t]))))
            add = float(d.get("Net Pay Addition") or 0); ded = float(d.get("Net Pay Deduction") or 0)
            if not add and not ded:
                continue
            name = f"{(d.get('First Name') or '').strip().title()} {(d.get('Last Name') or '').strip().title()}".strip()
            comment = (d.get("Comments", "") or "").strip()
            kind = "Owner draw" if (sec == "Owner" and DRAW_RE.search(comment)) else "Reimbursement / extra"
            out.append([(start - EPOCH).days, (end - EPOCH).days, (land - EPOCH).days, sec, name, float(d.get("Gross Pay") or 0), add, ded, comment, kind, path.name])
    return out


def upsert_people(svc, path: Path, dry_run: bool) -> str:
    rows = parse_apex_people(path)
    if dry_run:
        return f"DRY-RUN {len(rows)} net-pay detail rows: " + "; ".join(f"{r[4]} {r[6]:,.2f} ({r[8][:20]})" for r in rows[:6])
    vals = svc.values().get(spreadsheetId=PNL_SHEET_ID, range=f"'{DETAIL_TAB}'!A1:K3000", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if not vals:
        vals = [DETAIL_HEADER]
    pend = rows[0][1] if rows else None
    keep = [r for r in vals[1:] if not (len(r) > 1 and r[1] == pend)]
    new = sorted(keep + rows, key=lambda r: (r[1], r[3], r[4]), reverse=True)
    svc.values().clear(spreadsheetId=PNL_SHEET_ID, range=f"'{DETAIL_TAB}'!A1:K3000").execute()
    svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{DETAIL_TAB}'!A1:K{len(new) + 1}", valueInputOption="RAW", body={"values": [DETAIL_HEADER] + new}).execute()
    return f"net-pay detail: {len(rows)} rows for period ending {dt.date.fromordinal(EPOCH.toordinal() + pend) if pend else '-'} ({len(new)} total)"


def _sheets():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.load(open(TOKEN)))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("sheets", "v4", credentials=creds).spreadsheets()


def upsert_row(per, tot, fname: str, dry_run: bool) -> str:
    start, end = per
    row = [(start - EPOCH).days, (end - EPOCH).days, (end + dt.timedelta(days=6) - EPOCH).days,
           tot["Owner"], tot["Office Admins"], tot["Sales Reps"], tot["Company"],
           round(tot["Sales Reps"] / tot["Company"], 4) if tot["Company"] else 0, fname,
           round(tot["OwnerDraw"], 2), round(tot["OwnerOther"], 2), round(tot["AdminAdd"], 2), round(tot["RepAdd"], 2), round(tot["Deduct"], 2)]
    if dry_run:
        return f"DRY-RUN would upsert {end}: {row[3:8]}"
    svc = _sheets()
    vals = svc.values().get(spreadsheetId=PNL_SHEET_ID, range=f"'{TAB}'!A1:N400",
                            valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    key = (end - EPOCH).days
    for i, r in enumerate(vals[1:], start=2):
        if len(r) > 1 and r[1] == key:
            svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{TAB}'!A{i}:N{i}",
                                valueInputOption="RAW", body={"values": [row]}).execute()
            return f"updated row {i} for period ending {end}"
    # newest-first table: insert at row 2 (push the rest down)
    meta = svc.get(spreadsheetId=PNL_SHEET_ID, fields="sheets.properties").execute()
    sid = next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == TAB)
    svc.batchUpdate(spreadsheetId=PNL_SHEET_ID, body={"requests": [{"insertDimension": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 1, "endIndex": 2}, "inheritFromBefore": False}}]}).execute()
    svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{TAB}'!A2:N2",
                        valueInputOption="RAW", body={"values": [row]}).execute()
    return f"inserted new row for period ending {end}"


# ----------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--period", help="period END date YYYY-MM-DD (Sunday)")
    ap.add_argument("--backfill", type=int, default=0, help="newest N completed periods")
    args = ap.parse_args(argv)

    ensure_chrome()
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[-1] if ctx.pages else ctx.new_page()
        goto_payroll_entry(page)
        log(f"Payroll Entry ready: {page.url} period {period_on_page(page)}")
        periods = list_periods(page)
        if not periods:
            raise RuntimeError("no pay periods in dropdown")
        today = dt.date.today()
        completed = [pp for pp in periods if pp[2] < today]  # end date before today
        if args.period:
            want = dt.date.fromisoformat(args.period)
            targets = [pp for pp in periods if pp[2] == want]
            if not targets:
                raise SystemExit(f"period ending {want} not in dropdown")
        elif args.backfill:
            targets = completed[: args.backfill]
        else:
            targets = completed[:1]
        results = []
        for idx, start, end in targets:
            path = export_period(page, idx, end)
            per, tot = parse_apex(path)
            log(f"exported {path.name}: reps {tot['Sales Reps']:,.2f} admins {tot['Office Admins']:,.2f} "
                f"owner {tot['Owner']:,.2f} company {tot['Company']:,.2f}")
            results.append(upsert_row(per, tot, path.name, args.dry_run))
            results.append(upsert_people(_sheets() if not args.dry_run else None, path, args.dry_run))
        for r in results:
            log(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
