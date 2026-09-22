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


def _campaigns(feeds) -> str:
    """'Box, AT&T B2B' — the campaigns only. The feed's own key repeated the
    owner's name, which the ICD column already says (Megan 2026-09-22)."""
    seen: dict = {}
    for f in feeds:
        seen[f.label] = seen.get(f.label, 0) + 1
    return ", ".join(lab if n == 1 else f"{lab} ×{n}" for lab, n in seen.items())


def status_rows(today: dt.date | None = None) -> list:
    """[{ICD, Status, Campaign, Last reading, Agent, Board code}], worst first
    within the ones that need attention, Live at the top."""
    from automations.icd_sales_board import (board_access as BA,
                                             eco_feeds as E, profiles as P,
                                             relay_read as RR)
    today = today or dt.date.today()
    # THE CODE ITSELF, not "yes": this list is admin-only, and the code is the
    # one thing needed to hand an ICD their board — copy it from the row
    # instead of opening the Board Access tab to find it.
    try:
        code_of = {icd.strip().lower(): code for code, icd in BA.codes().items()}
    except Exception:   # noqa: BLE001
        code_of = {}
    want = _agent_n(CURRENT_AGENT)
    rows = []
    for icd in sorted(P.load()):
        feeds = E.for_icd(icd)
        base = {"ICD": icd, "Campaign": _campaigns(feeds),
                "Board code": code_of.get(icd.strip().lower(), "—")}
        if not feeds:
            rows.append(dict(base, Status=NONE, **{"Last reading": "",
                                                    "Agent": ""}))
            continue
        # The office's best feed decides: one working campaign is a working
        # office, and it is the one to look at first.
        best = None
        for f in feeds:
            lr = RR.last_reading(f.key) or {}
            if lr.get("day") and (best is None or lr["day"] > best["day"]):
                best = dict(lr, key=f.key)
        if best is None:
            rows.append(dict(base, Status=WAITING, **{"Last reading": "never",
                                                       "Agent": ""}))
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
        rows.append(dict(base, Status=status,
                         **{"Last reading": str(when)[:16],
                            "Agent": best.get("agent") or ""}))
    return sorted(rows, key=lambda r: (ORDER[r["Status"]], r["ICD"]))


def counts(rows: list) -> dict:
    out = {k: 0 for k in ORDER}
    for r in rows:
        out[r["Status"]] += 1
    return out
