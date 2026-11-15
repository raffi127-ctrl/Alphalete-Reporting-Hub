"""What ELSE Credico mails a Verizon office, and which of it carries a
customer phone number. READ-ONLY probe, runs on a Lucy with the Hub inbox.

Carlos 2026-11-15: "There's got to be somewhere where we can see the
customer's phone number before it hits the ARC file, which is the direct
deposit." The Sales Verification masks the line ("*1309-LINE"); the ARC
Commissions workbook has it but two weeks late. This lists every attachment
Credico (or the office's forward) sent in the last N days -- Sales
Verification, Compliance Flags, Dynamic Churn Report, scorecards, bulletins,
bonus trackers -- and for each xlsx the sheet names + header rows, flagging
any column whose VALUES look like a 10-digit phone number. Header names and
counts only, never a value, -> the control sheet tab 'VZ Inbox Probe'.

    python -m automations.verizon_office.inbox_probe --office nicolas [--days 21]
    lucy rerun verizon_inbox_probe

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tempfile
from pathlib import Path
from typing import List

CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "VZ Inbox Probe"
SENDER = "vzreports@credicousa.com"
_PHONE = re.compile(r"^\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(-LINE)?$")


def probe_xlsx(path: Path) -> List[List[str]]:
    import openpyxl
    out = []
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True, max_row=400) if any(c is not None for c in r)]
        hi = next((i for i, r in enumerate(rows) if sum(1 for c in r if isinstance(c, str)) >= 4), None)
        if hi is None:
            out.append([path.name, ws.title, "(no header row found)", ""])
            continue
        header = [str(c) if c is not None else "" for c in rows[hi]]
        body = rows[hi + 1:]
        phone_cols = []
        for i, h in enumerate(header):
            vals = [str(r[i]).strip() for r in body if i < len(r) and r[i] not in (None, "")]
            if vals and sum(1 for v in vals if _PHONE.match(v)) >= max(3, len(vals) // 2):
                phone_cols.append("%s (%d)" % (h, len(vals)))
        out.append([path.name, ws.title, " | ".join(h for h in header if h)[:1500],
                    ("PHONE-LIKE: " + ", ".join(phone_cols)) if phone_cols else ""])
    return out


def run(office_key: str, days: int, log=print) -> List[List[str]]:
    from automations.shared import email_ingest
    from automations.verizon_office import offices as OF
    office = OF.get(office_key)
    dest = Path(tempfile.gettempdir()) / "verizon_inbox_probe"
    rows = [["File", "Sheet", "Header", "Phone-like columns"],
            ["probed", dt.datetime.now().isoformat(timespec="seconds"), "office " + office.office, "last %d days" % days]]
    # ONE IMAP pass per sender with ONE glob: eight globs x two senders timed
    # out at 15 minutes on Lucy 4 (2026-11-15). The any-sender pass is narrowed
    # by subject, the way verizon_office.run.fetch does it (an all-mail search
    # with no sender took 3+ minutes on 11/06).
    # fetch_by_globs keeps the NEWEST attachment per glob, so one glob per
    # report type (the 11/15 16:49 run with "*.xlsx" saw only the Daily Sales
    # scorecard). Sender-filtered searches are quick; the any-sender pass (the
    # office's own forward of Credico's mail) is subject-narrowed.
    report_globs = ["*Sales Verification*", "*Compliance*", "*Churn*", "*Scorecard*", "*Daily Sales*",
                    "*Bulletin*", "*Bonus*", "*Quality*", "*Tracker*"]
    seen = set()
    for sender, subject, globs in ((SENDER, None, report_globs), ("", "Verizon Wireless", report_globs[:3])):
        found = email_ingest.fetch_by_globs(sender, globs, dest, subject=subject, since_days=days, verbose=False)
        for fname, path in found.items():
            if fname in seen:
                continue
            seen.add(fname)
            p = Path(path)
            if p.suffix.lower() in (".xlsx", ".xlsm"):
                try:
                    rows += probe_xlsx(p)
                except Exception as e:  # noqa: BLE001
                    rows.append([p.name, "", "(unreadable: %s)" % e, ""])
            else:
                rows.append([p.name, "", "(%s, not a workbook)" % p.suffix, ""])
    log("[verizon] inbox probe: %d attachment(s)" % len(seen))
    for r in rows[2:]:
        log("  %-60s %-20s %s" % (r[0][:60], r[1][:20], r[3] or ""))
    return rows


def push(rows, log=print) -> None:
    from automations.recruiting_report.fill import _retry, open_by_key
    import gspread
    sh = open_by_key(CONTROL_SHEET)
    try:
        ws = sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = _retry(lambda: sh.add_worksheet(title=TAB, rows=200, cols=4))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(rows, "A1", value_input_option="RAW"))
    log("[verizon] inbox probe -> control sheet tab %r (%d row(s))" % (TAB, len(rows) - 2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    rows = run(a.office, a.days)
    if not a.no_push:
        push(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
