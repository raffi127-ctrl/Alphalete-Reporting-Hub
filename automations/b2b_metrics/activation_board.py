"""Recreate the ACTIVATION RATES board as a full-height PNG — every rep, no
scroll clip.

WHY THIS EXISTS (Carlos 2026-08-12): Tableau's ACTIVATIONRATES dashboard renders
the "Activation Rates Owner (+/-) Rep" table inside a FIXED-HEIGHT scroll zone,
so Download -> Image (and any screenshot) clips it at the fold — Carlos's office
has 45 reps but only ~21 fit above the fold. The zone can't be resized in the
published view, so instead of screenshotting Tableau we DOWNLOAD the data and
REBUILD the board ourselves. Every row renders because we control the height.

DATA comes from the same 'Activation Office' crosstab vantura_churn already pulls
(automations.vantura_churn.activation_rates): per rep, per window
(0-7/8-14/15-30/31-60 Days), Total Activations (num) / Total Volume (den) /
Activation % — AND Tableau's OWN "Activation Color" per band. So the green/
yellow/red matches Tableau exactly, with no thresholds to guess (the blocker that
killed the churn rebuild does not apply here).

RENDER is self-contained HTML -> PNG via patchright (headless Chromium), so it
runs on any machine with no Google Sheet round-trip.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

WINDOWS = ["0-7 Days", "8-14 Days", "15-30 Days", "31-60 Days"]

# Saturated bands matching the Tableau board Carlos already reads (NOT the soft
# vantura house palette — this is a faithful recreation of his existing view).
BAND = {
    "Green":  {"bg": "#1e8e3e", "fg": "#ffffff"},
    "Yellow": {"bg": "#ffe14d", "fg": "#000000"},
    "Red":    {"bg": "#e04141", "fg": "#ffffff"},
}
BLANK_BG = "#ffffff"
NAVY = "#1f3b64"     # title bar


def _num(v):
    s = str(v or "").replace(",", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _owner(v: str) -> str:
    return str(v or "").split("\n")[0].split("\r")[0].strip().upper()


@dataclass
class Cell:
    num: int | None = None
    den: int | None = None
    pct: float | None = None      # 0..1
    color: str = ""               # "Green"/"Yellow"/"Red"/""


@dataclass
class Board:
    owner_office: str = ""
    reps: list = field(default_factory=list)         # [(rep_name, {window: Cell})]
    grand_total: dict = field(default_factory=dict)  # {window: Cell}
    national: dict = field(default_factory=dict)     # {window: Cell}


# --------------------------------------------------------------------------- #
# Parsing the 'Activation Office' crosstab grid
# --------------------------------------------------------------------------- #
# Layout (confirmed 2026-08-12):
#   Owner & Office | Rep | Activation Color | Calculation1 (1) | <measure> |
#   0-7 Days | 8-14 Days | 15-30 Days | 31-60 Days
# A rep spans several colour-band row-groups; each group has three measure rows
# (Activation % / Total Activations / Total Volume) and carries ONLY the windows
# that fall in that colour band (blank elsewhere). The band's colour applies to
# whichever windows it populates.
COL_OWNER, COL_REP, COL_COLOR, COL_MEASURE = 0, 1, 2, 4
COL_W0 = 5                                   # first window column
M_PCT, M_ACT, M_VOL = "Activation %", "Total Activations", "Total Volume"


def parse_grid(grid: list, owner_prefix: str) -> Board:
    """Build a Board from the raw 'Activation Office' grid rows (list of lists)."""
    hdr = [str(h or "").strip() for h in grid[0]]
    # Map each window to its column by header (survives layout drift).
    wcol = {w: hdr.index(w) for w in WINDOWS if w in hdr}
    if len(wcol) != 4:
        raise RuntimeError(
            f"activation grid missing window columns: found {sorted(wcol)}")

    reps: dict = {}          # rep -> {window: Cell}
    order: list = []         # first-appearance order = Tableau's 0-7-desc sort
    grand: dict = {w: Cell() for w in WINDOWS}
    owner_office = ""

    def _touch(store, w, measure, val, color):
        c = store.setdefault(w, Cell())
        if measure == M_ACT:
            c.num = int(val)
        elif measure == M_VOL:
            c.den = int(val)
        elif measure == M_PCT:
            c.pct = val / 100.0
            if color in BAND:
                c.color = color

    for r in grid[1:]:
        if len(r) <= max(wcol.values()):
            continue
        owner = str(r[COL_OWNER] or "").strip()
        rep = str(r[COL_REP] or "").replace("\r", " ").replace("\n", " ").strip()
        color = str(r[COL_COLOR] or "").strip()
        measure = str(r[COL_MEASURE] or "").strip()
        if measure not in (M_PCT, M_ACT, M_VOL):
            continue

        is_grand = owner == "Grand Total" or rep == "Total"
        if is_grand:
            for w, ci in wcol.items():
                v = _num(r[ci])
                if v is not None:
                    _touch(grand, w, measure, v, color)
            continue

        if not _owner(owner).startswith(owner_prefix.upper()):
            continue
        if not owner_office:
            owner_office = owner.replace("\r", " ").replace("\n", " ").strip()
        store = reps.setdefault(rep, {})
        if rep not in reps or rep not in order:
            if rep not in order:
                order.append(rep)
        for w, ci in wcol.items():
            v = _num(r[ci])
            if v is not None:
                _touch(store, w, measure, v, color)

    if not order:
        raise RuntimeError(f"activation grid: no rep rows for {owner_prefix!r}")

    b = Board(owner_office=owner_office, grand_total=grand)
    b.reps = [(rep, reps[rep]) for rep in order]
    return b


def apply_office_colors(board: Board, totals_csv_rows: list, owner_prefix: str):
    """Colour the Grand Total row from the office-totals dashboard CSV, which
    carries Tableau's own 'Activation Color' per (office, window). The grid's
    Grand Total rows report colour 'Total' (no band), so this fills it in."""
    hdr = [str(h or "").strip() for h in totals_csv_rows[0]]

    def col(name):
        return hdr.index(name) if name in hdr else None
    ci_bucket = col("Activation Bucket")
    ci_owner = col("Owner & Office")
    ci_color = col("Activation Color")
    if None in (ci_bucket, ci_owner, ci_color):
        return
    for r in totals_csv_rows[1:]:
        if len(r) <= max(ci_bucket, ci_owner, ci_color):
            continue
        if not _owner(r[ci_owner]).startswith(owner_prefix.upper()):
            continue
        w = str(r[ci_bucket] or "").strip()
        color = str(r[ci_color] or "").strip()
        if w in board.grand_total and color in BAND:
            board.grand_total[w].color = color


def _infer_color(rate, samples) -> str:
    """Classify a rate into Green/Yellow/Red using observed (rate, color) samples
    for the SAME window (Tableau's bands are on the rate, so the samples define
    clean cutoffs). Used only for the National Average row, whose colour Tableau
    doesn't ship as a band."""
    greens = [r for r, c in samples if c == "Green"]
    yellows = [r for r, c in samples if c == "Yellow"]
    if greens and rate >= min(greens):
        return "Green"
    if yellows and rate >= min(yellows):
        return "Yellow"
    if greens and rate >= (min(greens) - 1e-9):
        return "Green"
    return "Red"


def compute_national(totals_csv_rows: list) -> dict:
    """National Average per window from the FULL (all-office) dashboard totals
    CSV: sum activations / sum volume across every office, colour inferred from
    all offices' own (rate, colour) bands. Returns {window: Cell}."""
    hdr = [str(h or "").strip() for h in totals_csv_rows[0]]

    def col(name):
        return hdr.index(name) if name in hdr else None
    ci_bucket = col("Activation Bucket")
    ci_act = col("Sales (All)  (activations)")
    ci_sold = col("Sales (All)")
    ci_rate = col("Sales (All) Activation Rate")
    ci_color = col("Activation Color")
    if None in (ci_bucket, ci_act, ci_sold, ci_color):
        return {w: Cell() for w in WINDOWS}

    agg = {w: [0, 0] for w in WINDOWS}          # window -> [sum_act, sum_sold]
    samples: dict = {w: [] for w in WINDOWS}    # window -> [(rate, color)]
    for r in totals_csv_rows[1:]:
        if len(r) <= max(ci_bucket, ci_act, ci_sold, ci_color):
            continue
        w = str(r[ci_bucket] or "").strip()
        if w not in agg:
            continue
        a, s = _num(r[ci_act]), _num(r[ci_sold])
        if a is not None:
            agg[w][0] += a
        if s is not None:
            agg[w][1] += s
        rt = _num(r[ci_rate]) if ci_rate is not None else None
        color = str(r[ci_color] or "").strip()
        if rt is not None and color in BAND:
            samples[w].append((rt / 100.0 if rt > 1 else rt, color))

    out = {}
    for w in WINDOWS:
        a, s = agg[w]
        if s:
            rate = a / s
            out[w] = Cell(num=int(a), den=int(s), pct=rate,
                          color=_infer_color(rate, samples[w]))
        else:
            out[w] = Cell()
    return out


def set_national(board: Board, national: dict):
    """national: {window: Cell-like dict or Cell}. Country-wide reference band."""
    out = {}
    for w in WINDOWS:
        v = national.get(w)
        if v is None:
            out[w] = Cell()
        elif isinstance(v, Cell):
            out[w] = v
        else:
            out[w] = Cell(num=v.get("num"), den=v.get("den"),
                          pct=v.get("pct"), color=v.get("color", ""))
    board.national = out


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _cell_html(c: Cell) -> str:
    if c is None or (c.num is None and c.pct is None):
        return f'<td class="cell blank"></td>'
    band = BAND.get(c.color, {"bg": "#f4f4f4", "fg": "#000"})
    frac = ""
    if c.num is not None and c.den is not None:
        frac = f'<div class="frac">({c.num}/{c.den})</div>'
    pct = f'<div class="pct">{round((c.pct or 0) * 100)}%</div>' if c.pct is not None else ""
    return (f'<td class="cell" style="background:{band["bg"]};color:{band["fg"]}">'
            f'{frac}{pct}</td>')


def _row_html(label_html: str, cells: dict, extra_cls: str = "") -> str:
    tds = "".join(_cell_html(cells.get(w)) for w in WINDOWS)
    return f'<tr class="{extra_cls}">{label_html}{tds}</tr>'


def render_html(board: Board, title_date: str = "") -> str:
    owner_short = board.owner_office or "CARLOS HIDALGO"
    chips = [
        ("B2B Captain's T..", "All"),
        ("Owner & Office", owner_short),
        ("Rep", "All"),
        ("CRU/IRU", "All"),
        ("Product Type (..", "All"),
        ("Order Has VOIP", "All"),
        ("Activation vs U..", "Activation"),
    ]
    chip_html = "".join(
        f'<div class="chip"><div class="chip-k">{k}</div>'
        f'<div class="chip-v">{v}</div></div>' for k, v in chips)

    wcols = "".join(f'<th class="wh">{w}</th>' for w in WINDOWS)

    # National Average band
    nat_cells = "".join(_cell_html(board.national.get(w)) for w in WINDOWS)

    # Owner (+/-) Rep table
    grand_row = _row_html('<td class="lbl grand">Grand Total</td>',
                          board.grand_total, "grandrow")
    rep_rows = []
    n = len(board.reps)
    for i, (rep, cells) in enumerate(board.reps):
        owner_cell = ""
        if i == 0:
            owner_cell = (f'<td class="ownercell" rowspan="{n}">'
                          f'{owner_short}</td>')
        rep_rows.append(
            f'<tr>{owner_cell}<td class="lbl rep">{rep}</td>'
            + "".join(_cell_html(cells.get(w)) for w in WINDOWS) + "</tr>")
    rep_rows_html = "\n".join(rep_rows)

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#fff; font-family: Arial, Helvetica, sans-serif;
          color:#222; -webkit-font-smoothing:antialiased; }}
  .board {{ width: 1180px; padding: 0 0 14px; }}
  .titlebar {{ background:{NAVY}; color:#fff; text-align:center; padding:10px 0 8px; }}
  .titlebar .t1 {{ font-size:30px; font-weight:800; letter-spacing:.5px; }}
  .titlebar .t2 {{ font-size:15px; font-weight:700; opacity:.95; margin-top:2px; }}
  .chips {{ display:flex; gap:26px; padding:10px 16px 6px; flex-wrap:wrap; }}
  .chip-k {{ font-size:12px; font-weight:700; color:#333; }}
  .chip-v {{ font-size:12px; color:#444; }}
  .section {{ text-align:center; font-size:20px; font-weight:700; color:#555;
              margin:14px 0 6px; }}
  table {{ border-collapse:collapse; width: calc(100% - 24px); margin:0 12px; }}
  th, td {{ border:1px solid #cfcfcf; }}
  .wh {{ background:#fff; color:#333; font-size:13px; font-weight:700;
         padding:6px 4px; text-align:center; width:150px; }}
  .cornerA {{ text-align:left; padding:6px 8px; font-weight:700; font-size:13px;
              color:#333; }}
  .cell {{ text-align:center; height:44px; padding:3px 2px; vertical-align:middle; }}
  .cell .frac {{ font-size:12px; line-height:1.15; }}
  .cell .pct {{ font-size:15px; font-weight:800; line-height:1.15; }}
  .cell.blank {{ background:{BLANK_BG}; }}
  .nat td.cell {{ height:52px; }}
  .lbl {{ text-align:left; padding:6px 8px; font-size:13px; }}
  .lbl.grand {{ font-weight:800; }}
  .lbl.rep {{ color:#222; }}
  .ownercell {{ vertical-align:top; text-align:left; padding:8px; font-size:12px;
                font-weight:700; color:#222; width:250px; background:#fff; }}
  .grandrow td {{ font-weight:700; }}
</style></head><body>
  <div class="board">
    <div class="titlebar">
      <div class="t1">ACTIVATION RATES</div>
      <div class="t2">(Activations/Sales)</div>
    </div>
    <div class="chips">{chip_html}</div>

    <div class="section">National Average</div>
    <table class="nat"><tr>{wcols}</tr><tr>{nat_cells}</tr></table>

    <div class="section">Activation Rates Owner (+/-) Rep</div>
    <table>
      <tr><th class="cornerA">Owner &amp; Office</th><th class="cornerA">Rep</th>{wcols}</tr>
      {grand_row}
      {rep_rows_html}
    </table>
  </div>
</body></html>"""


# A correctly rendered board is ~50% non-white (the navy header band alone is a
# big block of ink). 0.5% is a floor for "the screenshot came back empty", not a
# quality bar — it must never argue with a real board that happens to be short.
_BLANK_MIN_INK = 0.005


def _looks_blank(path: Path) -> str:
    """Why this image reads as empty, or "" if it carries content.

    Added 2026-08-25: `render_png` handed back whatever the screenshot produced
    without ever looking at it, so a blank capture posted to Slack exactly like
    a good one — the section was reported "posted", the log said "recreated, all
    rows", and the only thing that noticed was a person opening the thread.
    Pillow is already a dependency of this package (capture.py), but a missing
    one returns "" — no opinion beats a false alarm on a working board."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — no Pillow, no verdict
        return ""
    def _ink(img) -> float:
        # reduce() is a box filter: it averages rather than samples, so thin ink
        # survives the shrink instead of falling between sample points.
        small = img.reduce(max(1, min(img.width, img.height) // 200))
        raw = small.tobytes()          # getdata() is deprecated in Pillow 14
        n = len(raw) // 3
        if not n:
            return 0.0
        inked = sum(1 for i in range(0, n * 3, 3)
                    if raw[i:i + 3] != b"\xff\xff\xff")
        return inked / n

    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            if not rgb.width or not rgb.height:
                return "no pixels"
            overall = _ink(rgb)
            # The BOTTOM half specifically. The navy title band renders even
            # when the table behind it does not, and a box filter smears a thin
            # band into enough grey to clear a whole-image floor. Height tracks
            # content here (1 rep -> 842px, 35 -> 3834), so the table always
            # occupies the lower half: measured 42-55% ink at 1, 3 and 35 reps,
            # against 0% for a header-band-only image.
            bottom = _ink(rgb.crop((0, rgb.height // 2, rgb.width, rgb.height)))
    except Exception as e:  # noqa: BLE001 — an unreadable file IS worth naming
        return f"unreadable ({type(e).__name__})"
    if overall < _BLANK_MIN_INK:
        return f"only {overall:.2%} of pixels carry ink"
    if bottom < _BLANK_MIN_INK:
        return (f"the table area is empty ({bottom:.2%} ink below the fold) — "
                "the header rendered but the board did not")
    return ""


def render_png(board: Board, out_path: Path, title_date: str = "") -> Path:
    """HTML -> PNG via headless Chromium (patchright). Screenshots the .board
    element at 2x for crispness. Renders every rep (no scroll clip)."""
    out_path = Path(out_path)
    html = render_html(board, title_date=title_date)
    tmp = out_path.with_suffix(".html")
    tmp.write_text(html, encoding="utf-8")
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        # Lucy 2 drives the REAL Chrome over CDP and may not have patchright's
        # bundled Chromium downloaded, so try the installed Google Chrome channel
        # first, then fall back to bundled Chromium (what the laptop uses).
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
                                    viewport={"width": 1200, "height": 1000})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            el = page.query_selector(".board")
            el.screenshot(path=str(out_path))
        finally:
            browser.close()
    # Look at what we just produced. Raising here is deliberate: the caller
    # (capture.activation_board_image) catches it, logs the reason loudly and
    # falls back to Tableau's Download→Image — a clipped-but-real board beats a
    # white rectangle, and either way the run stops being silent about it.
    blank = _looks_blank(out_path)
    if blank:
        raise RuntimeError(
            f"activation board rendered blank ({blank}) — {len(board.reps)} rep "
            "row(s) went in, so this is the screenshot, not the data")
    return out_path


def board_from_files(grid_path: Path, owner_prefix: str,
                     totals_path: Path | None = None,
                     national: dict | None = None) -> Board:
    """Convenience builder used by the capture wiring + local tests."""
    import csv
    with open(grid_path, encoding="utf-8-sig", errors="replace") as fh:
        grid = list(csv.reader(fh))
    board = parse_grid(grid, owner_prefix)
    if totals_path:
        with open(totals_path, encoding="utf-8-sig", errors="replace") as fh:
            apply_office_colors(board, list(csv.reader(fh)), owner_prefix)
    if national:
        set_national(board, national)
    return board
