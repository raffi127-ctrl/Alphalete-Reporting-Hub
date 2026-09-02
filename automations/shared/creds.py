"""Local credential loader — keeps the ownerville login OUT of source.

The repo was public with the ownerville password hardcoded (Megan 2026-05-25,
chose not to rotate). This reads the login from a GITIGNORED file at the repo
root (or env vars) instead, so the password never lives in the code — public or
private. NOTHING is hardcoded here: if the login isn't found, it raises a clear
error telling you to create the file.

  ownerville-creds.json  (repo root, gitignored, NEVER commit):
    {
      "ownerville_username": "rhidalgo",
      "ownerville_password": "..."
    }
  or env vars: OWNERVILLE_USERNAME / OWNERVILLE_PASSWORD

Each machine that runs login-based reports needs this file — distributed
out-of-band (not through the repo). Upload-only reports (Financial, Frontier,
First/Last Sale) don't touch it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

_CREDS_PATH = Path(__file__).resolve().parents[2] / "ownerville-creds.json"


@lru_cache(maxsize=1)
def _file() -> dict:
    try:
        return json.loads(_CREDS_PATH.read_text())
    except Exception:
        return {}


def reload() -> None:
    """Forget the cached credential files — call this after WRITING one from
    inside a long-lived process.

    `_file()` is read once per process, which is right for a report run and
    wrong for the mini's poller: it reads the file at startup and then lives for
    days. So an installer that writes a credential and immediately verifies it
    was checking the cached copy, not what it had just written. On 2026-08-27
    `set_doubleentry_creds` wrote the missing Double Entry login onto Lucy 1 and
    then reported "SIGN-IN FAILED: Missing Double Entry credential" — the
    credential was on disk the whole time. Wrong twice over: the row goes red on
    a good install, and a genuinely bad password would look identical."""
    _file.cache_clear()
    _alt_file.cache_clear()
    _accounts_file.cache_clear()


def _resolve(key: str, env: str) -> str:
    val = str(_file().get(key) or os.environ.get(env, "")).strip()
    if not val:
        raise RuntimeError(
            f"Missing credential {key!r}. Create '{_CREDS_PATH.name}' at the repo "
            f"root containing {{\"ownerville_username\": ..., \"ownerville_password\": "
            f"...}} (ask Megan for the login), or set the {env} environment "
            "variable. That file is gitignored — never commit it."
        )
    return val


def ownerville_username() -> str:
    return _resolve("ownerville_username", "OWNERVILLE_USERNAME")


def ownerville_password() -> str:
    return _resolve("ownerville_password", "OWNERVILLE_PASSWORD")


# --- AppStream (ApplicantStream) recruiting login ----------------------------
# ONLY TWO APPSTREAM ACCOUNTS EXIST (Megan 2026-09-02): "Lucy Reports" — every
# report on every Lucy — and "Lucy Resume Pushing" — the resume pusher, and
# nothing else. `rcaptain` is RETIRED; so is the old CarlosNLR 'alt' slot. If you
# are reading a comment somewhere that names another account, the comment is
# stale, not the code.
#
# Source order: gitignored creds file → env → macOS keychain (where it already
# lives via `security add-generic-password -a applicantstream -s applicantstream-
# <field>`). Never hardcoded — the repo was public.
def _keychain(service: str) -> str:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-a", "applicantstream",
             "-s", service, "-w"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _resolve_as(key: str, env: str, keychain_service: str) -> str:
    val = (str(_file().get(key) or "").strip()
           or os.environ.get(env, "").strip()
           or _keychain(keychain_service))
    if not val:
        raise RuntimeError(
            f"Missing AppStream credential {key!r}. Add it to "
            f"'{_CREDS_PATH.name}', set {env}, or store it in the keychain: "
            f"security add-generic-password -a applicantstream -s "
            f"{keychain_service} -w. Never commit it."
        )
    return val


# THE USERNAME HAS A SPACE IN IT. "Lucy Reports", not "LucyReports".
#
# WHY THIS IS CODE AND NOT A NOTE (Megan 2026-09-02): the creds file held
# `LucyReports` and nothing failed loudly. The form filled it, cleared
# Cloudflare, submitted — and the console still RENDERED, off the CFID/CFTOKEN
# pair re-injected on the `?rqst=…&p=701` hop. It carried no token. Every layer
# above read that as success: autorenew reported the token "renewed" and blamed
# a cold profile, and the whole 4am batch (daily_focus, applicant_sync_morning,
# recruiter_retention_daily) died on it. It cost a morning of wrong diagnoses
# before anyone looked at the username. With the space it minted 2h on the first
# try.
#
# A typo that silent must not be able to reach the form again, so the spelling
# is repaired here, at the one place every caller goes through, and the repair
# is printed — a silent fix is how the drift comes back.
_CANONICAL_APPSTREAM_USERNAMES = ("Lucy Reports", "Lucy Resume Pushing")

# WRONG SPELLINGS THAT ARE NOT JUST BAD SPACING. Squash-matching catches
# `LucyReports` -> `Lucy Reports`, but it cannot catch a name that is also
# TRUNCATED. `LucyResume` squashes to "lucyresume", which is not "lucyresume
# pushing", so it sails straight through.
#
# It was sitting in appstream-accounts.json on Lucy 2 the whole time. Megan
# confirmed the real login on 2026-09-02 by screenshot: `Lucy Resume Pushing`.
# Same silent failure as the reporting account — the form submits, the console
# renders off CFID/CFTOKEN, no token is minted, and every layer above calls it a
# success — except this one pushes resumes, and send-to-AI is irreversible.
#
# Add to this map only a spelling somebody has CONFIRMED against the real login
# screen. Guessing here installs a wrong username on purpose.
_APPSTREAM_USERNAME_ALIASES = {
    "lucyresume": "Lucy Resume Pushing",
}


def canonical_appstream_username(value: str) -> str:
    """Repair a known AppStream username whose spelling has been mangled.

    Matching ignores case and every space/underscore/hyphen, so `LucyReports`,
    `lucy_reports` and `LUCY  REPORTS` all resolve to `Lucy Reports`. Truncated
    forms are handled by _APPSTREAM_USERNAME_ALIASES above, since squashing
    alone cannot see that `LucyResume` is missing a word. A username that
    matches nothing we know is returned untouched — this corrects spellings we
    are certain of, it does not invent accounts."""
    raw = str(value or "").strip()
    if not raw:
        return raw
    squashed = re.sub(r"[\s_-]+", "", raw).lower()
    for canon in list(_CANONICAL_APPSTREAM_USERNAMES) + [
            _APPSTREAM_USERNAME_ALIASES.get(squashed)]:
        if not canon:
            continue
        if (squashed == re.sub(r"[\s_-]+", "", canon).lower()
                or _APPSTREAM_USERNAME_ALIASES.get(squashed) == canon):
            if raw != canon:
                print("[creds] AppStream username %r is misspelled — using %r "
                      "(the space matters: a wrong username reaches a console "
                      "that renders with NO token). Fix it at the source with "
                      "`lucy set_appstream_username`." % (raw, canon),
                      file=sys.stderr, flush=True)
            return canon
    return raw


def appstream_username() -> str:
    return canonical_appstream_username(
        _resolve_as("appstream_username", "APPLICANTSTREAM_USERNAME",
                    "applicantstream-username"))


def appstream_password() -> str:
    return _resolve_as("appstream_password", "APPLICANTSTREAM_PASSWORD",
                       "applicantstream-password")


# --- Double Entry (doubleentry.com) financial login ---------------------------
# The weekly financials used to arrive as emailed .xlsx workbooks; they now come
# off the Double Entry org summary report, which needs a login. Same rule as
# every other credential here: it lives in the gitignored creds file or an env
# var, NEVER in the code. Add to 'ownerville-creds.json' at the repo root:
#   {"doubleentry_username": "...@gmail.com", "doubleentry_password": "..."}
# or set DOUBLEENTRY_USERNAME / DOUBLEENTRY_PASSWORD.
def _resolve_de(key: str, env: str) -> str:
    val = str(_file().get(key) or os.environ.get(env, "")).strip()
    if not val:
        raise RuntimeError(
            f"Missing Double Entry credential {key!r}. Add it to "
            f"'{_CREDS_PATH.name}' at the repo root "
            f"({{\"doubleentry_username\": ..., \"doubleentry_password\": ...}}) "
            f"or set the {env} environment variable. That file is gitignored — "
            "never commit it."
        )
    return val


def doubleentry_username() -> str:
    return _resolve_de("doubleentry_username", "DOUBLEENTRY_USERNAME")


def doubleentry_password() -> str:
    return _resolve_de("doubleentry_password", "DOUBLEENTRY_PASSWORD")


# --- RETIRED: the alternate AppStream account -------------------------------
# THIS SLOT IS CLOSED (Megan 2026-09-02: "We should NOT be using any other app
# stream logins anymore other than the Lucy Reports & Lucy Resume Pushing ones —
# Rcaptain is RETIRED").
#
# It existed because Lucy 2 signed in as CarlosNLR, which could not see six of
# the 28 offices, while rcaptain could — so a job picked whichever account it
# needed. Both of those accounts are gone. Every report now signs in as
# 'Lucy Reports'; the resume pusher signs in as 'Lucy Resume Pushing'. There is
# no third answer, and a slot that can hold one is a way for a report to end up
# quietly running as somebody else — the 2026-08-20 failure where Lucy 2's
# "rcaptain" verify actually ran as Carlos Hidalgo.
#
# The readers stay so an old install carrying appstream-alt.json degrades to
# "no alternate" instead of crashing, but nothing may SELECT it: `has_appstream_
# alt()` is hard-False and appstream_account('alt') raises.
_ALT_PATH = Path.home() / ".config" / "recruiting-report" / "appstream-alt.json"


@lru_cache(maxsize=1)
def _alt_file() -> dict:
    # Outside the repo on purpose: the repo is public, and this is a live login.
    try:
        return json.loads(_ALT_PATH.read_text())
    except Exception:
        return {}


def appstream_alt_username() -> str:
    return (str(_alt_file().get("appstream_alt_username") or "").strip()
            or _resolve_as("appstream_alt_username", "APPLICANTSTREAM_ALT_USERNAME",
                           "applicantstream-alt-username"))


def appstream_alt_password() -> str:
    return (str(_alt_file().get("appstream_alt_password") or "").strip()
            or _resolve_as("appstream_alt_password", "APPLICANTSTREAM_ALT_PASSWORD",
                           "applicantstream-alt-password"))


def has_appstream_alt() -> bool:
    """Always False — the alternate account is retired (see above).

    Hard-coded rather than deleted: several callers ask this before offering an
    'alt' path, and the answer they need now is no. A machine with a leftover
    appstream-alt.json must not light that path back up."""
    return False


def appstream_alt_installed() -> bool:
    """Is a retired appstream-alt.json still sitting on this machine?

    Not used to SELECT the account — only so the login preflight can say
    'there is a stale credential file here, delete it'."""
    return bool(str(_alt_file().get("appstream_alt_username") or "").strip())


# --- Named AppStream accounts ------------------------------------------------
# WHY A NAMED MAP (Megan 2026-08-31). primary+alt is two slots, and Lucy 2 needs
# three kinds of access at once: a broad account for funnel_board /
# indeed_source_report / ad_sales_board / daily_update_fill, whatever is already
# in the alt slot, and now LucyResume — an account deliberately scoped to the two
# offices Applicant Push is allowed to touch.
#
# The scoping is the POINT. On 2026-08-30 the push sent to ~22 offices instead of
# 2: it bounds itself with an office SWITCH, but the v2 batch grid's select-all →
# Send To AI reaches what the ACCOUNT can see, and the shared 'Raf – Captain'
# login sees all 28. Send-to-AI is irreversible. An account that cannot see
# office 3 cannot push office 3 — that is a guarantee a UI control isn't.
#
# Lives OUTSIDE the repo (the repo is public) beside appstream-alt.json:
#   ~/.config/recruiting-report/appstream-accounts.json
#     {"lucyresume": {"username": "Lucy Resume Pushing", "password": "..."}}
#
# SPELL THE USERNAME THE WAY THE ACCOUNT IS SPELLED, spaces included — see
# canonical_appstream_username() above for what a mangled one costs.
#
# 'primary' and 'alt' resolve to the existing slots, so a caller can name any
# account without caring which storage mechanism holds it.
_ACCOUNTS_PATH = (Path.home() / ".config" / "recruiting-report"
                  / "appstream-accounts.json")


@lru_cache(maxsize=1)
def _accounts_file() -> dict:
    try:
        blob = json.loads(_ACCOUNTS_PATH.read_text())
    except Exception:  # noqa: BLE001 — absent is normal on most machines
        return {}
    return blob if isinstance(blob, dict) else {}


# THE ONLY TWO ACCOUNTS THERE ARE. 'primary' is the reporting login
# ("Lucy Reports"); 'lucyresume' is the resume pusher ("Lucy Resume Pushing").
# Anything else — 'alt', 'rcaptain', a name someone adds to the accounts file —
# is refused by appstream_account() rather than used.
ALLOWED_APPSTREAM_ACCOUNTS = ("primary", "lucyresume")


def appstream_accounts() -> list:
    """Every account name usable on this machine. NAMES ONLY — never a password.

    'primary' is always present. 'lucyresume' appears once the scoped resume
    login is installed. Nothing else is listed, even if the accounts file holds
    it: a name that appears here reads as a name a report may ask for, and there
    are exactly two (Megan 2026-09-02)."""
    names = ["primary"]
    if "lucyresume" in _accounts_file():
        names.append("lucyresume")
    return names


def unexpected_appstream_accounts() -> list:
    """Retired account names still installed on this machine, if any.

    Reported by the login preflight so a leftover 'alt'/rcaptain credential gets
    deleted rather than sitting there waiting to be selected by an old call
    site."""
    extra = sorted(k for k in _accounts_file()
                   if k not in ALLOWED_APPSTREAM_ACCOUNTS)
    if appstream_alt_installed():
        extra.append("alt (appstream-alt.json)")
    return extra


def appstream_account(name: str) -> tuple:
    """(username, password) for a named AppStream account.

    Resolution: the named map → the primary/alt slots. Raises with the list of
    names this machine actually has, because the failure we care about is a
    report asking for a scoped account on a box where nobody installed it — and
    the wrong answer there is falling back to a broader account and pushing to
    offices the report was never allowed to touch. Never fall back. Fail."""
    key = (name or "primary").strip().lower()
    # REFUSE A RETIRED ACCOUNT OUTRIGHT. Only 'Lucy Reports' (primary) and
    # 'Lucy Resume Pushing' (lucyresume) exist (Megan 2026-09-02). A caller still
    # asking for 'alt' or 'rcaptain' is running on a stale assumption, and the
    # dangerous version of that is a job signing in as an account with wider
    # office access than it is allowed to push — the 8/30 over-push exactly. Fail
    # where the name is chosen, not somewhere downstream.
    if key not in ALLOWED_APPSTREAM_ACCOUNTS:
        raise RuntimeError(
            "AppStream account %r is RETIRED. There are exactly two logins: "
            "'primary' (Lucy Reports — every report) and 'lucyresume' "
            "(Lucy Resume Pushing — the resume pusher only). Point this caller "
            "at one of those; do not re-install %r." % (key, key))
    entry = _accounts_file().get(key)
    if isinstance(entry, dict):
        user = canonical_appstream_username(entry.get("username") or "")
        pw = str(entry.get("password") or "")
        if user and pw:
            return user, pw
        raise RuntimeError(
            "AppStream account %r in %s is missing a username or password."
            % (key, _ACCOUNTS_PATH.name))
    if key == "primary":
        return appstream_username(), appstream_password()
    raise RuntimeError(
        "No AppStream account named %r on this machine. Configured: %s. Install "
        "it with the mini-control action set_appstream_account, and do NOT fall "
        "back to another account — a broader login can push offices this job is "
        "not allowed to touch." % (key, ", ".join(appstream_accounts())))


def appstream_account_fingerprint(name: str):
    """The AppStream 'Account No:' this named account is KNOWN to log in as, or
    None if nobody has recorded it yet."""
    entry = _accounts_file().get((name or "primary").strip().lower())
    if isinstance(entry, dict):
        val = str(entry.get("account_no") or "").strip()
        return val or None
    return None


def record_appstream_account_fingerprint(name: str, account_no: str) -> bool:
    """Remember which AppStream account number a named login lands on.

    WHY (Megan 2026-08-31): scoping LucyResume to two offices bounds what the
    push CAN reach, but only while the push is actually signed in as it. Carlos's
    worry is a different failure — the run attaching to a Chrome that another
    report already has open, which carries the BROAD login's cookies. The scoped
    credential is never used there, so the permission bound never applies.

    So the run also asserts identity on the page before it sends. That needs
    something to compare against, and the account number is the only stable thing
    the console shows. It gets recorded on a --dry-run (which sends nothing) and
    asserted on a live run — which matches the rule that a dry-run always
    precedes a live one."""
    key = (name or "primary").strip().lower()
    num = str(account_no or "").strip()
    if not num:
        return False
    blob = {}
    try:
        blob = json.loads(_ACCOUNTS_PATH.read_text())
    except Exception:  # noqa: BLE001 — absent/unreadable starts clean
        blob = {}
    if not isinstance(blob, dict):
        blob = {}
    entry = blob.get(key)
    if not isinstance(entry, dict):
        # Only ever ANNOTATE an account that already exists. Creating one here
        # would invent a credential-less entry that appstream_account() then
        # rejects, which reads like a corrupt install.
        return False
    if str(entry.get("account_no") or "").strip() == num:
        return True
    entry["account_no"] = num
    blob[key] = entry
    _ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ACCOUNTS_PATH.write_text(json.dumps(blob, indent=2))
    try:
        os.chmod(_ACCOUNTS_PATH, 0o600)
    except Exception:  # noqa: BLE001
        pass
    _accounts_file.cache_clear()
    return True
