"""Customers for the contacts-and-wrap-up-text pipeline.

SINCE 2026-10-27 (Carlos: "instead of rafs sara plus can you start using my
nds sara plus"): sourced from the NDS merged SaraPlus pull (alphaletegp +
b2batt dealers, nds_metrics' cache), crew-filtered, from 2026-10-20 on. The
Raf-era notes below are history: the envelope path is retired.

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
    # business is OPTIONAL: Raf's fiber export is residential and carries no
    # business column at all (seen live 2026-10-08) — the contact just gets
    # no Company, and run.py's label falls back to the customer's name.
    missing = [k for k in _COLS if k not in out and k not in ("phone",
                                                             "business")]
    if missing:
        # chunked, so the full header survives the queue's result-cell cap
        fl = [str(f) for f in (fieldnames or [])]
        for i in range(0, len(fl), 6):
            # print, not log: wrapup silences the loader's log and this
            # dump must reach the run log regardless
            print("GHDR%d: %s" % (i // 6, " | ".join(fl[i:i + 6])),
                  flush=True)
        raise RuntimeError(
            "NDS SOH export is missing column(s) %s — GHDR lines above "
            "carry the full header" % (missing,))
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
    """The crew's NDS orders with Order Date in [since, until], shaped
    like sara.scrape()'s rows.

    SOURCE (2026-10-29, third switch): the WIRELESS PER-LINE FEED
    (nds_metrics.wireless_pull), because the alphaletegp SOH export has
    no Customer Name column at all and the 6:45 check died on it every
    morning. The feed carries customer first+last, contact phone, DSI,
    Wireless Order # and BAN — which also fills the wrap-up text's
    blanks. The 6:10 daily pull writes the cache this reads; a missing
    cache pulls fresh (browser, ~2 min)."""
    from automations.nds_metrics import run as NM
    from automations.nds_metrics import wireless_pull as WP
    from automations.total_knocks import guests as gst

    today = dt.date.today()
    f = WP.cached(today)
    if f is None:
        log("guest rows: no wireless cache today — pulling fresh")
        data = WP.pull(today - dt.timedelta(days=31), today, log=log)
        f = NM.OUT_DIR / f"nds_wireless_{today.isoformat()}.html"
        f.write_bytes(data)
    orders, _lines = WP.parse(f.read_bytes(), log=lambda *a, **k: None)

    crew_names = (gst.roster("Rafael Hidalgo", "Carlos Hidalgo")
                  + ["Carlos Hidalgo"])
    toks = [gst._tokens(n) for n in crew_names]

    def _is_crew(n):
        t = gst._tokens(n)
        return any(gst._subseq(ct, t) or gst._subseq(t, ct) for ct in toks)

    since = max(since, NM.NDS_SINCE)
    out: List[Dict[str, str]] = []
    for o in orders:
        d = _parse_us_date(o.get("order_date", ""))
        if d is None or not (since <= d <= until):
            continue
        if not _is_crew(o.get("rep", "")):
            continue
        out.append({
            "order_id": _norm(o.get("dsi", "")),
            "day": d.isoformat(),
            "order_date": _norm(o.get("order_date", "")),
            "rep": _norm(o.get("rep", "")),
            "business": "",
            "customer_name": _norm(o.get("customer", "")),
            "phone": _norm(o.get("phone", "")),
            "alt_phones": [],
            "wireless_order": _norm(o.get("wireless_order", "")),
            "ban": _norm(o.get("ban", "")),
        })
    log("crew rows (NDS wireless feed): %d order(s) %s..%s"
        % (len(out), since, until))
    for c in out:
        log("  %-10s %-14s %-24s %s"
            % (c["day"], c["order_id"], c["customer_name"][:24],
               c["phone"] or "NO PHONE"))
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
