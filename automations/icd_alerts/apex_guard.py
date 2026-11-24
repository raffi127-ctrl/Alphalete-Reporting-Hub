"""The lock on Lucy's Apex browser: she can READ payroll, never change it.

WHY (Eve + Megan, 2026-11-16). The owner PNL on Lucy Eco reads the owner's
Apex with the OWNER's login, and soon signs in by herself (password + auth-app
key on the owner's Mac). That login can do anything in Apex -- edit pay,
approve payroll. So the limit is Lucy's, and it lives in her browser, not in
how carefully the clicks are written: every request that could change
something is stopped before it leaves the Mac, unless it is on the short list
below.

What the read path needs was measured, not guessed (probe_apex_requests,
Lucy 2, 2026-11-16: Payroll Entry -> pay period -> Export). Every request was
a read except three:
    POST apexapi.herbjoyent.com/auth/token   -- keeps the session alive. NEEDED.
    POST apex.herbjoyent.com/cdn-cgi/rum     -- Cloudflare page stats. Blocked.
    POST o418336.ingest.sentry.io/...        -- Apex's error reports. Blocked.
The export itself is only reads.

One exception to "reads pass": Apex's account pages (NEVER_OPEN) change the
account when merely opened, so they are stopped even for a GET.

Two modes:
    "block" -- Lucy's own run (pnl.read_apex). Anything not allowed is
               stopped and written down.
    "watch" -- the sign-in window a PERSON uses (apex_signin). Nothing is
               stopped -- it is their hands -- but whatever "block" would have
               stopped is written down. That is how the sign-in / 2-step
               requests get learned on the owner's first sign-in, before Lucy
               ever signs in alone.

What is written down: METHOD host/path and a count. Never the query, never
the body -- no payroll in the file. It lives on this Mac (apex-guard.json),
and pnl puts the short list in its `probe-pnl-apex` line.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Dict, Tuple
from urllib.parse import urlsplit

from automations.icd_alerts import config as C

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# The ONLY non-read requests allowed: (host, exact path). Adding one means the
# test that pins this list has to change too -- on purpose.
ALLOWED_WRITES = frozenset({
    ("apexapi.herbjoyent.com", "/auth/token"),
    # Lucy's own sign-in (apex_login, 2026-11-17): the password form and the
    # 2-step code form. Apex is ASP.NET Identity (its account pages are
    # /Identity/Account/Manage/...), whose sign-in forms post here. A sign-in
    # cannot change payroll. CONFIRM against the "sign-in window sent" list
    # from the owner's setup (apex_2fa_setup runs in "watch").
    ("apex.herbjoyent.com", "/identity/account/login"),
    ("apex.herbjoyent.com", "/identity/account/loginwith2fa"),
    # CONFIRMED on Jairo's Mac 2026-11-24 11:11: after the password Apex shows
    # "Select Verification Method" and its Next posts to /Account/SendCode
    # (no /Identity) -- the lock stopped it. The code form that follows is
    # /Account/VerifyCode in this (ASP.NET) flow. Both just pick/enter the
    # sign-in code; neither can change payroll.
    ("apex.herbjoyent.com", "/account/sendcode"),
    ("apex.herbjoyent.com", "/account/verifycode"),
    ("apex.herbjoyent.com", "/identity/account/sendcode"),
    ("apex.herbjoyent.com", "/identity/account/verifycode"),
})

# Cloudflare's "are you human" check in front of Apex. It answers Cloudflare,
# not Apex -- it cannot touch payroll -- and without it the page never loads.
CLOUDFLARE_CHECK = (
    ("apex.herbjoyent.com", "/cdn-cgi/challenge-platform/"),
    ("apexapi.herbjoyent.com", "/cdn-cgi/challenge-platform/"),
    ("challenges.cloudflare.com", "/"),
)

# Apex's ACCOUNT pages change the account just by being OPENED (ASP.NET
# Identity): a plain GET of /Identity/Account/Manage/EnableAuthenticator wrote
# a new authenticator key onto Carlos's account (probe_apex_2fa, Lucy 2,
# 2026-11-17 -- not turned on, his sign-in unchanged). So "GET = read" is not
# true there, and these are stopped even for a GET. The payroll read never
# goes near them; the sign-in pages (/Identity/Account/Login...) are not here.
NEVER_OPEN = (
    ("herbjoyent.com", "/identity/account/manage"),
    ("herbjoyent.com", "/manage/"),
)

GUARD_FILE = C.APP_DIR / "apex-guard.json"
MODES = ("block", "watch")


def _path(p: str) -> str:
    """'//auth/token/' -> '/auth/token' (the app doubles its slashes)."""
    p = re.sub(r"/{2,}", "/", p or "/")
    return p.rstrip("/") or "/"


def key(method: str, url: str) -> Tuple[str, str, str]:
    """(METHOD, host, path) -- no query, no body."""
    u = urlsplit(url)
    return method.upper(), (u.hostname or "").lower(), _path(u.path)


def _never_open(host: str, path: str) -> bool:
    p = path.lower() + "/"
    return any((host == h or host.endswith("." + h)) and p.startswith(pre)
               for h, pre in NEVER_OPEN)


def allowed(method: str, url: str) -> bool:
    m, host, path = key(method, url)
    if _never_open(host, path):
        return False
    if m in READ_METHODS:
        return True
    if (host, path.lower()) in ALLOWED_WRITES:
        return True
    return any(host == h and (path + "/").startswith(pre)
               for h, pre in CLOUDFLARE_CHECK)


class Guard:
    """One browser's lock. `install(ctx)` BEFORE the first page.goto."""

    def __init__(self, mode: str = "block"):
        if mode not in MODES:
            raise ValueError("mode must be one of %s" % (MODES,))
        self.mode = mode
        self.stopped: Dict[str, int] = {}     # "POST host/path" -> count

    def handle(self, route) -> None:
        req = route.request
        if allowed(req.method, req.url):
            route.continue_()
            return
        m, host, path = key(req.method, req.url)
        k = "%s %s%s" % (m, host, path)
        self.stopped[k] = self.stopped.get(k, 0) + 1
        if self.mode == "watch":
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def save(self) -> None:
        """Add this run's list to apex-guard.json. Never raises."""
        if not self.stopped:
            return
        try:
            d = load()
            seen = d.setdefault(self.mode, {})
            for k, n in self.stopped.items():
                seen[k] = seen.get(k, 0) + n
            d["updated"] = dt.datetime.now().isoformat(timespec="seconds")
            GUARD_FILE.parent.mkdir(parents=True, exist_ok=True)
            GUARD_FILE.write_text(json.dumps(d, indent=1, sort_keys=True))
        except Exception:  # noqa: BLE001 -- the list is a note, not the lock
            pass


def install(ctx, mode: str = "block") -> Guard:
    """Route EVERY request of this browser through the lock. Raises if it
    cannot -- the caller must then not open Apex at all."""
    g = Guard(mode)
    ctx.route("**/*", g.handle)
    return g


def launch_args() -> dict:
    """Extra launch_persistent_context arguments for an Apex browser. Service
    workers fetch outside the page's routing, so they are turned off -- or
    they would be a door around the lock."""
    return {"service_workers": "block"}


def load() -> dict:
    try:
        return json.loads(GUARD_FILE.read_text())
    except (OSError, ValueError):
        return {}


_NOISE = ("/cdn-cgi/rum", "sentry.io", "/shim-tests/")


def _noise(k: str) -> bool:
    return any(n in k for n in _NOISE)


def summary(limit: int = 300) -> str:
    """'lock stopped: ...; sign-in window sent: ...' -- '' when nothing yet."""
    d, parts = load(), []
    for mode, label in (("block", "lock stopped"),
                        ("watch", "sign-in window sent")):
        seen = d.get(mode) or {}
        if seen:
            # Page noise (analytics, error reports, the browser self-test)
            # goes LAST: on 11/23 it filled the 300 characters and hid the
            # sign-in requests the list exists to show.
            parts.append("%s: %s" % (label, ", ".join(
                "%s x%d" % (k, n) for k, n in
                sorted(seen.items(), key=lambda kv: (_noise(kv[0]), kv[0])))[:limit]))
    return "; ".join(parts)
