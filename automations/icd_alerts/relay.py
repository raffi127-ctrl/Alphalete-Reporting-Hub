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
import platform
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

from automations.icd_alerts import config as C

TIMEOUT_SECONDS = 30
AGENT_VERSION = "icd_alerts/3"          # 2 = sales, 3 = names its machine
# THE VERSION IS HOW WE SEE WHO HAS UPDATED, from the relay row, without
# asking anybody. Kash sat on /1 for a day with no sales and it was only
# visible because somebody went looking at the right column.
SALE_METRICS = ("Int", "Int Up", "DTV", "NL")
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


def _endpoint(office_key: str = "") -> Dict[str, str]:
    """This machine's relay record -- for ONE campaign when named.

    A machine can now hold several enrollments, one per campaign, each with
    its own relay key. Naming none keeps the old behaviour (the first), which
    is what every single-campaign office is.
    """
    rec = C.enrollment_for(office_key) if office_key else C.install()
    missing = [k for k in ("office_key", "relay_url", "relay_key") if not rec.get(k)]
    if missing:
        raise RelayError(
            "This computer is not set up to send yet (missing %s). Run the "
            "setup step you were given, or ask the reporting team to re-send "
            "your setup code." % ", ".join(missing))
    return rec



# --- which computer this is --------------------------------------------------
# An office can install on two machines -- a back-office PC as a backup is a
# reasonable thing to do -- and until now the relay could not tell them apart.
# Both wrote the same office+day row, last writer winning, so a SECOND machine
# was invisible: if one died the office kept relaying, looked alive, and
# nobody was told that half its redundancy was gone (Megan 2026-09-13).
#
# The id is random and per INSTALL, not derived from anything about the
# computer. It only has to be stable and distinct; a hostname or a MAC address
# would be needlessly identifying for something whose entire job is "not the
# other one".
MACHINE_ID_PATH = C.APP_DIR / "machine-id.txt"


def machine_id() -> str:
    """This install's id, made once and kept. Never raises: a relay that could
    not name its machine is still worth far more than one that did not go."""
    try:
        existing = MACHINE_ID_PATH.read_text().strip()
        if existing:
            return existing[:36]
    except OSError:
        pass
    try:
        import uuid
        made = uuid.uuid4().hex[:12]
        MACHINE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        MACHINE_ID_PATH.write_text(made)
        return made
    except Exception:  # noqa: BLE001 — read-only disk, odd permissions
        return ""


def is_desktop() -> bool:
    """True when this machine has NO battery -- so it is a desktop.

    THE ONE IMPLEMENTATION. The installer refuses a laptop using this same
    function rather than its own copy: two battery checks that could disagree
    is exactly how a rule ends up enforced at install and not in the reports,
    or the other way round.

    A battery and not hw.model, because Apple Silicon reports generic strings
    like "Mac14,7" for laptops AND desktops -- matching model names would
    refuse a brand-new iMac and accept a brand-new MacBook.

    Unknown counts as a desktop, matching the installer: refusing an office
    because a probe did not answer is worse than letting a laptop through.
    """
    import platform as _p
    if _p.system() == "Windows":
        return True                      # judged by its own rules over there

    # ASK THE MACHINE WHAT IT IS, FIRST. The battery probe can only answer by
    # ABSENCE, so anything that makes it look like a battery is present turns
    # a desktop away -- which is what happened to Carlos's Mac mini on
    # 2026-09-15, with the install refusing him at the very first step.
    # `system_profiler` prints a name a person would recognise ("Mac mini",
    # "MacBook Pro"), so a positive identification beats an inference.
    name = _model_name()
    if name:
        low = name.lower()
        if low.startswith("macbook"):
            return False                 # laptop, definitively
        for desktop in ("mac mini", "imac", "mac studio", "mac pro"):
            if desktop in low:
                return True              # desktop, definitively

    # Unrecognised model (a Hackintosh, a VM, something newer than this code):
    # fall back to the battery, which still catches the common case.
    try:
        import subprocess
        out = subprocess.run(["ioreg", "-rc", "AppleSmartBattery"],
                             capture_output=True, timeout=20)
        return b"AppleSmartBattery" not in (out.stdout or b"")
    except Exception:  # noqa: BLE001 — no ioreg, odd sandbox, slow disk
        return True


def _never_sleeps() -> Optional[bool]:
    """True/False, or None from an agent that cannot answer yet.

    None is not False. Every office installed before this existed would
    otherwise report as "sleeps", which is the same mistake the laptop check
    made: an office that was never asked must not look like an office that
    answered badly.
    """
    try:
        from automations.icd_alerts import stay_awake
        return bool(stay_awake.status().get("never_sleeps"))
    except Exception:  # noqa: BLE001 — older agent, odd machine, slow probe
        return None


def _model_name() -> str:
    """"Mac mini", "MacBook Pro", "iMac" -- or "" if it cannot be read.

    NOT hw.model: Apple Silicon reports "Mac14,7" style identifiers for
    laptops AND desktops, so matching those would refuse a new iMac and
    accept a new MacBook. SPHardwareDataType carries the name Apple puts on
    the box.
    """
    try:
        import re
        import subprocess
        out = subprocess.run(["system_profiler", "SPHardwareDataType"],
                             capture_output=True, timeout=30)
        text = (out.stdout or b"").decode("utf-8", "replace")
        m = re.search(r"Model Name:\s*(.+)", text)
        return m.group(1).strip() if m else ""
    except Exception:  # noqa: BLE001
        return ""


def machine_label() -> str:
    """Something a person can recognise in a list. The computer's own name is
    what an owner would use to tell two of their machines apart, and it is not
    a secret -- it is already on their wifi."""
    try:
        import socket
        return socket.gethostname().split(".")[0][:40]
    except Exception:  # noqa: BLE001
        return ""


def payload(records: Dict[str, int], day: dt.date,
            rec: Optional[Dict] = None, sales: Optional[Dict] = None) -> Dict:
    rec = rec or _endpoint()
    body = {
        "office_key": rec["office_key"],
        "key": rec["relay_key"],
        "day": day.isoformat(),
        "records": {str(k): int(v) for k, v in sorted(records.items())},
        # {REP: {Int, Int Up, DTV, NL}} -- the same four numbers the AO board
        # keeps. Sent as the totals so far today, like the credit checks: what
        # is NEW is worked out on our side, where the last-posted state lives.
        "sales": {str(k): {m: int(v.get(m, 0) or 0) for m in SALE_METRICS}
                  for k, v in sorted((sales or {}).items())},
        "agent": AGENT_VERSION,
        # WHICH computer this came from. An older relay ignores the key, so an
        # office that has not updated simply stays as one unnamed machine.
        "machine": machine_id(),
        "machine_name": machine_label(),
        # Desktop or laptop. An office on a laptop is not refused after the
        # fact -- the installer already turns those away -- but the ones
        # installed BEFORE that rule existed are otherwise invisible, and a
        # laptop is the single most likely reason a channel goes quiet.
        "desktop": is_desktop(),
        # CAN THIS MACHINE STILL GO TO SLEEP? Asked of the machine on every
        # relay, not remembered from install day: a declined password, an MDM
        # profile that puts the sleep timer back, or somebody turning it off
        # in System Settings all look identical from here otherwise. False is
        # the single best predictor of a channel about to go quiet.
        "never_sleeps": _never_sleeps(),
        # Mac or Windows, answered by the machine rather than by an owner
        # ticking a box about their own office. Windows has never been
        # exercised for real, so the first office that is actually on one is
        # something we want to know WITHOUT having asked.
        "os": platform.system() or "",
        # The laptop's own clock, so a machine that has been asleep is visible
        # as a stale reading rather than looking like a quiet office.
        "local_time": dt.datetime.now().isoformat(timespec="seconds"),
    }
    # Where the owner ASKED for their alerts. Sent every sweep, not once, so
    # re-running the installer is how somebody changes their mind -- there is
    # no other route, and "run it again" is an instruction anyone can follow.
    # It is a request: nothing posts there until a human approves it.
    # A LIST. An office can want the pings in the owners' room and the rep
    # channel both; asking for one and making them come back for the second is
    # a worse conversation than asking once. An empty list is a real answer --
    # "I am not sure, ask me" -- and differs from never having been asked.
    if rec.get("requested_channels") is not None:
        body["requested_channels"] = rec["requested_channels"]
    # What they asked for on the knocks report. Same rule: a request, decided
    # by a person, and re-sent every sweep so re-running the installer is how
    # an owner changes their mind.
    # A LIST of destinations, each with its own cadence -- the owners' room
    # every 15 minutes and the rep channel once an hour is a normal answer, and
    # one shared cadence cannot express it. Each carries the LABEL for whoever
    # reads the sheet and the MINUTES for the code that builds a schedule;
    # sending only the sentence would mean parsing english on our side to
    # recover a number the installer already had. An empty list is a real
    # answer -- "no knocks board" -- and is different from never being asked.
    if rec.get("requested_knocks_destinations") is not None:
        body["requested_knocks_destinations"] = rec["requested_knocks_destinations"]
        body["requested_knocks_hours_note"] = rec.get("requested_knocks_hours_note", "")
    if any(k in body for k in ("requested_channels", "requested_knocks_destinations")):
        body["owner"] = rec.get("owner", "")
        # How OwnerVille spells them, in their own words. OwnerVille disagrees
        # with every other list we keep -- Kash Rai is "Akashdeep Rai" there --
        # and the only person who can settle it is the one looking at it.
        if rec.get("ov_name"):
            body["ov_name"] = rec["ov_name"]
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


# A Google Sheets cell holds 50,000 characters. A day of dispositions is far
# short of that -- 30 reps by 15 columns is a few KB -- but "far short" is not
# "guaranteed", and a silently truncated cell would read as a half-empty board.
MAX_KNOCKS_CHARS = 45_000


def send_knocks(rows, day: Optional[dt.date] = None, *, time_tracker=None,
                dry_run: bool = False, office_key: str = "",
                log=print) -> Dict:
    """Hand over one day of disposition rows, raw.

    Separate call, separate failure. A SaraPlus sweep that works must not be
    lost because OwnerVille was slow, and a knocks read that works must not be
    thrown away because a credit-check pass failed -- they are different
    sources with different outages.
    """
    day = day or C.today()
    rec = _endpoint(office_key)
    body = {
        "office_key": rec["office_key"],
        "key": rec["relay_key"],
        "day": day.isoformat(),
        "knocks_rows": rows,
        "knocks_time_tracker": time_tracker or [],
        "agent": AGENT_VERSION,
        "local_time": dt.datetime.now().isoformat(timespec="seconds"),
    }

    payload_json = json.dumps(body)
    if len(json.dumps(rows)) > MAX_KNOCKS_CHARS:
        raise RelayError(
            "Today's knocks are too large to send in one go (%d reps). Please "
            "tell the reporting team -- this needs splitting on our end."
            % len(rows))

    if dry_run:
        log("dry run -- would send %d knock row(s) for %s" % (len(rows), body["day"]))
        return {"ok": True, "dry_run": True}

    raw = _post(rec["relay_url"], payload_json.encode("utf-8"))
    try:
        out = json.loads(raw)
    except ValueError:
        snippet = " ".join(raw.split())[:120]
        raise RelayError(
            "The reporting server sent back a web page instead of a reply, "
            "which means it is not set up correctly on our end -- please tell "
            "the reporting team. Nothing is lost. (It said: %s)" % snippet)
    if not out.get("ok"):
        raise RelayError("The reporting server did not accept the knocks: %s"
                         % str(out.get("error") or "no reason given"))
    log("sent %d knock row(s) for %s" % (len(rows), body["day"]))
    return out


# --- telling us what broke, without a Zoom ---------------------------------
# An office that stops relaying shows up as SILENCE. We learn THAT it stopped
# from the quiet nudge, and nothing at all about WHY -- which on 2026-09-12
# meant working out Cyrus's outage by elimination while he sat on a call.
# Multiply that by office #12 and the rollout stops scaling.
#
# So the laptop reports its own faults up the same one-way pipe it already
# uses. Same key, same endpoint, same guarantee about what travels.

# Anything matching these is stripped before a fault leaves the machine. A
# crash message is the one place a password reliably turns up as plain text --
# patchright prints the arguments it was called with -- and a diagnostic that
# leaks the thing this whole design protects would be a bad trade.
_SECRET_KEYS = ("password", "passwd", "pwd", "secret", "token", "key")


def _scrub(text: str, rec: Optional[Dict] = None) -> str:
    """Remove this office's own secrets from a message before sending it."""
    out = str(text or "")
    try:
        cr = C.creds()
    except Exception:  # noqa: BLE001 — no creds saved yet is normal at install
        cr = {}
    secrets = [str(cr.get(k) or "") for k in ("password", "passwd")]
    secrets.append(str((rec or {}).get("relay_key") or ""))
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "[removed]")
    # The email is not a secret, but it is the account name and there is no
    # diagnostic value in it -- we already know whose office this is.
    email = str(cr.get("email") or "")
    if email and len(email) >= 4:
        out = out.replace(email, "[their login]")
    # ANY email address, not just theirs. A traceback can carry a customer's,
    # and "no customer data leaves the laptop" is a promise worth keeping
    # literally rather than approximately.
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", out)
    # A belt-and-braces pass for anything that LOOKS like a credential in a
    # repr we did not anticipate: key=value where the key smells secret.
    for k in _SECRET_KEYS:
        out = re.sub(r"(?i)\b%s\b(\s*[=:]\s*)(\S+)" % re.escape(k),
                     r"%s\1[removed]" % k, out)
    return out[:1500]


def report_fault(stage: str, summary: str, detail: str = "",
                 day: Optional[dt.date] = None, log=None) -> bool:
    """Tell us something broke here. BEST EFFORT, and NEVER raises.

    This runs inside exception handlers and at the end of a failed install.
    A reporter that can itself throw would turn a diagnosable failure into a
    crash with no message at all -- so every path here swallows, including a
    missing config, an unreachable network and a malformed reply.

    `stage` is the coarse where: "install", "sweep", "knocks", "login".
    `summary` is one line we can read in a channel. `detail` is the traceback
    or command output, trimmed and scrubbed.

    Returns True only if the relay accepted it -- callers may use that to
    decide whether to also tell the person sitting there, but must not depend
    on it.
    """
    try:
        rec = _endpoint()
    except Exception:  # noqa: BLE001 — not enrolled yet; nothing to report to
        return False
    try:
        body = {
            "office_key": rec["office_key"],
            "key": rec["relay_key"],
            # THE DAY RIDES INSIDE THE FAULT, DELIBERATELY. A relay that has
            # not been redeployed yet does not know what a fault is, and would
            # fall through to its records branch and upsert an EMPTY {} over
            # this office's real day. Without a top-level `day` that older
            # script fails its own format check and does nothing at all, which
            # is exactly the right outcome: a fault report must never be able
            # to damage the numbers.
            "fault": {
                "day": (day or C.today()).isoformat(),
                "stage": str(stage or "")[:40],
                "summary": _scrub(summary, rec)[:300],
                "detail": _scrub(detail, rec),
                "agent": AGENT_VERSION,
                "platform": "%s %s" % (platform.system(), platform.release()),
                "python": platform.python_version(),
            },
            "local_time": dt.datetime.now().isoformat(timespec="seconds"),
        }
        raw = _post(rec["relay_url"], json.dumps(body).encode("utf-8"))
        return bool(json.loads(raw).get("ok"))
    except Exception as e:  # noqa: BLE001 — see docstring
        if log:
            log("could not report the fault upstream: %s" % type(e).__name__)
        return False


def send(records: Dict[str, int], day: Optional[dt.date] = None, *,
         sales: Optional[Dict] = None, dry_run: bool = False,
         office_key: str = "", log=print) -> Dict:
    """POST one sweep's totals. Returns the decoded reply, or raises RelayError
    with something an owner can act on."""
    day = day or C.today()
    rec = _endpoint(office_key)
    body = payload(records, day, rec, sales=sales)

    if dry_run:
        log("dry run -- would send %d rep(s) with credit checks and %d with "
            "sales for %s" % (len(body["records"]), len(body["sales"]),
                              body["day"]))
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
    log("sent %d rep(s) with credit checks, %d with sales, for %s"
        % (len(body["records"]), len(body["sales"]), body["day"]))
    return out
