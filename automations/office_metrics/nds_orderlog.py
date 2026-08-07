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
# no crosstab worksheet name and returns one comma-row per order.
#
# The view ships with its Start Date / End Date parameters PINNED to whatever week
# was last saved (found 2026-08-06 stuck on 6/29-7/5, five weeks stale — while the
# data source itself ran current through today). So we ALWAYS pass a current
# rolling window (last week's Sunday .. this week's Saturday) on the "Order Date"
# range, matching the two Sun-Sat weeks the house rep-activations board buckets by.
# Without this every order-log board (log/cancels/disconnects) reads an old week.
ORDERLOG_CSV_BASE = ("https://us-east-1.online.tableau.com/t/sci/views/"
                     "NDS-SNRES-ATT-OOFWorkbook/ORDERLOG.csv")


def _orderlog_url(start: dt.date, end: dt.date) -> str:
    """CSV export URL with the Order-Date range parameters set (ISO dates)."""
    return (f"{ORDERLOG_CSV_BASE}?Start%20Date={start.isoformat()}"
            f"&End%20Date={end.isoformat()}"
            f"&Search%20Date%20Range=Order%20Date&:refresh=yes")

THEME_SLATE = {"title_bg": (51, 65, 85), "header_bg": (30, 41, 59),
               "stripe": (236, 240, 245)}

BOARDS = {
    # The standard combined board every (non-NDS) office posts: two weekly tables
    # (Rep · Posted · Pending · Total · Canceled/Disconnected), rendered by the
    # SAME house function so Isaiah's looks identical to Raf's. Replaces the old
    # custom slate "Order Log" table + green "Rep Activations" table.
    "rep_summary": ("📋 Order Log / 🆕 Rep Activations", "clipboard"),
    "order_log":   ("📋 Order Log", "clipboard"),
    "cancels":     ("🚫 Canceled Orders", "no_entry_sign"),
    "disconnects": ("❎ Disconnected Orders", "negative_squared_cross_mark"),
}
# Board -> the status keyword its rows must contain (order status values seen live:
# Canceled / Confirmed / Disconnected / Posted / Shipped). 6+ days out was dropped:
# wireless orders ship immediately, so there's never a scheduled-out install
# (Raf 2026-08-06: "he won't have 6+ days out").
_STATUS_KEYWORD = {"cancels": "cancel", "disconnects": "disconnect"}


def _norm_h(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def pull(out_path: Path | None = None, verbose: bool = False) -> Path:
    """Download the NDS ORDER LOG .csv export — ONCE PER DAY, shared by all three
    boards (order_log/cancels/disconnects each run as a separate subprocess). The
    first to pull writes a dated cache; the others reuse it — so the export runs
    once, not three times (which was overloading the session and failing). Retries
    the export a few times to ride out a transient non-200/empty response."""
    from automations.rep_activations.aggregate import week_bounds
    last_start, _last_end, _this_start, this_end = week_bounds(dt.date.today())
    url = _orderlog_url(last_start, this_end)
    today = dt.date.today().isoformat()
    cache = Path(tempfile.gettempdir()) / f"nds_orderlog_{today}.csv"
    if cache.exists() and cache.stat().st_size > 500:
        if verbose:
            print(f"[nds_orderlog] reusing today's cached export "
                  f"({cache.stat().st_size:,} bytes)", flush=True)
        return cache
    last = ""
    for attempt in (1, 2, 3):
        with tableau_session(verbose=verbose) as page:
            if verbose:
                print(f"[nds_orderlog] window {last_start}..{this_end}", flush=True)
            r = page.context.request.get(url, timeout=300_000)
            body = r.body() or b""
            if verbose:
                print(f"[nds_orderlog] csv status={r.status} bytes={len(body):,} "
                      f"(try {attempt}/3)", flush=True)
            if r.status == 200 and len(body) >= 500:
                cache.write_bytes(body)
                return cache
            last = f"status={r.status} bytes={len(body)}"
    raise RuntimeError(f"NDS ORDER LOG export failed after 3 tries: {last}")


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


def _house_status(dtr: str) -> str:
    """Map an NDS DTR Status onto the house rep_activations vocabulary.

    House build_week_tables buckets: POSTED_STATUSES={"active"},
    CANCEL_STATUSES={cancelled,canceled,disconnected}, everything-else-nonblank =
    pending. NDS uses "Posted" for a posted sale and keeps Shipped/Confirmed as
    live pipeline, so: Posted->active, Canceled/Disconnected pass through,
    Shipped/Confirmed/etc -> their own lowercased value (falls into pending)."""
    s = (dtr or "").strip().lower()
    if s == "posted":
        return "active"
    if s in ("canceled", "cancelled"):
        return "canceled"
    if s == "disconnected":
        return "disconnected"
    return s or "pending"


def _render_rep_summary(owner, header, rows, target, out_dir):
    """The standard combined 'Order Log / Rep Activations' board, rendered by the
    house rep_activations pipeline (build_week_tables + render) so it's identical
    to every other office. `rows` are this owner's WIRELESS order rows. Posted is
    bucketed by Order Date (when the rep sold it), matching the house model."""
    import pandas as pd
    from automations.rep_activations.aggregate import build_week_tables
    from automations.rep_activations.render import render as _house_render
    rep_i = _find(header, "rep")
    st_i = _find(header, "dtr status", "order status", "status")
    odate_i = _find(header, "sp.order date", "order date")
    sdate_i = _find(header, "status date")
    df = pd.DataFrame([{
        "Rep": _cell(r, rep_i),
        "Status": _house_status(_cell(r, st_i)),
        "Activation Date": _cell(r, odate_i),   # Order Date = when rep sold it
        "Install Date": _cell(r, sdate_i),      # fallback bucket for cancels
    } for r in rows])
    summary = build_week_tables(df, target)
    out = out_dir / f"nds_rep_activations_{target.isoformat()}.png"
    return _house_render(summary, out)


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


def _render_status_orders(owner, header, rows, target, out_dir, keyword, label, slug):
    """Order rows whose status contains `keyword` (cancels -> 'cancel',
    disconnects -> 'disconnect'), rendered with the SAME house layout every other
    office's Canceled Orders board uses (canceled_orders.render) so it looks
    identical — just fed NDS order data mapped onto its column keys."""
    from automations.canceled_orders.render import render as _house_render
    st_i = _find(header, "dtr status", "order status", "status")
    rep_i = _find(header, "rep")
    cust_i = _find(header, "customer name")
    odate_i = _find(header, "sp.order date", "order date")
    sdate_i = _find(header, "status date")
    spm_i = _find(header, "sp.spm number", "spm number", "spm")
    phone_i = _find(header, "customer phone", "phone")
    hits = [r for r in rows if keyword in _cell(r, st_i).lower()]
    house_rows = [{
        "Rep": _cell(r, rep_i), "Customer Name": _cell(r, cust_i),
        "SPM #": _cell(r, spm_i), "Order Date": _cell(r, odate_i),
        "Status Date": _cell(r, sdate_i), "Customer Phone": _cell(r, phone_i),
    } for r in hits]
    out = out_dir / f"nds_{slug}_{target.isoformat()}.png"
    core = label.split(" ", 1)[1] if " " in label else label
    return _house_render(house_rows, out, title=f"{owner} — {core}"), len(hits)


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

    if board == "rep_summary":
        img, count = _render_rep_summary(owner, header, rows, target, out_dir), len(rows)
    elif board == "order_log":
        img, count = _render_order_log(owner, header, rows, target, out_dir), len(rows)
    else:  # cancels or disconnects — status-keyword filtered order lists
        img, count = _render_status_orders(owner, header, rows, target, out_dir,
                                           _STATUS_KEYWORD[board], label, board)
    print(f"[nds_orderlog:{board}] rendered {count} row(s) -> {img}", flush=True)

    # No rows on Cancels / Disconnects: post a "No new ... orders" one-liner (like
    # every other metric's no-data notice), NOT a blank image and NOT skipped —
    # so the reply matches the header line. Order Log always has his volume.
    empty_note = None
    if board in ("cancels", "disconnects") and count == 0:
        noun = "canceled" if board == "cancels" else "disconnected"
        empty_note = (f"{label} — {target.strftime('%b')} {target.day} "
                      f"— No new {noun} orders")

    if dry_run:
        print(f"[nds_orderlog:{board}] --dry-run — "
              f"{'would post: ' + empty_note if empty_note else 'rendered only'} "
              f"— NO post.", flush=True)
        return 0

    if empty_note:
        from automations.shared.slack_metrics_post import post_reply_text_only
        resp = post_reply_text_only(empty_note, react_emoji=emoji)
    else:
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
