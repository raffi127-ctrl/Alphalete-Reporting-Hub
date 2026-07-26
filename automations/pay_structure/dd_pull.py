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

# The product categories that carry sellable gross revenue (skip Bonus / Override
# / Chargeback / Total rows).
PRODUCT_CATEGORIES = {"INTERNET", "WIRELESS", "ELE", "AIR", "DTV"}


def pull(out_path: "Optional[Path]" = None, page=None):
    """Download the ORG DD Detail crosstab. Returns the path."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    out = Path(out_path) if out_path else (OUTPUT_DIR / "ORG DD Detail.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    download_crosstab_patchright(DD_VIEW, DD_SHEET, out, page=page)
    return out


def _num(v) -> "Optional[float]":
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def gross_revenue_by_office(rows) -> "Dict[str, Dict[str, float]]":
    """{owner_name: {'CATEGORY | Description': base_gross_revenue}} — the MODE of
    Total $ to ICD per (owner, category, description) for product-category rows.
    `rows` = list of dicts (crosstab records)."""
    acc: Dict[tuple, List[float]] = collections.defaultdict(list)
    for r in rows:
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        if cat not in PRODUCT_CATEGORIES:
            continue
        owner = str(r.get(COL_OWNER, "") or "").strip()
        desc = str(r.get(COL_DESCRIPTION, "") or "").strip()
        tot = _num(r.get(COL_TOTAL))
        if (not owner or owner.lower() in ("nan", "null")
                or "total" in owner.lower() or not desc or tot is None or tot == 0):
            continue
        acc[(owner, cat, desc)].append(tot)
    out: Dict[str, Dict[str, float]] = {}
    for (owner, cat, desc), vals in acc.items():
        base = collections.Counter(round(v, 2) for v in vals).most_common(1)[0][0]
        out.setdefault(owner, {})["{} | {}".format(cat, desc)] = base
    return out


def main_products(office_gross: "Dict[str, float]") -> "Dict[str, float]":
    """Map an office's raw {CATEGORY|Description: base} to the model's MAIN
    products (Internet 1 GIG, New Line). Best-effort by label; missing = absent."""
    out: Dict[str, float] = {}
    for key, base in office_gross.items():
        cat, _, desc = key.partition(" | ")
        d = desc.lower()
        if cat == "INTERNET" and "1000" in d:
            out["Internet 1 GIG"] = base
        elif cat == "WIRELESS" and ("new line" in d or "port" in d):
            out.setdefault("New Line", base)
    return out


COL_ACTIVATION = "cl.Activation_Date"


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
    import pandas as pd
    df = pd.ExcelFile(path).parse(0)
    return df.to_dict("records")


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
            by_office[office.key] = {"raw": gross, "main": main_products(gross),
                                     "activation": activation.get(owner),
                                     "pulled": pulled}
    if write:
        import os
        os.environ.setdefault("PAY_STRUCTURE_SHEET_ID",
                              "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        from automations.pay_structure import store as _st
        _st.save_gross_revenue(by_office)
    return by_office


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pull ICD gross revenue from DD DETAIL (ORG)")
    ap.add_argument("--write", action="store_true", help="persist to the sheet (default dry-run)")
    ap.add_argument("--src", help="parse an existing crosstab file instead of pulling")
    a = ap.parse_args()
    res = run(write=a.write, src=Path(a.src) if a.src else None)
    print("parsed gross revenue for {} office(s):".format(len(res)))
    for k, v in res.items():
        print("  {:8} main: {}".format(k, v["main"]))
