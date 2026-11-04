"""NDS Wireless Resolution Report — the PER-LINE feed off alphaletegp.

Carlos 2026-10-29 ("figure it out so we can make everything match"): the
2026-09-05 status probe already found this — Reporting Hub -> Wireless
Dashboard carries an Excel export with order headers (Customer, DSI #,
Wireless Order #, BAN, Salesperson, Order Status) and NESTED LINE ROWS:
Line Type (New/Port), Device Type, Plan, Line Status, ship/delivered
dates, Port Status. That per-line status is what the DD pays on while the
Sales Order History still says Shipped ($1,892 board vs $3,718 deposit on
WE 10.25), and the Plan column carries the Unlimited add-ons.

This module runs the same flow on the NDS dealer (alphaletegp): rc
sara.login on the NDS profile (passcode self-clearing), Reporting Hub,
_wireless_panel_dump, and caches the export (an Excel-flavoured HTML
table) at OUT_DIR/nds_wireless_<date>.html. parse() turns it into
(orders, lines) dicts for the boards.

    lucy rerun nds_wireless_pull             # pull + summary
    lucy rerun nds_wireless_pull --days 14
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

from automations.nds_metrics.run import (NDS_SARA_CREDS, NDS_SARA_PROFILE,
                                         OUT_DIR)


def pull(start: dt.date, end: dt.date, log=print) -> bytes:
    import json as _json
    from patchright.sync_api import sync_playwright
    from automations.rc_contact_sync import config as RC
    from automations.rc_contact_sync import sara
    from automations.rc_contact_sync.status_probe import (
        _dump_tab_strip, _wireless_panel_dump)
    cr = _json.loads(NDS_SARA_CREDS.read_text())
    NDS_SARA_PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(NDS_SARA_PROFILE), headless=True, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = sara.login(page, cr["email"], cr["password"], log=log)
            log(f"[ndsw] logged in as {cr['email']}")
            page.goto(base + RC.HUB_PATH, wait_until="networkidle",
                      timeout=RC.NAV_TIMEOUT_MS)
            _dump_tab_strip(page, log)   # mismatched strip shows itself
            try:
                data = _wireless_panel_dump(page, start, end, log)
            except Exception as e:  # noqa: BLE001 — a hung click on this
                # dealer must not lose the grid that is already rendered
                log(f"[ndsw] panel dump crashed mid-way "
                    f"({type(e).__name__}: {str(e)[:140]}) — scraping "
                    "whatever the panel shows")
                data = None
            log(f"[ndsw] page now at {page.url[:120]!r}")
            if not data:
                # This dealer's panel has no Excel button (click timed out
                # 2026-10-29) but the grid itself renders the same rows —
                # its outerHTML walks in document order, so parse()'s
                # order-then-lines association still holds.
                log("[ndsw] no export control — scraping the grid")
                html = page.evaluate(
                    """() => {
                         const el = document.querySelector(
                           "div[id*='WirelessDash'], table[id*='WirelessDash']");
                         return el ? el.outerHTML : '';
                       }""")
                if html and len(html) > 2000:
                    log(f"[ndsw] grid scraped ({len(html):,} chars)")
                    data = html.encode("utf-8")
            if not data:
                raise RuntimeError("wireless export AND grid scrape empty")
            return data
        finally:
            ctx.close()


def parse(data: bytes, log=print):
    """-> (orders, lines). Orders: one dict per order header row; lines:
    one dict per nested line row carrying its parent order."""
    txt = data.decode("utf-8-sig", errors="replace")
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S)

    def cells(tr):
        return [re.sub(r"<[^>]+>|&nbsp;", " ", c).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]

    ORDER_HDR = ["", "", "Customer Name", "Contact Phone", "Order Number",
                 "Order Date", "Wireless Order Number",
                 "Wireless Account Number", "Lines", "Salesperson",
                 "Dealer Name", "Dealer Code", "Order Status"]
    LINE_HDR = ["", "Line", "Line Type", "Device Type", "Line Number",
                "Phone", "Plan", "Line Status", "Est. Shipping Range",
                "Ship Date", "Delieverd Date", "Port Status"]
    LINE_TYPES = {"new", "port", "upgrade", "resolve order", "byod",
                  "tablet", "wearable", "aia"}
    DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
    orders, lines = [], []
    cur = None
    for tr in trs:
        c = cells(tr)
        if not any(c):
            continue
        joined = " ".join(c)
        if "Customer Name" in c or "Page size" in joined \
                or "Data pager" in joined:
            continue
        if "Line Type" in c and "Line Status" in c:
            continue
        # LINE row: its second cell is a line type word
        if len(c) >= 8 and (c[1] or "").strip().lower() in LINE_TYPES:
            lines.append({**(cur or {}),
                          "line_no": c[0], "line_type": c[1],
                          "device": c[3] if len(c) > 3 else "",
                          "line_number": c[2],
                          "line_phone": c[4] if len(c) > 4 else "",
                          "plan": c[5] if len(c) > 5 else "",
                          "line_status": c[6] if len(c) > 6 else "",
                          "ship_date": c[8] if len(c) > 8 else "",
                          "delivered": c[9] if len(c) > 9 else "",
                          "port_status": c[10] if len(c) > 10 else ""})
            continue
        # ORDER row: wide, has a customer and an order date
        if len(c) >= 13:
            cand = c
            # the grid may carry a leading expand cell — align on the
            # first cell pair (customer, phone-ish) before a date cell
            off = None
            for k in range(0, min(4, len(cand) - 11)):
                if cand[k + 2] and DATE_RE.match(cand[k + 5] or ""):
                    off = k
                    break
            if off is None:
                continue
            cur = {"customer": cand[off + 2], "phone": cand[off + 3],
                   "dsi": cand[off + 4], "order_date": cand[off + 5],
                   "wireless_order": cand[off + 6], "ban": cand[off + 7],
                   "line_count": cand[off + 8], "rep": cand[off + 9],
                   "order_status": cand[off + 12]
                   if len(cand) > off + 12 else ""}
            orders.append(cur)
    import collections as _coll
    reps = _coll.Counter((l.get("rep") or "(none)") for l in lines)
    log("[ndsw] lines by rep: "
        + (", ".join(f"{k[:20]}={v}" for k, v in reps.most_common(12))
           or "NONE"))
    log(f"[ndsw] parsed {len(orders)} order(s), {len(lines)} line(s)")
    return orders, lines


def cached(today: dt.date):
    f = OUT_DIR / f"nds_wireless_{today.isoformat()}.html"
    return f if f.exists() else None


def recon(today: dt.date, log=print) -> int:
    """Line the per-line feed up against the latest DD (Scoutly RAW tab):
    per PAID NDS base line, find its customer's feed lines and show their
    statuses/dates — this is what locks the pricing rules before any
    board re-sources onto the feed."""
    import collections
    from automations.recruiting_report.fill import open_by_key
    f = cached(today)
    if not f:
        raise RuntimeError("no wireless cache for today — run the pull")
    orders, lines = parse(f.read_bytes(), log=log)
    by_cust = collections.defaultdict(list)
    for l in lines:
        by_cust[(l.get("customer") or "").upper()].append(l)
    sh = open_by_key("1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY")
    raw = next(w for w in sh.worksheets()
               if w.title.strip().lower() == "raw")
    vals = raw.get_all_values()
    hix = {h: k for k, h in enumerate(vals[0])}
    weeks = [r[0].strip() for r in vals[1:] if r and r[0].strip()]
    week = weeks[-1] if weeks else "?"

    def money(v):
        try:
            return float(str(v).replace("$", "").replace(",", "") or 0)
        except ValueError:
            return 0.0

    paid = [r for r in vals[1:]
            if r and r[0].strip() == week
            and r[hix["Campaign"]].strip() == "NDS Wireless"
            and r[hix["Commission Type"]].strip() == "Base"]
    log(f"[recon] DD week {week}: {len(paid)} base line(s)")
    hit = miss = 0
    for r in paid:
        cust = r[hix["Customer Name"]].strip().upper()
        amt = money(r[hix["Total $ to ICD"]])
        prod = r[hix["Product"]].strip()
        act = r[hix["Activation Date"]].strip()
        fl = by_cust.get(cust, [])
        if not fl:
            # token-overlap fallback
            ct = set(cust.split())
            for k, v in by_cust.items():
                if ct and (ct <= set(k.split()) or set(k.split()) <= ct):
                    fl = v
                    break
        if fl:
            hit += 1
            sts = ", ".join(f"{l['line_type']}/{l['device'][:10]}/"
                            f"{l['line_status']}/dlv:{l['delivered'] or '-'}"
                            for l in fl[:6])
            log(f"RECON paid {cust[:22]:22} ${amt:>6,.0f} {prod[:12]:12} "
                f"act:{act:10} | feed: {sts[:150]}")
        else:
            miss += 1
            log(f"RECON NOFEED {cust[:22]:22} ${amt:>6,.0f} {prod[:12]:12} "
                f"act:{act}")
    log(f"[recon] matched {hit}, no feed match {miss}")
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_wireless_pull")
    ap.add_argument("--days", type=int, default=31)
    ap.add_argument("--recon", action="store_true",
                    help="join today's cache against the latest DD")
    a = ap.parse_args(argv)
    today = dt.date.today()
    if a.recon:
        return recon(today)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = pull(today - dt.timedelta(days=a.days), today)
    out = OUT_DIR / f"nds_wireless_{today.isoformat()}.html"
    out.write_bytes(data)
    print(f"[ndsw] saved {out.name} ({len(data):,} bytes)")
    orders, lines = parse(data)
    import collections
    st = collections.Counter(l["line_status"] or "(blank)" for l in lines)
    print("[ndsw] line statuses: "
          + ", ".join(f"{k}={v}" for k, v in st.most_common(10)))
    ty = collections.Counter(l["line_type"] or "(blank)" for l in lines)
    print("[ndsw] line types: "
          + ", ".join(f"{k}={v}" for k, v in ty.most_common(10)))
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
