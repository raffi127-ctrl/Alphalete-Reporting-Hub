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

# The product categories that carry sellable gross revenue (skip Bonus / Override
# / Chargeback / Total rows).
PRODUCT_CATEGORIES = {"INTERNET", "WIRELESS", "ELE", "AIR", "DTV",
                      "DIRECTV STREAM", "VOICE"}


def pull(out_path: "Optional[Path]" = None, page=None):
    """Download the ORG DD Detail crosstab. Returns the path. Tableau crosstab
    exports are UTF-16 TAB-delimited CSV (not xlsx), so the file is .csv."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    out = Path(out_path) if out_path else (OUTPUT_DIR / "ORG DD Detail.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
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


def gross_revenue_by_office(rows) -> "Dict[str, Dict[str, dict]]":
    """{owner: {'CATEGORY | Description': {'base': mode$, 'n': autopay_deals}}}.
    base = the MODE of Total $ to ICD per (owner, category, description). PREFER
    auto-bill-pay deals (Raf: assume auto-pay 100%), but for a product the office
    sold ONLY no-auto-pay, fall back to those deals so every product it sold still
    gets a payout. `n` = the auto-pay count only, so main_products' MIN_SAMPLE
    guard still keeps the simulator's base tier stable (a 1-deal outlier can't set
    Internet 1 GIG / New Line)."""
    ap: Dict[tuple, List[float]] = collections.defaultdict(list)
    al: Dict[tuple, List[float]] = collections.defaultdict(list)
    for r in rows:
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        if cat not in PRODUCT_CATEGORIES:
            continue
        owner = str(r.get(COL_OWNER, "") or "").strip()
        desc = _norm_desc(str(r.get(COL_DESCRIPTION, "") or "").strip())
        tot = _num(r.get(COL_TOTAL))
        if (not owner or owner.lower() in ("nan", "null")
                or "total" in owner.lower() or not desc or tot is None or tot <= 0):
            continue
        al[(owner, cat, desc)].append(tot)
        if _is_autopay(r):
            ap[(owner, cat, desc)].append(tot)
    out: Dict[str, Dict[str, dict]] = {}
    for key, allv in al.items():
        owner, cat, desc = key
        apv = ap.get(key) or []
        out.setdefault(owner, {})["{} | {}".format(cat, desc)] = {
            "base": _mode(apv or allv), "n": len(apv)}
    return out


def org_gross_revenue(rows) -> "Dict[str, float]":
    """{'CATEGORY | Description': base} over ALL owners — the org-wide reference
    payout per product, so the editor shows an ICD payout for a product an office
    hasn't personally sold (office's own value wins when present). PREFER auto-pay
    deals; fall back to any deal so every product that appears in the DD at all
    gets a reference (NO sample floor here — this is the org-wide backstop)."""
    ap: Dict[tuple, List[float]] = collections.defaultdict(list)
    al: Dict[tuple, List[float]] = collections.defaultdict(list)
    for r in rows:
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        if cat not in PRODUCT_CATEGORIES:
            continue
        desc = _norm_desc(str(r.get(COL_DESCRIPTION, "") or "").strip())
        tot = _num(r.get(COL_TOTAL))
        if not desc or tot is None or tot <= 0:
            continue
        al[(cat, desc)].append(tot)
        if _is_autopay(r):
            ap[(cat, desc)].append(tot)
    out: Dict[str, float] = {}
    for key, allv in al.items():
        out["{} | {}".format(*key)] = _mode(ap.get(key) or allv)
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


def run(write: bool = False, src: "Optional[Path]" = None) -> dict:
    """Pull (or read `src`), parse, and (if write) persist per-office gross
    revenue. Returns the parsed {office_key: {product: gross}} for the mapped
    offices."""
    from automations.pay_structure import offices as _po
    import datetime as _dt
    pulled = _dt.date.today().strftime("%b %d, %Y").replace(" 0", " ")  # no %-d (Windows)
    path = src or pull()
    rows = _read_rows(path)
    by_owner = gross_revenue_by_office(rows)
    activation = activation_by_office(rows)
    # key by office (owner -> office_key)
    by_office: Dict[str, dict] = {}
    for owner, gross in by_owner.items():
        office = _po.for_owner(owner)
        if office:
            raw = {k: v["base"] for k, v in gross.items()}   # flat for the sheet
            by_office[office.key] = {"raw": raw, "main": main_products(gross),
                                     "activation": activation.get(owner),
                                     "pulled": pulled}
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
        _st.save_gross_revenue(by_office)
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
    a = ap.parse_args()
    if a.inspect:
        inspect(a.inspect, src=Path(a.src) if a.src else None)
    else:
        res = run(write=a.write, src=Path(a.src) if a.src else None)
        print("parsed gross revenue for {} office(s):".format(len(res)))
        for k, v in res.items():
            if "main" in v:                 # skip the _org reference row (no 'main')
                print("  {:8} main: {}".format(k, v["main"]))
