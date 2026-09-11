"""Hand this office's numbers to us. The laptop's only outbound call.

PLAIN HTTP TO A WEB APP, NOT THE SHEETS API, and that is the point. Writing to
the Sheet directly would mean a Google credential on every ICD laptop -- a
write key to our spreadsheets, on 52 machines we do not own, which is the exact
thing this whole design exists to avoid. Instead each office gets its OWN relay
key, it can do nothing but hand in that office's numbers, and revoking one is a
row on our side.

STDLIB ONLY (urllib). Every dependency is one more thing that can fail on a
Windows laptop during an install we cannot watch.

WHAT GOES OVER THE WIRE: the office key, the day, and {rep: credit checks so
far today}. No password, no session, no customer data, no addresses -- the
SaraPlus login stays on the laptop and never travels. That is worth keeping
true: it is what makes the answer to "what do you have of mine" short.

THE LAPTOP DOES NOT DECIDE WHAT IS NEW. It reports totals; we diff them and
choose what to post. So a laptop that loses its state file, gets restored from
a backup, or runs twice cannot announce anything twice -- the worst it can do
is tell us the same totals again, which changes nothing.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Dict, Optional

from automations.icd_alerts import config as C

TIMEOUT_SECONDS = 30
AGENT_VERSION = "icd_alerts/1"


class RelayError(RuntimeError):
    """Phrased for whoever is reading it on an ICD's laptop."""


def _endpoint() -> Dict[str, str]:
    rec = C.install()
    missing = [k for k in ("office_key", "relay_url", "relay_key") if not rec.get(k)]
    if missing:
        raise RelayError(
            "This computer is not set up to send yet (missing %s). Run the "
            "setup step you were given, or ask the reporting team to re-send "
            "your setup code." % ", ".join(missing))
    return rec


def payload(records: Dict[str, int], day: dt.date,
            rec: Optional[Dict] = None) -> Dict:
    rec = rec or _endpoint()
    return {
        "office_key": rec["office_key"],
        "key": rec["relay_key"],
        "day": day.isoformat(),
        "records": {str(k): int(v) for k, v in sorted(records.items())},
        "agent": AGENT_VERSION,
        # The laptop's own clock, so a machine that has been asleep is visible
        # as a stale reading rather than looking like a quiet office.
        "local_time": dt.datetime.now().isoformat(timespec="seconds"),
    }


def send(records: Dict[str, int], day: Optional[dt.date] = None, *,
         dry_run: bool = False, log=print) -> Dict:
    """POST one sweep's totals. Returns the decoded reply, or raises RelayError
    with something an owner can act on."""
    day = day or C.today()
    rec = _endpoint()
    body = payload(records, day, rec)

    if dry_run:
        log("dry run -- would send %d rep(s) for %s to %s"
            % (len(body["records"]), body["day"], rec["relay_url"]))
        return {"ok": True, "dry_run": True}

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        rec["relay_url"], data=data, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RelayError(
            "The reporting server refused the update (error %s). Your alerts "
            "may be switched off -- ask the reporting team." % e.code)
    except urllib.error.URLError as e:
        # The ordinary case: no wifi, asleep, captive portal at a hotel.
        raise RelayError(
            "Could not reach the reporting server (%s). This usually means no "
            "internet connection. Nothing is lost -- the next run sends "
            "today's totals again." % getattr(e, "reason", e))

    try:
        out = json.loads(raw)
    except ValueError:
        raise RelayError("The reporting server sent back something unexpected. "
                         "Nothing was lost; the next run will try again.")
    if not out.get("ok"):
        raise RelayError("The reporting server did not accept the update: %s"
                         % str(out.get("error") or "no reason given"))
    log("sent %d rep(s) for %s" % (len(body["records"]), body["day"]))
    return out
