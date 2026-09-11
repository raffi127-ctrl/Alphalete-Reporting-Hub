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
import ssl
import urllib.error
import urllib.request
from typing import Dict, Optional

from automations.icd_alerts import config as C

TIMEOUT_SECONDS = 30
AGENT_VERSION = "icd_alerts/1"


def _ssl_context() -> "ssl.SSLContext":
    """A context that can actually verify Google, on a machine we did not set up.

    A python.org Python on macOS ships with NO CA bundle until somebody runs
    `Install Certificates.command`, and nobody runs it. Every HTTPS call then
    dies with CERTIFICATE_VERIFY_FAILED -- which reads like the relay is
    broken, or like the office has no internet, and is neither. Caught on
    Megan's own Mac on 2026-09-11 the first time this endpoint was called.

    certifi rides along with patchright, so it is already on any machine that
    can drive the browser at all; the system store is the fallback for Windows,
    where it works. Verification is never turned off -- an ICD laptop posting
    over an unverified connection is not a trade worth making for a fix that
    exists.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 -- no certifi: the system store may be fine
        return ssl.create_default_context()


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
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS,
                                    context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except ssl.SSLCertVerificationError:
        raise RelayError(
            "This computer cannot verify a secure connection, so it cannot "
            "send. On a Mac this is fixed by opening Applications > Python "
            "3.x and double-clicking 'Install Certificates.command'. Nothing "
            "is lost -- the next run sends today's totals again.")
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
        # A web page instead of JSON means the relay is mis-deployed on OUR
        # side -- the wrong url, or a deployment made before the script was
        # saved (which answers "Script function not found"). Say so plainly:
        # it is not the office's fault and not something they can fix.
        snippet = " ".join(raw.split())[:120]
        raise RelayError(
            "The reporting server sent back a web page instead of a reply, "
            "which means it is not set up correctly on our end -- please tell "
            "the reporting team. Nothing is lost. (It said: %s)" % snippet)
    if not out.get("ok"):
        raise RelayError("The reporting server did not accept the update: %s"
                         % str(out.get("error") or "no reason given"))
    log("sent %d rep(s) for %s" % (len(body["records"]), body["day"]))
    return out
