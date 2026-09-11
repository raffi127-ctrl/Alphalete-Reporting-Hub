"""B2B blocks for the org Focus Report — COMPUTED for every captainship owner.

Until 2026-09-07 this module copied each owner's 'MT · <First>' tab off the
Captainship Dashboard (filled every morning by automations/captainship_boards).
Carlos trashed that workbook on 9/7 — the org Focus Report is where the
captainship's sales metrics live now — so the copy became a computation: ONE
current-week ORDERLOG export, parsed once and tallied for every owner at the
same time, under the exact captainship_boards counting rules (Unit Count
summed by `sp.Order Date (copy)`, ALL product types; rank = cumulative
position among every owner in the export). The ACTIVATIONRATES / ALLTEAMCHURN
crosstabs are read once for everyone's activation + churn rows. Carlos is one
more owner on the same pass — his block was always computed like this.

Deliberately NOT emitted, so values typed on the org sheet win forever:
manual TEAM rows (Head Count / Leaders / People in Training) and every goal —
type them on the Focus Report and the Goal Sync script stores them, same as
BOX/NDS. The two NATIONAL rows are not computed either (the MT rows they
copied from had no daily refresh of their own); they hold their last stamped
value until they get a tracker source — an open follow-up.

Owner spellings: the ORDERLOG "Owner & Office" first line, uppercase —
captainship_boards.config.OWNERS is the proven per-owner source. Crosstab
owner cells may carry a "[company]" suffix ("SABRINA ALICEA [alisei, inc.]");
matching strips it.
"""
from __future__ import annotations

import datetime as _dt
import re

from automations.captainship_boards import config as CB
from automations.org_campaign_metrics import layout as L

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


# Captainship owners WITHOUT a sales board whose block is still computed
# (Carlos 2026-09-06: Nic Lujan gets the block, no board). label -> ORDERLOG
# "Owner & Office" line-1 spelling, verified against a cached export.
EXTRA_MANAGERS = {"Nicolas Lujan": "NICOLAS LUJAN"}


def _managers():
    """org-picker label -> ORDERLOG owner name for every computed b2b block:
    Carlos + each captainship owner with a sales board + EXTRA_MANAGERS."""
    out = {CARLOS: CARLOS_EXPORT}
    for label, (export, _fid) in CB.OWNERS.items():
        out[label] = export
    out.update(EXTRA_MANAGERS)
    return out


def _pct(n, d, dec=0):
    if not d:
        return None
    v = 100.0 * n / d
    return ("%d%%" % round(v)) if dec == 0 else ("%.1f%%" % v)


def _norm_owner(raw):
    return " ".join(str(raw or "").split("\n")[0].split()).strip().upper()


def _strip_company(raw):
    """Crosstab owner cell -> comparable owner name ("X [co., inc.]" -> "X")."""
    return _norm_owner(re.sub(r"\[[^\]]*\]", " ", str(raw or "")))


def orderlog_all_owner_slots(path, monday, upto, wanted, log=print):
    """Parse one ORDERLOG csv ONCE -> {owner: {layout label: text value}} for
    every owner in `wanted`. Every owner in the export is tallied either way,
    so Rank runs over the whole tracker, not just the captainship."""
    import collections
    from automations.att_order_log import clean

    agg = collections.defaultdict(collections.Counter)
    sellers = collections.defaultdict(set)
    owners_cum = collections.Counter()
    for r in clean.load_rows(str(path), owner_prefix=None):
        raw = str(r.get("Owner & Office", "") or "").replace("\r", "\n")
        owner = _norm_owner(raw)
        if owner == "ALL":
            # Tableau grand-total row (a fake owner). It self-skips today by
            # accident — its date field says "All" so strptime rejects it, and
            # past 999 units its comma'd Unit Count fails float() too — but
            # rank must not depend on that: skip it on purpose (verified 9/7
            # that the accidental skip was the only thing keeping ranks right).
            continue
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
        prod = " ".join(str(r.get("Product Type (Broken Out)", "") or "").split()).upper()
        counted = prod in CB.COUNTED_PRODUCTS
        if counted:
            owners_cum[owner] += u
        if owner not in wanted:
            continue
        a = agg[owner]
        try:
            a["voip"] += float(r.get("Voice Line Count") or 0)
        except (TypeError, ValueError):
            pass
        if not counted:
            continue        # tracker parity (Carlos 9/7) — not a sale
        rep = " ".join(str(r.get("Rep", "") or "").split())
        if rep:
            sellers[owner].add(rep)
        a["total"] += u
        cru = str(r.get("CRU/IRU", "") or "").strip().upper()
        wip = str(r.get("Wireless Installment Plan", "") or "").strip().upper()
        abp = str(r.get("Auto Bill Pay", "") or "").strip().upper()
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

    out = {}
    for owner in wanted:
        a = agg[owner]
        if not a["total"]:
            continue
        named = {
            "Total Apps": str(int(a["total"])),
            "Active Headcount on Tableau": str(len(sellers[owner])),
            "New Internet Sales": str(int(a["ni"])),
            "CRU Internet Sales": str(int(a["ni_cru"])),
            "Wireless Sales (excl. BYOD)": str(int(a["wl"] - a["byod"])),
            "BYOD Sales": str(int(a["byod"])),
            "CRU BYOD Sales": str(int(a["byod_cru"])),
            "IRU BYOD Sales": str(int(a["byod_iru"])),
            "AIR/AWB Sales": str(int(a["air"])),
            "VoIP Line Count": str(int(a["voip"])),
        }
        if sellers[owner]:
            named["Sales per Rep"] = "%.1f" % (a["total"] / len(sellers[owner]))
        my = owners_cum.get(owner, 0)
        if my:
            named["Rank on the Tracker"] = str(
                1 + sum(1 for v in owners_cum.values() if v > my))
        cden = a["cru"] + a["iru"]
        for lab, v in (("CRU %", _pct(a["cru"], cden)),
                       ("ABP %", _pct(a["abp_y"], a["abp_f"])),
                       ("BYOD %", _pct(a["byod"], a["wl"]))):
            if v is not None:
                named[lab] = v
        out[owner] = named
    return out


def orderlog_week_slots(path, monday, upto, log=print, owner=None):
    """One owner's slots — backfill_carlos_b2b's entry point. Same math as the
    all-owner pass (which also retired this function's old bug: a non-Carlos
    `owner` was still ranked as Carlos)."""
    owner_want = _norm_owner(owner or CARLOS_EXPORT)
    out = orderlog_all_owner_slots(path, monday, upto, {owner_want},
                                   log).get(owner_want, {})
    log("  [b2b] %s %s..%s apps=%s hc=%s rank=%s"
        % (owner_want, monday, upto, out.get("Total Apps", "-"),
           out.get("Active Headcount on Tableau", "-"),
           out.get("Rank on the Tracker", "-")))
    return out


def _quality_crosstabs(page, wanted, log):
    """{owner: {label: value}} for every owner in `wanted` — ACTIVATIONRATES
    ('31-60 Days') + ALLTEAMCHURN ('0-30 Day'). Best effort: a rename or a
    missing owner row logs and omits, never raises. Both crosstabs carry
    several rows per ICD with an UNNAMED subrow column; the value only lives
    on the named subrow ('Activation %' / 'Churn Rate') — first-row matching
    once put a count row on the dashboard as 375% churn (8/23)."""
    import collections
    import csv as _csv
    import tempfile
    from pathlib import Path as _P

    from automations.shared.tableau_patchright import download_crosstab_patchright

    out = collections.defaultdict(dict)
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
                log("  [b2b] no %r column on %s — skipped" % (colkey, sheet))
                continue
            for r in rows[1:]:
                if len(r) <= max(ci, oi):
                    continue
                owner = _strip_company(r[oi])
                if owner not in wanted or label in out[owner]:
                    continue
                if si is not None and len(r) > si and r[si].strip() and \
                        r[si].strip() != subrow:
                    continue                     # wrong subrow (a count row)
                v = r[ci].strip().rstrip("%")
                if not v:
                    continue
                try:
                    out[owner][label] = (("%.1f%%" % float(v)) if dec
                                         else ("%d%%" % round(float(v))))
                except ValueError:
                    continue
            hit = sum(1 for o in wanted if label in out[o])
            log("  [b2b] %s: %d/%d owners" % (label, hit, len(wanted)))
        except Exception as exc:  # noqa: BLE001 — quality rows are best-effort
            log("  [b2b] %s pull failed (%s) — skipped" % (sheet, exc))
    return out


def collect_computed(page, today, log=print):
    """-> (values, goals) for every computed b2b manager, CURRENT week only.
    goals is always [] — b2b goals are typed on the org sheet now. History
    already in the Campaign Log stays put: upserts never delete."""
    from pathlib import Path as _P

    from automations.att_order_log.run import _fetch_csv
    from automations.org_campaign_metrics.run import week_sunday

    monday = today - _dt.timedelta(days=today.weekday())
    upto = min(today, monday + _dt.timedelta(days=6))
    week_iso = week_sunday(today).isoformat()

    managers = _managers()
    for mgr in [m for m in managers if L.MANAGER_CAMPAIGN.get(m) != "b2b_att"]:
        log("  [b2b] %s has a board but no b2b_att mapping in layout.py — skipped"
            % mgr)
        managers.pop(mgr)

    out_dir = _P(__file__).resolve().parents[2] / "output" / "org_campaign_metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / ("b2b_orderlog_%s.csv" % today.isoformat())
    if not dest.exists() or dest.stat().st_size < 1000:
        body = _fetch_csv(page, ORDERLOG_CSV % (monday.isoformat(), upto.isoformat()),
                          log=log)
        dest.write_bytes(body)
    else:
        log("  [b2b] reusing today's export %s" % dest.name)

    wanted = set(managers.values())
    per = orderlog_all_owner_slots(dest, monday, upto, wanted, log)
    per_q = _quality_crosstabs(page, wanted, log)

    slots = L.slots_by_label("b2b_att")
    values = []
    for mgr, exp in managers.items():
        named = dict(per.get(exp, {}))
        named.update(per_q.get(exp, {}))
        values += [(mgr, week_iso, slots[lab], v)
                   for lab, v in named.items() if lab in slots]
        log("  [b2b] %-18s %2d values  apps=%s hc=%s rank=%s act=%s churn=%s"
            % (mgr, len(named), named.get("Total Apps", "-"),
               named.get("Active Headcount on Tableau", "-"),
               named.get("Rank on the Tracker", "-"),
               named.get("Activation Rate (31–60 Day)", "-"),
               named.get("0–30 Day Churn Rate", "-")))
    return values, []
