"""APPLY Recruiting plan — first write. Backup -> build 50-row roster ->
standard rows (per-row INDEX + ZZ + guard, % ratios) + Raf bespoke widened ->
write A4:P53 (USER_ENTERED) -> clear residual -> verify. Rows 1-3 untouched."""
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
rc = sh.worksheet("Recruiting")
RE_TAB = re.compile(r"INDEX\('([^']+)'!")

# ---- backup ----
backup = rfill._retry(rc.get_values, "A1:P60", value_render_option="FORMULA")
bpath = OUT / f"recruiting_backup_{TS}.json"
bpath.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"[backup] {bpath.name}")

# ---- current rows 4-53 ----
cur = backup[3:53]  # rows 4..53
def parse_tab(row):
    for c in range(1, len(row)):
        m = RE_TAB.search(str(row[c]))
        if m: return m.group(1)
    return None

QUITAR = {"Jacob Morgan","Jonathan Franco","Preppie Olison","Rason Williams",
          "Sharon Stephen","Zach Hogue","Alex Vondra","DMari Longmire","Wayne Rude",
          "Kiarri McBroom"}
AGREGAR = ["Carissa Ng","Chris Williams","Edgar Muniz II","Jeremiah Minor","Joseph Logan",
           "Kimberly Rodriguez","Rashad Reed","Stergios Kasapidis","Steve McElwee","William Sassenberg"]

roster = []  # (name, tab)
raf_row24 = None
for row in cur:
    name = str(row[0]).strip()
    if not name: continue
    if name == "Raf Hidalgo":
        raf_row24 = row
    if name in QUITAR: continue
    if name == "Tevin Sterling": name = "Jacob Dover"
    roster.append((name, parse_tab(row)))
for t in AGREGAR:
    roster.append((t, t))
roster.sort(key=lambda x: x[0].upper())
assert len(roster) == 50, len(roster)

# ---- builders ----
FUNNEL = {1:2, 2:7, 4:8, 6:11, 7:12, 9:14, 11:15, 13:18, 14:19}  # colidx -> source row
def cl(i):
    s="";i+=1
    while i:
        i,m=divmod(i-1,26);s=chr(65+m)+s
    return s
def idx_tmpl(tab, srow):
    return (f"=IFERROR(LET(v, INDEX('{tab}'!$C${srow}:$ZZ${srow},"
            f"MATCH($A$1,'{tab}'!$C$1:$ZZ$1,0)), IF(ISNUMBER(v),v,\"\")),\"\")")
def pct(numcol, dencol, R):
    return f"=IFERROR({numcol}{R}/{dencol}{R},0)"

def widen_guard(f):
    inner = re.sub(r'(\$[A-Z]+\$\d+):\$[A-Z]+(\$\d+)', r'\1:$ZZ\2', str(f))
    if inner.startswith("="): inner = inner[1:]
    return f'=IFERROR(LET(v, {inner}, IF(ISNUMBER(v),v,"")),"")'

# Raf bespoke INDEX cells from his current row 24
raf_idx = {}
if raf_row24 is not None:
    for ci in FUNNEL:
        raf_idx[ci] = widen_guard(raf_row24[ci]) if ci < len(raf_row24) and str(raf_row24[ci]).strip() else ""

matrix = []
for i, (name, tab) in enumerate(roster):
    R = 4 + i                      # sheet row
    rowcells = [""] * 16           # A..P
    rowcells[0] = name
    is_raf = (name == "Raf Hidalgo")
    for ci, srow in FUNNEL.items():
        if is_raf:
            rowcells[ci] = raf_idx.get(ci, "")
        else:
            rowcells[ci] = idx_tmpl(tab, srow)
    # % columns (relative ratios) — same for everyone, ref this row R
    rowcells[3]  = pct("C","B",R)  # D
    rowcells[5]  = pct("E","C",R)  # F
    rowcells[8]  = pct("H","G",R)  # I
    rowcells[10] = pct("J","H",R)  # K
    rowcells[12] = pct("L","J",R)  # M
    rowcells[15] = pct("O","N",R)  # P
    matrix.append(rowcells)

# ---- write A4:P53 + clear residual ----
rfill._retry(rc.update, matrix, "A4:P53", value_input_option="USER_ENTERED")
rfill._retry(rc.batch_clear, ["A54:P60"])
print("[write] A4:P53 (USER_ENTERED) + limpiado A54:P60 ; filas 1-3 intactas")

# ================= VERIFY =================
vf = rfill._retry(rc.get_values, "A1:P53", value_render_option="FORMULA")
vv = rfill._retry(rc.get_values, "A1:P53", value_render_option="FORMATTED_VALUE")

def is_err(s):
    s = str(s)
    return any(e in s for e in ["#REF!","#N/A","#ERROR!","#VALUE!","#NAME?","#DIV/0"])
errs = []
for ri in range(3, 53):           # rows 4..53
    for ci in range(1, 16):       # B..P
        val = vv[ri][ci] if ci < len(vv[ri]) else ""
        if is_err(val):
            errs.append((ri+1, cl(ci), str(vv[ri][0]), val))

names = [str(vv[ri][0]).strip() for ri in range(3,53) if str(vv[ri][0]).strip()]

# compare tab set vs CS
csf = sh.worksheet("Country Stats").get_values("A2:R51", value_render_option="FORMULA")
cs_tabs = set()
for row in csf:
    for c in range(1,len(row)):
        m = RE_TAB.search(str(row[c]))
        if m: cs_tabs.add(m.group(1)); break
final_tabs = set()
for ri in range(3,53):
    m = None
    for ci in range(1,16):
        mm = RE_TAB.search(str(vf[ri][ci]))
        if mm: m = mm.group(1); break
    if m: final_tabs.add(m)

print("\n========== VERIFICACION ==========")
print(f"celdas error/#REF!/texto en B4:P53: {len(errs)}")
for r,c,who,v in errs[:30]:
    print(f"   r{r} {c} ({who}): {v!r}")
print(f"\nconteo de reps (col A no vacia, r4-53): {len(names)}")
print(f"\ncomparacion set de tabs vs Country Stats:")
print(f"   Recruiting={len(final_tabs)}  CS={len(cs_tabs)}  "
      f"{'COINCIDEN EXACTO' if final_tabs==cs_tabs else 'DIFIEREN'}")
if final_tabs != cs_tabs:
    print(f"   solo Rec: {sorted(final_tabs-cs_tabs)}")
    print(f"   solo CS : {sorted(cs_tabs-final_tabs)}")

print("\nroster en orden:")
for ri in range(3,53):
    print(f"   r{ri+1}: {vv[ri][0]}")

# spot-check Jacob Dover + Raf
def show(nm):
    for ri in range(3,53):
        if str(vv[ri][0]).strip()==nm:
            cells = {cl(ci): (vv[ri][ci] if ci<len(vv[ri]) else "") for ci in range(0,16)}
            print(f"   {nm} (r{ri+1}): " + " ".join(f"{k}={v}" for k,v in cells.items()))
            return
print("\nspot-check:")
show("Jacob Dover")
show("Raf Hidalgo")

# % column sanity: D == C/B etc for a few rows
print("\n% columnas (chequeo D=C/B, F=E/C en 3 reps):")
def num(s):
    s=str(s).replace("%","").replace(",","")
    try: return float(s)
    except: return None
for nm in ["Kash Rai","Jacob Dover","Tony Chavez"]:
    for ri in range(3,53):
        if str(vv[ri][0]).strip()==nm:
            B,C,D,E,F = (num(vv[ri][x]) for x in (1,2,3,4,5))
            dc = (C/B*100) if B else None
            fc = (E/C*100) if C else None
            print(f"   {nm}: D={vv[ri][3]} (C/B={dc:.1f}% ) | F={vv[ri][5]} (E/C={fc:.1f}% )")
            break
print(f"\nbackup: {bpath}")
