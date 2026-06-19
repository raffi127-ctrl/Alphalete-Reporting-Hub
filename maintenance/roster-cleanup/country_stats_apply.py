"""APPLY Country Stats — first write. Backup -> build 50-row roster -> write
A2:R51 (USER_ENTERED) -> clear A52:R53 -> verify. Row 1 (header) untouched."""
import json
import re
import datetime as dt
from pathlib import Path

from automations.recruiting_report import fill as rfill

WB_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
OUT = Path(r"C:\Users\Eve\recruiting-report\output")

try:
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/Chicago"))
except Exception:
    now = dt.datetime.now()
TS = now.strftime("%Y%m%d_%H%M%S")

sh = rfill.open_by_key(WB_ID)
titles = [w.title for w in sh.worksheets()]
title_set = set(titles)
cs = sh.worksheet("Country Stats")

# ---------- 1. BACKUP A1:R53 (FORMULA) ----------
backup = rfill._retry(cs.get_values, "A1:R53", value_render_option="FORMULA")
bpath = OUT / f"country_stats_backup_{TS}.json"
bpath.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"[1] backup -> {bpath.name}  ({len(backup)} filas)")

# ---------- 2. BUILD roster ----------
# column index (0-based, A=0..R=17) -> label ; L(11),N(13),O(14) spacers
COLMAP = {
    1: "Total Apps", 2: "New Internets", 3: "Upgrades", 4: "DTV", 5: "New Lines",
    6: "AVG Apps Per Active Headcount", 7: "AVG New INT Per Active Headcount",
    8: "Active Headcount on Tableau", 9: "Total Leads", 10: "Penetration Rate",
    12: "Expected Fiber Sales (120 days, 17wks)", 15: "0-30 Day Cancel Rate",
    16: "Activation /Approval %", 17: "0-30 Day Churn",
}
SPACERS = {11, 13, 14}
NCOLS = 18  # A..R

def tmpl(tab, label):
    return (f"=IFERROR(INDEX('{tab}'!$A$1:$ZZ$300,"
            f"MATCH(\"{label}\",'{tab}'!$B$1:$B$300,0),"
            f"MATCH($A$1,'{tab}'!$1:$1,0)),\"\")")

def templated_row(colA, tab):
    row = [""] * NCOLS
    row[0] = colA
    for ci, lbl in COLMAP.items():
        row[ci] = tmpl(tab, lbl)
    return row

RE = re.compile(r"INDEX\('([^']+)'!")

# live reps (Group A) from backup; Rafael handled separately
live_rows = []      # (colA, tab)
rafael_row = None
for r in backup:
    a = str(r[0]).strip() if r else ""
    b = str(r[1]) if len(r) > 1 else ""
    m = RE.search(b)
    if not m:
        continue
    tab = m.group(1)
    if tab not in title_set:
        continue  # broken tab -> drop
    if a.upper() == "RAFAEL HIDALGO":
        # copy current B..R formulas tal cual, colA forced
        cells = (r + [""] * NCOLS)[:NCOLS]
        rafael_row = ["RAFAEL HIDALGO"] + [cells[i] for i in range(1, NCOLS)]
    else:
        live_rows.append((a, tab))

assert rafael_row is not None, "Rafael row not found in backup"
print(f"[2] live (sin Rafael): {len(live_rows)} ; Rafael: 1 (copiado tal cual)")

NEW28 = [
 'Edgar Muniz II','Nii Tagoe','Melik El Jaiez','Nigel Gilbert','Sheree Rodriguez',
 'Joseph Logan','Coel Reif','Rashad Reed','Cody Cannon','Haytham Nagi','Jacob Dover',
 'Cyrus Wade','Aya Al-Khafaji','German Lopez','Jennifer Figueroa','Steve McElwee',
 'Sahil Multani','Brian Tran','Chris Williams','Jeremiah Minor','JC Pascual',
 'William Sassenberg','Eric Martinez','Sam Park','Carissa Ng','Nicholas Weldon',
 'Marcial Rodriguez','Kimberly Rodriguez',
]
assert len(NEW28) == 28

roster = []
for colA, tab in live_rows:
    roster.append(templated_row(colA, tab))
roster.append(rafael_row)
for tab in NEW28:
    roster.append(templated_row(tab.upper(), tab))

# sort alphabetically by col A
roster.sort(key=lambda row: str(row[0]).upper())
assert len(roster) == 50, f"roster={len(roster)}"
print(f"[2] roster final: {len(roster)} filas (ordenado por col A)")

# ---------- 3. WRITE A2:R51 (one pass) + clear A52:R53 ----------
rfill._retry(cs.update, roster, "A2:R51", value_input_option="USER_ENTERED")
rfill._retry(cs.batch_clear, ["A52:R53"])
print("[3] escrito A2:R51 (USER_ENTERED) + limpiado A52:R53")

# ---------- 4. VERIFY ----------
vf = rfill._retry(cs.get_values, "A1:R51", value_render_option="FORMULA")
vv = rfill._retry(cs.get_values, "A1:R51", value_render_option="FORMATTED_VALUE")

# #REF! anywhere in rendered values A1:R51
ref_cells = []
for ri, row in enumerate(vv):
    for ci, val in enumerate(row):
        if "#REF!" in str(val):
            ref_cells.append((ri + 1, chr(65 + ci), str(val)))

colA_list = [str(vv[i][0]).strip() for i in range(1, len(vv)) if i < len(vv)]
colA_list = [a for a in colA_list if a]

# fully blank rows (B..R all empty in rendered) among data rows 2..51
blank_rows = []
for ri in range(1, len(vv)):
    row = vv[ri]
    a = str(row[0]).strip() if row else ""
    if not a:
        continue
    body = [str(row[c]).strip() if c < len(row) else "" for c in range(1, NCOLS)]
    if all(v == "" for v in body):
        blank_rows.append((ri + 1, a))

print("\n========== VERIFICACION ==========")
print(f"celdas con #REF! en A1:R51: {len(ref_cells)}")
for r, c, v in ref_cells:
    print(f"   fila {r} col {c}: {v}")
print(f"\nconteo de reps (col A no vacia, filas 2+): {len(colA_list)}")
print("\ncol A en orden:")
for i, a in enumerate(colA_list, start=2):
    print(f"   {i:>3}: {a}")
print(f"\nfilas enteras en blanco (B..R vacias -> fallo MATCH de fecha): {len(blank_rows)}")
for r, a in blank_rows:
    print(f"   fila {r}: {a}")
print(f"\nbackup guardado en: {bpath}")
