"""Raf's %-commission workbook (Raf Loom 2026-11-23, asked of Maud).

Raf is moving his local office to paying reps a % of the revenue they bring in.
From the ORG DD Detail crosstab this builds an .xlsx with:

  Edited    the 10 columns Raf keeps, sorted by rep; cl.Category WEARABLES /
            TABLET copied into the empty cl.Product cell.
  Reps Name & Commission payout   rep | % (yellow, typed by Raf/JD) |
            revenue (SUMIF on Edited) | payout.
  <rep>     one tab per rep: revenue, %, payout + that rep's sales.
  Raw       Raf's office rows untouched.

Scope: corporation "Alphalete Marketing Inc" (office 11479), owner Hidalgo.
Rows with no rep (Raf's own Captain Bonus) are left out. Bonus rows of a rep
DO count toward that rep's revenue — matches Raf's Ana Griffin = $3,562 check
(DD week 11/14/2026).

STATUS: sample only, writes a local file. The real build is Maud's.

    python -m automations.commission_sheet.pct_payout --out output/x.xlsx
    python -m automations.commission_sheet.pct_payout --dd-file dd.csv --out x.xlsx
"""
import argparse
import re
from pathlib import Path

from automations.commission_sheet.sources import read_crosstab
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

CORP_PREFIX = "Alphalete Marketing Inc"   # Raf's local office (11479)
OWNER = "Hidalgo"

EDITED_COLS = [  # (header shown, source column)
    ("REP.Full Name", "REP.Name"),
    ("cl.Sale Date", "cl.Sale Date"),
    ("cl.Activation Date", "cl.Activation Date"),
    ("cl.Product", "cl.Product"),
    ("cl.Description", "cl.Description"),
    ("cl.Tier", "cl.Tier"),
    ("cl.Description Detail", "cl.Description Detail"),
    ("cl.Order Type", "cl.Order Type"),
    ("cl.Customer Name", "cl.Customer Name"),
    ("Total $ to ICD", "Total $ to ICD"),
]
MOVE_TO_PRODUCT = {"WEARABLES", "TABLET"}
EXAMPLE_PCT = {"Ana Griffin": 0.45}   # Raf's own example in the Loom

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
MONEY = '"$"#,##0.00'


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
        rec["REP.Full Name"] = rep
        cat = r[ix["cl.Category"]].strip().upper()
        if cat in MOVE_TO_PRODUCT and not rec["cl.Product"].strip():
            rec["cl.Product"] = cat
        rec["Total $ to ICD"] = money(rec["Total $ to ICD"])
        edited.append(rec)
    edited.sort(key=lambda d: (d["REP.Full Name"].lower(), d["cl.Product"].lower()))
    reps = sorted({d["REP.Full Name"] for d in edited}, key=str.lower)

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
            if d["REP.Full Name"] == rep:
                wt.append([d[c] for c, _ in EDITED_COLS[1:]])
                wt.cell(wt.max_row, 9).number_format = MONEY
        widths(wt, [20, 30, 30, 16, 9, 18, 16, 26, 14])

    # --- Raw (Raf's office rows, untouched) -------------------------------
    wraw = wb.create_sheet("Raw")
    header(wraw, [x.strip() for x in h])
    for r in raw:
        wraw.append(r)

    wb.save(out)
    tot = {}
    for d in edited:
        tot[d["REP.Full Name"]] = tot.get(d["REP.Full Name"], 0) + d["Total $ to ICD"]
    print(f"raw rows {len(raw)}  edited rows {len(edited)}  reps {len(reps)}")
    print(f"total paid-out revenue {sum(tot.values()):,.2f}")
    print("moved to product:", sum(1 for d in edited if d["cl.Product"] in MOVE_TO_PRODUCT))
    print("DD weeks:", sorted({r[ix["cl.DD Week"]] for r in raw}))


def cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd-file", help="already-downloaded ORG DD Detail crosstab")
    ap.add_argument("--out", required=True, help="where to save the .xlsx")
    a = ap.parse_args(argv)
    dd = a.dd_file
    if not dd:
        from automations.commission_sheet.sources import fetch_dd
        dd = fetch_dd()
    main(dd, a.out)


if __name__ == "__main__":
    cli()
