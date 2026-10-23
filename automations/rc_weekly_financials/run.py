"""Friday R&C weekly financials — "Carlos' Finances" and "Hidalgo's finances" (Raf).

Mirrors the two Looms (2026-10-22):
  1. insert cells + shift right on the finance block only (Carlos rows 1..TOTAL $$$$$, Raf rows
     Fixed Expenses..Personal life style), copy last week into the new column, set the WE header
     (= the coming Sunday)
  2. fill every row we have a source for, by ROW LABEL (never by position)
  3. leave the rows only a person can fill blank and list them
  4. PNG of labels + the 4 newest weeks for Slack

  python -m automations.rc_weekly_financials.run pull  [--we 2026-10-25]          # all sources -> JSON
  python -m automations.rc_weekly_financials.run dup   --who raf [--we ...]        # test copy of the tab
  python -m automations.rc_weekly_financials.run fill  --who raf [--tab "..."] [--set "Indeed=-14471.90"]
                                                       [--prior "Indeed=-14454.06"] [--dry-run]
  python -m automations.rc_weekly_financials.run shot  --who raf [--tab "..."]
Bash must run `pull` outside the sandbox (Tableau browser). Outputs: output/rc_weekly_financials/ (git-ignored).
See RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from automations.rc_bank_totals import run as bank  # noqa: E402  (sheets(), creds(), tiller(), Tiller row maps)

OUT = REPO / "output" / "rc_weekly_financials"   # git-ignored: money never goes in the repo
EPOCH = dt.date(1899, 12, 30)

VANTURA = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"     # Vantura Master Sales Board, tab P&L 2026
AIO_RAF = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"     # All in One - local office Raf, tab RAF PNL 2026 (NEW)
ARS = "14yfjKXm00Lz_ewF0_hMFEo6ZVKgZOAizXl3GmwfTGHk"         # All in One - ARS, tab ARS PNL

PEOPLE = {
    "carlos": {"sheet": bank.PEOPLE["carlos"]["sheet"], "tab": "Carlos' Finances",
               "first": "Carlos' Monthly Expenses", "last": "TOTAL $$$$$",
               "slack": "Carlos + Raf"},
    "raf": {"sheet": bank.PEOPLE["raf"]["sheet"], "tab": "Hidalgo's finances",
            "first": "Fixed Expenses", "last": "Personal life style",
            "slack": "Maud first, then Raf + Megan"},
}

# Rows a person fills (no source this Mac can read). They're cleared in the new column and listed.
MANUAL = {
    "carlos": {},
    "raf": {
        "Support Staff Bonus (Maud, Twaddle)": "Slack DM Dylan ↔ Raf, 'captainship' bonus for the WE two weeks back",
        "Indeed": "Double Entry email 'Alphalete Marketing Inc (Rafael Hidalgo) Texas' (Tue) — highlighted Indeed; also update last week's column",
        "Recruiting Bonuses (Aisha)": "Apex",
        "Zach's Pay (overrides)": "you fill it",
        "Zach's Pay (true up + taxes) - 22/24": "Slack DM Raf ↔ Zach, last one sent",
    },
}
# Rows kept as copied from last week but worth a look.
CHECK = {
    "carlos": {
        "Maud's Bonus": "not in Apex — kept",
        "Indeed Charges … Investment into local office": "from his month tab one week back — see NOTES if it wasn't finished",
    },
    "raf": {
        "Office Space": "Loom says it changes — confirm",
        "Bas Overrides": "set to 0 — one lands every 4 weeks",
    },
}


def _n(s) -> str:
    return " ".join(str(s or "").lower().split())


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").replace("$", "").replace(",", "").strip()
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()")
    try:
        return -float(t) if neg else float(t)
    except ValueError:
        return None


def coming_sunday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(6 - today.weekday()) % 7)


def hdr(d: dt.date) -> str:
    return f"WE {d.month}.{d.day}"


def period_of(week: dt.date) -> int:
    """Tableau 4-week period for a processed-week Sunday (2026: P1 starts 1/4, P10 = 9/13–10/4)."""
    jan1 = dt.date(week.year, 1, 1)
    first_sun = jan1 + dt.timedelta(days=(6 - jan1.weekday()) % 7)
    return (week - first_sun).days // 28 + 1


# ---------------------------------------------------------------- sheet sources
def _serial_cols(row) -> dict:
    return {EPOCH + dt.timedelta(days=int(x)): j for j, x in enumerate(row) if isinstance(x, (int, float)) and x > 40000}


def vantura(week: dt.date) -> dict:
    """Carlos: Local Office Profits + Captainship for the week prior, from Vantura 'P&L 2026'."""
    v = bank.sheets().values().get(spreadsheetId=VANTURA, range="'P&L 2026'!A1:Z12").execute().get("values", [])
    want = f"WE {week.month}/{week.day}"
    j = next((i for i, h in enumerate(v[0]) if str(h).strip() == want), None)
    if j is None:
        print(f"  Vantura P&L 2026: no {want!r} column")
        return {}
    rows = {_n(r[0]): r for r in v if r}
    pick = lambda lbl: _num((rows.get(_n(lbl), []) + [""] * 30)[j])  # noqa: E731
    lo = next((pick(r[0]) for r in v if r and _n(r[0]).startswith("total gross profit (no captain")), None)
    cap = next((pick(r[0]) for r in v if r and _n(r[0]) == "captainship bonus"), None)
    print(f"  Vantura {want}: local office {lo}, captainship {cap}")
    return {"Local Office Profits (week prior)": lo, "Captainship (week prior)": cap}


def carlos_red_rows(week: dt.date) -> tuple[dict, list]:
    """Carlos rows 30-36 for the column AFTER `week`, from that week in his month tab ('September 2026', …).
    Same math as output/carlos_pnl/finances.py: Investment = -(Carlos-only weekly - travel - indeed - 850 - rent).
    Rent = a Carlos-only 'Online ACH Payment' >= $5,000 dated in the week (flagged for Maud to confirm)."""
    s, sid = bank.sheets(), PEOPLE["carlos"]["sheet"]
    want, notes = hdr(week), []
    titles = [sh["properties"]["title"] for sh in s.get(spreadsheetId=sid, fields="sheets.properties.title").execute()["sheets"]]
    for tab in [t for t in titles if re.match(r"^[A-Z][a-z]+ \d{4}$", t)][:3]:   # newest month tabs first
        v = s.values().get(spreadsheetId=sid, range=f"'{tab}'!A1:L2500", valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
        v = [r + [""] * 12 for r in v]
        top = next((i for i, r in enumerate(v) if str(r[7]).startswith("WE ") and r[4] == "Profits"), None)
        if top is None or want not in [str(x).strip() for x in v[top][7:12]]:
            continue
        j = 7 + [str(x).strip() for x in v[top][7:12]].index(want)
        lab = {_n(r[2]): i for i, r in enumerate(v) if i > top and str(r[2]).strip()}
        get = lambda name, c: v[lab[_n(name)]][c] if _n(name) in lab else ""  # noqa: E731
        indeed, food, travel = get("Indeed Charges", j), get("Food/Team Nights", j), get("Travel/Entertainment", j)
        bot = next(i for i, r in enumerate(v) if i > top and str(r[5]).strip().startswith("WE ") and not str(r[4]).strip())
        bj = 5 + [str(x).strip() for x in v[bot][5:10]].index(want)
        outside, co = get("Outside Deal - Weekly", bj), get("CARLOS ONLY Total Weekly", bj)
        if not all(isinstance(x, (int, float)) for x in (indeed, food, travel, outside, co)):
            notes.append(f"Carlos red rows: {tab} {want} isn't finished yet — kept last week's placeholders")
            return {}, notes
        lo, rent = week - dt.timedelta(days=6), 0.0
        for r in v:
            if isinstance(r[2], (int, float)) and r[2] > 40000 and str(r[4]).strip().lower() == "x" \
                    and str(r[1]).lower().startswith("online ach pay") and isinstance(r[3], (int, float)) and r[3] >= 5000 \
                    and lo <= EPOCH + dt.timedelta(days=int(r[2])) <= week:
                rent += r[3]
        if rent:
            notes.append(f"Carlos Rent/Utilities: found {rent:,.2f} (Online ACH Payment in {want}) — confirm it's rent")
        out = {"Indeed Charges": round(indeed, 2), "Outside Deals": -round(outside, 2), "ARS - interviewers": -850,
               "Rent/Utilities": -round(rent, 2) if rent else 0, "Food/Team Nights": round(food, 2), "Travel/Entertainment": round(travel, 2),
               "Investment into local office": round(-(co + travel + indeed - 850 - rent), 2)}
        print(f"  {tab} {want} -> red rows {out}")
        return out, notes
    notes.append(f"Carlos red rows: no month tab has {want} yet — kept last week's placeholders")
    return {}, notes


CARLOS_PNL = "1ngQtKRNeuGV_FDBp-d9boZmxp6cO3T4IKa7k2NdiLq0"   # Carlos Business & Personal P&L (carlos_payroll_pull writes Apex here Thursdays)
APEX_BONUS = {"Nico's Bonus": "nicolas murrugarra", "Sebastian's Bonus": "sebastian avellaneda", "Cinthya's Bonus": "cinthya reyes"}


def carlos_apex(we: dt.date) -> tuple[dict, list]:
    """Carlos's Apex rows from the Thursday payroll pull: the pay period ending one week before the WE.
    Personal Pay = -(owner gross x 1.12); NPA = -(owner net-pay additions); bonuses = -(that rep's net-pay addition)."""
    end = we - dt.timedelta(days=7)
    s = bank.sheets()
    v = s.values().get(spreadsheetId=CARLOS_PNL, range="'Apex Net Pay Detail'!A1:J400",
                       valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    hdr_ = [_n(h) for h in v[0]]
    ie, isec, iname, igross, iadd = (hdr_.index(k) for k in ("period end (sun)", "section", "name", "gross pay", "net pay addition"))
    as_date = lambda x: EPOCH + dt.timedelta(days=int(x)) if isinstance(x, (int, float)) else dt.datetime.strptime(str(x).strip(), "%b %d, %Y").date()  # noqa: E731
    rows = [r for r in v[1:] if len(r) > iadd and str(r[ie]).strip() and as_date(r[ie]) == end]
    if not rows:
        summ = s.values().get(spreadsheetId=CARLOS_PNL, range="'Payroll (Apex)'!B2:B3").execute().get("values", [])
        return {}, [f"carlos Apex: no period ending {end} in 'Apex Net Pay Detail' yet (newest: {summ[0][0] if summ else '?'}) — Apex rows kept from last week"]
    out = {label: 0 for label in APEX_BONUS}
    owner = [r for r in rows if _n(r[isec]) == "owner"]
    if owner:
        out["Personal Pay"] = -round((_num(owner[0][igross]) or 0) * 1.12, 2)
        out["NPA - Owner's Draw"] = -round(sum(_num(r[iadd]) or 0 for r in owner), 2)
    for label, name in APEX_BONUS.items():
        out[label] = -round(sum(_num(r[iadd]) or 0 for r in rows if _n(r[iname]) == name), 2)
    print(f"  Apex period ending {end}: {out}")
    return out, []


def raf_indeed(we: dt.date) -> tuple[dict, dict, list]:
    """Raf Indeed from Double Entry (same API the financial_report pull uses; login comes from the saved creds
    file, OTP from the reporting inbox). New column WE S = Double Entry week ending Sat S-8; last week's column = S-15."""
    try:
        from automations.financial_report.web_source import fetch_office_history
        offices, _ = fetch_office_history("rafael hidalgo", weeks_back=6, verbose=False)
    except Exception as e:  # noqa: BLE001 — missing login / OTP inbox on this machine
        return {}, {}, [f"raf Indeed: Double Entry not reachable here ({str(e).splitlines()[0][:110]}) — fill it from the Tuesday email"]
    offs = offices.values() if isinstance(offices, dict) else offices
    ind = {}
    for o in offs:
        for k, vals in o.get("metrics", {}).items():
            if k.strip().upper() == "INDEED":
                for d, x in vals.items():
                    if x is not None:
                        ind[d] = ind.get(d, 0) + x
    new, old = we - dt.timedelta(days=8), we - dt.timedelta(days=15)
    if new not in ind:
        return {}, {}, [f"raf Indeed: Double Entry has no week ending {new} (has {sorted(map(str, ind))})"]
    cur = {"Indeed": -round(abs(ind[new]), 2)}
    prev = {"Indeed": -round(abs(ind[old]), 2)} if old in ind else {}
    print(f"  Double Entry Indeed: wk {new} {ind[new]:,.2f}" + (f", wk {old} {ind[old]:,.2f}" if prev else ""))
    return cur, prev, []


def raf_local_office(week: dt.date) -> dict:
    """Raf: 'Raf's Net Profit from Local Office' for the week prior, RAF PNL 2026 (NEW)."""
    v = bank.sheets().values().get(spreadsheetId=AIO_RAF, range="'RAF PNL 2026 (NEW)'!A1:FZ60",
                                   valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    j = _serial_cols(v[0]).get(week)
    r = next((r for r in v if r and _n(r[0]).startswith("raf's net profit from local office")), None)
    if j is None or r is None or j >= len(r) or not isinstance(r[j], (int, float)):
        print(f"  RAF PNL 2026 (NEW): nothing for {week}")
        return {}
    print(f"  RAF PNL WE {week:%m/%d}: local office {r[j]:,.2f}")
    return {"Local Office Gross Profits": round(r[j], 2)}


def ars(week: dt.date) -> dict:
    """Raf: ARS PNL Gross Profit + 'Raf covers' for the SAME week."""
    v = bank.sheets().values().get(spreadsheetId=ARS, range="'ARS PNL'!A1:ZZ340",
                                   valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    j = _serial_cols(v[0]).get(week)
    if j is None:
        print(f"  ARS PNL: no WE {week} block")
        return {}
    got = {}
    for r in v[290:]:
        lbl = _n(r[j + 1]) if len(r) > j + 1 else ""
        val = r[j + 2] if len(r) > j + 2 else ""
        if lbl == "gross profit" and isinstance(val, (int, float)):
            got["ARS (PNL Shows)"] = round(val, 2)
        elif lbl == "raf covers" and isinstance(val, (int, float)):
            got["Money Given for Interviewers"] = -round(abs(val), 2)
    print(f"  ARS PNL WE {week:%m/%d}: {got}")
    return got


def loans() -> dict:
    """Raf: Kia + Lambo = last 'Money Owed left' in Running TOTALS 2026 (loan tables)."""
    v = bank.sheets().values().get(spreadsheetId=PEOPLE["raf"]["sheet"], range="'Running TOTALS 2026'!A40:H200",
                                   valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    head = next(i for i, r in enumerate(v) if r and _n(r[0]) == "lambo loan")
    out = {}
    for label, col in (("Lambo", 2), ("Kia", 6)):
        vals = [r[col] for r in v[head + 1:] if len(r) > col and isinstance(r[col], (int, float))]
        if vals:
            out[label] = -round(vals[-1], 2)
    print(f"  loans: {out}")
    return out


def banks(who: str) -> dict:
    """Tiller balances (via rc_bank_totals) -> Total CC Debt (negative) + Money in the Bank."""
    path = bank.tiller(who)
    b = json.loads(path.read_text())
    accts = bank.PEOPLE[who]["tiller_rows"]
    labels = list(accts.values())
    cards = [l for l in labels if "CC" in l or l.startswith(("Amex", "AMEX", "BOFA", "Capital"))]
    cash = [l for l in labels if l not in cards and l != "ARS"]   # Raf: Chase total minus ARS
    miss = [l for l in labels if l not in b and l != "ARS"]
    if miss:
        print(f"  {who}: MISSING balances {miss} — totals left blank")
        return {}
    print(f"  {who}: cards {cards}\n  {who}: cash  {cash}")
    return {"Total CC Debt": -round(sum(b[l] for l in cards), 2),
            "Money in the Bank": round(sum(b[l] for l in cash), 2)}


# ---------------------------------------------------------------- Tableau
def tableau(weeks: list[dt.date]) -> dict:
    """One Tableau session: SFDC security (both), ORG override summary (both), Raf ATT override, Raf captain."""
    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    from automations.shared.tableau_patchright import tableau_session, download_crosstab_patchright
    from automations.override_bulletin import pulls as P
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"security": {}, "org": {"carlos": {}, "raf": {}}, "att": {}, "captain": {}}
    periods = sorted({period_of(w) for w in weeks})
    with tableau_session(headless=True, verbose=False) as page:
        f = OUT / "_sfdc_balance.csv"
        try:
            download_crosstab_patchright(bank.LEDGER_VIEW, "SFDC Total Balance", f, page=page, verbose=False)
            for who, owner in bank.OWNERS.items():
                amt = next((_num(r[2]) for r in P.read_crosstab(f)[1:] if len(r) > 2 and owner in _n(r[1])), None)
                if amt is not None:
                    res["security"][who] = amt
        except Exception as e:  # noqa: BLE001
            print(f"  SFDC balance: {str(e)[:120]}")
        for n in periods:
            lab = f"Period {weeks[0].year}-{n}"
            f = OUT / f"_org_P{n}.csv"
            try:
                download_crosstab_patchright(P._with_filter(P.ORG_SUMMARY_VIEW, "Period", lab), P.ORG_SUMMARY_SHEET,
                                             f, page=page, verbose=False)
                rows = P.read_crosstab(f)
                for w in P.summary_weeks(rows):
                    m, d, y = w.split(".")
                    wk = dt.date(2000 + int(y), int(m), int(d))
                    o = P.parse_override_summary(rows, f"{m}/{d}/20{y}")
                    for who, owner in bank.OWNERS.items():
                        if owner in o:
                            res["org"][who][wk.isoformat()] = o[owner]
            except Exception as e:  # noqa: BLE001
                print(f"  ORG override summary {lab}: {str(e)[:120]}")
            f = OUT / f"_raf_bonus_P{n}.csv"
            for cand in P.period_candidates(lab):
                try:
                    download_crosstab_patchright(P._with_filter(P.RAF_BONUS_VIEW, "Period", cand), P.RAF_BONUS_SHEET,
                                                 f, page=page, verbose=False)
                except Exception as e:  # noqa: BLE001
                    print(f"  Raf override bonus {cand}: {str(e)[:100]}")
                    continue
                res["att"].update(raf_bonus_weeks(P.read_crosstab(f)))
                break
        try:
            cap = P.dd_captain_overrides(["rafael hidalgo"], OUT / "_dd_org.csv", page=page, verbose=False)
            for k, amt in cap.get("rafael hidalgo", {}).items():
                m, d, y = k.split(".")
                res["captain"][dt.date(2000 + int(y), int(m), int(d)).isoformat()] = amt
        except Exception as e:  # noqa: BLE001
            print(f"  DD captain: {str(e)[:120]}")
    print(f"  tableau: {json.dumps(res, indent=1)}")
    return res


def raf_bonus_weeks(rows) -> dict:
    """{week iso: Raf Payout Total} from the 'Payout- Raf wow' crosstab (week columns are dates)."""
    from automations.override_bulletin.pulls import _WK_HDR
    cols = {}
    for r in rows[:8]:
        for i, c in enumerate(r):
            m = _WK_HDR.match(str(c).strip())
            if m:
                y = int(m.group(3)); y += 2000 if y < 100 else 0
                cols[i] = dt.date(y, int(m.group(1)), int(m.group(2))).isoformat()
        if cols:
            break
    tot = next((r for r in rows if any("raf payout total" in _n(c) for c in r[:3])), None)
    if not tot:
        return {}
    return {wk: _num(tot[i]) for i, wk in cols.items() if i < len(tot) and _num(tot[i]) is not None}


# ---------------------------------------------------------------- pull
def pull(we: dt.date) -> Path:
    prior, before = we - dt.timedelta(days=7), we - dt.timedelta(days=14)
    print(f"WE {we} (week prior {prior}, update {before})")
    tab = tableau([prior, before])
    data = {"we": we.isoformat(), "carlos": {}, "raf": {}, "prior": {"carlos": {}, "raf": {}}}
    c, r = data["carlos"], data["raf"]
    c["Maud"] = 0
    c.update(vantura(prior))
    c["Overrides"] = 0
    c.update(banks("carlos"))
    red, notes = carlos_red_rows(prior)
    c.update(red)
    apex, n1 = carlos_apex(we)
    c.update(apex)
    notes += n1
    r.update(ars(we))
    r.update(raf_local_office(prior))
    r.update(loans())
    r.update(banks("raf"))
    ind_new, ind_prev, n2 = raf_indeed(we)
    r.update(ind_new)
    notes += n2
    if ind_prev:
        data["prior"]["raf"].setdefault(hdr(prior), {}).update(ind_prev)
    r["NC over rides"] = 0
    r["ATT Program over ride"] = 0
    r["Bas Overrides"] = 0
    dd_week = (we - dt.timedelta(days=1)).isoformat()   # the DD week showing on Friday = Saturday before the WE
    if dd_week in tab["captain"]:
        r["Captainship"] = tab["captain"][dd_week]
    else:
        print(f"  Raf captain: no DD week {dd_week} yet (have {sorted(tab['captain'])}) — row kept from last week")
    if tab["security"].get("carlos") is not None:
        c["Money in Security"] = tab["security"]["carlos"]
    if tab["security"].get("raf") is not None:
        r["Money in Security"] = tab["security"]["raf"]
    for wk in (prior, before):
        k = wk.isoformat()
        if k in tab["org"]["carlos"]:
            data["prior"]["carlos"].setdefault(hdr(wk), {})["Overrides"] = tab["org"]["carlos"][k]
        if k in tab["org"]["raf"]:
            data["prior"]["raf"].setdefault(hdr(wk), {})["NC over rides"] = tab["org"]["raf"][k]
        if k in tab["att"]:
            data["prior"]["raf"].setdefault(hdr(wk), {})["ATT Program over ride"] = tab["att"][k]
    data["tableau_raw"] = tab
    data["notes"] = notes
    for n in notes:
        print(f"  NOTE {n}")
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"values_{we.isoformat()}.json"
    out.write_text(json.dumps(data, indent=2))
    print(f"saved {out}")
    return out


# ---------------------------------------------------------------- sheet ops
def _meta(s, sid: str, title: str) -> dict:
    for sh in s.get(spreadsheetId=sid, fields="sheets.properties").execute()["sheets"]:
        if sh["properties"]["title"] == title:
            return sh["properties"]
    sys.exit(f"tab {title!r} not found")


def _block(s, p: dict, tab: str):
    """(rows, first_row, last_row, newest_col_idx) of the finance block — found by label, not position."""
    v = s.values().get(spreadsheetId=p["sheet"], range=f"'{tab}'!A1:Z400", valueRenderOption="FORMULA").execute()["values"]
    first = next(i for i, r in enumerate(v, 1) if r and _n(r[0]) == _n(p["first"]))
    last = next(i for i, r in enumerate(v, 1) if i > first and r and _n(r[0]).startswith(_n(p["last"])))
    head = v[first - 1]
    col = next(j for j, x in enumerate(head) if re.match(r"^WE \d+\.\d+$", str(x).strip()))
    return v, first, last, col


def dup(who: str, we: dt.date) -> str:
    s, p = bank.sheets(), PEOPLE[who]
    src = _meta(s, p["sheet"], p["tab"])
    name = f"{p['tab']} (TEST {hdr(we)})"
    s.batchUpdate(spreadsheetId=p["sheet"], body={"requests": [{"duplicateSheet": {
        "sourceSheetId": src["sheetId"], "insertSheetIndex": src["index"] + 1, "newSheetName": name}}]}).execute()
    print(f"  {who}: made test tab {name!r}")
    return name


def _col(j: int) -> str:
    out = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        out = chr(65 + r) + out
    return out


def fill(who: str, we: dt.date, tab: str | None, values: dict, prior: dict, dry: bool) -> None:
    s, p = bank.sheets(), PEOPLE[who]
    tab = tab or p["tab"]
    gid = _meta(s, p["sheet"], tab)["sheetId"]
    v, first, last, col = _block(s, p, tab)
    newest = str(v[first - 1][col]).strip()
    label_row = {_n(r[0]): i for i, r in enumerate(v, 1) if first < i <= last and r and str(r[0]).strip()}
    print(f"{who} / {tab!r}: block rows {first}-{last}, newest column {_col(col)} = {newest!r}")
    if newest == hdr(we):
        print(f"  {hdr(we)} is already there — refreshing it in place (no new column)")
    elif dry:
        print(f"  would insert cells at {_col(col)}{first}:{_col(col)}{last} (shift right) and copy {newest!r} into it")
    else:
        reqs = [
            {"insertRange": {"range": {"sheetId": gid, "startRowIndex": first - 1, "endRowIndex": last,
                                       "startColumnIndex": col, "endColumnIndex": col + 1}, "shiftDimension": "COLUMNS"}},
            {"copyPaste": {"source": {"sheetId": gid, "startRowIndex": first - 1, "endRowIndex": last,
                                      "startColumnIndex": col + 1, "endColumnIndex": col + 2},
                           "destination": {"sheetId": gid, "startRowIndex": first - 1, "endRowIndex": last,
                                           "startColumnIndex": col, "endColumnIndex": col + 1},
                           "pasteType": "PASTE_NORMAL"}},
        ]
        s.batchUpdate(spreadsheetId=p["sheet"], body={"requests": reqs}).execute()
        print(f"  inserted new column {_col(col)} (copy of {newest!r})")
        v, first, last, col = _block(s, p, tab)
    L = _col(col)
    data = [{"range": f"'{tab}'!{L}{first}", "values": [[hdr(we)]]}]
    todo = []
    for label in MANUAL[who]:
        i = label_row.get(_n(label))
        if i and _n(label) not in {_n(k) for k in values}:
            data.append({"range": f"'{tab}'!{L}{i}", "values": [[""]]})
            todo.append(f"{label} — {MANUAL[who][label]}")
    for label, val in values.items():
        i = label_row.get(_n(label))
        if i is None:
            print(f"  NO ROW for {label!r}")
            continue
        if val is None:
            todo.append(f"{label} — source had no number")
            continue
        cur = (v[i - 1] + [""] * (col + 1))[col]
        if str(cur).startswith("="):
            print(f"  skip {label!r} (formula row)")
            continue
        data.append({"range": f"'{tab}'!{L}{i}", "values": [[val]]})
        print(f"  {L}{i:<4} {label:<40} {val:>14,.2f}")
    head = v[first - 1]
    for wk_hdr, vals in prior.items():
        j = next((k for k, x in enumerate(head) if k != col and str(x).strip() == wk_hdr), None)
        if j is None:
            print(f"  no {wk_hdr!r} column for the prior-week update")
            continue
        for label, val in vals.items():
            i = label_row.get(_n(label))
            if i is None:
                continue
            old = (v[i - 1] + [""] * (j + 1))[j]
            data.append({"range": f"'{tab}'!{_col(j)}{i}", "values": [[val]]})
            print(f"  {_col(j)}{i:<4} {label} ({wk_hdr}): {old} -> {val:,.2f}")
    if not dry:
        s.values().batchUpdate(spreadsheetId=p["sheet"], body={"valueInputOption": "USER_ENTERED", "data": data}).execute()
        print(f"  wrote {len(data)} cells")
    print("  FOR YOU TO FILL:" if todo else "  nothing left blank")
    for t in todo:
        print(f"    - {t}")
    print("  CHECK (kept from last week):")
    for k, why in CHECK[who].items():
        print(f"    - {k} — {why}")


def shot(who: str, tab: str | None) -> Path:
    import fitz  # PyMuPDF
    from google.auth.transport.requests import AuthorizedSession
    s, p = bank.sheets(), PEOPLE[who]
    tab = tab or p["tab"]
    gid = _meta(s, p["sheet"], tab)["sheetId"]
    _, first, last, col = _block(s, p, tab)
    rng = f"A{first}:{_col(col + 3)}{last}"
    url = (f"https://docs.google.com/spreadsheets/d/{p['sheet']}/export?format=pdf&gid={gid}&range={rng}"
           f"&portrait=true&fitw=true&gridlines=true&printtitle=false&sheetnames=false&pagenum=UNDEFINED"
           f"&top_margin=0.2&bottom_margin=0.2&left_margin=0.2&right_margin=0.2")
    r = AuthorizedSession(bank.creds()).get(url)
    r.raise_for_status()
    page = fitz.open(stream=r.content, filetype="pdf")[0]
    clip = fitz.Rect(page.rect)
    blocks = page.get_text("blocks")
    if blocks:
        clip.y1 = min(page.rect.y1, max(b[3] for b in blocks) + 12)
        clip.x1 = min(page.rect.x1, max(b[2] for b in blocks) + 12)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{who}_finances_{dt.date.today().isoformat()}.png"
    page.get_pixmap(dpi=200, clip=clip).save(out)
    print(f"  saved {out}  (send to {p['slack']})")
    return out


def _kv(items) -> dict:
    out = {}
    for it in items or []:
        k, _, val = it.partition("=")
        out[k.strip()] = _num(val)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "dup", "fill", "shot"])
    ap.add_argument("--who", choices=list(PEOPLE))
    ap.add_argument("--we", help="week-ending Sunday YYYY-MM-DD (default: the coming Sunday)")
    ap.add_argument("--tab", help="fill/shot this tab instead of the live one (e.g. the test copy)")
    ap.add_argument("--values", help="JSON from pull (default: values_<we>.json)")
    ap.add_argument("--set", action="append", help='extra/override row for the new week: "Label=amount"')
    ap.add_argument("--prior", action="append", help='last week\'s column: "Label=amount"')
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    we = dt.date.fromisoformat(a.we) if a.we else coming_sunday(dt.date.today())
    if a.cmd != "pull" and not a.who:
        ap.error("--who is required")
    if a.cmd == "pull":
        pull(we)
    elif a.cmd == "dup":
        dup(a.who, we)
    elif a.cmd == "fill":
        path = Path(a.values) if a.values else OUT / f"values_{we.isoformat()}.json"
        d = json.loads(path.read_text())
        vals = {**d[a.who], **_kv(a.set)}
        prior = d["prior"][a.who]
        if a.prior:
            prior.setdefault(hdr(we - dt.timedelta(days=7)), {}).update(_kv(a.prior))
        fill(a.who, we, a.tab, vals, prior, a.dry_run)
        for n in d.get("notes", []):
            if n.lower().startswith(a.who):
                print(f"  NOTE {n}")
    else:
        shot(a.who, a.tab)


if __name__ == "__main__":
    main()
