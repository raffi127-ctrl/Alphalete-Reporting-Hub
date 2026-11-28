"""NDS sale revenue posts: every new AT&T (NDS) order priced and posted in
#alphalete-gp-sales a few minutes after the sale.

Carlos 2026-11-28: "Lucy post on slack when someone makes a sale. Are you able
to make her post the revenue generated?" ... "Yes build it with a sample
before going live".

WHY A SECOND POST. The sale shout-out comes from the office Mac's SaraPlus
DASHBOARD (icd_alerts, every ~2 min): a count per rep, so it knows "6 lines"
and nothing about the phones or the plan. Those are on SaraPlus's wireless
order report, one row per line (device "Smartphone" = a new phone that ships,
or BYOD; the plan; port / new number / upgrade). This reads the day's orders
off that report on Lucy 2, prices every order it has not posted yet exactly
the way the revenue board does (line_revenue.price_line + addon_of) and posts
one line per order:

    AT&T — :dollar: Anairt's sale = $1,368 · 6 new phones · Premium

The revenue board's rules:
  * port with a new phone $213, BYOD port $188, new number $25, upgrade $30,
    tablet / watch $25, + Premium $15 / Extra $10 a line (sow_rates.json);
  * in-footprint is not known on the day (Tableau marks it later), so every
    port prices out-of-footprint, as the board does until then;
  * cancelled lines are $0; Internet Air is not on this report; the weekly
    rep tier bonus is not in the number.

Runs every 5 minutes on LUCY 2 (com.alphalete.nds-sale-revenue,
deploy/nds_sale_revenue.sh); a check does nothing outside 10am-12:20am. It
keeps its own copy of the report (sale_revenue_feed.html), never
nds_wireless_<date>.html, which the revenue board replays as the morning feed.

    python -m automations.nds_metrics.sale_revenue --sample 2026-11-27  # that day's posts off the cached morning feed; nothing pulled or posted
    python -m automations.nds_metrics.sale_revenue                      # pull today's orders, print what would post (DRY)
    python -m automations.nds_metrics.sale_revenue --date 2026-11-27    # the same for another day (DRY)
    python -m automations.nds_metrics.sale_revenue --post               # post the new ones and remember them
    python -m automations.nds_metrics.sale_revenue --baseline           # remember the day's orders, post nothing
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from automations.nds_metrics.run import CHANNEL, NDS_SARA_PROFILE, OUT_DIR

OFFICE_KEY = "carlos-b2batt"        # the shout-outs' office: its sold-under swaps apply
PREFIX = "AT&amp;T — "              # the shout-outs' label; Slack text must escape &
STATE = OUT_DIR / "sale_revenue_posted.json"
FEED = OUT_DIR / "sale_revenue_feed.html"
START = dt.time(10, 0)              # first check of the day
LATE = dt.time(0, 20)               # checks just after midnight close out the day before
FIRST_POST_UNTIL = dt.time(10, 30)  # a day's FIRST check after this records, never posts a backlog
KEEP_DAYS = 7

# price_line's kinds -> the words in the post, in this order
KINDS = (("port", "new phone", "new phones"),
         ("byod port", "BYOD", "BYOD"),
         ("new", "new number", "new numbers"),
         ("upgrade", "upgrade", "upgrades"),
         ("tablet", "tablet/watch", "tablets/watches"))


def sale_day(now: dt.datetime) -> Optional[dt.date]:
    """The day this check is for: 10:00-23:59 -> today; 00:00-00:20 ->
    yesterday (a sale rung at 11:58pm still gets its line); else None."""
    t = now.time()
    if t >= START:
        return now.date()
    if t <= LATE:
        return now.date() - dt.timedelta(days=1)
    return None


def _date(text) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(str(text or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def order_groups(lines: List[dict], day: dt.date) -> Dict[str, List[dict]]:
    """line_revenue.parse_feed lines -> {order number: its lines} for the
    orders dated `day`."""
    out: Dict[str, List[dict]] = {}
    for ln in lines:
        oid = str(ln.get("order_id") or "").strip()
        if oid and _date(ln.get("order_date")) == day:
            out.setdefault(oid, []).append(ln)
    return out


def price(order_lines: List[dict], rates: Optional[dict] = None) -> dict:
    """One order -> {"total", "lines", "kinds": {kind: n}, "plans": {"Premium"/"Extra": n},
    "cancelled": n}. Every line the way the revenue board prices it once
    active: base (price_line, out-of-footprint) + the plan add-on."""
    from automations.nds_metrics import line_revenue as LR
    rates = rates or LR.sow_rates()
    out = {"total": 0.0, "lines": 0, "kinds": {}, "plans": {}, "cancelled": 0}
    for ln in order_lines:
        if "cancel" in str(ln.get("line_status") or "").lower():
            out["cancelled"] += 1
            continue
        base, kind = LR.price_line(ln, rates)
        if kind == "air" or kind.startswith("unpriced"):
            continue                    # Air is priced off the SOH, never this report
        plan = str(ln.get("plan") or "").lower()
        out["total"] += base + LR.addon_of(plan, rates)
        out["lines"] += 1
        out["kinds"][kind] = out["kinds"].get(kind, 0) + 1
        for word in ("Premium", "Extra"):
            if word.lower() in plan:
                out["plans"][word] = out["plans"].get(word, 0) + 1
                break
    return out


def describe(p: dict) -> str:
    """'6 new phones · Premium' / '3 new phones · 1 BYOD · 2 Premium · 2 Extra'."""
    parts = []
    for kind, one, many in KINDS:
        n = p["kinds"].get(kind, 0)
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    plans = p["plans"]
    if len(plans) == 1 and sum(plans.values()) == p["lines"]:
        parts.append(next(iter(plans)))         # every line on it: just the name
    else:
        parts += [f"{n} {name}" for name, n in plans.items()]
    return " · ".join(parts)


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def seller(sara_name: str, day: dt.date) -> str:
    """Who really sold: a sold-under swap (Esmeralda's login = Jacob, the
    shout-outs' rule) or the SaraPlus name itself."""
    try:
        from automations.icd_alerts import rep_names
        real = rep_names.sold_under_for(OFFICE_KEY, day, sara_name)
    except Exception:  # noqa: BLE001 -- the swap list is display sugar
        real = ""
    return real or sara_name


def display_names(full_names) -> Dict[str, str]:
    """{full name: what the post calls them}: the first name, or 'First L.'
    when two different sellers that day share a first name."""
    from automations.shared.sale_hype import short_name
    shown = {n: short_name(n) for n in full_names}
    firsts: Dict[str, set] = {}
    for n, s in shown.items():
        firsts.setdefault(s.split()[0].lower(), set()).add(s.lower())
    out = {}
    for n, s in shown.items():
        words = s.split()
        if len(firsts[words[0].lower()]) > 1 and len(words) > 1:
            out[n] = f"{words[0]} {words[-1][0]}."
        else:
            out[n] = words[0]
    return out


def lines_for(groups: Dict[str, List[dict]], oids, day: dt.date,
              rates: Optional[dict] = None) -> List[Tuple[str, str, dict]]:
    """[(order number, post line, priced)] for `oids` (orders with nothing
    priceable are left out), named against every seller of the day."""
    sellers = {oid: seller(str(ls[0].get("salesperson") or "?"), day)
               for oid, ls in groups.items()}
    names = display_names(set(sellers.values()))
    out = []
    for oid in sorted(oids, key=lambda o: (sellers[o].lower(), o)):
        p = price(groups[oid], rates)
        if p["lines"] <= 0:
            continue
        out.append((oid, f"{PREFIX}:dollar: {_esc(names[sellers[oid]])}'s sale = "
                         f"${p['total']:,.0f} · {describe(p)}", p))
    return out


# ------------------------------------------------------------------ state --

def load_state(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 -- no memory: every day starts fresh
        return {}


def save_state(state: dict, today: dt.date, path: Path = STATE) -> None:
    keep = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    state = {d: v for d, v in state.items() if d >= keep}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True))


def profile_busy(profile: Path = NDS_SARA_PROFILE) -> bool:
    """Chromium keeps a 'SingletonLock' link (-> 'host-PID') in a profile it
    has open and will not open it twice: True while that PID is alive (the
    morning pull or a hand rerun has it), so this check waits for the next."""
    try:
        target = os.readlink(str(Path(profile) / "SingletonLock"))
        pid = int(target.rsplit("-", 1)[-1])
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# -------------------------------------------------------------------- run --

def decide(state: dict, day: dt.date, groups: Dict[str, List[dict]],
           now: dt.datetime, baseline: bool = False) -> Tuple[List[str], bool]:
    """-> (order numbers to post, recording-only?). A day's first check
    after FIRST_POST_UNTIL (Lucy 2 was off, or this was just switched on)
    records the day's orders and posts none: a backlog is not news."""
    seen = (state.get(day.isoformat()) or {}).get("orders") or {}
    new = [oid for oid in groups if oid not in seen]
    first = day.isoformat() not in state
    late_first = first and not (day == now.date() and START <= now.time() <= FIRST_POST_UNTIL)
    return new, bool(baseline or late_first)


def check(now: dt.datetime, post: bool = False, baseline: bool = False,
          day: Optional[dt.date] = None, pull: Optional[Callable] = None,
          client=None, log=print, state_path: Path = STATE) -> int:
    from automations.nds_metrics import line_revenue as LR
    day = day or sale_day(now)
    if day is None:
        log("[salerev] outside 10am-12:20am -- nothing to do")
        return 0
    if pull is None:
        if profile_busy():
            log("[salerev] the SaraPlus profile is open in another job -- next check")
            return 0
        from automations.nds_metrics import wireless_pull as NW
        data = NW.pull(day, day, log=log)
        FEED.parent.mkdir(parents=True, exist_ok=True)
        FEED.write_bytes(data)
    else:
        data = pull(day)
    groups = order_groups(LR.parse_feed(data), day)
    state = load_state(state_path)
    new, record_only = decide(state, day, groups, now, baseline)
    rows = lines_for(groups, new, day)
    dry = not post and not baseline
    log(f"[salerev] {day}: {len(groups)} order(s) on the report, {len(new)} new, "
        f"{len(rows)} priced" + (" -- RECORDING ONLY, nothing posted"
                                 if record_only and not dry else ""))
    for _oid, text, p in rows:
        log("    " + text.replace("&amp;", "&"))
    if dry:
        log("[salerev] DRY RUN -- nothing posted or remembered (--post to post)")
        return 0
    if record_only:
        _remember(state, day, groups, new, now, posted=False)
        save_state(state, now.date(), state_path)
        return 0
    if rows:
        if client is None:
            from automations.shared.slack_metrics_post import _client
            client = _client()
        client.chat_postMessage(channel=CHANNEL[1], text="\n".join(t for _o, t, _p in rows))
        log(f"[salerev] posted {len(rows)} line(s) to {CHANNEL[0]}")
    _remember(state, day, groups, new, now, posted=True, priced={o: p for o, _t, p in rows})
    save_state(state, now.date(), state_path)
    return 0


def _remember(state, day, groups, new, now, posted, priced=None) -> None:
    d = state.setdefault(day.isoformat(), {"orders": {}})
    d["checked"] = now.isoformat(timespec="seconds")
    for oid in new:
        p = (priced or {}).get(oid)
        d["orders"][oid] = {"rep": str(groups[oid][0].get("salesperson") or ""),
                            "lines": len(groups[oid]),
                            "total": round(p["total"]) if p else None,
                            "posted": now.isoformat(timespec="seconds") if posted and p else ""}


def sample(day: dt.date, log=print) -> int:
    """That day's posts off the newest cached morning feed (it holds the
    whole day): nothing pulled, posted or remembered."""
    from automations.nds_metrics import line_revenue as LR
    feeds = [p for d, p in LR.cached_feeds() if d >= day]
    if not feeds:
        log(f"[salerev] no cached feed on or after {day}")
        return 1
    groups = order_groups(LR.parse_feed(feeds[-1].read_bytes()), day)
    rows = lines_for(groups, list(groups), day)
    log(f"[salerev] SAMPLE {day} off {feeds[-1].name}: {len(groups)} order(s), {len(rows)} priced")
    for _oid, text, _p in rows:
        log("    " + text.replace("&amp;", "&"))
    log(f"[salerev] SAMPLE total ${sum(p['total'] for _o, _t, p in rows):,.0f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_sale_revenue")
    ap.add_argument("--sample", metavar="YYYY-MM-DD")
    ap.add_argument("--date", metavar="YYYY-MM-DD")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args(argv)
    if a.sample:
        return sample(dt.date.fromisoformat(a.sample))
    day = dt.date.fromisoformat(a.date) if a.date else None
    if day is not None and a.post:
        print("[salerev] --date is for dry runs and --baseline; --post works on the clock's day")
        return 2
    return check(dt.datetime.now(), post=a.post, baseline=a.baseline, day=day)


if __name__ == "__main__":
    sys.exit(main())
