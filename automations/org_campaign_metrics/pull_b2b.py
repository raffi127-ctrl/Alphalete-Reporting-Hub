"""B2B block for Atef — a straight copy of 'MT · Atef' on the Captainship
Dashboard. That tab is already filled daily by automations/captainship_boards
(order log + tracker + email stamps), and Carlos types the manual TEAM numbers
THERE — so for b2b the copy wins, manual rows included (layout.
STAMPER_OWNS_MANUAL). No Tableau involved: one FORMATTED_VALUE read.

Matching is by LABEL (col A), never by row number: the MT block has been
re-rowed three times in one day before (see captainship-sales-boards README).
"""
from __future__ import annotations

import datetime as _dt
import re

from automations.org_campaign_metrics import layout as L

CAPTAINSHIP_DASHBOARD = "14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8"
MT_TAB = "MT · Atef"
MANAGER = "Atef Choudhury"          # org Focus Report picker spelling

# MT col-A label (normalized) -> our layout label. The ✎ glyph and spacing
# vary; normalization strips both.
_MT_TO_OURS = {
    "head count": "Head Count  ✎",
    "leaders": "Leaders  ✎",
    "people in training": "People in Training  ✎",
    "active headcount on tableau": "Active Headcount on Tableau",
    "total apps": "Total Apps",
    "sales per rep": "Sales per Rep",
    "rank on the tracker": "Rank on the Tracker",
    "new internet": "New Internet Sales",
    "new internet sales": "New Internet Sales",
    "cru internet": "CRU Internet Sales",
    "cru internet sales": "CRU Internet Sales",
    "wireless (excl. byod)": "Wireless Sales (excl. BYOD)",
    "wireless sales (excl. byod)": "Wireless Sales (excl. BYOD)",
    "byod": "BYOD Sales",
    "byod sales": "BYOD Sales",
    "cru byod": "CRU BYOD Sales",
    "cru byod sales": "CRU BYOD Sales",
    "iru byod": "IRU BYOD Sales",
    "iru byod sales": "IRU BYOD Sales",
    "air/awb": "AIR/AWB Sales",
    "air/awb sales": "AIR/AWB Sales",
    "voip line count": "VoIP Line Count",
    "cru %": "CRU %",
    "abp %": "ABP %",
    "byod %": "BYOD %",
    "activation rate (31-60 day)": "Activation Rate (31–60 Day)",
    "activation 31-60": "Activation Rate (31–60 Day)",
    "0-30 day churn rate": "0–30 Day Churn Rate",
    "0-30 churn": "0–30 Day Churn Rate",
    "national avg headcount": "National AVG Headcount",
    "national sales per rep": "National Sales per Rep",
}
# labels whose goal cell (col B) we also carry across
_GOAL_LABELS = ["Head Count  ✎", "Total Apps", "Sales per Rep"]

_WEEKS_TO_COPY = 99          # every WK block the MT tab has — full history


def _norm(label):
    s = str(label or "")
    s = s.replace("✎", "").replace("✎", "")          # pencil glyph
    s = s.replace("–", "-").replace("—", "-")   # en/em dash -> hyphen
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def collect(S, today=None, log=print):
    """-> (values, goals) for the Campaign Log upsert.

    S is an authorized Sheets session (funnel_board.auth). Reads the MT tab
    once with FORMATTED values — the display strings ("98%", "6.4") ARE our
    store format, so nothing is reparsed.
    """
    api = ("https://sheets.googleapis.com/v4/spreadsheets/"
           + CAPTAINSHIP_DASHBOARD)
    r = S.get(api + "/values/'%s'!A1:KZ70" % MT_TAB,
              params={"valueRenderOption": "FORMATTED_VALUE",
                      "dateTimeRenderOption": "FORMATTED_STRING"})
    if r.status_code != 200:
        raise RuntimeError("MT tab read failed: %s %s"
                           % (r.status_code, r.text[:300]))
    grid = r.json().get("values", [])
    if len(grid) < 4:
        raise RuntimeError("MT tab came back empty")

    def cell(rw, cl):
        row = grid[rw] if rw < len(grid) else []
        return row[cl] if cl < len(row) else ""

    # week blocks: row 3 (index 2) holds "WK m/d"; row 2 (index 1) the date —
    # formatted "m/d" with no year, so read that one row again as raw serials.
    # Block layout is [WK][Mon..Sun] starting at C, so WK columns are C, K, S…
    week_cols = []
    hdr = grid[2] if len(grid) > 2 else []
    for c, h in enumerate(hdr):
        if str(h).startswith("WK "):
            week_cols.append(c)
        if len(week_cols) >= _WEEKS_TO_COPY:
            break
    r2 = S.get(api + "/values/'%s'!2:2" % MT_TAB,
               params={"valueRenderOption": "UNFORMATTED_VALUE"})
    serials = (r2.json().get("values", [[]]) or [[]])[0] if r2.status_code == 200 else []
    weeks = []
    for c in week_cols:
        sv = serials[c] if c < len(serials) else None
        if not isinstance(sv, (int, float)):
            log("  [skip-week] col %d has no date serial (%r)" % (c, sv))
            continue
        d = _dt.date(1899, 12, 30) + _dt.timedelta(days=int(sv))
        weeks.append((c, d.isoformat()))
    if not weeks:
        raise RuntimeError("no week columns recognized on %s" % MT_TAB)

    slots = L.slots_by_label("b2b_att")
    values, goals, matched = [], [], set()
    for rw in range(len(grid)):
        ours = _MT_TO_OURS.get(_norm(cell(rw, 0)))
        if not ours or ours in matched or ours not in slots:
            continue
        matched.add(ours)
        s = slots[ours]
        for c, week_iso in weeks:
            v = str(cell(rw, c)).strip()
            if v != "":
                values.append((MANAGER, week_iso, s, v))
        if ours in _GOAL_LABELS:
            gv = str(cell(rw, 1)).strip()
            if gv != "":
                goals.append((MANAGER, s, gv))
    missing = set(_MT_TO_OURS.values()) - matched
    if missing:
        log("  [b2b] labels not found on MT tab (layout drift?): %s"
            % ", ".join(sorted(missing)))
    log("  [b2b] %d values (%d weeks), %d goals"
        % (len(values), len(weeks), len(goals)))
    return values, goals


# --------------------------------------------------------------- Carlos
# Carlos runs the same campaign but has no MT tab (his Vantura board sits
# outside the captainship fleet), so his block is COMPUTED — the exact math
# captainship_boards/run.py uses for the 11 owners (parse_orderlog +
# update_focus), specialized to one owner, cumulative over the week window.

CARLOS = "Carlos Hidalgo"
CARLOS_EXPORT = "CARLOS HIDALGO"          # ORDERLOG "Owner & Office" line 1

ORDERLOG_CSV = ("https://us-east-1.online.tableau.com/t/sci/views/"
                "ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
                "&Start%%20Date=%s&End%%20Date=%s")
ACTIVATION_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                   "ATTTRACKER-B2B/ACTIVATIONRATES")
# ALLTEAMCHURN custom view — the base CHURNRATES auto-restores a broken
# team-filtered custom view that drops most owners (opt_phase_carlos, 6/01).
CHURN_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
              "ATTTRACKER-B2B/CHURNRATES/429cb06d-a32e-4d0e-bf06-9acb77587afd/"
              "ALLTEAMCHURN")
_OUT = None  # set lazily: repo output dir for the shared csv


def _pct(n, d, dec=0):
    if not d:
        return None
    v = 100.0 * n / d
    return ("%d%%" % round(v)) if dec == 0 else ("%.1f%%" % v)


def orderlog_week_slots(path, monday, upto, log=print):
    """Parse one ORDERLOG csv -> (slot-label -> text value) for CARLOS, using
    the captainship counting rules (Unit Count summed by sp.Order Date (copy),
    all products; rank = cumulative position among every owner in the export).
    """
    import collections
    from automations.att_order_log import clean

    a = collections.Counter()
    sellers = set()
    owners_cum = collections.Counter()
    for r in clean.load_rows(str(path), owner_prefix=None):
        raw = str(r.get("Owner & Office", "") or "").replace("\r", "\n")
        owner = _norm_owner(raw)
        s = str(r.get("sp.Order Date (copy)", "") or "").strip()
        try:
            d = _dt.datetime.strptime(s, "%m/%d/%Y").date()
        except ValueError:
            continue
        if not (monday <= d <= upto):
            continue
        try:
            u = float(r.get("Unit Count") or 0)
        except (TypeError, ValueError):
            continue
        if not u:
            continue
        owners_cum[owner] += u
        if owner != CARLOS_EXPORT:
            continue
        rep = " ".join(str(r.get("Rep", "") or "").split())
        if rep:
            sellers.add(rep)
        a["total"] += u
        prod = " ".join(str(r.get("Product Type (Broken Out)", "") or "").split()).upper()
        cru = str(r.get("CRU/IRU", "") or "").strip().upper()
        wip = str(r.get("Wireless Installment Plan", "") or "").strip().upper()
        abp = str(r.get("Auto Bill Pay", "") or "").strip().upper()
        try:
            a["voip"] += float(r.get("Voice Line Count") or 0)
        except (TypeError, ValueError):
            pass
        if prod == "NEW INTERNET":
            a["ni"] += u
            if cru == "CRU":
                a["ni_cru"] += u
        elif prod == "WIRELESS":
            a["wl"] += u
            if wip == "BYOD":
                a["byod"] += u
                if cru == "CRU":
                    a["byod_cru"] += u
                elif cru == "IRU":
                    a["byod_iru"] += u
        elif prod == "AIR/AWB":
            a["air"] += u
        if cru == "CRU":
            a["cru"] += u
        elif cru == "IRU":
            a["iru"] += u
        if abp in ("Y", "YES"):
            a["abp_y"] += u
            a["abp_f"] += u
        elif abp in ("N", "NO"):
            a["abp_f"] += u
    my = owners_cum.get(CARLOS_EXPORT, 0)
    rank = (1 + sum(1 for v in owners_cum.values() if v > my)) if my else None
    out = {}
    if a["total"]:
        out["Total Apps"] = str(int(a["total"]))
        out["Active Headcount on Tableau"] = str(len(sellers))
        if sellers:
            out["Sales per Rep"] = "%.1f" % (a["total"] / len(sellers))
        if rank:
            out["Rank on the Tracker"] = str(rank)
        out["New Internet Sales"] = str(int(a["ni"]))
        out["CRU Internet Sales"] = str(int(a["ni_cru"]))
        out["Wireless Sales (excl. BYOD)"] = str(int(a["wl"] - a["byod"]))
        out["BYOD Sales"] = str(int(a["byod"]))
        out["CRU BYOD Sales"] = str(int(a["byod_cru"]))
        out["IRU BYOD Sales"] = str(int(a["byod_iru"]))
        out["AIR/AWB Sales"] = str(int(a["air"]))
        out["VoIP Line Count"] = str(int(a["voip"]))
        cden = a["cru"] + a["iru"]
        for lab, v in (("CRU %", _pct(a["cru"], cden)),
                       ("ABP %", _pct(a["abp_y"], a["abp_f"])),
                       ("BYOD %", _pct(a["byod"], a["wl"]))):
            if v is not None:
                out[lab] = v
    log("  [b2b/carlos] %s..%s apps=%s hc=%s rank=%s"
        % (monday, upto, out.get("Total Apps", "-"),
           out.get("Active Headcount on Tableau", "-"),
           out.get("Rank on the Tracker", "-")))
    return out


def _norm_owner(raw):
    return " ".join(str(raw or "").split("\n")[0].split()).strip().upper()


def _quality_crosstabs(page, log):
    """CARLOS row from ACTIVATIONRATES ('31-60 Days') + CHURNRATES ('0-30 Day').
    Best effort — a rename logs and omits, never raises."""
    import csv as _csv
    import tempfile
    from pathlib import Path as _P

    from automations.shared.tableau_patchright import download_crosstab_patchright

    out = {}
    # Both crosstabs are multi-row per ICD with an UNNAMED subrow column
    # ('Activation %' / 'Total Activations' / …; 'Churn Rate' / 'Activated
    # SPE/SP' / …) — the value only lives on the named subrow. Structure per
    # opt_phase_carlos's proven configs.
    jobs = [
        (ACTIVATION_VIEW, "Activation Office", "31-60", "Activation %",
         "Activation Rate (31–60 Day)", 0),
        (CHURN_VIEW, "ICD Churn", "0-30 Day", "Churn Rate",
         "0–30 Day Churn Rate", 1),
    ]
    for url, sheet, colkey, subrow, label, dec in jobs:
        try:
            dest = _P(tempfile.gettempdir()) / ("b2b_%s.csv" % colkey.replace(" ", ""))
            download_crosstab_patchright(url, sheet, dest, verbose=False, page=page)
            try:
                rows = list(_csv.reader(open(dest, encoding="utf-16"), delimiter="\t"))
            except UnicodeError:
                rows = list(_csv.reader(open(dest, encoding="utf-8")))
            hdr = rows[0]
            ci = next((i for i, h in enumerate(hdr) if colkey.lower() in h.lower()), None)
            oi = next((i for i, h in enumerate(hdr)
                       if "owner" in h.lower() or "icd" in h.lower()), 0)
            si = next((i for i, h in enumerate(hdr) if not str(h).strip()), None)
            if ci is None:
                log("  [b2b/carlos] no %r column on %s — skipped" % (colkey, sheet))
                continue
            for r in rows[1:]:
                if len(r) <= max(ci, oi) or _norm_owner(r[oi]) != CARLOS_EXPORT:
                    continue
                if si is not None and len(r) > si and r[si].strip() and \
                        r[si].strip() != subrow:
                    continue                     # wrong subrow (a count row)
                v = r[ci].strip().rstrip("%")
                if v:
                    try:
                        out[label] = (("%.1f%%" % float(v)) if dec
                                      else ("%d%%" % round(float(v))))
                        log("  [b2b/carlos] %s = %s" % (label, out[label]))
                        break
                    except ValueError:
                        continue
            if label not in out:
                log("  [b2b/carlos] no %r value for CARLOS on %s" % (subrow, sheet))
        except Exception as exc:  # noqa: BLE001 — quality rows are best-effort
            log("  [b2b/carlos] %s pull failed (%s) — skipped" % (sheet, exc))
    return out


def collect_carlos(page, today, log=print):
    """-> (values, goals_seed) for Carlos's computed b2b block, current week."""
    from pathlib import Path as _P

    from automations.att_order_log.run import _fetch_csv
    from automations.org_campaign_metrics.run import week_sunday

    monday = today - _dt.timedelta(days=today.weekday())
    upto = min(today, monday + _dt.timedelta(days=6))
    week_iso = week_sunday(today).isoformat()

    out_dir = _P(__file__).resolve().parents[2] / "output" / "org_campaign_metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / ("b2b_orderlog_%s.csv" % today.isoformat())
    if not dest.exists() or dest.stat().st_size < 1000:
        body = _fetch_csv(page, ORDERLOG_CSV % (monday.isoformat(), upto.isoformat()),
                          log=log)
        dest.write_bytes(body)
    else:
        log("  [b2b/carlos] reusing today's export %s" % dest.name)

    slots = L.slots_by_label("b2b_att")
    named = orderlog_week_slots(dest, monday, upto, log)
    named.update(_quality_crosstabs(page, log))
    values = [(CARLOS, week_iso, slots[lab], v)
              for lab, v in named.items() if lab in slots]
    return values, []
