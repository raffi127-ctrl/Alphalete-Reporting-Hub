"""Prove a newly enrolled office actually works — before it starts ticking.

An office confirmed on the sign-up form is wired but switched OFF, because the
two things that decide whether it can run are not on the form and not visible
from the Streamlit deploy:

  1. OFFICE ACCESS. Impersonation has to be granted for that owner in
     OwnerVille. Without it every tick fails, and at 15 minutes apart that is
     an incident stream, not a report ([[project_gap_alerts]] runs a
     fail-streak alert for exactly this).
  2. THE iMESSAGE ROOM. The chat only exists in LUCY 1's Messages, and only if
     alphaletereporting@ was added to it. A name that resolves to zero chats —
     or to two — is a send that never lands.

So instead of Megan checking both by hand and coming back to tick a box, this
runs ON THE RUNNER, proves them, and turns the office on if they hold. That is
the difference between "signed up" and "wired up without me having to do much".

  python -m automations.disposition_signup.preflight --key cody
  python -m automations.disposition_signup.preflight --key cody --enable --notify

Nothing is ever SENT here: the board is pulled and thrown away. A failed check
leaves the office off and says why.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List

from automations.disposition_signup import store
from automations.disposition_signup.schema import DispositionRecord


def _check_groups(rec: DispositionRecord) -> "List[Dict]":
    """One check per iMessage room: does each resolve to exactly one live chat
    on this box? An office can list several, and "one of them resolves" is not
    an answer — the one that does not is a room that silently gets nothing."""
    rooms = rec.of_kind("imessage")
    if not rooms:
        return [{"name": "iMessage group", "ok": True,
                 "note": "not enrolled for texts — skipped"}]
    from automations.b2b_dispositions import text_post as tp
    out = []
    for d in rooms:
        name = (d.get("name") or "").strip()
        label = "iMessage %r" % name
        try:
            hit = tp.resolve_group(name)
        except Exception as e:                       # noqa: BLE001
            out.append({"name": label, "ok": False, "note": str(e)[:220]})
            continue
        out.append({"name": label, "ok": True,
                    "note": "resolved (%s participants)"
                            % hit.get("participants")})
    return out


def _check_board(rec: DispositionRecord, day: dt.date, *,
                 headless: bool = True) -> Dict:
    """Can we impersonate the office and pull its board? This is the Office
    Access check and the campaign check at once — a wrong campaign pin comes
    back as a grid without the columns the scraper needs."""
    from automations.disposition_signup import apply as A
    from automations.gap_alerts import run as R

    cfg = A._row(rec)
    out_dir = Path(R.OUTPUT_DIR) / "preflight" / day.strftime("%Y-%m-%d")
    try:
        pngs, rows = R.pull_board(cfg, day, out_dir, "preflight")
    except Exception as e:                           # noqa: BLE001
        return {"name": "Office Access + campaign", "ok": False,
                "note": "%s: %s" % (type(e).__name__, str(e)[:220])}
    if not pngs:
        # Not a failure: before the field is out there are simply no rows, and
        # that is the same "nothing to send" the live tick treats as fine.
        return {"name": "Office Access + campaign", "ok": True,
                "note": "impersonated OK — no rows yet today (field not out)"}
    return {"name": "Office Access + campaign", "ok": True,
            "note": "impersonated OK — %d rep row(s) pulled" % len(rows)}


def check(key: str, *, headless: bool = True,
          day: "dt.date | None" = None) -> Dict:
    """Run every check for one office. -> {ok, rec, checks:[...]}"""
    d = store.load_one(key)
    if not d:
        return {"ok": False, "rec": None,
                "checks": [{"name": "sign-up row", "ok": False,
                            "note": "no sign-up found for %r" % key}]}
    rec = store.record_from_json(d)
    if rec.status != "wired":
        return {"ok": False, "rec": rec,
                "checks": [{"name": "sign-up row", "ok": False,
                            "note": "still %r — confirm it on the form first"
                                    % (rec.status or "unset")}]}
    checks: List[Dict] = list(_check_groups(rec))
    checks.append(_check_board(rec, day or dt.date.today(),
                               headless=headless))
    return {"ok": all(c["ok"] for c in checks), "rec": rec, "checks": checks}


def enable(rec: DispositionRecord) -> str:
    """Flip the office ON in the Sheet and re-materialize it. Only ever called
    after every check passed — this is proof, not an assumption."""
    from automations.disposition_signup import apply as A
    rec.enabled = True
    rec.submitted_by = "preflight (verified)"
    where = store.update(rec)
    A.main(["--only", rec.key, "--write"])
    return where


def summary(key: str, res: Dict) -> str:
    who = res["rec"].display() if res.get("rec") else key
    lines = ["%s — %s" % (who, "READY" if res["ok"] else "NOT READY")]
    for c in res["checks"]:
        lines.append("  %s %s: %s" % ("*" if c["ok"] else "x", c["name"],
                                      c["note"]))
    return "\n".join(lines)


def notify(key: str, res: Dict, *, enabled: bool) -> None:
    """One line to the corrections channel, detail in the thread — the standing
    format. Best-effort: a failed post must not fail the preflight."""
    rec = res.get("rec")
    who = rec.display() if rec else key
    if res["ok"]:
        title = ("Dispositions preflight passed for %s — %s"
                 % (who, "switched ON, it joins the next tick" if enabled
                    else "ready to switch on"))
    else:
        title = "Dispositions preflight failed for %s — still switched off" % who
    thread = ["- %s %s: %s" % ("PASS" if c["ok"] else "FAIL", c["name"],
                               c["note"]) for c in res["checks"]]
    if rec is not None:
        thread.append("- %s, %s" % (rec.cadence_label(), rec.hours_label()))
        thread += ["- %s" % r for r in rec.routes()]
    try:
        from automations.day_orchestrator import registry, notify as _n
        from automations.shared.slack_metrics_post import _client
        channel = _n._corrections_channel(registry.load_config())
        client = _client()
        top = client.chat_postMessage(channel=channel, text=title,
                                      unfurl_links=False, unfurl_media=False)
        client.chat_postMessage(channel=channel, thread_ts=top["ts"],
                                text="\n".join(thread), unfurl_links=False,
                                unfurl_media=False)
    except Exception as e:                           # noqa: BLE001
        print("[preflight] corrections post skipped: %s: %s"
              % (type(e).__name__, str(e)[:160]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="disposition_signup.preflight")
    ap.add_argument("--key", required=True, help="office key from the sign-up")
    ap.add_argument("--enable", action="store_true",
                    help="switch the office ON if every check passes")
    ap.add_argument("--notify", action="store_true",
                    help="post the result to the corrections channel")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)

    res = check(args.key, headless=not args.headed)
    print(summary(args.key, res))
    turned_on = False
    if res["ok"] and args.enable and res.get("rec") is not None:
        if res["rec"].enabled:
            print("already switched on — nothing to change")
        else:
            print("switching ON (%s)" % enable(res["rec"]))
            turned_on = True
    if args.notify:
        notify(args.key, res, enabled=turned_on)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
