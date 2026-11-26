"""A send that finished should say so, instead of waiting to be found.

Megan, 2026-11-25, after the first real drug order: "nothing says a send
worked... an admin has no watcher -- they press Send and then keep reloading
a row."

WHAT WAS MISSING. `actions.refresh_send` asks the relay how a send went and
writes the verdict onto its 'Admin Requests' row -- but only when somebody
has the Office Admin page OPEN. Nobody sits on that page. So a background
check or a drug test that failed at the office machine sat as "at office
computer" until a person thought to go and look, and the failure mode is
silent in the worst way: the admin believes the tests went out, nobody is
invited, and the first anybody hears of it is a start date with no result.

So this is the watcher the admin does not have. It polls the open sends,
writes the verdict the page would have written, and DMs the office when one
lands. Both kinds -- a drug order and a background check fail the same way.

    python -m automations.office_admin.send_watch           # dry
    python -m automations.office_admin.send_watch --send

ONCE, WITHOUT A STATE FILE. A row is picked up only while it says "at office
computer", and writing the verdict moves it off that status -- so the pass
that notifies is the pass that resolves it, and the next pass cannot see it
again. No marker to drift out of step with the sheet.

IT TELLS YOU ABOUT FAILURES AND SUCCESSES BOTH, and that is deliberate. A
"sent" message is how somebody learns the thing they pressed actually
happened, which is the whole complaint. Silence reserved for success would
leave the admin in exactly the position they are in now, reloading a row to
find out nothing is wrong.

UNCONFIRMED IS ITS OWN MESSAGE. `judge_job` already separates "the office
machine started this and never answered" from a clean failure, because the
first may have invited people and pressing Send again could invite them
twice. That distinction is the single most important thing in the DM, so it
gets its own wording rather than being folded into "failed".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Dict, List, Optional

from automations.office_admin import config as C

WATCHED = (C.SEND_BGC, C.SEND_DRUG)

WHAT = {C.SEND_BGC: "Background checks", C.SEND_DRUG: "Drug tests"}


def open_sends(reqs, office_key: str = "") -> List[Dict]:
    """Rows for a send that is still out at the office machine."""
    want = office_key.strip().lower()
    out = []
    for r in reqs or []:
        if str(r.get("Action") or "").strip().lower() not in WATCHED:
            continue
        if str(r.get("Status") or "").strip() != C.AT_OFFICE:
            continue
        if want and str(r.get("Office Key") or "").strip().lower() != want:
            continue
        out.append(r)
    return out


def _names(row: Dict) -> List[str]:
    try:
        d = json.loads(row.get("Details") or "{}")
    except (TypeError, ValueError):
        return []
    return [("%s %s" % (p.get("first_name", ""), p.get("last_name", ""))).strip()
            for p in (d or {}).get("people") or [] if isinstance(p, dict)]


def message(row: Dict, result: Dict) -> str:
    """The DM. What was sent, for whom, and -- when it went wrong -- whether
    anybody might already have been invited."""
    kind = WHAT.get(str(row.get("Action") or "").strip().lower(), "A send")
    asked = _names(row)
    res = result if isinstance(result, dict) else {}
    sent = res.get("sent") or []
    would = res.get("would_send") or []
    failed = res.get("failed") or []
    unconfirmed = res.get("unconfirmed") or []

    if unconfirmed:
        # THE ONE THAT NEEDS A HUMAN. It may have gone out; pressing again
        # could invite the same people twice.
        head = ("⚠️ *%s — not sure these went out.* Check Sterling BEFORE "
                "sending again: a second press could invite them twice."
                % kind)
        who = unconfirmed
    elif failed or str(row.get("Status")) == C.FAILED:
        head = "❌ *%s — did not send.* Nobody was invited." % kind
        who = failed or asked
    elif would:
        head = ("🧪 *%s — test run.* Nothing was sent; this is who it would "
                "have gone to." % kind)
        who = would
    else:
        head = "✅ *%s sent.*" % kind
        who = sent or asked

    lines = [head, ""]
    for n in who:
        lines.append("   •  %s" % n)
    err = str(res.get("error") or "").strip()
    if err:
        lines += ["", "_%s_" % err[:300]]
    return "\n".join(lines)


def run(*, send: bool = False, office_key: str = "", log=print) -> int:
    """Resolve every open send and DM its office. Returns how many landed."""
    from automations.office_admin import actions, sheets as S
    from automations.icd_alerts import post

    ws = S.requests_tab()
    rows = open_sends(S.read_requests(ws), office_key)
    if not rows:
        log("  no sends waiting on an office machine")
        return 0
    log("  %d send(s) still out" % len(rows))

    landed = 0
    for r in rows:
        rid = r.get("Request ID")
        before = r.get("Status")
        try:
            after = actions.refresh_send(ws, r)
        except Exception as exc:  # noqa: BLE001 -- one row, not the run
            log("  %s: could not refresh (%s: %s)"
                % (rid, type(exc).__name__, str(exc)[:100]))
            continue
        if str(after.get("Status")) == before:
            log("  %s: still waiting" % rid)
            continue
        try:
            result = json.loads(after.get("Result") or "{}")
        except (TypeError, ValueError):
            result = {}
        text = message(after, result)
        landed += 1
        log("  %s: %s" % (rid, str(after.get("Status"))))
        if not send:
            log("  --dry-run: would DM --\n%s\n" % text)
            continue
        try:
            to = post.dm_office_people(str(r.get("Office Key") or ""), text,
                                       log=log)
            log("  DM'd %d person/people." % len(to))
        except Exception as exc:  # noqa: BLE001
            # THE VERDICT IS ALREADY ON THE ROW. A DM we could not deliver
            # must not make the run look like the send is still out, so this
            # is said and the pass carries on.
            log("  !! couldn't DM %s about %s (%s: %s) -- the verdict IS on "
                "the row" % (r.get("Office Key"), rid,
                             type(exc).__name__, str(exc)[:100]))
    return landed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="actually DM (default: say what it would do)")
    ap.add_argument("--office", default="", help="one office key")
    a = ap.parse_args(argv)
    n = run(send=a.send, office_key=a.office.strip().lower())
    print("%d send(s) resolved" % n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
