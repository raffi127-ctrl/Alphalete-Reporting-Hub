"""Pull each office's base-tier GROSS REVENUE (what SCI pays the ICD per product)
from the DD DETAIL (ORG) Tableau view, so the pay-structure gross-profit model
uses real numbers instead of placeholders.

Gross revenue per product = `Total $ to ICD` at the BASE metrics tier with
auto-bill-pay assumed (Raf 2026-07-25). The full ORG view (all owners) covers
every campaign — residential AT&T (Internet/Wireless/DTV/Just Energy) AND B2B
(B2B-ATT-SBS, B2B-BOX-Energy, RES-BASE POWER-Energy) — so one pull feeds every
office.

Runs on Lucy 1 (the machine that keeps the ownerville/Tableau session warm), like
override_bulletin's DD pull. Manual: `lucy rerun dd_gross_revenue`; scheduled 1st
& 15th at noon (low priority). `--dry-run` (default) parses without writing the
sheet; `--write` persists.

BASE-TIER NOTE: a product's `Total $ to ICD` varies by the ± metrics tier (e.g.
Internet 1000 shows $344 base / $364 with a +$20 tier). We take the MODE per
(owner, product) as the base — the most common value is the base tier — which
matches Raf's "assume base tier". Refine per Raf if a product's base needs a
specific tier pick.
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path
from typing import Dict, List, Optional

DD_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
           "DirectDepositICDVIEWVersion2_0/DDDETAILORG")
DD_SHEET = "ORG DD Detail"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# DD crosstab columns.
COL_OWNER = "cl.ICD Owner Name"
COL_CATEGORY = "cl.Category"
COL_DESCRIPTION = "cl.Description"
COL_DETAIL = "cl.Description Detail"
COL_TOTAL = "Total $ to ICD"        # gross revenue to the ICD (Raf: this IS gross revenue)
COL_CAMPAIGN = "cl.Campaign__c"     # RES-ATT / RES-BASE POWER-Energy / B2B-BOX-Energy / …
COL_DDWEEK = "cl.DD Week"           # DD week ending (the dropdown Raf wants)
# The DD view changed ~2026-08 to break each deal into transaction-type rows and
# moved the product name to cl.Product (cl.Description went empty for internet). So
# the base payout = SUM of the 'Commissions' rows per ORDER (not per-row Total$).
COL_PRODUCT = "cl.Product"
COL_ORDER = "cl.Order ID"
COL_TXN = "cl.Transaction Type"


def _is_commission(r) -> bool:
    return str(r.get(COL_TXN, "") or "").strip().lower() == "commissions"


def _product_name(r, cat: str) -> str:
    """The pay-structure product name. Wireless keys off the line type
    (cl.Description: Port Line/New Line/BYOD); everything else off cl.Product
    (Internet 1000, Choice, …), falling back to cl.Description."""
    prod = str(r.get(COL_PRODUCT, "") or "").strip()
    desc = str(r.get(COL_DESCRIPTION, "") or "").strip()
    return desc if cat == "WIRELESS" else (prod or desc)

# The product categories that carry sellable gross revenue (skip Bonus / Override
# / Chargeback / Total rows).
PRODUCT_CATEGORIES = {"INTERNET", "WIRELESS", "ELE", "AIR", "DTV",
                      "DIRECTV STREAM", "VOICE"}

# Description substrings that mark a BONUS / adjustment line (not a sellable
# product) — excluded from the product + weekly lists. (Raf: "whenever it sees
# Captain bonus, just ignore it.")
BONUS_MARKERS = ("bonus", "captains", "lead disposition", "converged", "kwh",
                 "guarantee", "disposition", "pilot", "adjustment", "chargeback")


def _settled_period(months_back: int = 1) -> str:
    """A SETTLED Period. SCI's 'Period' = a MONTH; deals post over ~2–3 weeks, so the
    previous COMPLETE month is fully settled (full payouts). Format 'Period 2026-7'."""
    import datetime as _dt
    today = _dt.date.today()
    y, m = today.year, today.month - months_back
    while m < 1:
        m += 12
        y -= 1
    return "Period {}-{}".format(y, m)


def _period_month(period) -> "Optional[int]":
    import re as _re2
    mm = _re2.search(r"-(\d{1,2})\s*$", str(period)) or _re2.search(
        r"Period\s+(\d{1,2})\s*$", str(period))
    return int(mm.group(1)) if mm else None


def _parse_date(s):
    import datetime as _dt
    if hasattr(s, "strftime"):
        return s
    for f in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return _dt.datetime.strptime(str(s).strip(), f).date()
        except ValueError:
            continue
    return None


def _dominant_dd_week(path):
    """(most-common cl.DD Week value, count) in a crosstab — used to CONFIRM a
    filter actually took (Tableau silently ignores a mis-named filter and returns
    the default latest week)."""
    try:
        rows = _read_rows(path)
    except Exception:
        return (None, 0)
    c = collections.Counter(str(r.get(COL_DDWEEK, "") or "").strip()
                            for r in rows if str(r.get(COL_DDWEEK, "") or "").strip())
    return c.most_common(1)[0] if c else (None, 0)


def _rows_ok(path: "Path", minimum: int = 200) -> bool:
    """A filter that matches nothing yields an empty/tiny crosstab — reject it."""
    try:
        return len(_read_rows(path)) >= minimum
    except Exception:
        return False


def pull(out_path: "Optional[Path]" = None, page=None, period=None):
    """Download the ORG DD Detail crosstab for a SETTLED Period (SCI 'Period' = a
    MONTH; default = previous complete month). Deals post over ~2–3 weeks, so a
    settled month carries the FULL payouts (a recent week is a partial ~$10). Uses
    the 'Period' URL filter that override_bulletin already relies on for THIS view,
    tries candidate formats, and CONFIRMS the download's dominant DD week is in the
    target month — Tableau silently ignores a mis-valued filter and returns the
    default latest week, which is the trap. One Period pull also yields EVERY DD
    week in that month for Raf's dropdown."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.override_bulletin.pulls import _with_filter, period_candidates
    out = Path(out_path) if out_path else (OUTPUT_DIR / "ORG DD Detail.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    period = period or _settled_period()
    tgt_month = _period_month(period)
    for cand in period_candidates(period):
        try:
            url = _with_filter(DD_VIEW, "Period", cand)
            download_crosstab_patchright(url, DD_SHEET, out, page=page)
        except Exception as e:            # noqa: BLE001
            print("  Period {!r} failed: {}".format(cand, str(e).splitlines()[0][:80]))
            continue
        dom, n = _dominant_dd_week(out)
        total = len(_read_rows(out))
        dp = _parse_date(dom)
        ok = _rows_ok(out) and dp and dp.month == tgt_month
        print("Period {!r} -> dominant DD week {} (month {}, {}/{} rows) {}".format(
            cand, dom, (dp.month if dp else None), n, total, "✓ TARGET" if ok else "✗ (ignored/empty)"))
        if ok:
            return out
    print("!! no Period filter validated to month {} — UNFILTERED fallback (latest, partial)".format(tgt_month))
    download_crosstab_patchright(DD_VIEW, DD_SHEET, out, page=page)
    return out


def _num(v) -> "Optional[float]":
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


MIN_SAMPLE = 5     # a base value needs >= this many auto-pay deals to be trusted


def _is_autopay(r) -> bool:
    """Raf's model assumes auto-bill-pay 100%. Keep 'Auto Bill Pay', drop
    'No Auto Bill Pay' (a lower payout) — the phrase contains 'auto bill pay' too,
    so exclude it explicitly."""
    ot = str(r.get(COL_ORDER_TYPE, "") or "").lower()
    return "auto bill pay" in ot and "no auto" not in ot


def _is_activated(r) -> bool:
    """Only ACTIVATED deals carry the settled full payout. A recent DD week is
    mostly un-activated (its Total $ to ICD is a partial/pending ~$10 that grows to
    the real base ~$198 as the deal activates over 2–3 weeks) — so aggregating only
    activated rows keeps the base-tier value stable regardless of which week the DD
    view is showing. (COL_ACTIVATION = cl.Activation Date.)"""
    a = str(r.get(COL_ACTIVATION, "") or "").strip().lower()
    return bool(a) and a not in ("nan", "null", "none", "0")


import re as _re
# B2B wireless splits In-Footprint / Out-Of-Footprint ("… - IF" / "… - OOF" /
# "… - INFP"); the sale type doesn't say which, so fold both footprints into one
# product and let the MODE pick the dominant footprint (by deal count) — no arbitrary
# IF-vs-OOF choice. Residential descriptions have no such suffix (no-op).
_FOOTPRINT_RE = _re.compile(r"\s*-\s*(IF|OOF|INFP)\s*$", _re.I)


def _norm_desc(desc: str) -> str:
    return _FOOTPRINT_RE.sub("", desc or "").strip()


def _mode(vals: "List[float]") -> float:
    return collections.Counter(round(v, 2) for v in vals).most_common(1)[0][0]


def _order_sums(rows, key_fn):
    """Group ACTIVATED 'Commissions' rows by key_fn(r,cat,owner) → {order: summed
    Total$}, plus the set of auto-pay order ids per key. The base payout is the MODE
    across orders of each order's summed commission (the DD splits a deal into
    transaction-type rows). ELE/energy is handled elsewhere."""
    order_sum: "Dict[tuple, Dict[str, float]]" = collections.defaultdict(
        lambda: collections.defaultdict(float))
    ap_orders: "Dict[tuple, set]" = collections.defaultdict(set)
    for r in rows:
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        if (cat not in PRODUCT_CATEGORIES or cat == "ELE"
                or not _is_commission(r) or not _is_activated(r)):
            continue
        owner = str(r.get(COL_OWNER, "") or "").strip()
        name = _norm_desc(_product_name(r, cat))
        order = str(r.get(COL_ORDER, "") or "").strip()
        tot = _num(r.get(COL_TOTAL))
        if (not owner or owner.lower() in ("nan", "null") or "total" in owner.lower()
                or not name or not order or tot is None):
            continue
        k = key_fn(owner, cat, name)
        if k is None:
            continue
        order_sum[k][order] += tot
        if _is_autopay(r):
            ap_orders[k].add(order)
    return order_sum, ap_orders


def gross_revenue_by_office(rows) -> "Dict[str, Dict[str, dict]]":
    """{owner: {'CATEGORY | product': {'base': mode$, 'n': autopay_orders}}}. base =
    the MODE across ORDERS of each order's summed 'Commissions' Total$ (the DD splits
    a deal into transaction-type rows). Prefer auto-pay orders; fall back to all.
    `n` = auto-pay order count, for main_products' MIN_SAMPLE stability guard."""
    order_sum, ap_orders = _order_sums(rows, lambda o, c, n: (o, c, n))
    out: Dict[str, Dict[str, dict]] = {}
    for (owner, cat, name), orders in order_sum.items():
        ap = ap_orders.get((owner, cat, name), set())
        sums = [orders[o] for o in (ap if ap else orders)]
        sums = [s for s in sums if s > 0]
        if not sums:
            continue
        out.setdefault(owner, {})["{} | {}".format(cat, name)] = {
            "base": _mode(sums), "n": len(ap)}
    return out


def org_gross_revenue(rows) -> "Dict[str, float]":
    """{'CATEGORY | Description': base} over ALL owners — the org-wide reference
    payout per product, so the editor shows an ICD payout for a product an office
    hasn't personally sold (office's own value wins when present). base = the MODE
    across ORDERS of each order's summed 'Commissions' Total$; prefer auto-pay orders,
    fall back to all (NO sample floor — org-wide backstop). ELE handled elsewhere."""
    order_sum, ap_orders = _order_sums(rows, lambda o, c, n: (c, n))   # ignore owner
    out: Dict[str, float] = {}
    for (cat, name), orders in order_sum.items():
        ap = ap_orders.get((cat, name), set())
        sums = [orders[o] for o in (ap if ap else orders)]
        sums = [s for s in sums if s > 0]
        if sums:
            out["{} | {}".format(cat, name)] = _mode(sums)
    return out


def energy_products(rows) -> "Dict[str, float]":
    """{'ELE | <description>': mode Total$} for energy. Energy is NOT auto-pay
    (order type blank), so it bypasses the auto-pay filter; and unlike AT&T it's
    keyed by DESCRIPTION, which IS the product: BOX breaks down by BF tier
    (BF 1=$325, BF 2=$275, BF 3=$210), BASE is a flat 'Energy Enrollment'=$200,
    Just Energy is Green/Not Green. Descriptions don't collide across campaigns."""
    acc: Dict[str, List[float]] = collections.defaultdict(list)
    for r in rows:
        if str(r.get(COL_CATEGORY, "") or "").strip().upper() != "ELE":
            continue
        desc = str(r.get(COL_DESCRIPTION, "") or "").strip()
        tot = _num(r.get(COL_TOTAL))
        if not desc or tot is None or tot <= 0:
            continue
        acc[desc].append(tot)
    return {"ELE | {}".format(desc): _mode(vals) for desc, vals in acc.items()}


def main_products(office_gross: "Dict[str, dict]") -> "Dict[str, float]":
    """Map an office's {CATEGORY|Description: {base, n}} to the model's MAIN
    products (Internet 1 GIG = INTERNET 1000; New Line = WIRELESS New Line, NOT
    Port Line — Raf: different gross). Pick the LARGEST-sample matching bucket and
    require MIN_SAMPLE deals, so a noisy tiny bucket never sets the base."""
    def best(pred) -> "Optional[float]":
        cands = [(v.get("n", 0), v.get("base"))
                 for k, v in office_gross.items()
                 if pred(k) and v.get("n", 0) >= MIN_SAMPLE and v.get("base")]
        return max(cands)[1] if cands else None

    out: Dict[str, float] = {}
    ig = best(lambda k: k.startswith("INTERNET | ")
              and ("1000" in k or "1 gig" in k.lower()))
    if ig is not None:
        out["Internet 1 GIG"] = ig
    # Raf's model "New Line" = "New Ported Line" (his gross_profit.py note) = the DD
    # **Port Line** (ported number, $198/35 deals for raf) — the dominant, higher-
    # value wireless add — NOT the DD 'New Line' (brand-new number, ~$103/8 deals).
    # Prefer the ported line; fall back to a genuine 'New Line' desc only if an
    # office has no qualifying Port Line sample.
    nl = best(lambda k: k.startswith("WIRELESS | ") and "port line" in k.lower())
    if nl is None:
        nl = best(lambda k: k.startswith("WIRELESS | ")
                  and "new line" in k.lower() and "port" not in k.lower())
    if nl is not None:
        out["New Line"] = nl
    return out


COL_ACTIVATION = "cl.Activation Date"    # real crosstab header uses a SPACE, not "_"
COL_ORDER_TYPE = "cl.Order Type"         # "Auto Bill Pay" vs "No Auto Bill Pay"


def _is_residential_att(campaign: str) -> bool:
    """The AT&T RESIDENTIAL program — internet, wireless, upgrades, DIRECTV, voice
    (RES-ATT, RES-DTV, …) — but NOT energy (RES-BASE POWER-Energy) or B2B."""
    c = (campaign or "").strip().lower()
    return c.startswith("res-") and "energy" not in c and "power" not in c


def weekly_by_office(rows, campaign=None) -> "Dict[str, Dict[str, Dict[str, float]]]":
    """{owner: {dd_week: {'CATEGORY | product': base$}}} — each product an owner got
    each DD WEEK (base = MODE across orders of that order's summed 'Commissions'
    Total$; bonuses excluded). Powers Raf's 'pick a DD week' dropdown. Covers the
    whole AT&T RESIDENTIAL program (internet/wireless/upgrade/DIRECTV/voice), not
    just RES-ATT. DD week = cl.DD Week (Saturday-ending)."""
    # (owner, week, cat, name) -> order -> summed commissions
    os_: "Dict[tuple, Dict[str, float]]" = collections.defaultdict(
        lambda: collections.defaultdict(float))
    for r in rows:
        camp = str(r.get(COL_CAMPAIGN, "") or "").strip()
        if not (_is_residential_att(camp) if campaign is None else camp == campaign):
            continue
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        # NOT activation-gated (unlike the aggregated payout): Raf wants to see EVERY
        # product he got that week — a recent week's un-activated rows just show a
        # partial value that fills in as it settles.
        if cat not in PRODUCT_CATEGORIES or cat == "ELE" or not _is_commission(r):
            continue
        name = _norm_desc(_product_name(r, cat))
        owner = str(r.get(COL_OWNER, "") or "").strip()
        week = str(r.get(COL_DDWEEK, "") or "").strip()
        order = str(r.get(COL_ORDER, "") or "").strip()
        tot = _num(r.get(COL_TOTAL))
        if (not owner or owner.lower() in ("nan", "null") or "total" in owner.lower()
                or not week or not name or not order or tot is None):
            continue
        os_[(owner, week, cat, name)][order] += tot
    out: "Dict[str, Dict[str, Dict[str, float]]]" = collections.defaultdict(dict)
    for (owner, week, cat, name), orders in os_.items():
        sums = [s for s in orders.values() if s > 0]
        if sums:
            out[owner].setdefault(week, {})["{} | {}".format(cat, name)] = _mode(sums)
    return {o: dict(w) for o, w in out.items()}


def _cap_weeks(weeks: "Dict[str, dict]", keep: int = 12) -> "Dict[str, dict]":
    """Keep only the most recent `keep` DD weeks (keys like '7/25/2026')."""
    import datetime as _dt

    def _key(w):
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return _dt.datetime.strptime(w, fmt)
            except ValueError:
                continue
        return _dt.datetime.min
    return {w: weeks[w] for w in sorted(weeks, key=_key, reverse=True)[:keep]}


def activation_by_office(rows) -> "Dict[str, float]":
    """{owner: activation_rate 0-1} — fraction of product lines that have an
    Activation Date. A first-pass proxy from the same DD pull; can be swapped for
    the metrics-tab rolling-week rate later (Raf's preferred source)."""
    tot: Dict[str, int] = collections.defaultdict(int)
    act: Dict[str, int] = collections.defaultdict(int)
    for r in rows:
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        if cat not in PRODUCT_CATEGORIES:
            continue
        owner = str(r.get(COL_OWNER, "") or "").strip()
        if not owner or owner.lower() in ("nan", "null") or "total" in owner.lower():
            continue
        tot[owner] += 1
        a = str(r.get(COL_ACTIVATION, "") or "").strip().lower()
        if a and a not in ("nan", "null", "none"):
            act[owner] += 1
    return {o: round(act[o] / tot[o], 3) for o in tot if tot[o]}


def _read_rows(path: Path):
    """Tableau crosstab = UTF-16 tab-delimited (sometimes UTF-8/comma). Reuse
    override_bulletin's proven encoding/delimiter-robust reader (returns row
    lists), then zip the header row into per-row dicts (what the parsers expect)."""
    from automations.override_bulletin.pulls import read_crosstab
    table = read_crosstab(path)
    if not table:
        return []
    header = [str(h).strip() for h in table[0]]
    rows = []
    for r in table[1:]:
        if not any(str(c).strip() for c in r):
            continue
        rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
    return rows


def run(write: bool = False, src: "Optional[Path]" = None,
        period=None) -> dict:
    """Pull (or read `src`), parse, and (if write) persist per-office gross
    revenue. Returns the parsed {office_key: {product: gross}} for the mapped
    offices."""
    from automations.pay_structure import offices as _po
    import datetime as _dt
    pulled = _dt.date.today().strftime("%b %d, %Y").replace(" 0", " ")  # no %-d (Windows)
    path = src or pull(period=period)
    rows = _read_rows(path)
    by_owner = gross_revenue_by_office(rows)
    activation = activation_by_office(rows)
    weekly = weekly_by_office(rows)                     # {owner: {week: {desc: $}}}
    # key by office (owner -> office_key)
    by_office: Dict[str, dict] = {}
    weekly_office: Dict[str, dict] = {}
    for owner, gross in by_owner.items():
        office = _po.for_owner(owner)
        if office:
            raw = {k: v["base"] for k, v in gross.items()}   # flat for the sheet
            by_office[office.key] = {"raw": raw, "main": main_products(gross),
                                     "activation": activation.get(owner),
                                     "pulled": pulled}
            if owner in weekly:
                weekly_office[office.key] = weekly[owner]
    # org-wide reference payouts (every product anyone sells), for the editor's
    # per-sale-type ICD payout when an office has no own value for a product.
    # Energy (box/base) is merged in — it's keyed by campaign, not description.
    org_raw = org_gross_revenue(rows)
    org_raw.update(energy_products(rows))
    by_office["_org"] = {"raw": org_raw, "pulled": pulled}
    if write:
        import os
        os.environ.setdefault("PAY_STRUCTURE_SHEET_ID",
                              "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        from automations.pay_structure import store as _st
        # MAX-MERGE the aggregated payouts: a product's base payout is stable, and a
        # partial recent-week pull only UNDERSTATES it (~$10 vs the settled ~$198 that
        # posts over 2–3 weeks). So never let a pull LOWER a known value — this
        # converges to the settled value and stops the daily pull from corrupting it.
        try:
            prev = _st.load_gross_revenue_all()
            for ok, data in by_office.items():
                old = (prev.get(ok) or {}).get("raw", {})
                new = data.get("raw", {})
                data["raw"] = {k: max(float(new.get(k, 0) or 0), float(old.get(k, 0) or 0))
                               for k in set(new) | set(old)}
        except Exception as e:            # noqa: BLE001 — never fail the pull
            print("gross max-merge skipped: {}".format(str(e)[:120]))
        _st.save_gross_revenue(by_office)
        # accumulate per-week sale types (a pull only holds ~1 DD week), keeping the
        # most recent 12 weeks; MAX per (week, product) so a week's values converge
        # up to settled as later pulls re-see the same week fuller.
        try:
            existing = _st.load_weekly_all()
            merged: Dict[str, dict] = {}
            for ok in set(existing) | set(weekly_office):
                wk = dict(existing.get(ok, {}))
                for week, descs in (weekly_office.get(ok) or {}).items():
                    cur = dict(wk.get(week, {}))
                    for d, v in descs.items():
                        cur[d] = max(float(v or 0), float(cur.get(d, 0) or 0))
                    wk[week] = cur
                merged[ok] = _cap_weeks(wk, 12)
            _st.save_weekly(merged)
        except Exception as e:            # noqa: BLE001 — weekly is additive, never fail the pull
            print("weekly accumulate skipped: {}".format(str(e)[:120]))
    return by_office


def inspect(owner: str, src: "Optional[Path]" = None) -> None:
    """Diagnostic: dump the REAL structure of the last-saved crosstab for one
    owner so we can model base-tier correctly (no re-download). Lines are prefixed
    'INSP|' so `lucy logtail <log> INSP` retrieves them from the mini."""
    path = src or (OUTPUT_DIR / "ORG DD Detail.csv")
    rows = _read_rows(Path(path))
    if not rows:
        print("INSP|EMPTY {}".format(path)); return
    # Org-wide ENERGY probe: `--inspect __ELE__`. Energy is NOT auto-pay (order type
    # blank) so the normal filter drops it; here we dump every ELE row grouped by
    # (owner, campaign) with the Total$ distribution, to see if the payout varies
    # (BF tier×term) or is a flat per-enrollment value.
    # Full product catalog probe: `--inspect __PRODUCTS__`. Every distinct
    # (category, description) that is a real PRODUCT (bonuses/guarantees excluded),
    # with its auto-pay payout — the master list Megan wants the editor to list so
    # every product has an accurate ICD payout. Energy keyed by campaign.
    # Week probe: `--inspect __WEEKS__` — distinct DD weeks × campaigns, and for
    # Rafael Hidalgo's RES-ATT the descriptions per week (does it carry all the
    # product types Raf expects: New Internet, Upgrade, Voice, Video?).
    if owner.strip().upper() in ("__WEEKS__",):
        wc = collections.Counter((str(r.get(COL_DDWEEK, "")).strip(),
                                  str(r.get(COL_CAMPAIGN, "")).strip()) for r in rows)
        for (wk, camp), n in wc.most_common(20):
            print("INSP|W|{}|{}|n={}".format(wk or "-", camp or "-", n))
        rr = [r for r in rows if str(r.get(COL_OWNER, "")).strip() == "Rafael Hidalgo"
              and str(r.get(COL_CAMPAIGN, "")).strip() == "RES-ATT"]
        byweek = collections.defaultdict(set)
        for r in rr:
            byweek[str(r.get(COL_DDWEEK, "")).strip()].add(
                "{}|{}".format(str(r.get(COL_CATEGORY, "")).strip(),
                               str(r.get(COL_DESCRIPTION, "")).strip()))
        for wk in sorted(byweek):
            print("INSP|RAFWK|{}|{}descs={}".format(wk, len(byweek[wk]),
                  sorted(byweek[wk])[:14]))
        return
    # Raf DD probe: `--inspect __RAFDD__` (Carlos 2026-08-30). Per-DD-week
    # deposit math for Rafael Hidalgo out of the last-saved ORG crosstab —
    # week total $ to ICD (the deposit), Commissions vs bonus/override/
    # chargeback transaction lines, and per-product order counts with the
    # per-order payout — so Carlos can lay Raf's real revenue next to the
    # office Commissions sheet. Rich output goes to the control workbook's
    # 'Inspect Out' tab (the mini Result cell truncates); INSP| lines mirror
    # the headline numbers for logtail.
    if owner.strip().upper() in ("__RAFDD__",):
        mine = [r for r in rows
                if str(r.get(COL_OWNER, "")).strip() == "Rafael Hidalgo"]
        out_rows = [["RAF DD", "week", "key", "orders/rows", "$ per order", "total $"]]
        byweek: Dict[str, list] = collections.defaultdict(list)
        for r in mine:
            byweek[str(r.get(COL_DDWEEK, "")).strip() or "-"].append(r)
        for wk in sorted(byweek):
            wrows = byweek[wk]
            tot = sum(_num(r.get(COL_TOTAL)) or 0 for r in wrows)
            comm = [r for r in wrows if _is_commission(r)]
            comm_tot = sum(_num(r.get(COL_TOTAL)) or 0 for r in comm)
            out_rows.append(["WEEK", wk, "DEPOSIT (all rows)", len(wrows), "",
                             round(tot, 2)])
            out_rows.append(["", wk, "product commissions", len(comm), "",
                             round(comm_tot, 2)])
            other: Dict[str, float] = collections.defaultdict(float)
            for r in wrows:
                if not _is_commission(r):
                    txn = str(r.get(COL_TXN, "") or "").strip() or "(no txn type)"
                    other[txn] += _num(r.get(COL_TOTAL)) or 0
            for txn, v in sorted(other.items(), key=lambda x: -abs(x[1])):
                out_rows.append(["", wk, txn, "", "", round(v, 2)])
            # ITEMIZE the non-commission rows (Carlos: "all the add-ons and
            # random bonuses") — every (txn type, description-or-product) with
            # row count + total, so no bonus stays a lump.
            bonus_items: Dict[tuple, List[float]] = collections.defaultdict(list)
            for r in wrows:
                if _is_commission(r):
                    continue
                txn = str(r.get(COL_TXN, "") or "").strip() or "(no txn type)"
                what = (str(r.get(COL_DESCRIPTION, "") or "").strip()
                        or str(r.get(COL_PRODUCT, "") or "").strip()
                        or str(r.get(COL_DETAIL, "") or "").strip() or "(blank)")
                bonus_items[(txn, what)].append(_num(r.get(COL_TOTAL)) or 0)
            for (txn, what), vals in sorted(bonus_items.items(),
                                            key=lambda x: -abs(sum(x[1]))):
                out_rows.append(["", wk, "{} :: {}".format(txn, what),
                                 len(vals), round(sum(vals) / len(vals), 2),
                                 round(sum(vals), 2)])
            # ITEMIZE commission LINE ITEMS by description (the add-on rows —
            # Unlimited Extra / Premium / Next Up / BYOD — that the per-ORDER
            # grouping below folds into bundle averages).
            line_items: Dict[str, List[float]] = collections.defaultdict(list)
            for r in comm:
                cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
                what = (str(r.get(COL_DESCRIPTION, "") or "").strip()
                        or str(r.get(COL_PRODUCT, "") or "").strip() or "(blank)")
                line_items["{} :: {}".format(cat, what)].append(
                    _num(r.get(COL_TOTAL)) or 0)
            for what, vals in sorted(line_items.items(),
                                     key=lambda x: -abs(sum(x[1]))):
                out_rows.append(["", wk, "LINE {}".format(what), len(vals),
                                 round(sum(vals) / len(vals), 2),
                                 round(sum(vals), 2)])
            # per-product: distinct orders + per-order payout (sum of the
            # order's Commissions rows — the post-2026-08 row-split format)
            per: Dict[str, Dict[str, float]] = collections.defaultdict(
                lambda: collections.defaultdict(float))
            for r in comm:
                cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
                key = "{} | {}".format(cat, _product_name(r, cat) or "(blank)")
                oid = str(r.get(COL_ORDER, "") or "").strip()
                per[key][oid] += _num(r.get(COL_TOTAL)) or 0
            for key, orders in sorted(per.items(),
                                      key=lambda x: -sum(x[1].values())):
                s = sum(orders.values())
                n = len(orders)
                out_rows.append(["", wk, key, n,
                                 round(s / n, 2) if n else "", round(s, 2)])
        for r in out_rows:
            if r[0] in ("RAF DD", "WEEK"):
                print("INSP|RAFDD|" + "|".join(str(c) for c in r))
        try:
            import gspread
            from automations.recruiting_report import fill as _fill
            from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
            sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
            try:
                ws = sh.worksheet("Inspect Out")
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title="Inspect Out", rows=300, cols=8)
            ws.clear()
            ws.update(out_rows, "A1")
            print("INSP|RAFDD|wrote {} rows to 'Inspect Out'".format(len(out_rows)))
        except Exception as e:            # noqa: BLE001 — probe must not crash on the write
            print("INSP|RAFDD|Inspect Out write failed: {}".format(str(e)[:200]))
        return
    if owner.strip().upper() in ("__PRODUCTS__", "__PROD__"):
        BONUS = ("bonus", "captains", "lead disposition", "converged", "kwh",
                 "guarantee", "disposition", "pilot", "adjustment", "chargeback")
        prod: Dict[tuple, List[float]] = collections.defaultdict(list)
        for r in rows:
            cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
            if cat not in PRODUCT_CATEGORIES:
                continue
            desc = str(r.get(COL_DESCRIPTION, "") or "").strip()
            if not desc or any(b in desc.lower() for b in BONUS):
                continue
            tot = _num(r.get(COL_TOTAL))
            if tot is None or tot <= 0:
                continue
            # energy: key by campaign (desc is flat/varies); AT&T: auto-pay only
            if cat == "ELE":
                camp = str(r.get(COL_CAMPAIGN, "") or "").strip()
                prod[(cat, "{} [{}]".format(desc, camp))].append(tot)
            elif _is_autopay(r):
                prod[(cat, desc)].append(tot)
        for (cat, desc), vals in sorted(prod.items()):
            if len(vals) < MIN_SAMPLE:
                continue
            mode = collections.Counter(round(v, 0) for v in vals).most_common(1)[0][0]
            print("INSP|P|{}|{}|n={}|${:.0f}".format(cat, desc, len(vals), mode))
        return
    if owner.strip().upper() in ("__ELE__", "__ENERGY__"):
        ele = [r for r in rows if str(r.get(COL_CATEGORY, "")).strip().upper() == "ELE"]
        print("INSP|ELE total rows={}".format(len(ele)))
        bycamp: Dict[str, List[float]] = collections.defaultdict(list)
        for r in ele:
            bycamp[str(r.get(COL_CAMPAIGN, "")).strip() or "(blank)"].append(_num(r.get(COL_TOTAL)) or 0)
        for camp, vals in sorted(bycamp.items(), key=lambda x: -len(x[1]))[:6]:
            modes = collections.Counter(round(v, 0) for v in vals).most_common(6)
            print("INSP|ELE camp={!r} n={} Total$modes={}".format(camp, len(vals), modes))
        # which owners/offices sell energy (for owner->office mapping)
        from automations.pay_structure import offices as _po
        byown = collections.Counter(str(r.get(COL_OWNER, "")).strip() for r in ele)
        for own, n in byown.most_common(8):
            off = _po.for_owner(own)
            print("INSP|ELE owner={!r} n={} office={}".format(own, n, off.key if off else None))
        return
    cols = list(rows[0].keys())
    print("INSP|rows={} cols={} hasDesc={} hasAct={} hasOrderType={}".format(
        len(rows), len(cols), COL_DESCRIPTION in cols, COL_ACTIVATION in cols,
        COL_ORDER_TYPE in cols))
    mine = [r for r in rows if str(r.get(COL_OWNER, "")).strip() == owner]
    print("INSP|{} rows={}".format(owner, len(mine)))
    cats = collections.Counter(str(r.get(COL_CATEGORY, "")).strip().upper() for r in mine)
    print("INSP|cats={}".format(dict(cats.most_common(6))))
    for want in ("INTERNET", "WIRELESS"):
        sub = [r for r in mine if str(r.get(COL_CATEGORY, "")).strip().upper() == want]
        descs = collections.Counter(str(r.get(COL_DESCRIPTION, "")).strip() for r in sub)
        print("INSP|{} descs={}".format(want, dict(descs.most_common(6))))
        ap_ = [r for r in sub if _is_autopay(r)]
        tot = collections.Counter(round(_num(r.get(COL_TOTAL)) or 0, 0) for r in ap_)
        print("INSP|{} autopayTotal$={}".format(want, dict(tot.most_common(6))))
    # per-WIRELESS-description auto-pay base + count (New Line vs Port Line vs BYOD),
    # to settle whether Raf's "New Line" ($173) = the DD 'Port Line' (New Ported Line).
    for want in ("WIRELESS", "INTERNET"):
        wl = [r for r in mine
              if str(r.get(COL_CATEGORY, "")).strip().upper() == want and _is_autopay(r)]
        bydesc: Dict[str, List[float]] = collections.defaultdict(list)
        for r in wl:
            bydesc[str(r.get(COL_DESCRIPTION, "")).strip()].append(_num(r.get(COL_TOTAL)) or 0)
        for dsc, vals in sorted(bydesc.items(), key=lambda x: -len(x[1]))[:5]:
            mode = collections.Counter(round(v, 0) for v in vals).most_common(1)[0]
            print("INSP|{} desc={!r} n={} mode={}".format(want, dsc, len(vals), mode))
    # energy (ELE) — why box/base map empty: order-type split (auto-pay?) + descs.
    for want in ("ELE", "DTV", "DIRECTV STREAM"):
        sub = [r for r in mine if str(r.get(COL_CATEGORY, "")).strip().upper() == want]
        if not sub:
            continue
        ots = collections.Counter(str(r.get(COL_ORDER_TYPE, "")).strip() or "(blank)" for r in sub)
        dsc = collections.Counter(str(r.get(COL_DESCRIPTION, "")).strip() or "(blank)" for r in sub)
        print("INSP|{} n={} ordertypes={}".format(want, len(sub), dict(ots.most_common(4))))
        print("INSP|{} descs={}".format(want, dict(dsc.most_common(6))))
    go = gross_revenue_by_office(rows).get(owner, {})
    print("INSP|MAPPED={}".format(main_products(go)))
    print("INSP|activation={}".format(activation_by_office(rows).get(owner)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pull ICD gross revenue from DD DETAIL (ORG)")
    ap.add_argument("--write", action="store_true", help="persist to the sheet (default dry-run)")
    ap.add_argument("--src", help="parse an existing crosstab file instead of pulling")
    ap.add_argument("--inspect", metavar="OWNER", help="dump the last-saved crosstab's "
                    "real structure for one owner (no download/write); for modeling")
    ap.add_argument("--period", metavar="'Period 2026-7'", help="pull a specific SCI "
                    "Period (month) instead of the default (previous complete month)")
    a = ap.parse_args()
    if a.inspect:
        inspect(a.inspect, src=Path(a.src) if a.src else None)
    else:
        res = run(write=a.write, src=Path(a.src) if a.src else None,
                  period=a.period)
        print("parsed gross revenue for {} office(s):".format(len(res)))
        for k, v in res.items():
            if "main" in v:                 # skip the _org reference row (no 'main')
                print("  {:8} main: {}".format(k, v["main"]))
