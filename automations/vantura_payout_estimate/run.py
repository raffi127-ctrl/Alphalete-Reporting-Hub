"""One-shot: price a week of Carlos's ATT B2B order log on the office comp
sheet (AT&T B2B Commission Overview, effective 2026-08-24) — per rep, per
product, office total.

Carlos 2026-08-30: the flat estimate off the board's data tab missed the
add-ons — "Look through the order log again. I think you can see if auto
bill pays on there ... there's next up, extra, and you can see what each
line qualifies for." He's right: the FULL 47-column ORDERLOG export (the one
captainship_boards pulls every morning to output/captainship_boards/) carries
`Auto Bill Pay`, and the plan/package columns carry Next Up / Premium /
Advanced. This prices each line with those add-ons:

  WIRELESS port (CRU): IF 215 / OOF 295 non-BYOD, IF 170 / OOF 255 BYOD
    (CRU Total = base + the $35 CRU bonus, per the comp sheet)
    + $15 Next Up (non-BYOD, plan says Next w/o an explicit "w/o Next Up")
    + $15 Unlimited Premium  OR  + $10 Extra/Advanced (package name)
    + $10 ABP bonus (Auto Bill Pay = Y)
  WIRELESS port (IRU): 165 non-BYOD / 25 BYOD + the same add-ons' IRU rates
  NEW INTERNET: by speed (CRU 918/728/728/553/553/143; IRU 393/293/293/243/
    203/68) + $30 Internet ABP bonus when ABP = Y
  AIR/AWB: CRU 268 (+$100 ABP bonus when Y) / IRU AIA 100 (+$45 ABP when Y),
    plus the BASELINE churn adjustment (+$20 CRU / +$10 IRU — Carlos:
    "assume the base payout for churn"; wireless baseline = $0)
  VOICE: $88 CRU per line

NOT included (not in the order log): tiered volume bonus, MCOE, road trip.

Scope = reps on the Vantura Sales Board's B2B campaign rows (same roster the
fill uses). Reads the newest output/captainship_boards/orderlog_*.csv —
MUST RUN ON LUCY 2, where that file lands every morning. Results are WRITTEN
to the Mini Control workbook, tab 'Pay Estimate' (never the live board), so
they can be read remotely.

  python -m automations.vantura_payout_estimate.run                # newest csv
  python -m automations.vantura_payout_estimate.run --week 2026-08-24
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import re
import sys
from pathlib import Path

CSV_DIR = Path(__file__).resolve().parents[2] / "output" / "captainship_boards"
BOARD_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
CONTROL_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
OUT_TAB = "Pay Estimate"

INTERNET_CRU = {5000: 918, 2000: 728, 1000: 728, 500: 553, 300: 553, 100: 143}
INTERNET_IRU = {5000: 393, 2000: 293, 1000: 293, 500: 243, 300: 203, 100: 68}
AIR_CHURN_BASE = {"CRU": 20, "IRU": 10}     # baseline tier 3 (comp sheet)


def _n(s) -> str:
    return " ".join(str(s or "").split()).strip()


# The export writes legal first names, the board the name the rep goes by —
# same aliasing vantura_orderlog_sales uses (Will/William cost the first run
# two whole reps).
_FIRST_ALIASES = {"william": "will", "nicholas": "nick", "jeffrey": "jeff"}


def norm_name(n: str):
    t = re.sub(r"[^a-z ]", "", n.lower()).split()
    if not t:
        return ("", "")
    return (_FIRST_ALIASES.get(t[0], t[0]), t[-1])


def board_b2b_reps():
    from automations.recruiting_report.fill import open_by_key
    g = open_by_key(BOARD_ID).worksheet("Sales Board").get_all_values()
    reps = set()
    for r in g[4:]:
        name = (r[1] if len(r) > 1 else "").strip()
        camp = (r[11] if len(r) > 11 else "").strip()
        if name.startswith("AT&T"):
            break
        if name and camp == "B2B":
            reps.add(norm_name(name))
    return reps


def price(row):
    """-> (amount, label, addon_notes) for one export line, or (None, why, '')."""
    prod = _n(row.get("Product Type (Broken Out)")).upper()
    cru = _n(row.get("CRU/IRU")).upper() or "CRU"
    abp = _n(row.get("Auto Bill Pay")).upper() in ("Y", "YES")
    pkg = _n(row.get("Package"))
    wip = _n(row.get("Wireless Installment Plan")).upper()
    oof = _n(row.get("IF/OOF")).upper() == "OOF"
    tn = _n(row.get("spe.TN Type")).lower()
    byod = wip == "BYOD"
    notes = []

    if prod == "WIRELESS":
        if tn == "port":
            if cru == "CRU":
                amt = (255 if byod else 295) if oof else (170 if byod else 215)
            else:
                amt = 25 if byod else 165
            label = f"Port {'BYOD' if byod else 'Non-BYOD'} {cru}"
        elif tn == "new":
            amt, label = (60 if cru == "CRU" else 25), f"New Line {cru}"
        elif tn == "upgrade":
            amt, label = 30, f"Upgrade {cru}"
            if abp:
                notes.append("abp-skipped(upgrade)")
                abp = False                    # ABP bonus is non-upgrade only
        elif "TABLET" in pkg.upper() or "WATCH" in pkg.upper():
            amt, label = 25, "Tablet/Wearable"
        else:
            return None, f"WIRELESS tn={tn!r}", ""
        if "NEXT" in wip and "W/O NEXT UP" not in wip and not byod:
            amt += 15
            notes.append("next-up+15")
        pu = pkg.upper()
        if "PREMIUM" in pu:
            amt += 15
            notes.append("premium+15")
        elif "ADVANCED" in pu or "EXTRA" in pu:
            amt += 10
            notes.append("extra/adv+10")
        if abp and tn != "upgrade":
            amt += 10
            notes.append("abp+10")
        return amt, label, ",".join(notes)

    if prod == "NEW INTERNET":
        m = re.search(r"(\d{3,4})", pkg)
        spd = int(m.group(1)) if m else 0
        table = INTERNET_CRU if cru == "CRU" else INTERNET_IRU
        amt = table.get(spd, 143 if cru == "CRU" else 68)
        if abp:
            amt += 30
            notes.append("int-abp+30")
        return amt, f"Internet {spd or '?'} {cru}", ",".join(notes)

    if prod == "AIR/AWB":
        amt = 268 if cru == "CRU" else 100
        if abp:
            amt += 100 if cru == "CRU" else 45
            notes.append("air-abp")
        amt += AIR_CHURN_BASE[cru]
        notes.append(f"churn-base+{AIR_CHURN_BASE[cru]}")
        return amt, f"AIR {cru}", ",".join(notes)

    if prod == "VOICE":
        return (88 if cru == "CRU" else 0), "VoIP", ""

    return None, f"prod={prod!r}", ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="Monday YYYY-MM-DD (default: newest csv)")
    ap.add_argument("--csv", help="explicit csv path")
    ap.add_argument("--headers", action="store_true",
                    help="just print every column of the export + sample "
                         "values (looking for a tier/volume column)")
    a = ap.parse_args(argv)

    if a.csv:
        src = Path(a.csv)
    else:
        pat = (f"orderlog_{a.week}_*.csv" if a.week else "orderlog_*.csv")
        cands = sorted(CSV_DIR.glob(pat))
        if not cands:
            print(f"no {pat} in {CSV_DIR} — run captainship_boards first")
            return 1
        src = cands[-1]
    print(f"pricing {src.name}")

    from automations.att_order_log import clean

    if a.headers:
        rows = list(clean.load_rows(str(src), owner_prefix=None))
        cols = list(rows[0].keys()) if rows else []
        print(f"{len(cols)} columns:")
        for c in cols:
            vals = [str(r.get(c) or "").strip() for r in rows[:400]]
            uniq = sorted({v for v in vals if v})[:4]
            print(f"  {c!r}: {uniq}")
        return 0

    reps_ok = board_b2b_reps()

    per_rep = collections.defaultdict(float)
    per_prod = collections.defaultdict(lambda: [0, 0.0])
    addon_totals = collections.Counter()
    unpriced = collections.Counter()
    days = set()
    for r in clean.load_rows(str(src), owner_prefix=None):
        rep = _n(r.get("Rep"))
        if not rep or norm_name(rep) not in reps_ok:
            continue
        try:
            u = float(r.get("Unit Count") or 0)
        except (TypeError, ValueError):
            continue
        if not u:
            continue
        amt, label, notes = price(r)
        if amt is None:
            unpriced[label] += u
            continue
        days.add(_n(r.get("sp.Order Date (copy)")))
        per_rep[rep.title()] += amt * u
        per_prod[label][0] += u
        per_prod[label][1] += amt * u
        for nt in notes.split(","):
            if nt:
                addon_totals[nt] += u

    lines = [["Vantura B2B pay estimate (office comp sheet eff 8/24, "
              "baseline churn)", src.name, dt.datetime.now().isoformat(timespec='seconds')],
             ["days", ", ".join(sorted(days))], [],
             ["REP", "REVENUE"]]
    for k, v in sorted(per_rep.items(), key=lambda kv: -kv[1]):
        lines.append([k, round(v, 2)])
    lines += [[], ["OFFICE TOTAL", round(sum(per_rep.values()), 2)], [],
              ["PRODUCT", "UNITS", "REVENUE"]]
    for k, (n, v) in sorted(per_prod.items(), key=lambda kv: -kv[1][1]):
        lines.append([k, n, round(v, 2)])
    lines += [[], ["ADD-ON", "UNITS"]]
    for k, n in addon_totals.most_common():
        lines.append([k, n])
    if unpriced:
        lines += [[], ["UNPRICED", "UNITS"]]
        for k, n in unpriced.items():
            lines.append([k, n])

    for row in lines:
        print("  " + "  |  ".join(str(c) for c in row))

    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(CONTROL_ID)
    try:
        ws = sh.worksheet(OUT_TAB)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=OUT_TAB, rows=120, cols=6)
    _retry(ws.update, values=lines, range_name="A1")
    print(f"written to '{OUT_TAB}' on the Mini Control workbook")
    return 0


if __name__ == "__main__":
    sys.exit(main())
