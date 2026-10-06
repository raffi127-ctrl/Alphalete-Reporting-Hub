"""Where every ICD stands on LucyECO — one row each, for chasing the rollout.

The goal is every ICD with LucyECO and their own live board (Megan
2026-09-22). Getting there is mostly owners installing, so the useful thing
is a list that says who is done, who is stuck and who has not started —
without asking anyone. Everything here is read from what the machines
already report: the ICD Signup tab, the relay's last reading per feed, the
agent version it carries, and the Board Access codes.
"""
from __future__ import annotations

import datetime as dt

# The version the machines should be on. Bumped with relay.AGENT_VERSION.
CURRENT_AGENT = "icd_alerts/5"

LIVE, UPDATE, QUIET, WAITING, NONE = (
    "Live", "Needs update", "Gone quiet", "Signed up — not reporting",
    "Not on LucyECO")
ORDER = {LIVE: 0, UPDATE: 1, QUIET: 2, WAITING: 3, NONE: 4}


def _agent_n(agent: str) -> int:
    try:
        return int(str(agent).rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return 0


# What an ICD's board can show today, with or without LucyEco. An office
# Tableau covers per rep already has a real board — yesterday's settled
# numbers, no live ones — so it can be handed a link now (Megan 2026-09-22:
# the goal is every ICD with their own board).
SHOWS_LIVE = "Live + settled"
SHOWS_SETTLED = "Settled only (yesterday)"
SHOWS_OFFICE = "Office total only"
SHOWS_NOTHING = "Nothing yet"


def _tableau_owners() -> tuple:
    """(letters of every per-rep owner, letters of every office-total owner)."""
    from automations.icd_sales_board import tableau_days as TD
    from automations.recruiting_report.fill import open_by_key
    try:
        sh = open_by_key(TD.SHEET_ID)
        rep = sh.worksheet(TD.REP_TAB).get_all_values()
        i = rep[0].index("Owner")
        per_rep = {TD._letters(r[i]) for r in rep[1:] if len(r) > i}
    except Exception:   # noqa: BLE001
        per_rep = set()
    try:
        off = sh.worksheet(TD.OFFICE_TAB).get_all_values()
        j = off[0].index("Owner")
        office = {TD._letters(r[j]) for r in off[1:] if len(r) > j}
    except Exception:   # noqa: BLE001
        office = set()
    return per_rep, office


def _campaigns(feeds) -> str:
    """'Box, AT&T B2B' — the campaigns only. The feed's own key repeated the
    owner's name, which the ICD column already says (Megan 2026-09-22)."""
    seen: dict = {}
    for f in feeds:
        seen[f.label] = seen.get(f.label, 0) + 1
    return ", ".join(lab if n == 1 else f"{lab} ×{n}" for lab, n in seen.items())


def status_rows(today: dt.date | None = None, light: bool = False) -> list:
    """[{ICD, Status, Campaign, Last reading, On latest update}], worst first
    within the ones that need attention, Live at the top.

    NO BOARD CODE HERE (Megan 2026-10-05). It used to carry each office's
    access code so one could be handed over without opening the Board Access
    tab. That was fine while this list was admin-only and is not fine now that
    it is becoming a link anyone can open — a code on a shared page is a code
    that is no longer an access control."""
    from automations.icd_sales_board import (eco_feeds as E, profiles as P,
                                             relay_read as RR)
    today = today or dt.date.today()
    want = _agent_n(CURRENT_AGENT)
    # 'Board shows' costs two large Tableau-mirror reads. The enrollment page
    # does not draw that column, and paying for a column you do not show is
    # most of that page's first load.
    per_rep, office = (set(), set()) if light else _tableau_owners()
    try:
        from automations.focus_office_att import aliases as A
        raw = A.load_aliases()
    except Exception:   # noqa: BLE001
        A, raw = None, {}
    rows = []
    for icd in sorted(P.load()):
        feeds = E.for_icd(icd)
        names = [icd] + (A.get_search_candidates(icd, raw) if A else [])
        keys = {E.norm(n) for n in names}
        settled = SHOWS_SETTLED if keys & per_rep else (
            SHOWS_OFFICE if keys & office else SHOWS_NOTHING)
        base = {"ICD": icd, "Campaign": _campaigns(feeds),
                "Board shows": settled}
        if not feeds:
            rows.append(dict(base, Status=NONE,
                             **{"Last reading": "", "On latest update": ""}))
            continue
        # The office's best feed decides: one working campaign is a working
        # office, and it is the one to look at first.
        best = None
        for f in feeds:
            lr = RR.last_reading(f.key) or {}
            if lr.get("day") and (best is None or lr["day"] > best["day"]):
                best = dict(lr, key=f.key)
        if best is None:
            rows.append(dict(base, Status=WAITING,
                             **{"Last reading": "never",
                                "On latest update": ""}))
            continue
        age = (today - best["day"]).days
        agent = str(best.get("agent") or "")
        if age >= 2:
            status = QUIET
        elif agent.startswith("icd_alerts/") and _agent_n(agent) < want:
            status = UPDATE
        else:
            # Anything that is not the ECO agent is one of our own machines
            # relaying for the office (Raf: the Alphalete sweep), which has no
            # version to fall behind on.
            status = LIVE
        when = best.get("local_time") or best["day"].isoformat()
        if status in (LIVE, UPDATE):
            base["Board shows"] = SHOWS_LIVE
        # WHETHER, not which: the version string said 'icd_alerts/4' and left
        # you to remember what the current one is. The answer people want is
        # yes or no, with the old version named only when it is NO.
        on_latest = ("Yes" if agent == CURRENT_AGENT
                     else (agent or "—") if agent else "—")
        rows.append(dict(base, Status=status,
                         **{"Last reading": str(when)[:16],
                            "On latest update": on_latest}))
    return sorted(rows, key=lambda r: (ORDER[r["Status"]], r["ICD"]))


def counts(rows: list) -> dict:
    out = {k: 0 for k in ORDER}
    for r in rows:
        out[r["Status"]] += 1
    return out
