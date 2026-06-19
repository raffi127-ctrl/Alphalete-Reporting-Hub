"""Extend + guard Raf (row 40). Widen right edge of both ranges DG->ZZ, keep left
edge + row numbers, wrap in IFERROR(LET(...ISNUMBER...)). Simulate anchors for
6/14/26 BEFORE writing; STOP if any blank. Then write only B40:R40."""
import json, re, datetime as dt
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
cs = sh.worksheet("Country Stats")

# ---- backup ----
backup = rfill._retry(cs.get_values, "A1:R53", value_render_option="FORMULA")
bpath = OUT / f"country_stats_backup_rafext_{TS}.json"
bpath.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"[backup] {bpath.name}")

a1 = rfill._retry(cs.get_values, "A1:A1")[0][0]
row40 = rfill._retry(cs.get_values, "A40:R40", value_render_option="FORMULA")[0]
row40 = (list(row40) + [""] * 18)[:18]
assert str(row40[0]).strip().upper() == "RAFAEL HIDALGO"

METRIC = [1,2,3,4,5,6,7,8,9,10,12,15,16,17]   # B..R metric cols (full A=0 index)
def cl(i):
    s="";i+=1
    while i:
        i,m=divmod(i-1,26);s=chr(65+m)+s
    return s

def widen_wrap(f):
    inner = f.replace("$DG$", "$ZZ$")
    if inner.startswith("="):
        inner = inner[1:]
    return f'=IFERROR(LET(v, {inner}, IF(ISNUMBER(v),v,"")),"")'

# parse the value-row each metric uses (left row of value range)
VR = re.compile(r"INDEX\('Raf Hidalgo'!\$C\$(\d+):")
new_cells = {}
val_rows = {}
for ci in METRIC:
    f = str(row40[ci])
    m = VR.search(f)
    val_rows[ci] = int(m.group(1)) if m else None
    new_cells[ci] = widen_wrap(f)

# ---- SIMULATE for A1 (6/14/26): read Raf row1 + value rows at the matched col ----
raf = sh.worksheet("Raf Hidalgo")
r1 = rfill._retry(raf.get_values, "A1:ZZ1")[0]
match_cols = [i for i, v in enumerate(r1) if str(v).strip() == a1]
print(f"[sim] A1={a1!r}  ocurrencias en Raf row1: {[cl(i) for i in match_cols]}")
assert match_cols, "fecha no esta en Raf row1"
mc = match_cols[0]                      # MATCH returns first
mcl = cl(mc)
# read that whole column for the value rows
col_vals = rfill._retry(raf.get_values, f"{mcl}1:{mcl}90", value_render_option="FORMATTED_VALUE")
col_vals = [(c[0] if c else "") for c in col_vals]
def get(row): return col_vals[row-1] if 0 < row <= len(col_vals) else ""

def is_num(s):
    s = str(s).strip().replace(",","").replace("%","").replace("$","")
    if s == "": return None
    try: float(s); return True
    except ValueError: return False

ANCHORS = {1:435, 2:272, 3:23, 4:21, 5:119}   # B,C,D,E,F
print(f"[sim] columna que matchea = {mcl}; valores previstos por celda:")
stop = False
for ci in METRIC:
    vr = val_rows[ci]
    val = get(vr)
    ok = is_num(val)
    note = ""
    if ci in ANCHORS:
        note = f"  ancla esperada={ANCHORS[ci]} -> {'OK' if str(val).strip()==str(ANCHORS[ci]) else 'MISMATCH'}"
    if ok is not True:
        note += "  <-- BLANCO/NO-NUM (bloque no llega a esta col)"
        stop = True
    print(f"   {cl(ci)}40 (row {vr}): {val!r}{note}")

if stop:
    print("\n*** FRENO: alguna metrica vuelve blanco/no-num. NO se escribe. ***")
    raise SystemExit(1)

# ---- write only B40:R40 (preserve L,N,O verbatim) ----
out_row = []
for ci in range(1, 18):                 # B..R
    out_row.append(new_cells[ci] if ci in new_cells else row40[ci])
rfill._retry(cs.update, [out_row], "B40:R40", value_input_option="USER_ENTERED")
print("\n[write] B40:R40 escrito (USER_ENTERED); L40/N40/O40 preservadas")

# ---- verify ----
vv = rfill._retry(cs.get_values, "A1:R51", value_render_option="FORMATTED_VALUE")
raf_v = vv[39]
print("\n========== VERIFICACION ==========")
print("Fila Raf (40):")
for ci in range(0, 18):
    val = raf_v[ci] if ci < len(raf_v) else ""
    print(f"   {cl(ci)}40: {val!r}")

nonnum = []
for ri in range(1, len(vv)):
    for ci in METRIC:
        val = vv[ri][ci] if ci < len(vv[ri]) else ""
        if is_num(val) is False:
            nonnum.append((ri+1, cl(ci), str(vv[ri][0]), val))
print(f"\nceldas metricas no-numericas/error en A1:R51: {len(nonnum)}")
for r,c,who,val in nonnum:
    print(f"   fila {r} col {c} ({who}): {val!r}")

# SUM(M2:M51)
msum = 0.0; mbad = False
for ri in range(1, len(vv)):
    val = vv[ri][12] if len(vv[ri]) > 12 else ""
    n = is_num(val)
    if n is True: msum += float(str(val).replace(",",""))
    elif n is False: mbad = True
print(f"\nSUM(M2:M51) = {msum:.2f}  ({'NUMERO' if not mbad else 'tiene #N/A/texto'})")
print(f"\nbackup: {bpath}")
