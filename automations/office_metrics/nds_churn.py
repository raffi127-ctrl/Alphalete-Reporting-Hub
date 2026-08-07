"""NDS Wireless Churn — office-level churn board for an NDS owner.

The office_metrics Wireless Churn board pulls the ATT-D2D per-rep wireless-churn
view, which is EMPTY for an NDS owner (they're not in that workbook). NDS owners'
churn lives in the NDS-SN (RES-ATT-OOF) CHURNRATES view, which publishes, PER
PERIOD (0-30 / 30 / 60 / 90 day) and per office: churn rate, activated wireless
lines, disconnect count, and Tableau's own Red/Yellow/Green health color.

CHURNRATES lays the four periods out as SEPARATE ROWS (col0 = "0-30 Day Churn",
"30 Day Churn", ...), one row per office. So one office contributes four rows —
one per period. We slice to the owner (by the "OWNER[office]" col1 prefix) and
render a small table styled like the house New-Internet-Churn board (orange bar,
churn cell colored by Tableau's own color), posted as the 📊 Wireless Churn reply.

  python -m automations.office_metrics.nds_churn --owner "Isaiah Revelle" --dry-run
  python -m automations.office_metrics.nds_churn --owner "Isaiah Revelle" --live
"""
from __future__ import annotations

import argparse
import csv as _csv
import datetime as dt
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

# opt_nds already owns NDS owner-normalization; reuse it so "Isaiah Revelle"
# matches "ISAIAH REVELLE[legacy specialized acquisitions, inc.]".
from automations.alphalete_org_report.opt_nds import _norm_owner
from automations.shared.tableau_patchright import tableau_session
# House churn palette + font so this board looks like the ones we post for Raf.
from automations.new_internet_churn.render import (
    _font, GREEN, YELLOW, RED, TITLE_BG, TITLE_FG, TEXT, ROW_BG)

# NDS CHURNRATES — pulled via the DIRECT .csv export (like nds_orderlog), which
# needs no crosstab worksheet name. :refresh=yes so it isn't a stale extract.
CHURNRATES_CSV_URL = ("https://us-east-1.online.tableau.com/t/sci/views/"
                      "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES.csv?:refresh=yes")

# col0 label -> (period key, display label). Order = display order (rows).
PERIODS = [
    ("0-30 Day Churn", "0-30", "0–30 Day"),
    ("30 Day Churn",   "30",   "30 Day"),
    ("60 Day Churn",   "60",   "60 Day"),
    ("90 Day Churn",   "90",   "90 Day"),
]
# Tableau's own churn-health color (col2) -> house palette. Authoritative: it's
# the same Red/Yellow/Green Tableau shows, so our cell matches the dashboard.
_TABLEAU_COLOR = {"red": RED, "yellow": YELLOW, "green": GREEN}

# Metric columns after col1 (owner/office): idx2 color, idx3 activated, idx4
# churn rate, idx5 disconnect count. Found by header name, never fixed indices.
POST_LABEL = "📊 Wireless Churn"
POST_EMOJI = "bar_chart"


def pull(out_path: Path | None = None, verbose: bool = False) -> Path:
    """Download the NDS CHURNRATES .csv export (dated cache + retry)."""
    today = dt.date.today().isoformat()
    cache = out_path or (Path(tempfile.gettempdir()) / f"nds_churn_{today}.csv")
    if cache.exists() and cache.stat().st_size > 500:
        if verbose:
            print(f"[nds_churn] reusing cached export "
                  f"({cache.stat().st_size:,} bytes)", flush=True)
        return cache
    last = ""
    for attempt in (1, 2, 3):
        with tableau_session(verbose=verbose) as page:
            r = page.context.request.get(CHURNRATES_CSV_URL, timeout=300_000)
            body = r.body() or b""
            if verbose:
                print(f"[nds_churn] csv status={r.status} bytes={len(body):,} "
                      f"(try {attempt}/3)", flush=True)
            if r.status == 200 and len(body) > 500:
                cache.write_bytes(body)
                return cache
            last = f"status={r.status} bytes={len(body)}"
    raise RuntimeError(f"[nds_churn] CHURNRATES export failed after 3 tries: {last}")


def _col_index(header: list[str], *names: str) -> int:
    """Find a column by (normalized) name; -1 if absent."""
    norm = [" ".join((h or "").strip().lower().split()) for h in header]
    for n in names:
        key = " ".join(n.strip().lower().split())
        for i, h in enumerate(norm):
            if h == key or h.startswith(key):
                return i
    return -1


def parse_office(path: Path, owner: str) -> dict:
    """{period_key: {"color","churn","activated","disc"}} for ONE owner.

    col1 is "OWNER NAME[office, inc.]"; we match the owner-name prefix (before
    "[") so only that owner's one row per period is taken — Isaiah's "legacy
    specialized acquisitions" without pulling in the other "legacy" offices,
    which belong to different owners."""
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    rows = list(_csv.reader(text.splitlines()))
    if not rows:
        return {}
    header = rows[0]
    ci_owner = _col_index(header, "owner & office", "owner")
    ci_color = _col_index(header, "30-60 color churn", "color")
    ci_act = _col_index(header, "activated wireless lines", "activated")
    ci_churn = _col_index(header, "churn rate")
    ci_disc = _col_index(header, "disconnect count", "disconnect")
    if min(ci_owner, ci_act, ci_churn, ci_disc) < 0:
        return {}
    period_by_label = {lbl: key for lbl, key, _ in PERIODS}
    want = _norm_owner(owner)
    out: dict = {}
    for r in rows[1:]:
        if len(r) <= max(ci_owner, ci_act, ci_churn, ci_disc):
            continue
        period_lbl = (r[0] or "").strip()
        key = period_by_label.get(period_lbl)
        if not key:
            continue
        owner_cell = r[ci_owner] or ""
        owner_name = owner_cell.split("[", 1)[0]
        if _norm_owner(owner_name) != want:
            continue
        out[key] = {
            "color": (r[ci_color].strip().lower() if ci_color >= 0
                      and ci_color < len(r) else ""),
            "churn": (r[ci_churn] or "").strip(),
            "activated": (r[ci_act] or "").strip(),
            "disc": (r[ci_disc] or "").strip(),
        }
    return out


# ---- render (house orange style, all cell text centered) -------------------
_PAD = 12
_TITLE_H = 56
_HDR_H = 30
_ROW_H = 30
_COLS = [("Period", 150), ("Churn Rate", 130),
         ("Activated Lines", 150), ("Disconnects", 130)]


def _center(d, box, text, font, fill):
    """Draw `text` centered in (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = box
    tw = d.textlength(text, font=font)
    try:
        asc, desc = font.getmetrics()
        th = asc + desc
    except Exception:
        th = font.size
    d.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2),
           text, fill=fill, font=font)


def render(owner: str, data: dict, target: dt.date, out_dir: Path) -> Path:
    total_w = sum(w for _, w in _COLS) + _PAD * 2
    n = len(PERIODS)
    h = _TITLE_H + _HDR_H + _ROW_H * n + _PAD * 2
    img = Image.new("RGB", (total_w, h), "white")
    d = ImageDraw.Draw(img)
    f_title = _font(20, bold=True)
    f_hdr = _font(12, bold=True)
    f_cell = _font(13)
    f_cellb = _font(13, bold=True)

    x = _PAD
    y = _PAD
    inner_w = total_w - _PAD * 2

    # Title bar — orange, matching the house churn board.
    d.rectangle([x, y, x + inner_w, y + _TITLE_H], fill=TITLE_BG)
    title = f"WIRELESS CHURN — {target.strftime('%b')} {target.day}, {target.year}"
    _center(d, (x, y, x + inner_w, y + _TITLE_H), title, f_title, TITLE_FG)
    y += _TITLE_H

    # Column-header row — black bar, white text (house col-header look).
    d.rectangle([x, y, x + inner_w, y + _HDR_H], fill=(0, 0, 0))
    cx = x
    for label, w in _COLS:
        _center(d, (cx, y, cx + w, y + _HDR_H), label, f_hdr, (255, 255, 255))
        cx += w
    y += _HDR_H

    # One row per period; churn cell colored by Tableau's own health color.
    for ri, (_, key, disp) in enumerate(PERIODS):
        row = data.get(key, {})
        base_bg = "white" if ri % 2 == 0 else ROW_BG
        d.rectangle([x, y, x + inner_w, y + _ROW_H], fill=base_bg)
        cx = x
        # Period
        _center(d, (cx, y, cx + _COLS[0][1], y + _ROW_H), disp, f_cellb, TEXT)
        cx += _COLS[0][1]
        # Churn Rate — colored cell (Tableau color, fallback blank=white)
        churn = row.get("churn", "")
        color = _TABLEAU_COLOR.get(row.get("color", ""), base_bg)
        d.rectangle([cx, y, cx + _COLS[1][1], y + _ROW_H], fill=color)
        _center(d, (cx, y, cx + _COLS[1][1], y + _ROW_H), churn or "—",
                f_cellb, TEXT)
        cx += _COLS[1][1]
        # Activated Lines
        _center(d, (cx, y, cx + _COLS[2][1], y + _ROW_H),
                row.get("activated", "") or "—", f_cell, TEXT)
        cx += _COLS[2][1]
        # Disconnects
        _center(d, (cx, y, cx + _COLS[3][1], y + _ROW_H),
                row.get("disc", "") or "—", f_cell, TEXT)
        y += _ROW_H

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"nds_wireless_churn_{target.isoformat()}.png"
    img.save(out_path)
    return out_path


def run(owner: str, *, target: dt.date | None = None, dry_run: bool = False,
        out_dir: Path | None = None, verbose: bool = False) -> int:
    target = target or dt.date.today()
    out_dir = out_dir or (Path(__file__).resolve().parents[2] / "output"
                          / "nds_churn")
    csv_path = pull(verbose=verbose)
    data = parse_office(csv_path, owner)
    print(f"[nds_churn] {owner} — {len(data)} period row(s): {sorted(data)}",
          flush=True)

    if not data:
        text = (f"{POST_LABEL} — {target.strftime('%b')} {target.day} "
                f"— No data available")
        if dry_run:
            print(f"[nds_churn] --dry-run — would post: {text}", flush=True)
            return 0
        from automations.shared.slack_metrics_post import post_reply_text_only
        post_reply_text_only(text, react_emoji=POST_EMOJI)
        return 0

    img = render(owner, data, target, out_dir)
    print(f"[nds_churn] Rendered -> {img}", flush=True)
    if dry_run:
        print("[nds_churn] --dry-run — rendered only, NO Slack post.", flush=True)
        return 0

    from automations.shared.slack_metrics_post import post_reply_with_image
    comment = f"{POST_LABEL} — {target.strftime('%b')} {target.day}"
    resp = post_reply_with_image(Path(img), comment=comment,
                                 react_emoji=POST_EMOJI)
    print(f"[nds_churn] {'✅ Posted' if resp.get('ok') else '⚠ ' + str(resp)}",
          flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics.nds_churn",
                                 description="NDS office-level Wireless Churn board.")
    ap.add_argument("--owner", required=True, help="office owner name, e.g. "
                    "'Isaiah Revelle' (matched loosely against the crosstab).")
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default today).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="pull + render, NO Slack post.")
    g.add_argument("--live", action="store_true", help="pull + render + post.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(args.owner, target=target, dry_run=not args.live,
               verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
