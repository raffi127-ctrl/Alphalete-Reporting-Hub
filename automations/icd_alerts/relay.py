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
import urllib.parse
import urllib.request
from typing import Dict, Optional

from automations.icd_alerts import config as C

TIMEOUT_SECONDS = 30
AGENT_VERSION = "icd_alerts/1"
MAX_REDIRECTS = 5


class _NoAutoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects automatically, so `_post` can do it properly.

    urllib's default handler follows a 302 by issuing a GET -- which against an
    Apps Script web app lands on doGet and comes back "POST only", as though
    the relay had asked for the wrong thing. Worse, it does it INCONSISTENTLY:
    on 2026-09-11 the same four calls returned a mix of real answers, "POST
    only", and a 404 at the end of the redirect chain. A relay that works four
    times out of five is the worst possible kind of broken, because the
    failures read as an empty day.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
    body = {
        "office_key": rec["office_key"],
        "key": rec["relay_key"],
        "day": day.isoformat(),
        "records": {str(k): int(v) for k, v in sorted(records.items())},
        "agent": AGENT_VERSION,
        # The laptop's own clock, so a machine that has been asleep is visible
        # as a stale reading rather than looking like a quiet office.
        "local_time": dt.datetime.now().isoformat(timespec="seconds"),
    }
    # Where the owner ASKED for their alerts. Sent every sweep, not once, so
    # re-running the installer is how somebody changes their mind -- there is
    # no other route, and "run it again" is an instruction anyone can follow.
    # It is a request: nothing posts there until a human approves it.
    if rec.get("requested_channel"):
        body["requested_channel"] = rec["requested_channel"]
        body["owner"] = rec.get("owner", "")
    return body


def _is_result_url(url: str) -> bool:
    """True for the url Apps Script parks a finished response on."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host.endswith("googleusercontent.com")


def _post(url: str, data: bytes) -> str:
    """POST, then follow Apps Script's redirect to the result BY HAND.

    An Apps Script web app answers /exec with a 302 to
    script.googleusercontent.com, where the actual response body lives, and it
    is fetched with a GET. That part is by design. What is not survivable is
    letting urllib do it: it turns the POST into a GET against /exec itself and
    the relay silently reads doGet's reply instead of doPost's.
    """
    opener = urllib.request.build_opener(
        _NoAutoRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"})

    for _ in range(MAX_REDIRECTS):
        try:
            with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location") if e.headers else None
            if e.code not in (301, 302, 303, 307, 308) or not location:
                raise
            nxt = urllib.parse.urljoin(req.full_url, location)
            # WHICH METHOD depends on WHERE it is sending us, and getting this
            # wrong is silent. A hop to script.googleusercontent.com is Apps
            # Script handing back the RESULT of the POST it already ran: fetch
            # it with a GET, because re-POSTing would submit the relay twice.
            # A hop back to /exec itself has not run anything yet -- GET it and
            # doGet answers "POST only", which is what made this look flaky
            # rather than broken (2026-09-11, one call in six).
            if _is_result_url(nxt):
                req = urllib.request.Request(nxt, method="GET")
            else:
                req = urllib.request.Request(
                    nxt, data=data, method="POST",
                    headers={"Content-Type": "application/json"})
    raise RelayError(
        "The reporting server kept redirecting and never answered. Nothing is "
        "lost -- the next run sends today's totals again.")


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
    try:
        raw = _post(rec["relay_url"], data)
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
