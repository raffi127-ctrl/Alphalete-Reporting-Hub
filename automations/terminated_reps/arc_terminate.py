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

THE GATE (Eve 11/25). A termination in ARC can't be undone: there is no
reactivate button, only a brand-new onboarding (Add Campaign -> documents ->
Credico approval). So nobody is terminated until Eve says so. Lucy DMs Eve
alone, one message per batch, listing who she would terminate; Eve forwards it
to Raf, and when it's right she reacts ✅ on Lucy's message. The next run
(4am / 8pm) terminates exactly the people in that message. No ✅, nothing
happens. Only Eve's ✅ counts. Login trouble also goes to Eve alone.

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
API = "https://arcapi.credico.com/"
SEEN = Path(__file__).resolve().parents[2] / "output" / "terminated_reps" / "arc_shadow_seen.json"
GATE = SEEN.with_name("arc_gate.json")   # {"asks": [{channel, ts, keys}], "told": [key]}
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark"}
EVE_ID = "U088E2KJEV8"           # only her ✅ opens the gate

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


def gate_key(name: str, term_date: dt.date) -> str:
    return f"{norm_name(name)}|{term_date}"


def approved(msg: dict | None) -> bool:
    """True when Eve reacted ✅ on the message. Anyone else's ✅ doesn't count."""
    for r in (msg or {}).get("reactions") or []:
        if r.get("name") in APPROVE_EMOJI and EVE_ID in (r.get("users") or []):
            return True
    return False


def render_ask(results: list) -> str:
    lines = [f"• {r.name} (terminated {r.term_date:%m/%d}) → "
             + (f"terminate {r.agent}" if r.status == "would" else f"❌ won't touch: {r.status}")
             for r in results]
    asks = any(r.status == "would" for r in results)
    return ("ARC terminations waiting for approval. Lucy will terminate these in ARC, "
            f"reason '{OFFBOARD_REASON}', dated the day she runs:\n" + "\n".join(lines)
            + ("\n\nCheck with Raf, then react ✅ to THIS message and Lucy does it on "
               "her next run (4am / 8pm). No ✅ = nothing happens. A termination in ARC "
               "can't be undone." if asks else ""))


def load_gate() -> dict:
    try:
        g = json.loads(GATE.read_text(encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        g = {}
    g.setdefault("asks", [])
    g.setdefault("told", [])
    return g


def _save_gate(g: dict) -> None:
    GATE.parent.mkdir(parents=True, exist_ok=True)
    GATE.write_text(json.dumps(g, indent=1), encoding="utf-8")


def _lucy_client():
    """Lucy's Slack client, or None when this machine posts as someone else."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    try:
        who = client.auth_test().get("user", "")
    except Exception:                                           # noqa: BLE001
        who = ""
    if who and "lucy" not in who.lower():
        print("! esta máquina postea como %s, no Lucy -- no mando el DM" % who)
        return None
    return client


def approved_keys(gate: dict, today: dt.date, logfn) -> set:
    """Keys from every ask Eve ticked ✅. A read failure keeps the gate shut."""
    ok: set = set()
    if not gate["asks"]:
        return ok
    client = _lucy_client()
    if client is None:
        return ok
    for ask in gate["asks"]:
        try:
            msgs = client.conversations_history(
                channel=ask["channel"], latest=ask["ts"], oldest=ask["ts"],
                inclusive=True, limit=1).get("messages") or []
        except Exception as e:                                  # noqa: BLE001
            logfn(f"  ⚠ ARC: couldn't read Eve's ✅ ({type(e).__name__})")
            _once_a_day(today, "ARC: Lucy couldn't read the ✅ on her ARC approval "
                        "message, so nobody was terminated in ARC. Nothing is lost: "
                        "she tries again on the next run.", logfn, flag="arc_gate_read")
            return set()
        if msgs and approved(msgs[0]):
            ok.update(ask.get("keys") or [])
    return ok


def _ask_eve(results: list, gate: dict, logfn) -> None:
    """One new DM to Eve with whoever she hasn't been told about yet."""
    told = set(gate["told"])
    new = [r for r in results if r.status and r.status != "done"
           and gate_key(r.name, r.term_date) not in told]
    if not new:
        return
    try:
        client = _lucy_client()
        if client is None:
            return
        ch = client.conversations_open(users=EVE_ID)["channel"]["id"]
        resp = client.chat_postMessage(channel=ch, text=render_ask(new))
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  ⚠ couldn't DM Eve the ARC approval list: {type(e).__name__}")
        return
    keys = [gate_key(r.name, r.term_date) for r in new if r.status == "would"]
    if keys:
        gate["asks"].append({"channel": ch, "ts": resp["ts"], "keys": keys})
    gate["told"] = sorted(told | {gate_key(r.name, r.term_date) for r in new})
    _save_gate(gate)


def _once_a_day(today: dt.date, text: str, logfn, flag: str = "arc_login_dm") -> None:
    flag = SEEN.with_name(f"{flag}_{today.isoformat()}.flag")
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
        approve: list | None = None, logfn=print) -> list[ArcResult]:
    """Never raises. `emails` = {folded name: OwnerVille email} from step two."""
    from automations.terminated_reps.board import to_date, week_sunday
    from automations.terminated_reps.tracker import TAB, TRACKER_SHEET_ID, _open
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
    gate = load_gate() if apply else {"asks": [], "told": []}
    ok = approved_keys(gate, today, logfn) if apply else set()
    # --arc-approve: Eve's go given in chat (11/25, Roderick Evans).
    by_hand = {norm_name(n) for n in (approve or [])}
    ok |= {gate_key(r.name, r.term_date) for r in reps
           if apply and (norm_name(r.name) in by_hand or base_name(r.name) in by_hand)}
    logfn(f"  ARC: checking {len(reps)} terminated rep(s) "
          f"({len(ok)} approved by Eve)")
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
                if apply and gate_key(r.name, r.term_date) in ok:
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
    if apply:
        _ask_eve(out, gate, logfn)
    return out
