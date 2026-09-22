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


def run(office: str, hold_s: int = DEFAULT_HOLD_S) -> int:
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
        while time.time() - t0 < hold_s:
            blocked, title, body = _challenged(pg)
            if title == "(window closed)":
                print("[clear] window closed — stopping", flush=True)
                return 1
            if not blocked:
                print(f"[clear] ✅ through the check after "
                      f"{int(time.time() - t0)}s — title={title!r}", flush=True)
                print("[clear] the walk's next tick reads numbers normally; "
                      "you can close this window", flush=True)
                return 0
            print(f"[clear] {int(time.time() - t0):4d}s still on the check "
                  f"({title!r})", flush=True)
            pg.wait_for_timeout(10000)
        print(f"[clear] still on the check after {hold_s}s — give up for now; "
              f"the walk keeps retrying on its own", flush=True)
    return 4


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Open one resume so a human can clear Indeed's check")
    ap.add_argument("office", nargs="?", default="11280",
                    help="office id, e.g. 11280 (see applicant_push/offices.py)")
    ap.add_argument("--hold", type=int, default=DEFAULT_HOLD_S,
                    help="seconds to keep the window open waiting for the tick")
    args = ap.parse_args(argv)
    return run(args.office, args.hold)


if __name__ == "__main__":
    sys.exit(main())
