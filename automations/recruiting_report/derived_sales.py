"""Rebuild a newly-promoted ICD's weekly sales from the office they came out of.

Tableau promotes an owner in stages. The Metrics view gets them first — they
show up as an `ICD Owner Name` with their own `Rep Name` roster — but the ATT
and INT ICD Summary views keep crediting their reps' sales to the office they
were promoted OUT of. In between, their tab's four sale-type rows fill blank
every Monday even though the sales exist and are sitting one office over.

This module closes that window: take the owner's roster from the Metrics view
(Tableau's own answer to "who is in this office"), then sum those reps inside
the HOST office's rows in the PRODUCT SALES crosstab.

Verified 2026-08-04 against four offices that ARE in both sources (Gabe Perez,
Cody Cannon, Sahil Multani, Chan Park): 14 of 16 sale-type totals matched the
official ATT number exactly, the two misses being 1 wireless line each on
130+-line offices. So the derived numbers are the same numbers, not an estimate.

SELF-RETIRING BY DESIGN. `opt_phase.fill_opt_for_tab` only consults this when
the tab has NO ATT row. The week Tableau starts listing the owner as an ICD,
the real crosstab wins and none of this runs — no config change, no cleanup.
Nothing here ever overwrites a value that came from a real Tableau row.

CAUTION — these sales are DOUBLE-COUNTED while the window is open: the host
office's own ATT row still includes them, so they land on the host's tab too.
That is Tableau's state of the world, not something this module introduces, but
it means org-level totals over the ICD tabs will run high until the promotion
finishes. Every run logs the derivation so it is never silent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

# {Sheet tab name: the host office EXACTLY as the PRODUCT SALES crosstab spells
#  its 'Owner Name'}. Add a row when someone is promoted and Tableau has only
#  half-moved them; delete it once their ATT row exists (harmless either way —
#  the ATT row takes precedence automatically).
DERIVED_SALES: Dict[str, str] = {
    # Promoted out of Gabe Perez's office into Mercel Management (AppStream
    # office 23888) — in the Metrics view as an owner since at least WE 8/2,
    # still absent from ATT/INT. (Eve, 2026-08-04)
    "Mercy Ohiokhai": "Gabe Perez",
}

# PRODUCT SALES 'Product Type (Broken Out)' -> the Sheet's OPT row label.
# Same four types the ATT crosstab reports, under different names.
PRODUCT_TO_ROW: Dict[str, str] = {
    "NEW INTERNET":     "New Internets",
    "UPGRADE INTERNET": "Upgrades",
    "VIDEO":            "DTV",
    "WIRELESS":         "New Lines",
}


def _norm(s) -> str:
    """Lowercase, drop apostrophes/periods, collapse whitespace."""
    s = str(s or "").strip().lower().replace("'", "").replace("’", "").replace(".", "")
    return re.sub(r"\s+", " ", s)


def _same_person(a: str, b: str) -> bool:
    """True when two crosstab spellings are the same rep.

    The Metrics view and the PRODUCT SALES view disagree on middle names —
    'Briana Zamora' vs 'Briana Karlen Orejel Zamora', 'Francisco Daniel
    Martinez' vs 'Francisco Martinez'. Match on FIRST + LAST word rather than
    a loose subset test, so two different reps who merely share a surname
    can't collapse into one.
    """
    na, nb = _norm(a).split(), _norm(b).split()
    if not na or not nb:
        return False
    if na == nb:
        return True
    return len(na) >= 2 and len(nb) >= 2 and na[0] == nb[0] and na[-1] == nb[-1]


def _read_crosstab(path: Path) -> List[List[str]]:
    """Tableau crosstabs are UTF-16, tab-delimited."""
    raw = Path(path).read_text(encoding="utf-16")
    return [ln.split("\t") for ln in raw.splitlines() if ln.strip()]


def roster_from_metrics(metrics_path: Path, owner_name: str) -> List[str]:
    """The reps Tableau's Metrics view assigns to `owner_name`'s office.

    That view repeats the ICD name on every rep row and carries the office's
    own subtotal on a 'Total' row — we want the rep rows, not the subtotal.
    """
    rows = _read_crosstab(metrics_path)
    if not rows:
        return []
    headers = [_norm(h) for h in rows[0]]
    owner_col = next((i for i, h in enumerate(headers) if "icd owner name" in h), 0)
    rep_col = next((i for i, h in enumerate(headers) if h == "rep name"), None)
    if rep_col is None:
        return []
    target = _norm(owner_name)
    out: List[str] = []
    for r in rows[1:]:
        if len(r) <= max(owner_col, rep_col):
            continue
        if _norm(r[owner_col]) != target:
            continue
        rep = r[rep_col].strip()
        if rep and rep.lower() != "total" and rep not in out:
            out.append(rep)
    return out


def sales_from_host(product_sales_path: Path, host_owner: str,
                    roster: List[str]) -> dict:
    """Sum this roster's weekly sales inside the host office's rows.

    Adds the seven weekday columns only — the crosstab's trailing 'Product
    Total' column already holds the week's sum, so including it would double
    every count (same trap `parse_personal_production` sidesteps).

    Returns {"values": {Sheet row label: int}, "headcount": int,
             "matched": [...], "unmatched": [...]} — `unmatched` being roster
    reps with no row under the host, which usually just means they sold
    nothing this week.

    `headcount` is the count of roster reps that sold something, which is what
    ATT's 'Rep Count' measures: checked 2026-08-04 against the first 15 offices
    in the ATT crosstab and it matched 14 of 15 exactly (Rafael Hidalgo off by
    one). It feeds 'Active Headcount on Tableau'.
    """
    rows = _read_crosstab(product_sales_path)
    if not rows:
        return {"values": {}, "matched": [], "unmatched": list(roster)}
    headers = [str(h).strip().lower() for h in rows[0]]
    day_cols = [i for i in range(3, len(headers)) if "total" not in headers[i]]

    totals: Dict[str, int] = {label: 0 for label in PRODUCT_TO_ROW.values()}
    matched: List[str] = []
    host = _norm(host_owner)
    for r in rows[1:]:
        if len(r) < 4 or _norm(r[0]) != host:
            continue
        rep = (r[1] or "").strip()
        ptype = (r[2] or "").strip().upper()
        if not rep or rep.lower() == "total" or ptype not in PRODUCT_TO_ROW:
            continue
        if not any(_same_person(rep, m) for m in roster):
            continue
        week = 0
        for i in day_cols:
            cell = r[i].strip() if i < len(r) else ""
            if cell.replace(",", "").isdigit():
                week += int(cell.replace(",", ""))
        if week:
            totals[PRODUCT_TO_ROW[ptype]] += week
        if rep not in matched:
            matched.append(rep)

    unmatched = [m for m in roster
                 if not any(_same_person(m, hit) for hit in matched)]
    return {"values": totals, "headcount": len(matched),
            "matched": matched, "unmatched": unmatched}


def build(metrics_path: Path, product_sales_path: Path,
          logfn=print) -> Dict[str, dict]:
    """Derive sales for every tab in DERIVED_SALES that still needs it.

    Returns {tab_name: {"values": {row label: int}, "host": str,
                        "roster": [...], "matched": [...], "unmatched": [...]}}.
    Fails soft: a missing or unreadable crosstab just yields no derivations,
    and the tab's sale rows stay blank exactly as they are today.
    """
    out: Dict[str, dict] = {}
    if not DERIVED_SALES:
        return out
    for tab, host in DERIVED_SALES.items():
        try:
            roster = roster_from_metrics(metrics_path, tab)
            if not roster:
                logfn(f"OPT: derived sales for {tab} — no roster in the Metrics "
                      f"view yet; sale rows stay blank")
                continue
            res = sales_from_host(product_sales_path, host, roster)
        except Exception as e:  # noqa: BLE001 — never fail the OPT phase
            logfn(f"OPT: derived sales for {tab} FAILED ({type(e).__name__}: "
                  f"{str(e)[:120]}) — sale rows stay blank")
            continue
        vals = {k: v for k, v in res["values"].items() if v}
        if not vals:
            logfn(f"OPT: derived sales for {tab} — roster of {len(roster)} "
                  f"sold nothing under '{host}' this week")
            continue
        res["host"] = host
        res["roster"] = roster
        out[tab] = res
        logfn(f"OPT: derived sales for {tab} from host office '{host}' — "
              + ", ".join(f"{k}={v}" for k, v in res["values"].items())
              + f"  (roster {len(roster)}, matched {len(res['matched'])}"
              + (f", no sales this week: {', '.join(res['unmatched'])}"
                 if res["unmatched"] else "") + ")")
    return out
