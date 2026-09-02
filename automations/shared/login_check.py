#!/usr/bin/env python3
"""Are BOTH logins live on THIS machine? Ownerville and AppStream, separately.

WHY THIS EXISTS (Megan 2026-09-02): "Ownerville and App stream ARE NOT the same
login and should not be considered fixed if only one of them works."

That is not a hypothetical. The two are genuinely independent systems and we
have repeatedly proved one and declared the other fixed:

  * AppStream on Lucy 1 cannot be minted from its ownerville session at all —
    Lucy 1's ownerville identity is offered ~90 program codes and p=701 (the
    recruiting console) is not among them. A 56h-healthy ownerville sat beside a
    dead AppStream for a whole morning.
  * The reverse is just as easy: `appstream_whoami` comes back green while the
    ownerville token has hours to live and dies mid-batch.

So this reports TWO verdicts and never collapses them. The exit code is the AND
of both, and a failure line always names WHICH system failed. Checking one and
saying "logins are fixed" is the specific mistake it is here to make impossible.

WHAT IT CHECKS
  Ownerville  — the stored session carries a live rqst SSO token, with enough
                life left to clear the next 4am batch.
  AppStream   — the stored session carries a live rqst token AND, with --deep,
                the console's own 'Account No:' is read back so the machine can
                say WHO it is signed in as rather than merely that it is signed
                in. A wrong username reaches a console that renders with no
                token, so "a console appeared" is not evidence of anything.
  Accounts    — the configured AppStream username is one of the two accounts
                that exist (Lucy Reports / Lucy Resume Pushing), spelled with
                its space, and no retired credential (rcaptain, the CarlosNLR
                'alt' slot) is still installed.

This machine only. Nothing here reads or repairs another Lucy: one machine must
never depend on another (Megan 2026-09-02), so each runs its own check.

    PYTHONPATH=. .venv/bin/python -m automations.shared.login_check
    PYTHONPATH=. .venv/bin/python -m automations.shared.login_check --deep
    PYTHONPATH=. .venv/bin/python -m automations.shared.login_check --json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

# A token with less than this left will not survive the 4am batch, so it counts
# as dead NOW rather than dying halfway through the reports. Same threshold the
# pre-batch self-heal uses, deliberately — two probes that disagree about what
# "healthy" means is how a green check precedes a red batch.
MIN_MINUTES_FOR_BATCH = 90.0


def _machine() -> str:
    """This machine's name, and whether it actually claims one.

    `session_holder._this_machine()` returns "Lucy 1" when the .machine-profile
    marker is missing — a silent default, so an unmarked box (Megan's laptop, a
    freshly imaged Lucy) reports itself as Lucy 1 and every line below reads as a
    statement about Lucy 1. A check whose header may be a lie is worse than no
    header, so say when the name is a fallback rather than a marker."""
    try:
        from automations.shared import session_holder as sh
        name = sh._this_machine() or "<unplaced>"
        try:
            marked = bool(sh._MACHINE_MARKER.read_text().strip())
        except Exception:  # noqa: BLE001
            marked = False
        return name if marked else "%s (ASSUMED — no .machine-profile marker)" % name
    except Exception:  # noqa: BLE001 — a label must never fail the check
        return "<unknown>"


def _is_appstream_runner() -> bool:
    """Does this machine run AppStream reports at all?

    A box with neither a credential nor a stored session has simply never been
    an AppStream runner — Megan's laptop is the standing example, and its
    rcaptain keychain pair was deliberately deleted on 2026-09-02. Reporting
    that as a FAILED login makes the check cry wolf on a machine that is
    correctly configured, and a check that is red by design gets ignored on the
    morning it is red for real."""
    from automations.shared import creds
    try:
        # THE CREDENTIAL IS THE DEFINITION, not the presence of a session file.
        # A leftover .appstream_storage_state.json from a retired account proves
        # only that this box once ran AppStream; with no credential it can never
        # log in again, so calling it a broken runner is wrong twice over. (Both
        # are true of Megan's laptop today: the rcaptain keychain pair was
        # deleted on 2026-09-02, and a dead state file was left behind.)
        return bool(creds.appstream_username())
    except Exception:  # noqa: BLE001 — no credential is the answer, not an error
        return False


def check_ownerville() -> dict:
    """Verdict for the ownerville/Tableau session. Never consults AppStream."""
    from automations.shared.appstream_watch import session_status
    from automations.shared.tableau_patchright import OWNERVILLE_STORAGE_STATE
    s = session_status(OWNERVILLE_STORAGE_STATE, "Ownerville")
    mins = (s["hours_left"] or 0) * 60 if s["hours_left"] is not None else 0.0
    ok = bool(s["ok"]) and mins >= MIN_MINUTES_FOR_BATCH
    detail = s["reason"]
    if s["ok"] and not ok:
        detail += (" — under the %.0f min the 4am batch needs, so it counts as "
                   "dead now rather than dying mid-run" % MIN_MINUTES_FOR_BATCH)
    return {"system": "Ownerville", "ok": ok, "detail": detail,
            "minutes_left": round(mins), "login_page": "https://ownerville.com/"}


def check_appstream(deep: bool = False) -> dict:
    """Verdict for the AppStream session. Never consults ownerville.

    The stored-token check is cheap and runs always. --deep additionally opens
    the console and reads its 'Account No:' back, which is the only way to catch
    the failure that matters most here: a console that renders while carrying no
    token, because the username was misspelled."""
    from automations.shared.appstream_watch import session_status
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    s = session_status(APPSTREAM_STORAGE_STATE, "AppStream")
    mins = (s["hours_left"] or 0) * 60 if s["hours_left"] is not None else 0.0
    # JUDGED IN THE PRESENT TENSE, unlike ownerville. The AppStream rqst TTL is
    # ~2h, so it can never cover the next 4am; asking it to is a question with
    # only one answer, and a probe that always says no is a probe nobody reads.
    # The 3:15am self-heal is what makes it live at 4am.
    out = {"system": "AppStream", "ok": bool(s["ok"]), "detail": s["reason"],
           "minutes_left": round(mins), "account_no": None, "label": None}
    if not deep:
        return out
    try:
        from automations.shared.tableau_patchright import appstream_direct_session
        from automations.shared.appstream_whoami import identity
        with appstream_direct_session(headless=False, verbose=False) as page:
            who = identity(page)
        out["label"] = who
        for part in who.split():
            if part.startswith("account_no="):
                out["account_no"] = part.split("=", 1)[1]
        # A console with no #searchMC never gets this far; a console WITH one but
        # no token is exactly the 2026-09-02 failure, and the token half is the
        # stored-session check above. Both have to hold.
        out["ok"] = bool(s["ok"]) and out["account_no"] not in (None, "?")
        out["detail"] = "%s · console says %s" % (s["reason"], who)
    except Exception as e:  # noqa: BLE001 — a failed deep probe IS the answer
        out["ok"] = False
        out["detail"] = "%s · deep probe failed: %s: %s" % (
            s["reason"], type(e).__name__, str(e).splitlines()[0][:160])
    return out


def check_accounts() -> dict:
    """Is this machine configured for the two accounts that exist, and only them?"""
    from automations.shared import creds
    problems, notes = [], []
    try:
        user = creds.appstream_username()
        notes.append("AppStream username: %r" % user)
        if user not in creds._CANONICAL_APPSTREAM_USERNAMES:
            problems.append(
                "AppStream username %r is not one of the two accounts that "
                "exist (%s). rcaptain and the CarlosNLR 'alt' login are RETIRED."
                % (user, " / ".join(creds._CANONICAL_APPSTREAM_USERNAMES)))
    except Exception as e:  # noqa: BLE001
        problems.append("no AppStream username configured: %s" % str(e).splitlines()[0][:140])
    try:
        notes.append("accounts installed: %s" % ", ".join(creds.appstream_accounts()))
    except Exception:  # noqa: BLE001
        pass
    try:
        stale = creds.unexpected_appstream_accounts()
        if stale:
            problems.append(
                "retired AppStream credential(s) still installed: %s — delete "
                "them; nothing may sign in as anything but Lucy Reports or "
                "Lucy Resume Pushing." % ", ".join(stale))
    except Exception:  # noqa: BLE001
        pass
    try:
        creds.ownerville_username()
        notes.append("ownerville credential: present")
    except Exception as e:  # noqa: BLE001
        problems.append("no ownerville credential on this machine: %s"
                        % str(e).splitlines()[0][:140])
    return {"system": "Accounts", "ok": not problems,
            "detail": "; ".join(problems) if problems else " · ".join(notes)}


def run(deep: bool = False) -> dict:
    if not _is_appstream_runner():
        return {"machine": _machine(),
                "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ok": True,
                "results": [{"system": "AppStream", "ok": True,
                             "detail": "not an AppStream runner (no credential, "
                                       "no stored session) — nothing to check "
                                       "here. Correct for a machine that is not "
                                       "one of the three Lucys."},
                            check_ownerville()]}
    results = [check_ownerville(), check_appstream(deep=deep), check_accounts()]
    return {"machine": _machine(),
            "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": all(r["ok"] for r in results),
            "results": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deep", action="store_true",
                    help="also open the AppStream console and read back which "
                         "account it is actually signed in as (slower; opens a "
                         "browser)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    res = run(deep=a.deep)
    if a.json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    print("=" * 66)
    print("  LOGIN CHECK — %s   %s" % (res["machine"], res["at"]))
    print("  Ownerville and AppStream are SEPARATE logins. Both must pass.")
    print("=" * 66)
    for r in res["results"]:
        print("  %s %s" % ("PASS" if r["ok"] else "FAIL", r["system"]))
        print("       %s" % r["detail"])
    print("-" * 66)
    if res["ok"]:
        print("  BOTH logins are live on this machine.")
        return 0
    bad = [r["system"] for r in res["results"] if not r["ok"]]
    print("  NOT FIXED: %s" % ", ".join(bad))
    # Name the remedy per system — they do not share one, which is the whole
    # point of checking them apart.
    if "Ownerville" in bad:
        print("   Ownerville → log in at https://ownerville.com/ (NOT "
              "v2.ownerville.com) — it self-heals unattended:")
        print("     PYTHONPATH=. .venv/bin/python -c \"from automations.shared."
              "appstream_autorenew import refresh_ownerville; "
              "print(refresh_ownerville())\"")
    if "AppStream" in bad:
        print("   AppStream → its own login, NOT reachable from ownerville on "
              "every machine:")
        print("     PYTHONPATH=. .venv/bin/python -m "
              "automations.shared.tableau_patchright --appstream-login")
    if "Accounts" in bad:
        print("   Accounts → fix the credential, then re-run this check.")
    print("  Fix them HERE. No machine is donated a session by another one.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
