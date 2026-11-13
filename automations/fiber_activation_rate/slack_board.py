"""📈 Activation Rate by Rep — one Fiber office's reps, as Slack images.

Reads ONLY the 'Fiber Activation by REP (daily log)' tab that run.py fills each morning from
Tableau (ATTTRACKER2_1-D2D → Metrics → 'Metrics Call Last week data
(Internet)' → ICD Owner Name (rep) / Rep Name → 'Rolling 4 Weeks' and
'30-60 day New Internet activation rate').

TWO images, one per window (0-30 = Rolling 4 Weeks, 30-60): reps down the
side, the last 7 logged days across (newest on the left), like the Ongoing
Cancel image Raf pointed at. Same look and colours as the NDS board
(nds_activation_rate.slack_board): green 83%+, grey 79-82.99% (0-30 only),
red below.

  python -m automations.fiber_activation_rate.slack_board --owner "Haytham Nagi"                   (dry run: PNGs only)
  python -m automations.fiber_activation_rate.slack_board --owner "Haytham Nagi" --post-to D087ZGE2B0F
  python -m automations.fiber_activation_rate.slack_board --owner "Haytham Nagi" --live            (metrics thread)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.fiber_activation_rate import run as _run
from automations.nds_activation_rate.slack_board import render_png, _same_owner

LABEL = "📈 Activation Rate by Rep"
EMOJI = "chart_with_upwards_trend"
DAYS_SHOWN = 7
TITLES = {"0-30": "ACTIVATION RATE 0-30 DAYS (ROLLING 4 WEEKS)",
          "30-60": "ACTIVATION RATE 30-60 DAYS"}
HEAD_BG = {"0-30": "#0B3D91", "30-60": "#8A3B00"}
GREEN, GREY, RED = ("#93C47D", "#000"), ("#D9D9D9", "#000"), ("#E06666", "#fff")


def band(win: str, v: Optional[float]):
    if v is None:
        return None
    if v >= 0.83:
        return GREEN
    if win == "0-30" and v >= 0.79:
        return GREY
    return RED


def _pct(s: str) -> Optional[float]:
    s = (s or "").strip().rstrip("%").replace(",", "")
    try:
        return float(s) / 100
    except ValueError:
        return None


def load_owner(grid, owner: str, aliases: Optional[dict] = None):
    """-> (log owner name, {rep: {day: {win: pct}}}) or None."""
    log_owner = next((r[2] for r in grid[1:] if len(r) > 3
                      and _same_owner(r[2], owner, aliases or {})), None)
    if not log_owner:
        return None
    reps: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for r in grid[1:]:
        if len(r) > 3 and r[2] == log_owner:
            reps.setdefault(r[3], {})[r[0]] = {
                w: _pct(r[4 + i] if len(r) > 4 + i else "")
                for i, w in enumerate(_run.WIN_KEYS)}
    return log_owner, reps


def last_days(reps: dict) -> List[str]:
    return sorted({d for v in reps.values() for d in v}, reverse=True)[:DAYS_SHOWN]


_CSS = """<style>
 body{margin:0;font-family:'Helvetica Neue',Arial,sans-serif}
 .board{display:inline-block;padding:14px;background:#fff}
 .title{color:#fff;text-align:center;font-weight:700;font-size:20px;padding:10px 18px}
 .sub{color:#555;text-align:center;font-weight:700;font-size:13px;padding:8px 0}
 table{border-collapse:collapse;margin:0 auto}
 th,td{border:1px solid #999;padding:6px 10px;font-size:13px;text-align:center}
 th{background:#efefef}
 td.lbl{text-align:left;min-width:190px}
 tr.office td{font-weight:700;border-top:2px solid #333;border-bottom:2px solid #333}
 td.v{font-weight:700;font-size:13px;min-width:64px}
 td.blank{color:#bbb;font-weight:400}
 .legend{text-align:center;font-size:12px;color:#444;padding-top:8px}
 .sw{display:inline-block;width:12px;height:12px;vertical-align:middle;margin:0 3px 0 10px;border:1px solid #999}
</style>"""


def _cell(win: str, v: Optional[float]) -> str:
    if v is None:
        return '<td class="v blank">–</td>'
    bg, fg = band(win, v) or ("#fff", "#000")
    return f'<td class="v" style="background:{bg};color:{fg}">{v * 100:.1f}%</td>'


def build_html(win: str, owner: str, days: List[str], reps: dict) -> str:
    def row(label, series, cls=""):
        tds = "".join(_cell(win, series.get(d, {}).get(win)) for d in days)
        return f'<tr class="{cls}"><td class="lbl">{html.escape(label)}</td>{tds}</tr>'

    def lab(d):
        x = dt.date.fromisoformat(d)
        return f"{x.strftime('%a')}<br>{x.month}/{x.day}"

    body = [row(f"{owner} — Office Total", reps.get(_run.TOTAL, {}), "office")]
    for rep in sorted((r for r in reps if r != _run.TOTAL), key=str.lower):
        if any(reps[rep].get(d, {}).get(win) is not None for d in days):
            body.append(row(rep, reps[rep]))
    grey = win == "0-30"
    legend = ('<span class="sw" style="background:#93C47D"></span>83%+'
              + ('<span class="sw" style="background:#D9D9D9"></span>79–82.99%' if grey else "")
              + '<span class="sw" style="background:#E06666"></span>below'
              + (" 79%" if grey else " 83%"))
    head = "".join(f"<th>{lab(d)}</th>" for d in days)
    return (f"<html><head><meta charset='utf-8'>{_CSS}</head><body><div class='board'>"
            f"<div class='title' style='background:{HEAD_BG[win]}'>{TITLES[win]}"
            f" — {html.escape(owner)}</div>"
            f"<div class='sub'>New Internet activation rate (Tableau Metrics) · last "
            f"{len(days)} day(s)</div>"
            f"<table><tr><th>Rep</th>{head}</tr>" + "".join(body)
            + f"</table><div class='legend'>{legend}</div></div></body></html>")


def run(owner: str, *, sandbox: bool, dry_run: bool, post_to: str = "",
        grid=None, out_dir: Optional[Path] = None) -> int:
    if grid is None:
        from automations.new_internet_churn import fill as _shared
        book = _run.open_book(sandbox)
        grid = _shared._retry(_run.log_ws(book).get_all_values)
    try:
        from automations.focus_office_att.aliases import load_aliases
        aliases = load_aliases()
    except Exception as e:  # noqa: BLE001 — exact names still match
        print(f"[fiber_activation_rate:slack] aliases unavailable ({e})", flush=True)
        aliases = {}
    got = load_owner(grid, owner, aliases)
    if not got:
        print(f"[fiber_activation_rate:slack] {owner!r} is not in '{_run.LOG_TAB}' "
              "— no board (add the spelling to ICD Aliases?)", flush=True)
        return 1
    _log_owner, reps = got
    days = last_days(reps)
    out_dir = out_dir or _run.OUT_DIR
    slug = "_".join(owner.lower().split())
    imgs = [render_png(build_html(w, owner, days, reps),
                       out_dir / f"activation_{w}_{slug}_{days[0]}.png")
            for w in _run.WIN_KEYS]
    print(f"[fiber_activation_rate:slack] {owner}: days {days[-1]}..{days[0]} -> "
          f"{[str(i) for i in imgs]}", flush=True)
    if dry_run:
        print("[fiber_activation_rate:slack] dry run — rendered only, NO post.", flush=True)
        return 0
    from automations.shared import slack_metrics_post as smp
    d = dt.date.fromisoformat(days[0])
    where = dict(channel_id=post_to, top_level=True, mirror=False) if post_to else {}
    ok = True
    for w, img in zip(_run.WIN_KEYS, imgs):      # one post per image, in order
        comment = f"{LABEL} ({w} days) — {d.strftime('%b')} {d.day}"
        resp = smp.post_reply_with_image(img, comment=comment, wait_visible=True,
                                         react_emoji=None if post_to else EMOJI, **where)
        good = bool(resp.get("ok"))
        ok = ok and good
        print(f"[fiber_activation_rate:slack] {w}: {'Posted' if good else 'FAILED ' + str(resp)}",
              flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fiber_activation_rate.slack_board")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--real", action="store_true",
                    help="read the log from the REAL workbook (default: sandbox while building)")
    ap.add_argument("--post-to", default="",
                    help="TEST: post top-level to this channel/DM instead of the metrics thread")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    dry = not (args.live or args.post_to)
    return run(args.owner, sandbox=not args.real, dry_run=dry, post_to=args.post_to)


if __name__ == "__main__":
    sys.exit(main())
