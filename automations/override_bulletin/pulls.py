"""Number pulls for the override-bulletin fill (phases 2-4).

Each function fetches ONE piece of the weekly override for a given week and
returns a plain {normalized_owner_name: amount} dict (or a scalar for the
Raf-only pieces), so fill.py can assemble section-1/section-2 and report anyone
it can't match. See FILL_SOURCES.md for the full spec.

WEEK KEYS. The override sheet labels weeks m.d.yy ("7.12.26"). Sources use their
own conventions (Raf PNL "WE 7/12"; DD Detail runs a day behind). Each pull maps
the sheet's week to its source internally; callers pass the sheet label.

The Tableau pulls MUST run on Lucy 1 (Raf's login — only Raf's org views see the
whole downline) and are built on download_crosstab_patchright. The Raf-PNL pull
below is a plain Google-Sheets read and runs anywhere.
"""
from __future__ import annotations

import datetime as dt
import re


def _norm_name(s: str) -> str:
    """Fold a person name for matching across sources: drop any '[office]' /
    '(office)' suffix, lowercase, collapse whitespace. 'CARLOS HIDALGO [alphalete
    specialized marketing, inc.]' and ' Carlos Hidalgo ' both -> 'carlos hidalgo'."""
    s = (s or "").split("[")[0].split("(")[0]
    return " ".join(s.lower().split())


def _we_key(week_mdy: str) -> str:
    """'7.12.26' -> 'WE 7/12' (the Raf PNL header form)."""
    m, d, _y = week_mdy.split(".")
    return f"WE {int(m)}/{int(d)}"


# --------------------------------------------------------------------------
# Raf Captain Override — Google Sheet (Raf PNL 2026, row 335)
# --------------------------------------------------------------------------
RAF_PNL_WORKBOOK = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
RAF_PNL_TAB = "Raf PNL 2026"
RAF_CAPTAIN_ROW = 335        # "Captain Override" row


def _money(raw):
    if raw is None:
        return None
    s = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def raf_captain_override(week_mdy: str, ws=None):
    """Raf's Captain Override for the given sheet week (e.g. '7.12.26').

    Reads Raf PNL 2026 row 335 at the target week's WE block — the value sits in
    the block's Profit/Loss column, i.e. the WE-header column + 2 (the label
    'Captain Override' is one cell left, under 'Got Paid'). Returns the amount or
    None if the week/value isn't present."""
    if ws is None:
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(RAF_PNL_WORKBOOK).worksheet(RAF_PNL_TAB)
    vals = ws.get_all_values()
    header = vals[0]
    want = _we_key(week_mdy)
    base = next((i for i, h in enumerate(header) if (h or "").strip() == want), None)
    if base is None:
        return None
    row = vals[RAF_CAPTAIN_ROW - 1] if RAF_CAPTAIN_ROW - 1 < len(vals) else []
    vcol = base + 2                                  # Profit/Loss col of the block
    return _money(row[vcol]) if vcol < len(row) else None


# --------------------------------------------------------------------------
# Regular override — Tableau ORG OVERRIDE SUMMARY crosstab
# --------------------------------------------------------------------------
OVERRIDE_SUMMARY_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "OverridesICDView/ORGOVERRIDESUMMARY")


def _num_locale(s: str):
    """Parse a money string in either US ('72,253.17') or EU ('72.253,17')
    format, tolerating '$', parens-negatives and spaces. None if not a number."""
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if "," in t and "." in t:
        # last separator is the decimal
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") \
            else t.replace(",", "")
    elif "," in t:
        # comma-only: decimal if it looks like ",dd" at the end, else thousands
        t = t.replace(",", ".") if re.search(r",\d{1,2}$", t) else t.replace(",", "")
    try:
        v = float(t)
        return -v if neg else v
    except ValueError:
        return None


def parse_override_summary(rows, week_header, *, name_col=0):
    """Sum each ICD owner's campaign rows for one week column.

    `rows` is the downloaded crosstab as a list of row-lists. The owner name sits
    in `name_col`; continuation rows for the owner's other campaigns have a blank
    name (Megan 2026-07-22: "add up the sum of everything listed with that ICD").
    `week_header` is the target week's column header (e.g. '07/12/2026'); we find
    that column in the header rows. Returns {normalized_owner: total}. Skips the
    grand-total row ('Total general' / 'Grand Total')."""
    # locate the week column (and the header row) by matching its header
    wk_col = hdr_row = None
    for ri, r in enumerate(rows[:6]):
        for ci, cell in enumerate(r):
            if str(cell).strip() == str(week_header).strip():
                wk_col, hdr_row = ci, ri
                break
        if wk_col is not None:
            break
    if wk_col is None:
        raise ValueError(f"week column {week_header!r} not found in crosstab header")

    out, cur = {}, None
    for r in rows[hdr_row + 1:]:               # skip the header rows
        name = (r[name_col] if name_col < len(r) else "").strip()
        low = name.lower()
        if low in ("total general", "grand total", "total"):
            cur = None
            continue
        if name:
            cur = _norm_name(name)
            out.setdefault(cur, 0.0)
        if cur is None:
            continue
        val = _num_locale(r[wk_col]) if wk_col < len(r) else None
        if val is not None:
            out[cur] += val
    return {k: round(v, 2) for k, v in out.items()}


# --------------------------------------------------------------------------
# Shared crosstab helpers + the other-source parsers (column names set once
# discovery confirms the real headers; the parse LOGIC below is unit-tested).
# --------------------------------------------------------------------------
def read_crosstab(path):
    """Read a Tableau crosstab file to a list of row-lists. Tableau exports
    UTF-16 tab-separated; some are UTF-8/comma. Tries encodings in order and
    auto-detects the delimiter (mirrors int_wow_penetration.pull)."""
    import csv
    import io
    raw = open(path, "rb").read()
    txt = None
    for enc in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if txt is None:
        txt = raw.decode("latin-1", "replace")
    first = txt.splitlines()[0] if txt else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    return list(csv.reader(io.StringIO(txt), delimiter=delim))


def _hdr_col(header, name):
    """Index of the header cell matching `name` (case/space-insensitive), or None."""
    want = " ".join(str(name).lower().split())
    for i, h in enumerate(header):
        if " ".join(str(h).lower().split()) == want:
            return i
    return None


_CAP_RE = re.compile(r"captain'?s?\s+bonus", re.I)
_WK_IN_DESC = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def parse_dd_captain(rows, owners):
    """{owner_norm: {week_key: amount}} of Captain's-Bonus overrides from the
    ORG DD Detail crosstab.

    The crosstab is HIERARCHICAL — empty dimensions collapse per row, so columns
    do NOT align to the header (the amount lands wherever the row happens to end).
    So we match by CONTENT, not column index:
      * the row has a 'Captain('s) Bonus M.D.YY' cell (the description),
      * its owner (any cell) is in `owners` (normalized captain names),
      * the amount is the max money cell (Total $ to ICD == the non-zero one).
    week_key is 'M.D.YY' parsed from the description (rows with no date — e.g. the
    $0 NDS wireless 'Captain Bonus' — are skipped). The fill maps week_key to the
    sheet column positionally, so the DD-vs-sheet day offset doesn't matter."""
    out = {}
    for r in rows:
        cap = next((str(c) for c in r if _CAP_RE.search(str(c))), None)
        if not cap:
            continue
        m = _WK_IN_DESC.search(cap)
        if not m:
            continue
        wk = f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)[-2:]}"
        owner = next((_norm_name(c) for c in r if _norm_name(c) in owners), None)
        if not owner:
            continue
        amt = max((_num_locale(c) or 0) for c in r)
        if amt:
            d = out.setdefault(owner, {})
            d[wk] = round(d.get(wk, 0) + amt, 2)
    return out


def parse_ledger(rows, *, owner_col, expl_col, amt_col, needle):
    """{owner: Transaction Amount} for ledger rows whose NS_Explanation contains
    `needle` (e.g. 'P6-2026 Special Override' or 'January 2026 ... Credico')."""
    hdr = rows[0]
    oc, ec, ac = (_hdr_col(hdr, c) for c in (owner_col, expl_col, amt_col))
    out, cur = {}, None
    for r in rows[1:]:
        nm = (r[oc] or "").strip() if oc is not None and oc < len(r) else ""
        if nm:
            cur = _norm_name(nm)
        expl = (r[ec] or "") if ec is not None and ec < len(r) else ""
        if needle.lower() in expl.lower() and cur is not None:
            v = _num_locale(r[ac]) if ac is not None and ac < len(r) else None
            if v is not None:
                out[cur] = out.get(cur, 0) + v
    return {k: round(v, 2) for k, v in out.items()}


def parse_raf_payout(rows, *, label, week_header):
    """Scalar 'Raf Payout Total' for a Processed-Week column."""
    wk = None
    for r in rows[:8]:
        for i, c in enumerate(r):
            if str(c).strip() == str(week_header).strip():
                wk = i
                break
        if wk is not None:
            break
    if wk is None:
        return None
    for r in rows:
        if any(label.lower() in str(c).lower() for c in r[:2]):
            return _num_locale(r[wk]) if wk < len(r) else None
    return None


# --------------------------------------------------------------------------
# Fetch wrappers — download the confirmed crosstab sheets (Lucy 1) and parse.
# DD + NETSUITE carry ALL weeks/transactions, so no period-select is needed —
# we download the whole sheet once and filter in the parse.
# --------------------------------------------------------------------------
DD_DETAIL_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "DirectDepositICDVIEWVersion2_0/DDDETAILORG")
DD_DETAIL_SHEET = "ORG DD Detail"

LEDGER_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "OverridesICDView/NETSUITESECURITYLEDGERSFDC")
LEDGER_SHEET = "Transaction Details"


def dd_captain_overrides(owners, out_path, *, page=None, verbose=True):
    """{owner_norm: {week_key: amount}} — download ORG DD Detail once and extract
    every Captain's-Bonus override for the captains in `owners`, keyed by the
    description's week (M.D.YY). The caller picks the target week per captain."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    download_crosstab_patchright(DD_DETAIL_VIEW, DD_DETAIL_SHEET, out_path,
                                 page=page, verbose=verbose)
    rows = read_crosstab(out_path)
    return parse_dd_captain(rows, {_norm_name(o) for o in owners})


def ledger_amounts(needle, out_path, *, page=None, verbose=True):
    """{owner: Transaction Amount} for ledger rows whose NS_Explanation contains
    `needle` (e.g. 'P6-2026 Special Override' or 'January 2026 ... Credico').
    Downloads the Transaction Details sheet once (all owners, all transactions)."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    download_crosstab_patchright(LEDGER_VIEW, LEDGER_SHEET, out_path,
                                 page=page, verbose=verbose)
    rows = read_crosstab(out_path)
    return parse_ledger(rows, owner_col="ICD Owner Name and OFFICE NAME",
                        expl_col="NS_Explanation__c", amt_col="Transaction Amount",
                        needle=needle)


# --------------------------------------------------------------------------
# Period-scoped pulls (RAF special, regular override). The crosstab shows only
# the selected Period's weeks, so we set the Period via a URL filter param
# (avoids driving the dropdown). Field name/value format confirmed on Lucy 1.
# --------------------------------------------------------------------------
RAF_BONUS_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "ResATTSpecialDealOverride-Raf/RafOverrideBonus")
RAF_BONUS_SHEET = "Payout- Raf wow"

ORG_SUMMARY_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                    "OverridesICDView/ORGOVERRIDESUMMARY")
# Crosstab sheet name — confirmed on Lucy 1; only renders under a 'Period 2026-M'
# filter (the bare 'Period M' form returns no sheets).
ORG_SUMMARY_SHEET = "ORG Override Summary"


def _with_filter(base_url, field, value):
    """Append a Tableau URL filter param: ?<field>=<value> (or &…)."""
    from urllib.parse import quote
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{quote(field)}={quote(value)}"


def raf_special_override(week_header, out_path, *, period, page=None, verbose=True):
    """Raf's special override ('Raf Payout Total' row) for a week. `period` is the
    Period-filter value (e.g. 'Period 7')."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    url = _with_filter(RAF_BONUS_VIEW, "Period", period)
    download_crosstab_patchright(url, RAF_BONUS_SHEET, out_path, page=page, verbose=verbose)
    return parse_raf_payout(read_crosstab(out_path), label="Raf Payout Total",
                            week_header=week_header)


def regular_overrides(week_header, out_path, *, period, page=None, verbose=True):
    """{owner: regular override} — sum each owner's campaign rows for the week
    column. `period` is the Period-filter value (e.g. 'Period 2026-7')."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    url = _with_filter(ORG_SUMMARY_VIEW, "Period", period)
    download_crosstab_patchright(url, ORG_SUMMARY_SHEET, out_path, page=page, verbose=verbose)
    rows = read_crosstab(out_path)
    return parse_override_summary(rows, week_header)


def period_for(week_mdy, *, style="num"):
    """Period-filter value for a sheet week. 'Period 2026-7' (style='year') or
    'Period 7' (style='num') — the month drives the period number."""
    m = int(week_mdy.split(".")[0])
    return f"Period 2026-{m}" if style == "year" else f"Period {m}"
