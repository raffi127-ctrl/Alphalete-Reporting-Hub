"""Recreate the CHURN RATES board per office from ONE shared crosstab pull.

WHY (Megan 2026-10-06): the per-office churn screenshot sliced the shared
ALLTEAMWireless view by CLICKING its Owner & Office dropdown (URL slicing that
field blanks the workbook). The click never committed — Apply is not a
<button> — so Jamis, Sabrina and Eveliz all posted the whole-org board with
Atef's block on top, and a fixed click still only held about one try in three.
Megan's answer: ONE saved view ('lucyexp', CHURNRATES) that already holds every
office that needs slicing, pulled ONCE as data, then split per office here.

DATA (proven on Lucy 2 2026-10-06, Carlos's login):
  * 'ICD Churn' worksheet — Owner & Office | Rep | Product | colour | measure |
    0-30 / 30 / 60 / 90 / 120 Day. Measures: Activated SPE/SP (den),
    Disconnect count (SPE/SP) (num), Churn Rate. Each (rep, product) spans one
    row-group PER COLOUR BAND, and a band only fills the windows in that band
    — the same shape as the activation crosstab, so Tableau's OWN colour comes
    with every cell (the missing thresholds that blocked the 2026-07-23
    rebuild are not needed).
  * 'Churn National Average' — the same shape keyed by product only.
  The view is wireless-only as saved; the product URL filter (AIR, AIR/AWB,
  WIRELESS, NEW INTERNET) brings back all four rows, also proven that day.

The office TOTAL row per product is summed from its reps (disconnects /
activations). Tableau ships no colour for it and the reps' bands can't stand
in (a 0.4% total read RED off them on the first render), so it renders
neutral grey — every colour on the board is Tableau's own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from automations.b2b_metrics.activation_board import (
    BAND, NAVY, Cell, _looks_blank, _num)

WINDOWS = ["0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]
PRODUCTS = ["AIR/AWB", "BYOD WIRELESS", "NEW INTERNET", "NON BYOD WIRELESS"]
M_ACT = "Activated SPE/SP"
M_DIS = "Disconnect count (SPE/SP)"
M_PCT = "Churn Rate"


@dataclass
class ChurnBoard:
    owner_office: str = ""
    national: dict = field(default_factory=dict)   # product -> {window: Cell}
    total: dict = field(default_factory=dict)      # product -> {window: Cell}
    reps: list = field(default_factory=list)       # [(rep, {product: {window: Cell}})]


def _cols(hdr):
    h = [str(x or "").strip() for x in hdr]
    wcol = {w: h.index(w) for w in WINDOWS if w in h}
    if len(wcol) != len(WINDOWS):
        raise RuntimeError("churn grid missing window columns: found {}".format(
            sorted(wcol)))
    # The measure column has no header; it sits right before the first window.
    return h, wcol, min(wcol.values()) - 1


def _touch(store: dict, w: str, measure: str, val: float, color: str):
    c = store.setdefault(w, Cell())
    if measure == M_ACT:
        c.den = int(val)
    elif measure == M_DIS:
        c.num = int(val)
    elif measure == M_PCT:
        c.pct = val / 100.0
        if color in BAND:
            c.color = color


def parse_national(grid: list) -> dict:
    """'Churn National Average' rows -> {product: {window: Cell}}."""
    _h, wcol, mcol = _cols(grid[0])
    out: dict = {}
    for r in grid[1:]:
        if len(r) <= max(wcol.values()):
            continue
        prod = str(r[0] or "").strip()
        color, measure = str(r[1] or "").strip(), str(r[mcol] or "").strip()
        for w, ci in wcol.items():
            v = _num(r[ci])
            if v is not None:
                _touch(out.setdefault(prod, {}), w, measure, v, color)
    return out


def _norm(v) -> str:
    return " ".join(str(v or "").split()).upper()


def reconcile(grid: list) -> None:
    """The whole pull must add up: summing EVERY owner's rep rows has to equal
    Tableau's own Grand Total row, per window, for activations AND disconnects.
    A miss means rows were dropped, doubled or mis-attributed — raise, never
    post (Megan 2026-10-06: other owners must never get another owner's data).
    Proven exact on the first live pull (0-30: 870 / 32 across all three)."""
    _h, wcol, mcol = _cols(grid[0])
    grand, summed = {}, {}
    for r in grid[1:]:
        if len(r) <= max(wcol.values()):
            continue
        measure = str(r[mcol] or "").strip()
        if measure not in (M_ACT, M_DIS):
            continue
        is_grand = str(r[0] or "").strip() == "Grand Total"
        for w, ci in wcol.items():
            v = _num(r[ci])
            if v is None:
                continue
            tgt = grand if is_grand else summed
            tgt[(measure, w)] = tgt.get((measure, w), 0) + v
    if not grand:
        raise RuntimeError("churn grid has no Grand Total row to reconcile")
    bad = ["{} {}: rows {} vs Grand Total {}".format(m, w, summed.get((m, w), 0), g)
           for (m, w), g in grand.items() if abs(summed.get((m, w), 0) - g) > 0.5]
    if bad:
        raise RuntimeError("churn pull does NOT reconcile — not posting: "
                           + "; ".join(bad))


def parse_office(grid: list, owner_office: str) -> ChurnBoard:
    """One office's board out of the shared 'ICD Churn' grid. `owner_office`
    is the FULL "NAME [office]" member and must match EXACTLY (whitespace and
    case aside) — no prefix match, so a similarly named owner can never leak
    into another office's board."""
    want = _norm(owner_office)
    _h, wcol, mcol = _cols(grid[0])
    reps: dict = {}
    order: list = []
    found = ""
    for r in grid[1:]:
        if len(r) <= max(wcol.values()):
            continue
        owner = str(r[0] or "")
        if _norm(owner) != want:
            continue
        rep = " ".join(str(r[1] or "").split())
        prod = str(r[2] or "").strip()
        color, measure = str(r[3] or "").strip(), str(r[mcol] or "").strip()
        if measure not in (M_ACT, M_DIS, M_PCT):
            continue
        if not found:
            found = " ".join(owner.split())
        if rep not in reps:
            reps[rep] = {}
            order.append(rep)
        for w, ci in wcol.items():
            v = _num(r[ci])
            if v is not None:
                _touch(reps[rep].setdefault(prod, {}), w, measure, v, color)
    if not order:
        raise RuntimeError("churn grid: no rep rows for {!r}".format(owner_office))

    total: dict = {}
    for prod in PRODUCTS:
        for w in WINDOWS:
            num = den = 0
            for rep in order:
                c = reps[rep].get(prod, {}).get(w)
                if c and c.den:
                    den += c.den
                    num += c.num or 0
            if den:
                rate = num / den
                total.setdefault(prod, {})[w] = Cell(num=num, den=den,
                                                     pct=rate)
    return ChurnBoard(owner_office=found, total=total,
                      reps=[(rep, reps[rep]) for rep in order])


# Short window labels for the compact header (the data keys stay Tableau's).
WSHORT = {"0-30 Day": "0-30", "30 Day": "30", "60 Day": "60",
          "90 Day": "90", "120 Day": "120"}
PSHORT = {"AIR/AWB": "AIR / AWB", "BYOD WIRELESS": "BYOD Wireless",
          "NEW INTERNET": "New Internet", "NON BYOD WIRELESS": "Non-BYOD Wireless"}


def _cell_html(c, first: bool = False) -> str:
    cls = "cell first" if first else "cell"
    if c is None or c.pct is None:
        return '<td class="{} blank"></td>'.format(cls)
    band = BAND.get(c.color, {"bg": "#eceff3", "fg": "#1b1f24"})
    frac = ""
    if c.num is not None and c.den is not None:
        frac = '<div class="frac">{}/{}</div>'.format(c.num, c.den)
    pct = c.pct * 100
    txt = "{:.0f}%".format(pct) if pct == int(pct) else "{:.1f}%".format(pct)
    return ('<td class="{}" style="background:{};color:{}">'
            '<div class="pct">{}</div>{}</td>').format(
                cls, band["bg"], band["fg"], txt, frac)


def _row(label: str, by_prod: dict, cls: str = "") -> str:
    """ONE row per rep (Megan 2026-10-06: the rep x product stack was 18,000px
    tall and read as repeats): the four products sit side by side as column
    groups, so every rep and every product is still on the board."""
    tds = "".join(_cell_html((by_prod.get(p) or {}).get(w), first=(i == 0))
                  for p in PRODUCTS for i, w in enumerate(WINDOWS))
    return '<tr class="{}"><td class="lbl">{}</td>{}</tr>'.format(cls, label, tds)


def render_html(board: ChurnBoard) -> str:
    groups = "".join('<th class="grp" colspan="{}">{}</th>'.format(
        len(WINDOWS), PSHORT[p]) for p in PRODUCTS)
    wins = "".join('<th class="wh{}">{}</th>'.format(" first" if i == 0 else "",
                                                     WSHORT[w])
                   for _p in PRODUCTS for i, w in enumerate(WINDOWS))
    body = [_row("National Average", board.national, "nat"),
            _row("Office Total", board.total, "tot")]
    body += [_row(rep, by_prod, "alt" if i % 2 else "")
             for i, (rep, by_prod) in enumerate(board.reps)]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#fff; font-family: Arial, Helvetica, sans-serif; color:#1b1f24; }}
  .board {{ display:inline-block; padding: 0 0 12px; }}
  .titlebar {{ background:{NAVY}; color:#fff; padding:12px 18px; display:flex;
               align-items:baseline; justify-content:space-between; }}
  .t1 {{ font-size:26px; font-weight:800; letter-spacing:.5px; }}
  .t2 {{ font-size:15px; font-weight:700; }}
  .sub {{ font-size:12px; color:#555; padding:6px 18px 8px; }}
  table {{ border-collapse:collapse; margin:0 12px; }}
  th, td {{ border:1px solid #d6d9de; }}
  .grp {{ background:#e9eef6; font-size:14px; font-weight:800; padding:7px 4px;
          text-align:center; border-left:3px solid #5a6b85; }}
  .wh {{ font-size:12px; font-weight:700; padding:5px 2px; text-align:center;
         width:58px; color:#444; background:#f6f8fb; }}
  .first {{ border-left:3px solid #5a6b85; }}
  .corner {{ background:#f6f8fb; font-size:13px; font-weight:800; text-align:left;
             padding:6px 10px; }}
  .lbl {{ font-size:14px; padding:4px 10px; white-space:nowrap; min-width:200px; }}
  tr.alt .lbl {{ background:#f7f8fa; }}
  tr.nat .lbl, tr.tot .lbl {{ font-weight:800; }}
  tr.tot td {{ border-bottom:3px solid #5a6b85; }}
  .cell {{ text-align:center; height:40px; padding:2px 1px; vertical-align:middle; }}
  .cell .pct {{ font-size:14px; font-weight:700; line-height:1.1; }}
  .cell .frac {{ font-size:10px; opacity:.9; }}
  .blank {{ background:#fff; }}
</style></head><body><div class="board">
  <div class="titlebar"><div class="t1">CHURN RATES</div>
    <div class="t2">{board.owner_office}</div></div>
  <div class="sub">Disconnects / Activations by product and age window (days).
    Colours are Tableau's; Office Total is summed from the reps below.</div>
  <table>
    <tr><th class="corner" rowspan="2">Rep</th>{groups}</tr>
    <tr>{wins}</tr>
    {"".join(body)}
  </table>
</div></body></html>"""


def render_png(board: ChurnBoard, out_path: Path) -> Path:
    """Same headless render as the activation board — every rep, no clip."""
    out_path = Path(out_path)
    tmp = out_path.with_suffix(".html")
    tmp.write_text(render_html(board), encoding="utf-8")
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = None
        for kw in ({"channel": "chrome"}, {}):
            try:
                browser = p.chromium.launch(headless=True, **kw)
                break
            except Exception:  # noqa: BLE001 — try the next launcher
                continue
        if browser is None:
            raise RuntimeError("no headless Chromium/Chrome available to render")
        try:
            page = browser.new_page(device_scale_factor=2,
                                    viewport={"width": 1500, "height": 1000})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.query_selector(".board").screenshot(path=str(out_path))
        finally:
            browser.close()
    blank = _looks_blank(out_path)
    if blank:
        raise RuntimeError("churn board rendered blank ({})".format(blank))
    return out_path
