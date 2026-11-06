"""NDS Activation Revenue, priced per LINE -- the way the direct deposit pays.

Carlos 2026-11-06, after the $6,153 board vs $6,311 deposit reconciliation
("you should price each individual line and add internet air"):

WHAT THE DEPOSIT DOES (Vantura RAW tab, Campaign 'NDS Wireless'): one Base
row per LINE, dated the day THAT line activated (Port Line $213 OOF / $193
IF, BYOD - Port $188); an Add On row per line for its plan (Unlimited Extra
$10 / Premium $15, Protect $15); one AIR row per Internet Air install ($93 +
$30 auto bill pay); plus the rep's monthly Tier Volume Bonus rows. Its weeks
run Monday..Sunday (WE 11.1 = 10/26..11/1).

WHAT THIS BOARD DOES: the same, from what SaraPlus shows today.
  * lines + statuses: the NDS Wireless Resolution Report (wireless_pull's
    daily cache, parsed by sp_order_log.wireless_lines) -- the per-line view
    Carlos means by "on sara plus ... you can see the status of each
    individual line". The Sales Order History (SOH) export is order-level:
    'Active' there only means the FIRST line activated.
  * a line's activation DAY: sp_order_log's activation tracker (the day a
    line FIRST showed Active). Every run replays ALL cached feeds oldest ->
    newest into it, so history survives a missed morning and does not
    depend on which order-log path ran. A flip seen by the 06:10 pull
    happened the day before (LIVE_FLIP_LAG_DAYS); a line already Active the
    first time it was ever seen takes the order's SOH active date (src
    "order").
  * price: sow_rates.json at base comp -- port $213 / BYOD port $188 / new
    line $25 / upgrade $30 / tablet $25, OOF rates (no IF/OOF flag anywhere
    in SaraPlus); the plan's Unlimited Extra ($10) / Premium ($15) rides on
    an Active line; Internet Air $93 (+$30 when the order has ABP) from the
    SOH Internet columns, on its install date.
  * NOT priced (deposit only): the monthly Tier Volume Bonus, Protect
    Advantage, the in-footprint rate.
  * weeks: Monday..Sunday like the deposit -- "last week" is the week the
    Wednesday deposit pays.
  * Cancelled $: a line now Disconnected/Cancelled, in the week it died
    (the day the feed first showed it dead, else the order's cancel date).
    A line that was paid in an EARLIER week stays posted there as well --
    that is the chargeback coming.
  * Still Open $: every line not yet Active and not dead, whatever its week.
An order the feed does not carry (window edge, feed missing) is priced the
old way -- at order level on its SOH active date -- and the log counts them.

    lucy rerun nds_metrics --only activation_revenue              # dry
    lucy rerun nds_metrics_probe --line-calib   # lines vs the deposit
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.nds_metrics.run import (OUT_DIR, _parse_date, _soh_cell,
                                         price_order, sow_rates)

# The feed is pulled ~06:10; a line that flipped Active since yesterday's
# pull activated the day before the pull that first shows it.
LIVE_FLIP_LAG_DAYS = 1
DEAD_WORDS = ("disconnect", "cancel")
FEED_RE = re.compile(r"^nds_wireless_(\d{4}-\d{2}-\d{2})\.html$")


# ---------------------------------------------------------------- weeks ----

def week_bounds(today: dt.date) -> Tuple[dt.date, dt.date, dt.date, dt.date]:
    """(last_start, last_end, this_start, this_end) as MONDAY..SUNDAY weeks
    -- the deposit's weeks (WE Sunday), unlike the Sun..Sat weeks the other
    boards use (att_order_log.payout.week_bounds)."""
    this_start = today - dt.timedelta(days=today.weekday())
    this_end = this_start + dt.timedelta(days=6)
    return (this_start - dt.timedelta(days=7),
            this_start - dt.timedelta(days=1), this_start, this_end)


def label(start: dt.date, end: dt.date) -> str:
    return "WE {}.{}: {}.{} - {}.{}".format(end.month, end.day, start.month,
                                           start.day, end.month, end.day)


def _iso(v) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


# ---------------------------------------------------------- feed + ledger ----

def cached_feeds(out_dir: Optional[Path] = None) -> List[Tuple[dt.date, Path]]:
    """Every cached wireless feed, oldest first."""
    out = []
    for p in (out_dir or OUT_DIR).glob("nds_wireless_*.html"):
        m = FEED_RE.match(p.name)
        if not m:
            continue
        d = _iso(m.group(1))
        if d is None or p.stat().st_size < 2000:
            continue
        out.append((d, p))
    return sorted(out)


def soh_dates(ix, orders) -> Tuple[Dict[str, str], Dict[str, Optional[dt.date]]]:
    """({order id: active date ISO} for the tracker's seed, {order id:
    cancel date}) off the SOH export."""
    active, cancel = {}, {}
    for r in orders:
        oid = _soh_cell(ix, r, "Order ID")
        if not oid:
            continue
        d = _parse_date(_soh_cell(ix, r, "Wireless Active Date"))
        if d:
            active[oid] = d.isoformat()
        cancel[oid] = _parse_date(_soh_cell(ix, r, "Wireless Cancel Date"))
    return active, cancel


def replay(feeds: Sequence[Tuple[dt.date, Path]], soh_active: Dict[str, str],
           log=print, save: bool = True):
    """Fold every cached feed, oldest first, into sp_order_log's activation
    tracker. first_active / first_dead never move once stamped, so a
    replay is idempotent -- the board no longer depends on which order-log
    path ran each morning. -> (state, newest feed date, its lines)."""
    from automations.sp_order_log import wireless_lines as WL
    state = WL.load_state()
    before = len(state)
    newest_date, newest_lines = None, []
    folded = []
    for d, p in feeds:
        try:
            lines = WL.parse_wireless_xls(p.read_bytes())
        except Exception as e:  # noqa: BLE001
            log(f"[nds] feed {p.name} unreadable ({type(e).__name__}) -- skipped")
            continue
        if not lines:
            log(f"[nds] feed {p.name}: zero lines -- skipped")
            continue
        WL.update_state(state, lines, d, {}, soh_active,
                        log=lambda *_a, **_k: None)
        folded.append(d)
        newest_date, newest_lines = d, lines
    if folded:
        log(f"[nds] line ledger: {len(folded)} feed day(s) replayed "
            f"{folded[0]}..{folded[-1]}, {len(state)} line(s) tracked "
            f"(was {before})")
        if save:
            WL.save_state(WL.prune_state(state, newest_date))
    else:
        log("[nds] line ledger: NO cached wireless feed -- order-level "
            "pricing for every order")
    return state, newest_date, newest_lines


# -------------------------------------------------------------- pricing ----

def activation_date(rec: Optional[dict]) -> Optional[dt.date]:
    if not rec:
        return None
    d = _iso(rec.get("first_active"))
    if d and rec.get("src") == "live":
        d -= dt.timedelta(days=LIVE_FLIP_LAG_DAYS)
    return d


def dead_date(rec: Optional[dict], line_status: str,
              soh_cancel: Optional[dt.date]) -> Optional[dt.date]:
    if not any(w in (line_status or "").lower() for w in DEAD_WORDS):
        return None
    d = _iso((rec or {}).get("first_dead"))
    if d:
        return d - dt.timedelta(days=LIVE_FLIP_LAG_DAYS)
    return soh_cancel


def is_byod(ln: dict) -> bool:
    lt = (ln.get("line_type") or "").strip().lower()
    hay = " ".join(str(ln.get(k) or "") for k in
                   ("device_type", "device", "plan")).lower()
    return lt == "byod" or "byod" in hay


def price_line(ln: dict, rates: Optional[dict] = None) -> Tuple[float, str]:
    """-> (base $, kind) for one feed line. Air lines are $0 here: Internet
    Air is priced off the SOH's Internet columns (which carry the install
    date); an AIA line on the wireless report would double it."""
    sw = (rates or sow_rates())["wireless"]
    lt = (ln.get("line_type") or "").strip().lower()
    hay = " ".join(str(ln.get(k) or "") for k in
                   ("device_type", "device")).lower()
    if lt == "aia" or "aia" in hay or "internet air" in hay:
        return 0.0, "air"
    if lt in ("tablet", "wearable") or "ipad" in hay or "tablet" in hay \
            or "watch" in hay:
        return float(sw["tablet_wearable_nonbyod"]), "tablet"
    if lt == "new":
        return float(sw["new_line"]), "new"
    if lt == "upgrade":
        return float(sw["upgrade_voice"]), "upgrade"
    if lt in ("port", "byod", ""):
        if is_byod(ln):
            return float(sw["port_byod"]["OOF"]), "byod port"
        return float(sw["port_nonbyod"]["OOF"]), "port"
    return 0.0, "unpriced:" + lt


def addon_of(plan: str, rates: Optional[dict] = None) -> float:
    ad = (rates or sow_rates())["addons"]
    p = (plan or "").lower()
    if "premium" in p:
        return float(ad["unlimited_premium"])
    if "extra" in p:
        return float(ad["unlimited_extra"])
    return 0.0


def assign_byod(order_lines: List[dict], n_byod: int) -> None:
    """The SOH counts the order's BYOD lines; when the feed's own words mark
    none of them, flag that many port lines as BYOD (unshipped ones first
    -- a BYOD line ships no phone) so the order prices at its SOH mix."""
    marked = sum(1 for ln in order_lines if is_byod(ln))
    if n_byod <= 0 or marked >= n_byod:
        return
    ports = [ln for ln in order_lines
             if (ln.get("line_type") or "").strip().lower() in ("port", "")
             and not is_byod(ln)]
    ports.sort(key=lambda ln: (bool((ln.get("ship_date") or "").strip()),
                               str(ln.get("line_idx") or "").zfill(3)))
    for ln in ports[:n_byod - marked]:
        ln["_byod_assumed"] = True
        ln["device_type"] = ((ln.get("device_type") or "") + " BYOD").strip()


# ------------------------------------------------------------- the board ----

def _bucket(a: dict, key: str, d: dt.date, amt: float, wk) -> str:
    ls, le, ts, te = wk
    if ls <= d <= le:
        a[key + "_last"] += amt
        return key + "_last"
    if ts <= d <= te:
        a[key + "_this"] += amt
        return key + "_this"
    return "older" if d < ls else "future"


def _fresh():
    return {"posted_last": 0.0, "posted_this": 0.0, "open": 0.0,
            "can_last": 0.0, "can_this": 0.0}


def compute(soh, today: dt.date, lines: Sequence[dict], state: dict,
            rates: Optional[dict] = None, log=print) -> dict:
    """The pure core: SOH (ix, orders, pulled_at) + feed lines + tracker
    state -> {"tables", "detail", "stats"}. No IO."""
    from automations.sp_order_log import wireless_lines as WL
    rates = rates or sow_rates()
    ix, orders, _pulled = soh
    wk = week_bounds(today)
    soh_active, soh_cancel = soh_dates(ix, orders)
    by_order = {}
    for r in orders:
        oid = _soh_cell(ix, r, "Order ID")
        if oid:
            by_order[oid] = r
    lines_by_order: Dict[str, List[dict]] = collections.defaultdict(list)
    for ln in lines:
        if ln.get("order_id") in by_order:
            lines_by_order[ln["order_id"]].append(dict(ln))
    reps: Dict[str, dict] = {}
    detail: List[dict] = []
    stats = collections.Counter()

    def rep_of(r):
        return _soh_cell(ix, r, "User Name")

    for oid, r in by_order.items():
        rep = rep_of(r)
        if not rep:
            continue
        a = reps.setdefault(rep, _fresh())
        panel = lines_by_order.get(oid)
        if _soh_cell(ix, r, "Wireless Status") or _soh_cell(ix, r, "Wireless Line Count"):
            if panel:
                try:
                    n_byod = int(float(_soh_cell(ix, r, "BYOD Line Count") or 0))
                except ValueError:
                    n_byod = 0
                assign_byod(panel, n_byod)
                for ln in panel:
                    rec = state.get(WL.line_key(ln))
                    base, kind = price_line(ln, rates)
                    act = activation_date(rec)
                    dead = dead_date(rec, ln.get("line_status", ""),
                                     soh_cancel.get(oid))
                    addon = addon_of(ln.get("plan", ""), rates) if act else 0.0
                    amt = base + addon
                    where = "open"
                    if dead is not None:
                        # SOW: activated-and-disconnected the same week is
                        # never paid -- cancelled only
                        if act is not None and week_bounds(act)[2] == week_bounds(dead)[2]:
                            act = None
                        where = _bucket(a, "can", dead, base, wk)
                        stats["dead"] += 1
                    if act is not None:
                        where = _bucket(a, "posted", act, amt, wk) + ("+can" if dead else "")
                        stats["active"] += 1
                    elif dead is None:
                        a["open"] += base
                        stats["open"] += 1
                    if kind == "air":
                        stats["air_lines_on_feed"] += 1
                    detail.append({
                        "rep": rep, "customer": ln.get("customer", ""),
                        "order_id": oid, "order_date": ln.get("order_date", ""),
                        "line": ln.get("line_idx", ""), "type": ln.get("line_type", ""),
                        "device_type": ln.get("device_type", ""),
                        "device": ln.get("device", ""), "plan": ln.get("plan", ""),
                        "status": ln.get("line_status", ""),
                        "first_active": (rec or {}).get("first_active", ""),
                        "src": (rec or {}).get("src", ""),
                        "first_dead": (rec or {}).get("first_dead", ""),
                        "activation": act.isoformat() if act else "",
                        "dead": dead.isoformat() if dead else "",
                        "kind": kind + (" (BYOD assumed)" if ln.get("_byod_assumed") else ""),
                        "base": base, "addon": addon, "bucket": where})
                stats["lines"] += len(panel)
            else:
                # not on the wireless report: order-level, the old way
                amt = price_order(ix, r)
                st = _soh_cell(ix, r, "Wireless Status").lower()
                act = _parse_date(_soh_cell(ix, r, "Wireless Active Date"))
                where = "open"
                if any(w in st for w in DEAD_WORDS):
                    d = soh_cancel.get(oid) or act or today
                    where = _bucket(a, "can", d, amt, wk)
                elif act is None:
                    a["open"] += amt
                else:
                    where = _bucket(a, "posted", act, amt, wk)
                stats["orders_off_report"] += 1
                detail.append({
                    "rep": rep, "customer": "", "order_id": oid,
                    "order_date": _soh_cell(ix, r, "Order Date"), "line": "(order)",
                    "type": "order-level", "device_type": "", "device": "",
                    "plan": "", "status": _soh_cell(ix, r, "Wireless Status"),
                    "first_active": "", "src": "soh", "first_dead": "",
                    "activation": act.isoformat() if act else "",
                    "dead": "", "kind": "order", "base": amt, "addon": 0.0,
                    "bucket": where})
        # Internet Air off the SOH (install date = the deposit's activation)
        pkg = _soh_cell(ix, r, "Internet Package").lower()
        ist = _soh_cell(ix, r, "Internet Status").lower()
        if "air" in pkg and (ist or _soh_cell(ix, r, "Internet Install Date")):
            air = rates["internet_air"]
            amt = float(air["activation"]) + (
                float(air["auto_bill_pay_bonus"])
                if _soh_cell(ix, r, "ABP").upper() == "Y" else 0.0)
            inst = _parse_date(_soh_cell(ix, r, "Internet Install Date"))
            canc = _parse_date(_soh_cell(ix, r, "Internet Cancel Date"))
            where = "open"
            if any(w in ist for w in DEAD_WORDS):
                where = _bucket(a, "can", canc or inst or today, amt, wk)
            elif ist == "active" and inst:
                where = _bucket(a, "posted", inst, amt, wk)
            else:
                a["open"] += amt
            stats["air"] += 1
            detail.append({
                "rep": rep, "customer": "", "order_id": oid,
                "order_date": _soh_cell(ix, r, "Order Date"), "line": "AIR",
                "type": "internet air", "device_type": "", "device": "",
                "plan": _soh_cell(ix, r, "Internet Package"),
                "status": _soh_cell(ix, r, "Internet Status"),
                "first_active": "", "src": "soh", "first_dead": "",
                "activation": inst.isoformat() if inst else "",
                "dead": canc.isoformat() if canc else "", "kind": "air",
                "base": amt, "addon": 0.0, "bucket": where})

    ls, le, ts, te = wk

    def _table(start, end, pk, ck):
        rows = [{"rep": rep, "posted": round(a[pk]),
                 "pending": round(a["open"]), "canceled": round(a[ck])}
                for rep, a in reps.items()]
        rows.sort(key=lambda x: (-x["posted"], x["rep"].lower()))
        totals = {k: sum(x[k] for x in rows)
                  for k in ("posted", "pending", "canceled")}
        return {"label": label(start, end), "rows": rows, "totals": totals}

    tables = {"last": _table(ls, le, "posted_last", "can_last"),
              "this": _table(ts, te, "posted_this", "can_this")}
    return {"tables": tables, "detail": detail, "stats": stats, "weeks": wk}


def log_tables(tables: dict, log=print) -> None:
    """The same grammar the order-level board logged (DD reconciliation
    visibility, Carlos 2026-10-28): act-rev <label>: posted / open /
    cancelled, then one line per rep."""
    for key in ("last", "this"):
        t = tables[key]
        log(f"[nds] act-rev {t['label']}: posted ${t['totals']['posted']:,}"
            f" / open ${t['totals']['pending']:,}"
            f" / cancelled ${t['totals']['canceled']:,}")
        for row in t["rows"]:
            if row["posted"]:
                log(f"[nds]   {key} {row['rep'][:26]}: ${row['posted']:,}")


def prepare(soh, today: dt.date, log=print, save: bool = True) -> dict:
    """IO wrapper: cached feeds -> replayed ledger -> compute()."""
    ix, orders, pulled_at = soh
    soh_active, _ = soh_dates(ix, orders)
    feeds = cached_feeds()
    state, feed_date, lines = replay(feeds, soh_active, log=log, save=save)
    res = compute(soh, today, lines, state, log=log)
    res["feed_date"] = feed_date
    res["pulled_at"] = pulled_at
    s = res["stats"]
    log(f"[nds] act-rev lines: {s['lines']} on the wireless report "
        f"({s['active']} active, {s['open']} open, {s['dead']} dead), "
        f"{s['orders_off_report']} order(s) off the report priced at order "
        f"level, {s['air']} Internet Air")
    log_tables(res["tables"], log=log)
    return res


def build(soh, today: dt.date, out: Path, log=print) -> Path:
    from automations.box_order_log import png as bpng
    res = prepare(soh, today, log=log)
    fd = res["feed_date"]
    feed_note = (f"wireless report {fd:%m/%d}" if fd
                 else "NO wireless report -- every order priced at order level")
    sub = ("NDS -- $ by activation week, Mon-Sun like the deposit. Each LINE "
           "priced the day it first shows Active on SaraPlus's wireless "
           f"report ({feed_note}); Internet Air $93 (+$30 ABP) on its install "
           "date;\nUnlimited Extra/Premium ride with an active line. OOF rates "
           "at base comp (no IF flag in SaraPlus); tier volume bonus + Protect "
           "are deposit-only. A paid line that later dies shows in Cancelled $ "
           f"too. SaraPlus pulled {res['pulled_at']:%H:%M}.")
    saved = list(bpng.COLS)
    bpng.COLS[:] = [("Rep Name", "rep", "left"),
                    ("Posted $", "posted", "center"),
                    ("Cancelled $", "canceled", "center"),
                    ("Still Open $", "pending", "center")]
    try:
        bpng.render(res["tables"], out, money=True, subtitle=sub)
    finally:
        bpng.COLS[:] = saved
    log("[nds] activation revenue (SARAPLUS per line + SOW base comp)")
    return out
