"""Which AppStream account is this machine actually using, and what can it see?

Written because Lucy 2 reached only 22 of 28 offices while the laptop reached 28
with the SAME credentials file. "This Office is not assigned to you!" is an
account-level permission, so the machines were not acting as the same account —
and the likely reason is the SAVED SESSION: appstream_direct_session reuses
.appstream_storage_state.json when it is still live, so a session minted by a
different login keeps working and the configured username is never used.

  python -m automations.shared.appstream_whoami                 # as it runs today
  python -m automations.shared.appstream_whoami --force         # ignore the saved
                                                                # session, log in fresh
  python -m automations.shared.appstream_whoami --offices 22583,19717

--force is the interesting one: if the configured creds are rcaptain, a forced
login should turn the deniels into OKs. Compare the two runs.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

BASE = "https://applicantstream.com/index.cfm"
TOKRE = re.compile(r"rqst=([A-Za-z0-9\-]+)")
# The six Lucy 2 denied on 2026-08-20, plus two it reached, as a control.
DEFAULT_OFFICES = "22583,19717,23607,22177,23411,21328,11580,23318"


def identity(page) -> str:
    body = page.inner_text("body")[:400].replace("\n", " ")
    acct = re.search(r"Account No:\s*(\d+)", body)
    who = re.search(r"Account No:\s*\d+\s*\)?\s*\|?\s*([^|]{2,40}?)\s*\|", body)
    return "account_no=%s  label=%r" % (
        acct.group(1) if acct else "?",
        (who.group(1).strip() if who else body[:60]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="ignore the saved session and drive the login form")
    ap.add_argument("--offices", default=DEFAULT_OFFICES)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--accounts", action="store_true",
                    help="list which AppStream accounts this machine can use, "
                         "then exit (names only — never a password)")
    ap.add_argument("--alt", action="store_true",
                    help="use the stored ALTERNATE account "
                         "(set_appstream_alt_creds) instead of the primary")
    ap.add_argument("--user", help="log in as this account instead of the "
                                   "configured one (needs --pass)")
    ap.add_argument("--pass", dest="pw", help="password for --user")
    a = ap.parse_args(argv)

    from automations.shared import creds

    if a.alt:
        # Resolve the second login from where set_appstream_alt_creds stored
        # it, so a remote verify never has to put the password in a queue row.
        if not creds.has_appstream_alt():
            print("no alternate AppStream login on this machine — set one "
                  "with the mini-control action set_appstream_alt_creds")
            return 3
        a.user, a.pw = creds.appstream_alt_username(), creds.appstream_alt_password()
    from automations.shared.tableau_patchright import (
        appstream_direct_session, APPSTREAM_STORAGE_STATE)

    if a.accounts:
        # WHICH accounts are usable here, by name only. Two machines using
        # different logins is exactly how Lucy 2 ended up seeing 22 of 28
        # offices, so this has to be answerable without a browser.
        import json as _json, os as _os, subprocess as _sp
        root = pathlib.Path(creds.__file__).resolve().parents[2]
        f = root / "ownerville-creds.json"
        try:
            blob = _json.loads(f.read_text())
        except Exception:
            blob = {}
        print("creds file          : %s (%s)"
              % (f.name, "present" if f.exists() else "ABSENT"))
        print("  appstream_username: %s" % (blob.get("appstream_username") or "-none-"))
        print("  other keys        : %s"
              % ", ".join(sorted(k for k in blob if "password" not in k.lower())))
        print("env APPLICANTSTREAM_USERNAME: %s"
              % (_os.environ.get("APPLICANTSTREAM_USERNAME") or "-unset-"))
        alt_path = pathlib.Path.home() / ".config" / "recruiting-report" / "appstream-alt.json"
        try:
            alt_blob = _json.loads(alt_path.read_text())
        except Exception:
            alt_blob = {}
        print("ALT file            : %s (%s)"
              % (alt_path.name, "present" if alt_path.exists() else "ABSENT"))
        print("  alt username      : %s"
              % (alt_blob.get("appstream_alt_username") or "-none-"))
        print("  alt password      : %s"
              % ("set (%d chars)" % len(alt_blob.get("appstream_alt_password") or "")
                 if alt_blob.get("appstream_alt_password") else "-none-"))
        try:
            print("creds.has_appstream_alt(): %s" % creds.has_appstream_alt())
        except Exception as e:  # noqa: BLE001
            print("creds.has_appstream_alt(): error %s" % type(e).__name__)
        for svc in ("applicantstream-username", "applicantstream-username-rcaptain",
                    "applicantstream-username-alt"):
            r = _sp.run(["security", "find-generic-password", "-a", "applicantstream",
                         "-s", svc, "-w"], capture_output=True, text=True)
            print("keychain %-38s: %s"
                  % (svc, r.stdout.strip() if r.returncode == 0 else "-not found-"))
        # LAST line on purpose: the mini-control poller truncates a result to
        # ~450 chars and keeps the TAIL, so the answer has to be the final line
        # or it is exactly what gets cut off.
        print("SUMMARY primary=%s alt=%s has_alt=%s"
              % (blob.get("appstream_username") or "none",
                 alt_blob.get("appstream_alt_username") or "none",
                 creds.has_appstream_alt()))
        return 0

    if a.alt and not (a.user and a.pw):
        if not creds.has_appstream_alt():
            print("no ALTERNATE account configured on this machine "
                  "(set one with the set_appstream_alt_creds action)")
            return 5
        a.user, a.pw = creds.appstream_alt_username(), creds.appstream_alt_password()

    try:
        user = a.user or creds.appstream_username()
    except Exception as e:  # noqa: BLE001
        user = "<unreadable: %s>" % type(e).__name__
    print("configured username : %s" % user, flush=True)
    print("saved session file  : %s (%s)"
          % (APPSTREAM_STORAGE_STATE.name,
             "present" if APPSTREAM_STORAGE_STATE.exists() else "ABSENT"), flush=True)
    print("mode                : %s" % ("FORCED fresh login" if a.force
                                        else "reuse saved session if live"), flush=True)

    ids = [o.strip() for o in a.offices.split(",") if o.strip()]
    ok, denied, other = [], [], []
    kw = dict(headless=not a.headed, verbose=True, allow_form_login=True,
              force_form_login=a.force or bool(a.user))
    if a.user and a.pw:
        # Separate profile, same reason daily_focus --alt-appstream uses one:
        # a second account's cookies must not overwrite the primary's session.
        from automations.shared.tableau_patchright import APPSTREAM_PROFILE_DIR
        kw.update(username=a.user, password=a.pw,
                  profile_dir=APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_alt")
    with appstream_direct_session(**kw) as page:
        tok = (TOKRE.search(page.url) or TOKRE.search(page.content())).group(1)
        print("identity            : %s" % identity(page), flush=True)
        for oid in ids:
            page.goto("%s?p=104&rqst=%s&newOfficeId=%s" % (BASE, tok, oid), timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(900)
            body = page.inner_text("body")
            if "not assigned to you" in body.lower():
                denied.append(oid)
                mark = "DENIED"
            else:
                m = re.search(r"Office ID:\s*(\d+)\s*Owner:\s*([^|\n]+)", body)
                if m and m.group(1) == oid:
                    ok.append(oid)
                    mark = "OK   %s" % m.group(2).strip()[:26]
                else:
                    other.append(oid)
                    mark = "?    (did not land on %s)" % oid
            print("  %-7s %s" % (oid, mark), flush=True)

    print("\nreachable %d/%d  denied=%s%s"
          % (len(ok), len(ids), ",".join(denied) or "none",
             ("  unclear=" + ",".join(other)) if other else ""), flush=True)
    return 0 if not denied else 4


if __name__ == "__main__":
    sys.exit(main())
