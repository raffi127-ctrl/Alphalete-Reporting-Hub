"""Upload this office's new-start headshots into its own OwnerVille.

WHY ON THE OFFICE'S COMPUTER (Megan 2026-10-26, rolling Raf's headshot bot out
to every ICD). An ICD's OwnerVille login sees only that ICD's reps, so the
upload has to happen with THEIR login -- and their login lives here, not on a
Lucy. Lucy 3 does everything else: posts the Monday thread in the office's
channel, reads the replies, makes the white-background headshot, and replies
in the thread with how the upload went.

THE HAND-OVER is the relay, both ways, so this computer still talks to nothing
but the relay and still holds no Slack token and no Google credential:

    Lucy 3   -> relay   "headshot for <name>, office X"    (admin key)
    here     -> relay   "any headshots for me?"            (this office's key)
             <- relay   the photo(s), only this office's
    here     -> relay   "uploaded" / "not found" / ...     (this office's key)
    Lucy 3   <- relay   the answer -> reply in the thread

THE SAME UPLOADER AS RAF'S. automations/headshots/ov_upload.upload_on_page is
shipped as-is, so a fix to the click-path reaches every office on the next
self-update. It NEVER overwrites a photo already on a profile.

NEVER SIGNS IN FOR THIS. A headshot is not worth a browser window popping up on
somebody's screen. If the OwnerVille session has lapsed the job goes back in
the queue ("deferred") and the next knocks sweep -- which already knows how to
sign in -- brings the session back.

A JOB'S MODE IS SET ON OUR SIDE (automations/headshots/config.OFFICES):
"dry" finds the person and reads their Photo pill, changes nothing; "live"
uploads. There is no switch on this computer.

    python -m automations.icd_alerts.headshot_jobs        # one check, now
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_alerts import config as C

# How often a machine asks. Headshots are not urgent -- the thread already has
# the finished photo -- and every ask is a call on the shared relay.
ASK_EVERY_MINUTES = 10
# Office hours for asking: nobody submits headshots overnight, and a 3am
# browser on someone's computer is the kind of thing that gets Lucy uninstalled.
HOURS = (8, 21)

_STATE = C.APP_DIR / "headshot-jobs.json"


def _load() -> Dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: Dict) -> None:
    try:
        C.app_dir()
        _STATE.write_text(json.dumps(s), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- only costs an extra ask
        pass


def due(now: Optional[dt.datetime] = None, state: Optional[Dict] = None) -> bool:
    now = now or dt.datetime.now()
    if not (HOURS[0] <= now.hour < HOURS[1]):
        return False
    last = (state if state is not None else _load()).get("last_ask", 0)
    return (time.time() - float(last or 0)) >= ASK_EVERY_MINUTES * 60


def _call(rec: Dict, extra: Dict) -> Dict:
    from automations.icd_alerts import relay as R
    body = {"office_key": rec["office_key"], "key": rec["relay_key"]}
    body.update(extra)
    raw = R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
    out = json.loads(raw)
    if not isinstance(out, dict):
        raise ValueError("relay answered %r" % (raw[:80],))
    return out


def fetch_jobs(rec: Dict) -> List[Dict]:
    out = _call(rec, {"headshot_jobs": True})
    # An older relay has no idea what this is and answers 'bad day' -- that
    # is "no headshots here", not a fault.
    if not out.get("ok"):
        return []
    return list(out.get("jobs") or [])


def send_result(rec: Dict, job_id: str, res: Dict) -> bool:
    payload = dict(res)
    payload["job_id"] = job_id
    try:
        return bool(_call(rec, {"headshot_result": payload}).get("ok"))
    except Exception:  # noqa: BLE001 -- offered again after 30 min
        return False


def _work(jobs: List[Dict], campaign_id: str = "", log=print) -> List[Dict]:
    """Run each job on ONE OwnerVille browser. Returns [{job_id, result}].

    PUTS THE CAMPAIGN BACK. Finding a person walks View Progress's campaign
    dropdown, and OwnerVille's campaign is sticky across the whole login --
    so the session is pinned back to this office's own campaign afterwards,
    the same pin the knocks read uses, and a board can never read the
    campaign a headshot search happened to end on."""
    from patchright.sync_api import sync_playwright

    from automations.headshots import ov_upload
    from automations.icd_alerts import ov_read
    from automations.shared import ownerville_knocks as K

    done: List[Dict] = []
    try:
        C.ownerville_creds()
    except Exception:  # noqa: BLE001
        msg = "this computer has no OwnerVille login saved"
        return [{"job_id": j["job_id"],
                 "result": {"status": "error", "error": msg}} for j in jobs]

    with tempfile.TemporaryDirectory(prefix="lucy-headshots-") as tmp, \
            sync_playwright() as p:
        try:
            ctx = ov_read._context(p, True)
        except Exception as e:  # noqa: BLE001 -- profile busy: knocks running
            log("headshots: OwnerVille browser busy (%s) -- next time"
                % type(e).__name__)
            return [{"job_id": j["job_id"], "result": {"status": "deferred"}}
                    for j in jobs]
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            rqst = K.capture_rqst(page)
            if not rqst:
                log("headshots: OwnerVille not signed in right now -- next time")
                return [{"job_id": j["job_id"],
                         "result": {"status": "deferred"}} for j in jobs]
            for j in jobs:
                name = str(j.get("name") or "").strip()
                live = j.get("mode") == "live"
                try:
                    photo = Path(tmp) / ("%s - Headshot.png" % j["job_id"])
                    photo.write_bytes(base64.b64decode(j.get("png_b64") or ""))
                    # REPLACE only when Lucy 3 says so (a person asked for
                    # a redo by name) -- otherwise a photo on file is kept.
                    res = ov_upload.upload_on_page(
                        page, name, photo, dry_run=not live, verbose=True,
                        rqst=rqst, replace=bool(j.get("replace")) and live)
                    log("headshots: %s -> %s" % (name, res.get("status")))
                except Exception as e:  # noqa: BLE001 -- one person, not all
                    res = {"status": "error",
                           "error": "%s: %s" % (type(e).__name__, str(e)[:160])}
                    log("headshots: %s failed (%s)" % (name, type(e).__name__))
                res["mode"] = "live" if live else "dry"
                done.append({"job_id": j["job_id"], "result": res})
            if campaign_id:
                K.pin_campaign(page, rqst, campaign_id, log=log)
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    return done


def run_once(log=print) -> int:
    """Ask for this computer's headshots, upload them, report back. Returns
    how many jobs were answered."""
    answered = 0
    for rec in C.active_enrollments():
        if not rec.get("relay_url") or not rec.get("relay_key"):
            continue
        try:
            jobs = fetch_jobs(rec)
        except Exception as e:  # noqa: BLE001 -- offline; ask next time
            log("headshots: could not ask the relay (%s)" % type(e).__name__)
            continue
        if not jobs:
            continue
        log("headshots: %d to do for %s" % (len(jobs), rec["office_key"]))
        cid = C.CAMPAIGN_IDS.get(
            str(rec.get("campaign") or "att").strip().lower(), "")
        for d in _work(jobs, campaign_id=cid, log=log):
            if send_result(rec, d["job_id"], d["result"]):
                answered += 1
    return answered


def maybe_run(log=print) -> bool:
    """Called from every agent tick. Cheap when nothing is due: a small JSON
    read and a clock check."""
    if os.environ.get("LUCY_NO_HEADSHOTS"):
        return False
    state = _load()
    if not due(state=state):
        return False
    state["last_ask"] = time.time()
    _save(state)
    run_once(log=log)
    return True


def main(argv=None) -> int:
    n = run_once()
    print("answered %d headshot job(s)" % n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
