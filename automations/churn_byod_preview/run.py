"""Churn BYOD preview — one-shot PNG of Carlos's LUCY CHURN top section
re-laid-out for the 9/7/26 comp change (BYOD vs Non-BYOD churn tiers,
"B2B ATT Comp Change Details", jorton 8/19), DM'd to Carlos on Slack.

This is a PREVIEW, not the live rebuild: the wireless BYOD/non-BYOD line
split is approximated from the rolloff list's Phone/BYOD text (a group
that mixes BYOD + financed phones is split evenly), and the activation
BASE split is an assumed 40% BYOD share. The real tab rebuild will read
each line's BYOD flag from the order log and both become exact.

  python -m automations.churn_byod_preview.run --dry-run   # render only
  python -m automations.churn_byod_preview.run             # render + DM Carlos
  python -m automations.churn_byod_preview.run --channel   # post to #alphalete-gp-sales
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB = "LUCY CHURN"
CARLOS_SLACK_ID = "U046G04P5LG"          # same id team_tree DMs
GP_SALES = ("#alphalete-gp-sales", "C07J46MQNUX")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BYOD_BASE_SHARE = 0.40                   # assumed until the order-log split is built

# Captain payout decelerator (new comp, first applied WE 08/22): brackets on
# 0-30 day churn, applied at the WORSE of team vs personal (office) churn.
DECEL = [("<4%", "100%"), ("4-4.9%", "75%"), ("5-5.9%", "50%"),
         ("6-6.9%", "25%"), ("7%+", "0%")]
DECEL_EDGES = [4.0, 5.0, 6.0, 7.0]           # bracket upper bounds (strict)
# Latest weekly "Captains Bonus Breakdown" team churn, per office key —
# update by hand when the Wednesday email lands. None -> line omitted.
TEAM_CHURN_REF = {
    "carlos": ("4.70%", "WE 08/22"),
    "atef": ("3.10%", "WE 08/22"),
}

NONBYOD_TIERS = [("6", "≤1.0%", "$30"), ("5", "1.0–2.0%", "$10"),
                 ("4", "2.0–2.5%", "$0"), ("3", "2.5–3.0%", "($10)"),
                 ("2", "3.0–3.5%", "($20)"), ("1", ">3.5%", "($30)")]
NONBYOD_EDGES = [1.0, 2.0, 2.5, 3.0, 3.5]     # tier 6..2 upper bounds
BYOD_TIERS = [("6", "≤3.0%", "$50"), ("5", "3.0–4.5%", "$25"),
              ("4", "4.5–5.5%", "$0"), ("3", "5.5–6.5%", "($25)"),
              ("2", "6.5–8.0%", "($50)"), ("1", ">8.0%", "($75)")]
BYOD_EDGES = [3.0, 4.5, 5.5, 6.5, 8.0]
TIER_BG = ["#a9d18e", "#d7e9c5", "#ffe59a", "#fac775", "#f09595", "#e24b4a"]
TIER_FG = ["#173404", "#27500A", "#633806", "#412402", "#501313", "#ffffff"]


def _tier_ix(pct: float, edges) -> int:
    """0 = best (tier 6) ... 5 = worst (tier 1)."""
    for i, e in enumerate(edges):
        if pct <= e:
            return i
    return 5


def _sheet_rows(rng: str, sheet_id: str = SHEET_ID, tab: str = TAB):
    from automations.funnel_board.auth import session
    S = session()
    r = S.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/"
              f"'{tab}'!{rng}", params={"valueRenderOption": "FORMATTED_VALUE"})
    r.raise_for_status()
    return r.json().get("values", [])


def collect(sheet_id: str = SHEET_ID, tab: str = TAB, rows_of=None) -> dict:
    """rows_of(rng) -> values overrides the default funnel_board-auth fetch —
    b2b_metrics passes the office board's already-open gspread worksheet
    (Lucy 2's funnel_board credential can't read every office board; its
    gspread one can — Atef 403, 2026-09-01)."""
    if rows_of is None:
        rows_of = lambda rng: _sheet_rows(rng, sheet_id, tab)  # noqa: E731
    ctrl = rows_of("A4:F12")
    prods = {}
    for row in ctrl:
        row += [""] * (6 - len(row))
        name = (row[0] or "").strip()
        if name.lower() in ("wireless", "air", "internet"):
            prods[name.title()] = {
                "act": row[1], "disc": row[2], "churn": row[3],
                "act30": row[4], "act3160": row[5]}
    roll = rows_of("A15:L80")
    rows = []
    for row in roll[1:]:
        row += [""] * (12 - len(row))
        if (row[10] or "").strip().upper() != "WIRELESS":
            continue
        try:
            lines = int(row[2])
        except (TypeError, ValueError):
            continue
        dev = row[9] or ""
        has_byod = "BYOD" in dev
        has_dev = bool(re.sub(r"BYOD|/|\s", "", dev))
        if has_byod and not has_dev:
            b, n, approx = lines, 0, False
        elif has_dev and not has_byod:
            b, n, approx = 0, lines, False
        else:
            b = (lines + 1) // 2
            n, approx = lines - b, True
        rows.append({"days": row[0], "date": row[1], "lines": lines,
                     "cust": row[4], "rep": row[5], "ordered": row[6],
                     "posted": row[7], "cru": row[8], "dev": dev,
                     "b": b, "n": n, "approx": approx})
    return {"prods": prods, "rows": rows}


def build_html(data: dict, *, label: str = "", team_ref=None) -> str:
    wl = data["prods"].get("Wireless", {})
    try:
        act = int(wl.get("act") or 0)
        disc = int(wl.get("disc") or 0)
    except ValueError:
        act, disc = 0, 0
    rows = data["rows"]
    b_disc = sum(r["b"] for r in rows)
    n_disc = sum(r["n"] for r in rows)
    b_base = max(1, round(act * BYOD_BASE_SHARE))
    n_base = max(1, act - b_base)
    b_pct = 100.0 * b_disc / b_base
    n_pct = 100.0 * n_disc / n_base
    b_ix = _tier_ix(b_pct, BYOD_EDGES)
    n_ix = _tier_ix(n_pct, NONBYOD_EDGES)

    def tier_table(title, tiers, cur_ix, note):
        trs = []
        for i, (t, rng, imp) in enumerate(tiers):
            mark = " style=\"outline:3px solid #c00;\"" if i == cur_ix else ""
            trs.append(
                f"<tr{mark}><td>{t}{' ◀' if i == cur_ix else ''}</td>"
                f"<td style=\"background:{TIER_BG[i]};color:{TIER_FG[i]};"
                f"text-align:center\">{rng}</td>"
                f"<td style=\"text-align:center\">{imp}</td></tr>")
        return (f"<div class=\"box\"><div class=\"hdr\">{title}</div>"
                f"<table class=\"tiers\"><tr class=\"sub\"><td>Tier</td>"
                f"<td>0-30 day</td><td>Impact</td></tr>{''.join(trs)}</table>"
                f"<p class=\"note\">{note}</p></div>")

    # per-bucket churn-after-rolloff, walking the list top to bottom
    b_rem, n_rem = b_disc, n_disc
    body = []
    for r in rows:
        b_rem -= r["b"]
        n_rem -= r["n"]
        b_after = 100.0 * b_rem / b_base
        n_after = 100.0 * n_rem / n_base
        bi, ni = _tier_ix(b_after, BYOD_EDGES), _tier_ix(n_after, NONBYOD_EDGES)
        star = "*" if r["approx"] else ""
        body.append(
            f"<tr><td>{html.escape(r['days'])}</td><td>{html.escape(r['date'])}</td>"
            f"<td style=\"text-align:center\">{r['n']} / {r['b']}{star}</td>"
            f"<td style=\"background:{TIER_BG[ni]};color:{TIER_FG[ni]};"
            f"text-align:center\">{n_after:.1f}%</td>"
            f"<td style=\"background:{TIER_BG[bi]};color:{TIER_FG[bi]};"
            f"text-align:center\">{b_after:.1f}%</td>"
            f"<td>{html.escape(r['cust'])}</td><td>{html.escape(r['rep'])}</td>"
            f"<td>{html.escape(r['ordered'])}</td><td>{html.escape(r['posted'])}</td>"
            f"<td style=\"text-align:center\">{html.escape(r['cru'])}</td>"
            f"<td class=\"dev\">{html.escape(r['dev'][:60])}</td></tr>")

    def prod_row(label, a, d, pct, indent=False, hot=False):
        pad = "padding-left:18px;" if indent else ""
        bg = "background:#e24b4a;color:#fff;font-weight:700;" if hot else ""
        return (f"<tr><td style=\"{pad}\">{label}</td>"
                f"<td style=\"text-align:center\">{a}</td>"
                f"<td style=\"text-align:center\">{d}</td>"
                f"<td style=\"text-align:center;{bg}\">{pct}</td></tr>")

    air = data["prods"].get("Air", {})
    net = data["prods"].get("Internet", {})

    # ---- captain decelerator block (under the customer list) ----
    tot_act = tot_disc = 0
    for v in data["prods"].values():
        try:
            tot_act += int(v.get("act") or 0)
            tot_disc += int(v.get("disc") or 0)
        except ValueError:
            pass
    office_pct = 100.0 * tot_disc / tot_act if tot_act else 0.0
    team_line = (f" · Team churn {team_ref[0]} ({team_ref[1]} bonus email) —"
                 f" the decelerator uses the WORSE of the two, so keep both down."
                 if team_ref else
                 " · decelerator uses the WORSE of team vs office churn.")
    d_ix = 0
    for i, e in enumerate(DECEL_EDGES):
        if office_pct >= e:
            d_ix = i + 1
    cells = []
    for i, (rng, mult) in enumerate(DECEL):
        hot = i == d_ix
        style = ("background:#e24b4a;color:#fff;font-weight:700;outline:3px solid #c00;"
                 if hot else "background:#eef2f8;")
        cells.append(f"<td style=\"text-align:center;{style}\">{rng}<br>"
                     f"<span style=\"font-size:15px\">{mult}</span>"
                     f"{' ◀' if hot else ''}</td>")
    climbs = []
    import math
    for e, mult in ((7.0, "25%"), (6.0, "50%"), (5.0, "75%"), (4.0, "100%")):
        if office_pct < e:
            continue
        allowed = math.ceil(tot_act * e / 100.0) - 1
        need = max(0, tot_disc - allowed)
        # estimated date: walk the wireless rolloff list until `need` lines aged off
        cum, when = 0, None
        for r in rows:
            cum += r["lines"]
            if cum >= need:
                when = r["date"]
                break
        when_s = f" (≈ after {when})" if when else ""
        climbs.append(f"<li>&lt;{e:g}% → {mult}: {need} lines must roll off{when_s}</li>")
    climb_html = ("<ul style=\"margin:4px 0 0 18px;padding:0\">" + "".join(climbs) + "</ul>"
                  if climbs else "<p class=\"note\">already in the best bracket</p>")
    decel_html = f"""<div style=\"margin-top:14px;border:1px solid #ccd\">
<div class=\"hdr\">Captain decelerator — payout multiplier (worse of team vs yours)</div>
<div style=\"display:grid;grid-template-columns:1.6fr 1fr;gap:10px;padding:10px\">
<div><table><tr>{''.join(cells)}</tr></table>
<p class=\"note\">Office 0-30 (all products): <b>{office_pct:.1f}%</b>
 ({tot_disc} of {tot_act}){team_line}</p></div>
<div><div style=\"font-size:12.5px;font-weight:600\">Lines to climb a bracket</div>
<div style=\"font-size:12.5px\">{climb_html}</div>
<p class=\"note\">Dates estimated from the wireless rolloff schedule only.</p></div>
</div></div>"""
    today = dt.date.today().strftime("%a %-m/%-d/%y")
    label_sfx = f" — {html.escape(label)}" if label else ""
    return f"""<meta charset="utf-8"><title>Churn preview</title><style>
body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; background:#fff;
       color:#1a1a1a; width: 1560px; margin: 24px; }}
.banner {{ background:#1f3a5f; color:#fff; text-align:center; padding:8px;
           font-weight:700; font-size:17px; }}
.subban {{ background:#eef2f8; color:#445; text-align:center; padding:5px;
           font-size:12px; border:1px solid #ccd; border-top:none; }}
.grid {{ display:grid; grid-template-columns: 1.25fr 1fr 1fr 1fr; gap:10px;
         border:1px solid #ccd; border-top:none; padding:10px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
td {{ border:1px solid #b9c2cf; padding:4px 7px; }}
.hdr {{ background:#1f3a5f; color:#fff; text-align:center; font-weight:700;
        font-size:13px; padding:5px; }}
.sub td {{ background:#dfe6ef; font-weight:600; }}
.tiers td {{ font-size:12.5px; padding:3px 7px; }}
.note {{ font-size:11px; color:#667; margin:5px 0 0; }}
.roll {{ margin-top:12px; }}
.roll td {{ font-size:12.5px; }}
.roll .hd td {{ background:#1f3a5f; color:#fff; font-weight:600; border-color:#1f3a5f; }}
.dev {{ max-width:330px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }}
.foot {{ font-size:11.5px; color:#667; margin-top:10px; }}
</style>
<div class="banner">0–30 Day Rolloff List{label_sfx} · new comp · {today}</div>
<div class="subban">BYOD / Non-BYOD churn tiers go live SALE DATE 9/7/26
 (B2B ATT Comp Change Details, 8/19). Splits marked * are approximated —
 the live rebuild reads each line's BYOD flag from the order log.</div>
<div class="grid">
<div>
<table><tr class="sub"><td>Product</td><td>Activ.</td><td>Disc.</td><td>Churn %</td></tr>
{prod_row("Wireless (all)", act, disc, wl.get("churn", ""))}
{prod_row("↳ Non-BYOD*", f"≈{n_base}", f"≈{n_disc}", f"≈{n_pct:.1f}%", indent=True, hot=n_ix == 5)}
{prod_row("↳ BYOD*", f"≈{b_base}", f"≈{b_disc}", f"≈{b_pct:.1f}%", indent=True, hot=b_ix == 5)}
{prod_row("Air", air.get("act", ""), air.get("disc", ""), air.get("churn", ""))}
{prod_row("Internet", net.get("act", ""), net.get("disc", ""), net.get("churn", ""))}
</table>
<p class="note">0-30 day activation {wl.get("act30", "")} · 31-60 day
 {wl.get("act3160", "")} · filter gains BYOD / Non-BYOD views</p>
</div>
{tier_table("Churn tiers — Non-BYOD (new 9/7)", NONBYOD_TIERS, n_ix, "Pay hit: CRU + IRU port lines")}
{tier_table("Churn tiers — BYOD (new 9/7)", BYOD_TIERS, b_ix, "Pay hit: CRU BYOD port lines")}
<div class="box"><div class="hdr">Churn tiers — AIR &amp; AWB</div>
<table class="tiers"><tr class="sub"><td>Tier</td><td>0-30 day</td><td>CRU</td><td>IRU</td></tr>
<tr><td>5</td><td style="background:#a9d18e;color:#173404;text-align:center">&lt;2.0%</td><td style="text-align:center">$60</td><td style="text-align:center">$30</td></tr>
<tr><td>4</td><td style="background:#d7e9c5;color:#27500A;text-align:center">2.01–4.00%</td><td style="text-align:center">$40</td><td style="text-align:center">$20</td></tr>
<tr><td>3</td><td style="background:#ffe59a;color:#633806;text-align:center">4.01–5.00%</td><td style="text-align:center">$20</td><td style="text-align:center">$10</td></tr>
<tr><td>2</td><td style="background:#f09595;color:#501313;text-align:center">5.01–8.00%</td><td style="text-align:center">($40)</td><td style="text-align:center">($20)</td></tr>
<tr><td>1</td><td style="background:#e24b4a;color:#fff;text-align:center">&gt;8.01%</td><td style="text-align:center">($60)</td><td style="text-align:center">($30)</td></tr>
</table><p class="note">Unchanged by the comp email</p></div>
</div>
<table class="roll"><tr class="hd"><td>Days</td><td>Disc. Date</td>
<td>Lines (N/B)*</td><td>After: Non-BYOD</td><td>After: BYOD</td><td>Customer</td>
<td>Sales Rep</td><td>Ordered</td><td>Activated</td><td>CRU/IRU</td>
<td>Phone / BYOD</td></tr>{''.join(body)}</table>
{decel_html}
<p class="foot">Lines (N/B) = non-BYOD / BYOD lines in the group; rows marked *
 mix BYOD and financed phones so the split is approximate. Base split assumes
 {int(BYOD_BASE_SHARE*100)}% BYOD activations. ◀ marks today's tier in each chart.</p>"""


def render_office_png(sheet_id: str, tab: str, out_png: Path, *,
                      label: str = "", office_key: str = "", ws=None) -> Path:
    """Render the new-comp churn image for one office board — the entry point
    b2b_metrics' customer_churn capture calls. Raises on any problem so the
    caller can fall back to the plain sheet screenshot. Pass `ws` (an open
    gspread worksheet on that tab) to reuse its authorized client instead of
    the funnel_board session."""
    rows_of = None
    if ws is not None:
        rows_of = lambda rng: ws.get(rng)  # noqa: E731
    data = collect(sheet_id, tab, rows_of=rows_of)
    if not data["rows"] or not data["prods"]:
        raise ValueError(f"no churn data on {tab!r} (rows={len(data['rows'])})")
    html_txt = build_html(data, label=label,
                          team_ref=TEAM_CHURN_REF.get(office_key))
    html_path = out_png.with_suffix(".html")
    html_path.write_text(html_txt, encoding="utf-8")
    render_png(html_path, out_png)
    return out_png


def render_png(html_path: Path, png_path: Path) -> None:
    png_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                 "--no-first-run", "--no-default-browser-check",
                 "--disable-extensions", f"--user-data-dir={tmp}",
                 "--force-device-scale-factor=2", "--window-size=1620,1400",
                 f"--screenshot={png_path}", html_path.resolve().as_uri()],
                capture_output=True, timeout=90)
        except subprocess.TimeoutExpired:
            pass
    if not png_path.exists() or png_path.stat().st_size < 20_000:
        raise RuntimeError(f"screenshot too small/missing: {png_path}")
    try:
        from PIL import Image, ImageChops
        im = Image.open(png_path).convert("RGB")
        bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
        bbox = ImageChops.difference(im, bg).getbbox()
        if bbox:
            left, top, right, bottom = bbox
            pad = 40
            im.crop((max(0, left - pad), max(0, top - pad),
                     min(im.width, right + pad),
                     min(im.height, bottom + pad))).save(png_path)
    except ImportError:
        print("  (Pillow missing — posting untrimmed screenshot)")


def post(png: Path, *, to_channel: bool) -> dict:
    from automations.shared.slack_metrics_post import _client
    client = _client()
    if to_channel:
        channel = GP_SALES[1]
    else:
        channel = client.conversations_open(
            users=CARLOS_SLACK_ID)["channel"]["id"]
    resp = client.files_upload_v2(
        channel=channel, file=str(png),
        title="Churn log — new comp preview",
        initial_comment=("Today's churn log under the 9/7 BYOD/Non-BYOD "
                         "comp change (preview — * splits approximated)"))
    return {"ok": resp.get("ok"), "channel": channel}


def main() -> int:
    ap = argparse.ArgumentParser(prog="churn_byod_preview")
    ap.add_argument("--dry-run", action="store_true", help="render only")
    ap.add_argument("--channel", action="store_true",
                    help="post to #alphalete-gp-sales instead of Carlos's DM")
    args = ap.parse_args()

    print("Collecting today's LUCY CHURN data...")
    data = collect()
    print(f"  wireless rolloff groups: {len(data['rows'])}")
    out = Path(tempfile.gettempdir()) / "churn_byod_preview"
    out.mkdir(exist_ok=True)
    html_path = out / "preview.html"
    png_path = out / "churn_byod_preview.png"
    html_path.write_text(
        build_html(data, label="Carlos's B2B Office",
                   team_ref=TEAM_CHURN_REF.get("carlos")), encoding="utf-8")
    print("Rendering PNG...")
    render_png(html_path, png_path)
    print(f"  {png_path} ({png_path.stat().st_size:,} bytes)")
    if args.dry_run:
        print("  dry-run: not posting")
        return 0
    dest = GP_SALES[0] if args.channel else "Carlos DM"
    res = post(png_path, to_channel=args.channel)
    print(f"  posted to {dest}: {res}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
