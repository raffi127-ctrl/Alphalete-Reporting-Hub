"""Open ONE applicant resume in a headed browser so a human can tick Indeed's
"Verify you are human" box.

    cd ~/recruiting-report && PYTHONPATH=. .venv/bin/python -m \
        automations.oat_processing.cf_clear_window 11280

This is the command the Slack alert prints (session_wedge_watch.run_resume_check).
It is the ONLY step in Applicant Push that needs a person, and only sometimes:
Indeed challenges the first resume a browser opens, the challenge usually clears
itself within ~40s (which is why the walk waits it out), and when it doesn't, a
human tick opens the gate.

WHY ONE TICK IS ENOUGH (measured 2026-09-22, Lucy 4, office 11280): after the
box was ticked on the first resume, the next SIX resumes in that same browser
rendered with no challenge at all. The check is per browser session, not per
applicant — so this window is worth opening even though the walk relaunches
Chrome on its own schedule: it proves the gate opens, and the reads that follow
inside this window fill numbers for real.

It uses the SAME Chrome profile the walk uses for that office, so nothing about
the session is special-cased. Run it on the machine named in the alert.

AND THEN IT DRAINS THE QUEUE (the reason to bother). The gate opens for this
browser SESSION, and the scheduled walk relaunches Chrome every tick — so a
clear that just ends buys a few minutes. Instead, once the check is past, this
runs the ordinary live walk inside the very session the person opened: numbers
filled, applicants sent, for as long as the queue lasts. `--just-clear` skips it.
The scheduled agent is paused while this runs (it would pkill this window's
Chrome on its next tick) and restarted afterwards.
"""
from __future__ import annotations

import argparse
import sys
import time

DEFAULT_HOLD_S = 600


def _open_resume(page, oat):
    """cmd-click 'View resume' on the applicant showing now → the new tab, or None."""
    _fr, loc = oat._view_resume_link(page)
    if loc is None:
        return None
    try:
        with page.context.expect_page(timeout=20000) as pi:
            loc.click(timeout=8000, modifiers=["Meta"])
        return pi.value
    except Exception as e:  # noqa: BLE001
        print(f"    (the click opened no tab: {type(e).__name__})", flush=True)
        return None


def _challenged(pg) -> tuple[bool, str, str]:
    """(still behind the check?, title, all-frame text) — the walk's own view."""
    try:
        title = (pg.title() or "")[:60]
    except Exception:  # noqa: BLE001
        return True, "(window closed)", ""
    texts = []
    try:
        texts.append(pg.evaluate("() => (document.body.innerText||'')") or "")
    except Exception:  # noqa: BLE001
        pass
    for f in pg.frames:
        try:
            t = f.evaluate("() => (document.body.innerText||'')") or ""
        except Exception:  # noqa: BLE001
            continue
        if t and t not in texts:
            texts.append(t)
    body = " ".join(" ".join(texts).split())
    low = (title + " " + body).lower()
    blocked = (not body) or "just a moment" in low \
        or "verify you are human" in low or "additional verification" in low
    return blocked, title, body


def run(office: str, hold_s: int = DEFAULT_HOLD_S, drain: bool = True) -> int:
    from automations.applicant_push import offices
    from automations.oat_processing import run as oat
    from automations.resume_pushing import run as rp

    offices.activate(office)
    label = offices.get(office).get("short", "office " + office)
    print(f"[clear] opening a resume for {label} — this uses the same browser "
          f"profile the walk uses", flush=True)
    with rp.warm_appstream_cdp_page(diag_tab=f"OAT Walk Diag {office}") as (page, _ctx, _net):
        oat.attach_dialog_accept(page)
        if not oat._open_oat_ready(page):
            print("[clear] could not open Process Emails — nothing to do", flush=True)
            return 2
        pg = None
        for _ in range(12):
            a = oat.read_current_applicant(page)
            pg = _open_resume(page, oat)
            if pg is not None:
                print(f"[clear] opened {a.first_name} {a.last_name}'s resume",
                      flush=True)
                break
            if not oat.advance_to_next(page):
                break
        if pg is None:
            print("[clear] no applicant in the queue has a resume link", flush=True)
            return 3
        try:
            pg.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        print("[clear] >>> tick the 'Verify you are human' box in this window <<<",
              flush=True)
        print("[clear] (it often clears on its own — give it ~40s first)", flush=True)
        t0 = time.time()
        cleared = False
        while time.time() - t0 < hold_s:
            blocked, title, body = _challenged(pg)
            if title == "(window closed)":
                print("[clear] window closed — stopping", flush=True)
                return 1
            if not blocked:
                cleared = True
                print(f"[clear] ✅ through the check after "
                      f"{int(time.time() - t0)}s — title={title!r}", flush=True)
                break
            print(f"[clear] {int(time.time() - t0):4d}s still on the check "
                  f"({title!r})", flush=True)
            pg.wait_for_timeout(10000)
        if not cleared:
            print(f"[clear] still on the check after {hold_s}s — giving up for now; "
                  f"the walk keeps retrying on its own", flush=True)
            return 4
        try:
            pg.close()
        except Exception:  # noqa: BLE001
            pass
        if not drain:
            print("[clear] done — you can close this window", flush=True)
            return 0
        # DRAIN, and this is the whole point of the window. The gate is open for
        # THIS browser session only: the scheduled walk relaunches Chrome every
        # tick and meets a brand-new check, so a clear that ends here buys a few
        # minutes. Walking the queue inside the session the human just opened
        # turns one tick of their time into the whole queue's numbers.
        print("[clear] gate is open — walking the queue in THIS session now "
              "(this is the real work: numbers filled, applicants sent)",
              flush=True)
        oat.reset_cf_session()
        oat._mark_cf_cleared()
        try:
            rc = oat.run_walk(page, live=True)
            print(f"[clear] walk finished (rc={rc})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[clear] walk error: {type(e).__name__}: {str(e)[:160]}",
                  flush=True)
            return 5
    return 0


AGENT_PLIST = "~/Library/LaunchAgents/com.alphalete.applicant-push.plist"


def _agent(action: str) -> bool:
    """bootout/bootstrap the scheduled push agent. It relaunches Chrome on its own
    every couple of minutes and pkills the office profile when it does — which
    would close this window under the person standing at it. Best effort: a
    machine without the agent (a laptop) just carries on."""
    import os
    import subprocess
    plist = os.path.expanduser(AGENT_PLIST)
    if not os.path.exists(plist):
        return False
    try:
        uid = os.getuid()
        r = subprocess.run(["launchctl", action, f"gui/{uid}"] +
                           ([plist] if action == "bootstrap" else [plist]),
                           capture_output=True, text=True)
        ok = r.returncode == 0
        print(f"[clear] scheduled push agent "
              f"{'paused' if action == 'bootout' else 'restarted'}"
              f"{'' if ok else ' (failed: ' + (r.stderr or '').strip()[:60] + ')'}",
              flush=True)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[clear] could not {action} the agent ({type(e).__name__})", flush=True)
        return False


def _machine_offices() -> list:
    """The offices THIS machine actually works, in rotation order."""
    try:
        from automations.applicant_push import offices
        return list(offices.rotation_for())
    except Exception:  # noqa: BLE001
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Open one resume so a human can clear Indeed's check")
    ap.add_argument("office", nargs="?", default="11280",
                    help="office id, e.g. 11280 (see applicant_push/offices.py)")
    ap.add_argument("--all", action="store_true",
                    help="every office this machine works, one window after "
                         "another — one sitting instead of one command each")
    ap.add_argument("--hold", type=int, default=DEFAULT_HOLD_S,
                    help="seconds to keep the window open waiting for the tick")
    ap.add_argument("--just-clear", action="store_true",
                    help="stop once the check is cleared; do NOT walk the queue")
    args = ap.parse_args(argv)
    todo = _machine_offices() if args.all else [args.office]
    if args.all and not todo:
        print("[clear] this machine has no office rotation — name one instead",
              flush=True)
        return 2
    # Pause the scheduled agent ONCE around the whole sitting, not per office:
    # its next tick would pkill whichever window is open at the time.
    paused = _agent("bootout")
    worst = 0
    try:
        for i, office in enumerate(todo, 1):
            if len(todo) > 1:
                print(f"\n[clear] ===== office {office} ({i} of {len(todo)}) =====",
                      flush=True)
            rc = run(office, args.hold, drain=not args.just_clear)
            worst = worst or rc
            if len(todo) > 1:
                print(f"[clear] office {office} finished (rc={rc})", flush=True)
        return worst
    finally:
        if paused:
            _agent("bootstrap")


if __name__ == "__main__":
    sys.exit(main())
