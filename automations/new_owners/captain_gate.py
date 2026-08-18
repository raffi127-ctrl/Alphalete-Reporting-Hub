"""The ✅ between "Tableau shows a new rep" and "the board has a new row".

Eve, 2026-08-10: the campaign side adds itself (the bank row IS the decision),
but a captainship rep must be approved first — the VA board that used to be the
authority on who belongs to which captainship is no longer maintained, so the
only remaining judgement is a human's.

    detect   a captainship report pulls its captain's team from Tableau and
             finds a rep with no row -> `propose()` posts ONE gate line per rep
             in the year's captainship thread, tagging Evelyn
    approve  she reacts ✅ on that line
    apply    the next Org Sales Board captainship run calls `resolve()`, which
             reads the reactions and inserts the rep into every table of that
             captainship (`cap_insert`). A clean add says NOTHING in the thread
             — the ✅ is the confirmation (Eve, 2026-08-13) and the log tab
             records who approved it and where the rep landed. It speaks only
             when the add FAILS, so silence always means "done"

Nothing is added without a checkmark, and nothing is proposed twice: the log tab
carries one line per rep with its gate ts, so a pending rep is neither re-posted
by the next report that sees them nor re-inserted by the next run.

The approvers, the emoji set and the mention helper are IMPORTED from the Org
Board's own review gate rather than re-listed here — one place decides who can
approve in this channel, and a change there can't leave this gate behind.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.new_owners import bank, cap_insert, notify
from automations.new_owners.captain_watch import captain_name
from automations.org_sales_board.review_gate import (
    APPROVE_EMOJI,
    APPROVERS,
    _mentions,
)

PENDING = "awaiting ✅"

# Reps Tableau still files under a captain they have LEFT. The captain filter is
# this gate's only source of truth, so until someone re-files them in Tableau it
# offers the same person to Evelyn every day, and one absent-minded ✅ puts them
# straight back into a captainship they are not in any more.
#
# Keyed by captain, because the SAME name is legitimate elsewhere: Atef belongs
# in ATEF's boxes, just not in Carlos'.
#
# 2026-08-18 (Eve): Atef Choudhury took Sabrina Alicea and Dhey Patel out of
# Carlos' captainship into his own, and Joe Eckhart came off it. Tableau has no
# Atef captain filter yet, so all three still read as Carlos' team. Drop these
# entries once Tableau is corrected — a name here that no longer shows under
# that captain is harmless, just dead weight.
#
# The sibling mechanism (the VA-board self-heal) has its own list:
# org_sales_board.roster_sync.EXCLUDE.
EXCLUDE: Dict[str, tuple] = {
    "Carlos": ("Atef Choudhury", "Sabrina Alicea",
               "Joe Eckhart", "Joseph Eckhart"),
}


def _excluded(captain: str, name: str) -> bool:
    """Is this rep pinned OUT of this captainship, whatever Tableau says?"""
    def _k(s):
        return " ".join(str(s or "").lower().split())
    for capt, names in EXCLUDE.items():
        if _k(capt) == _k(captain):
            return _k(name) in {_k(n) for n in names}
    return False
ADDED = "added ✅"


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _gate_text(name: str, captain: str, source: str) -> str:
    return (f":new: *{name}* — new in the *{captain}* captainship "
            f"(Tableau, via {source}).\n"
            f"✅ and I add them to {captain}'s boxes on the Org Sales Board — "
            f"leaderboard, daily and the delta table. Nothing happens without "
            f"the checkmark.\n{_mentions()}")


def pending_rows(entries: List[dict]) -> List[dict]:
    return [e for e in entries
            if e["kind"].strip().lower() == bank.KIND_CAPTAINSHIP.lower()
            and e["action"].startswith(PENDING)]


def propose(names: List[str], *, captain: str, source: str,
            today: Optional[dt.date] = None, ss=None, dry_run: bool = False,
            logfn=print) -> List[dict]:
    """Ask for a ✅ on each rep that is new to this captainship.

    Returns the reps actually proposed. A rep already in the log — pending OR
    added — is skipped, which is what keeps five reports from asking five times
    about the same person."""
    today = today or dt.date.today()
    names = [n for n in dict.fromkeys((n or "").strip() for n in names) if n]
    if not names:
        return []
    capt = captain_name(captain)
    try:
        from automations.recruiting_report.fill import open_by_key
        from automations.org_sales_board.run import SHEET_ID
        ss = ss if ss is not None else open_by_key(SHEET_ID)
        lws = bank.open_log(ss, logfn=logfn)
        seen = bank.log_entries(lws)
    except Exception as e:  # noqa: BLE001 — never break the calling report
        logfn(f"  ⚠ captainship gate skipped ({type(e).__name__}: "
              f"{str(e)[:80]})")
        return []

    fresh = [n for n in names
             if not bank.already_logged(seen, bank.KIND_CAPTAINSHIP, n, capt)]
    # Filtered HERE, not in the callers: this is the one door every report goes
    # through, so a new report can't reintroduce a rep Eve already ruled out.
    pinned = [n for n in fresh if _excluded(capt, n)]
    for n in pinned:
        logfn(f"  – {n} ({capt}): pinned out of this captainship — not proposing "
              f"(captain_gate.EXCLUDE)")
    fresh = [n for n in fresh if n not in pinned]
    if not fresh:
        return []

    out: List[dict] = []
    ts_parent = None
    for n in fresh:
        text = _gate_text(n, capt, source)
        if dry_run:
            logfn(f"── DRY-RUN, would ask for a ✅ on {n} ({capt}) ──")
            logfn(text)
            out.append({"name": n, "captain": capt, "ts": None})
            continue
        try:
            ts_parent = ts_parent or notify.ensure_thread(
                lws, bank.KIND_CAPTAINSHIP, today.year, logfn=logfn)
            r = _client().chat_postMessage(
                channel=notify.CHANNEL, thread_ts=ts_parent, text=text,
                unfurl_links=False)
        except Exception as e:  # noqa: BLE001
            logfn(f"  ⚠ couldn't post the gate for {n} ({type(e).__name__}: "
                  f"{str(e)[:80]})")
            continue
        bank.append_log(lws, [[today.strftime("%m/%d/%Y"),
                               bank.KIND_CAPTAINSHIP, n, capt,
                               f"{PENDING} (via {source})", r["ts"]]],
                        logfn=logfn)
        logfn(f"  🕓 {n} ({capt}): waiting for a ✅ from Evelyn")
        out.append({"name": n, "captain": capt, "ts": r["ts"]})
    return out


def _approver_of(msg: dict):
    for rx in msg.get("reactions", []) or []:
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []) or []:
            if uid in APPROVERS:
                return APPROVERS[uid]
    return None


def resolve(ws, *, today: Optional[dt.date] = None, dry_run: bool = False,
            logfn=print) -> dict:
    """Apply every approved-but-not-yet-added rep. Returns {'added', 'waiting'}.

    Reads the reactions off the year's thread in ONE call, so a long pending
    list costs the same as a short one. A rep whose gate line can't be found any
    more is left pending and named in the log rather than silently dropped."""
    today = today or dt.date.today()
    out = {"added": [], "waiting": 0, "unresolved": []}
    ss = ws.spreadsheet
    lws = bank.open_log(ss, logfn=logfn)
    entries = bank.log_entries(lws)
    waiting = pending_rows(entries)
    if not waiting:
        return out
    anchor = bank.thread_anchor(lws, notify.thread_key(bank.KIND_CAPTAINSHIP,
                                                       today.year))
    if not (anchor and anchor.get("ts")):
        logfn(f"  ⚠ {len(waiting)} rep(s) waiting for a ✅ but this year's "
              f"thread anchor is missing — can't read the reactions.")
        return out
    try:
        replies = _client().conversations_replies(
            channel=anchor.get("channel") or notify.CHANNEL,
            ts=anchor["ts"], limit=1000).get("messages", [])
    except Exception as e:  # noqa: BLE001 — advisory, never break the fill
        logfn(f"  ⚠ couldn't read the captainship thread "
              f"({type(e).__name__}: {str(e)[:80]}) — {len(waiting)} rep(s) "
              f"stay pending.")
        return out
    by_ts = {m.get("ts"): m for m in replies}

    for e in waiting:
        msg = by_ts.get(e["notes"].strip())
        if msg is None:
            out["unresolved"].append(f"{e['name']} ({e['scope']})")
            continue
        who = _approver_of(msg)
        if not who:
            out["waiting"] += 1
            continue
        logfn(f"  ✅ {e['name']} ({e['scope']}) approved by {who} — adding to "
              f"the board")
        try:
            res = cap_insert.add_rep(ws, e["scope"], e["name"],
                                     dry_run=dry_run, logfn=logfn)
        except Exception as ex:  # noqa: BLE001 — one rep must not stop the rest
            logfn(f"  ⚠ couldn't add {e['name']} to {e['scope']} "
                  f"({type(ex).__name__}: {str(ex)[:100]}) — still pending, "
                  f"the next run retries.")
            # THE ONLY thing this gate posts back: the ✅ was read and the add
            # did NOT happen (Eve, 2026-08-13 — "que solo avise si algo falla").
            # Without it a failed apply is invisible to whoever ticked: silence
            # is what a SUCCESS looks like now, so a failure has to speak.
            # In the thread, under the rep's own gate line, so it can't be read
            # as being about somebody else.
            if not dry_run:
                try:
                    _client().chat_postMessage(
                        channel=anchor.get("channel") or notify.CHANNEL,
                        thread_ts=anchor["ts"],
                        text=(f":warning: *{e['name']}* — el ✅ está leído pero "
                              f"NO pude agregarla/o a la captainship *{e['scope']}* "
                              f"en el Org Sales Board ({type(ex).__name__}: "
                              f"{str(ex)[:120]}). Queda pendiente y la próxima "
                              f"corrida reintenta sola — si vuelve a aparecer "
                              f"este aviso, hay que mirarlo."),
                        unfurl_links=False)
                except Exception:  # noqa: BLE001 — the run log already has it
                    logfn("  ⚠ (no pude postear el aviso de la falla en Slack)")
            continue
        placed = ", ".join(f"{k} row {v}" for k, v in
                           sorted(res.get("rows", {}).items()))
        note = placed or (f"already had a row ({res['already']})"
                          if res.get("already") else "")
        # NO reply on success. Eve, 2026-08-13: "no necesito ese mensaje cada
        # vez que le doy a checkmark, ya asumo que lo hace cuando reacciono con
        # ese emoji" — the ✅ is the confirmation. Silence means it landed; the
        # log tab keeps the record (who approved, which rows, when). Only the
        # FAILURE path above posts, which is what makes the silence readable.
        if not dry_run:
            bank.update_log(lws, e["row"],
                            action=f"{ADDED} {who} {today.strftime('%m/%d/%Y')}",
                            notes=f"{e['notes']} · {note}"[:480], logfn=logfn)
        out["added"].append({"name": e["name"], "captain": e["scope"],
                             "approved_by": who, "rows": res.get("rows", {})})
    if out["unresolved"]:
        logfn(f"  ⚠ {len(out['unresolved'])} pending rep(s) whose gate message "
              f"couldn't be found in this year's thread: "
              f"{', '.join(out['unresolved'])}")
    if out["waiting"]:
        logfn(f"  🕓 {out['waiting']} rep(s) still waiting for a ✅")
    return out
