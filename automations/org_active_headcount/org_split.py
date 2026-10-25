"""Org Active Headcount — the same week-over-week summary, split BY ORG.

Rafael 2026-10-25 (email): "similar to the alphalete sales board report, can we
have this WoW report in 4 different formats: 1. Whole org (the screenshot at the
top) 2. My org outside Carlos / Colten 3. Carlos's org 4. Coltens org. The 3 of
our summaries can go at the end." Same closing trio as the Org Sales Board mail
(RAF w/out Carlos & Colten, CARLOS, COLTEN).

WHERE THE SPLIT COMES FROM: the delta box's 'Org Head' helper column (Raf /
Carlos / Colten), the one roster_add fills for every new owner. Nothing here is
typed by hand.

WHAT EACH ORG'S TABLE CARRIES, and why not more:
  - This Week HC   = the daily block's per-owner cells (the same cells the
                     whole-org Totals row adds up), per day.
  - HC (Last Week) = the delta box's per-day 'Last week' cells.
  - vs Prior Week  = the two above.
  - This Week App Avg = each owner's App Avg weighted by their headcount.
  - last week's App Avg and the 'N Week AVG' rows come from org_history, the
    per-owner record the Tuesday roll keeps since 2026-10-25 (the tab itself
    keeps only TOTALS for old weeks). Seeded back to WE 09.27, so it is a full
    4 Week AVG from day one; a week ever missing shows as '3 Week AVG'.

The three orgs must add back up to the whole org's Totals row on every filled
day, and every owner must carry one of the three tags — otherwise this raises
and the mail is not built, the same rule as email_send.totals_mismatch.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from automations.org_active_headcount import daily as d

# (Org Head tag on the tab, title on the picture) — email order.
# Megan 2026-10-25: these exact spellings, possessive and title-cased.
ORGS = [("raf", "Raf's Org"),
        ("carlos", "Carlos' Org"),
        ("colten", "Colten's Org")]


def _org_head_col(g, dx) -> int:
    sub = dx["sub"]
    k = next((k for k in range(1, len(g[sub - 1]) + 1)
              if d._c(g, sub, k).lower() == "org head"), None)
    if k is None:
        raise ValueError("delta box: no 'Org Head' column — can't split by org")
    return k


def _float(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def org_numbers(g) -> Dict[str, dict]:
    """{tag: {'this': [7], 'last': [7], 'app': [7]}} — None on a day the
    whole-org Totals row has not filled yet. Pure: reads the grid only."""
    dl, dx = d.find_daily(g), d.find_delta(g)
    oh = _org_head_col(g, dx)
    org_of = {}
    for r, name in dx["rows"]:
        tag = d._c(g, r, oh).lower()
        if tag not in dict(ORGS):
            raise ValueError(f"{name}: Org Head {d._c(g, r, oh)!r} is not "
                             f"Raf / Carlos / Colten")
        org_of[name.lower()] = (tag, r)
    filled = [d._num(d._c(g, dl["totals"], k)) is not None for k in dl["days"]]
    out = {t: {"this": [0] * 7, "last": [0] * 7, "hc_app": [0.0] * 7,
               "hc_w": [0] * 7} for t, _ in ORGS}
    for r, name, _camp in dl["rows"]:
        if name.lower() not in org_of:
            raise ValueError(f"{name} is on the daily block but not in the delta "
                             f"box, so it has no Org Head")
        tag, _dr = org_of[name.lower()]
        o = out[tag]
        for i, k in enumerate(dl["days"]):
            hc = d._num(d._c(g, r, k))
            if hc is None:
                continue
            o["this"][i] += hc
            a = _float(d._c(g, r, dl["avg"][i])) if dl["avg"][i] else None
            if a is not None:
                o["hc_app"][i] += hc * a
                o["hc_w"][i] += hc
    for name, (tag, dr) in org_of.items():
        for i, k in enumerate(dx["last"]):
            out[tag]["last"][i] += d._num(d._c(g, dr, k)) or 0
    # the three must be the whole org, day by day
    bad = []
    for i, k in enumerate(dl["days"]):
        if not filled[i]:
            continue
        tot = d._num(d._c(g, dl["totals"], k))
        s = sum(out[t]["this"][i] for t, _ in ORGS)
        if s != tot:
            bad.append(f"{d.DAYS[i]}: orgs add to {s}, Totals row says {tot}")
    if bad:
        raise ValueError("org split does not add up:\n  " + "\n  ".join(bad))
    res = {}
    for t, _ in ORGS:
        o = out[t]
        res[t] = {
            "this": [o["this"][i] if filled[i] else None for i in range(7)],
            "last": [o["last"][i] for i in range(7)],
            "app": [round(o["hc_app"][i] / o["hc_w"][i], 1)
                    if filled[i] and o["hc_w"][i] else None for i in range(7)],
        }
    return res


def add_history(nums: Dict[str, dict], history: Dict, this_sunday) -> None:
    """Fill each org's last-week App Avg and its N-week averages from the
    owners' stored weeks (org_history). Pure; edits `nums` in place.

    Only weeks BEFORE this one count, newest first, at most 4 — the same window
    as the whole-org 'HC (4 Week AVG)' (the four 'WE M.D' rows under Totals).
    The org a row counts for is the one it carried THAT week. Fewer than 2
    stored weeks = no average rows (one week IS last week); 2 or 3 weeks are
    shown as a 2- or 3-week average, never called four."""
    import datetime as dt
    weeks = sorted((w for w in history if w < this_sunday), reverse=True)[:4]
    per_week = {}                      # we -> tag -> (hc[7], app[7])
    for we in weeks:
        agg = {t: ([0] * 7, [0.0] * 7, [0] * 7) for t, _ in ORGS}
        for o in history[we].values():
            tag = o["org"].lower()
            if tag not in agg:
                continue
            hc, ha, hw = agg[tag]
            for i in range(7):
                if o["hc"][i] is None:
                    continue
                hc[i] += o["hc"][i]
                if o["app"][i] is not None:
                    ha[i] += o["hc"][i] * o["app"][i]
                    hw[i] += o["hc"][i]
        per_week[we] = {t: (hc, [round(ha[i] / hw[i], 1) if hw[i] else None
                                 for i in range(7)])
                        for t, (hc, ha, hw) in agg.items()}
    last_we = this_sunday - dt.timedelta(days=7)
    for t, _ in ORGS:
        n = nums[t]
        n["app_last"] = (per_week[last_we][t][1] if last_we in per_week
                         else [None] * 7)
        n["avg_weeks"] = len(weeks) if len(weeks) >= 2 else 0
        if n["avg_weeks"]:
            n["hc_avg"] = [round(sum(per_week[w][t][0][i] for w in weeks) / len(weeks))
                           for i in range(7)]
            apps = [[per_week[w][t][1][i] for w in weeks] for i in range(7)]
            n["app_avg"] = [round(sum(a) / len(a), 1) if a and None not in a else None
                            for a in apps]


# ------------------------------------------------------------------ render --
# The tab's own look: orange section bars, grey label column, red/green %.
ORANGE, GREY, WHITE = (180, 95, 6), (204, 204, 204), (255, 255, 255)
TITLE_BG = (217, 217, 217)
RED, GREEN = (244, 199, 195), (183, 225, 205)
BORDER = (150, 150, 150)
_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",   # macOS
    "C:/Windows/Fonts/georgiab.ttf",                          # Windows
]


def _font(size: int):
    from PIL import ImageFont
    for p in _FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise FileNotFoundError(f"Georgia Bold not found — looked in {_FONT_PATHS}")


def _pct(now, then) -> str:
    if not now or not then:
        return ""
    return f"{round((now - then) / then * 100)}%"


def render(out_path: Path, title: str, nums: dict) -> Path:
    from PIL import Image, ImageDraw
    days = [x.capitalize() for x in d.DAYS]
    s = lambda v: "" if v is None else str(v)                    # noqa: E731
    f1 = lambda v: "" if v is None else f"{v:.1f}"                # noqa: E731
    n = nums.get("avg_weeks") or 0
    app_last = nums.get("app_last") or [None] * 7
    rows = [
        ("bar", "Headcount Current vs Prior Weeks"),
        ("hdr", ["Headcount"] + days),
        ("row", ["This Week HC"] + [s(v) for v in nums["this"]]),
        ("pct", ["vs Prior Week"] + [_pct(a, b) for a, b in zip(nums["this"], nums["last"])]),
    ]
    if n:
        rows.append(("pct", [f"vs {n} WeekAVG"]
                     + [_pct(a, b) for a, b in zip(nums["this"], nums["hc_avg"])]))
    rows.append(("row", ["HC (Last Week)"] + [s(v) for v in nums["last"]]))
    if n:
        rows.append(("row", [f"HC ({n} Week AVG)"] + [s(v) for v in nums["hc_avg"]]))
    rows += [
        ("bar", "App AVG Current vs Prior Weeks"),
        ("row", ["This Week App Avg"] + [f1(v) for v in nums["app"]]),
    ]
    if any(v is not None for v in app_last):
        rows.append(("pct", ["vs Prior Week"]
                     + [_pct(a, b) for a, b in zip(nums["app"], app_last)]))
    if n:
        rows.append(("pct", [f"vs {n} WeekAVG"]
                     + [_pct(a, b) for a, b in zip(nums["app"], nums["app_avg"])]))
    if any(v is not None for v in app_last):
        rows.append(("row", ["App Avg (Last Week)"] + [f1(v) for v in app_last]))
    if n:
        rows.append(("row", [f"App Avg ({n} Week AVG)"] + [f1(v) for v in nums["app_avg"]]))
    f, ft, fb = _font(22), _font(34), _font(24)
    widths = [300] + [150] * 7
    rh, pad, th = 44, 16, 64
    W = sum(widths) + 2 * pad
    H = 2 * pad + th + rh * len(rows)
    img = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(img)

    def text_c(x, y, w, h, t, font, fill="black"):
        tw = g.textlength(t, font=font)
        bb = font.getbbox("Hg")
        g.text((x + (w - tw) / 2, y + (h - (bb[3] - bb[1])) / 2 - bb[1]), t,
               font=font, fill=fill)

    g.rectangle([pad, pad, W - pad, pad + th], fill=TITLE_BG, outline=BORDER)
    text_c(pad, pad, W - 2 * pad, th, title, ft, (192, 0, 0))
    y = pad + th
    for kind, val in rows:
        if kind == "bar":
            g.rectangle([pad, y, W - pad, y + rh], fill=ORANGE, outline=BORDER)
            text_c(pad, y, W - 2 * pad, rh, val, fb, "white")
        else:
            x = pad
            for i, (w, t) in enumerate(zip(widths, val)):
                fill = GREY if (i == 0 or kind == "hdr") else WHITE
                if kind == "pct" and i and t and t != "0%":
                    fill = RED if t.startswith("-") else GREEN
                g.rectangle([x, y, x + w, y + rh], fill=fill, outline=BORDER)
                text_c(x, y, w, rh, t, f)
                x += w
        y += rh
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def build(g, out_dir: Path, today=None) -> List[tuple]:
    """[(name, png, title)] for the three orgs, in email order. A history tab
    that can't be read leaves the average rows off; it never stops the mail."""
    import datetime as dt
    nums = org_numbers(g)
    try:
        from automations.org_active_headcount import org_history
        add_history(nums, org_history.load(),
                    d.board_sunday(g, today or dt.date.today()))
    except Exception as e:                                         # noqa: BLE001
        print(f"  ⚠ org history not read ({type(e).__name__}: {e}) — "
              "org tables go out without last-week App Avg / week averages")
    return [(f"org_{t}", render(out_dir / f"org_active_headcount_org_{t}.png",
                                title, nums[t]), title)
            for t, title in ORGS]
