"""When the push is allowed to run — and what a refusal costs.

Its own module, with NO imports beyond the stdlib, for two reasons: the test can
pin every edge of the window without importing run.py (which pulls patchright
and a warm-Chrome stack), and nothing in the test can ever reach a live push.
"""
from __future__ import annotations

# Exit code for "declined on purpose, nothing ran, nothing is broken" — 75,
# EX_TEMPFAIL, which is already this repo's word for HELD (sales_boards,
# rep_sales_fill, vantura_*, and post_watch's "exit 75 = held, a no-post is
# legit"). The wrapper (deploy/applicant_push.sh) treats it as a healthy skip;
# any OTHER non-zero is still a bad pass that counts toward the failure streak.
#
# NOT 3, which this first shipped as: rc=3 is already spoken for in this exact
# family — resume_pushing exits 3 for an Indeed/Turnstile extractor wedge
# ("exiting rc=3 so the next pass self-heals and the fail-streak notifier can
# fire"), and oat_processing returns 3 for an AppStream-busy session. Today
# applicant_push.run() swallows both (it always returns 0), so nothing collided
# yet — but a wrapper that reads 3 as "healthy skip" is a loaded gun pointed at
# the day someone propagates a stage's rc, and it would mute exactly the wedge
# alert Lucy 2 depends on.
QUIET_EXIT = 75


def quiet_window(now) -> bool:
    """Is `now` inside the weekend quiet window? Fri 1:00 PM -> Sun 1:00 PM,
    machine-local (Lucy 2 runs Central). Carlos, 2026-09-04 — supersedes the
    plain Saturday block of 2026-08-31."""
    wd, hr = now.weekday(), now.hour
    # 2026-10-04 ONLY (Carlos, 10/2: "this sunday lets start up at 2pm"): that
    # Sunday the window ends an hour later. Every other Sunday stays 1 PM.
    sunday_end = 14 if now.date().isoformat() == "2026-10-04" else 13
    return (wd == 4 and hr >= 13) or wd == 5 or (wd == 6 and hr < sunday_end)


# ---- CARLOS'S SCHEDULE, ON THE LUCYS TOO (Megan 2026-10-28) -----------------
# "make all of these accounts follow the schedule carlos set": his relay
# computer pushes 5:30 AM - 10:00 PM, each pass 15 minutes apart
# (icd_alerts/resume_push.py DAY_START / DAY_END / EVERY_MINUTES). The Lucys ran
# 7:00 AM - 10:00 PM with each office every ~4-6 min. Before 7:00 a Lucy's own
# 4am batch can still be running, and Megan chose "5:30, after 4am run": a push
# never starts on a Lucy while its 4am reports are busy ("we CANNOT mess up the
# 4am run", 2026-10-21).
DAY_START = (5, 30)
DAY_END = (22, 0)            # the 22:00 tick itself still runs, as before
BATCH_FREE_FROM = (7, 0)     # from 7:00 the old schedule never checked the batch
EVERY_MINUTES = 15


def in_hours(now) -> bool:
    hm = (now.hour, now.minute)
    return DAY_START <= hm <= DAY_END


def needs_batch_check(now) -> bool:
    return (now.hour, now.minute) < BATCH_FREE_FROM


def due(last_start_epoch, now_epoch: float) -> bool:
    """15 minutes since this office's last pass started (or never ran)."""
    if not last_start_epoch:
        return True
    return now_epoch - float(last_start_epoch) >= EVERY_MINUTES * 60


def gate(office: str, stamp_path: str, now=None, batch_running=None):
    """(go, reason) for one office's tick. batch_running is a callable
    returning True / False / None (None = can't tell, treated as busy)."""
    import datetime as _dt
    import os
    import time
    now = now or _dt.datetime.now()
    if not in_hours(now):
        return False, "outside 5:30AM-10PM CST window (h=%d)" % now.hour
    if needs_batch_check(now):
        if batch_running is None:
            from automations.day_orchestrator.mini_control import _batch_running
            batch_running = _batch_running
        busy = batch_running()
        if busy is None or busy:
            return False, ("before 7AM and this Lucy's 4am run is still going"
                           if busy else "before 7AM and the 4am run state "
                           "can't be read -- waiting")
    try:
        last = open(stamp_path).read().strip() if os.path.exists(stamp_path) else ""
    except OSError:
        last = ""
    if not due(last, time.time()):
        mins = (time.time() - float(last)) / 60
        return False, "office %s ran %.0f min ago (every %d min)" % (
            office, mins, EVERY_MINUTES)
    return True, "ok"


if __name__ == "__main__":
    # bash deploy/applicant_push.sh: python -m automations.applicant_push.window
    #   <office> <stamp file>  -> exit 0 = go, 75 = skip (reason on stdout)
    import sys
    ok, why = gate(sys.argv[1], sys.argv[2])
    print(why)
    sys.exit(0 if ok else QUIET_EXIT)
