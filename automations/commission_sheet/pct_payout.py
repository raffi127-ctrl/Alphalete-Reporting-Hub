"""Raf's %-commission workbook (Raf Loom 2026-11-23, asked of Maud).

Raf is moving his local office to paying reps a % of the revenue they bring in.
From the ORG DD Detail crosstab this builds an .xlsx with:

  Edited    the 10 columns Raf keeps, sorted by rep; cl.Category WEARABLES /
            TABLET copied into the empty cl.Product cell.
  Reps Name & Commission payout   rep | % (yellow, typed by Raf/JD) |
            revenue (SUMIF on Edited) | payout.
  <rep>     one tab per rep: revenue, %, payout + that rep's sales.
  Raw       Raf's office rows untouched. ALWAYS present - require_raw()
            refuses to save a workbook without it.

Scope: corporation "Alphalete Marketing Inc" (office 11479), owner Hidalgo.
Rows with no rep (Raf's own Captain Bonus) are left out. Bonus rows of a rep
DO count toward that rep's revenue — matches Raf's Ana Griffin = $3,562 check
(DD week 11/14/2026).

STATUS: sample only, writes a local file. The real build is Maud's.

    python -m automations.commission_sheet.pct_payout --out output/x.xlsx
    python -m automations.commission_sheet.pct_payout --dd-file dd.csv --out x.xlsx
    python -m automations.commission_sheet.pct_payout --restyle old.xlsx --out new.xlsx
"""
import argparse
import colorsys
import re
from pathlib import Path

from automations.commission_sheet.sources import read_crosstab
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

CORP_PREFIX = "Alphalete Marketing Inc"   # Raf's local office (11479)
OWNER = "Hidalgo"

EDITED_COLS = [  # (header shown, source column)  — names per Maud 2026-11-23
    ("Rep Full Name", "REP.Name"),
    ("Sale Date", "cl.Sale Date"),
    ("Activation Date", "cl.Activation Date"),
    ("Product", "cl.Product"),
    ("Description", "cl.Description"),
    ("Tier", "cl.Tier"),
    ("Description Detail", "cl.Description Detail"),
    ("Order Type", "cl.Order Type"),
    ("Customer Name", "cl.Customer Name"),
    ("Total $ to ICD", "Total $ to ICD"),
]
#: Old Tableau-style headers -> new ones, so --restyle can fix workbooks built
#: before the rename (e.g. the WE 11.14 sample).
OLD_HEADERS = {"REP.Full Name": "Rep Full Name", "cl.Sale Date": "Sale Date",
               "cl.Activation Date": "Activation Date", "cl.Product": "Product",
               "cl.Description": "Description", "cl.Tier": "Tier",
               "cl.Description Detail": "Description Detail",
               "cl.Order Type": "Order Type", "cl.Customer Name": "Customer Name"}
MOVE_TO_PRODUCT = {"WEARABLES", "TABLET"}
EXAMPLE_PCT = {"Ana Griffin": 0.45}   # Raf's own example in the Loom

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
MONEY = '"$"#,##0.00'
LABEL_FILL = PatternFill("solid", fgColor="DDEBF7")   # rep-tab labels, TOTAL row
CENTER = Alignment(horizontal="center", vertical="center")
_EDGE = Side(style="thin", color="8EA9C8")
BORDER = Border(left=_EDGE, right=_EDGE, top=_EDGE, bottom=_EDGE)
TAB_EDITED = "Edited"
TAB_PAYOUT = "Reps Name & Commission payout"
TAB_RAW = "Raw"


def money(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") or s.startswith("-")
    s = s.strip("()-")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def clean_name(s):
    return re.sub(r"\s*\(\d+\)\s*$", "", s or "").strip()


def header(ws, labels):
    ws.append(labels)
    for c in ws[1]:
        c.font, c.fill = HEAD, HEAD_FILL
    ws.freeze_panes = "A2"


def widths(ws, w):
    for i, x in enumerate(w, 1):
        ws.column_dimensions[get_column_letter(i)].width = x


def safe_title(name, used):
    t = re.sub(r"[\[\]\*\?/\\:]", "", name)[:31].strip("'")
    base, n = t, 2
    while t.lower() in used:
        t = f"{base[:28]} {n}"
        n += 1
    used.add(t.lower())
    return t


def product_fills(products):
    """One blue per product: hues spread from teal-blue to periwinkle, light and
    mid tints alternating so neighbouring products read as different. Black
    text stays readable on every shade."""
    names = sorted({(p or "").strip() for p in products}, key=str.lower)
    n = max(len(names) - 1, 1)
    fills = {}
    for i, name in enumerate(names):
        hue = (190 + 40 * i / n) / 360
        light = (0.93, 0.85, 0.78)[i % 3]
        r, g, b = colorsys.hls_to_rgb(hue, light, 0.62)
        fills[name] = PatternFill("solid", fgColor="%02X%02X%02X" % (
            round(r * 255), round(g * 255), round(b * 255)))
    return fills


def _box(ws, r1, r2, c1, c2):
    """Center + border every cell in the block."""
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
        for c in row:
            c.alignment, c.border = CENTER, BORDER


def _header_row(ws, row, c1, c2):
    for c in next(ws.iter_rows(min_row=row, max_row=row, min_col=c1, max_col=c2)):
        c.font, c.fill = HEAD, HEAD_FILL


def _fill_by_product(ws, r1, r2, ncols, product_col, fills):
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=1, max_col=ncols):
        f = fills.get((row[product_col - 1].value or "").strip())
        if f:
            for c in row:
                c.fill = f


def style_workbook(wb):
    """Centered text, borders on every table, navy headers, rows shaded by
    product. Works on a fresh build or on an existing workbook of this shape."""
    ncol = len(EDITED_COLS)
    ed = wb[TAB_EDITED]
    fills = product_fills(ed.cell(r, 4).value for r in range(2, ed.max_row + 1))
    _header_row(ed, 1, 1, ncol)
    _fill_by_product(ed, 2, ed.max_row, ncol, 4, fills)
    _box(ed, 1, ed.max_row, 1, ncol)

    wr = wb[TAB_PAYOUT]
    last = wr.max_row
    while last > 1 and wr.cell(last, 1).value in (None, ""):
        last -= 1
    _header_row(wr, 1, 1, 4)
    for r in range(2, last + 1):
        if str(wr.cell(r, 1).value).strip().upper() == "TOTAL":
            for c in range(1, 5):
                wr.cell(r, c).fill = LABEL_FILL
        else:
            wr.cell(r, 2).fill = INPUT_FILL
    _box(wr, 1, last, 1, 4)

    for ws in wb.worksheets:
        if ws.title in (TAB_EDITED, TAB_PAYOUT, TAB_RAW):
            continue
        for r in range(1, 5):                     # Rep / Revenue / % / Payout
            ws.cell(r, 1).fill = LABEL_FILL
        _box(ws, 1, 4, 1, 2)
        if ws.max_row >= 6:                       # header row 6, sales from 7
            _header_row(ws, 6, 1, ncol - 1)
            _fill_by_product(ws, 7, ws.max_row, ncol - 1, 3, fills)
            _box(ws, 6, ws.max_row, 1, ncol - 1)

    if TAB_RAW in wb.sheetnames:
        raw = wb[TAB_RAW]
        _header_row(raw, 1, 1, raw.max_column)
        _box(raw, 1, raw.max_row, 1, raw.max_column)


def require_raw(wb, expected_rows=None):
    """Every workbook this makes keeps a Raw tab with the untouched Tableau
    rows (Maud 2026-11-23: "always keep a tab with the Raw data"). Refuse to
    save without it."""
    if TAB_RAW not in wb.sheetnames:
        raise RuntimeError("no Raw tab - refusing to save without the raw data")
    have = wb[TAB_RAW].max_row - 1
    if have < 1 or (expected_rows is not None and have != expected_rows):
        raise RuntimeError(f"Raw tab has {have} data rows, expected "
                           f"{expected_rows if expected_rows is not None else '1+'}")


def restyle(src, out):
    """Apply the new header names + styling to an already-built workbook,
    keeping every value, formula and typed % as it is."""
    wb = load_workbook(src)
    for ws in wb.worksheets:
        if ws.title == TAB_RAW:
            continue
        for row in (1, 6):
            for c in ws[row]:
                if isinstance(c.value, str) and c.value.strip() in OLD_HEADERS:
                    c.value = OLD_HEADERS[c.value.strip()]
    style_workbook(wb)
    require_raw(wb)
    wb.save(out)
    print(f"restyled -> {out}")


def main(src, out):
    rows = read_crosstab(Path(src))
    h = rows[0]
    ix = {n.strip(): i for i, n in enumerate(h)}
    raw = [r for r in rows[2:]
           if r[0].startswith(CORP_PREFIX) and OWNER in r[ix["cl.ICD Owner Name"]]]

    edited = []
    for r in raw:
        rep = clean_name(r[ix["REP.Name"]])
        if not rep:          # Raf's own Captain Bonus — no rep, not paid out
            continue
        rec = {}
        for label, col in EDITED_COLS:
            rec[label] = r[ix[col]]
        rec["Rep Full Name"] = rep
        cat = r[ix["cl.Category"]].strip().upper()
        if cat in MOVE_TO_PRODUCT and not rec["Product"].strip():
            rec["Product"] = cat
        rec["Total $ to ICD"] = money(rec["Total $ to ICD"])
        edited.append(rec)
    edited.sort(key=lambda d: (d["Rep Full Name"].lower(), d["Product"].lower()))
    reps = sorted({d["Rep Full Name"] for d in edited}, key=str.lower)

    wb = Workbook()
    # --- Edited ------------------------------------------------------------
    ws = wb.active
    ws.title = "Edited"
    header(ws, [c for c, _ in EDITED_COLS])
    for d in edited:
        ws.append([d[c] for c, _ in EDITED_COLS])
    for (c,) in ws.iter_rows(min_row=2, min_col=10, max_col=10):
        c.number_format = MONEY
    ws.auto_filter.ref = ws.dimensions
    widths(ws, [24, 12, 14, 30, 16, 9, 18, 16, 26, 14])
    last = ws.max_row

    # --- Reps Name & Commission payout ------------------------------------
    wr = wb.create_sheet("Reps Name & Commission payout")
    header(wr, ["Rep Name", "Commission %", "Revenue Brought In", "Payout"])
    for i, rep in enumerate(reps, 2):
        wr.cell(i, 1, rep)
        p = wr.cell(i, 2, EXAMPLE_PCT.get(rep))
        p.number_format, p.fill = "0%", INPUT_FILL
        c = wr.cell(i, 3, f"=SUMIF(Edited!$A$2:$A${last},A{i},Edited!$J$2:$J${last})")
        c.number_format = MONEY
        d = wr.cell(i, 4, f'=IF(B{i}="","",C{i}*B{i})')
        d.number_format = MONEY
    n = len(reps) + 1
    t = n + 1
    wr.cell(t, 1, "TOTAL").font = Font(bold=True)
    for col in ("C", "D"):
        c = wr[f"{col}{t}"]
        c.value = f"=SUM({col}2:{col}{n})"
        c.number_format, c.font = MONEY, Font(bold=True)
    wr["F1"] = "Type each rep's % in the yellow column. Everything else fills itself."
    wr["F1"].font = Font(italic=True)
    widths(wr, [28, 14, 20, 14])

    # --- one tab per rep --------------------------------------------------
    used = {"edited", "reps name & commission payout", "raw"}
    for rep in reps:
        wt = wb.create_sheet(safe_title(rep, used))
        wt["A1"], wt["B1"] = "Rep", rep
        wt["A2"] = "Revenue Brought In"
        wt["B2"] = f"=SUMIF(Edited!$A$2:$A${last},B1,Edited!$J$2:$J${last})"
        wt["A3"] = "Commission %"
        wt["B3"] = ("=IFERROR(INDEX('Reps Name & Commission payout'!$B:$B,"
                    "MATCH(B1,'Reps Name & Commission payout'!$A:$A,0)),\"\")")
        wt["A4"] = "Payout"
        wt["B4"] = '=IF(B3="","",B2*B3)'
        for a in ("A1", "A2", "A3", "A4"):
            wt[a].font = Font(bold=True)
        wt["B1"].font = Font(bold=True, size=13)
        wt["B2"].number_format = MONEY
        wt["B3"].number_format = "0%"
        wt["B4"].number_format = MONEY
        wt["B4"].font = Font(bold=True, size=13, color="006100")
        wt.append([])
        wt.append([c for c, _ in EDITED_COLS[1:]])
        for c in wt[6]:
            c.font, c.fill = HEAD, HEAD_FILL
        for d in edited:
            if d["Rep Full Name"] == rep:
                wt.append([d[c] for c, _ in EDITED_COLS[1:]])
                wt.cell(wt.max_row, 9).number_format = MONEY
        widths(wt, [20, 30, 30, 16, 9, 18, 16, 26, 14])

    # --- Raw (Raf's office rows, untouched) -------------------------------
    wraw = wb.create_sheet("Raw")
    header(wraw, [x.strip() for x in h])
    for r in raw:
        wraw.append(r)

    style_workbook(wb)
    require_raw(wb, expected_rows=len(raw))
    wb.save(out)
    tot = {}
    for d in edited:
        tot[d["Rep Full Name"]] = tot.get(d["Rep Full Name"], 0) + d["Total $ to ICD"]
    print(f"raw rows {len(raw)}  edited rows {len(edited)}  reps {len(reps)}")
    print(f"total paid-out revenue {sum(tot.values()):,.2f}")
    print("moved to product:", sum(1 for d in edited if d["Product"] in MOVE_TO_PRODUCT))
    print("DD weeks:", sorted({r[ix["cl.DD Week"]] for r in raw}))


def cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd-file", help="already-downloaded ORG DD Detail crosstab")
    ap.add_argument("--restyle", help="existing workbook to rename + restyle only")
    ap.add_argument("--out", required=True, help="where to save the .xlsx")
    a = ap.parse_args(argv)
    if a.restyle:
        restyle(a.restyle, a.out)
        return
    dd = a.dd_file
    if not dd:
        from automations.commission_sheet.sources import fetch_dd
        dd = fetch_dd()
    main(dd, a.out)


if __name__ == "__main__":
    cli()
