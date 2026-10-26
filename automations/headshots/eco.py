"""Lucy 3's half of the LucyEco headshot hand-over.

An ICD's OwnerVille login sees only that ICD's reps, so for every office but
Raf's the upload happens on the office's OWN computer
(automations/icd_alerts/headshot_jobs.py). This module is the other end:

  enqueue()       hand a finished headshot to the relay for one office
  results()       what the office computers have answered
  post_results()  reply in each office's thread with how the upload went,
                  then tell the relay it was posted (which also bins the photo)

Everything goes through the relay web app with the ADMIN key -- Lucy 3 needs
no access to the relay workbook or its Drive. The key lives in the relay's
Script Properties as LUCY_ADMIN_KEY and, on Lucy 3, in
~/.config/headshots/relay-admin-key (or env HEADSHOTS_RELAY_ADMIN_KEY).

    # read-only test of one office's computer (finds the person, reads their
    # Photo pill, uploads NOTHING):
    python -m automations.headshots.eco --test-job --office omar \\
        --name "First Last" --file photo.png

    # what has come back (and clear the test answers):
    python -m automations.headshots.eco --results
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

ADMIN_KEY_PATH = Path.home() / ".config" / "headshots" / "relay-admin-key"


class EcoError(RuntimeError):
    pass


def _admin_key() -> str:
    k = os.environ.get("HEADSHOTS_RELAY_ADMIN_KEY", "").strip()
    if not k and ADMIN_KEY_PATH.exists():
        k = ADMIN_KEY_PATH.read_text(encoding="utf-8-sig").strip()
    if not k:
        raise EcoError(
            "No relay admin key on this machine. Save the LUCY_ADMIN_KEY value "
            "from the relay's Script Properties to %s." % ADMIN_KEY_PATH)
    return k


def _call(extra: Dict) -> Dict:
    from automations.icd_alerts import offices as O
    from automations.icd_alerts import relay as R
    body = {"admin_key": _admin_key()}
    body.update(extra)
    raw = R._post(O.RELAY_URL, json.dumps(body).encode("utf-8"))
    try:
        out = json.loads(raw)
    except ValueError:
        raise EcoError("relay answered a web page, not JSON -- is the new "
                       "relay version deployed? (%s)" % " ".join(raw.split())[:120])
    if not out.get("ok"):
        raise EcoError("relay refused: %s" % (out.get("error") or "no reason"))
    return out


def enqueue(eco_key: str, name: str, photo: Path, *, mode: str,
            channel: str = "", thread_ts: str = "",
            replace: bool = False) -> str:
    """Queue one headshot for one office's computer. Returns the job id.

    `replace` is for run.py --redo only: the office computer uploads OVER a
    photo already on the profile instead of leaving it alone."""
    if not eco_key:
        raise EcoError("this office has no LucyEco key yet (config.OFFICES)")
    out = _call({"headshot_enqueue": {
        "office": eco_key, "name": name, "mode": mode,
        "png_b64": base64.b64encode(Path(photo).read_bytes()).decode("ascii"),
        "channel": channel, "thread_ts": thread_ts,
        "replace": bool(replace)}})
    return str(out.get("job_id") or "")


def results() -> List[Dict]:
    return list(_call({"headshot_results": True}).get("results") or [])


def mark_posted(job_ids: List[str]) -> int:
    if not job_ids:
        return 0
    return int(_call({"headshot_posted": list(job_ids)}).get("marked") or 0)


def queued_line(mode: str, replace: bool = False) -> str:
    """The OwnerVille line on the headshot post, before the office answers."""
    if mode == "live" and replace:
        return ("\nOwnerVille: sent to your office computer to REPLACE the "
                "photo on their profile — I'll reply here when it's done")
    if mode == "live":
        return ("\nOwnerVille: sent to your office computer to upload — "
                "I'll reply here when it's on their profile")
    return ""


def manual_line(replace: bool = False) -> str:
    """An office that is live before its computer is enrolled on LucyEco."""
    what = "replace their photo" if replace else "upload this one"
    return ("\nOwnerVille: please %s by hand for now — your office "
            "computer takes this over once it's set up on Lucy" % what)


def result_line(r: Dict) -> str:
    """One thread reply for one answer from an office computer."""
    name = r.get("name") or "this person"
    res = r.get("result") or {}
    st = res.get("status")
    as_who = (" (matched to *%s* in OwnerVille)" % res["matched_as"]
              if res.get("matched_as") else "")
    if st == "uploaded":
        ok = "" if res.get("verified") else " (check the Photo pill)"
        what = ("replaced the photo on their profile" if res.get("replaced")
                else "uploaded to their profile")
        return "*%s* — OwnerVille: %s ✅%s%s" % (name, what, ok, as_who)
    if st == "already_uploaded":
        return ("*%s* — OwnerVille: a photo is already on their profile — "
                "left as-is%s" % (name, as_who))
    if st == "dry_run_found":
        return ("*%s* — OwnerVille (test, nothing uploaded): found, Photo "
                "pill is %s%s" % (name, res.get("pill") or "?", as_who))
    if st == "not_found":
        return ("⚠ *%s* — OwnerVille: couldn't find them in View Progress "
                "(every campaign + Show All) — please upload this one by "
                "hand" % name)
    return ("⚠ *%s* — OwnerVille: the upload didn't go through on the office "
            "computer — please upload this one by hand" % name)


def post_results(cl, *, dry_run: bool = True, log=print) -> int:
    """Reply in each office's thread with its computer's answers. Answers
    with no thread (a --test-job) are left for `--results` to show."""
    try:
        got = results()
    except EcoError as e:
        log("  headshot results not read: %s" % e)
        return 0
    posted = []
    for r in got:
        if not (r.get("channel") and r.get("thread_ts")):
            continue
        line = result_line(r)
        if dry_run:
            log("  WOULD reply in %s: %s" % (r["channel"], line))
            continue
        try:
            cl.chat_postMessage(channel=r["channel"],
                                thread_ts=r["thread_ts"], text=line)
            posted.append(r["job_id"])
        except Exception as e:  # noqa: BLE001 -- retried next tick
            log("  could not reply for %s: %s" % (r.get("name"),
                                                 type(e).__name__))
    if posted:
        mark_posted(posted)
    return len(posted)


def main(argv: Optional[List[str]] = None) -> int:
    from automations.headshots import config
    ap = argparse.ArgumentParser(description="LucyEco headshot hand-over.")
    ap.add_argument("--test-job", action="store_true",
                    help="queue a READ-ONLY job for one office's computer")
    ap.add_argument("--office", help="office row in headshots config.OFFICES")
    ap.add_argument("--name", help='"First Last" of someone in their OwnerVille')
    ap.add_argument("--file", help="any headshot PNG (nothing is uploaded)")
    ap.add_argument("--results", action="store_true",
                    help="show what the office computers answered, and clear "
                         "the test answers")
    args = ap.parse_args(argv)

    if args.test_job:
        off = config.OFFICES.get((args.office or "").lower())
        if not off or off.uploader != "eco":
            ap.error("--office must be a LucyEco office in config.OFFICES")
        if not (args.name and args.file):
            ap.error("--test-job needs --name and --file")
        job = enqueue(off.eco_key, args.name, Path(args.file), mode="dry")
        print("queued read-only job %s for %s (%s). Their computer picks it up "
              "within ~10 min during office hours; then run --results."
              % (job, off.owner, off.eco_key))
        return 0

    if args.results:
        got = results()
        if not got:
            print("No answers waiting.")
            return 0
        tests = []
        for r in got:
            print("%-12s %-24s %s" % (r.get("office"), r.get("name"),
                                      json.dumps(r.get("result"))))
            if not r.get("thread_ts"):
                tests.append(r["job_id"])
        if tests:
            mark_posted(tests)
            print("(cleared %d test answer(s))" % len(tests))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
