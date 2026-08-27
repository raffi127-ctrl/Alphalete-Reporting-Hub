"""Browser-free, Slack-free checks on the multi-office Applicant Push wiring.

The whole risk of running two offices through one flow is CROSSED STATE — office
A's Chrome profile, day-files, Sheet tab or Slack channel getting used for office
B. Every check here is about that: activate() must move ALL of it, and 11580 must
keep its original names so nothing already in flight moves under Carlos.

Run:  PYTHONPATH=. .venv/bin/python -m automations.applicant_push.test_offices
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import datetime as dt

from automations.applicant_push import offices
from automations.oat_processing import config as oat_config
from automations.oat_processing import run as oat_run
from automations.oat_processing import summary as oat_summary
from automations.oat_processing import session_wedge_watch as wedge
from automations.resume_pushing import run as rp

_passed = 0
_failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


def check_ne(label, a, b):
    global _passed, _failed
    if a != b:
        _passed += 1
        print("  [ok] %s: %r != %r" % (label, a, b))
    else:
        _failed += 1
        print("  [FAIL] %s: both are %r" % (label, a))


print("every office declares its own isolation keys:")
# A shared profile/port/kill-pattern/suffix is the bug this table exists to
# prevent, so assert they are unique ACROSS the table rather than per-office.
for field in ("cdp_profile", "cdp_port", "cdp_kill_pat", "suffix",
              "walk_diag_tab", "push_diag_tab", "log_stem", "hub_report_id"):
    vals = [o[field] for o in offices.OFFICES.values()]
    check("%s values are all distinct" % field, len(set(vals)), len(vals))

# A kill pattern that is a SUBSTRING of another office's profile path would let
# one office pkill the other's Chrome (every run does `pkill -f <kill_pat>`).
print("no office's pkill pattern can match another office's Chrome:")
for a in offices.OFFICES.values():
    for b in offices.OFFICES.values():
        if a is b:
            continue
        check("%s's kill pattern misses %s's profile"
              % (a["office_id"], b["office_id"]),
              a["cdp_kill_pat"] in b["cdp_profile"], False)

print("11580 keeps every original name (nothing in flight moves):")
carlos = offices.get("11580")
check("suffix is empty", carlos["suffix"], "")
check("profile unchanged", carlos["cdp_profile"], "/tmp/rp_cdp_profile")
check("port unchanged", carlos["cdp_port"], "9245")
check("walk diag tab unchanged", carlos["walk_diag_tab"], "OAT Walk Diag")
check("hub id unchanged", carlos["hub_report_id"], "applicant_push")
check("log stem unchanged", carlos["log_stem"], "applicant-push")

print("activate(23467) moves the browser, the files, the tab and the channel:")
offices.activate("23467")
check("rp office", rp.OFFICE_ID, "23467")
check("rp hint", rp.OFFICE_HINT, "ATEF CHOUDHURY")
check("rp profile", rp.CDP_PROFILE, "/tmp/rp_cdp_23467")
check("rp port", rp.CDP_PORT, "9247")
check("rp kill pattern", rp._CDP_KILL_PAT, "rp_cdp_23467")
# Derived from CDP_PROFILE at import — if it does not move, office B reuses
# office A's "already seeded" marker and never seeds its own profile.
check("rp seed marker follows the profile",
      rp._CDP_SEED_MARKER, "/tmp/rp_cdp_23467/.rp_seeded")
check("oat office", oat_config.OFFICE_ID, "23467")
check("oat file suffix", oat_config.FILE_SUFFIX, "-23467")
check("walk diag tab", oat_config.WALK_DIAG_TAB, "OAT Walk Diag 23467")
check("summary channel is Atef's own", oat_summary.CHANNEL_ID, "C0B85KRS5FU")

print("every per-day artefact is namespaced (no office overwrites another):")
today = dt.date.today().isoformat()
check("activity csv", oat_run._activity_csv(),
      "output/oat-activity-%s-23467.csv" % today)
check("nophone cache", oat_run._nophone_checked_path().name,
      "oat-nophone-checked-%s-23467.json" % today)
check("blocked cache", oat_run._nophone_blocked_path().name,
      "oat-nophone-blocked-%s-23467.json" % today)
check("summary reads the SAME activity csv the walk writes",
      str(oat_summary._activity_path(dt.date.today())),
      "output/oat-activity-%s-23467.csv" % today)

print("back on 11580, every name is the original again:")
offices.activate("11580")
check("rp office", rp.OFFICE_ID, "11580")
check("rp profile", rp.CDP_PROFILE, "/tmp/rp_cdp_profile")
check("rp seed marker", rp._CDP_SEED_MARKER, "/tmp/rp_cdp_profile/.rp_seeded")
check("oat suffix", oat_config.FILE_SUFFIX, "")
check("activity csv", oat_run._activity_csv(), "output/oat-activity-%s.csv" % today)
check("walk diag tab", oat_config.WALK_DIAG_TAB, "OAT Walk Diag")
# activate() only ever OVERRIDES the channel — 11580's row is empty so the
# module default (#alphaletegp-recruiting) stands. Assert it is NOT Atef's, which
# is the failure that would put his applicants in Carlos's channel.
check_ne("summary channel is not Atef's", oat_summary.CHANNEL_ID, "C0B85KRS5FU")

print("the wedge alarm names the office the signature actually came from:")
check("Atef's log", wedge._office_of("applicant-push-23467-2026-08-26.log"), "23467")
check("Carlos's log", wedge._office_of("applicant-push-2026-08-26.log"), "11580")
check("retired single-office log", wedge._office_of("oat-processing-2026-08-26.log"),
      "11580")
check("label", wedge._office_label("23467"), "office 23467 (Atef Choudhury)")
# One incident thread per office: a wedge on Atef must not ✅ Carlos's open thread.
check("11580 keeps the original incident key",
      wedge._incident_key("11580"), "failure-oat-session-wedge")
check_ne("Atef gets his own incident key",
         wedge._incident_key("23467"), wedge._incident_key("11580"))
check_ne("Atef gets his own wedge state file",
         str(wedge._state_path("23467")), str(wedge._state_path("11580")))

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
