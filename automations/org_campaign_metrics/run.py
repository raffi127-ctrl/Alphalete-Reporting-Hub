"""Org Focus Report campaign-metrics stamper.

Fills the hidden 'Campaign Log' tab of the Alphalete Recruiting Dashboard —
the data behind the campaign zone on the Focus Report tab (rendered hourly by
funnel_board/build.py). One run = layout sync + per-campaign pulls + upserts.

    python -m automations.org_campaign_metrics.run              # dry preview
    python -m automations.org_campaign_metrics.run --write      # stamp
    python -m automations.org_campaign_metrics.run --only box   # one campaign
    python -m automations.org_campaign_metrics.run --skip-tableau  # b2b only

Campaign sources:
    b2b   copy of 'MT · Atef' on the Captainship Dashboard (Sheets read)
    box   B2BBOXEnergyTracker views + the BOX order log  (Tableau)
    nds   NDS-SN (RES-ATT-OOF) workbook views            (Tableau)

Goal policy: b2b goals copy from the MT tab every run (that tab is the source
of truth). BOX/NDS goals are SEEDED only where empty — Sales per Rep from the
campaign's national average, weekly-units from HeadCount-goal x national SPR —
and never overwritten after that; typed goals live on via the Goal Sync
script. Manual TEAM rows (mm/mg) are never emitted for BOX/NDS at all.

Runs on Lucy 2 (needs the Tableau session). Python 3.9.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import traceback
from zoneinfo import ZoneInfo

from automations.org_campaign_metrics import layout as L
from automations.org_campaign_metrics import sheet as CL

TZ = ZoneInfo("America/Chicago")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def week_sunday(d):
    """The org Focus Report's weeks are Mon-Sun; WK columns carry the Sunday."""
    return d + dt.timedelta(days=6 - d.weekday())


def _num(s):
    try:
        return float(re.sub(r"[,%$+]", "", str(s)))
    except (TypeError, ValueError):
        return None


def _derive_unit_goals(S, values, goals_seeded, log):
    """Seed weekly-units goals: HeadCount goal x national SPR (per campaign).

    Only for managers who HAVE a stored HC goal and no units goal yet;
    upsert_goals(seed_only=True) enforces the 'no units goal yet' half.
    """
    out = []
    nat_spr = {}
    for camp in ("box", "nds"):
        slots = L.slots_by_label(camp)
        ns = slots.get("National Sales per Rep")
        if not ns:
            continue
        for mgr, _week, slot, val in values:
            if L.MANAGER_CAMPAIGN.get(mgr) == camp and slot == ns:
                v = _num(val)
                if v:
                    nat_spr[camp] = v
    def _unit_goal_slot(camp):
        for i, (kind, lab) in enumerate(L.LAYOUTS.get(camp, [])):
            if kind == "g" and lab != "Sales per Rep":
                return i + 1        # the weekly-units row (Complete Sales /
        return None                 # New-Ports Sold / Total Apps)

    for mgr, camp in L.MANAGER_CAMPAIGN.items():
        if camp not in nat_spr:
            continue
        hc_slot = L.slots_by_label(camp).get("Head Count  ✎")
        unit_slot = _unit_goal_slot(camp)
        if not (hc_slot and unit_slot):
            continue
        hc = _num(CL.existing_goal(S, mgr, hc_slot))
        if hc:
            out.append((mgr, unit_slot, str(int(round(hc * nat_spr[camp])))))
    if out:
        log("unit-goal seeds: %s" % out)
    return out + goals_seeded


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="actually write (default: dry preview)")
    ap.add_argument("--only", choices=["b2b", "box", "nds"],
                    help="run a single campaign's pull")
    ap.add_argument("--skip-tableau", action="store_true",
                    help="skip box+nds (no browser) — b2b copy only")
    a = ap.parse_args(argv)
    dry = not a.write
    today = dt.datetime.now(TZ).date()
    log = print

    from automations.funnel_board.auth import session as sheets_session
    S = sheets_session(verbose=False)

    log("== org_campaign_metrics %s -> %s%s" % (
        today.isoformat(), CL.SSID[:10] + "…", " (DRY RUN)" if dry else ""))
    if not dry:
        CL.write_layout(S, log)

    values, goals_now, goals_seed = [], [], []
    failures = []

    def _run(name, fn):
        try:
            v, g = fn()
            return v, g
        except Exception:  # noqa: BLE001 — one campaign must not sink the rest
            log("!! %s pull failed:\n%s" % (name, traceback.format_exc()))
            failures.append(name)
            return [], []

    if a.only in (None, "b2b"):
        from automations.org_campaign_metrics import pull_b2b
        v, g = _run("b2b", lambda: pull_b2b.collect(S, today, log))
        values += v
        goals_now += g               # MT goals win every run

    if not a.skip_tableau and a.only in (None, "box", "nds"):
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=True) as page:
            if a.only in (None, "box"):
                from automations.org_campaign_metrics import pull_box
                v, g = _run("box", lambda: pull_box.collect(page, today, log))
                values += v
                goals_seed += g
            if a.only in (None, "nds"):
                from automations.org_campaign_metrics import pull_nds
                v, g = _run("nds", lambda: pull_nds.collect(page, today, log))
                values += v
                goals_seed += g

    goals_seed = _derive_unit_goals(S, values, goals_seed, log)

    log("-- totals: %d values, %d goals (stamped), %d goals (seed-only)"
        % (len(values), len(goals_now), len(goals_seed)))
    if dry:
        for row in values[:200]:
            log("   %s" % (row,))
        if len(values) > 200:
            log("   … %d more" % (len(values) - 200))
        for row in goals_now + goals_seed:
            log("   goal %s" % (row,))
    CL.upsert_values(S, values, dry_run=dry, log=log)
    if goals_now:
        CL.upsert_goals(S, goals_now, dry_run=dry, log=log)
    if goals_seed:
        CL.upsert_goals(S, goals_seed, dry_run=dry, seed_only=True, log=log)

    if failures:
        log("!! completed with failures: %s" % ", ".join(failures))
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
