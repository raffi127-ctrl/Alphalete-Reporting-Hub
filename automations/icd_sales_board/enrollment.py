"""What every office is enrolled in, and when each thing runs.

Megan 2026-10-05: a link anyone can open showing "what everyone is enrolled in
and on what schedule". Nobody could answer that without opening five
registries, so it was answered five different ways.

ASSEMBLED, NEVER RE-KEYED. Every column reads the registry that already
decides it, so this page cannot drift from what actually runs:

  Sara+ Alerts        'Office Channels' tab, Alerts Approved
  Text Scoreboard     same tab, Texts Approved
  Knock & Dispo       same tab, Knocks Approved
  Resume Pushing      applicant_push.OFFICES
  Metrics thread      office_metrics.OFFICES + its schedule_config entry
  Trackers            office_metrics (a metrics office gets the tracker set)
  Dispo alerts        gap_alerts.config.OFFICES
  Own board           board_access — WHETHER they have a code, never the code

A CELL IS THE SCHEDULE, NOT A TICK. "Yes" tells an owner nothing they wanted;
"9pm local" answers the actual question. Blank means not enrolled.

NOTHING SENSITIVE. This is built to be served WITHOUT an access code, so it
carries no board codes, no money, no phone numbers, no channel ids — names,
what runs, and when. `SAFE_COLUMNS` is the whole contract and a test pins it.
"""
from __future__ import annotations

import re
import time

# The columns this page may ever show. Anything not here is a leak, and the
# test that checks it is the point of the list existing.
SAFE_COLUMNS = ["ICD", "Campaigns", "LucyECO", "Sara+ Alerts",
                "Text Scoreboard", "Knock & Dispo Boards", "Resume Pushing",
                "Metrics Thread", "Trackers", "Dispo Alerts", "Own Board"]

# Schedules that are the same wherever the feature is switched on. Each is
# read off the module that enforces it rather than retyped from memory; where
# that module holds the hours as config, the comment says which.
# Sara+ alerts and the text scoreboard run noon to midnight with a 2am
# catch-up, which is near enough round the clock that printing the window was
# noise in a column people scan for "do they have it?" (Megan 2026-10-05: "it
# should just say active since it's pretty much 24/7"). The hours still live
# in icd_alerts.config SALES_* — this is how they READ, not what they are.
ALWAYS_ON = "Active"
KNOCK_SLOTS = "9pm local"                      # knocks_intraday: all offices
DISPO_WINDOW = "every 15 min, Mon–Sat"         # gap_alerts wrapper gate
RESUME_WHEN = "daily"                          # applicant_push schedule entry
BOARD_WHEN = "live"

_CACHE: dict = {}
_TTL = 600


def _letters(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _channels() -> dict:
    """{office key: {alerts, knocks, texts}} off the Office Channels tab."""
    key = "channels"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    out: dict = {}
    try:
        from automations.icd_alerts import post as P
        from automations.recruiting_report.fill import open_by_key, _retry
        grid = _retry(open_by_key(P.RELAY_SPREADSHEET_ID)
                      .worksheet(P.CHANNELS_TAB).get_all_values)

        def yes(row, i):
            return (len(row) > i
                    and str(row[i]).strip().upper() in ("TRUE", "YES", "Y"))

        for r in grid[1:]:
            k = (r[P.CH_OFFICE] or "").strip().lower() if r else ""
            if not k:
                continue
            out[k] = {"alerts": yes(r, P.CH_APPROVED),
                      "knocks": yes(r, P.CH_KN_APPROVED),
                      "texts": yes(r, P.CH_TX_APPROVED)}
    except Exception:   # noqa: BLE001 — the page shows what it can read
        out = {}
    _CACHE[key] = (now, out)
    return out


def _metrics_schedule() -> dict:
    """{office key: 'daily 4am on Lucy 4'} from the scheduler's own entries."""
    out: dict = {}
    try:
        import json
        from pathlib import Path
        here = Path(__file__).resolve().parents[1] / "day_orchestrator"
        reps = json.loads((here / "schedule_config.json").read_text())["reports"]
        for rid, v in reps.items():
            if not rid.endswith("_metrics") or not v.get("on_scheduler"):
                continue
            days = (v.get("cadence") or {}).get("weekdays") or []
            when = ("daily" if len(days) == 7 else
                    "weekdays" if days == [0, 1, 2, 3, 4] else
                    f"{len(days)} day(s)" if days else "")
            at = (v.get("cadence") or {}).get("not_before")
            out[rid[: -len("_metrics")]] = " ".join(
                p for p in (when, f"from {at}" if at else "") if p)
    except Exception:   # noqa: BLE001
        pass
    return out


def _by_owner(pairs) -> dict:
    """{letters-only owner: value} — the only join that survives spellings."""
    return {_letters(o): v for o, v in pairs if _letters(o)}


def rows(icds=None) -> list:
    """One row per ICD, every cell a schedule or blank. Never raises."""
    out = []
    try:
        from automations.icd_sales_board import eco_feeds as E
        from automations.icd_sales_board import profiles as P
        from automations.icd_sales_board import rollout as RO
        names = sorted(icds if icds is not None else P.load())
        chan = _channels()
        sched = _metrics_schedule()

        try:
            from automations.office_metrics import offices as OM
            metrics = _by_owner((o.owner, k) for k, o in OM.OFFICES.items())
        except Exception:   # noqa: BLE001
            metrics = {}
        try:
            from automations.applicant_push import offices as AP
            resume = _by_owner((o.get("owner"), o.get("office_id"))
                               for o in AP.OFFICES.values())
        except Exception:   # noqa: BLE001
            resume = {}
        # GAP ALERTS KEY BY SHORT NAME, not by owner: its offices are 'rafael',
        # 'calvin', 'jay_att'. Several carry no owner at all, so an owner join
        # matched nobody and the column read zero for everyone — including Raf,
        # whose office is the one it was built for.
        try:
            from automations.gap_alerts import config as GC
            dispo = set()
            for o in GC.OFFICES:
                for attr in ("owner", "key"):
                    v = (getattr(o, attr, None)
                         if not isinstance(o, dict) else o.get(attr))
                    if v:
                        dispo.add(_letters(v))
        except Exception:   # noqa: BLE001
            dispo = set()
        try:
            from automations.icd_sales_board import board_access as BA
            boards = {_letters(i) for i in BA.codes().values()}
        except Exception:   # noqa: BLE001
            boards = set()

        status = {r["ICD"]: r for r in RO.status_rows(light=True)}

        for icd in names:
            me = _letters(icd)
            feeds = E.for_icd(icd)
            # An office's ECO switches are per FEED key, and one owner can run
            # two. Enrolled in either is enrolled.
            mine = [chan.get(f.key, {}) for f in feeds]
            on = lambda w: any(m.get(w) for m in mine)   # noqa: E731
            mkey = metrics.get(me, "")
            st = status.get(icd, {})
            out.append({
                "ICD": icd,
                "Campaigns": st.get("Campaign", ""),
                "LucyECO": st.get("Status", ""),
                "Sara+ Alerts": ALWAYS_ON if on("alerts") else "",
                "Text Scoreboard": ALWAYS_ON if on("texts") else "",
                "Knock & Dispo Boards": KNOCK_SLOTS if on("knocks") else "",
                "Resume Pushing": RESUME_WHEN if me in resume else "",
                "Metrics Thread": (sched.get(mkey) or "daily") if mkey else "",
                "Trackers": "daily" if mkey else "",
                # A short key is a PREFIX of the full name ('rafael' ->
                # 'rafaelhidalgo'), which is how that registry names an office.
                "Dispo Alerts": DISPO_WINDOW if any(
                    d == me or (len(d) >= 5 and me.startswith(d))
                    for d in dispo) else "",
                "Own Board": BOARD_WHEN if me in boards else "",
            })
    except Exception:   # noqa: BLE001
        return out
    return out


def counts(rows_: list) -> dict:
    """{column: how many offices have it} for the columns that are features."""
    feats = [c for c in SAFE_COLUMNS if c not in ("ICD", "Campaigns", "LucyECO")]
    return {c: sum(1 for r in rows_ if r.get(c)) for c in feats}
