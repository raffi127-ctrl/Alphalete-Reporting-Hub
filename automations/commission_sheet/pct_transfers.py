"""ATT Sales Transfers -> the %-payout workbook (Maud's Loom 2026-11-24).

Reads "ATT Sales Transfers" on All in One Local Office - Raf and applies every
open row whose customer ACTIVATED this week (= is on this week's DD):

  * TRANSFER — "Your Name" gets the sale that sits under "Name that the Sale
    is under". The customer's DD lines are moved to the right rep (Edited,
    their tab, their revenue + commission).
  * CUSTOMER BONUS — "Your Name" reads "$20 bonus"; the rep the sale is under
    earns it, PER ACTIVATED LINE: the rate comes from the Notes ("$20 x 4"),
    else the amount / quantity. Shown as "<Customer> bonus".
  * SPLIT — Notes like "Safiya gets 70%, Leo gets 35%": the sale's revenue is
    paid as a customer bonus to each named rep at their %, and is left out of
    the sale rep's own commission (marked "Split sale").

Status written back to the tab (column L), with column M ("Paid Weeks") keeping
how many lines were paid in which week, so a re-run of the same week is safe:
  PAID                   every line in the Quantity column has activated
  PARTIALLY (k of n)     some lines activated; the rest pay when they do
  CANCELLED              still not activated 45+ days after the sale date
Rows already PAID / CANCELLED / QUIT are left alone. Anything that can't be
matched safely is left blank and listed on the workbook's "Transfers to Check"
tab with the reason.

Lines are counted as distinct SPE numbers (cl.Production Lookup) on the DD's
"Base" rows for that customer — every phone line / internet has its own.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.commission_sheet import config as C
from automations.commission_sheet.names import customer_keys, match_person, nrm

PAID, CANCELLED = "PAID", "CANCELLED"
DONE = {"PAID", "CANCELLED", "QUIT"}
CANCEL_AFTER_DAYS = 45
WEEKS_HEADER = "Paid Weeks"
SPLIT_NOTE = "Split sale"


@dataclass
class Plan:
    moves: List[Tuple[int, str, str]] = field(default_factory=list)    # (edited idx, to rep, note)
    split: List[int] = field(default_factory=list)                     # edited idx
    bonuses: List[Tuple[str, str, float]] = field(default_factory=list)  # (rep, label, $)
    updates: Dict[int, Tuple[str, str]] = field(default_factory=dict)  # row -> (status, weeks)
    checks: List[list] = field(default_factory=list)                   # rows for the check tab
    applied: List[str] = field(default_factory=list)                   # log lines


def _money(s) -> Optional[float]:
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", str(s or ""))
    return float(m.group(1).replace(",", "")) if m else None


def _qty(text) -> Optional[int]:
    nums = [int(n) for n in re.findall(r"\d+", str(text or ""))]
    return sum(nums) or None


def _date(s) -> Optional[dt.date]:
    try:
        m, d, y = (int(x) for x in str(s).strip().split()[0].split("/"))
        return dt.date(y, m, d)
    except (ValueError, IndexError):
        return None


def _weeks(text) -> Dict[str, int]:
    """'WE 11.22: 2 · WE 11.29: 1' -> {'WE 11.22': 2, 'WE 11.29': 1}"""
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"(WE \d+\.\d+):\s*(\d+)", str(text or ""))}


def _weeks_text(d: Dict[str, int]) -> str:
    return " · ".join(f"{k}: {v}" for k, v in d.items() if v)


def _splits(note) -> List[Tuple[str, float]]:
    """'Safiya gets 70%, LEO gets 35%' / '… and Leo 35% of the commission'."""
    out = []
    for m in re.finditer(r"([A-Za-z][A-Za-z'\-]+)\s+(?:gets\s+)?(\d+(?:\.\d+)?)\s*%", str(note or "")):
        out.append((m.group(1), float(m.group(2)) / 100))
    return out


def load(sheet_id: str = C.ALL_IN_ONE_ID):
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(sheet_id).worksheet(C.TAB_TRANSFERS)
    values = ws.get_values()
    return ws, values


def _col(header, label) -> int:
    lab = nrm(label)
    for i, h in enumerate(header):
        if lab in nrm(h):
            return i
    raise KeyError(f"{C.TAB_TRANSFERS!r} has no {label!r} column")


def plan(values, edited, roster, week_label: str, run_date: dt.date,
         held=frozenset()) -> Plan:
    """Work out what to apply this week. edited: the Edited records (with
    '_spe' / '_ctype'); roster: rep names to resolve form names against;
    held: name keys of new starts held this week (their bonuses still land on
    their row and carry with them)."""
    P = Plan()
    header = [str(h) for h in values[0]]
    c_to, c_from = _col(header, C.TR_TO_REP), _col(header, C.TR_FROM_REP)
    c_date, c_cust = _col(header, C.TR_SALE_DATE), _col(header, C.TR_CUSTOMER)
    c_notes, c_qty = _col(header, "Notes"), _col(header, "Quantity")
    c_status = _col(header, "Status")
    c_weeks = next((i for i, h in enumerate(header) if WEEKS_HEADER.lower() in h.lower()), None)

    by_cust = collections.defaultdict(list)
    for i, d in enumerate(edited):
        for k in customer_keys(d.get("Customer Name", "")):
            by_cust[k].append(i)

    seen = set()
    for n, raw in enumerate(values[1:], start=2):
        cells = [str(c) for c in raw] + [""] * (len(header) + 2 - len(raw))
        to_rep, frm = cells[c_to].strip(), cells[c_from].strip()
        cust, notes = cells[c_cust].strip(), cells[c_notes].strip()
        status = cells[c_status].strip().upper()
        weeks = _weeks(cells[c_weeks] if c_weeks is not None else "")
        this_week_done = week_label in weeks
        if status in DONE and not this_week_done:
            continue
        if "test" in to_rep.lower() or "test" in frm.lower() or not cust:
            continue
        before = sum(v for k, v in weeks.items() if k != week_label)
        is_bonus = "bonus" in to_rep.lower()
        split = _splits(notes)
        qty = _qty(cells[c_qty])
        rate = None
        if is_bonus:
            m = re.search(r"\$\s*([\d.]+)\s*[x×]\s*(\d+)", notes, re.I)
            if m:
                rate, qty = float(m.group(1)), int(m.group(2))
            else:
                total = _money(to_rep)
                rate = (total / qty) if (total and qty) else total

        def check(why):
            P.checks.append([n, cells[0], to_rep, frm, cust, cells[c_qty].strip(),
                             notes, why])

        # same customer + same order (SPM) + same kind = submitted twice
        spm = re.sub(r"\D", "", cells[_col(header, C.TR_SPM)])[-9:]
        dkey = (tuple(sorted(customer_keys(cust))), nrm(frm), is_bonus, bool(split),
                spm or nrm(cells[c_qty]))
        if dkey in seen:
            check("duplicate submission — already counted above")
            continue
        seen.add(dkey)

        hits = []
        for k in customer_keys(cust):
            hits = by_cust.get(k, [])
            if hits:
                break
        full = {str(edited[i]["Customer Name"]).strip().lower() for i in hits}
        if len(full) > 1:
            check(f"customer name matches more than one DD customer: {sorted(full)}")
            continue
        units = len({edited[i].get("_spe") for i in hits
                     if edited[i].get("_ctype") == "Base" and edited[i].get("_spe")})
        if not hits or not units:
            sale = _date(cells[c_date])
            if not before and sale and (run_date - sale).days >= CANCEL_AFTER_DAYS:
                P.updates[n] = (CANCELLED, _weeks_text(weeks))
                P.applied.append(f"r{n} {cust}: not activated {CANCEL_AFTER_DAYS}+ days -> CANCELLED")
            continue

        dd_rep = edited[hits[0]]["Rep Full Name"]
        if qty:
            units = min(units, max(qty - before, 0)) or units
        if units == 0:
            continue

        if split:
            who = []
            for first, pct in split:
                m, cands = match_person(first, roster)
                if not m:
                    who = None
                    check(f"split: can't tell who {first!r} is"
                          + (f" (could be {cands})" if cands else ""))
                    break
                who.append((m, pct))
            if who is None:
                continue
            rev = sum(edited[i]["Total $ to ICD"] for i in hits)
            P.split.extend(hits)
            for m, pct in who:
                P.bonuses.append((m, f"{cust.title()} split {pct:.0%}", round(rev * pct, 2)))
            P.applied.append(f"r{n} {cust}: split {who} of ${rev:,.2f}")
        elif is_bonus:
            earner, cands = match_person(frm, roster)
            if not earner:
                check(f"bonus earner {frm!r} not found"
                      + (f" (could be {cands})" if cands else ""))
                continue
            if rate is None:
                check("bonus amount not readable")
                continue
            amt = round(rate * units, 2) if qty else round(rate, 2)
            P.bonuses.append((earner, f"{cust.title()} bonus", amt))
            P.applied.append(f"r{n} {cust}: ${amt:,.2f} bonus -> {earner} ({units} line(s))")
        else:
            dst, dcands = match_person(to_rep, roster)
            if not dst:
                check(f"can't tell who {to_rep!r} is"
                      + (f" (could be {dcands})" if dcands else ""))
                continue
            src, _ = match_person(frm, [dd_rep])
            if nrm(dd_rep) == nrm(dst):
                P.applied.append(f"r{n} {cust}: already under {dst}")
            elif not src:
                check(f"DD has this sale under {dd_rep!r}, not {frm!r}")
                continue
            else:
                for i in hits:
                    P.moves.append((i, dst, f"Transferred from {dd_rep}"))
                P.applied.append(f"r{n} {cust}: {dd_rep} -> {dst} ({units} line(s))")

        weeks[week_label] = units
        got = before + units
        status = PAID if (not qty or got >= qty) else f"PARTIALLY ({got} of {qty})"
        P.updates[n] = (status, _weeks_text(weeks))
    return P


def write(ws, values, updates: Dict[int, Tuple[str, str]]) -> int:
    """Status (L) and Paid Weeks (next free column, header added once)."""
    from gspread.utils import rowcol_to_a1
    header = [str(h) for h in values[0]]
    c_status = _col(header, "Status")
    c_weeks = next((i for i, h in enumerate(header) if WEEKS_HEADER.lower() in h.lower()), None)
    data = []
    if c_weeks is None:
        c_weeks = len(header)
        data.append({"range": rowcol_to_a1(1, c_weeks + 1), "values": [[WEEKS_HEADER]]})
    for n, (status, weeks) in sorted(updates.items()):
        data.append({"range": rowcol_to_a1(n, c_status + 1), "values": [[status]]})
        data.append({"range": rowcol_to_a1(n, c_weeks + 1), "values": [[weeks]]})
    if data:
        ws.batch_update(data, value_input_option="RAW")
    include_in_table(ws, c_weeks)
    return len(updates)


def include_in_table(ws, col: int) -> bool:
    """The tab is a Google Sheets table (its filter hides PAID / CANCELLED /
    QUIT). Widen the table to take in `col` (0-based) so Paid Weeks sits inside
    the filter (Maud 2026-11-24). Keeps the table's sort and filters."""
    sh = ws.spreadsheet
    meta = sh.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),tables,bandedRanges(bandedRangeId,range))"})
    for sheet in meta["sheets"]:
        if sheet["properties"]["sheetId"] != ws.id:
            continue
        for t in sheet.get("tables", []):
            rng = t["range"]
            if rng["startColumnIndex"] != 0 or rng["endColumnIndex"] > col:
                continue
            props = t.get("columnProperties", [])
            have = {p.get("columnIndex", 0) for p in props}
            for c in range(rng["endColumnIndex"], col + 1):
                if c not in have:
                    props.append({"columnIndex": c,
                                  "columnName": WEEKS_HEADER if c == col else f"Column {c + 1}"})
            rng = dict(rng, endColumnIndex=col + 1)
            # Sheets bands a column typed next to a table on its own; that
            # banding blocks the table from growing over it — drop it first.
            reqs = [{"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}}
                    for b in sheet.get("bandedRanges", [])
                    if b["bandedRangeId"] != int(t["tableId"])
                    and b["range"]["startColumnIndex"] >= t["range"]["endColumnIndex"]
                    and b["range"]["endColumnIndex"] <= col + 1]
            sh.batch_update({"requests": reqs + [{"updateTable": {
                "table": {"tableId": t["tableId"], "range": rng, "columnProperties": props},
                "fields": "range,columnProperties"}}]})
            return True
    return False
