"""Pull + aggregate the Country Metrics data from Tableau.

Two source views (reuse the OPT phase's unattended patchright crosstab driver):
  • Metrics  (base view) — sheet "Metrics Call Last week data (Internet)".
    Rows are grouped by `Captain's Bonus Teams`; each team has a `… | Total`
    subtotal row and there's a `Grand Total` row (= COUNTRY). Gives the 7 rate
    rows AND the owner→team roster. Rolling-4-week metrics: no date needed.
  • PRODUCT SALES SUMMARY 4WK / ALLREPS — week-filtered via the
    'Sale Date Week Ending (mon-sun)' URL param.
      - sheet "Product Sales Summary by ORG"   → COUNTRY product counts.
      - sheet "Sales By ICD (Weekly View)"     → per-owner product counts +
        per-owner weekly total (for Total Owners + Owners Over 100, aggregated
        per captainship via the roster).

Returns {section: {metric_key: value}} where section ∈ COUNTRY/RAF/STARR/ARON/
PAT/WAYNE/SAM/CHAN/TONY/SAHIL. Sales (ALL), AVG Units, % of Owners over 100, and COUNTRY's
owner counts are Sheet formulas — never produced here.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from automations.recruiting_report import opt_phase
from automations.focus_office_att import aliases as _aliases

WORKSPACE = Path(__file__).resolve().parent.parent.parent
OUT = WORKSPACE / "output"

METRICS_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/Metrics")
METRICS_SHEET = "Metrics Call Last week data (Internet)"
# We fill one week behind, so the Metrics view's "Week's Metrics" filter must be
# "Last Week", not its default "This Week" (Eve, 2026-05-28 — the default made
# ABP Mix / 1Gig+ pull the in-progress week). Set via URL param.
METRICS_WEEK_FILTER = "?" + quote("Week's Metrics") + "=" + quote("Last Week")
PRODUCT_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
               "3a00519d-9219-4991-919b-7e084d56fc21/ALLREPS")
ORG_SHEET = "Product Sales Summary by ORG"
ICD_SHEET = "Sales By ICD (Weekly View)"

# Order Log ALLREPS view — source of each owner's AIR orders for the
# "Owners Over 100" count (Eve, 2026-05-28: that count must include AIR;
# Eve, 2026-06-04: keep counting Order Log GROSS orders for the threshold even
# though PRODUCT SALES now carries net AIR — don't change who passes).
# These are gross orders (all DTR statuses), not net sales — fine for the
# threshold. VOICE is intentionally NOT counted.
ORDERLOG_URL_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/ORDERLOG/117748c0-9487-45e8-a5d4-c447093718d5/ALLREPS"
    "?:iid=1&Start%20Date={start}&End%20Date={end}")
ORDERLOG_SHEET = "A.Order Log"

# Tableau "Captain's Bonus Teams" value -> Sheet section name.
TEAM_TO_SECTION = {
    "Grand Total": "COUNTRY",
    "Aron's Team": "ARON",
    "Chan's Team": "CHAN",
    "Pat's Team": "PAT",
    "Raf's Team": "RAF",
    "Sahil's Team": "SAHIL",
    "Sam's Team": "SAM",
    "Starr's Team": "STARR",
    "Tony's Team": "TONY",
    "Wayne's Team": "WAYNE",
}

# Rate rows: Sheet metric_key -> Metrics crosstab column header. All percents.
METRICS_RATE_COLS = {
    "rolling4": "Rolling 4 Weeks",
    "act3060": "30-60 day New Internet activation rate",
    "churn030": "0-30 day new internet churn rate",
    "abp": "New Internet ABP Mix % (Metrics)",
    "gig1": "New Internet 1Gig+ Mix% (Metrics)",
    "sched6": "% of sales scheduled 6+ days out (4 wks)",
}
METRICS_COUNT_COLS = {"jep": "Jep New Internet Count (4 wk)"}

# Product Type (Broken Out) value -> Sheet metric_key.
PRODUCT_KEYS = {
    "AIR": "air",
    "NEW INTERNET": "newint",
    "UPGRADE INTERNET": "upgrade",
    "VIDEO": "video",
    "WIRELESS": "wireless",
}

# The PRODUCT SALES view's published quick-filter omits AIR, but the datasource
# carries it (Tableau fix, confirmed 2026-06-04) — force the filter to all 5
# products on every download. Commas must stay literal (value separators).
PRODUCT_FILTER_PARAM = (quote("Product Type (Broken Out)") + "="
                        + quote(",".join(PRODUCT_KEYS), safe=","))

PERCENT_KEYS = {"rolling4", "act3060", "churn030", "abp", "gig1", "sched6"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def _canon(name: str, alias_raw: dict) -> str:
    """Owner name -> normalized canonical, resolving spelling mismatches via the
    shared 'ICD Aliases' sheet (e.g. 'Patrick Thompson' -> 'Pat Thompson'). Both
    the Metrics roster and the Sales-By-ICD owners run through this, so the same
    person matches across the two views regardless of how each spells the name."""
    return _norm(_aliases.alias_to_canonical(name, alias_raw))


def _read_crosstab(path: Path) -> list[list[str]]:
    """Crosstab CSVs are UTF-16, tab-delimited."""
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.reader(f, delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            continue
    return []


def _num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return int(s) if re.fullmatch(r"-?\d+", s) else float(s)
    except ValueError:
        return None


# ----------------------------------------------------------------- download
def _download(week: dt.date, page, logfn) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = _paths()
    week_url = opt_phase._week_url(PRODUCT_URL, week)
    week_url += ("&" if "?" in week_url else "?") + PRODUCT_FILTER_PARAM
    logfn(f"  Metrics crosstab (Last Week filter)…")
    opt_phase.download_crosstab(METRICS_URL + METRICS_WEEK_FILTER, METRICS_SHEET,
                                paths["metrics"], verbose=False, page=page)
    logfn(f"  PRODUCT SALES ORG @ {week}…")
    opt_phase.download_crosstab(week_url, ORG_SHEET, paths["org"], verbose=False, page=page)
    logfn(f"  PRODUCT SALES by-ICD @ {week}…")
    opt_phase.download_crosstab(week_url, ICD_SHEET, paths["icd"], verbose=False, page=page)
    start = week - dt.timedelta(days=6)
    ol_url = ORDERLOG_URL_TMPL.format(start=start.isoformat(), end=week.isoformat())
    logfn(f"  Order Log {start}..{week} (for AIR per owner)…")
    opt_phase.download_crosstab(ol_url, ORDERLOG_SHEET, paths["orderlog"], verbose=False, page=page)
    return paths


def _paths() -> dict:
    return {
        "metrics": OUT / "country_metrics_metrics.csv",
        "org": OUT / "country_metrics_org.csv",
        "icd": OUT / "country_metrics_icd.csv",
        "orderlog": OUT / "country_metrics_orderlog.csv",
    }


# -------------------------------------------------------------------- parse
def _col_index(header: list[str], wanted: str) -> Optional[int]:
    w = wanted.strip().lower()
    for i, h in enumerate(header):
        if (h or "").strip().lower() == w:
            return i
    return None


def _parse_metrics(rows: list[list[str]], alias_raw: dict):
    """Returns (rates: {section: {key: '<value>%' or count}}, roster: {CANON: section})."""
    header = rows[0]
    idx = {k: _col_index(header, col) for k, col in
           {**METRICS_RATE_COLS, **METRICS_COUNT_COLS}.items()}
    missing = [METRICS_RATE_COLS.get(k) or METRICS_COUNT_COLS.get(k)
               for k, v in idx.items() if v is None]
    rates: dict[str, dict] = {}
    roster: dict[str, str] = {}
    for r in rows[1:]:
        if len(r) < 2:
            continue
        team, owner = r[0].strip(), r[1].strip()
        section = TEAM_TO_SECTION.get(team)
        if team == "Grand Total":
            section = "COUNTRY"
        if owner == "Total":           # team subtotal (or grand total) row
            if not section:
                continue
            d = {}
            for k, j in idx.items():
                if j is None or j >= len(r):
                    continue
                raw = (r[j] or "").strip()
                if not raw:
                    continue
                if k in PERCENT_KEYS:
                    d[k] = raw                     # keep '81.2%' (USER_ENTERED → %)
                else:
                    d[k] = _num(raw)
            rates[section] = d
        elif section and owner:        # per-rep row → roster
            roster[_canon(owner, alias_raw)] = section
    return rates, roster, missing


def _parse_org(rows: list[list[str]]) -> dict:
    """COUNTRY product counts from the 'by ORG' sheet (col 1 = the week)."""
    out = {}
    for r in rows[1:]:
        if len(r) < 2:
            continue
        key = PRODUCT_KEYS.get((r[0] or "").strip().upper())
        if key:
            out[key] = _num(r[1])
    return out


def _parse_orderlog_air(rows: list[list[str]], alias_raw: dict) -> dict:
    """{canon_owner: AIR order count} from the Order Log crosstab."""
    if not rows:
        return {}
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    try:
        oi = header.index("Owner Name")
        pi = header.index("Product Type (Broken Out)")
    except ValueError:
        return {}
    air: dict[str, int] = {}
    for r in rows[1:]:
        if len(r) <= max(oi, pi):
            continue
        if (r[pi] or "").strip().upper() == "AIR":
            air[_canon(r[oi].strip(), alias_raw)] = air.get(_canon(r[oi].strip(), alias_raw), 0) + 1
    return air


def _parse_icd(rows: list[list[str]], roster: dict, alias_raw: dict, air_by_canon: dict):
    """Per-section product counts + owner counts, aggregated via the roster.
    Owners Over 100 counts owners whose weekly units (4 non-AIR PRODUCT SALES
    products + Order Log AIR orders) reach 100. Returns (per_section: {section:
    {air,newint,upgrade,video,wireless,totalowners,ownersover100}},
    unmatched: [owner,...])."""
    # Owner grand totals (Rep == Total, Product == Total). With the forced
    # product filter these now INCLUDE net AIR.
    owner_total: dict[str, float] = {}
    for r in rows[1:]:
        if len(r) > 10 and r[1].strip() == "Total" and r[2].strip() == "Total":
            owner = r[0].strip()
            if owner.lower() == "sales total":
                continue
            owner_total[owner] = _num(r[10]) or 0

    sections = ("ARON", "CHAN", "PAT", "RAF", "SAHIL", "SAM", "STARR", "TONY", "WAYNE")
    per = {s: {"air": 0, "newint": 0, "upgrade": 0, "video": 0, "wireless": 0,
               "totalowners": 0, "ownersover100": 0} for s in sections}

    # Per-rep product rows → add to owner's team. Also track each owner's net
    # AIR so the >=100 threshold can back it out of the Total row.
    unmatched = set()
    owner_air_net: dict[str, float] = {}
    for r in rows[1:]:
        if len(r) <= 10 or r[1].strip() == "Total":
            continue
        owner = r[0].strip()
        prod_key = PRODUCT_KEYS.get((r[2] or "").strip().upper())
        if not prod_key:
            continue
        if prod_key == "air":
            owner_air_net[owner] = owner_air_net.get(owner, 0) + (_num(r[10]) or 0)
        section = roster.get(_canon(owner, alias_raw))
        if not section:
            unmatched.add(owner)
            continue
        per[section][prod_key] += _num(r[10]) or 0

    # Owner counts per team (owners appearing in the product data). The
    # >=100 threshold counts the 4 non-AIR PRODUCT SALES products PLUS the
    # owner's Order Log AIR orders (gross — Eve, 2026-06-04: keep the
    # threshold's AIR source unchanged). Net AIR is backed out of the Total
    # row so it isn't double-counted against the Order Log number.
    for owner, total in owner_total.items():
        c = _canon(owner, alias_raw)
        section = roster.get(c)
        if not section:
            unmatched.add(owner)
            continue
        per[section]["totalowners"] += 1
        if (total - owner_air_net.get(owner, 0) + air_by_canon.get(c, 0)) >= 100:
            per[section]["ownersover100"] += 1

    return per, sorted(unmatched)


# --------------------------------------------------------------------- main
def gather(week: dt.date, page=None, skip_download: bool = False, logfn=print) -> dict:
    """Pull + aggregate. Returns {'data': {section: {key: value}},
    'unmatched': [...], 'missing_cols': [...]}."""
    paths = _paths()
    if not skip_download:
        if page is not None:
            paths = _download(week, page, logfn)
        else:
            from automations.shared.tableau_patchright import tableau_session
            with tableau_session(verbose=True) as pg:
                paths = _download(week, pg, logfn)

    try:
        alias_raw = _aliases.load_aliases()
    except Exception as e:
        logfn(f"  (alias sheet unreachable: {e} — matching on raw names)")
        alias_raw = {}

    rates, roster, missing = _parse_metrics(_read_crosstab(paths["metrics"]), alias_raw)
    org = _parse_org(_read_crosstab(paths["org"]))
    air = _parse_orderlog_air(_read_crosstab(paths["orderlog"]), alias_raw)
    per_icd, unmatched = _parse_icd(_read_crosstab(paths["icd"]), roster, alias_raw, air)

    data: dict[str, dict] = {}
    # COUNTRY: rates from Grand Total + products from ORG (no owner counts — formula).
    data["COUNTRY"] = {**rates.get("COUNTRY", {}), **org}
    # Captainships + SAM: rates from team Total + products/owners from by-ICD.
    for section in ("RAF", "STARR", "ARON", "PAT", "WAYNE", "SAM", "CHAN", "TONY", "SAHIL"):
        d = dict(rates.get(section, {}))
        d.update(per_icd.get(section, {}))
        data[section] = d

    return {"data": data, "unmatched": unmatched, "missing_cols": missing,
            "roster_size": len(roster), "air_total": sum(air.values())}
