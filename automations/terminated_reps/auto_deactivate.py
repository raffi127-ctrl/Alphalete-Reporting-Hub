"""Step two: actually retire terminated reps in OwnerVille and deactivate them
in Slack, every run (Eve, 2026-10-13: "ahora quiero que los desactives vos de
slack y los retires de ownerville; algún caso dudoso o que no encuentres el
mail / nombre de usuario, reportámelo y lo hago manualmente").

WHO. Everyone on the tracker's 'Terminated Reps' tab in the current or previous
week with Ownerville (E) or Slack Deact (F) still unticked — the same list the
'Still to deactivate' checklist reads (deactivate.pending_for_week). FFP rows
are skipped: they keep both accounts. Board rows the board contradicts itself
about never get here — they aren't filed until a ✅.

OWNERVILLE. ov_retire.retire_one: retire only on exactly ONE live match on
Raf's p=20 roster, then re-read the roster and tick E only once the rep is gone
from it. Zero / several live matches → left for Eve.

SLACK. The match is by the EMAIL OwnerVille has for that rep, never by name
alone (two live 'Luis Ramirez' on 10/9; Logan Ellis was deactivated by mistake
on 10/1). Then two vetoes before the SCIM delete, both of which send the rep to
Eve instead:
  * the account is an AO admin/owner (SCIM answers 403 anyway);
  * the account sits in ANOTHER office's '*-office-recruiting-<oid>' channel —
    "terminated" on Raf's board can be a move to another office, and AO is
    shared by every office ([[raf-terminated-may-be-office-transfer]]).
F is ticked only after users.info reads the account back as deactivated.
An account that was already deactivated just gets its F ticked.

Everything it could not do comes back as an Outcome with a plain-English reason,
which is what the thread's checklist shows next to the name.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from automations.terminated_reps.deactivate import (COL_OWNERVILLE, COL_SLACK,
                                                    Pending, pending_for_week)
from automations.terminated_reps.tracker import COL_NAME, TAB, TRACKER_SHEET_ID, _open

RAF_OFFICE = "11280"            # #rafs-office-recruiting-11280
_OFFICE_CH = re.compile(r"office-recruiting-(\d+)$")
LOG_DIR = Path(__file__).resolve().parents[2] / "output" / "terminated_reps"


@dataclass
class Outcome:
    name: str
    row: int
    term_date: dt.date
    ov: str = ""                 # "done" | "already" | "" (not needed) | reason
    slack: str = ""
    email: str = ""
    moved: str = ""              # another office's recruiting channel they're in
    cleared: bool = False        # Slack checked and nothing says they moved
    notes: list = field(default_factory=list)

    @property
    def ov_ok(self) -> bool:
        return self.ov in ("", "done", "already")

    @property
    def slack_ok(self) -> bool:
        return self.slack in ("", "done", "already")

    @property
    def needs_eve(self) -> bool:
        return not (self.ov_ok and self.slack_ok)

    def todo_text(self) -> str:
        """What Eve still has to do by hand, and why."""
        parts = []
        if not self.ov_ok:
            parts.append(f"OwnerVille: {self.ov}")
        if not self.slack_ok:
            parts.append(f"Slack: {self.slack}")
        return " · ".join(parts)


OV_REASON = {
    "not-found": "not found by name",
    "several-live": "more than one live rep with this name",
    "button-missing": "Retire button not found",
    "retire-failed": "clicked Retire but rep is still active",
}


# ----------------------------------------------------------------- Slack side

def _other_office(cli, uid: str) -> str:
    """Name of another office's recruiting channel this account is in, or ""."""
    try:
        chans = []
        cursor = None
        while True:
            r = cli.users_conversations(user=uid, limit=200, cursor=cursor,
                                        types="public_channel,private_channel",
                                        exclude_archived=True)
            chans += r.get("channels", [])
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:                                      # noqa: BLE001
        return f"? couldn't read their channels ({type(e).__name__})"
    for c in chans:
        m = _OFFICE_CH.search(c.get("name") or "")
        if m and m.group(1) != RAF_OFFICE:
            return "#" + c["name"]
    return ""


def _retry(fn, tries: int = 3):
    """Slack sometimes cuts a response body short (IncompleteRead) — retry."""
    import time
    for i in range(tries):
        try:
            return fn()
        except Exception as e:                                  # noqa: BLE001
            err = getattr(e, "response", None)
            if err is not None and getattr(err, "data", {}).get("error") == "users_not_found":
                return None
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def load_users(cli, logfn=print) -> dict | None:
    """{email: [raw member]} for the whole workspace, deactivated included, or
    None when users.list keeps coming back cut short (it does on Eve's Windows
    box) — slack_lookup then asks per email, which can't see deactivated
    accounts."""
    from automations.ao_cleanup.slack_read import _paged
    try:
        members = _retry(lambda: _paged(cli.users_list, "members"))
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  Slack users.list failed ({type(e).__name__}) — looking up "
              f"one email at a time")
        return None
    out: dict = {}
    for m in members:
        em = ((m.get("profile") or {}).get("email") or "").lower()
        if em:
            out.setdefault(em, []).append(m)
    return out


def slack_lookup(o: Outcome, cli, users: dict | None) -> dict | None:
    """Find the account by OwnerVille's email and run the vetoes. Returns the
    Slack user to deactivate, or None (with o.slack saying why). Sets
    o.cleared when nothing in Slack argues against the termination."""
    if not o.email:
        o.slack = "no email in OwnerVille to match the Slack account"
        return None
    if users is not None:
        same = users.get(o.email.lower(), [])
        live = [u for u in same if not u.get("deleted")]
        if same and not live:
            o.slack, o.cleared = "already", True
            return None
        if len(live) > 1:
            o.slack = f"{len(live)} Slack accounts share {o.email}"
            return None
        u = live[0] if live else None
    else:
        try:
            r = _retry(lambda: cli.users_lookupByEmail(email=o.email))
        except Exception as e:                                  # noqa: BLE001
            o.slack = f"couldn't read Slack ({type(e).__name__}) — next run retries"
            return None
        u = (r or {}).get("user") if r else None
    if not u:
        # Most new starts never got a Slack account (5 of 6 on WE 10/11).
        o.slack = f"no Slack account with {o.email}"
        o.cleared = True
        return None
    name = (u.get("profile") or {}).get("real_name") or u.get("real_name") or u.get("name")
    if u.get("deleted"):
        o.slack = "already"
        return None
    if u.get("is_admin") or u.get("is_owner"):
        o.slack = f"{name} is an AO admin — only Megan can deactivate"
        return None
    other = _other_office(cli, u["id"])
    if other.startswith("?"):
        o.slack = other[2:]
        return None
    if other:
        o.moved = other
        o.slack = f"also in {other} — moved office?"
        return None
    o.cleared = True
    return {"id": u["id"], "name": name}


def slack_deactivate(o: Outcome, u: dict, cli) -> None:
    from automations.owner_rep_audit.slack_ops import deactivate
    res = deactivate(u["id"])
    if res == "admin":
        o.slack = f"{u['name']} is an AO admin — only Megan can deactivate"
        return
    if res != "ok":
        o.slack = f"deactivate failed ({res})"
        return
    back = _retry(lambda: cli.users_info(user=u["id"])) or {}
    o.slack = ("done" if (back.get("user") or {}).get("deleted")
               else "deactivated but Slack still shows it active")
    o.notes.append(f"Slack {u['name']} ({u['id']})")


# ------------------------------------------------------------------- tracker

def tick(col: int, done: dict) -> None:
    """Tick column `col` for {row: name}, re-reading each row's name first —
    the tab can gain rows between the read and the write."""
    if not done:
        return
    _, ws = _open(TRACKER_SHEET_ID, TAB)
    for r, name in done.items():
        if (ws.cell(r, COL_NAME).value or "").strip() != name.strip():
            print(f"  row {r} is no longer {name!r} — not ticked", flush=True)
            continue
        ws.update_cell(r, col, True)


# ---------------------------------------------------------------------- main

def run(today: dt.date, *, apply: bool, logfn=print) -> list[Outcome]:
    """Do the week's (and last week's) pending deactivations. Never raises for a
    per-person problem; raises only if nothing could be read at all."""
    from automations.terminated_reps.board import week_sunday
    from automations.terminated_reps import ov_retire

    sunday = week_sunday(today)
    pending: list[Pending] = []
    for s in (sunday - dt.timedelta(days=7), sunday):
        pending += [p for p in pending_for_week(s) if not p.ffp]
    if not pending:
        logfn("  deactivate: nobody pending")
        return []
    logfn(f"  deactivate: {len(pending)} pending "
          f"({'LIVE' if apply else 'look only'})")
    outs = {p.row: Outcome(p.name, p.row, p.term_date) for p in pending}

    # 1) LOOK at everything first: OwnerVille's roster (it is also where the
    # email for Slack comes from), then the Slack account and its vetoes.
    # 2) ACT only on what passed: a rep who looks moved to another office
    # keeps BOTH accounts, so the vetoes must come before the OwnerVille click.
    from automations.shared.tableau_patchright import ownerville_session
    from automations.ao_cleanup import slack_read
    try:
        cli = slack_read.client()
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  ⚠ no Slack admin token: {type(e).__name__}: {e}")
        cli = None
    users = load_users(cli, logfn) if cli is not None else None

    def _pass():
        with ownerville_session(profile_dir=ov_retire.PROFILE_DIR) as page:
            rqst = ov_retire.open_p20(page)
            reps = ov_retire.roster(page, rqst)
            opened.append(True)
            for p in pending:
                o = outs[p.row]
                status, hits = ov_retire.retire_one(page, rqst, p.name, reps,
                                                    apply=False, note="")
                # 'noemail@gmail.com' is OwnerVille's placeholder (Logan
                # Ellis) — matching Slack on it would "clear" anybody.
                emails = {h["email"].lower() for h in hits
                          if h.get("email") and not h["email"].lower().startswith("noemail")}
                if len(emails) == 1:
                    o.email = emails.pop()
                o.notes += [f"OV: {h['name']} <{h['email']}> {h['roster']}"
                            for h in hits]
                slack_user = None
                if p.slack:
                    if cli is None:
                        o.slack = "no Slack admin token on this machine"
                    else:
                        slack_user = slack_lookup(o, cli, users)
                if p.ownerville:
                    if o.moved:
                        o.ov = f"also in {o.moved} — moved office?"
                    elif status == "already-retired":
                        o.ov = "already"
                    elif status != "ok":
                        o.ov = OV_REASON.get(status, status)
                    elif p.slack and not o.cleared:
                        # Couldn't check Slack for a move to another office
                        # (Logan Ellis, 10/1) — don't retire blind.
                        o.ov = "skipped — couldn't check Slack for a move to another office"
                    elif not apply:
                        o.ov = "done"
                    else:
                        note = ov_retire.NOTE.format(
                            sunday=week_sunday(p.term_date).strftime("%m/%d"))
                        st, _ = ov_retire.retire_one(page, rqst, p.name, reps,
                                                     apply=True, note=note)
                        o.ov = ("done" if st == "RETIRED"
                                else OV_REASON.get(st, st))
                if slack_user:
                    if apply:
                        slack_deactivate(o, slack_user, cli)
                    else:
                        o.slack = "done"
                        o.notes.append(f"would deactivate Slack "
                                       f"{slack_user['name']} ({slack_user['id']})")

    # A stale saved session is the usual failure. Mint a fresh login OUTSIDE
    # ownerville_session (its own self-heal dies inside a running sync
    # playwright — ov_retire --relogin) and try once more, but only if the
    # first pass never got as far as the roster, so nothing is done twice.
    opened: list = []
    for attempt in (1, 2):
        try:
            _pass()
            break
        except Exception as e:                                  # noqa: BLE001
            if attempt == 1 and not opened:
                logfn(f"  OwnerVille session didn't open ({type(e).__name__}) "
                      f"— logging in again")
                try:
                    from automations.shared.appstream_autorenew import refresh_ownerville
                    refresh_ownerville(verbose=False)
                except Exception as e2:                         # noqa: BLE001
                    logfn(f"  relogin failed: {type(e2).__name__}: {e2}")
                continue
            msg = f"OwnerVille session failed ({type(e).__name__}) — next run retries"
            logfn(f"  ⚠ {msg}: {e}")
            for p in pending:
                o = outs[p.row]
                if p.ownerville and not o.ov:
                    o.ov = msg
                if p.slack and not o.slack:
                    o.slack = "waiting on OwnerVille for the email — next run retries"
            break

    result = sorted(outs.values(), key=lambda o: (o.term_date, o.name.lower()))
    if apply:
        tick(COL_OWNERVILLE, {o.row: o.name for o in result
                              if o.ov in ("done", "already")})
        tick(COL_SLACK, {o.row: o.name for o in result
                         if o.slack in ("done", "already")})
    for o in result:
        logfn(f"     {o.name:30} OV={o.ov or '-':12} Slack={o.slack or '-'}")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"deactivate_{today.isoformat()}{'' if apply else '_dry'}.json"
        rows = [{**o.__dict__, "term_date": o.term_date.isoformat()} for o in result]
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:                                           # noqa: BLE001
        pass
    return result
