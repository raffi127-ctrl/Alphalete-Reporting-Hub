"""Customers Carlos's reps sold under RAF'S SaraPlus code -> the same
contacts-and-wrap-up-text pipeline.

Carlos 2026-10-08: "My guys started selling under Rafael's code last Tuesday
[2026-09-29], so go ahead and check everything as of last Tuesday. Let us
know who's received the text message and who hasn't, and add all those
customers into the contact list." His reps sell ONLY under Raf's code until
they move onto his own AT&T NDS code (~mid-Oct), so the daily scrape of
Carlos's dealer sees none of these orders.

NO SECOND SARAPLUS LOGIN. The Lucy 1 raf_guest_orders pull (see
sp_order_log/raf_guest.py) already lands the guest roster's full Sales Order
History rows on the control sheet, and that export carries everything the
RUNBOOK's step 2 needs -- rep (`User Name`), business (`Business Name`),
customer (`Customer Name`), phone and `Order Date`. This module only decodes
that envelope and shapes the rows like sara.scrape() does; contacts, the
texted() check and the Slack post are the pipeline's own, unchanged.

Headers are matched TOLERANTLY (("Phone", "spe.Phone"), spacing ignored)
because the CSV export and the on-screen grid have disagreed before --
sp_order_log reads `spe.Phone` where the grid says `Phone`. A row with no
phone still goes through: run() already logs-and-skips it, which is the
visibility we want, not a silent drop here.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import io
from typing import Dict, List, Optional, Tuple

# (what we call it, the headers it may hide under -- checked in order,
# spacing/case ignored)
_COLS = {
    "order_id": ("Order ID",),
    "order_date": ("Order Date",),
    "rep": ("User Name",),
    "business": ("Business Name", "Company Name"),
    "customer_name": ("Customer Name",),
    "phone": ("Phone", "spe.Phone", "Primary Phone", "Phone Number"),
}


def _key(h: str) -> str:
    return str(h or "").replace(" ", "").replace(".", "").strip().lower()


def _header_map(fieldnames: List[str], log=print) -> Dict[str, str]:
    by_key = {_key(f): f for f in fieldnames or []}
    out: Dict[str, str] = {}
    for ours, cands in _COLS.items():
        for c in cands:
            if _key(c) in by_key:
                out[ours] = by_key[_key(c)]
                break
    missing = [k for k in _COLS if k not in out and k != "phone"]
    if missing:
        raise RuntimeError(
            "Raf guest export is missing column(s) %s — header was: %r"
            % (missing, (fieldnames or [])[:20]))
    if "phone" not in out:
        log("guest rows: NO phone column found (tried %s) — every guest "
            "customer will be skipped as phoneless; fix guest._COLS"
            % (_COLS["phone"],))
    return out


def _parse_us_date(v: str) -> Optional[dt.date]:
    s = str(v or "").strip().split()[0] if str(v or "").strip() else ""
    try:
        m, d, y = s.split("/")
        return dt.date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        try:
            return dt.date.fromisoformat(s)
        except ValueError:
            return None


def _norm(v: str) -> str:
    return " ".join(str(v or "").split())


def guest_customers(since: dt.date, until: dt.date,
                    log=print) -> List[Dict[str, str]]:
    """The guest reps' orders with Order Date in [since, until], shaped
    exactly like sara.scrape()'s rows (day = the ORDER date, so the state
    key and the Slack grouping date the customer by their sale).

    Raises when the envelope is missing or stale — for the DAILY run the
    caller wraps this (a lost Lucy 1 pull must not sink Carlos's own
    customers), for the backfill a loud failure IS the right answer."""
    from automations.sp_order_log import raf_guest

    env = raf_guest.fetch(log=log)
    if not env:
        raise RuntimeError(
            "no Raf guest pull on the control sheet (tab %r) — run "
            "`lucy rerun raf_guest_orders --machine \"Lucy 1\"` first"
            % raf_guest.TAB)
    age = raf_guest._age_hours(env)
    if age is None or age > raf_guest.MAX_AGE_H:
        raise RuntimeError(
            "the Raf guest pull is STALE (%s, %sh old) — re-run "
            "raf_guest_orders on Lucy 1 before trusting it"
            % (env.get("pulled"), "?" if age is None else round(age, 1)))
    data = base64.b64decode(env.get("csv", "") or "")
    reader = csv.DictReader(io.StringIO(
        data.decode("utf-8-sig", errors="replace")))
    rows = list(reader)
    cols = _header_map(list(reader.fieldnames or []), log=log)

    out: List[Dict[str, str]] = []
    skipped_dates = 0
    for r in rows:
        d = _parse_us_date(r.get(cols["order_date"], ""))
        if d is None:
            skipped_dates += 1
            continue
        if not (since <= d <= until):
            continue
        out.append({
            "order_id": _norm(r.get(cols["order_id"], "")),
            "day": d.isoformat(),
            "order_date": _norm(r.get(cols["order_date"], "")),
            "rep": _norm(r.get(cols["rep"], "")),
            "business": _norm(r.get(cols["business"], "")),
            "customer_name": _norm(r.get(cols["customer_name"], "")),
            "phone": _norm(r.get(cols.get("phone", ""), ""))
            if cols.get("phone") else "",
        })
    if skipped_dates:
        log("guest rows: %d row(s) had an unreadable Order Date — left out"
            % skipped_dates)
    log("guest rows (Raf's code): %d order(s) %s..%s, pull from %s"
        % (len(out), since, until, env.get("pulled")))
    for c in out:
        log("  %-10s %-14s %-26s %-24s %s"
            % (c["day"], c["order_id"], (c["business"] or "(no business)")[:26],
               c["customer_name"][:24], c["phone"] or "NO PHONE"))
    return out


def for_day(day: dt.date, log=print) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """The daily run's fail-open wrapper: ([customers], error or None)."""
    try:
        return guest_customers(day, day, log=log), None
    except Exception as e:  # noqa: BLE001
        msg = "%s: %s" % (type(e).__name__, str(e)[:200])
        log("guest rows: FAILED (%s) — today's run covers Carlos's own "
            "dealer only" % msg)
        return [], msg
