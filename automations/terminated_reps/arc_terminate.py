"""Step three: terminate in ARC (Credico) whoever the Sales Board terminated.

Raf, 2026-11-20 (email to Maud + Eve): "if we terminate from the sales board we
can terminate from ARCH?" The prompt was Credico's daily 'Current Active
Agents' email, which asks the office to terminate anyone no longer working.

WHO. Every row on the tracker's 'Terminated Reps' tab dated this week or last
week, minus FFP rows (those keep their accounts), and minus Raf himself (he
holds two badges in ARC as the owner). The tick boxes for OwnerVille and Slack
play no part: a rep whose two boxes are already ticked still needs ARC.

There is no ARC column on Raf's tracker, and none was added. ARC itself is the
record: anyone terminated no longer shows on the office's active list, so a
re-run finds nothing left to do.

THE MATCH. ARC office 2556 'Alphalete Marketing, Inc.' (Charter D2D + Retail-SC)
holds about 20 people, and the board holds every Raf rep, so most terminated
reps are simply not in ARC — that is normal, and nothing gets said about them.
Someone counts as a match when:
  * the email OwnerVille has for them equals ARC's EmailAddress, or
  * no email is available and their first + last name matches exactly.
More than one hit → nobody gets touched, and Eve is told.
VETO: an ARC start date AFTER the termination date means a rehire, so it goes
to Eve and is never terminated.

THE TERMINATION is the same form a person uses: Agent Management → the agent →
'Terminate Agent' (office level, which also ends every campaign). The offboard
reason is required. ARC refuses past dates, so the date is the day of the run,
never the board's date. Afterwards the agent is read back through the API: the
office end date must have moved off 5000-12-31, or it doesn't count.

SHADOW MODE until Eve says go (LIVE = False). Nothing gets clicked. Eve and Raf
get one group DM from Lucy with each person it WOULD terminate, once per person
(Eve 11/23: Raf sees the test too). Login trouble still goes to Eve alone.

Login: Raf's Credico session (`--account raf`). It's a 14-day token with no
refresh, so when it dies this step reports '⏳ retrying' and does nothing until
someone logs in again ([[project_credico-token-is-14-days-no-refresh]]).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from automations.shared.names import base_name, norm_name

LIVE = True                      # Raf OK 11/24 on the Roderick Evans test (Eve 11/25)
ACCOUNT = "raf"
OFFICE_ID = 2556                 # 'Alphalete Marketing, Inc.'
OWNER_NAMES = {"rafael hidalgo", "raf hidalgo"}
# Required by ARC's form. Its options as of 11/20: Work Permit or Study Permit
# Expired · Voluntary · Switching Campaigns · Violated Campaign procedures ·
# No Sales · Severe · Code Sharing · Excessive SOP Violations · Legal Action ·
# Score Card Failure · Office Transfer.
OFFBOARD_REASON = "No Sales"
NOTE = "Terminated on the Alphalete Sales Board ({day}). Auto - Lucy."
OPEN_END = "5000-12-31"
RAF_USER_ID = "U045Z8N0ZQC"      # resources/owner-slack-ids.md
API = "https://arcapi.credico.com/"
SEEN = Path(__file__).resolve().parents[2] / "output" / "terminated_reps" / "arc_shadow_seen.json"

_FETCH = """async p=>{const a=JSON.parse(localStorage.getItem('CredicoArcAuth')||'{}');
const r=await fetch('%s'+p,{headers:{authorization:'bearer '+(a.access_token||'')}});
if(!r.ok) throw new Error('ARC API '+r.status+' on '+p); return await r.json()}""" % API


@dataclass
class Rep:
    name: str
    term_date: dt.date
    row: int
    email: str = ""


@dataclass
class ArcResult:
    name: str
    term_date: dt.date
    status: str                  # "done" | "would" | "" (not in ARC) | reason
    agent: str = ""              # 'First Last <email> #id'


# ---------------------------------------------------------------- pure parts

def _d(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def office_entry(agent: dict) -> dict | None:
    for o in agent.get("Offices") or []:
        if o.get("OfficeID") == OFFICE_ID:
            return o
    return None


def is_active(agent: dict, today: dt.date) -> bool:
    o = office_entry(agent)
    end = _d(o.get("EndDate")) if o else None
    return bool(o) and (end is None or end > today)


def full(agent: dict) -> str:
    return f"{agent.get('FirstName', '')} {agent.get('LastName', '')}".strip()


def label(agent: dict) -> str:
    return f"{full(agent)} <{agent.get('EmailAddress') or 'no email'}> #{agent.get('AgentID')}"


def reps_from_grid(grid: list, sundays: set, *, week_sunday, to_date) -> list[Rep]:
    """Tracker rows dated in one of `sundays`' weeks, without FFP / Raf."""
    from automations.terminated_reps.deactivate import FFP_NOTE
    from automations.terminated_reps.tracker import COL_DATE, COL_NAME, COL_NOTES
    out, seen = [], set()
    for i, r in enumerate(grid[1:], start=2):
        name = str(r[COL_NAME - 1] or "").strip() if len(r) >= COL_NAME else ""
        day = to_date(r[COL_DATE - 1]) if len(r) >= COL_DATE else None
        if not name or day is None or week_sunday(day) not in sundays:
            continue
        note = str(r[COL_NOTES - 1] or "").lower() if len(r) >= COL_NOTES else ""
        if FFP_NOTE in note.replace("-", " ").replace("/", " ").split():
            continue
        if base_name(name) in OWNER_NAMES or norm_name(name) in OWNER_NAMES:
            continue
        if norm_name(name) in seen:
            continue
        seen.add(norm_name(name))
        out.append(Rep(name, day, i))
    return out


def match(rep: Rep, agents: list, today: dt.date) -> tuple[dict | None, str]:
    """(agent to terminate, "") or (None, why-not). Why "" = not in ARC."""
    live = [a for a in agents if is_active(a, today)
            and norm_name(full(a)) not in OWNER_NAMES]
    hits = []
    if rep.email:
        hits = [a for a in live
                if (a.get("EmailAddress") or "").strip().lower() == rep.email.lower()]
    if not hits:
        n, b = norm_name(rep.name), base_name(rep.name)
        hits = [a for a in live if norm_name(full(a)) in (n, b)]
    if not hits:
        return None, ""
    if len(hits) > 1:
        return None, f"{len(hits)} active ARC agents match ({', '.join(label(a) for a in hits)})"
    a = hits[0]
    start = _d((office_entry(a) or {}).get("StartDate"))
    if start and start > rep.term_date:
        return None, (f"ARC start {start:%m/%d} is after the termination "
                      f"{rep.term_date:%m/%d} — rehired?")
    return a, ""


# ------------------------------------------------------------- browser parts

def _agents(page) -> list:
    return page.evaluate(_FETCH, f"api/agents?OfficeID={OFFICE_ID}")


def _terminate(page, agent: dict, rep: Rep, today: dt.date) -> str:
    """Fill ARC's own termination form, then read the agent back."""
    from automations.credico.session import BASE
    aid = agent["AgentID"]
    page.goto(f"{BASE}/#/dashboard/agent/terminate?agentId={aid}&officeId={OFFICE_ID}",
              wait_until="domcontentloaded")
    sel = "select[name=selectedReason]"
    page.wait_for_function(
        f"()=>document.querySelectorAll('{sel} option').length>1", timeout=30000)
    head = page.inner_text("body")
    if full(agent).lower() not in head.lower():
        return "the form opened for someone else — not terminated"
    page.select_option(sel, label=OFFBOARD_REASON)
    page.fill("textarea[name=notes]", NOTE.format(day=rep.term_date.strftime("%m/%d/%Y")))
    # ARC asks 'are you sure' with a browser confirm(); unanswered, Playwright
    # dismisses it and nothing is saved.
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Terminate", exact=True).click()
    try:
        page.get_by_text("successfully terminated").wait_for(timeout=30000)
    except Exception:                                           # noqa: BLE001
        pass
    back = page.evaluate(_FETCH, f"api/agents/{aid}")
    return "done" if not is_active(back, today) else "clicked Terminate but ARC still shows them active"


def _dm_eve_and_raf(text: str) -> bool:
    """One group DM (Lucy + Eve + Raf). False when this machine isn't Lucy."""
    from automations.shared import slack_metrics_post as smp
    from automations.sales_board_fixer.run import EVE_USER_ID
    client = smp._client()
    try:
        who = client.auth_test().get("user", "")
    except Exception:                                           # noqa: BLE001
        who = ""
    if who and "lucy" not in who.lower():
        print("! esta máquina postea como %s, no Lucy -- no mando el DM" % who)
        return False
    ch = client.conversations_open(users=f"{EVE_USER_ID},{RAF_USER_ID}")["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)
    return True


def _shadow_dm(results: list, logfn) -> None:
    """Shadow mode: tell Eve + Raf once per person what LIVE would have done."""
    try:
        seen = set(json.loads(SEEN.read_text(encoding="utf-8")))
    except Exception:                                           # noqa: BLE001
        seen = set()
    new = [r for r in results if r.status and f"{norm_name(r.name)}|{r.term_date}" not in seen]
    if not new:
        return
    lines = [f"• {r.name} (terminated {r.term_date:%m/%d}) → "
             + (f"WOULD terminate {r.agent}" if r.status == "would" else f"❌ {r.status}")
             for r in new]
    text = ("ARC test run (nothing was clicked). This is what Lucy would do "
            f"in ARC, reason '{OFFBOARD_REASON}', dated today:\n" + "\n".join(lines))
    try:
        if _dm_eve_and_raf(text):
            SEEN.parent.mkdir(parents=True, exist_ok=True)
            SEEN.write_text(json.dumps(sorted(seen | {f"{norm_name(r.name)}|{r.term_date}"
                                                      for r in new})), encoding="utf-8")
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  ⚠ couldn't DM Eve + Raf the ARC test list: {type(e).__name__}")


def _once_a_day(today: dt.date, text: str, logfn) -> None:
    flag = SEEN.with_name(f"arc_login_dm_{today.isoformat()}.flag")
    if flag.exists():
        return
    try:
        from automations.sales_board_fixer.run import _dm_eve
        if _dm_eve(text):
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("sent", encoding="utf-8")
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  ⚠ couldn't DM Eve about the ARC login: {type(e).__name__}")


# ---------------------------------------------------------------------- main

def run(today: dt.date, *, apply: bool, emails: dict | None = None,
        logfn=print) -> list[ArcResult]:
    """Never raises. `emails` = {folded name: OwnerVille email} from step two."""
    from automations.terminated_reps.board import to_date, week_sunday
    from automations.terminated_reps.tracker import TAB, TRACKER_SHEET_ID, _open
    live = apply and LIVE
    sunday = week_sunday(today)
    try:
        _, ws = _open(TRACKER_SHEET_ID, TAB)
        grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  ⚠ ARC: couldn't read the tracker ({type(e).__name__})")
        return []
    reps = reps_from_grid(grid, {sunday, sunday - dt.timedelta(days=7)},
                          week_sunday=week_sunday, to_date=to_date)
    for r in reps:
        r.email = (emails or {}).get(norm_name(r.name), "")
    if not reps:
        return []
    logfn(f"  ARC: checking {len(reps)} terminated rep(s) "
          f"({'LIVE' if live else 'test only — nothing clicked'})")
    out: list[ArcResult] = []
    try:
        from automations.credico.session import credico_session
        with credico_session(account=ACCOUNT, verbose=False) as page:
            agents = _agents(page)
            for r in reps:
                a, why = match(r, agents, today)
                if a is None:
                    if why:
                        out.append(ArcResult(r.name, r.term_date, why))
                    continue
                res = ArcResult(r.name, r.term_date, "would", label(a))
                if live:
                    try:
                        res.status = _terminate(page, a, r, today)
                    except Exception as e:                      # noqa: BLE001
                        res.status = f"ARC form failed ({type(e).__name__}) — next run retries"
                out.append(res)
    except Exception as e:                                      # noqa: BLE001
        first = str(e).splitlines()[0] if str(e) else type(e).__name__
        logfn(f"  ⚠ ARC: {first}")
        # Without ARC open there's no telling who is in it, so no rep gets an
        # ARC status. Eve is told once a day instead; the next run retries.
        if apply and any(k in str(e) for k in ("EXPIRED", "REJECTED", "no Credico session")):
            _once_a_day(today, "ARC: Raf's Credico login has expired, so nobody "
                        "was terminated in ARC. To fix it, someone logs in again:\n"
                        "python -m automations.credico.session --login --account raf\n"
                        "then send it to Lucy 1 (set_credico_state --account raf).",
                        logfn)
        return []
    for r in out:
        logfn(f"     ARC {r.name:28} {r.status} {r.agent}")
    if not live and apply:
        _shadow_dm(out, logfn)
    return out
