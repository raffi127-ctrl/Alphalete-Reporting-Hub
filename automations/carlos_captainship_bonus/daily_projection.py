"""Daily projection of Carlos's B2B captainship bonus for the RUNNING DD week.

Carlos 2026-09-07: "make something to predict my captainship bonus as
activations update for the current week on a daily basis."

THE PROGRAM (decoded from SC's weekly 'B2B ATT Captains Bonus Breakdown'
email — DD WE 08/29 reproduces Carlos's actual $794 payout to the dollar):

  1. Team DD volume = the captainship's activations POSTED in the DD week
     (Sun-Sat, labelled by the Saturday) across four products:
     Internet / Non-BYOD wireless / BYOD wireless / AIR-AWB.
  2. $/pc from Carlos's PERSONAL tier ladder (SC recalibrates it; Senior
     scale $0/5/6/7/8/9/10.5/12.5 at thresholds in sc_program.json)
     + activation adder (31-60d team activation >=81% -> +$1, >=83% -> +$2)
     + churn adder (team total 0-30 churn <=2.8% -> +$2, <=3.5% -> +$1).
  3. Payout = max(volume x $/pc, $2,500 Senior floor).
  4. WEIGHTED DECELERATOR — the killer. Per product, the WORSE of team vs
     personal 0-30 churn maps to a decel (100/75/50/25/0%) on per-product
     thresholds; the payout is multiplied by sum(vol_p x decel_p)/sum(vol_p).
     (Verified: 8325 x 9.5% = $794.)

WHAT'S LIVE vs SEEDED:
  * Volumes: LIVE — the ATTTRACKER-B2B ORDERLOG (same pull as the
    b2b_captainship_activations tab), activations = posted & not
    canceled/disconnected, bucketed by POSTED date, split into the four SC
    products, summed over the CURRENT captainship roster.
  * Projection: week-to-date volume divided by the cumulative share of the
    week normally posted by this weekday (last 4 completed DD weeks, same
    export). Before ~8% of the week has normally posted it refuses to
    extrapolate and shows WTD math only.
  * Churn / activation rates: SEEDED from the latest SC breakdown email
    (sc_program.json, as-of date shown in the output; refresh it weekly when
    Wednesday's email lands). Live volumes re-weight the decel daily even
    with seeded churn %s. --churn / --activation / --team-churn override.

ROSTER: the current captainship (post-8/17 realignment) incl. Nicolas Lujan.
SC's own team filter lags (it still filed Ryan Kabbes on 8/29) — a unit or
two of drift vs their sheet is expected.

    PYTHONPATH=. .venv/bin/python -m automations.carlos_captainship_bonus.daily_projection
    ... --dm                # DM the projection to Carlos (from Lucy)
    ... --from-file a.csv --from-file b.csv     # reuse existing exports
    lucy rerun carlos_bonus_projection          # (base_args carry --dm)

Prints/DMs only — writes no sheets.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.b2b_captainship_activations.run import (
    CANCEL_STATUSES, ORDER_COL, POSTED_COL, CSV_URL, _norm_owner, _parse_date)

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "carlos_bonus_projection"
PROGRAM = Path(__file__).resolve().parent / "sc_program.json"
CHUNK_DAYS = 31
LOOKBACK_DAYS = 45          # covers 4 completed DD weeks + the running one

SLACK_CARLOS = "U046G04P5LG"

# Current captainship, ORDERLOG "Owner & Office" spellings (token match).
TEAM_TOKENS = [
    ("CARLOS", "HIDALGO"), ("JAMIS", "GARAY"), ("GEORGE", "HIPOLITO"),
    ("KINSEY", "GUENTHER"), ("JOEY", "RAMIREZ"), ("JUSTIN", "WOOD"),
    ("GARY", "WHITAKER"), ("LUJAN",), ("JACKIE", "LEROY"),
    ("JEFFREY", "STARR"), ("VINCENT", "SMITH"), ("JOSHUA", "MURPHY"),
]

PRODUCTS = ("internet", "nonbyod", "byod", "air")
PROD_LABEL = {"internet": "Internet", "nonbyod": "Non-BYOD",
              "byod": "BYOD", "air": "AIR/AWB"}


def _on_team(owner_uc: str) -> bool:
    toks = set(owner_uc.split())
    return any(all(t in toks for t in alt) for alt in TEAM_TOKENS)


def _product(ln: dict) -> Optional[str]:
    prod = " ".join(str(ln.get("Product Type (Broken Out)", "") or "").split()).upper()
    if prod == "NEW INTERNET":
        return "internet"
    if prod == "AIR/AWB":
        return "air"
    if prod == "WIRELESS":
        wip = str(ln.get("Wireless Installment Plan", "") or "").strip().upper()
        return "byod" if wip == "BYOD" else "nonbyod"
    return None                     # VOICE / VIDEO / TABLET etc — not DD volume


def dd_week(today: dt.date) -> Tuple[dt.date, dt.date]:
    """The running Sun-Sat DD week (same arithmetic as att_order_log.payout)."""
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return start, start + dt.timedelta(days=6)


# --------------------------------------------------------------------- pull

def _chunks(start: dt.date, end: dt.date):
    out, s = [], start
    while s <= end:
        e = min(s + dt.timedelta(days=CHUNK_DAYS - 1), end)
        out.append((s, e))
        s = e + dt.timedelta(days=1)
    return out


def pull(today: dt.date, log=print) -> List[Path]:
    """Same CDP/chunk mechanics as b2b_captainship_activations.pull_chunks."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.att_order_log.run import _fetch_csv
    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = today - dt.timedelta(days=LOOKBACK_DAYS)
    jobs = [(s, e, OUT_DIR / "orderlog_{}_{}_asof_{}.csv".format(
        s.isoformat(), e.isoformat(), today.isoformat()))
        for s, e in _chunks(start, today)]
    missing = [(s, e, d) for s, e, d in jobs
               if not d.exists() or d.stat().st_size < 1000]
    if not missing:
        log("  [pull] all %d chunks cached for %s" % (len(jobs), today))
        return [d for _, _, d in jobs]
    with cdp_pull._cdp_lock(label="carlos_bonus_projection", log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        log("  [cdp] real Chrome pid=%s; waiting 20s" % proc.pid)
        time.sleep(20)
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(
                    "http://127.0.0.1:%s" % cdp_pull.CDP_PORT)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                for s, e, dest in missing:
                    log("  [pull] %s..%s" % (s, e))
                    dest.write_bytes(_fetch_csv(
                        page, CSV_URL.format(s.isoformat(), e.isoformat()),
                        log=log))
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            cdp_pull._kill_ours()
    return [d for _, _, d in jobs]


# --------------------------------------------------------------------- math

def tally(paths, today: dt.date, log=print):
    """-> (wtd_by_product, weekday_cum_share, per_owner_wtd, weekly).

    wtd_by_product: activations posted this DD week so far, per SC product.
    weekday_cum_share: over the last 4 COMPLETED DD weeks, the share of a
    week's team activations posted by end of each weekday index 0=Sun..6=Sat.
    weekly: {DD week Sunday-start: Counter(product -> n)} for completed DD
    weeks from 2026-08-23 on (post-realignment — older weeks come from SC's
    own emails, so the current-roster tally would be wrong for them anyway).
    """
    from automations.att_order_log import clean

    ws, we = dd_week(today)
    hist_start = ws - dt.timedelta(days=28)
    weekly_floor = dt.date(2026, 8, 23)     # first post-realignment DD week

    wtd = collections.Counter()
    per_owner = collections.Counter()
    hist_by_day = collections.Counter()     # weekday idx -> volume, last 4 wks
    weekly = collections.defaultdict(collections.Counter)
    for path in paths:
        for ln in clean.load_rows(str(path), owner_prefix=None):
            owner = _norm_owner(ln.get("Owner & Office"))
            if not owner or owner == "ALL" or not _on_team(owner):
                continue
            status = str(ln.get("DTR Status (enriched)", "") or "").strip().lower()
            if status in CANCEL_STATUSES:
                continue
            posted = _parse_date(ln.get(POSTED_COL))
            if posted is None:
                continue
            prod = _product(ln)
            if prod is None:
                continue
            if ws <= posted <= today:
                wtd[prod] += 1
                per_owner[owner.title()] += 1
            elif hist_start <= posted < ws:
                hist_by_day[(posted.weekday() + 1) % 7] += 1   # 0=Sun
            if posted < ws and posted >= weekly_floor:
                wk_start = posted - dt.timedelta(days=(posted.weekday() + 1) % 7)
                weekly[wk_start][prod] += 1
    hist_total = sum(hist_by_day.values())
    cum, share = 0, []
    for d in range(7):
        cum += hist_by_day.get(d, 0)
        share.append(cum / hist_total if hist_total else 0.0)
    log("  [tally] WTD %s (%s)  hist 4wk=%d  cum-share today=%.0f%%"
        % (sum(wtd.values()),
           " ".join("%s %d" % (PROD_LABEL[p], wtd[p]) for p in PRODUCTS),
           hist_total, 100 * share[(today.weekday() + 1) % 7]))
    return wtd, share, per_owner, weekly


def _tier(vol: float, prog: dict) -> Tuple[int, float]:
    """-> (tier index 0=Base..7, $/pc)."""
    idx = 0
    for i, thr in enumerate(prog["tier_thresholds"]):
        if vol >= thr:
            idx = i
    return idx, prog["tier_rates"][idx]


def _adder(value: float, ladder, higher_is_better: bool) -> float:
    """ladder = [[threshold, $], ...] best first."""
    for thr, dollars in ladder:
        if (value >= thr) if higher_is_better else (value <= thr):
            return dollars
    return 0.0


def _decel(churn_pct: float, thresholds: List[float], scale: List[float]) -> float:
    d = scale[0]
    for i, thr in enumerate(thresholds):
        if churn_pct >= thr:
            d = scale[i + 1]
    return d


def bonus(vol_by_product: Dict[str, float], prog: dict, rates: dict) -> dict:
    vol = sum(vol_by_product.values())
    tier_i, rate = _tier(vol, prog)
    a_add = _adder(rates["activation_31_60_pct"], prog["activation_adder"], True)
    c_add = _adder(rates["team_total_churn_pct"], prog["churn_adder"], False)
    per_pc = rate + a_add + c_add
    payout = max(vol * per_pc, prog["payout_floor"]) if vol else 0.0
    dec_vol = 0.0
    decels = {}
    for p in PRODUCTS:
        d = _decel(rates["churn_pct"][p], prog["decel_thresholds"][p],
                   prog["decel_scale"])
        decels[p] = d
        dec_vol += vol_by_product.get(p, 0) * d
    wdecel = (dec_vol / vol) if vol else 0.0
    return {"vol": vol, "tier": tier_i, "rate": rate, "act_add": a_add,
            "churn_add": c_add, "per_pc": per_pc, "payout": payout,
            "decels": decels, "wdecel": wdecel, "final": payout * wdecel}


# -------------------------------------------------------------------- report

def build_report(today: dt.date, wtd, share, per_owner, prog) -> str:
    ws, we = dd_week(today)
    rates = dict(prog["seed_rates"])
    rates["churn_pct"] = dict(rates["churn_pct"])

    cs = share[(today.weekday() + 1) % 7]
    can_project = cs >= 0.08
    proj_by_p = ({p: wtd[p] / cs for p in PRODUCTS} if can_project
                 else {p: float(wtd[p]) for p in PRODUCTS})

    now = bonus({p: float(wtd[p]) for p in PRODUCTS}, prog, rates)
    proj = bonus(proj_by_p, prog, rates)

    tier_names = ["Base"] + ["Tier %d" % i for i in range(1, 8)]
    nxt = ""
    thr = prog["tier_thresholds"]
    if proj["tier"] < 7:
        need = thr[proj["tier"] + 1] - proj["vol"]
        nxt = (" (+%d units to %s = $%.2f/pc)"
               % (max(1, round(need)), tier_names[proj["tier"] + 1],
                  prog["tier_rates"][proj["tier"] + 1]))

    top = sorted(per_owner.items(), key=lambda kv: -kv[1])[:5]
    lines = [
        "📈 *Captainship Bonus Projection — DD week ending Sat %s*"
        % we.strftime("%-m/%-d"),
        "_as of %s (%s)_" % (today.strftime("%a %-m/%-d"),
                             "day %d of the pay week" % (((today - ws).days) + 1)),
        "",
        "*Posted so far:* %d  (%s)" % (now["vol"], " · ".join(
            "%s %d" % (PROD_LABEL[p], wtd[p]) for p in PRODUCTS)),
        "Top: " + ", ".join("%s %d" % (n, v) for n, v in top) if top else "",
    ]
    if can_project:
        lines += [
            "*Projected week:* ~%d units (by this point last 4 weeks had "
            "posted %.0f%% of the week)" % (round(proj["vol"]), 100 * cs),
        ]
    else:
        lines += ["_Too early in the pay week to project (only %.0f%% of a "
                  "normal week posts by now) — showing week-to-date only._"
                  % (100 * cs)]
    lines += [
        "",
        "*Rate:* %s → $%.2f/pc%s · activation %.1f%% → +$%.0f · team churn "
        "%.1f%% → +$%.0f"
        % (tier_names[proj["tier"]], proj["rate"], nxt,
           rates["activation_31_60_pct"], proj["act_add"],
           rates["team_total_churn_pct"], proj["churn_add"]),
        "*Weighted decel:* %.1f%%  (%s — churn as of SC's DD WE %s email)"
        % (100 * proj["wdecel"],
           " · ".join("%s %.0f%%" % (PROD_LABEL[p], 100 * proj["decels"][p])
                      for p in PRODUCTS),
           prog["dd_we"]),
        "",
        "*Projected bonus:* $%s × %.1f%% ≈ *$%s*"
        % ("{:,.0f}".format(proj["payout"]), 100 * proj["wdecel"],
           "{:,.0f}".format(proj["final"])),
        "If the week stopped today: ≈ $%s" % "{:,.0f}".format(now["final"]),
        "If churn were clean (100%% decel): ≈ $%s"
        % "{:,.0f}".format(proj["payout"]),
    ]
    age = (today - dt.date.fromisoformat(prog["as_of"])).days
    if age > 9:
        lines.append("⚠️ sc_program.json is %d days old — refresh from the "
                     "latest SC breakdown email." % age)
    return "\n".join(l for l in lines if l != "")


HISTORY = Path(__file__).resolve().parent / "sc_history.json"
BONUS_TAB = "Captainship Bonus"
TIER_NAMES = ["Base"] + ["Tier %d" % i for i in range(1, 8)]


def _money(v) -> str:
    return "$" + "{:,.0f}".format(v)


def _bonus_col(prog, vols, rates, status, posted_so_far=None):
    """One sheet column (list of display strings) from computed inputs."""
    b = bonus({p: float(vols.get(p, 0)) for p in PRODUCTS}, prog, rates)
    thr = prog["tier_thresholds"][b["tier"]]
    col = [
        status,
        str(int(round(b["vol"]))),
        (str(posted_so_far) if posted_so_far is not None else u"—"),
    ]
    col += [str(int(round(vols.get(p, 0)))) for p in PRODUCTS]
    col += [
        "%s (≥%d)" % (TIER_NAMES[b["tier"]], thr),
        "$%.2f" % b["rate"],
        "%.1f%%" % rates["activation_31_60_pct"],
        "+$%.0f" % b["act_add"],
        "%.1f%%" % rates["team_total_churn_pct"],
        u"—",
        "+$%.0f" % b["churn_add"],
        "$%.2f" % b["per_pc"],
        _money(b["payout"]),
    ]
    col += ["%.1f%% → %.0f%%" % (rates["churn_pct"][p],
                                      100 * b["decels"][p]) for p in PRODUCTS]
    col += ["%.1f%%" % (100 * b["wdecel"]), _money(b["final"])]
    return col


def _paid_col(wk: dict):
    """One sheet column from an SC-email actual (old or new format)."""
    prods = wk.get("products") or {}
    cprods = wk.get("churn_products") or {}
    dprods = wk.get("decel_products") or {}
    per_pc = wk["vol_rate"] + wk["act_add"] + wk["churn_add"]
    col = ["PAID (SC email)", str(wk["volume"]), u"—"]
    col += [(str(prods[p]) if p in prods else u"—") for p in PRODUCTS]
    col += [
        u"—",
        "$%.2f" % wk["vol_rate"],
        "%.1f%%" % wk["activation"],
        "+$%.0f" % wk["act_add"],
        "%.1f%%" % wk["churn_team"],
        "%.1f%%" % wk["churn_personal"],
        "+$%.0f" % wk["churn_add"],
        "$%.2f" % per_pc,
        _money(wk["payout"]),
    ]
    if wk.get("format") == "weighted":
        col += ["%.1f%% → %.0f%%" % (cprods[p], 100 * dprods[p])
                for p in PRODUCTS]
    else:
        col += [u"— (single decel)"] * len(PRODUCTS)
    col += ["%.1f%%" % (100 * wk["decel"]), _money(wk["final"])]
    return col


ROW_LABELS = [
    "", "DD Volume (activations)", "posted so far",
    "  Internet", "  Non-BYOD wireless", "  BYOD wireless", "  AIR/AWB",
    "Volume tier", "Volume $/pc",
    "Activation % (31–60d)", "Activation adder",
    "Team churn % (0–30d)", "Personal churn % (0–30d)", "Churn adder",
    "Total $/pc", "Payout (before decel)",
    "Internet churn → decel", "Non-BYOD churn → decel",
    "BYOD churn → decel", "AIR/AWB churn → decel",
    "Weighted decelerator", "FINAL BONUS",
]


def build_sheet(today, wtd, share, weekly, prog, log=print):
    """-> (values, meta) for the 'Captainship Bonus' tab. Columns: the running
    DD week (live), then prior DD weeks newest-first — SC actuals where the
    breakdown email exists (sc_history.json), our ESTIMATE where it doesn't
    yet (post-realignment weeks only)."""
    hist = json.loads(HISTORY.read_text())["weeks"]
    rates = dict(prog["seed_rates"])
    rates["churn_pct"] = dict(rates["churn_pct"])

    ws, we = dd_week(today)
    cs = share[(today.weekday() + 1) % 7]
    can_project = cs >= 0.08
    cur_vols = ({p: wtd[p] / cs for p in PRODUCTS} if can_project
                else {p: float(wtd[p]) for p in PRODUCTS})
    day_n = (today - ws).days + 1
    cur_status = ("LIVE · day %d, projected" % day_n if can_project
                  else "LIVE · day %d, WTD only" % day_n)

    cols = [("DD WE %d/%d" % (we.month, we.day),
             _bonus_col(prog, cur_vols, rates, cur_status,
                        posted_so_far=sum(wtd.values())))]
    # prior weeks, newest first: SC actual > our estimate > skip
    prior = ws - dt.timedelta(days=7)
    hist_keys = sorted(hist.keys(), reverse=True)
    oldest = dt.date.fromisoformat(min(hist_keys)) if hist_keys else prior
    wk = prior
    while wk >= oldest - dt.timedelta(days=6):
        sat = wk + dt.timedelta(days=6)
        label = "DD WE %d/%d" % (sat.month, sat.day)
        h = hist.get(sat.isoformat())
        if h:
            cols.append((label, _paid_col(h)))
        elif wk in weekly:
            cols.append((label + " *",
                         _bonus_col(prog, dict(weekly[wk]), rates,
                                    "ESTIMATE (SC email pending)")))
        wk -= dt.timedelta(days=7)

    ncol = len(cols) + 1
    values, meta = [], []

    def push(row, kind=None):
        values.append(row + [""] * (ncol - len(row)))
        if kind:
            meta.append((len(values), kind))

    push(["CARLOS CAPTAINSHIP BONUS — WEEKLY BREAKDOWN"], "title")
    push(["DD (pay) weeks run Sun–Sat. PAID columns are Smart Circle's own "
          "breakdown email; ESTIMATE/LIVE columns are computed from the order "
          "log with churn/activation seeded from the latest email (as of %s). "
          "Bonus = volume × tier $/pc (+adders, $%s floor) × weighted "
          "churn decelerator. Before DD WE 8/29 the program used one single "
          "decelerator. Updated %s."
          % (prog["as_of"], "{:,}".format(prog["payout_floor"]),
             today.strftime("%m/%d/%Y"))], "note")
    push([""])
    push([""] + [c[0] for c in cols], "header")
    for i, lab in enumerate(ROW_LABELS):
        if i == 0:
            push(["Status"] + [c[1][0] for c in cols], "status")
            continue
        kind = "final" if lab == "FINAL BONUS" else (
            "money" if lab in ("Payout (before decel)", "Weighted decelerator")
            else None)
        push([lab] + [c[1][i] for c in cols], kind)
    return values, meta


def write_bonus_tab(values, meta, log=print):
    from automations.b2b_captainship_activations.run import SHEET_ID
    from automations.recruiting_report.fill import _retry, open_by_key

    sh = open_by_key(SHEET_ID)
    ncol = max(len(r) for r in values)
    try:
        ws = sh.worksheet(BONUS_TAB)
    except Exception:  # noqa: BLE001 — WorksheetNotFound
        ws = _retry(lambda: sh.add_worksheet(title=BONUS_TAB,
                                             rows=len(values) + 10,
                                             cols=ncol + 2))
        log("  [sheet] created tab %r" % BONUS_TAB)
    if ws.title != BONUS_TAB:
        raise RuntimeError("PROTECTED: refusing to write tab %r" % ws.title)
    _retry(lambda: ws.resize(rows=max(len(values) + 10, 40),
                             cols=max(ncol + 2, 10)))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(values, "A1", raw=True))

    sid = ws.id
    white = {"red": 1, "green": 1, "blue": 1}
    navy = {"red": 0.12, "green": 0.30, "blue": 0.47}
    slate = {"red": 0.85, "green": 0.88, "blue": 0.91}
    gold = {"red": 1.0, "green": 0.95, "blue": 0.75}
    grey = {"red": 0.95, "green": 0.95, "blue": 0.95}

    def band(i0, color, fg=None, bold=True, size=None, italic=False):
        fmt = {"backgroundColor": color,
               "textFormat": {"bold": bold, "italic": italic}}
        if fg:
            fmt["textFormat"]["foregroundColor"] = fg
        if size:
            fmt["textFormat"]["fontSize"] = size
        return {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": i0 - 1, "endRowIndex": i0,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}}

    reqs = [
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0,
                      "endRowIndex": len(values), "startColumnIndex": 1,
                      "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER",
                                           "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 190}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": ncol},
            "properties": {"pixelSize": 132}, "fields": "pixelSize"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sid,
                           "gridProperties": {"frozenRowCount": 4,
                                              "frozenColumnCount": 1}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
    ]
    for i, kind in meta:
        if kind == "title":
            reqs.append(band(i, white, size=14))
        elif kind == "note":
            reqs.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": i - 1,
                          "endRowIndex": i, "startColumnIndex": 0,
                          "endColumnIndex": ncol},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"italic": True, "fontSize": 8},
                    "wrapStrategy": "OVERFLOW_CELL"}},
                "fields": "userEnteredFormat(textFormat,wrapStrategy)"}})
        elif kind == "header":
            reqs.append(band(i, navy, fg=white))
        elif kind == "status":
            reqs.append(band(i, slate, bold=False, italic=True))
        elif kind == "money":
            reqs.append(band(i, grey))
        elif kind == "final":
            reqs.append(band(i, gold, size=12))
    from automations.recruiting_report.fill import _retry as _r
    _r(lambda: sh.batch_update({"requests": reqs}))
    log("  [sheet] %r: %d rows x %d cols, formatted"
        % (BONUS_TAB, len(values), ncol))


def dm(text: str, user: str, log=print) -> None:
    from automations.shared.slack_metrics_post import _bot_client
    client = _bot_client()
    ch = client.conversations_open(users=user)["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)
    log("  [slack] DM'd projection to %s" % user)


# ---------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="carlos_bonus_projection")
    ap.add_argument("--dm", action="store_true", help="DM Carlos the projection")
    ap.add_argument("--sheet", action="store_true",
                    help="write the 'Captainship Bonus' tab on the Vantura board")
    ap.add_argument("--dm-user", default=SLACK_CARLOS)
    ap.add_argument("--dry-run", action="store_true",
                    help="never DM, even if --dm was passed")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--from-file", action="append", default=None, metavar="CSV")
    ap.add_argument("--churn", default=None, metavar="INT,NONBYOD,BYOD,AIR",
                    help="override per-product churn %% (worse of team/personal)")
    ap.add_argument("--activation", type=float, default=None)
    ap.add_argument("--team-churn", type=float, default=None)
    args = ap.parse_args(argv)

    log = print
    today = (dt.date.fromisoformat(args.today) if args.today else dt.date.today())
    prog = json.loads(PROGRAM.read_text())
    if args.churn:
        vals = [float(x) for x in args.churn.split(",")]
        prog["seed_rates"]["churn_pct"] = dict(zip(PRODUCTS, vals))
    if args.activation is not None:
        prog["seed_rates"]["activation_31_60_pct"] = args.activation
    if args.team_churn is not None:
        prog["seed_rates"]["team_total_churn_pct"] = args.team_churn

    ws, we = dd_week(today)
    log("Carlos bonus projection — %s (DD week %s..%s)" % (today, ws, we))
    paths = ([Path(p) for p in args.from_file] if args.from_file
             else pull(today, log=log))
    wtd, share, per_owner, weekly = tally(paths, today, log=log)
    text = build_report(today, wtd, share, per_owner, prog)
    log("")
    log(text)
    if args.sheet and not args.dry_run:
        values, meta = build_sheet(today, wtd, share, weekly, prog, log=log)
        write_bonus_tab(values, meta, log=log)
    if args.dm and not args.dry_run:
        dm(text, args.dm_user, log=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
