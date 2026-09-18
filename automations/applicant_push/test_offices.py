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


# --- no-phone removal policy is PER OFFICE (Carlos 2026-08-27) ---------------
# "in my specific office, if they don't have a phone number on the resume, you
# don't remove them. You leave them there." A regression here silently DELETES
# applicants, so assert both directions, and assert every office STATES a policy
# rather than inheriting one — a new office defaulting to True would start
# removing people in an office nobody chose that for.
print("no-phone removal policy")
from automations.oat_processing import config as _oat_config
for _oid in sorted(offices.OFFICES):
    check("office %s states a no-phone policy" % _oid,
          "remove_no_phone" in offices.OFFICES[_oid], True)
offices.activate("11580")
check("11580 LEAVES no-phone applicants", _oat_config.REMOVE_NO_PHONE, False)
offices.activate("23467")
# 9/12 (Carlos): Atef's office joined Carlos's rule — a no-number applicant STAYS
# in the queue. This assertion still read True from the 8/27 policy and had been
# failing since the row flipped; the row is what Carlos asked for, so the test
# moved, not the config.
check("23467 LEAVES no-phone applicants too (Carlos, 9/12)",
      _oat_config.REMOVE_NO_PHONE, False)
offices.activate("11580")

# --- which machine works which offices (2026-09-13) -------------------------
# Raf's 23965 moved to Lucy 3 so the other three stop paying for it. Three things
# have to stay true, and each one has cost a real outage in this repo's history:
#   * every LIVE office is worked by exactly one machine — assigned twice and two
#     boxes race the same queue; assigned zero times and it is worked by nobody
#     while every Hub card stays green;
#   * an unknown machine gets NOTHING, so Megan's marker-less laptop can never
#     start sending real applicants;
#   * the diagnostic offices stay out of every machine's rotation.
_assigned = [o for offs in offices.ROTATION_BY_MACHINE.values() for o in offs]
check("no office is assigned to two machines",
      len(_assigned), len(set(_assigned)))
check("every ROTATION office has a machine",
      sorted(set(_assigned)), sorted(offices.ROTATION))
# The Lucy 3 split is PARKED until Lucy 3 can hold an AppStream session, so all
# SIX live offices are Lucy 2's — Carlos, Atef, Khalil and Raf's three streams
# (11280 / 23965 / 24065, added 2026-09-18). The check that actually protects
# production is not which box owns what — it is that NOTHING is orphaned, pinned
# just below.
_LUCY2 = ["11580", "23467", "11901", "23965", "11280", "24065"]
check("every live office is worked by Lucy 2 while the split is parked",
      offices.rotation_for("Lucy 2"), _LUCY2)
check("Lucy 3 is assigned nothing yet", offices.rotation_for("Lucy 3"), [])
check("a marker written in lower case still resolves",
      offices.rotation_for("lucy 2"), _LUCY2)
check("an unknown machine gets no offices at all",
      offices.rotation_for("Megans-MacBook.local"), [])
check("so does a machine with no name", offices.rotation_for(""), [])
for _oid in _assigned:
    check("assigned office %s exists" % _oid, _oid in offices.OFFICES, True)
    check("assigned office %s uses the resume login" % _oid,
          offices.OFFICES[_oid]["account"], offices.RESUME_ACCOUNT)

# A scheduled office that run.py would REFUSE to push is worse than one that is
# missing: the rotation keeps handing it ticks and every one of them dies on the
# allowlist. 11901 cost hours to a row that was in the rotation but broken; this
# pins the two lists to each other.
from automations.applicant_push import run as push_run
check("every rotation office is on run.py's live allowlist",
      sorted(set(offices.ROTATION) - push_run.PUSH_ALLOWED), [])
check("the allowlist holds nothing that nobody rotates",
      sorted(push_run.PUSH_ALLOWED - set(offices.ROTATION)), [])

# --- Raf's three streams (Carlos, 2026-09-18) -------------------------------
# All three are HIS offices, and two of them were added on the same day, so the
# thing to pin is that they did not inherit each other's state or somebody
# else's Slack channel.
print("Raf's three streams are live, isolated, and post nowhere")
for _oid in ("11280", "23965", "24065"):
    _o = offices.get(_oid)
    check("%s is Raf's" % _oid, _o["owner"], "Rafael Hidalgo")
    check("%s is in the rotation" % _oid, _oid in offices.ROTATION, True)
    # None of Raf's offices has been asked for a daily to-do post, and none of
    # them may ever text an applicant (only Carlos's 11580 texts).
    check("%s posts no to-do list" % _oid, _o["post_todo"], False)
    check("%s never texts an applicant" % _oid, _o["allow_retext"], False)
    # The channel a to-do WOULD use, if it is ever switched on: Raf's own, never
    # Carlos's #alphaletegp-recruiting (C09L1S3MQ1E).
    check_ne("%s does not point at Carlos's channel" % _oid,
             _o["post_channel"], "C09L1S3MQ1E")
offices.activate("11580")

# --- the wrapper knows every office the table rotates -----------------------
# deploy/applicant_push.sh carries three per-office case statements, and a
# rotation office missing from any of them fails in its own quiet way:
#   * no label/HUB_ID arm  -> the unknown-office arm skips the tick, forever;
#   * no OAT env arm       -> the separate summary process reads ANOTHER
#                             office's suffix, tab and channel;
#   * no pkill arm         -> a wedge kill leaves Chrome holding that office's
#                             profile lock and the next tick cannot relaunch
#                             (this one really happened, to 11901 and 23965).
# The table is the source of truth, so check the script against it rather than
# trusting two lists to be edited together.
print("deploy/applicant_push.sh handles every rotation office")
import pathlib as _pathlib
_wrapper = (_pathlib.Path(__file__).resolve().parents[2]
            / "deploy" / "applicant_push.sh").read_text(encoding="utf-8")
for _oid in offices.ROTATION:
    _o = offices.get(_oid)
    check("%s has a label/HUB_ID arm" % _oid,
          ('HUB_ID="%s"' % _o["hub_report_id"]) in _wrapper, True)
    check("%s has a wedge-kill arm" % _oid,
          ("pkill -f %s " % _o["cdp_kill_pat"]) in _wrapper, True)
# 11580 is the exception by design: it runs on the module defaults so its files
# stay unsuffixed, so it exports no OAT_OFFICE_ID.
for _oid in offices.ROTATION:
    if _oid == "11580":
        continue
    check("%s exports its own OAT day-file suffix" % _oid,
          ('export OAT_FILE_SUFFIX="%s"' % offices.get(_oid)["suffix"]) in _wrapper,
          True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
