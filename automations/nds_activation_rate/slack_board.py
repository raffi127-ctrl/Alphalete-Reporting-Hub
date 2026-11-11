"""📈 Activation Rate by Rep — one NDS office's reps, as a Slack image.

Replaces Megan's order-log board of the same name (Eve 2026-11-10, option A;
the old code is backed up in output/backup_megan_nds_activation_board_2026-11-10/).
Reads ONLY the 'NDS Activation Log' tab that run.py fills from Dylan's Tableau
view, so the numbers are the same ones Raf/Dylan see:

  NDS-SNRES-ATT-OOFWorkbook → ChurnActivationRateRep → custom view
  NDSActivationbyRep → worksheet 'Churn % and Activation %' → filter
  NDS Captain Teams=<captain>'s Team → Owner Name / Rep Name rows →
  'New/Port Trailing Act. Rate (10-19 / 20-29 / 30-60 Days)'.

THREE images, one per window (10-19 / 20-29 / 30-60): reps down the side,
the last 7 logged days across, like the Ongoing Cancel image (Dylan 11/11).
Fiber colours: green 83%+, grey 79-82.99% (not on 30-60), red below.

  python -m automations.nds_activation_rate.slack_board --owner "Isaiah Revelle" --sandbox --dry-run
  python -m automations.nds_activation_rate.slack_board --owner "Isaiah Revelle" --sandbox --post-to D087ZGE2B0F
  python -m automations.nds_activation_rate.slack_board --owner "Isaiah Revelle" --live      (metrics thread)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.nds_activation_rate import sheet

LABEL = "📈 Activation Rate by Rep"
EMOJI = "chart_with_upwards_trend"
WINS = [k for k, _ in sheet.WINDOWS]
COLORS = {  # sheet's band colours, as CSS (text colour picked for contrast)
    "green": ("#93C47D", "#000"), "grey": ("#D9D9D9", "#000"),
    "red": ("#E06666", "#fff")}


def _pct(s: str) -> Optional[float]:
    s = (s or "").strip().rstrip("%")
    try:
        return float(s) / 100
    except ValueError:
        return None


def _band(win: str, v: Optional[float]) -> Optional[str]:
    c = sheet.band_color(win, v)
    for name, color in (("green", sheet.GREEN), ("grey", sheet.GREY),
                        ("red", sheet.RED)):
        if c == color:
            return name
    return None


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _same_owner(a: str, b: str, aliases: dict) -> bool:
    if _norm(a) == _norm(b):
        return True
    # Same alias group either way round (the ICD Aliases tab has some names
    # listed in both directions, e.g. Zaid Arabiyat / Zaid Arabyat).
    na, nb = _norm(a), _norm(b)
    for canonical, alts in (aliases or {}).items():
        group = {_norm(canonical)} | {_norm(x) for x in alts}
        if na in group and nb in group:
            return True
    return False


def load_owner(grid, owner: str, aliases: Optional[dict] = None):
    """-> (captain, log owner name, newest day, week-ago day or None,
           {rep: {day: {win: pct}}}, {day: {win: pct}} captainship avg).
    Rep 'Total' = the owner's office number. None when the owner isn't logged."""
    match = None
    for r in grid[1:]:
        if len(r) > 3 and r[2] != sheet.CAPTAINSHIP and _same_owner(r[2], owner, aliases or {}):
            match = (r[1], r[2])
            break
    if not match:
        return None
    captain, log_owner = match
    reps: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    cap: Dict[str, Dict[str, Optional[float]]] = {}
    for r in grid[1:]:
        if len(r) < 4 or r[1] != captain:
            continue
        vals = {w: _pct(r[4 + i] if len(r) > 4 + i else "") for i, w in enumerate(WINS)}
        if r[2] == sheet.CAPTAINSHIP:
            cap[r[0]] = vals
        elif r[2] == log_owner:
            reps.setdefault(r[3], {})[r[0]] = vals
    days = sorted({d for v in reps.values() for d in v}, reverse=True)
    newest = days[0]
    cutoff = (dt.date.fromisoformat(newest) - dt.timedelta(days=7)).isoformat()
    week_ago = next((d for d in days if d <= cutoff), None)
    return captain, log_owner, newest, week_ago, reps, cap


DAYS_SHOWN = 7


def _cell(win: str, v: Optional[float]) -> str:
    if v is None:
        return '<td class="v blank">–</td>'
    bg, fg = COLORS.get(_band(win, v) or "", ("#fff", "#000"))
    return f'<td class="v" style="background:{bg};color:{fg}">{v * 100:.1f}%</td>'


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
 tr.cap td.lbl{color:#555;font-style:italic}
 td.v{font-weight:700;font-size:13px;min-width:64px}
 td.blank{color:#bbb;font-weight:400}
 .legend{text-align:center;font-size:12px;color:#444;padding-top:8px}
 .sw{display:inline-block;width:12px;height:12px;vertical-align:middle;margin:0 3px 0 10px;border:1px solid #999}
</style>"""
HEAD_BG = {"10-19": "#0B3D91", "20-29": "#1B5E20", "30-60": "#8A3B00"}


def last_days(reps: dict, newest: str) -> List[str]:
    """Up to DAYS_SHOWN logged days, newest first (same order as the sheet)."""
    days = sorted({d for v in reps.values() for d in v if d <= newest}, reverse=True)
    return days[:DAYS_SHOWN]


def build_html(win: str, owner: str, captain: str, days: List[str],
               reps: dict, cap: dict) -> str:
    """ONE window (10-19 / 20-29 / 30-60): rows = office, captainship, reps;
    columns = the last 7 logged days. Same idea as the Ongoing Cancel image
    (Dylan 11/11: 'like the ongoing cancel reports, but in three screenshots')."""
    def row(label, series, cls=""):
        tds = "".join(_cell(win, series.get(d, {}).get(win)) for d in days)
        return f'<tr class="{cls}"><td class="lbl">{html.escape(label)}</td>{tds}</tr>'

    def lab(d):
        x = dt.date.fromisoformat(d)
        return f"{x.strftime('%a')}<br>{x.month}/{x.day}"

    head = "".join(f"<th>{lab(d)}</th>" for d in days)
    body = [row(f"{owner} — Office Total", reps.get("Total", {}), "office"),
            row(f"{captain}'s Captainship Avg", cap, "cap")]
    for rep in sorted((r for r in reps if r != "Total"), key=str.lower):
        if any(reps[rep].get(d, {}).get(win) is not None for d in days):
            body.append(row(rep, reps[rep]))
    grey = win != "30-60"
    legend = ('<span class="sw" style="background:#93C47D"></span>83%+'
              + ('<span class="sw" style="background:#D9D9D9"></span>79–82.99%' if grey else "")
              + '<span class="sw" style="background:#E06666"></span>below'
              + (" 79%" if grey else " 83%"))
    return (f"<html><head><meta charset='utf-8'>{_CSS}</head><body><div class='board'>"
            f"<div class='title' style='background:{HEAD_BG[win]}'>ACTIVATION RATE {win} DAYS"
            f" — {html.escape(owner)}</div>"
            f"<div class='sub'>New/Port trailing activation rate (Tableau) · last "
            f"{len(days)} day(s)</div>"
            f"<table><tr><th>Rep</th>{head}</tr>"
            + "".join(body) + f"</table><div class='legend'>{legend}</div></div></body></html>")


def render_png(page_html: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".html")
    tmp.write_text(page_html, encoding="utf-8")
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = None
        for kw in ({"channel": "chrome"}, {}):
            try:
                browser = p.chromium.launch(headless=True, **kw)
                break
            except Exception:  # noqa: BLE001
                continue
        if browser is None:
            raise RuntimeError("no headless Chrome/Chromium to render")
        try:
            page = browser.new_page(device_scale_factor=2,
                                    viewport={"width": 1400, "height": 900})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.query_selector(".board").screenshot(path=str(out_path))
        finally:
            browser.close()
    return out_path


def run(owner: str, *, sandbox: bool, dry_run: bool, post_to: str = "",
        out_dir: Optional[Path] = None) -> int:
    book = sheet.open_book(sandbox)
    grid = sheet._shared._retry(book.worksheet(sheet.LOG_TAB).get_all_values)
    try:
        from automations.focus_office_att.aliases import load_aliases
        aliases = load_aliases()
    except Exception as e:  # noqa: BLE001 — exact names still match
        print(f"[nds_activation_rate:slack] aliases unavailable ({e})", flush=True)
        aliases = {}
    got = load_owner(grid, owner, aliases)
    if not got:
        # Loud, not blank: an office with no row is a name mismatch or an
        # owner outside the 3 captainships — fix it in 'ICD Aliases'.
        print(f"[nds_activation_rate:slack] {owner!r} is not in '{sheet.LOG_TAB}' "
              "— no board (add the spelling to ICD Aliases?)", flush=True)
        return 1
    captain, log_owner, newest, _week_ago, reps, cap = got
    days = last_days(reps, newest)
    out_dir = out_dir or Path(__file__).resolve().parents[2] / "output" / "nds_activation_rate"
    slug = "_".join(owner.lower().split())
    imgs = [render_png(build_html(w, owner, captain, days, reps, cap),
                       out_dir / f"activation_{w}_{slug}_{newest}.png") for w in WINS]
    stale = newest != dt.date.today().isoformat()
    print(f"[nds_activation_rate:slack] {owner} ({captain}): days {days[-1]}..{newest}"
          f"{' (NOT today)' if stale else ''} -> {[str(i) for i in imgs]}", flush=True)
    if dry_run:
        print("[nds_activation_rate:slack] --dry-run — rendered only, NO post.", flush=True)
        return 0
    from automations.shared import slack_metrics_post as smp
    d = dt.date.fromisoformat(newest)
    where = (dict(channel_id=post_to, top_level=True, mirror=False) if post_to else {})
    ok = True
    # One post per image, in order, so they never arrive shuffled.
    for w, img in zip(WINS, imgs):
        comment = f"{LABEL} ({w} days) — {d.strftime('%b')} {d.day}"
        resp = smp.post_reply_with_image(img, comment=comment,
                                         react_emoji=None if post_to else EMOJI, **where)
        good = bool(resp.get("ok"))
        ok = ok and good
        print(f"[nds_activation_rate:slack] {w}: {'✅ Posted' if good else '⚠ ' + str(resp)}",
              flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_activation_rate.slack_board")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--sandbox", action="store_true",
                    help="read the log from the SANDBOX sheet (default: the real workbook)")
    ap.add_argument("--post-to", default="",
                    help="TEST: post top-level to this channel/DM instead of the metrics thread")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    dry = not (args.live or args.post_to)
    return run(args.owner, sandbox=args.sandbox, dry_run=dry, post_to=args.post_to)


if __name__ == "__main__":
    sys.exit(main())
