"""PROBE (Eve 2026-11-10, Colten in #l10-alphalete): "Pending Valid Payment"
never shows on his Order Log. Today's three letter files (11/1-11/9 orders,
243 lines) carry zero PVP rows. This pulls the same NDS ORDERLOG export with
a 60-day window and prints, for one owner, every status-like column's values
and where any "valid payment" text lives (which column, how old the order).
Writes nothing, posts nothing.

    python -m automations.office_metrics.nds_orderlog_status_probe --owner "Colten Wright"
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys

from automations.office_metrics import nds_orderlog as n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="Colten Wright")
    ap.add_argument("--days", type=int, default=n.ACT_LOOKBACK_DAYS)
    a = ap.parse_args(argv)

    path = n.pull(verbose=True, days=a.days)
    all_rows = n._read_csv(path)
    header, rows = n.load(path, a.owner)
    print("[probe] export %s: %d rows total, %d for %s"
          % (path.name, max(len(all_rows) - 1, 0), len(rows), a.owner), flush=True)
    print("[probe] columns: %s" % header, flush=True)

    # Every column whose name smells like a status / payment field.
    keys = ("status", "payment", "pay", "credit", "hold", "reason")
    cols = [i for i, h in enumerate(header) if any(k in h.lower() for k in keys)]
    lines = n._one_row_per_line(header, rows)
    for i in cols:
        cnt = collections.Counter(n._cell(r, i) or "(blank)" for r in lines)
        print("[probe] %-30s %s" % (header[i], dict(cnt.most_common())), flush=True)

    # Where does "valid payment" appear — any column, this owner AND everyone.
    od = n._find(header, "sp.order date", "order date")
    rep = n._find(header, "rep")
    spm = n._find(header, "sp.spm number", "spm number", "spm")
    for label, src in (("owner", rows), ("ALL OWNERS", all_rows[1:])):
        hits = collections.Counter()
        dates = []
        for r in src:
            for i, v in enumerate(r):
                if "valid payment" in (v or "").lower():
                    hits[header[i] if i < len(header) else i] += 1
                    dates.append(n._cell(r, od))
        print("[probe] 'valid payment' in %s: %s; order dates %s..%s"
              % (label, dict(hits), min(dates) if dates else "-",
                 max(dates) if dates else "-"), flush=True)
    seen = 0
    for r in rows:
        if any("valid payment" in (v or "").lower() for v in r) and seen < 25:
            seen += 1
            print("[probe]   %s | %s | %s | %s" % (
                n._cell(r, od), n._cell(r, rep), n._cell(r, spm),
                " / ".join("%s=%s" % (header[i], n._cell(r, i)) for i in cols)),
                flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
