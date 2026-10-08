"""Ringover: the recruiters' phone system, and the other half of the audit.

WHY THIS EXISTS. The text audit can already see that the call is where
these recruiters lose people -- across the four accounts, bookings agreed
on a call show up at 14% against 47% when they are agreed by text, and the
gap holds at every booking lead time. The texts are readable, so they get
coached; the calls are not, so the single biggest leak gets a sentence of
inference. This reads the calls.

NOT RingCentral. automations/rc_contact_sync talks to RingCentral, which is
a different vendor doing a different job (B2B customer contacts on Taylor's
line). Ringover is what the recruiters log into -- the ARS doc lists it in
Day 1 homework beside Applicant Stream, Slack and Skool. The two share no
credentials, no base URL and no phone numbers. Do not reach for the RC
client here.

AUTH is one API key in a header, no OAuth dance:

    curl --header "Authorization: <key>" https://public-api.ringover.com/v2/calls

Megan makes it at Dashboard > Developer > API key, and the Rights chosen
at creation decide what this module can see. A key with no recording right
authenticates perfectly well and returns calls with no recording on them --
which reads exactly like a team that records nothing. probe() is what tells
the two apart, and it is why the first thing to run is a probe and not a
pull.

READ-ONLY. Every call here is a GET.
"""
from __future__ import annotations  # Lucy runs Python 3.9 -- keep lazy

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

BASE = "https://public-api.ringover.com/v2"
CREDS_PATH = (Path.home() / ".config" / "recruiting-report"
              / "ringover-key.json")
TIMEOUT_S = 45


class RingoverError(RuntimeError):
    pass


def api_key():
    """The key, from the environment or the 600-mode file."""
    env = os.environ.get("RINGOVER_API_KEY")
    if env:
        return env.strip()
    if not CREDS_PATH.exists():
        raise RingoverError(
            "no Ringover API key at {}. Make one at Dashboard > Developer > "
            "API key with the call and recording rights, then put it on this "
            "machine with `python -m automations.sms_audit.set_ringover_key` "
            "(hidden prompt -- it never reaches shell history or a log)."
            .format(CREDS_PATH))
    data = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
    key = (data.get("api_key") or "").strip()
    if not key:
        raise RingoverError("{} has no 'api_key' in it".format(CREDS_PATH))
    return key


def norm_phone(v):
    """Last 10 digits -- the only part two systems agree on.

    The same convention the rest of the audit uses, so a Ringover call and
    an AppStream applicant can be matched on it."""
    digits = re.sub(r"\D", "", str(v or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _get(path, params=None, key=None):
    r = requests.get(BASE + path, params=params or {},
                     headers={"Authorization": key or api_key()},
                     timeout=TIMEOUT_S)
    if r.status_code == 401:
        raise RingoverError(
            "Ringover rejected the key (401). Check it was copied whole and "
            "that it is still listed under Dashboard > Developer > API key.")
    if r.status_code == 403:
        raise RingoverError(
            "the key authenticated but is not allowed {} (403). Its Rights "
            "were set when it was created; make a new one with the call and "
            "recording rights.".format(path))
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RingoverError("Ringover {} on {}: {}".format(
            r.status_code, path, (r.text or "")[:300]))
    if not r.content:
        return None
    return r.json()


def calls(start_iso, end_iso, limit=50, key=None):
    """Calls in a window. [] means none in it -- never 'we could not look'.

    A failure raises; an empty window returns an empty list. The two must
    stay distinguishable or a dark key reads as a quiet week."""
    got = _get("/calls", {"start_date": start_iso, "end_date": end_iso,
                          "limit_count": limit}, key=key)
    if not got:
        return []
    return got.get("call_list") or []


def _first(d, *names):
    for n in names:
        v = d.get(n)
        if v:
            return v
    return None


# --- Empower: Ringover's own transcription -----------------------------------
# Seen on Megan's screen 2026-10-08: a call detail panel carrying an AI
# Summary, a Recording player, and a speaker-separated Transcript with
# timestamps ("(313) 550-9905: Come on!" / "RH Alphalete Marketing: Hello,
# this is Josh from Educor Cole"). That is Empower, and it means we never
# transcribe audio ourselves -- we read what Ringover already wrote.
#
# These take the call's UUID, not its numeric call_id.

def empower_transcript(uuid, key=None):
    """Speaker-separated transcript, or None when the call has none."""
    return _get("/empower/call/{}".format(uuid), key=key)


def empower_summary(uuid, key=None):
    """Ringover's written summary of the call, or None."""
    return _get("/empower/call/{}/summary".format(uuid), key=key)


def empower_moments(uuid, key=None):
    """Ringover's 'key moments' for the call, or None."""
    return _get("/empower/call/{}/moments".format(uuid), key=key)


def uuid_of(call):
    """The id the Empower routes want.

    The call list carries both a numeric call_id and a UUID, and only the
    UUID works on /empower/call/. Which key holds it differs by plan, so
    this reads the spellings rather than betting on one."""
    return _first(call, "cdr_uuid", "call_uuid", "uuid", "channel_id")


def describe(call):
    """What one call row actually carries, in the audit's own words."""
    rec = _first(call, "record", "recording", "record_url")
    return {
        "id": _first(call, "call_id", "id", "cdr_id"),
        "when": _first(call, "start_time", "date", "created_at"),
        "direction": _first(call, "direction", "type"),
        "seconds": call.get("total_duration") or call.get("duration"),
        "user": ((call.get("user") or {}).get("concat_name")
                 if isinstance(call.get("user"), dict) else call.get("user")),
        "their_number": norm_phone(
            _first(call, "to_number", "from_number", "contact_number") or ""),
        "recording": rec,
        # Ringover's own AI add-on. If their plan has it the transcript
        # arrives with the call and we never transcribe anything ourselves,
        # which is the difference between a cheap build and an expensive one.
        "transcript": _first(call, "transcription", "transcript",
                             "ai_transcription"),
    }


def probe(key=None, days=7, limit=25):
    """One round trip that answers every question the build depends on.

    Megan 2026-10-08 wants call recordings in the audit. Four things decide
    how that is built and none of them can be guessed from outside: whether
    the key can read calls at all, whether recordings come back on them,
    whether Ringover is already transcribing (their Empower add-on), and
    which users the key can see. Asking the API beats four rounds of me
    guessing at it -- the same reason probe_calls.py exists for AppStream."""
    import datetime as dt
    end = dt.datetime.utcnow()
    start = end - dt.timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    out = {"ok": False, "window_days": days}
    rows = calls(start.strftime(fmt), end.strftime(fmt), limit=limit, key=key)
    out["ok"] = True
    out["calls_seen"] = len(rows)
    if not rows:
        out["why"] = ("the key works but no calls came back for the last {} "
                      "days. Either nobody called, or this key's Rights do "
                      "not cover the team's users.".format(days))
        return out
    seen = [describe(c) for c in rows]
    out["fields_on_a_call"] = sorted(rows[0].keys())
    out["with_recording"] = sum(1 for s in seen if s["recording"])
    out["with_transcript"] = sum(1 for s in seen if s["transcript"])
    out["users"] = sorted({s["user"] for s in seen if s["user"]})
    out["sample"] = {k: v for k, v in seen[0].items() if k != "recording"}
    out["sample_has_recording"] = bool(seen[0]["recording"])

    # Empower is the whole cost question, so the probe answers it rather
    # than leaving it to be discovered mid-build. Try the longest call --
    # a 9-second one is not transcribed on any plan.
    longest = max(rows, key=lambda c: (c.get("total_duration")
                                       or c.get("duration") or 0))
    uid = uuid_of(longest)
    out["empower"] = {"tried_uuid": uid,
                      "seconds_of_that_call": (longest.get("total_duration")
                                               or longest.get("duration"))}
    if not uid:
        out["empower"]["why"] = (
            "no UUID on the call row, so the Empower routes cannot be "
            "addressed. The field names are in fields_on_a_call.")
        return out
    for name, fn in (("transcript", empower_transcript),
                     ("summary", empower_summary),
                     ("moments", empower_moments)):
        try:
            got = fn(uid, key=key)
        except RingoverError as e:
            out["empower"][name] = "FAILED: {}".format(e)
            continue
        out["empower"][name] = "nothing returned" if not got else got
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true",
                    help="report what this key can actually see, and stop")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    if not a.probe:
        ap.error("nothing to do yet -- run with --probe")
    try:
        got = probe(days=a.days)
    except RingoverError as e:
        print("[ringover] {}".format(e), file=sys.stderr)
        return 1
    print(json.dumps(got, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
