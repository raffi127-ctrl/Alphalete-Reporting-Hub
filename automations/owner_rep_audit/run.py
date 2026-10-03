"""Monthly owner rep audit — run it every day; it does what the day needs.

    python -m automations.owner_rep_audit.run                      # dry run
    python -m automations.owner_rep_audit.run --test-to U088E2KJEV8 --live
    python -m automations.owner_rep_audit.run --live               # for real
    python -m automations.owner_rep_audit.run --show               # state

Each run, in order (state in output/owner_rep_audit/<YYYY-MM>.json):
  1. START   first run on/after day SEND_DAY with no state for the month: read
             every granted office's active reps, DM each owner their list,
             open the month's thread in #l10-alphalete.
  2. POLL    read new DM replies and act (numbers -> confirm prompt,
             REMOVE -> deactivate in Slack, none -> done, else -> ask again).
  3. REMIND  once, on/after REMIND_DAY, to owners who haven't finished.
  4. SUMMARY the thread's results reply, edited in place.
  5. CLOSE   once, on/after CLOSE_DAY: post the unfinished owners' lists in
             the thread tagging Evelyn.

DRY RUN (default) sends nothing and removes nobody: it prints every message.
--test-to <uid> sends EVERYTHING (owner DMs and channel posts) to that one
person instead, and never deactivates anyone -- the end-to-end rehearsal.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Dict, List, Optional

from automations.owner_rep_audit import config as C
from automations.owner_rep_audit import messages as M
from automations.owner_rep_audit import replies as R

ACTIVE = ("sent", "selected", "unclear")


def month_key(day: dt.date) -> str:
    return day.strftime("%Y-%m")


def month_label(day: dt.date) -> str:
    return day.strftime("%B %Y")


def state_path(day: dt.date):
    return C.STATE_DIR / f"{month_key(day)}.json"


def load_state(day: dt.date) -> Optional[dict]:
    try:
        return json.loads(state_path(day).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def save_state(day: dt.date, st: dict) -> None:
    C.STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(day).write_text(json.dumps(st, indent=1), encoding="utf-8")


def due(st: Optional[dict], day: dt.date) -> List[str]:
    """Which steps this run owes. Pure: the tests pin the calendar."""
    if st is None:
        return ["start", "summary"] if day.day >= C.SEND_DAY else []
    steps = ["poll"]
    if day.day >= C.REMIND_DAY and not st.get("reminded"):
        steps.append("remind")
    steps.append("summary")
    if day.day >= C.CLOSE_DAY and not st.get("closed"):
        steps.append("close")
    return steps


def apply_reply(o: dict, text: str, today: dt.date) -> tuple:
    """(new status, owner-facing answer, names to remove). Pure."""
    names = [r["name"] for r in o["reps"]]
    kind, good, bad = R.parse(text, len(names), bool(o.get("selected")))
    if kind == R.SELECT:
        o["selected"] = good
        return "selected", M.confirm_prompt([names[i - 1] for i in good], bad), []
    if kind == R.CONFIRM:
        picked = [names[i - 1] for i in o["selected"]]
        o["confirmed_on"] = f"{today.month}/{today.day}"
        return "done", M.done(picked), picked
    if kind == R.NONE:
        o["confirmed_on"] = f"{today.month}/{today.day}"
        o["selected"] = []
        return "done", M.none_ack(), []
    if o.get("status") == "selected":
        return "selected", M.awaiting_remove(), []
    return "unclear", M.unclear(), []


class Out:
    """Where messages go. Dry: print. Test: everything to one person. Live:
    owners get DMs, the channel gets the thread."""

    def __init__(self, mode: str, test_to: str = ""):
        self.mode, self.test_to = mode, test_to
        self.cli = None
        if mode != "dry":
            from automations.owner_rep_audit import slack_ops as S
            self.S, self.cli = S, S.lucy()
        self._test_dm = None

    def _dm_channel(self, uid: str) -> str:
        if self.mode == "test":
            if not self._test_dm:
                self._test_dm = self.S.open_dm(self.cli, self.test_to)
            return self._test_dm
        return self.S.open_dm(self.cli, uid)

    def dm(self, uid: str, text: str, label: str) -> Optional[tuple]:
        if self.mode == "dry":
            print(f"\n--- DM to {label} ({uid}) ---\n{text}")
            return None
        if self.mode == "test":
            text = f"[TEST · would go to {label}]\n{text}"
        ch = self._dm_channel(uid)
        return ch, self.S.send(self.cli, ch, text)

    def reply_dm(self, o: dict, text: str) -> None:
        if self.mode == "dry":
            print(f"\n--- reply to {o['owner']} ---\n{text}")
            return
        if self.mode == "test":
            text = f"[TEST · reply to {o['owner']}]\n{text}"
        self.S.send(self.cli, o["dm_channel"], text)

    def channel(self, text: str, thread_ts: str = None) -> Optional[str]:
        if self.mode == "dry":
            print(f"\n--- #l10-alphalete{' (thread)' if thread_ts else ''} ---\n{text}")
            return None
        ch = self._dm_channel("") if self.mode == "test" else C.CHANNEL
        if self.mode == "test":
            text = "[TEST · would go to #l10-alphalete]\n" + text
        return self.S.send(self.cli, ch, text, thread_ts=thread_ts)

    def edit(self, ts: str, text: str) -> None:
        if self.mode == "dry" or not ts:
            return
        ch = self._dm_channel("") if self.mode == "test" else C.CHANNEL
        if self.mode == "test":
            text = "[TEST · would go to #l10-alphalete]\n" + text
        self.cli.chat_update(channel=ch, ts=ts, text=text)


# ----------------------------------------------------------------- the steps

def start(day: dt.date, out: Out, rosters_json: str = "", only=None) -> dict:
    from automations.owner_rep_audit import roster as RO
    if rosters_json:
        rows = json.loads(open(rosters_json, encoding="utf-8").read())
    else:
        got = RO.read_all(only=only)
        RO.dump(got, C.STATE_DIR / f"rosters-{day.isoformat()}.json")
        rows = [g.__dict__ for g in got]
    users = []
    try:
        from automations.ao_cleanup.slack_read import all_users
        users = all_users()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ couldn't list AO Slack members ({type(e).__name__}): "
              "owners can't be matched, so nobody gets a DM")
    from automations.owner_rep_audit.slack_ops import find_owner
    st = {"month": month_label(day), "started": day.isoformat(),
          "mode": out.mode, "offices": {}}
    for r in rows:
        o = {k: r.get(k, "") for k in ("office", "owner", "company", "access",
                                         "note")}
        o.update(reps=r.get("reps") or [], selected=[], removed=[],
                 ov_pending=[], log=[])
        st["offices"][o["office"]] = o
        if o["access"] != "granted":
            o["status"] = "no_access"
            continue
        if not o["reps"]:
            o["status"] = "done"           # nobody active, nothing to ask
            continue
        o["slack_id"] = find_owner(o["owner"], users) if users else None
        if not o["slack_id"]:
            o["status"] = "no_slack"
            print(f"  ⚠ {o['owner']} ({o['office']}): no unique Slack match "
                  "— add them to config.OWNER_SLACK")
            continue
        sent = out.dm(o["slack_id"],
                      M.owner_dm(o["owner"], [x["name"] for x in o["reps"]],
                                 st["month"]), o["owner"])
        if sent:
            o["dm_channel"], o["dm_ts"] = sent
            o["last_seen_ts"] = o["dm_ts"]
        o["status"] = "sent"
    st["thread_ts"] = out.channel(M.thread_intro(st["month"]))
    return st


def remove(o: dict, names: List[str], out: Out) -> None:
    from automations.owner_rep_audit import slack_ops as S
    from automations.ao_cleanup.slack_read import all_users
    users = all_users()
    for name in names:
        rep = next(r for r in o["reps"] if r["name"] == name)
        acct = S.find_rep(rep, users)
        if not acct:
            res = "not in Slack"
        elif out.mode != "live":
            res = f"would deactivate {acct['id']}"
        else:
            res = S.deactivate(acct["id"])
        o["log"].append(f"{name}: slack {res}")
        if not C.OV_RETIRE_AUTOMATED:
            o["ov_pending"].append(name)
    o["removed"] = names


def poll(st: dict, out: Out, today: dt.date) -> None:
    if out.mode == "dry":
        return
    from automations.owner_rep_audit import slack_ops as S
    for o in st["offices"].values():
        if o.get("status") not in ACTIVE or not o.get("dm_channel"):
            continue
        uid = out.test_to if out.mode == "test" else o["slack_id"]
        for m in S.owner_messages(out.cli, o["dm_channel"], uid,
                                  o["last_seen_ts"]):
            o["last_seen_ts"] = m["ts"]
            if o["status"] == "done":
                break
            status, answer, picked = apply_reply(o, m.get("text", ""), today)
            o["status"] = status
            if picked:
                remove(o, picked, out)
            out.reply_dm(o, answer)


def remind(st: dict, out: Out) -> None:
    for o in st["offices"].values():
        if o.get("status") in ACTIVE:
            text = (M.awaiting_remove() if o["status"] == "selected"
                    else M.reminder(o["owner"]))
            if o.get("dm_channel"):
                out.reply_dm(o, text)
            else:
                out.dm(o["slack_id"], text, o["owner"])
    st["reminded"] = True


def _summary_rows(st: dict) -> List[dict]:
    return [o for o in st["offices"].values()
            if o.get("status") not in ("no_access",)]


def summary(st: dict, out: Out) -> None:
    text = M.summary(_summary_rows(st))
    if text == st.get("summary_text"):
        return
    if st.get("summary_ts"):
        out.edit(st["summary_ts"], text)
    else:
        st["summary_ts"] = out.channel(text, thread_ts=st.get("thread_ts"))
    st["summary_text"] = text


def close(st: dict, out: Out) -> None:
    left = [dict(o, reps=[r["name"] for r in o["reps"]])
            for o in st["offices"].values()
            if o.get("status") in ACTIVE + ("no_slack",)]
    if left:
        st["pending_ts"] = out.channel(M.pending_for_evelyn(left),
                                       thread_ts=st.get("thread_ts"))
    st["closed"] = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true",
                    help="really send (with --test-to: only to that person)")
    ap.add_argument("--test-to", default="",
                    help="Slack member id that receives EVERYTHING instead")
    ap.add_argument("--date", help="pretend today is YYYY-MM-DD")
    ap.add_argument("--rosters", help="reuse a rosters-*.json instead of "
                                      "reading OwnerVille")
    ap.add_argument("--only", nargs="*", help="limit to these office numbers")
    ap.add_argument("--show", action="store_true", help="print the state")
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    if a.show:
        print(json.dumps(load_state(today), indent=1)[:20000])
        return 0
    mode = "dry" if not a.live else ("test" if a.test_to else "live")
    if mode == "test" and len(a.only or []) != 1:
        # Every test DM lands in ONE conversation, so two offices would read
        # each other's answers. One office per rehearsal.
        print("--test-to needs --only with exactly ONE office number")
        return 2
    out = Out(mode, a.test_to)
    st = load_state(today) if mode != "dry" else None
    if st and st.get("mode") != mode:
        print(f"this month's state was made in {st.get('mode')!r} mode, not "
              f"{mode!r} — refusing to mix them. Move {state_path(today)} "
              "aside to start over.")
        return 1
    steps = due(st, today) if mode != "dry" else ["start", "summary", "close"]
    print(f"owner rep audit · {today} · {mode} · steps: {', '.join(steps) or 'none'}")
    for step in steps:
        if step == "start":
            st = start(today, out, a.rosters or "", a.only)
        elif step == "poll":
            poll(st, out, today)
        elif step == "remind":
            remind(st, out)
        elif step == "summary":
            summary(st, out)
        elif step == "close":
            close(st, out)
        if st is not None and mode != "dry":
            save_state(today, st)
    if st:
        counts: Dict[str, int] = {}
        for o in st["offices"].values():
            counts[o["status"]] = counts.get(o["status"], 0) + 1
        print("status:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
