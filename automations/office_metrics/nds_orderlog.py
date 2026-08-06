"""NDS Order Log family — Order Log, Canceled Orders, and Sales 6+ Days Out for an
NDS owner, all from ONE pull of the NDS-SN (RES-ATT-OOF) ORDER LOG view.

The D2D order-log boards pull the ATT-D2D ORDER LOG ("A.Order Log" worksheet) and
filter Python-side (canceled_orders -> canceled+NEW INTERNET; 6-days -> scheduled
installs). NDS owners aren't in that book; their orders live in the NDS-SN ORDER
LOG. This pulls that view once, slices to one owner + WIRELESS, and renders the
board asked for (--board order_log | cancels | sched_6plus).

  python -m automations.office_metrics.nds_orderlog --owner "Isaiah Revelle" --board order_log --dry-run

First dry-run is DIAGNOSTIC: it prints the crosstab header + the owner's row count
so the exact column names drive the render (never fixed indices).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.alphalete_org_report.opt_nds import _read_tab_csv, _norm_owner
from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
from automations.total_knocks.render import _draw

# NDS ORDER LOG — default view (no guid needed), same as NDSDailyTracker is wired.
ORDERLOG_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "NDS-SNRES-ATT-OOFWorkbook/ORDERLOG")
# Crosstab worksheet — the D2D ORDER LOG uses "A.Order Log"; confirmed/adjusted by
# the diagnostic dry-run below if the NDS book names it differently.
WORKSHEET = "A.Order Log"

THEME_SLATE = {"title_bg": (51, 65, 85), "header_bg": (30, 41, 59),
               "stripe": (236, 240, 245)}

BOARDS = {
    "order_log":   ("📋 Order Log", "clipboard"),
    "cancels":     ("🚫 Canceled Orders", "no_entry_sign"),
    "sched_6plus": ("📅 Sales Scheduled 6+ Days Out", "date"),
}


def _norm_h(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def pull(out_path: Path | None = None, verbose: bool = False) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "nds_orderlog.csv"
    with tableau_session(verbose=verbose) as page:
        download_crosstab_patchright(ORDERLOG_URL, WORKSHEET, out_path,
                                     verbose=verbose, page=page)
    return out_path


def load(path: Path, owner: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows-for-this-owner). Owner matched via _norm_owner on the
    'Owner & Office' column (found by header name, never a fixed index)."""
    rows = _read_tab_csv(path)
    if not rows:
        return [], []
    header = rows[0]
    idx = {_norm_h(h): i for i, h in enumerate(header)}
    owner_col = next((idx[k] for k in idx if k.startswith("owner")), 0)
    want = _norm_owner(owner)
    mine = [r for r in rows[1:]
            if len(r) > owner_col and _norm_owner(r[owner_col]) == want]
    return header, mine


def run(owner: str, board: str, *, dry_run: bool = False,
        verbose: bool = False) -> int:
    label, emoji = BOARDS[board]
    csv_path = pull(verbose=verbose)
    header, rows = load(csv_path, owner)
    print(f"[nds_orderlog:{board}] {owner} — {len(rows)} order row(s)", flush=True)
    # DIAGNOSTIC: surface the real columns so the render maps by name next pass.
    print(f"[nds_orderlog:{board}] columns: {header}", flush=True)
    if rows:
        print(f"[nds_orderlog:{board}] sample row: {rows[0]}", flush=True)

    # Render is intentionally minimal until the diagnostic confirms columns; this
    # keeps the first dry-run safe (no post) while revealing the structure.
    print(f"[nds_orderlog:{board}] (diagnostic pass — render wired after columns "
          f"confirmed)", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics.nds_orderlog")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--board", choices=list(BOARDS), default="order_log")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    return run(args.owner, args.board, dry_run=not args.live, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
