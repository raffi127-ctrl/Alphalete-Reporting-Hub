"""Raf's full Sales Order History (ALL reps) off the Lucy 1 handoff, shaped
like rc_contact_sync.sara.scrape()'s rows so the texted() check and the Slack
post take them unchanged.

This is rc_contact_sync.guest with the roster filter removed: guest reads the
"Raf Guest Orders" tab (Carlos's reps only); this reads the "Raf All Orders"
tab (everybody under Raf's code). The header-matching, date parsing and row
shape are guest's own helpers, imported — one answer about what a column is,
everywhere.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import io
import json
from typing import Dict, List, Optional

from automations.rc_contact_sync_raf import config as C
# Reuse the tolerant header map + date/whitespace helpers verbatim.
from automations.rc_contact_sync.guest import (
    _header_map, _parse_us_date, _norm)


def _fetch(log=print) -> Optional[Dict]:
    """The "Raf All Orders" envelope off the control sheet, or None (reason
    logged). Mirrors raf_guest.fetch(), pointed at this report's tab."""
    try:
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(C.CONTROL_SHEET)
        t = sh.worksheet(C.TAB)
        chunks = [c[0] for c in t.get_values("A1:A200") if c and c[0]]
        if not chunks:
            log("raf-all fetch: tab %r is empty — no pull has landed" % C.TAB)
            return None
        return json.loads(base64.b64decode("".join(chunks)))
    except Exception as e:                                 # noqa: BLE001
        log("raf-all fetch: couldn't read tab %r (%s: %s)"
            % (C.TAB, type(e).__name__, str(e)[:120]))
        return None


def _age_hours(env: Dict) -> Optional[float]:
    try:
        pulled = dt.datetime.fromisoformat(str(env.get("pulled", "")))
        return (dt.datetime.now() - pulled).total_seconds() / 3600.0
    except Exception:                                      # noqa: BLE001
        return None


def all_customers(since: dt.date, until: dt.date,
                  log=print) -> List[Dict[str, str]]:
    """Every order under Raf's code with Order Date in [since, until], shaped
    like sara.scrape()'s rows (day = the ORDER date). Raises when the envelope
    is missing or stale — the caller decides whether that sinks the run."""
    env = _fetch(log=log)
    if not env:
        raise RuntimeError(
            "no Raf all-orders pull on the control sheet (tab %r) — run "
            "`python -m automations.rc_contact_sync_raf.pull_raf --pull` on "
            "Lucy 1 first" % C.TAB)
    age = _age_hours(env)
    if age is None or age > C.MAX_AGE_H:
        raise RuntimeError(
            "the Raf all-orders pull is STALE (%s, %sh old > %dh) — re-run "
            "pull_raf on Lucy 1 before trusting it"
            % (env.get("pulled"), "?" if age is None else round(age, 1),
               C.MAX_AGE_H))
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
            "business": _norm(r.get(cols.get("business", ""), ""))
            if cols.get("business") else "",
            "customer_name": _norm(r.get(cols["customer_name"], "")),
            "phone": _norm(r.get(cols.get("phone", ""), ""))
            if cols.get("phone") else "",
            # No customer-card harvest on this report, so no alt numbers — the
            # texted() check degrades to the primary number + the name, which
            # is exactly the B2B report's original behaviour.
            "alt_phones": [],
            "wireless_order": _norm(r.get("Wireless Order #", "")),
            "ban": _norm(r.get("Wireless Acct #", "")),
        })
    if skipped_dates:
        log("raf-all: %d row(s) had an unreadable Order Date — left out"
            % skipped_dates)
    log("raf-all orders: %d order(s) %s..%s, pull from %s"
        % (len(out), since, until, env.get("pulled")))
    return out
