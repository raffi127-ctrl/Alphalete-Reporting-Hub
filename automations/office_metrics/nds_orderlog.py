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

import csv as _csv
import io as _io

from automations.alphalete_org_report.opt_nds import _norm_owner
from automations.shared.tableau_patchright import tableau_session
from automations.total_knocks.render import _draw

# NDS ORDER LOG — pull via the DIRECT .csv export (like att_order_log), which needs
# no crosstab worksheet name and returns one comma-row per order. :refresh=yes so
# it isn't a stale extract snapshot.
ORDERLOG_CSV_URL = ("https://us-east-1.online.tableau.com/t/sci/views/"
                    "NDS-SNRES-ATT-OOFWorkbook/ORDERLOG.csv?:refresh=yes")

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
        r = page.context.request.get(ORDERLOG_CSV_URL, timeout=300_000)
        body = r.body() or b""
        if verbose:
            print(f"[nds_orderlog] csv status={r.status} bytes={len(body):,}",
                  flush=True)
        if r.status != 200 or len(body) < 500:
            raise RuntimeError(f"NDS ORDER LOG export failed: status={r.status} "
                               f"bytes={len(body)}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(body)
    return out_path


def _read_csv(path: Path) -> list[list[str]]:
    """Parse the .csv export — comma-delimited; try utf-8-sig then utf-16."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            if "\t" in text.split("\n", 1)[0] and "," not in text.split("\n", 1)[0]:
                return [r for r in _csv.reader(_io.StringIO(text), delimiter="\t")]
            return [r for r in _csv.reader(_io.StringIO(text))]
        except (UnicodeDecodeError, UnicodeError):
            continue
    return []


def load(path: Path, owner: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows-for-this-owner). Owner matched via _norm_owner on the
    'Owner & Office' column (found by header name, never a fixed index)."""
    rows = _read_csv(path)
    if not rows:
        return [], []
    header = rows[0]
    idx = {_norm_h(h): i for i, h in enumerate(header)}
    owner_col = next((idx[k] for k in idx if k.startswith("owner")), 0)
    want = _norm_owner(owner)
    mine = [r for r in rows[1:]
            if len(r) > owner_col and _norm_owner(r[owner_col]) == want]
    return header, mine


def _find(header: list[str], *candidates: str) -> int | None:
    """Column index by name (exact first, then substring). Never a fixed index."""
    norm = [_norm_h(h) for h in header]
    for cand in candidates:                      # exact
        c = _norm_h(cand)
        if c in norm:
            return norm.index(c)
    for cand in candidates:                      # substring
        c = _norm_h(cand)
        for i, h in enumerate(norm):
            if c in h:
                return i
    return None


def _cell(row: list[str], i: int | None) -> str:
    return (row[i].strip() if i is not None and i < len(row) and row[i] else "")


def _wireless(rows, header):
    pt = _find(header, "product type (broken out)", "product type")
    if pt is None:
        return rows
    return [r for r in rows if "wireless" in _cell(r, pt).lower()]


def _title(label: str, target: dt.date) -> str:
    core = label.split(" ", 1)[1] if " " in label else label
    return f"{core.upper()} — {target.strftime('%b')} {target.day}, {target.year}"


def _render_order_log(owner, header, rows, target, out_dir):
    rep_i = _find(header, "rep")
    st_i = _find(header, "dtr status", "order status", "status")
    reps: dict[str, dict[str, int]] = {}
    statuses: list[str] = []
    for r in rows:
        rep = _cell(r, rep_i) or "—"
        st = _cell(r, st_i) or "—"
        if st not in statuses:
            statuses.append(st)
        reps.setdefault(rep, {})
        reps[rep][st] = reps[rep].get(st, 0) + 1
    statuses = sorted(statuses)
    header_row = ["Rep", *statuses, "Total"]
    body = []
    for rep in sorted(reps, key=lambda k: -sum(reps[k].values())):
        counts = reps[rep]
        body.append([rep, *[str(counts.get(s, "")) for s in statuses],
                     str(sum(counts.values()))])
    out = out_dir / f"nds_order_log_{target.isoformat()}.png"
    return _draw(header_row, body, _title("📋 Order Log", target), THEME_SLATE,
                 out, name_col=0)


def _render_cancels(owner, header, rows, target, out_dir):
    st_i = _find(header, "dtr status", "order status", "status")
    rep_i = _find(header, "rep")
    cust_i = _find(header, "customer name")
    date_i = _find(header, "sp.order date", "order date", "status date")
    canceled = [r for r in rows if "cancel" in _cell(r, st_i).lower()]
    body = [[_cell(r, rep_i) or "—", _cell(r, cust_i) or "—",
             _cell(r, date_i) or "—", _cell(r, st_i) or "—"] for r in canceled]
    out = out_dir / f"nds_cancels_{target.isoformat()}.png"
    return _draw(["Rep", "Customer", "Order Date", "Status"], body,
                 _title("🚫 Canceled Orders", target), THEME_SLATE, out, name_col=0), \
        len(canceled)


def _render_6plus(owner, header, rows, target, out_dir):
    date_i = _find(header, "cl.dd date", "dd date", "dtr active date")
    rep_i = _find(header, "rep")
    cust_i = _find(header, "customer name")
    cutoff = target + dt.timedelta(days=6)
    out_rows = []
    for r in rows:
        d = _parse_date(_cell(r, date_i))
        if d and d >= cutoff:
            out_rows.append([_cell(r, rep_i) or "—", _cell(r, cust_i) or "—",
                             d.isoformat()])
    out_rows.sort(key=lambda x: x[2])
    out = out_dir / f"nds_sched_6plus_{target.isoformat()}.png"
    return _draw(["Rep", "Customer", "Install/DD Date"], out_rows,
                 _title("📅 Sales Scheduled 6+ Days Out", target), THEME_SLATE,
                 out, name_col=0), len(out_rows)


def _parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def run(owner: str, board: str, *, target: dt.date | None = None,
        dry_run: bool = False, out_dir: Path | None = None,
        verbose: bool = False) -> int:
    target = target or dt.date.today()
    out_dir = out_dir or (Path(__file__).resolve().parents[2] / "output"
                          / "nds_orderlog")
    out_dir.mkdir(parents=True, exist_ok=True)
    label, emoji = BOARDS[board]
    csv_path = pull(verbose=verbose)
    header, rows = load(csv_path, owner)
    rows = _wireless(rows, header)
    print(f"[nds_orderlog:{board}] {owner} — {len(rows)} wireless order row(s)",
          flush=True)
    # Diagnostics that help confirm the cancel/date fields without another pull.
    st_i = _find(header, "dtr status", "order status", "status")
    if st_i is not None:
        vals = sorted({_cell(r, st_i) for r in rows if _cell(r, st_i)})
        print(f"[nds_orderlog:{board}] DTR/Order status values: {vals}", flush=True)

    if board == "order_log":
        img, count = _render_order_log(owner, header, rows, target, out_dir), len(rows)
    elif board == "cancels":
        img, count = _render_cancels(owner, header, rows, target, out_dir)
    else:  # sched_6plus
        img, count = _render_6plus(owner, header, rows, target, out_dir)
    print(f"[nds_orderlog:{board}] rendered {count} row(s) -> {img}", flush=True)

    # Skip-empty: Cancels / 6+ Days post NOTHING on a zero-row day (a wireless
    # office often has no cancels and never has installs scheduled 6+ days out).
    # An empty board is worse than no board. Order Log always posts (his volume).
    if board in ("cancels", "sched_6plus") and count == 0:
        print(f"[nds_orderlog:{board}] 0 rows — skipping (no blank board).",
              flush=True)
        return 0

    if dry_run:
        print(f"[nds_orderlog:{board}] --dry-run — rendered only, NO post.",
              flush=True)
        return 0
    from automations.shared.slack_metrics_post import post_reply_with_image
    comment = f"{label} — {target.strftime('%b')} {target.day}"
    resp = post_reply_with_image(Path(img), comment=comment, react_emoji=emoji)
    print(f"[nds_orderlog:{board}] {'✅ Posted' if resp.get('ok') else '⚠ '+str(resp)}",
          flush=True)
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
