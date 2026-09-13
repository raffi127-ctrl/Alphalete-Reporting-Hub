"""Text the admin-staff chat the day before a rep's birthday.

Raf's ask (l10-alphalete, 2026-09-13): check the board for birthdays and ping
admin staff the DAY BEFORE, so somebody grabs a photo and the birthday social
post goes out on the actual day. SCOPE: RAF'S OFFICE ONLY (Megan, same day).

  python -m automations.birthday_reminders.run             # dry-run: prints, sends nothing
  python -m automations.birthday_reminders.run --send      # actually text
  python -m automations.birthday_reminders.run --date 2026-09-14   # pretend it's that day
  python -m automations.birthday_reminders.run --init      # create the 'DOB LUCY' tab once
  python -m automations.birthday_reminders.run --who       # who WOULD be texted, and why not

DRY-RUN IS THE DEFAULT and the group is resolved even on a dry run, because
membership is the half most likely to be wrong and a preview that skipped it
would prove nothing (same rule as text_post's own sends).

NOBODY IS TEXTED WE CANNOT PROVE IS WORKING THIS WEEK -- see liveness.py. The
skip list is printed every run, so a wrong suppression is visible rather than
silent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.birthday_reminders import config as C
from automations.birthday_reminders import liveness as L
from automations.birthday_reminders import store as S

# The success line prints emoji; a Windows console (cp1252) raises on that
# AFTER the text has gone out, which makes a clean send look like a crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
           "Saturday", "Sunday")


def _mdy(d: dt.date) -> str:
    """'9/14' -- built by hand, never '%-m/%-d': that flag is a no-op on
    Windows and every report here runs on both. [[cross-platform]]"""
    return "%d/%d" % (d.month, d.day)


def compose(names: list, day: dt.date) -> str:
    """The text itself. Real emoji, not ':cake:' -- iMessage shows shortcodes
    literally (same reason alphalete_sales_board/notify.py spells out FIRE)."""
    when = "%s %s" % (WEEKDAY[day.weekday()], _mdy(day))
    if len(names) == 1:
        who = names[0]
        head = "%s Birthday tomorrow (%s): %s" % (C.CAKE, when, who)
    else:
        head = "%s Birthdays tomorrow (%s): %s" % (
            C.CAKE, when, ", ".join(names))
    return head + "\n\nGrab a photo today so the post is ready to go out."


def plan(today: dt.date, *, logfn=print, source: str = "auto") -> dict:
    """Who would be texted tomorrow, who wouldn't, and why. No sends, no writes."""
    target = today + dt.timedelta(days=C.DAYS_AHEAD)
    want = S.today_mmdd(target)
    entries = S.load()
    hits = S.birthdays_on(entries, want)
    opted = [e.name for e in entries if e.mmdd.strip() == want and e.opted_out]

    out = {"today": today, "target": target, "mmdd": want,
           "stored": len(entries), "opted_out": opted,
           "send": [], "skip": [], "text": "", "degraded": ""}
    if not hits:
        return out

    live = L.read(today, logfn=logfn, source=source)
    out["degraded"] = live.degraded
    out["board_tab"] = live.tab
    for e in hits:
        v = live.verdict(e.name)
        (out["send"] if v.allowed else out["skip"]).append(v)
    if out["send"]:
        out["text"] = compose([v.name for v in out["send"]], target)
    return out


def _report(p: dict, logfn=print) -> None:
    logfn("Birthdays for %s (%s) -- %d name(s) stored"
          % (_mdy(p["target"]), p["mmdd"], p["stored"]))
    if p.get("board_tab"):
        logfn("  board: %s" % p["board_tab"])
    for v in p["send"]:
        logfn("  SEND  %s -- %s" % (v.name, v.why))
    for v in p["skip"]:
        logfn("  skip  %s -- %s" % (v.name, v.why))
    for name in p["opted_out"]:
        logfn("  skip  %s -- opted out by hand (Skip column)" % name)
    if not p["send"] and not p["skip"] and not p["opted_out"]:
        logfn("  nobody has a birthday tomorrow.")


def run(*, today: dt.date | None = None, dry_run: bool = True,
        logfn=print, source: str = "auto") -> int:
    today = today or dt.date.today()
    p = plan(today, logfn=logfn, source=source)
    _report(p, logfn)

    if not p["send"]:
        # NOT an error and NOT a failed run: most days nobody has a birthday.
        # [[findings are not failures]]
        _publish("success", "no birthdays tomorrow" if not p["skip"]
                 else "%d skipped, none to send" % len(p["skip"]))
        return 0

    if not C.GROUP_ADMIN_STAFF:
        logfn("\n⚠ No admin-staff chat configured yet. The text below is READY "
              "but cannot be addressed.\n"
              "  Set config.GROUP_ADMIN_STAFF to the chat's name (a needle, not "
              "a GUID), or export BIRTHDAY_GROUP to test.\n"
              "  Find it with: lucy find_group <part of the name> --machine \"Lucy 1\"")
        logfn("\n--- the text ---\n%s\n----------------" % p["text"])
        _publish("problem", "admin-staff chat not configured")
        return 1

    from automations.b2b_dispositions import text_post
    logfn("\n--- the text ---\n%s\n----------------" % p["text"])
    try:
        res = text_post.send_text_to_group(C.GROUP_ADMIN_STAFF, p["text"],
                                           dry_run=dry_run)
    except text_post.GroupTextError as e:
        # Resolution failing means Lucy isn't in that chat any more -- which is
        # exactly what it should mean. Loud, not silent.
        logfn("⚠ couldn't reach the admin-staff chat: %s" % e)
        _publish("problem", str(e)[:200])
        return 1

    # %s, not %d: find_groups returns `participants` as a STRING on Lucy 1
    # (AppleScript hands back text), and a %d there raised TypeError AFTER the
    # send had already gone out -- the send succeeds and the run reads failed.
    # The unit test passed because it used an int. Caught only by running on the
    # real machine (2026-09-13).
    logfn("%s %s to %r (%s participants)"
          % ("✅ Texted" if not dry_run else "(dry run) would text",
             ", ".join(v.name for v in p["send"]),
             res.get("resolved_name"), res.get("participants", "?")))
    if not dry_run:
        _publish("success", "texted %d birthday(s)" % len(p["send"]))
    return 0


def _publish(status: str, note: str) -> None:
    """Best-effort Hub publish -- a Hub write must never fail the send.
    [[a LaunchAgent report publishes to the Hub]]"""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(C.HUB_REPORT_ID, C.HUB_CARD,
                                 status=status, note=note)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Text admin staff the day before a rep's birthday (Raf's office).")
    ap.add_argument("--send", action="store_true",
                    help="Actually text (default is a dry run that sends nothing).")
    ap.add_argument("--date", help="Pretend today is this YYYY-MM-DD (testing).")
    ap.add_argument("--init", action="store_true",
                    help="Create the 'DOB LUCY' tab with its headers, once.")
    ap.add_argument("--who", action="store_true",
                    help="Print who would be texted and why not, then stop.")
    ap.add_argument("--source", choices=("auto", "site", "sheet"), default="auto",
                    help="Where 'is this rep still here' comes from. 'auto' uses "
                         "the site roster once it actually records terminations, "
                         "and the sales board until then.")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    if args.init:
        res = S.create_tab(dry_run=not args.send)
        if res.get("created"):
            print("✅ created %r with headers: %s"
                  % (C.STORE_TAB, ", ".join(res["headers"])))
        elif res.get("why") == "already exists":
            print("%r already exists -- nothing to do." % C.STORE_TAB)
        else:
            print("(dry run) would create %r with headers: %s\n"
                  "Re-run with --send to actually create it."
                  % (C.STORE_TAB, ", ".join(res.get("headers", []))))
        return 0

    if args.who:
        _report(plan(today, source=args.source))
        return 0

    return run(today=today, dry_run=not args.send, source=args.source)


if __name__ == "__main__":
    # Non-technical people run these from the Hub. A traceback is not an error
    # message -- print the sentence and nothing else. [[7-year-old-simple]]
    try:
        sys.exit(main())
    except S.StoreError as e:
        print("\u26a0 %s" % e)
        sys.exit(1)
