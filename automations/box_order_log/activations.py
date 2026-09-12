"""BOX Activation Rates — 0-30 and 31-60 day windows, per rep, as a PNG.

Carlos, 2026-09-12: "I want you to look at the B2B metrics thread ... the
activation report that shows the 0-30-day activation and the 31-60-day
activation. I want you to recreate a similar one for Box. Activation is the
same thing as accepted by supplier — once it's accepted by supplier, to me,
that's activated."

The AT&T version (b2b_metrics/activation_board.py) REBUILDS a Tableau board
from Tableau's own crosstab, colors included. BOX has no such Tableau view, so
this one computes the same shape from data we already trust: the merged
"Box Sales Log" rows (flat_log) — the 60-day record that survives the export's
amnesia. That matters here specifically: an erased TPV row would otherwise
quietly shrink a window's denominator and inflate the rate.

Definitions (Carlos's, verbatim where quoted):
  * A deal is ACTIVATED once it has EVER been Accepted by Supplier — the
    surfaced status, or "Accepted by Supplier" anywhere in Secondary Status.
    Later movement doesn't un-activate it ("once it's accepted ... that's
    activated"), mirroring the TPV rule of 8/28.
  * Windows bucket by SALE DATE age: 0-30 = sold within the last 30 days,
    31-60 = sold 31-60 days ago. Rate = activated / all sales in the window.
    Denominator is every deal on the tab in that window — the tab already
    holds only real sales (Draft/TPV-failed noise never reaches it).

Colors: green >= 75%, yellow >= 50%, red below — DEFAULTS, not a ruling.
The AT&T board inherits Tableau's bands; BOX has none to inherit, so these are
stated here for Carlos to adjust rather than buried in render code.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from . import clean, flat_log
from .png import SCALE, _font

WINDOWS = (("0-30 Days", 0, 30), ("31-60 Days", 31, 60))

GREEN_T, YELLOW_T = 0.75, 0.50
BAND = {"green": "#1e8e3e", "yellow": "#ffe14d", "red": "#e04141"}
INK_ON = {"green": "#ffffff", "yellow": "#000000", "red": "#ffffff"}
NAVY = "#1f3b64"
GREY = "#ededed"

# Just the name (Carlos 2026-09-13: "It can just say 'Box activation rates.'
# That's it.") — the image's own title already says the rest, and the caption
# repeating it read as saying it twice.
ACTIVATIONS_LINE = ":zap: BOX Activation Rates (0-30 / 31-60 days)"


def _is_activated(row) -> bool:
    status = (row[flat_log._COL_STATUS] or "").strip()
    if status == "Accepted by Supplier":
        return True
    secondary = (row[flat_log._COL_SECONDARY] or "").strip()
    return any(p.strip() == "Accepted by Supplier" for p in secondary.split(","))


def build(rows: List[List[str]], today: Optional[dt.date] = None) -> Dict:
    """rows = the Box Sales Log body (flat_log HEADERS order, no header row)."""
    today = today or dt.date.today()
    per: "Dict[str, Dict[str, List[int]]]" = {}
    total = {w: [0, 0] for w, _, _ in WINDOWS}
    for r in rows:
        r = list(r) + [""] * (len(flat_log.HEADERS) - len(r))
        sd = clean._parse_date(r[flat_log._COL_SALE])
        if not sd:
            continue
        age = (today - sd).days
        for wname, lo, hi in WINDOWS:
            if lo <= age <= hi:
                rep = (r[1] or "").strip() or "(blank)"
                cell = per.setdefault(rep, {w: [0, 0] for w, _, _ in WINDOWS})
                cell[wname][1] += 1
                total[wname][1] += 1
                if _is_activated(r):
                    cell[wname][0] += 1
                    total[wname][0] += 1
                break
    return {"per_rep": per, "total": total, "today": today}


def _color(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    return "green" if pct >= GREEN_T else ("yellow" if pct >= YELLOW_T else "red")


def render(data: Dict, out_path: Path) -> Path:
    per, total = data["per_rep"], data["total"]
    reps = sorted(per, key=lambda r: (-sum(v[1] for v in per[r].values()), r))

    f = _font(13 * SCALE)
    fb = _font(13 * SCALE, bold=True)
    ft = _font(16 * SCALE, bold=True)

    name_w = 240 * SCALE
    cell_w = 150 * SCALE
    row_h = 26 * SCALE
    pad = 14 * SCALE
    title_h = 34 * SCALE
    hdr_h = 30 * SCALE
    width = pad * 2 + name_w + cell_w * len(WINDOWS)
    height = title_h + hdr_h + row_h * (len(reps) + 1) + pad * 2
    if data.get("hidden"):
        height += 18 * SCALE
    if data.get("unlisted"):
        height += 18 * SCALE
    if data.get("hidden") or data.get("unlisted"):
        height += 8 * SCALE

    img = Image.new("RGB", (width, height), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, title_h], fill=NAVY)
    d.text((pad, title_h // 2), "BOX ACTIVATION RATES — {}".format(
        data["today"].strftime("%B %d, %Y")), font=ft, fill="#ffffff",
        anchor="lm")

    y = title_h
    d.rectangle([0, y, width, y + hdr_h], fill="#3d3d3d")
    d.text((pad, y + hdr_h // 2), "Rep", font=fb, fill="#ffffff", anchor="lm")
    for i, (wname, _, _) in enumerate(WINDOWS):
        cx = pad + name_w + cell_w * i + cell_w // 2
        d.text((cx, y + hdr_h // 2), wname, font=fb, fill="#ffffff",
               anchor="mm")
    y += hdr_h

    def row(label, cells, bold=False, bg=None):
        nonlocal y
        if bg:
            d.rectangle([0, y, width, y + row_h], fill=bg)
        d.text((pad, y + row_h // 2), label[:34], font=fb if bold else f,
               fill="#000000", anchor="lm")
        for i, (wname, _, _) in enumerate(WINDOWS):
            act, vol = cells[wname]
            x0 = pad + name_w + cell_w * i
            if vol:
                pct = act / vol
                band = _color(pct)
                d.rectangle([x0 + 2, y + 2, x0 + cell_w - 2, y + row_h - 2],
                            fill=BAND[band])
                d.text((x0 + cell_w // 2, y + row_h // 2),
                       "{:.0%}  ({}/{})".format(pct, act, vol),
                       font=fb if bold else f, fill=INK_ON[band], anchor="mm")
            else:
                d.text((x0 + cell_w // 2, y + row_h // 2), "·",
                       font=f, fill="#999999", anchor="mm")
        d.line([0, y + row_h, width, y + row_h], fill="#d9d9d9",
               width=max(1, SCALE // 2))
        y += row_h

    for rep in reps:
        row(rep, per[rep])
    row("OFFICE TOTAL", total, bold=True, bg=GREY)

    fy = y + 6 * SCALE
    ff = _font(10 * SCALE)
    if data.get("hidden"):
        d.text((pad, fy),
               "Terminated on Roll Call, hidden ({} sale{} still in OFFICE "
               "TOTAL): {}".format(
                   data.get("hidden_sales", 0),
                   "s" if data.get("hidden_sales", 0) != 1 else "",
                   ", ".join(data["hidden"])[:170]),
               font=ff, fill="#777777")
        fy += 15 * SCALE
    if data.get("unlisted"):
        d.text((pad, fy),
               "Not on the Roll Call roster (shown anyway): {}".format(
                   ", ".join(data["unlisted"])[:170]),
               font=ff, fill="#777777")

    img = img.resize((width // SCALE, height // SCALE), Image.LANCZOS)
    img.save(out_path)
    return out_path


def _norm_tokens(name: str) -> List[str]:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in s.lower().replace(".", " ").split() if t]


def _names_match(a: str, b: str) -> bool:
    """Roll Call names and order-log names drift ('Nico Murrugarra' vs
    'Nicolas Murrugarra', 'Tara Ecklof' vs 'Tara Lynn Ecklof', 'Kandice
    Flores' vs 'Kandice Michelle Flores'). Match on FIRST and LAST tokens,
    either being a prefix of the other, accents stripped. Middle names are
    ignored — they are exactly what drifts."""
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return False
    def pfx(x, y):
        return x.startswith(y) or y.startswith(x)
    return pfx(ta[0], tb[0]) and pfx(ta[-1], tb[-1])


def roll_call_status(sheet_id: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """(active names, terminated names) from the Roll Call tab, any campaign.

    Carlos 2026-09-12: "cross-reference with the roll call, and we only show
    the active reps." The rule is deliberately TERMINATED-DRIVEN: the roster
    itself has gaps (2026-09-12: Sandy Samaniego was 'Here' all week in
    RollCallData yet absent from the Roll Call tab entirely), so hiding
    everyone who fails to match Active would hide real sellers. A rep is
    hidden only on an explicit Terminated match; one the roster has never
    heard of stays visible and is flagged in the footer instead. Terminated
    matches ANY campaign — a rep marked Terminated under B2B is still gone.
    Unreadable tab -> ([], []) -> nothing hidden.
    """
    from .sheet import _open, _retry
    try:
        sh = _open(sheet_id)
        grid = _retry(lambda: sh.worksheet("Roll Call").get_all_values())
    except Exception:
        return [], []
    hdr_i = next((i for i, r in enumerate(grid)
                  if r and "Status" in r and "Campaign" in r), None)
    if hdr_i is None:
        return [], []
    hdr = grid[hdr_i]
    i_st = hdr.index("Status")
    i_nm = hdr.index("Roll Call") if "Roll Call" in hdr else i_st + 2
    active, terminated = [], []
    for r in grid[hdr_i + 1:]:
        r = list(r) + [""] * (i_nm + 1 - len(r))
        name = r[i_nm].strip()
        if not name:
            continue
        st = r[i_st].strip().lower()
        if st == "active":
            active.append(name)
        elif st == "terminated":
            terminated.append(name)
    return active, terminated


def split_by_roster(data: Dict, active: List[str],
                    terminated: List[str]) -> Dict:
    """Hide Terminated reps; flag roster-absent ones. Totals stay OFFICE-wide
    so the bottom line still reconciles with the order log."""
    keep, hidden, unlisted = {}, [], []
    for rep, cells in data["per_rep"].items():
        if any(_names_match(rep, t) for t in terminated) and not any(
                _names_match(rep, a) for a in active):
            hidden.append(rep)
        else:
            keep[rep] = cells
            if not any(_names_match(rep, a) for a in active):
                unlisted.append(rep)
    out = dict(data)
    out["per_rep"] = keep
    out["hidden"] = sorted(hidden)
    out["unlisted"] = sorted(unlisted)
    return out


def build_from_sheet(today: Optional[dt.date] = None,
                     sheet_id: Optional[str] = None) -> Dict:
    """Read the merged Box Sales Log tab — the durable 60-day record."""
    from .sheet import _open, _retry
    sh = _open(sheet_id)
    grid = _retry(lambda: sh.worksheet(flat_log.TAB).get_all_values())
    full = build(grid[1:] if grid else [], today=today)
    active, terminated = roll_call_status(sheet_id)
    data = split_by_roster(full, active, terminated)
    # so the footer can say how many sales the hidden reps carry — the OFFICE
    # TOTAL row keeps them, and this line is what makes that visibly add up.
    data["hidden_sales"] = sum(
        v for rep in data["hidden"]
        for (_a, v) in full["per_rep"].get(rep, {}).values())
    return data
