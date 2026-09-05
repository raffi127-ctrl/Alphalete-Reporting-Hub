"""Step 5 — reconcile `ATT Sales Transfers` against the week's DD.

This is the step JD calls "the difficult part that takes the most amount of
time" (Loom 2026-09-03). The form feeds two different things through one tab:

  * a REAL TRANSFER — `Your Name` is the rep who should get the credit and
    `Name that the Sale is under` is the rep the sale currently sits under.
    If that customer activated, the DD's `REP.Full Name` is rewritten to the
    receiving rep, on EVERY DD row for the order (a sale is several rows: the
    base line plus its tier-volume bonus).
  * a BONUS — `Your Name` literally reads "$20 bonus" and the rep in `Name
    that the Sale is under` earns it. Eve fills these from SaraPlus, so the
    names already match. If the customer activated, a line is added to 4b
    rather than any name being rewritten.

A row only matters once the customer has ACTIVATED — i.e. once the order shows
up on this week's DD. Anything not yet on the DD stays pending and comes back
next week untouched; that is why the form carries months of open rows.

Joining the three sheets:
    transfers.SPM  ->  order log (sp.SPM Number)  ->  spe.Name (SPE-########)
                                                  ->  DD (cl.Production Lookup)
The SPE key is the reliable bridge (198 of 207 DD orders carry one that the
order log also has). But roughly half the real transfer rows have no usable
SPM — people type "N/a", "ENERGY SALE", or a phone number — so the customer
name is a needed fallback, matched on first-name + last-initial because the
order log abbreviates surnames.

Both paths run whenever they can, and a row where they DISAGREE is reported,
never applied.

    python -m automations.commission_sheet.transfers              # dry run
    python -m automations.commission_sheet.transfers --write      # apply
    python -m automations.commission_sheet.transfers --clear-paid # tidy the form

CLEARING THE PAID ONES. JD works the form down by emptying the rows he has
already dealt with, so only live ones remain (JD, 2026-09-04: "delete the data
in the cells"). `--clear-paid` does that: it empties the CELLS of every row
whose Status reads PAID and leaves the rows themselves in place, so no other
row shifts and nothing below is renumbered. Every row it empties is written to
output/ first — this is somebody's form data, and the manual version has no
undo.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.commission_sheet import config as C
from automations.commission_sheet.names import (
    customer_key, customer_keys, header_index, match_person, nrm, spm_key)

# Outcome kinds, in the order the report prints them.
APPLY_TRANSFER = "transfer"
APPLY_BONUS = "bonus"
PENDING = "pending"        # customer has not activated yet — leave it alone
REVIEW = "review"          # JD has to look at this one


@dataclass
class Finding:
    kind: str
    row: int                       # 1-based row in the transfers tab
    customer: str
    from_rep: str = ""
    to_rep: str = ""
    note: str = ""
    dd_rows: List[int] = field(default_factory=list)
    dd_rep: str = ""
    amount: str = ""

    def line(self) -> str:
        who = f"{self.from_rep} -> {self.to_rep}" if self.from_rep else self.to_rep
        rows = f" DD rows {self.dd_rows}" if self.dd_rows else ""
        note = f"  [{self.note}]" if self.note else ""
        amt = f" {self.amount}" if self.amount else ""
        return f"  r{self.row:<4} {self.customer[:26]:<26} {who}{amt}{rows}{note}"


class _Grid:
    """A tab's values plus label-based column access.

    `values` must start at sheet row 1 so the row numbers reported back are the
    ones JD sees in the sheet."""

    def __init__(self, values: List[List[str]], header_row: int, first_data_row: int):
        self.header = [str(c).strip() for c in values[header_row - 1]]
        self.width = len(self.header)
        self.first_data_row = first_data_row
        self.rows: List[tuple] = []          # (sheet_row_number, padded cells)
        for n, raw in enumerate(values[first_data_row - 1:], start=first_data_row):
            cells = [str(c) for c in raw] + [""] * (self.width - len(raw))
            if any(c.strip() for c in cells):
                self.rows.append((n, cells))

    def col(self, label: str) -> int:
        return header_index(self.header, label)

    def get(self, cells, label: str) -> str:
        return cells[self.col(label)].strip()


def _load(sheet_id: str, tab: str, rng: str, header_row: int, first_row: int) -> _Grid:
    from automations.recruiting_report.fill import open_by_key
    values = open_by_key(sheet_id).worksheet(tab).get(rng)
    return _Grid(values, header_row, first_row)


def analyze(workbook_id: str = C.WORKBOOK_ID,
            all_in_one_id: str = C.ALL_IN_ONE_ID) -> Dict[str, List[Finding]]:
    """Read the three tabs and work out what each pending transfer row needs.

    Read-only. Returns findings bucketed by kind."""
    dd = _load(workbook_id, C.TAB_DD, "A1:CA2000", C.DD_HEADER_ROW, C.DD_FIRST_DATA_ROW)
    ol = _load(workbook_id, C.TAB_ORDER_LOG, "A1:BA20000",
               C.OL_HEADER_ROW, C.OL_FIRST_DATA_ROW)
    tr = _load(all_in_one_id, C.TAB_TRANSFERS, "A1:P500", 1, 2)

    # --- indexes -----------------------------------------------------------
    dd_by_spe: Dict[str, list] = {}
    dd_by_cust: Dict[str, list] = {}
    for n, cells in dd.rows:
        spe = dd.get(cells, C.DD_PRODUCTION_LOOKUP)
        if spe:
            dd_by_spe.setdefault(spe, []).append((n, cells))
        for ck in customer_keys(dd.get(cells, C.DD_CUSTOMER)):
            dd_by_cust.setdefault(ck, []).append((n, cells))

    ol_by_spm: Dict[str, tuple] = {}
    ol_by_cust: Dict[str, list] = {}
    for _n, cells in ol.rows:
        spe = ol.get(cells, C.OL_SPE)
        rec = (ol.get(cells, C.OL_CUSTOMER), ol.get(cells, C.OL_REP), spe)
        k = spm_key(ol.get(cells, C.OL_SPM))
        if k:
            ol_by_spm.setdefault(k, rec)
        for ck in customer_keys(rec[0]):
            ol_by_cust.setdefault(ck, []).append(rec)

    dd_roster = sorted({dd.get(c, C.DD_REP) for _n, c in dd.rows if dd.get(c, C.DD_REP)})
    roster = sorted(set(_commission_roster(workbook_id)) | set(dd_roster)) or dd_roster

    out: Dict[str, List[Finding]] = {k: [] for k in
                                     (APPLY_TRANSFER, APPLY_BONUS, PENDING, REVIEW)}
    seen: set = set()

    for n, cells in tr.rows:
        status = tr.get(cells, C.TR_STATUS).upper()
        to_rep = tr.get(cells, C.TR_TO_REP)
        from_rep = tr.get(cells, C.TR_FROM_REP)
        customer = tr.get(cells, C.TR_CUSTOMER)
        raw_spm = tr.get(cells, C.TR_SPM)

        if status == "PAID":
            continue
        if C.TEST_MARKER in to_rep.lower() or C.TEST_MARKER in from_rep.lower():
            continue
        if not (to_rep or from_rep or customer):
            continue

        is_bonus = C.BONUS_MARKER in nrm(to_rep)

        # The same sale gets submitted twice fairly often. Key on the order,
        # falling back to the customer when there is no SPM.
        dedupe = (spm_key(raw_spm), customer_key(customer), nrm(from_rep), is_bonus)
        if dedupe in seen:
            out[REVIEW].append(Finding(REVIEW, n, customer, from_rep, to_rep,
                                       note="duplicate submission — already counted above"))
            continue
        seen.add(dedupe)

        # --- resolve the order to DD rows ---------------------------------
        dd_hits: List[tuple] = []
        how = ""
        key = spm_key(raw_spm)
        ol_rec = ol_by_spm.get(key) if key else None
        if ol_rec and ol_rec[2]:
            dd_hits = dd_by_spe.get(ol_rec[2], [])
            how = "SPM"

        name_hits = _first_hit(dd_by_cust, customer_keys(customer))
        if not dd_hits and name_hits:
            dd_hits, how = name_hits, "customer name"
        elif not dd_hits and not ol_rec:
            for rec in _first_hit(ol_by_cust, customer_keys(customer)):
                if rec[2] and rec[2] in dd_by_spe:
                    dd_hits, how = dd_by_spe[rec[2]], "customer name via order log"
                    break

        # The SPM and the typed customer name pointing at different people is
        # a data-entry error, not something to resolve by picking one.
        if ol_rec and customer_keys(customer) and \
                not (customer_keys(ol_rec[0]) & customer_keys(customer)):
            out[REVIEW].append(Finding(
                REVIEW, n, customer, from_rep, to_rep,
                note=f"SPM {raw_spm} is {ol_rec[0]!r} on the order log, not "
                     f"{customer!r} — check which is right"))
            continue

        if not dd_hits:
            out[PENDING].append(Finding(
                PENDING, n, customer,
                "" if is_bonus else from_rep,
                from_rep if is_bonus else to_rep,
                amount=_bonus_amount(to_rep) if is_bonus else "",
                note="not on this week's DD yet" if (ol_rec or name_hits or key)
                     else "no SPM and no order-log/DD match"))
            continue

        dd_rows = [r for r, _c in dd_hits]
        dd_rep = dd.get(dd_hits[0][1], C.DD_REP)

        if is_bonus:
            # `from_rep` is the earner. Eve's feed already matches, but resolve
            # against the DD roster so a typo still gets caught.
            who, cands = match_person(from_rep, roster)
            if not who:
                out[REVIEW].append(Finding(
                    REVIEW, n, customer, "", from_rep, dd_rows=dd_rows,
                    note=f"bonus earner {from_rep!r} is not on the roster"
                         + (f" — closest: {cands}" if cands else "")))
                continue
            out[APPLY_BONUS].append(Finding(
                APPLY_BONUS, n, customer, "", who, dd_rows=dd_rows, dd_rep=dd_rep,
                amount=_bonus_amount(to_rep), note=f"matched by {how}"))
            continue

        # A real transfer: confirm the DD really does sit under `from_rep`.
        src, src_cands = match_person(from_rep, [dd_rep] if dd_rep else [])
        dst, dst_cands = match_person(to_rep, dd_roster)
        if not src:
            out[REVIEW].append(Finding(
                REVIEW, n, customer, from_rep, to_rep, dd_rows=dd_rows, dd_rep=dd_rep,
                note=f"DD has this sale under {dd_rep!r}, not {from_rep!r}"))
            continue
        if not dst:
            out[REVIEW].append(Finding(
                REVIEW, n, customer, from_rep, to_rep, dd_rows=dd_rows, dd_rep=dd_rep,
                note=f"receiving rep {to_rep!r} is not on the DD"
                     + (f" — closest: {dst_cands}" if dst_cands else "")))
            continue
        out[APPLY_TRANSFER].append(Finding(
            APPLY_TRANSFER, n, customer, dd_rep, dst, dd_rows=dd_rows, dd_rep=dd_rep,
            note=f"matched by {how}"))

    return out


def _first_hit(index: Dict[str, list], keys) -> list:
    """First non-empty bucket among `keys` — the customer-name indexes are
    filed under several candidate keys per name (see names.customer_keys)."""
    for k in keys:
        if index.get(k):
            return index[k]
    return []


def _commission_roster(workbook_id: str) -> List[str]:
    """Rep names as tab 3 spells them — the spelling that has to go into 4b.

    A missing/renamed tab is not worth failing the whole reconcile over; the
    caller falls back to the DD roster."""
    try:
        from automations.recruiting_report.fill import open_by_key
        col = open_by_key(workbook_id).worksheet(C.TAB_REPS).col_values(2)
    except Exception:
        return []
    return [v.strip() for v in col[3:] if str(v).strip()]


def _bonus_amount(marker: str) -> str:
    """"$20 bonus" -> "$20". Anything unparseable comes back blank so the
    report shows it as a gap rather than inventing a number."""
    import re
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", str(marker or ""))
    return f"${m.group(1)}" if m else ""


def report(found: Dict[str, List[Finding]]) -> str:
    lines = []
    titles = [(APPLY_TRANSFER, "TRANSFERS to apply (rewrite REP.Full Name on the DD)"),
              (APPLY_BONUS, "BONUSES to add (tab 4b)"),
              (REVIEW, "NEEDS YOUR EYES"),
              (PENDING, "PENDING — not activated yet, left alone")]
    for kind, title in titles:
        items = found.get(kind, [])
        lines.append(f"\n{title}  ({len(items)})")
        if not items:
            lines.append("  —")
        for f in items:
            lines.append(f.line())
    return "\n".join(lines)


def _col_letter(idx0: int) -> str:
    """0-based column index -> A1 letter."""
    n, out = idx0 + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def apply(found: Dict[str, List[Finding]],
          workbook_id: str = C.WORKBOOK_ID) -> Dict[str, int]:
    """Write the confidently-resolved findings. REVIEW/PENDING are left alone.

    Two writes, both to mapped cells only (never a clear, never a delete):
      * each transfer overwrites `REP.Full Name` on its DD rows;
      * each bonus appends one line to the 4b block.

    The transfers tab itself is NOT touched — marking rows PAID stays JD's
    call, and the form responses are somebody else's data."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(workbook_id)
    done = {"transfers": 0, "bonuses": 0}

    transfers = found.get(APPLY_TRANSFER, [])
    if transfers:
        dd_ws = sh.worksheet(C.TAB_DD)
        header = [str(c).strip() for c in dd_ws.row_values(C.DD_HEADER_ROW)]
        letter = _col_letter(header_index(header, C.DD_REP))
        payload = [{"range": f"{letter}{r}", "values": [[f.to_rep]]}
                   for f in transfers for r in f.dd_rows]
        dd_ws.batch_update(payload, value_input_option="USER_ENTERED")
        done["transfers"] = len(payload)

    bonuses = found.get(APPLY_BONUS, [])
    if bonuses:
        cf_ws = sh.worksheet(C.TAB_CONFIRM)
        existing = cf_ws.col_values(12)                    # column L = Rep
        start = max(len(existing) + 1, 5)                  # 4b data begins at row 5
        rows = [[f.to_rep, f"ATT Sales Transfer bonus — {f.customer}".strip(),
                 "", "Bonus", f.amount] for f in bonuses]
        cf_ws.update(f"L{start}:P{start + len(rows) - 1}", rows,
                     value_input_option="USER_ENTERED")
        done["bonuses"] = len(rows)

    return done


def clear_paid(all_in_one_id: str = C.ALL_IN_ONE_ID,
               write: bool = False) -> dict:
    """Empty the cells of every PAID row on the transfers form.

    Cells, not rows: deleting rows would shift everything below and break any
    row number already reported. A snapshot goes to output/ before any write."""
    import datetime as dt
    import json
    from pathlib import Path

    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(all_in_one_id).worksheet(C.TAB_TRANSFERS)
    values = ws.get("A1:P500")
    grid = _Grid(values, 1, 2)
    status_col = grid.col(C.TR_STATUS)

    paid = [(n, cells) for n, cells in grid.rows
            if cells[status_col].strip().upper() == "PAID"]
    if not paid or not write:
        return {"paid": len(paid), "cleared": 0,
                "rows": [n for n, _c in paid], "snapshot": None}

    out_dir = Path(__file__).resolve().parents[2] / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = out_dir / f"transfers-cleared-{dt.date.today().isoformat()}.json"
    snap.write_text(json.dumps(
        {"taken": dt.datetime.now().isoformat(timespec="seconds"),
         "header": grid.header,
         "rows": [{"row": n, "values": cells} for n, cells in paid]}, indent=2),
        encoding="utf-8")

    last = _col_letter(grid.width - 1)
    ws.batch_clear([f"A{n}:{last}{n}" for n, _c in paid])
    return {"paid": len(paid), "cleared": len(paid),
            "rows": [n for n, _c in paid], "snapshot": snap}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workbook", default=C.WORKBOOK_ID)
    ap.add_argument("--write", action="store_true",
                    help="apply the transfers/bonuses (default is a dry run)")
    ap.add_argument("--clear-paid", action="store_true",
                    help="empty the cells of rows already marked PAID")
    args = ap.parse_args(argv)

    if args.clear_paid:
        res = clear_paid(write=args.write)
        print(f"\nPAID rows on the form: {res['paid']}  {res['rows'][:12]}"
              + (" …" if len(res["rows"]) > 12 else ""))
        if not args.write:
            print("\n(dry run — nothing cleared; add --write to empty them)")
            return 0
        print(f"Emptied {res['cleared']} row(s); rows left in place so nothing "
              f"below shifts.")
        print(f"Snapshot: {res['snapshot']}")
        return 0

    found = analyze(workbook_id=args.workbook)
    print(report(found))
    if not args.write:
        print("\n(dry run — nothing written; add --write to apply)")
        return 0

    todo = len(found[APPLY_TRANSFER]) + len(found[APPLY_BONUS])
    if not todo:
        print("\nNothing to apply.")
        return 0
    done = apply(found, workbook_id=args.workbook)
    print(f"\nWrote {done['transfers']} DD rep cell(s) and "
          f"{done['bonuses']} bonus line(s).")
    if found[REVIEW]:
        print(f"Left {len(found[REVIEW])} row(s) for you under NEEDS YOUR EYES.")
    print("Transfers tab untouched — mark rows PAID yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
