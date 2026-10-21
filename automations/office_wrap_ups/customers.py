"""Parse the org-wide Order Log crosstab into per-office customer rows shaped
for the RingCentral texted() check + the Slack reply.

The crosstab is the same ALLREPS export disconnects/canceled_orders pull
(UTF-16-LE, tab-delimited). We read it ONCE, then slice per office by Owner
Name. 'Product Type (Broken Out)' gives one row per product line, so a customer
who bought internet + a couple phones appears as several rows — we dedupe by
phone and collect the product categories (Internet / TV / Wireless).
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from typing import Dict, List, Optional

from automations.rc_contact_sync import ringcentral as RC

# DTR statuses that mean the sale is dead — don't chase a wrap-up for it.
EXCLUDE_DTR = {"cancelled", "canceled", "disconnected"}


def _find(idx: Dict[str, int], *cands) -> Optional[int]:
    for c in cands:
        if c in idx:
            return idx[c]
    norm = {re.sub(r"[^a-z0-9]", "", h.lower()): i for h, i in idx.items()}
    for c in cands:
        k = re.sub(r"[^a-z0-9]", "", c.lower())
        if k in norm:
            return norm[k]
    return None


def read_crosstab(csv_path) -> List[Dict[str, str]]:
    """Every data row as {owner, rep, order_date, customer_name, phone,
    product, dtr}. Tolerant to the exact Tableau header spelling."""
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return []
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    ci = {
        "owner": _find(idx, "Owner Name"),
        "rep": _find(idx, "Rep"),
        "order_date": _find(idx, "sp.Order Date (copy)", "Order Date"),
        "customer_name": _find(idx, "Customer Name"),
        "phone": _find(idx, "sp.Customer Phone", "Customer Phone"),
        "product": _find(idx, "Product Type (Broken Out)", "Product Type"),
        "dtr": _find(idx, "DTR Status"),
    }
    out: List[Dict[str, str]] = []
    for r in rows[1:]:
        def g(key: str) -> str:
            i = ci[key]
            return r[i].strip() if i is not None and i < len(r) else ""
        out.append({k: g(k) for k in ci})
    return out


def _parse_date(v: str) -> Optional[dt.date]:
    s = (v or "").strip().split()[0] if (v or "").strip() else ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _product_tag(product_type: str) -> Optional[str]:
    p = (product_type or "").lower()
    if any(w in p for w in ("internet", "fiber")):
        return "Internet"
    if any(w in p for w in ("directv", "direct tv", "video", " tv", "tv ", "stream")):
        return "TV"
    if any(w in p for w in ("wireless", "mobility", "mobile", "wifi")):
        return "Wireless"
    return None


def for_office(rows: List[Dict[str, str]], profile: Dict[str, str],
               since: dt.date, until: dt.date, log=print) -> List[Dict[str, str]]:
    """This office's customers (Order Date in [since, until]), deduped by phone,
    with products collected. `profile` is one office_profiles() entry."""
    aliases = {a.strip().lower()
               for a in (profile.get("owner_aliases") or [profile.get("owner", "")])
               if a and a.strip()}
    by_key: Dict[str, Dict] = {}
    skipped_dead = 0
    for r in rows:
        if r["owner"].strip().lower() not in aliases:
            continue
        d = _parse_date(r["order_date"])
        if d is None or not (since <= d <= until):
            continue
        if r["dtr"].strip().lower() in EXCLUDE_DTR:
            skipped_dead += 1
            continue
        ph = RC.norm_phone(r["phone"])
        key = ph or ("name:" + r["customer_name"].strip().lower())
        c = by_key.get(key)
        if c is None:
            c = {"rep": r["rep"], "business": "",
                 "customer_name": r["customer_name"], "phone": r["phone"],
                 "day": d.isoformat(), "order_date": r["order_date"],
                 "alt_phones": [], "wireless_order": "", "ban": "",
                 "_tags": set()}
            by_key[key] = c
        tag = _product_tag(r["product"])
        if tag:
            c["_tags"].add(tag)
    out: List[Dict[str, str]] = []
    for c in by_key.values():
        c["products"] = [t for t in ("Internet", "TV", "Wireless")
                         if t in c["_tags"]]
        c.pop("_tags", None)
        out.append(c)
    log("  %s (%s): %d customer(s) %s..%s (%d dead-order row(s) skipped)"
        % (profile.get("key"), profile.get("owner"), len(out), since, until,
           skipped_dead))
    return out
