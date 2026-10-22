"""Weekly bank-account totals for Carlos + Raf ("Weekly Totals 24-26" tab).

Mirrors the Loom steps:
  1. add  -> insert a fresh column B (copy of last week: formats + total formulas), set the WE header,
             clear the typed numbers but keep the formula rows and the carried rows (Raf Debt, etc.)
  tiller -> pull bank/card balances from Tiller into <who>_<date>.json (Carlos today; Raf once he has Tiller)
  tableau -> Business Security for both (Hub's Tableau session)
  payout  -> Raf's Payout toward CC = his CC payments table (Q:S) summed for the Mon–Sun week
  2. fill -> write balances by ROW LABEL from a JSON file  {"Personal": 7458.42, ...}
  3. shot -> export the header + last 4 weeks as a PNG for Slack

  python -m automations.rc_bank_totals.run add  --who carlos [--we 2026-10-25] [--dry-run]
  python -m automations.rc_bank_totals.run tiller --who carlos
  python -m automations.rc_bank_totals.run tableau
  python -m automations.rc_bank_totals.run payout [--we 2026-10-25]
  python -m automations.rc_bank_totals.run fill --who carlos --values output/rc_bank_totals/carlos_<date>.json [--dry-run]
  python -m automations.rc_bank_totals.run shot --who carlos
Outputs land in output/rc_bank_totals/. See RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "rc_bank_totals"   # git-ignored: balances + screenshots never go in the repo
TAB = "Weekly Totals 24-26"

PEOPLE = {
    "carlos": {
        "sheet": "1HYnmAVCZn6LaWgXEPZItCB9E2bMdXFBxBwbXorkScm8", "gid": 1594939012, "last_row": 18,
        "header": lambda d: f"WE {d.month}.{d.day}",
        "carry": ["Raf Debt", "Idea Loan"],
        # Carlos's Tiller sheet (same one carlos_finance syncs on Lucy 2) — Accounts tab, keyed by account #
        "tiller": "1D2mjKSRNCM3fleq8e7uJyRuIotVqMfEW6baC7DV9fAE",
        "tiller_rows": {
            "0573": "Alphalete Marketing", "5328": "Personal", "8623": "Personal Savings",
            "7643": "Business CC (44K)", "0021": "Business CC 2 (6K)", "3455": "Personal CC (17.3K)",
            "9005": "Amex", "5550": "BOFA (20K)", "2242": "Capital",
        },
    },
    "raf": {
        "sheet": "1M2Vy2qo3N1AND1tVuKugtT_FizYw_6lBD3t2tcRLFYg", "gid": 1018067572, "last_row": 26,
        "header": lambda d: float(f"{d.month}.{d.day}"),   # sheet stores 10/4 as the number 10.4
        "carry": ["CareCredit (July 26)", "AMEX - Dropship"],
        "tiller": None,   # Raf has no Tiller yet — fill these account #s in once his sheet exists
        "tiller_rows": {
            "1096": "Local Office", "5289": "Shared LO CC - 5289 - (53.2k)", "1909": "Local Office CC - 1909 - (90k)",
            "5719": "Org CC - 5719 - (24k)", "0586": "Lifestyle CC - 0586 - (60k)", "6468": "Personal CC - 6468 - (10k)",
        },
    },
}


def _acct(v) -> str:
    """Tiller drops leading zeros (0573 -> 573)."""
    t = str(v).strip().split(".")[0]
    return t.zfill(4) if t.isdigit() else t


def tiller(who: str) -> Path:
    """Tiller Accounts tab -> <who>_<date>.json of {row label: balance}, cards as positive debt."""
    p, s = PEOPLE[who], sheets()
    if not p["tiller"]:
        sys.exit(f"{who}: no Tiller sheet set up yet")
    from googleapiclient.errors import HttpError
    try:
        acc = s.values().get(spreadsheetId=p["tiller"], range="Accounts!A1:R100",
                             valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    except HttpError as e:
        if e.resp.status == 403:
            sys.exit(f"{who}: Tiller sheet not shared with this Mac's Hub Google account yet (Viewer is enough)")
        raise
    hdr = acc[0]
    ia, ib = hdr.index("Account #"), hdr.index("Last Balance")
    iu = hdr.index("Last Update") if "Last Update" in hdr else None
    tb = {_acct(r[ia]): r for r in acc[1:] if len(r) > max(ia, ib) and str(r[ia]).strip()}
    values, stale = {}, []
    for num, label in p["tiller_rows"].items():
        r = tb.get(num)
        if r is None or r[ib] in ("", None):
            print(f"  MISSING in Tiller: {label} (…{num}) — get it from the bank")
            continue
        values[label] = round(abs(float(r[ib])), 2)   # Tiller shows card debt as negative; the sheet shows it positive
        upd = r[iu] if iu is not None and iu < len(r) else ""
        if isinstance(upd, (int, float)) and dt.date(1899, 12, 30) + dt.timedelta(days=int(upd)) < dt.date.today() - dt.timedelta(days=2):
            stale.append(label)
        print(f"  {label:<34} {values[label]:>12,.2f}   (…{num}, updated {upd})")
    if stale:
        print("  WARNING older than 2 days in Tiller (reconnect the bank in Tiller):", ", ".join(stale))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{who}_{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(values, indent=2))
    print(f"  saved {out} — add Business Security (Tableau) before running fill")
    return out


def creds() -> Credentials:
    c = Credentials.from_authorized_user_file(str(TOKEN))
    if not c.valid:
        c.refresh(Request())
    return c


def sheets():
    return build("sheets", "v4", credentials=creds()).spreadsheets()


def last_sunday(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def read_ab(s, p) -> list[list]:
    rng = f"'{TAB}'!A1:B{p['last_row']}"
    return s.values().get(spreadsheetId=p["sheet"], range=rng, valueRenderOption="FORMULA").execute().get("values", [])


def add(who: str, we: dt.date, dry: bool) -> None:
    p, s = PEOPLE[who], sheets()
    rows = read_ab(s, p)
    hdr = p["header"](we)
    if len(rows[0]) > 1 and rows[0][1] == hdr:
        sys.exit(f"{who}: column B is already {hdr!r} — nothing to add")
    clear, keep = [], []
    for i, r in enumerate(rows[1:], start=2):
        label, val = (r + ["", ""])[:2]
        if str(val).startswith("=") or label in p["carry"] or val == "":
            keep.append(label or f"row {i}")
        else:
            clear.append(i)
    print(f"{who}: new column B = {hdr!r} (last week was {rows[0][1]!r})")
    print(f"  keep (formula / carried): {', '.join(k for k in keep if not k.startswith('row'))}")
    print(f"  cleared for new numbers: {', '.join(rows[i - 1][0] for i in clear)}")
    if dry:
        return
    g, n = p["gid"], p["last_row"]
    reqs = [
        {"insertDimension": {"range": {"sheetId": g, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                             "inheritFromBefore": False}},
        {"copyPaste": {"source": {"sheetId": g, "startRowIndex": 0, "endRowIndex": n, "startColumnIndex": 2, "endColumnIndex": 3},
                       "destination": {"sheetId": g, "startRowIndex": 0, "endRowIndex": n, "startColumnIndex": 1, "endColumnIndex": 2},
                       "pasteType": "PASTE_NORMAL"}},
    ]
    s.batchUpdate(spreadsheetId=p["sheet"], body={"requests": reqs}).execute()
    data = [{"range": f"'{TAB}'!B1", "values": [[hdr]]}] + [{"range": f"'{TAB}'!B{i}", "values": [[""]]} for i in clear]
    s.values().batchUpdate(spreadsheetId=p["sheet"], body={"valueInputOption": "USER_ENTERED", "data": data}).execute()
    print("  done")


LEDGER_VIEW = "https://us-east-1.online.tableau.com/#/site/sci/views/OverridesICDView/NETSUITESECURITYLEDGERSFDC"
OWNERS = {"carlos": "carlos hidalgo", "raf": "rafael hidalgo"}


def merge_json(who: str, label: str, amt: float) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{who}_{dt.date.today().isoformat()}.json"
    values = json.loads(out.read_text()) if out.exists() else {}
    values[label] = amt
    out.write_text(json.dumps(values, indent=2))
    print(f"  {who:<7} {label:<18} {amt:>12,.2f}  -> {out.name}")


def tableau() -> None:
    """Hub's Tableau session -> Business Security (SFDC Total Balance) for both, merged into <who>_<date>.json."""
    sys.path.insert(0, str(REPO))
    import os
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.override_bulletin.pulls import read_crosstab
    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    bal = OUT / "_sfdc_balance.csv"
    download_crosstab_patchright(LEDGER_VIEW, "SFDC Total Balance", bal, verbose=False)

    def money(v) -> float:
        t = str(v).replace("$", "").replace(",", "").strip()
        return -float(t.strip("-()")) if t.startswith(("-", "(")) else float(t or 0)

    for who, owner in OWNERS.items():
        amt = next((money(r[2]) for r in read_crosstab(bal)[1:] if len(r) > 2 and owner in str(r[1]).lower()), None)
        if amt is None:
            print(f"  {who}: no SFDC Total Balance row for {owner!r}")
            continue
        merge_json(who, "Business Security", amt)


def payout(we: dt.date) -> float:
    """Raf's 'Payout toward CC' = sum of the CC payments table (Q:S, under the 'CC#' header on the same tab)
    dated Mon–Sun of the week ending `we`. Blank dates belong to the date above (merged cells)."""
    p, s = PEOPLE["raf"], sheets()
    rows = s.values().get(spreadsheetId=p["sheet"], range=f"'{TAB}'!Q1:S600",
                          valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    head = next(i for i, r in enumerate(rows) if r and str(r[0]).strip() == "CC#")
    start, total, cur = we - dt.timedelta(days=6), 0.0, None
    print(f"  Raf CC payments {start:%m/%d}–{we:%m/%d}:")
    for i, r in enumerate(rows[head + 1:], start=head + 2):
        r = (r + ["", "", ""])[:3]
        if isinstance(r[1], (int, float)):
            cur = dt.date(1899, 12, 30) + dt.timedelta(days=int(r[1]))
        if cur and start <= cur <= we and isinstance(r[2], (int, float)):
            total += r[2]
            print(f"    row {i:<4} {cur:%m/%d}  {str(r[0]):<11} {r[2]:>12,.2f}")
    total = round(total, 2)
    merge_json("raf", "Payout toward CC", total)
    return total


def fill(who: str, values: dict, dry: bool) -> None:
    p, s = PEOPLE[who], sheets()
    rows = read_ab(s, p)
    where = {r[0].strip().lower(): i for i, r in enumerate(rows, start=1) if r and r[0]}
    data, missing = [], []
    for label, v in values.items():
        i = where.get(label.strip().lower())
        if i is None:
            missing.append(label)
            continue
        cur = (rows[i - 1] + ["", ""])[1]
        if str(cur).startswith("="):
            missing.append(f"{label} (formula row — not overwritten)")
            continue
        data.append({"range": f"'{TAB}'!B{i}", "values": [[v]]})
        print(f"  B{i:<3} {label:<34} {v:>12,.2f}")
    if missing:
        print("  NOT WRITTEN:", "; ".join(missing))
    empty = [r[0] for r in rows[1:] if r and r[0] and len(r) < 2 and r[0] not in values]
    if empty:
        print("  still blank in column B:", ", ".join(empty))
    if not dry and data:
        s.values().batchUpdate(spreadsheetId=p["sheet"], body={"valueInputOption": "USER_ENTERED", "data": data}).execute()
        print(f"  wrote {len(data)} cells")


def shot(who: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    import fitz  # PyMuPDF
    p = PEOPLE[who]
    url = (f"https://docs.google.com/spreadsheets/d/{p['sheet']}/export?format=pdf&gid={p['gid']}"
           f"&range=A1:E{p['last_row']}&portrait=false&fitw=true&gridlines=true&printtitle=false"
           f"&sheetnames=false&pagenum=UNDEFINED&top_margin=0.2&bottom_margin=0.2&left_margin=0.2&right_margin=0.2")
    r = AuthorizedSession(creds()).get(url)
    r.raise_for_status()
    page = fitz.open(stream=r.content, filetype="pdf")[0]
    clip = fitz.Rect(page.rect)
    blocks = page.get_text("blocks")
    if blocks:   # crop the white space under the table
        clip.y1 = min(page.rect.y1, max(b[3] for b in blocks) + 12)
        clip.x1 = min(page.rect.x1, max(b[2] for b in blocks) + 12)
    out = OUT / f"{who}_bank_totals_{dt.date.today().isoformat()}.png"
    page.get_pixmap(dpi=200, clip=clip).save(out)
    print(f"  saved {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["add", "tiller", "tableau", "payout", "fill", "shot"])
    ap.add_argument("--who", choices=list(PEOPLE), help="required except for tableau (both) and payout (Raf)")
    ap.add_argument("--we", help="week-ending Sunday, YYYY-MM-DD (default: most recent Sunday)")
    ap.add_argument("--values", help="JSON file of {row label: amount}")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd not in ("tableau", "payout") and not a.who:
        ap.error("--who is required")
    we = dt.date.fromisoformat(a.we) if a.we else last_sunday(dt.date.today())
    if a.cmd == "add":
        add(a.who, we, a.dry_run)
    elif a.cmd == "tableau":
        tableau()
    elif a.cmd == "payout":
        payout(we)
    elif a.cmd == "tiller":
        tiller(a.who)
    elif a.cmd == "fill":
        fill(a.who, json.loads(Path(a.values).read_text()), a.dry_run)
    else:
        shot(a.who)


if __name__ == "__main__":
    main()
