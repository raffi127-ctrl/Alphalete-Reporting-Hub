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


WINDOW_DAYS = 10


def pull(start: dt.date, end: dt.date, log=print) -> bytes:
    """The wireless feed for [start, end], pulled in WINDOW_DAYS-day windows
    and concatenated. The dealer's grid shows one page of 100 orders: on
    2026-11-10 the 31-day window passed 100 orders and every pull since read
    the same 100 (the oldest) -- no order after 11/07 reached the tab, the
    wrap-up and never-texted checks saw "0 customer(s)" for four days.
    parse() walks the concatenated documents in order; windows are disjoint
    by order date, so no order appears twice."""
    chunks = []
    for w_start, w_end in windows(start, end):
        log(f"[ndsw] window {w_start}..{w_end}")
        chunks.append(_pull_window(w_start, w_end, log=log))
    return b"\n<!-- window -->\n".join(chunks)


def windows(start: dt.date, end: dt.date, days: int = WINDOW_DAYS):
    """[start, end] cut into runs of `days` days, oldest first."""
    out = []
    cur = start
    while cur <= end:
        w_end = min(end, cur + dt.timedelta(days=days - 1))
        out.append((cur, w_end))
        cur = w_end + dt.timedelta(days=1)
    return out


def _pull_window(start: dt.date, end: dt.date, log=print) -> bytes:
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


_ORDER_FIELDS = (("customer", "customer name"), ("phone", "contact phone"),
                 ("dsi", "order number"), ("order_date", "order date"),
                 ("wireless_order", "wireless order number"),
                 ("ban", "wireless account number"), ("line_count", "lines"),
                 ("rep", "salesperson"), ("order_status", "order status"))
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_DIGITS = re.compile(r"\D")


def _order_by_header(c, hdr_idx):
    """An order row read by the grid header's column names (None when no
    header was seen, the row is narrower than the header, or the cells
    under Customer Name / Order Date don't look like one)."""
    if not hdr_idx or "customer name" not in hdr_idx or "order date" not in hdr_idx:
        return None
    if len(c) <= max(hdr_idx["customer name"], hdr_idx["order date"]):
        return None

    def at(name):
        i = hdr_idx.get(name)
        return (c[i] if i is not None and i < len(c) else "").strip()

    if not at("customer name") or not _DATE_RE.match(at("order date")):
        return None
    return {key: at(name) for key, name in _ORDER_FIELDS}


def _order_by_position(c):
    """The pre-11/11 read, kept as the fallback when no header row came
    through: the first (customer, date) pair three cells apart, the customer
    sitting in cell 1..5 (one or two leading expand cells, or none), the
    rest of the order following the date in the old order; Order Status =
    the last cell."""
    for j in range(3, min(len(c), 9)):
        if _DATE_RE.match((c[j] or "").strip()) and (c[j - 3] or "").strip():
            g = lambda i: (c[i] if i < len(c) else "").strip()  # noqa: E731
            return {"customer": g(j - 3), "phone": g(j - 2), "dsi": g(j - 1),
                    "order_date": g(j), "wireless_order": g(j + 1), "ban": g(j + 2),
                    "line_count": g(j + 3), "rep": g(j + 4),
                    "order_status": (c[-1] or "").strip()}
    return None


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
    LINE_TYPES = {"new", "port", "upgrade", "byod",
                  "tablet", "wearable", "aia"}
    DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
    orders, lines = [], []
    cur = None
    adrift = False          # True while the lines being read have no readable order above them
    seen_nos = set()        # line numbers already read under `cur`
    dropped = 0
    hdr_idx = None          # {header text: cell index} once the grid header has been seen
    skipped = []            # wide rows that were neither a line nor an order (diagnostic)
    wide = []               # first rows wide enough to be an order row (diagnostic)
    hdr_cells = None        # the grid header row's cells (diagnostic)
    for tr in trs:
        c = cells(tr)
        if not any(c):
            continue
        joined = " ".join(c)
        if "Customer Name" in c or "Page size" in joined \
                or "Data pager" in joined:
            if "Customer Name" in c and hdr_cells is None:
                hdr_cells = c
                # 11/11: SaraPlus re-cut the order grid (one leading cell
                # instead of two, ICD Company ID / ICD Owner / Employer added
                # after Salesperson) and the positional read found no order
                # for a whole morning. Read order rows BY HEADER from here on.
                hdr_idx = {h.strip().lower(): i for i, h in enumerate(c) if h.strip()}
            continue
        if "Line Type" in c and "Line Status" in c:
            continue
        if len(c) >= 6 and (c[1] or "").strip().lower() not in LINE_TYPES \
                and len(skipped) < 4:
            skipped.append(c)
        if len(c) >= 13 and len(wide) < 3:        # the order-row candidates themselves
            wide.append(c)
        # "RESOLVE ORDER" row: an ORDER header with one extra cell (the
        # 'Resolve Order' button) after the expand cell, and no line number.
        # Until 11/19 it was read as a line and thrown away for having no
        # number, so the order never became `cur` and its lines were filed
        # under the customer ABOVE it in the grid: Danzell Vaughn (1 line)
        # showed 3 'Port Approved / Porting Issue' lines that were Osman
        # Justiniano's, Ana Mereno Ruiz's six lines were overwritten by Nelson
        # Martinez's (Carlos: "some orders will show porting issue and then we
        # look them up and they don't").
        if len(c) >= 8 and (c[1] or "").strip().lower() == "resolve order" and not (c[0] or "").strip():
            order = (_order_by_header(c, hdr_idx) or _order_by_header(c[:1] + c[2:], hdr_idx)
                     or _order_by_position(c))
            if order is None:
                # never file the next lines under the previous customer
                adrift = True
                log("[ndsw] a 'Resolve Order' row could not be read as an order (%d cells): %s"
                    % (len(c), " | ".join((x or "")[:16] for x in c[:12])))
                continue
            order["resolve"] = True
            cur, adrift, seen_nos = order, False, set()
            orders.append(cur)
            continue
        # LINE row: its second cell is a line type word
        if len(c) >= 8 and (c[1] or "").strip().lower() in LINE_TYPES:
            no = (c[0] or "").strip()
            if no and no in seen_nos and not adrift:
                # line numbers restart at 1 for every order: a number coming
                # round again means an order header went unread in between
                adrift = True
                log("[ndsw] line %s appears twice under %s -- an order header above it was not "
                    "read; that line and the ones after it are left out"
                    % (no, (cur or {}).get("customer", "?")))
            if adrift:
                dropped += 1
                continue
            seen_nos.add(no)
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
            order = _order_by_header(c, hdr_idx) or _order_by_position(c)
            if order is None:
                continue
            cur, adrift, seen_nos = order, False, set()
            orders.append(cur)
    if dropped:
        log(f"[ndsw] {dropped} line row(s) left out: no readable order header above them")
    import collections as _coll
    reps = _coll.Counter((l.get("rep") or "(none)") for l in lines)
    log("[ndsw] lines by rep: "
        + (", ".join(f"{k[:20]}={v}" for k, v in reps.most_common(12))
           or "NONE"))
    log(f"[ndsw] parsed {len(orders)} order(s), {len(lines)} line(s)")
    if lines and not orders:
        # 11/11: 316 lines, 0 orders, tab left as it was -- the order rows had
        # changed shape and nothing said how. Show what was skipped, the row
        # width histogram, and the raw markup around the first order header
        # (chunked so `logtail nds_metrics "[ndsw] raw"` can page it).
        for c in skipped:
            log(f"[ndsw] no-order-row sample ({len(c)} cells): "
                + " | ".join((x or "")[:18] for x in c[:14]))
        if hdr_cells is not None:
            log(f"[ndsw] wide header ({len(hdr_cells)} cells): " + " | ".join(x[:22] for x in hdr_cells))
        for c in wide:
            log(f"[ndsw] wide row ({len(c)} cells): " + " | ".join((x or "")[:22] for x in c))
        widths = _coll.Counter(len(cells(tr)) for tr in trs)
        log("[ndsw] row widths: " + ", ".join(f"{w}x{n}" for w, n in sorted(widths.items())))
        at = txt.find("Customer Name")
        raw = re.sub(r"\s+", " ", txt[max(0, at - 600): at + 2400]) if at >= 0 else "(no 'Customer Name' in the export)"
        for i in range(0, min(len(raw), 3000), 150):
            log(f"[ndsw] raw {i // 150:02d}: {raw[i:i + 150]}")
    return orders, lines


def line_number(l: dict) -> str:
    """The line's phone number, digits only ('' when it has none yet). The
    grid has carried it in either of two neighbouring cells, so take the one
    that reads as a number rather than trusting the key's name."""
    for k in ("device", "line_phone"):
        v = str(l.get(k) or "")
        d = _DIGITS.sub("", v)
        if len(d) >= 10 and not re.search(r"[A-Za-z]", v):
            return d[-10:]
    return ""


def trace(today: dt.date, needle: str = "", log=print) -> int:
    """READ-ONLY look at one day's cached feed, compact enough for logdump:
    every order whose parsed line rows do not match its own 'Lines' count
    (a line row filed under the wrong order shows up exactly there), every
    phone number that sits under more than one order, and -- for `needle`
    (customer / rep / order # / phone substring) -- the matching orders with
    their neighbours in document order and every line under them."""
    import collections as _coll
    f = cached(today)
    if not f:
        log(f"[trace] no wireless cache for {today}")
        return 1
    orders, lines = parse(f.read_bytes(), log=lambda *_: None)
    by_order = _coll.OrderedDict((id(o), []) for o in orders)
    owner = {id(o): o for o in orders}
    orphan = 0
    for l in lines:
        hit = [k for k, o in owner.items() if all(l.get(f_) == o.get(f_) for f_ in ("wireless_order", "dsi", "customer", "order_date"))]
        if hit:
            by_order[hit[-1]].append(l)
        else:
            orphan += 1
    log(f"[trace] {today}: {len(orders)} order(s), {len(lines)} line(s), {orphan} line(s) with no order")

    def show(o, mark=""):
        ls = by_order[id(o)]
        log(f"[trace] {mark}#{orders.index(o):03d} {o.get('customer','')[:26]} | {o.get('rep','')[:22]} | {o.get('order_date','')} | "
            f"{o.get('wireless_order','')} | hdr lines={o.get('line_count','')} parsed={len(ls)} | {o.get('order_status','')[:30]}")
        for l in ls:
            log(f"[trace]     L{l.get('line_no','')} {l.get('line_type','')[:8]} {line_number(l) or '(no number)'} | {l.get('line_status','')} | "
                f"ship {l.get('ship_date','') or '-'} dlv {l.get('delivered','') or '-'} port {l.get('port_status','') or '-'}"
                # 11/27: the device and plan price a line (phone vs BYOD, the
                # Premium / Extra add-on) -- "how much is that sale worth?"
                f" | dev {(l.get('device','') or '-')[:44]} | plan {(l.get('plan','') or '-')[:44]}")

    bad = [o for o in orders if str(o.get("line_count", "")).strip().isdigit()
           and int(o["line_count"]) != len(by_order[id(o)])]
    log(f"[trace] orders whose line rows != their 'Lines' count: {len(bad)}")
    for o in bad[:40]:
        show(o, "MISMATCH ")
    phones = _coll.defaultdict(set)
    for o in orders:
        for l in by_order[id(o)]:
            if line_number(l):
                phones[line_number(l)].add(orders.index(o))
    dup = {p_: ix for p_, ix in phones.items() if len(ix) > 1}
    log(f"[trace] phone numbers under more than one order: {len(dup)}")
    for p_, ix in list(dup.items())[:40]:
        log(f"[trace] DUP {p_} -> " + ", ".join(f"#{i:03d} {orders[i].get('customer','')[:20]}" for i in sorted(ix)))
    n = (needle or "").strip().lower()
    if n:
        hits = [i for i, o in enumerate(orders)
                if n in " ".join(str(v) for v in o.values()).lower()
                or any(_DIGITS.sub("", n) and _DIGITS.sub("", n) in line_number(l) for l in by_order[id(o)])]
        log(f"[trace] orders matching {needle!r}: {len(hits)}")
        seen = set()
        for i in hits:
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(orders) and j not in seen:
                    seen.add(j)
                    show(orders[j], "HIT " if j == i else "near ")
    return 0


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
