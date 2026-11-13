"""Raf's monthly Profit Share -> his "Special Override" on the bulletin.

Maud 2026-11-09: Raf now gets a Profit Share every retail period and wants it to
count as Special Overrides on the bulletin. It is NOT in Tableau — it arrives as
an email from Smart Circle's controller:

    Subject:  Profit Share - P10 - 2026 - Rafael Hidalgo
    Body:     "... This will be posted to your security account by EOD November 9, 2026."
    Attach:   Raf Hidalgo Profit Sharing Report P10 2026 Final.xlsx

Maud filtered it into the reporting inbox (alphaletereporting@gmail.com), so this
reads it with the same IMAP app password every email-fed report uses.

Source path for the number:
    email attachment -> 'Summary' tab -> row 'Profit Sharing net of M&C Reserve'
    -> column 'P<n>-YYYY'.  (P10-2026 = $24,246.02; gross before the 8% M&C
    reserve = $26,354.37 on the row "Raf Hidalgo's Profit Share".)
NET is what posts to his security account, same as every other Special the
bulletin carries (ledger Transaction Amount).

Which week (Eve 2026-11-13): the bulletin that goes out the week the EMAIL
ARRIVES — not the "posted ... by EOD" date, not the Special's period. Eve would
rather it sat with Raf's Special Override, but until Smart Circle / Maud say
otherwise it goes in the week of the email. The bulletin goes out Friday and
reports the week that closed the Sunday before, so: next Friday on or after the
arrival date, minus 5 days. P10-2026 arrived Mon 11/9 -> Fri 11/13 bulletin ->
11.8.26 (matches Eve's hand tab). A Saturday arrival goes to the NEXT bulletin
— that Friday's is already out. The posted date is kept only as a fallback if
the email has no readable Date header.

STATELESS on purpose: the inbox IS the state. Every fill/backtrack re-reads the
emails, so a re-run never adds it twice and a backtrack rebuild of that week
keeps it instead of erasing it.
"""
from __future__ import annotations

import datetime as dt
import email
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional

SUBJECT = "Profit Share"
ATTACH_RE = re.compile(r"profit\s*shar.*\.xlsx$", re.I)
NET_LABEL = "profit sharing net of m&c reserve"
GROSS_LABEL = "raf hidalgo's profit share"
_PERIOD_RE = re.compile(r"^P(\d{1,2})-(\d{4})$")
_POSTED_RE = re.compile(
    r"posted to your security account by(?: EOD)?\s+([A-Z][a-z]+ \d{1,2},? \d{4})",
    re.I)
OUT_DIR = Path("output/override_bulletin/profit_share")
SINCE_DAYS = 120          # backtrack reaches ~5 weeks; one period of slack


def parse_xlsx(path) -> Dict[str, Dict[str, float]]:
    """{'P10-2026': {'net': 24246.02, 'gross': 26354.37}} for every period column
    on the Summary tab with a non-zero net. Columns/rows found by label."""
    import openpyxl
    # read_only keeps the file handle open on Windows (next fetch can't overwrite
    # it) — close it before parsing.
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = next((s for s in wb.worksheets
                   if s.title.strip().lower() == "summary"), None)
        if ws is None:
            raise ValueError(f"{Path(path).name}: no 'Summary' tab")
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    hdr_i, cols = None, {}
    for i, r in enumerate(rows):
        found = {c: str(v).strip() for c, v in enumerate(r)
                 if v is not None and _PERIOD_RE.match(str(v).strip())}
        if found:
            hdr_i, cols = i, found
            break
    if hdr_i is None:
        raise ValueError(f"{Path(path).name}: no P#-YYYY header on Summary")

    def _row(label):
        for r in rows[hdr_i + 1:]:
            if any(isinstance(v, str) and " ".join(v.split()).lower() == label
                   for v in r):
                return r
        return None

    net_r, gross_r = _row(NET_LABEL), _row(GROSS_LABEL)
    if net_r is None:
        raise ValueError(f"{Path(path).name}: no {NET_LABEL!r} row on Summary")
    out = {}
    for c, per in cols.items():
        net = net_r[c] if c < len(net_r) else None
        if isinstance(net, (int, float)) and round(net, 2) != 0:
            gross = gross_r[c] if gross_r is not None and c < len(gross_r) else None
            out[per] = {"net": round(float(net), 2),
                        "gross": round(float(gross), 2)
                        if isinstance(gross, (int, float)) else None}
    return out


def posted_date(body: str, fallback: Optional[dt.date]) -> Optional[dt.date]:
    m = _POSTED_RE.search(body or "")
    if m:
        txt = m.group(1).replace(",", "")
        try:
            return dt.datetime.strptime(txt, "%B %d %Y").date()
        except ValueError:
            pass
    return fallback


def week_label(d: dt.date) -> str:
    """Week of the bulletin that goes out the week `d` arrives: the Friday on or
    after `d`, minus 5 days (Mon 11/9/26 -> Fri 11/13 -> 11.8.26)."""
    fri = d + dt.timedelta(days=(4 - d.weekday()) % 7)
    sun = fri - dt.timedelta(days=5)
    return f"{sun.month}.{sun.day}.{sun.strftime('%y')}"


def _body_text(msg) -> str:
    out = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                out.append(part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", "replace"))
            except Exception:  # noqa: BLE001
                pass
    return re.sub(r"<[^>]+>", " ", "\n".join(out))


def fetch(since_days: int = SINCE_DAYS, verbose: bool = True) -> List[dict]:
    """Every Profit Share in the reporting inbox, one entry per period
    (newest email wins — a forward or a corrected resend replaces the first).
    [{period, net, gross, posted, week, file}]. Raises on IMAP failure: the
    caller decides (fill = abort, backtrack = keep the sheet's value)."""
    from automations.shared import email_ingest as EI
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    M = EI._connect()
    by_period: Dict[str, dict] = {}
    try:
        for i in reversed(EI._search(M, "", SUBJECT, since_days)):     # newest first
            _, raw = M.fetch(i, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            if "rafael hidalgo" not in EI._decode(msg.get("Subject", "")).lower():
                continue
            try:
                sent = parsedate_to_datetime(msg["Date"]).date()
            except Exception:  # noqa: BLE001
                sent = None
            body = _body_text(msg)
            for part in msg.walk():
                fn = EI._filename(part)
                if not fn or not ATTACH_RE.search(fn):
                    continue
                path = OUT_DIR / EI._safe_name(fn)
                path.write_bytes(part.get_payload(decode=True))
                for per, amt in parse_xlsx(path).items():
                    if per in by_period:
                        continue
                    # Week = when the email ARRIVED (Eve 2026-11-13); the
                    # posted date only stands in if the Date header is unreadable.
                    when = sent or posted_date(body, None)
                    by_period[per] = {"period": per, **amt,
                                      "posted": posted_date(body, None),
                                      "arrived": sent,
                                      "week": week_label(when) if when else None,
                                      "file": path.name}
                    if verbose:
                        EI._say(f"  profit share {per}: ${amt['net']:,.2f} net "
                                f"-> week {by_period[per]['week']} ({fn})")
    finally:
        M.logout()
    return sorted(by_period.values(), key=lambda e: e["period"])


def by_week(entries) -> Dict[str, float]:
    """{sheet_week_label: net} — two periods posting the same week are summed."""
    out: Dict[str, float] = {}
    for e in entries:
        if e.get("week"):
            out[e["week"]] = round(out.get(e["week"], 0) + e["net"], 2)
    return out


_CACHE: Dict[int, Dict[str, float]] = {}


def amounts_by_week(verbose: bool = True) -> Dict[str, float]:
    """by_week(fetch()), read once per process (the fill and its backtrack share it)."""
    if SINCE_DAYS not in _CACHE:
        _CACHE[SINCE_DAYS] = by_week(fetch(verbose=verbose))
    return _CACHE[SINCE_DAYS]


if __name__ == "__main__":
    for e in fetch():
        print(e)
