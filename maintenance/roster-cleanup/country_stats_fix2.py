"""APPLY fix2 — wrap every metric cell (all rows except Raf) in LET+ISNUMBER so
each returns number-or-blank, never error/text. Backup first. Raf = read-only
diagnostic only (not written). Then verify."""
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
cs = sh.worksheet("Country Stats")

# ---------- 1. BACKUP ----------
backup = rfill._retry(cs.get_values, "A1:R53", value_render_option="FORMULA")
bpath = OUT / f"country_stats_backup_fix2_{TS}.json"
bpath.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"[1] backup -> {bpath.name}")

a1_val = rfill._retry(cs.get_values, "A1:A1")[0][0]
print(f"    A1 actual = {a1_val!r}")

# ---------- 2. build matrix ----------
COLMAP = {
    1: "Total Apps", 2: "New Internets", 3: "Upgrades", 4: "DTV", 5: "New Lines",
    6: "AVG Apps Per Active Headcount", 7: "AVG New INT Per Active Headcount",
    8: "Active Headcount on Tableau", 9: "Total Leads", 10: "Penetration Rate",
    12: "Expected Fiber Sales (120 days, 17wks)", 15: "0-30 Day Cancel Rate",
    16: "Activation /Approval %", 17: "0-30 Day Churn",
}
NCOLS = 18

def tmpl(tab, label):
    return (f"=IFERROR(LET(v, INDEX('{tab}'!$A$1:$ZZ$300,"
            f"MATCH(\"{label}\",'{tab}'!$B$1:$B$300,0),"
            f"MATCH($A$1,'{tab}'!$1:$1,0)), IF(ISNUMBER(v),v,\"\")),\"\")")

RE = re.compile(r"INDEX\('([^']+)'!")
cur = rfill._retry(cs.get_values, "A2:R51", value_render_option="FORMULA")

matrix = []
rewritten = 0
raf_kept = 0
for r in cur:
    r = (list(r) + [""] * NCOLS)[:NCOLS]
    colA = str(r[0]).strip()
    if colA.upper() == "RAFAEL HIDALGO":
        matrix.append(r)           # keep Raf verbatim (read-only)
        raf_kept += 1
        continue
    # find this row's tab from any existing metric formula
    tab = None
    for ci in COLMAP:
        m = RE.search(str(r[ci]))
        if m:
            tab = m.group(1)
            break
    if not tab:
        matrix.append(r)           # safety: leave untouched if unparseable
        continue
    row = [""] * NCOLS
    row[0] = colA
    for ci, lbl in COLMAP.items():
        row[ci] = tmpl(tab, lbl)
    matrix.append(row)
    rewritten += 1

print(f"[2] reescritas con LET+ISNUMBER: {rewritten} ; Raf mantenido: {raf_kept}")
assert len(matrix) == 50

# ---------- write A2:R51 ----------
rfill._retry(cs.update, matrix, "A2:R51", value_input_option="USER_ENTERED")
print("[3] escrito A2:R51 (USER_ENTERED)")

# ---------- Raf diagnostic (read-only) ----------
print("\n========== RAF — DIAGNOSTICO (read-only) ==========")
raf = sh.worksheet("Raf Hidalgo")
r1 = rfill._retry(raf.get_values, "A1:ZZ1")
r1 = r1[0] if r1 else []
def colletter(i):
    s = ""; i += 1
    while i:
        i, m = divmod(i - 1, 26); s = chr(65 + m) + s
    return s
target = a1_val
hits = [(i, colletter(i), v) for i, v in enumerate(r1) if str(v).strip() == target]
print(f"A1 objetivo = {target!r}")
print(f"row1 de 'Raf Hidalgo' contiene {target!r}? -> {'SI' if hits else 'NO'}")
for i, cl, v in hits:
    print(f"   en col {cl} (idx {i+1})")
# his current formula's date-match range
raf_b = str(backup[ [str(x[0]).strip().upper() for x in backup].index("RAFAEL HIDALGO") ][1])
print(f"formula actual Raf col B: {raf_b}")
mrange = re.search(r"MATCH\(\$A\$1,'Raf Hidalgo'!\$([A-Z]+)\$1:\$([A-Z]+)\$1", raf_b)
if mrange:
    c0, c1 = mrange.group(1), mrange.group(2)
    def coln(letters):
        n = 0
        for ch in letters:
            n = n * 26 + (ord(ch) - 64)
        return n
    lo, hi = coln(c0), coln(c1)
    print(f"rango de fecha de su formula: {c0}:{c1}  (cols {lo}..{hi})")
    if hits:
        hc = hits[0][0] + 1
        print(f"la fecha cae en col {hits[0][1]} (idx {hc}) -> "
              f"{'DENTRO del rango (alcanza)' if lo <= hc <= hi else 'FUERA del rango (se queda corto)'}")
# repeats / multi-block
allhits = [colletter(i) for i, v in enumerate(r1) if str(v).strip() == target]
print(f"repeticiones de {target!r} en row1 (multi-bloque): {len(allhits)} -> {allhits}")

# ---------- VERIFY ----------
vv = rfill._retry(cs.get_values, "A1:R51", value_render_option="FORMATTED_VALUE")
metric_cols = list(COLMAP.keys())
def is_num(s):
    s = str(s).strip().replace(",", "").replace("%", "").replace("$", "")
    if s == "":
        return None
    try:
        float(s); return True
    except ValueError:
        return False

nonnum = []
for ri in range(1, len(vv)):
    row = vv[ri]
    for ci in metric_cols:
        val = row[ci] if ci < len(row) else ""
        if is_num(val) is False:
            nonnum.append((ri + 1, colletter(ci), str(vv[ri][0]), val))

print("\n========== VERIFICACION ==========")
print(f"celdas metricas NO-numericas (ni blanco) en A1:R51: {len(nonnum)}")
for r, c, who, v in nonnum:
    print(f"   fila {r} col {c} ({who}): {v!r}")

print("\nSUM por columna (rows 2-51) — total / total sin Raf:")
raf_ri = [str(vv[i][0]).strip().upper() for i in range(len(vv))].index("RAFAEL HIDALGO")
for ci in metric_cols:
    tot = 0.0; tot_nr = 0.0; bad = False
    for ri in range(1, len(vv)):
        val = vv[ri][ci] if ci < len(vv[ri]) else ""
        n = is_num(val)
        if n is True:
            x = float(str(val).replace(",", "").replace("%", "").replace("$", ""))
            tot += x
            if ri != raf_ri:
                tot_nr += x
        elif n is False:
            bad = True
    lbl = COLMAP[ci]
    flag = "  <-- tiene texto/error" if bad else ""
    print(f"   col {colletter(ci):<2} {lbl[:34]:<34} sum={tot:>10.2f}  sin_Raf={tot_nr:>10.2f}{flag}")

print(f"\nbackup: {bpath}")
