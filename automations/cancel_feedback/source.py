"""Who to text: yesterday's cancels + disconnects, deduped by phone.

Reuses canceled_orders.pull and disconnects.pull verbatim (same views, same
owner rosters the #alphalete-sales daily post uses), so the outreach list
mirrors that post. `unify()` is a pure function so it is unit-tested offline;
`gather()` does the two Tableau pulls then calls it.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.cancel_feedback import config as C


def normalize_phone(raw: str) -> Optional[str]:
    """US 10-digit → '+1XXXXXXXXXX'. None for blanks or anything that isn't a
    real 10-digit number (so we never text a malformed value)."""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    area, exch = digits[:3], digits[3:6]
    if area[0] in "01" or exch[0] in "01":        # area/exchange can't start 0/1
        return None
    if area[1:] == "11" or exch[1:] == "11":      # N11 (211,311,...,911) aren't DIDs
        return None
    return "+1" + digits


def first_name(full: str) -> str:
    """First token of the customer name, title-cased. 'there' if empty."""
    tok = (str(full or "").strip().split() or [""])[0]
    return tok[:1].upper() + tok[1:].lower() if tok else "there"


def unify(cancel_rows: List[dict], disconnect_rows: List[dict]) -> List[dict]:
    """Merge the two sources into one outreach list, deduped by phone. A number
    that both cancelled and disconnected becomes a single entry (kind merged;
    disconnect reason kept). Rows with no usable phone are dropped."""
    by_phone: Dict[str, dict] = {}

    def add(row: dict, kind: str, reason: str):
        phone = normalize_phone(row.get("Customer Phone", ""))
        if not phone:
            return
        name = row.get("Customer Name", "")
        owner = row.get("_owner") or row.get("Owner Name", "")
        cur = by_phone.get(phone)
        if cur is None:
            by_phone[phone] = {
                "phone": phone,
                "customer_name": name,
                "first": first_name(name),
                "rep": row.get("Rep", ""),
                "owner": owner,
                "kinds": {kind},
                "reason": reason or "",
                "status_date": row.get("Status Date", ""),
            }
        else:
            cur["kinds"].add(kind)
            if reason and not cur["reason"]:
                cur["reason"] = reason
            if not cur.get("customer_name"):
                cur["customer_name"] = name
                cur["first"] = first_name(name)

    for r in cancel_rows:
        add(r, "cancel", "")
    for r in disconnect_rows:
        add(r, "disconnect", r.get("Eligibility Reason", ""))

    out = list(by_phone.values())
    for c in out:
        c["kind"] = "+".join(sorted(c.pop("kinds")))
    out.sort(key=lambda c: (c.get("owner", ""), c.get("customer_name", "")))
    return out


def gather(day: Optional[dt.date] = None, *, owners: Optional[set] = None,
           cancel_csv=None, disconnect_csv=None, log=print) -> List[dict]:
    """Yesterday's (or `day`'s) cancels + disconnects as one deduped list,
    restricted to `owners` (default: Rafael's whole captainship). Pass
    cancel_csv/disconnect_csv to parse existing crosstabs instead of pulling
    (offline/testing)."""
    from automations.canceled_orders import pull as cxpull
    from automations.disconnects import pull as dxpull

    day = day or C.yesterday()
    owners = owners if owners is not None else C.captainship_owners()
    order_start = day - dt.timedelta(days=C.ORDER_WINDOW_DAYS)
    window = (day, day)

    if cancel_csv is None:
        log("cancels: Order Log pull (%s..%s)…" % (order_start, day))
        cancel_csv = cxpull.fetch_crosstab(order_start, day)
    cancel_rows = cxpull.parse_and_filter(cancel_csv, owners, window)

    if disconnect_csv is None:
        log("disconnects: Order Log pull (%s..%s)…" % (order_start, day))
        disconnect_csv = dxpull.fetch_crosstab(order_start, day)
    disconnect_rows = dxpull.parse_and_filter(disconnect_csv, owners, window)

    log("cancels: %d  disconnects: %d  (status date == %s)"
        % (len(cancel_rows), len(disconnect_rows), day))
    customers = unify(cancel_rows, disconnect_rows)
    log("unique customers to reach out to: %d" % len(customers))
    return customers
