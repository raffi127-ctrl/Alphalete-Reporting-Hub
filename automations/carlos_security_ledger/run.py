"""Carlos Business Security ledger — Tableau (NetSuite Security Ledger SFDC) → 'Security Ledger'
tab of Carlos's Business & Personal P&L sheet.  Runs DAILY (the ledger itself updates weekly).

HOW
  * Real Chrome over CDP with a COPY of Carlos's everyday Chrome profile (logged into
    Tableau Cloud as him).  Profile dir /tmp/carlos_tableau_cdp_profile, port 9249 —
    separate from vantura_churn (9246) / resume_pushing (9245) / apex (9247 / 9248).
    Read-only on the source profile; nothing is typed into any login.
  * View: OverridesICDView / NETSUITE SECURITY LEDGER SFDC.  Download → Crosstab of
    'Transaction Details' (all ICDs; we keep Carlos's rows) and 'SFDC Total Balance'.
  * Rows are classified (override credits by campaign, payouts to bank, transfers to
    other ICDs, fees, bonuses) and the whole tab is rewritten newest-first.

  python -m automations.carlos_security_ledger.run            # live
  python -m automations.carlos_security_ledger.run --dry-run  # download + classify, no write
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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CDP_PROFILE = "/tmp/carlos_tableau_cdp_profile"
CDP_PORT = "9249"
VIEW = "https://us-east-1.online.tableau.com/#/site/sci/views/OverridesICDView/NETSUITESECURITYLEDGERSFDC"
PNL_SHEET_ID = os.environ.get("CARLOS_PNL_SHEET_ID", "1ngQtKRNeuGV_FDBp-d9boZmxp6cO3T4IKa7k2NdiLq0")
TAB = "Security Ledger"
CAP_TAB = "Captain Bonus (Tableau)"
OVR_TAB = "Override Weekly (Tableau)"
OVR_HEADER = ["Week (Sun)", "P&L week ending (Sat)", "Period", "Standard override", "Pulled", "Source"]
OVR_SOURCE = "Tableau → Overrides ICD View → ORG Override Summary (Carlos Hidalgo, all campaign rows)"
TILLER_ID = "1D2mjKSRNCM3fleq8e7uJyRuIotVqMfEW6baC7DV9fAE"
BAL_TAB = "Balances"
HUB_WB = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"   # Alphalete Org/Captainship Reports (override_bulletin fills it weekly from Tableau)
HUB_OVR_TAB = "Org Overrides Ongoing Report"
HUB_DD_TAB = "Org DDs Ongoing Report"
CAP_HEADER = ["DD week (Sun)", "Lands in P&L week ending (Sat)", "Captain's Bonus", "DD total to ICD (Tableau)", "Live Tableau check (current week)", "Source", "Pulled"]
DD_VIEW = "https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/DDDETAIL"
DD_ORG_VIEW = "https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/DDDETAILORG"
CAP_RE = re.compile(r"captain'?s?\s*bonus", re.I)
OUT_DIR = Path.home() / "Library/Application Support/carlos_security_ledger"
TOKEN = Path.home() / ".config/recruiting-report/oauth-token.json"
OWNER = "carlos hidalgo"
EPOCH = dt.date(1899, 12, 30)
HEADER = ["Date", "Explanation", "Kind", "Campaign", "Amount", "Running balance", "Document", "Week ending (Sat)", "Month", "Pulled"]


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}", flush=True)


def money(s) -> float:
    s = str(s).replace("$", "").replace(",", "").strip()
    neg = s.startswith("-") or s.startswith("(")
    v = float(re.sub(r"[^\d.]", "", s) or 0)
    return -v if neg else v


def classify(expl: str, amt: float) -> tuple[str, str]:
    e = re.sub(r"\s+", " ", expl.lower()).strip()   # Tableau text carries double spaces ("Wire security  payment")
    camp = ""
    m = re.search(r"override[s]?\s*-\s*(.+)$", expl, re.I) or re.search(r"overrides\s{2,}(.+)$", expl, re.I)
    if m:
        camp = m.group(1).strip()
    if "credico" in e:
        return "Override - Credico", "Credico"
    if "special override" in e:
        return "Override - Special", camp or "Special"
    if "standard override" in e or "std or" in e:
        return "Override - Standard", camp
    if "wire fee" in e or "ach fee" in e or e.endswith(" fee") or " fee " in e:
        return "Fee", ""
    if "security payment" in e or "sec draw" in e or ("wire" in e and "payment" in e):
        return "Payout to bank", ""
    if "security transfer" in e or "autho " in e or "sec dep" in e or "balance transfe" in e:
        return ("Transfer out (to other ICD / account)" if amt < 0 else "Transfer in"), ""
    if "bonus" in e or "r&r" in e:
        return "Bonus", camp
    if "burn" in e or "chargeback" in e or "deduct" in e:
        return "Deduction", ""
    return ("Other credit" if amt > 0 else "Other debit"), ""


def pull_hub() -> tuple[list[list], float]:
    """Lucy path: the Hub's shared Tableau session (ownerville SSO), no Chrome profile copy.
    Uses the ORG DD Detail view (that login sees every captain) and keeps Carlos's rows."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.override_bulletin.pulls import read_crosstab
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    det = OUT_DIR / "Transaction_Details.csv"
    bal = OUT_DIR / "SFDC_Total_Balance.csv"
    download_crosstab_patchright(VIEW, "Transaction Details", det, verbose=False)
    download_crosstab_patchright(VIEW, "SFDC Total Balance", bal, verbose=False)
    try:
        download_crosstab_patchright(DD_ORG_VIEW, "ORG DD Detail", OUT_DIR / "DD_Detail.csv", verbose=False)
    except Exception as e:  # noqa: BLE001
        log(f"ORG DD Detail download failed (captain bonus not updated this run): {str(e)[:120]}")
    rows = read_crosstab(det)
    hdr = rows[0]
    ix = {h: i for i, h in enumerate(hdr)}
    out = [r for r in rows[1:] if OWNER in str(r[ix["ICD Owner Name and OFFICE NAME"]]).lower() and r[ix["Date"]] != "Total"]
    balance = None
    for r in read_crosstab(bal)[1:]:
        if len(r) > 2 and OWNER in str(r[1]).lower():
            balance = money(r[2])
    return [hdr] + out, balance


def pull() -> tuple[list[list], float]:
    from patchright.sync_api import sync_playwright
    from automations.vantura_churn import cdp_pull as cp
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    from automations.override_bulletin.pulls import read_crosstab

    cp.CDP_PROFILE = CDP_PROFILE
    cp.CDP_PORT = CDP_PORT
    subprocess.run(["pkill", "-f", "carlos_tableau_cdp_profile"], capture_output=True)
    time.sleep(1)
    cp._copy_default_profile()
    proc = cp._launch(VIEW)
    log(f"launched real Chrome pid={proc.pid}")
    time.sleep(25)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    det = OUT_DIR / "Transaction_Details.csv"
    bal = OUT_DIR / "SFDC_Total_Balance.csv"
    try:
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            page = b.contexts[0].pages[0]
            for _ in range(30):
                if "tableau.com/#/site" in page.url and "signin" not in page.url.lower():
                    break
                time.sleep(2)
            try:
                log(f"landed on: {page.url[:110]} | title: {page.title()[:70]}")
            except Exception:  # noqa: BLE001
                pass
            if "signin" in page.url.lower() or "login" in page.url.lower() or "sso." in page.url.lower() or "idp" in page.url.lower():
                raise SystemExit("TABLEAU SESSION MISSING — Carlos's everyday Chrome is no longer signed into "
                                 "Tableau Cloud. He must sign in there once; nothing is typed by this job.")
            drive_crosstab_dialog(page, VIEW, "Transaction Details", det, verbose=False)
            drive_crosstab_dialog(page, VIEW, "SFDC Total Balance", bal, verbose=False)
            try:
                drive_crosstab_dialog(page, DD_VIEW, "ICD dd Detail", OUT_DIR / "DD_Detail.csv", verbose=False)
            except Exception as e:  # noqa: BLE001
                log(f"DD Detail download failed (captain bonus not updated this run): {str(e)[:120]}")
    finally:
        subprocess.run(["pkill", "-f", "carlos_tableau_cdp_profile"], capture_output=True)
    rows = read_crosstab(det)
    hdr = rows[0]
    ix = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rows[1:]:
        if OWNER not in str(r[ix["ICD Owner Name and OFFICE NAME"]]).lower() or r[ix["Date"]] == "Total":
            continue
        out.append(r)
    balance = None
    for r in read_crosstab(bal)[1:]:
        if len(r) > 2 and OWNER in str(r[1]).lower():
            balance = money(r[2])
    return [hdr] + out, balance


def to_rows(raw: list[list]) -> list[list]:
    hdr = raw[0]
    ix = {h: i for i, h in enumerate(hdr)}
    today = dt.date.today()
    recs = []
    for r in raw[1:]:
        d = dt.datetime.strptime(r[ix["Date"]], "%m/%d/%Y").date()
        amt = money(r[ix["Transaction Amount"]])
        expl = str(r[ix["NS_Explanation__c"]]).strip()
        kind, camp = classify(expl, amt)
        we = d + dt.timedelta(days=(5 - d.weekday()) % 7)          # Saturday
        recs.append(((d - EPOCH).days, expl, kind, camp, amt, money(r[ix["NS Running Balance"]]),
                     str(r[ix["NS_Document_Number__c"]]), (we - EPOCH).days, d.strftime("%Y-%m"), today.isoformat(),
                     int(str(r[ix["Row no"]]) or 0)))
    recs.sort(key=lambda x: (x[0], x[10]), reverse=True)
    return [list(x[:10]) for x in recs]


def captain_rows(path: Path) -> list[list]:
    """[[dd_week_serial, captain_bonus, grand_total_to_icd, landing_week_serial, pulled]] from an ICD dd Detail crosstab."""
    from automations.override_bulletin.pulls import read_crosstab, _num_locale
    if not path.exists():
        return []
    rows = read_crosstab(path)
    hdr = rows[0]
    ix = {h: i for i, h in enumerate(hdr)}
    wk = next((i for h, i in ix.items() if "DD Week" in h), None)
    tc = next((i for h, i in ix.items() if "Total $ to ICD" in h), None)
    if wk is None or tc is None:
        return []
    by_week: dict = {}
    grand = None
    for r in rows[1:]:
        if len(r) <= max(wk, tc):
            continue
        amt = _num_locale(r[tc]) or 0.0
        if "grand total" in str(r[0]).lower():          # its DD Week cell reads "Total"
            grand = amt
            continue
        try:
            d = dt.datetime.strptime(r[wk], "%m/%d/%Y").date()
        except ValueError:
            continue
        if OWNER not in str(r[1]).lower():
            continue
        e = by_week.setdefault(d, {"cap": 0.0, "gt": 0.0})
        e["gt"] += amt                                        # Carlos's total to ICD that DD week (= the Thursday deposit)
        if any(CAP_RE.search(str(c)) for c in r):
            e["cap"] += amt
    out = []
    for d, e in sorted(by_week.items(), reverse=True):
        land = d + dt.timedelta(days=7)          # DD week (Sat) → paid the next Thursday → P&L week ending the following Sat
        out.append([(d - EPOCH).days, round(e["cap"], 2), round(e["gt"], 2), (land - EPOCH).days, dt.date.today().isoformat()])
    return out


def _label_date(lbl: str):
    m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*$", str(lbl))
    if not m:
        return None
    y = int(m.group(3)); y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def hub_captain_history(svc) -> dict:
    """{dd_week_sunday: {'cap': x, 'dd': y}} from the Hub workbook, which override_bulletin fills every week
    straight from Tableau (DD DETAIL ORG → Captain's Bonus row; Org DDs → Grand Total to ICD)."""
    ov = svc.values().get(spreadsheetId=HUB_WB, range=f"'{HUB_OVR_TAB}'!A1:DZ200", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
    out: dict = {}
    hdr = None
    in_cap = False
    for i, r in enumerate(ov):
        a = str(r[0]).strip().lower() if r else ""
        if "captain/special overrides only" in a:
            in_cap = True; hdr = r; continue
        if in_cap and a == "carlos hidalgo":
            nxt = ov[i + 1] if i + 1 < len(ov) else []
            if nxt and "captain override" in str(nxt[0]).lower():
                for j, lbl in enumerate(hdr):
                    d = _label_date(lbl)
                    if d and j < len(nxt) and str(nxt[j]).strip():
                        out.setdefault(d, {})["cap"] = money(nxt[j])
            break
    dd = svc.values().get(spreadsheetId=HUB_WB, range=f"'{HUB_DD_TAB}'!A1:DZ200", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
    if dd:
        hdr = dd[0]
        for r in dd[1:]:
            if r and str(r[0]).strip().lower().startswith("carlos hidalgo"):
                for j, lbl in enumerate(hdr):
                    d = _label_date(lbl)
                    if d and j < len(r) and str(r[j]).strip():
                        out.setdefault(d, {})["dd"] = money(r[j])
                break
    return out


def write_captain_table(svc, live_rows: list[list]) -> str:
    """Rewrite the Captain Bonus tab: every week the Hub captured from Tableau, plus the live DD Detail
    figure for the current week as a cross-check."""
    hist = hub_captain_history(svc)
    live = {dt.date.fromordinal(EPOCH.toordinal() + r[0]) + dt.timedelta(days=1): r[1] for r in live_rows}  # DD week Sat → Sun label
    rows = []
    for d in sorted(set(hist) | set(live), reverse=True):
        h = hist.get(d, {})
        cap = h.get("cap")
        lv = live.get(d)
        if cap is None and lv is not None:
            cap = lv
        src = "Tableau DD Detail (Hub weekly capture)" if "cap" in h else "Tableau DD Detail (live pull)"
        rows.append([(d - EPOCH).days, (d + dt.timedelta(days=6) - EPOCH).days, cap if cap is not None else 0,
                     h.get("dd", ""), lv if lv is not None else "", src, dt.date.today().isoformat()])
    svc.values().clear(spreadsheetId=PNL_SHEET_ID, range=f"'{CAP_TAB}'!A1:G400").execute()
    svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{CAP_TAB}'!A1:G{len(rows) + 1}", valueInputOption="RAW",
                        body={"values": [CAP_HEADER] + rows}).execute()
    mism = [r for r in rows if r[4] != "" and abs(float(r[4]) - float(r[2])) > 0.01]
    return f"captain table: {len(rows)} weeks; live-vs-Hub mismatches: {len(mism)}" + (f" {mism[0][:5]}" if mism else "")


def upsert_captain(svc, rows: list[list]) -> str:
    if not rows:
        return "no captain rows"
    vals = svc.values().get(spreadsheetId=PNL_SHEET_ID, range=f"'{CAP_TAB}'!A1:E400", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    have = {r[0]: i + 1 for i, r in enumerate(vals) if i > 0 and r and isinstance(r[0], (int, float))}
    msgs = []
    for row in rows:
        if row[0] in have:
            svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{CAP_TAB}'!A{have[row[0]]}:E{have[row[0]]}", valueInputOption="RAW", body={"values": [row]}).execute()
            msgs.append(f"updated DD week {dt.date.fromordinal(EPOCH.toordinal() + row[0])}: captain {row[1]:,.2f}")
        else:
            svc.values().append(spreadsheetId=PNL_SHEET_ID, range=f"'{CAP_TAB}'!A1:E1", valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
            msgs.append(f"added DD week {dt.date.fromordinal(EPOCH.toordinal() + row[0])}: captain {row[1]:,.2f}")
    return "; ".join(msgs)


def update_balances(svc) -> str:
    """Copy each account's Last Balance from the Tiller Accounts tab into Balances!C (rows keyed by account # in col E)."""
    acc = svc.values().get(spreadsheetId=TILLER_ID, range="Accounts!A1:R100", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if not acc:
        return "tiller accounts: nothing read"
    hdr = acc[0]
    ib = hdr.index("Last Balance"); ia = hdr.index("Account #"); iu = hdr.index("Last Update") if "Last Update" in hdr else None
    def _k(v):   # account numbers with a leading zero (0573, 0021, 0253) come back as 573 / 21 / 253 from one side or the other
        t = str(v).strip().split(".")[0]
        return t.zfill(4) if t.isdigit() else t
    tb = {_k(r[ia]): (r[ib], r[iu] if iu is not None and iu < len(r) else "") for r in acc[1:] if len(r) > max(ib, ia) and str(r[ia]).strip()}
    rows = svc.values().get(spreadsheetId=PNL_SHEET_ID, range=f"'{BAL_TAB}'!A1:E60", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    data = []
    n = 0
    for i, r in enumerate(rows, start=1):
        key = _k(r[4]) if len(r) > 4 and str(r[4]).strip() else ""
        if key in tb:
            data.append({"range": f"'{BAL_TAB}'!C{i}", "values": [[tb[key][0]]]}); n += 1
    if data:
        data.append({"range": f"'{BAL_TAB}'!H1", "values": [[f"Tiller balances as of {dt.date.today().isoformat()}"]]})
        svc.values().batchUpdate(spreadsheetId=PNL_SHEET_ID, body={"valueInputOption": "RAW", "data": data}).execute()
    expected = sum(1 for r in rows[1:] if len(r) > 4 and str(r[4]).strip())
    if n < expected:
        log(f"WARNING balances: only {n} of {expected} account rows matched Tiller — check account numbers on the Balances tab")
    return f"balances: {n} of {expected} accounts updated from Tiller"


def override_weeks(rows: list[list]) -> dict:
    """{week serial: amount} for Carlos from one ORG Override Summary crosstab (all his campaign rows summed per week column)."""
    from automations.override_bulletin.pulls import _WK_HDR, _num_locale
    cols = {}
    hdr_row = None
    for ri, r in enumerate(rows[:6]):
        for ci, c in enumerate(r):
            m = _WK_HDR.match(str(c).strip())
            if m:
                y = int(m.group(3)); y += 2000 if y < 100 else 0
                cols[ci] = dt.date(y, int(m.group(1)), int(m.group(2))).toordinal() - EPOCH.toordinal()
                hdr_row = ri
        if cols:
            break
    out, mine, seen = {}, False, False
    for r in rows[(hdr_row or 0) + 1:]:
        name = str(r[0]).strip() if r else ""
        if name:
            mine = name.lower().split("[")[0].split("(")[0].strip() == OWNER
        if not mine:
            continue
        seen = True
        for ci, wk in cols.items():
            v = _num_locale(r[ci]) if ci < len(r) else None
            if v is not None:
                out[wk] = round(out.get(wk, 0.0) + v, 2)
    return out if seen else {}


def pull_overrides_hub(periods: list[int]) -> list[list]:
    """[week serial, period label, amount] per (week, period) from Tableau. A week near a month edge sits in two periods; both count."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.override_bulletin.pulls import read_crosstab, _with_filter, ORG_SUMMARY_VIEW, ORG_SUMMARY_SHEET
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for n in periods:
        label = f"Period {dt.date.today().year}-{n}"
        path = OUT_DIR / f"Override_Summary_P{n}.csv"
        try:
            download_crosstab_patchright(_with_filter(ORG_SUMMARY_VIEW, "Period", label), ORG_SUMMARY_SHEET, path, verbose=False)
            got = override_weeks(read_crosstab(path))
        except Exception as e:  # noqa: BLE001
            log(f"override summary {label}: no crosstab ({str(e)[:90]})")
            continue
        log(f"override summary {label}: {len(got)} weeks" + (f", newest {dt.date.fromordinal(EPOCH.toordinal() + max(got))} = {got[max(got)]:,.2f}" if got else ""))
        out += [[wk, label, amt] for wk, amt in got.items()]
    return out


def write_overrides(svc, via_hub: bool) -> str:
    """Upsert the weekly standard override by (week, period). First run backfills every period of the year."""
    have = svc.values().get(spreadsheetId=PNL_SHEET_ID, range=f"'{OVR_TAB}'!A2:F", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    have = [r for r in have if len(r) >= 4 and isinstance(r[0], (int, float))]
    if not via_hub:
        return f"override weekly: skipped (Lucy pulls it); {len(have)} rows on the tab"
    m = dt.date.today().month
    periods = list(range(1, min(13, m + 1) + 1)) if not have else [x for x in (m - 1, m, m + 1) if 1 <= x <= 13]
    fresh = pull_overrides_hub(periods)
    if not fresh:
        return "override weekly: Tableau returned nothing this run — tab left as is"
    today = dt.date.today().isoformat()
    keep = {(r[0], r[2]): r for r in have}
    for wk, label, amt in fresh:
        keep[(wk, label)] = [wk, wk + 6, label, amt, today, OVR_SOURCE]
    rows = sorted(keep.values(), key=lambda r: (-r[0], str(r[2])))
    svc.values().clear(spreadsheetId=PNL_SHEET_ID, range=f"'{OVR_TAB}'!A2:F2000").execute()
    svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{OVR_TAB}'!A1:F{len(rows) + 1}", valueInputOption="RAW",
                        body={"values": [OVR_HEADER] + rows}).execute()
    return f"override weekly: {len(fresh)} week-rows refreshed from periods {periods}; {len(rows)} on the tab"


def write(rows: list[list], balance: float | None, via_hub: bool = False) -> None:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.load(open(TOKEN)))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    svc = build("sheets", "v4", credentials=creds).spreadsheets()
    svc.values().clear(spreadsheetId=PNL_SHEET_ID, range=f"'{TAB}'!A1:J3000").execute()
    svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{TAB}'!A1:J{len(rows) + 1}", valueInputOption="RAW",
                        body={"values": [HEADER] + rows}).execute()
    note = [["Security balance (SFDC Total Balance)", balance if balance is not None else "", "as of", dt.date.today().isoformat()]]
    svc.values().update(spreadsheetId=PNL_SHEET_ID, range=f"'{TAB}'!L1:O1", valueInputOption="RAW", body={"values": note}).execute()
    log(write_captain_table(svc, captain_rows(OUT_DIR / "DD_Detail.csv")))
    log(update_balances(svc))
    try:
        log(write_overrides(svc, via_hub))
    except Exception as e:  # noqa: BLE001
        log(f"override weekly failed (rest of the run is fine): {str(e)[:160]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-files", action="store_true", help="skip Tableau; reuse the last downloaded CSVs")
    import getpass
    default_via = os.environ.get("CARLOS_TABLEAU_VIA") or ("hub" if getpass.getuser().lower().startswith("lucy") else "chrome")
    ap.add_argument("--via", choices=["chrome", "hub"], default=default_via, help="chrome = copy Carlos's Chrome Tableau session (his Mac); hub = the Hub's shared Tableau session (Lucy)")
    args = ap.parse_args(argv)
    log(f"tableau via: {args.via}")
    if args.from_files:
        from automations.override_bulletin.pulls import read_crosstab
        rows = read_crosstab(OUT_DIR / "Transaction_Details.csv")
        hdr = rows[0]; ix = {h: i for i, h in enumerate(hdr)}
        raw = [hdr] + [r for r in rows[1:] if OWNER in str(r[ix["ICD Owner Name and OFFICE NAME"]]).lower() and r[ix["Date"]] != "Total"]
        balance = None
        for r in read_crosstab(OUT_DIR / "SFDC_Total_Balance.csv")[1:]:
            if len(r) > 2 and OWNER in str(r[1]).lower():
                balance = money(r[2])
    else:
        raw, balance = pull_hub() if args.via == "hub" else pull()
    rows = to_rows(raw)
    log(f"{len(rows)} Carlos ledger rows; newest {rows[0][1][:50] if rows else '-'}; balance {balance}")
    if args.dry_run:
        for c in captain_rows(OUT_DIR / "DD_Detail.csv"): log(f"  captain: DD week {dt.date.fromordinal(EPOCH.toordinal()+c[0])} bonus {c[1]:,.2f} grand {c[2]:,.2f}")
        for r in rows[:5]:
            log(f"  {r[1][:50]:50s} {r[2]:22s} {r[4]:>12,.2f}")
        return 0
    write(rows, balance, via_hub=(args.via == "hub" and not args.from_files))
    log(f"wrote '{TAB}' ({len(rows)} rows) + balance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
