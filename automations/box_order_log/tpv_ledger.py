"""A permanent record of every deal we have EVER seen reach TPV.

Why this exists (2026-08-28)
----------------------------
Tableau's export drops a deal's TPV transition row weeks after the fact. The
sale gate reads history, so a deal that passed TPV and later cancelled comes
back looking like it was "cancelled before it ever reached TPV" and is thrown
out of the workbook and the payout tables. Found chasing El Meson Doña Tere
(ctr 278285): recorded TPV Passed on 8/14, and by 8/23 its only rows were
`Draft` and `Cancelled by Broker`.

`sheet.tpv_seen_keys()` already answers this from the live board, but its
memory is only as long as the board's SIX-WEEK window: a deal erased before it
aged off is unrecoverable there, and every week that passes forgets more.

The daily crosstabs are the longer record. Every run writes its raw pull to
`output/box_order_log_<date>.csv` and nothing ever deletes them, so the archive
is a day-by-day photograph of what Tableau said each morning going back to the
report's first run. This module walks that archive once, records every sale key
that was EVER seen at TPV or beyond — with the date we first saw it and the
level it was at — and keeps the result in a small JSON ledger.

The ledger only ever GROWS. Rebuilding it re-reads the archive and unions the
result with what's already there, so a pruned archive can never shrink it. It
is evidence, not derived state: nothing regenerates it if it's lost, which is
exactly why it is kept on disk rather than recomputed each run.

    # build/refresh it from the archive, print what changed
    python -m automations.box_order_log.tpv_ledger --build

    # what does it know about one deal?
    python -m automations.box_order_log.tpv_ledger --show meson
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from . import clean

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
LEDGER_PATH = OUTPUT_DIR / "box_tpv_ledger.json"

# Where a long --erased list goes so the mini can actually read it. The queue
# sheet, not the Vantura board: this is diagnostics, and the board is Carlos's.
QUEUE_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
ERASED_TAB = "Box TPV Erased"

# box_order_log_2026-08-23.csv  and  box_order_log_all_2026-08-23.csv
_CSV_GLOB = "box_order_log*.csv"
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _file_date(path: Path) -> Optional[dt.date]:
    m = _DATE_RE.search(path.name)
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _key_str(key) -> str:
    a, b = clean.norm_key(key)
    return "{}|{}".format(a, b)


def row_reached_tpv(row: Dict[str, str]) -> Optional[str]:
    """The level this RAW export row proves, or None if it proves nothing.

    Same bar as the live gate: a SALE_LEVEL, an exempt Incomplete, or the
    "Rejected By Supplier" sub-status (the supplier can only reject what it
    received). Deliberately reads clean's constants rather than copying them.
    """
    status = (row.get("Status") or "").strip()
    sub = (row.get("Contr. Sub-status") or "").strip()
    if status in clean.JUNK_STATUSES:
        return None                      # a Draft never proves anything
    if status in clean.SALE_EXEMPT_STATUSES:
        return status
    lvl = clean.level(status, sub)
    if lvl in clean.SALE_LEVELS:
        return lvl
    if clean._norm_sub(sub) in clean.SUPPLIER_SAW_IT_SUBS:
        return lvl
    return None


def load(path: Path = LEDGER_PATH) -> Dict[str, dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("seen", {})
    except (OSError, ValueError):
        return {}


def keys(path: Path = LEDGER_PATH) -> Set[Tuple[str, str]]:
    """The ledger as sale keys, ready for `clean.collapse(tpv_seen=...)`."""
    out = set()
    for k in load(path):
        a, _, b = k.partition("|")
        out.add((a, b))
    return out


def build(output_dir: Path = OUTPUT_DIR, path: Path = LEDGER_PATH,
          log=print) -> dict:
    """Walk the archived crosstabs and fold what they prove into the ledger."""
    seen = load(path)
    before = len(seen)
    files = sorted(Path(output_dir).glob(_CSV_GLOB), key=lambda p: p.name)
    scanned = skipped = 0

    for csv in files:
        day = _file_date(csv)
        if day is None:
            skipped += 1
            continue
        try:
            rows = clean.read_rows(csv)
        except Exception as exc:                       # a truncated pull, say
            log("  ! skipped {} ({})".format(csv.name, exc))
            skipped += 1
            continue
        scanned += 1
        stamp = day.isoformat()
        for row in rows:
            lvl = row_reached_tpv(row)
            if not lvl:
                continue
            k = _key_str((row.get("Contract ID"), row.get("Account Id")))
            if k == "|":
                continue
            rec = seen.get(k)
            if rec is None:
                seen[k] = {"first_seen": stamp, "last_seen": stamp,
                           "level": lvl,
                           "business": (row.get("Business Name") or "").strip(),
                           "rep": (row.get("Rep Name") or "").strip()}
            else:
                # Keep the EARLIEST proof and the latest sighting; the archive
                # is walked in name order, but a re-run or a back-filled file
                # must not be able to move first_seen forward.
                if stamp < rec.get("first_seen", stamp):
                    rec["first_seen"] = stamp
                if stamp > rec.get("last_seen", ""):
                    rec["last_seen"] = stamp

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"built": dt.datetime.now().isoformat(timespec="seconds"),
                   "files_scanned": scanned, "seen": seen}, fh, indent=1)
    tmp.replace(path)                                  # atomic; never a torn ledger

    log("  TPV ledger: {} crosstab(s) scanned, {} skipped · {} keys "
        "({} new this build)".format(scanned, skipped, len(seen),
                                     len(seen) - before))
    return {"files": scanned, "skipped": skipped, "keys": len(seen),
            "added": len(seen) - before}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", action="store_true",
                    help="scan the archived crosstabs and refresh the ledger")
    ap.add_argument("--show", metavar="TEXT",
                    help="print ledger entries whose business name, contract "
                         "or account contains TEXT")
    ap.add_argument("--erased", action="store_true",
                    help="list deals the ledger vouches for that TODAY's "
                         "newest crosstab no longer shows reaching TPV")
    ap.add_argument("--to-tab", metavar="NAME", nargs="?", const=ERASED_TAB,
                    help="also write the --erased list to a tab on the Lucy "
                         "queue sheet. The queue's Result cell truncates to "
                         "~450 chars keeping the tail, so a list this long is "
                         "unreadable from the mini otherwise — same reason "
                         "RP Diag exists.")
    args = ap.parse_args(argv)

    if args.build:
        build()

    if args.show:
        needle = args.show.strip().lower()
        hits = [(k, v) for k, v in load().items()
                if needle in v.get("business", "").lower() or needle in k]
        print("{} ledger entr(ies) matching {!r}".format(len(hits), args.show))
        for k, v in sorted(hits, key=lambda kv: kv[1].get("first_seen", "")):
            print("  {:<16} {:<34} first {} · last {} · {}".format(
                k, v.get("business", "")[:34], v.get("first_seen", "?"),
                v.get("last_seen", "?"), v.get("level", "?")))

    if args.erased:
        files = sorted(OUTPUT_DIR.glob(_CSV_GLOB), key=lambda p: p.name)
        if not files:
            print("no archived crosstabs found", file=sys.stderr)
            return 1
        newest = files[-1]
        rows = clean.read_rows(newest)
        present = {_key_str((r.get("Contract ID"), r.get("Account Id")))
                   for r in rows}
        proves = {_key_str((r.get("Contract ID"), r.get("Account Id")))
                  for r in rows if row_reached_tpv(r)}
        led = load()
        gone = [(k, v) for k, v in led.items()
                if k in present and k not in proves]
        print("newest crosstab: {}".format(newest.name))
        print("{} deal(s) the ledger saw at TPV that this export no longer "
              "shows reaching it:".format(len(gone)))
        for k, v in sorted(gone, key=lambda kv: kv[1].get("first_seen", "")):
            print("  {:<16} {:<34} TPV first seen {} · last seen {}".format(
                k, v.get("business", "")[:34], v.get("first_seen", "?"),
                v.get("last_seen", "?")))

        if args.to_tab:
            _write_tab(args.to_tab, newest.name, gone)
    return 0


def _write_tab(tab_name: str, source: str, gone) -> None:
    """Publish the erased list to a queue-sheet tab. Never fatal."""
    header = ["Contract ID", "Account Id", "Rep", "Business",
              "TPV first seen", "TPV last seen", "Level when seen"]
    rows = [header]
    for k, v in sorted(gone, key=lambda kv: kv[1].get("first_seen", "")):
        contract, _, account = k.partition("|")
        rows.append([contract, account, v.get("rep", ""), v.get("business", ""),
                     v.get("first_seen", ""), v.get("last_seen", ""),
                     v.get("level", "")])
    try:
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(QUEUE_SHEET)
        try:
            ws = sh.worksheet(tab_name)
            ws.clear()
        except Exception:
            ws = sh.add_worksheet(title=tab_name, rows=max(100, len(rows) + 20),
                                  cols=len(header))
        ws.resize(rows=max(100, len(rows) + 20), cols=len(header))
        ws.update(rows, "A1", value_input_option="RAW")
        ws.update([["source: {} · {} deal(s) · built {}".format(
            source, len(gone),
            dt.datetime.now().strftime("%Y-%m-%d %H:%M"))]],
            "A{}".format(len(rows) + 2), value_input_option="RAW")
        print("  wrote {} row(s) to the {!r} tab".format(len(gone), tab_name))
    except Exception as exc:
        # Diagnostics must never take the run down.
        print("  ! could not write the {!r} tab: {}".format(tab_name, exc))


if __name__ == "__main__":
    raise SystemExit(main())
