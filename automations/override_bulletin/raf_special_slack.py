"""Raf's Special Override, once a week in his Slack DM (Raf, 2026-11-06).

Ask: "For my special over ride for the att program, can I get a slack from
Lucy of what it is and what the last 4 weeks are? Once a week slack message
whenever it updates."

Source: Tableau `ResATTSpecialDealOverride-Raf` -> sheet `Payout- Raf wow`
(the same view the Override Bulletin reads his special from). Per Processed
Week it has four rows, found BY LABEL:
    New Fiber Estimate  -> picks the tier
    Override Estimate   -> the units he is paid on
    Raf Bonus Payout    -> $ per unit ($4 / $5 / $6)
    Raf Payout Total    -> Override Estimate x rate = his special
The tier table comes from the sibling sheet `Payouts Raf` (live, so a tier
change in Tableau shows up in the message without a code change).

Sent as a PICTURE (Eve 2026-11-06: table, tier colored, total at the bottom)
with a one-line caption. EVERY FRIDAY (Eve 2026-11-06, "todos los viernes a
rafael, empezando hoy"): the agent fires Friday 14:00 CT with retries at 15:00
and 16:00; one send per Friday (state file), so a retry never double-posts.

LUCY 1 (Raf's Tableau login; its Slack token posts as Lucy).

  python -m automations.override_bulletin.raf_special_slack           # dry: prints it
  python -m automations.override_bulletin.raf_special_slack --preview # DM to Eve only
  python -m automations.override_bulletin.raf_special_slack --send    # DM to Raf (once per day)

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RAF = "U045Z8N0ZQC"            # resources/owner-slack-ids.md
EVE = "U088E2KJEV8"            # preview goes ONLY here
TIER_SHEET = "Payouts Raf"
WEEKS_SHOWN = 4
OUT_DIR = REPO / "output" / "override_bulletin" / "raf_special_slack"
STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "raf_special_slack_sent.json")

LABELS = {
    "new fiber estimate": "fiber",
    "override estimate": "units",
    "raf bonus payout": "rate",
    "raf payout total": "total",
}
_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_TIER = re.compile(r"tier\s*(\d+)\s*:\s*\$?\s*([\d.]+)\s*\|\s*([\d,]+)", re.I)


def _num(s):
    from automations.override_bulletin.pulls import _num_locale
    return _num_locale(s)


def parse_weeks(rows) -> dict:
    """{date: {'fiber','units','rate','total'}} from a `Payout- Raf wow` crosstab.

    Week columns come from the row holding m/d/yyyy dates; values are read from
    the label rows at those same columns. No fixed row or column numbers."""
    cols = {}
    for r in rows[:8]:
        for i, c in enumerate(r):
            m = _DATE.match(str(c).strip())
            if m:
                cols[i] = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if cols:
            break
    out = {}
    for r in rows:
        key = None
        for c in r[:2]:
            key = LABELS.get(str(c).strip().lower())
            if key:
                break
        if not key:
            continue
        for i, day in cols.items():
            v = _num(r[i]) if i < len(r) else None
            if v is not None:
                out.setdefault(day, {})[key] = v
    return out


def parse_tiers(rows) -> list:
    """[(tier, rate, threshold)] from the `Payouts Raf` sheet, e.g.
    'Tier 2 : $5 | 2,800'. Empty list if the sheet changed shape."""
    out = []
    for r in rows:
        for c in r:
            m = _TIER.search(str(c))
            if m:
                out.append((int(m.group(1)), float(m.group(2)),
                            int(m.group(3).replace(",", ""))))
    return sorted(set(out))


def last_weeks(weeks: dict, n: int = WEEKS_SHOWN) -> list:
    """Newest `n` weeks that have a payout, oldest first."""
    done = sorted(d for d, v in weeks.items() if v.get("total") is not None)
    return [(d, weeks[d]) for d in done[-n:]]


def _money(x) -> str:
    return "$%s" % format(int(round(x)), ",")


def _md(d: dt.date) -> str:
    return "%d/%d" % (d.month, d.day)


def caption(shown: list) -> str:
    d, v = shown[-1]
    line = "Raf's AT&T Special Override — WE %s: *%s*" % (_md(d), _money(v["total"]))
    if len(shown) >= 2:
        diff = v["total"] - shown[-2][1]["total"]
        line += " (%s%s vs last week)" % ("+" if diff >= 0 else "-", _money(abs(diff)))
    return line


# Lowest rate -> highest: red-ish, amber, green. More than 3 rates reuse the scale.
_RATE_COLORS = [("#fde2e1", "#9b1c1c"), ("#fff1c2", "#7a5300"), ("#d6f5dd", "#13652b")]


def _rate_style(rate, tiers) -> str:
    rates = sorted({float(r) for _, r, _ in tiers}) or [4.0, 5.0, 6.0]
    try:
        i = rates.index(float(rate))
    except ValueError:
        return "background:#eee;color:#333"
    k = i * len(_RATE_COLORS) // len(rates) if len(rates) > 3 else i
    bg, fg = _RATE_COLORS[min(k, len(_RATE_COLORS) - 1)]
    return "background:%s;color:%s" % (bg, fg)


_CSS = """<style>
 body{margin:0;font-family:'Helvetica Neue',Arial,sans-serif;background:#fff}
 .card{display:inline-block;padding:18px;background:#fff;min-width:620px}
 .title{background:#1f3b64;color:#fff;font-weight:700;font-size:22px;
        padding:12px 18px;border-radius:6px 6px 0 0}
 .what{background:#f3f6fa;color:#333;font-size:14px;padding:10px 18px 12px;
       line-height:1.45;border-radius:0 0 6px 6px}
 h3{font-size:15px;color:#1f3b64;margin:16px 0 6px}
 table{border-collapse:collapse;width:100%}
 th{background:#efefef;font-size:13px;padding:8px 12px;border:1px solid #ccc}
 td{font-size:15px;padding:8px 12px;border:1px solid #ccc;text-align:right}
 td.l{text-align:left;font-weight:700}
 td.c{text-align:center;font-weight:700}
 tr.new td{font-weight:700}
 tr.tot td{background:#1f3b64;color:#fff;font-weight:700;font-size:16px}
 .next{margin-top:10px;font-size:14px;color:#333;background:#f3f6fa;
       padding:8px 12px;border-radius:6px}
 .src{color:#888;font-size:11px;margin-top:8px}
</style>"""


def tier_for(rate, tiers):
    """(tier number, threshold) whose rate matches; (None, None) if none does."""
    for t, r, th in tiers:
        if abs(float(r) - float(rate or 0)) < 0.001:
            return t, th
    return None, None


def next_tier_line(shown, tiers) -> str:
    """How far the newest week was from the next tier up. '' at the top tier."""
    if not tiers:
        return ""
    d, v = shown[-1]
    fiber = int(v.get("fiber") or 0)
    up = [(t, r, th) for t, r, th in tiers if th > fiber]
    if not up:
        return "WE %s hit the top tier (Tier %d, $%g)." % (_md(d), tiers[-1][0], tiers[-1][1])
    t, r, th = up[0]
    return ("Next tier: <b>Tier %d ($%g)</b> at %s New Fiber &mdash; WE %s was "
            "<b>%s short</b>." % (t, r, format(th, ","), _md(d), format(th - fiber, ",")))


def render_html(shown: list, tiers: list) -> str:
    tier_rows = "".join(
        '<tr><td class="c" style="%s">Tier %d</td><td>%s+</td>'
        '<td class="c" style="%s">$%g</td></tr>'
        % (_rate_style(r, tiers), t, format(th, ","), _rate_style(r, tiers), r)
        for t, r, th in tiers)
    tier_block = ("<h3>Your tiers</h3><table><tr><th>Tier</th>"
                  "<th>Org New Fiber that week</th><th>You get per unit</th></tr>"
                  "%s</table>" % tier_rows) if tiers else ""
    trs = []
    for i, (d, v) in enumerate(shown):
        cls = ' class="new"' if i == len(shown) - 1 else ""
        t, _ = tier_for(v.get("rate"), tiers)
        label = ("Tier %d &middot; $%g" % (t, v.get("rate") or 0)) if t \
            else "$%g" % (v.get("rate") or 0)
        trs.append(
            '<tr%s><td class="l">WE %s</td><td>%s</td>'
            '<td class="c" style="%s">%s</td><td>%s</td><td>%s</td></tr>'
            % (cls, _md(d), format(int(v.get("fiber") or 0), ","),
               _rate_style(v.get("rate") or 0, tiers), label,
               format(int(v.get("units") or 0), ","), _money(v["total"])))
    total = sum(v["total"] for _, v in shown)
    trs.append('<tr class="tot"><td class="l">%d-week total</td><td></td><td></td>'
               '<td></td><td>%s</td></tr>' % (len(shown), _money(total)))
    nxt = next_tier_line(shown, tiers)
    return ("<html><head><meta charset='utf-8'>%s</head><body><div class='card'>"
            "<div class='title'>Raf's AT&amp;T Special Override</div>"
            "<div class='what'><b>What it is:</b> each week you're paid a rate per unit "
            "of the org's <b>Override Estimate</b>. The rate is set by your "
            "<b>tier</b>, which depends on the org's <b>New Fiber Estimate</b> that "
            "week.</div>"
            "%s"
            "<h3>Last %d weeks</h3>"
            "<table><tr><th>Week</th><th>New Fiber</th><th>Tier</th>"
            "<th>Override Est.</th><th>Payout</th></tr>%s</table>"
            "%s"
            "<div class='src'>Source: Tableau &rarr; ResATTSpecialDealOverride-Raf "
            "&rarr; Payout- Raf wow / Payouts Raf</div></div></body></html>"
            % (_CSS, tier_block, len(shown), "".join(trs),
               ("<div class='next'>%s</div>" % nxt) if nxt else ""))


def render_png(shown: list, tiers: list, out_path: Path) -> Path:
    """HTML -> headless Chrome screenshot (same way b2b_metrics.rep_boards does)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".html")
    tmp.write_text(render_html(shown, tiers), encoding="utf-8")
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
                                    viewport={"width": 900, "height": 700})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.query_selector(".card").screenshot(path=str(out_path))
        finally:
            browser.close()
    return out_path


def _periods(today: dt.date) -> list:
    """Retail periods to read: last month's, this month's, next month's number.
    Retail periods don't line up with months (P11 held 10/11), so a window of
    three always covers the newest 4 weeks. Empty ones are skipped."""
    m = today.month
    return ["Period %d" % p for p in sorted({max(1, m - 1), m, min(13, m + 1)})]


def pull(today: dt.date, verbose=True):
    from automations.override_bulletin import pulls as P
    from automations.shared.tableau_patchright import tableau_session
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    weeks, tiers = {}, []
    with tableau_session(headless=True, verbose=verbose) as page:
        for period in _periods(today):
            out = OUT_DIR / ("wow_%s.csv" % period.replace(" ", "_"))
            try:
                got, used = P._download_first_nonempty(
                    P.RAF_BONUS_VIEW, P.RAF_BONUS_SHEET, out,
                    P.period_candidates(period), page=page, verbose=verbose,
                    accept=lambda rs: parse_weeks(rs) or None)
            except Exception as e:  # noqa: BLE001 -- an empty future period is normal
                print("  %s: nothing (%s)" % (period, type(e).__name__))
                continue
            print("  %s (%s): weeks %s" % (period, used,
                                           ", ".join(_md(d) for d in sorted(got or {}))))
            weeks.update(got or {})
            if not tiers and used:
                try:
                    tout = OUT_DIR / "tiers.csv"
                    from automations.shared.tableau_patchright import (
                        download_crosstab_patchright)
                    download_crosstab_patchright(
                        P._with_filter(P.RAF_BONUS_VIEW, "Period", used),
                        TIER_SHEET, tout, page=page, verbose=verbose)
                    tiers = parse_tiers(P.read_crosstab(tout))
                except Exception as e:  # noqa: BLE001 -- message still goes, without tiers
                    print("  tier table: not read (%s)" % type(e).__name__)
    return weeks, tiers


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(d: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(d, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--send", action="store_true", help="DM Raf (once per day)")
    g.add_argument("--preview", action="store_true", help="DM Eve only, always")
    ap.add_argument("--force", action="store_true", help="--send even if it went today already")
    a = ap.parse_args(argv)

    try:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001
        today = dt.date.today()

    weeks, tiers = pull(today)
    shown = last_weeks(weeks)
    if not shown:
        print("no weeks with a Raf Payout Total -- nothing to send")
        return 1
    text = caption(shown)
    png = render_png(shown, tiers, OUT_DIR / ("raf_special_%s.png" % today.isoformat()))
    print(text)
    print("picture: %s" % png)

    if not (a.send or a.preview):
        print("\n(dry run -- nothing posted)")
        return 0
    state = _state()
    if a.send and not a.force and state.get("sent_day") == today.isoformat():
        print("already sent to Raf today (%s) -- nothing to do" % state.get("sent_at"))
        return 0

    from automations.shared import slack_metrics_post as smp
    to = EVE if a.preview else RAF
    # as_bot=False: the machine's user token, which on Lucy 1 IS Lucy (the
    # text preview went out that way on 2026-11-06).
    r = smp.dm_user_with_file(png, user=to, comment=text, file_name=png.name,
                              as_bot=False)
    print("posted to %s: %s" % ("Eve (preview)" if a.preview else "Raf", r))
    if a.send:
        _save_state({"sent_day": today.isoformat(),
                     "week": shown[-1][0].isoformat(),
                     "sent_at": dt.datetime.now().isoformat(timespec="seconds"),
                     "file": r.get("file")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
