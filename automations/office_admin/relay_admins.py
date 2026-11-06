"""Office admin logins for the BROWSER EXTENSION -- kept on the relay workbook.

The extension (extension/office-admin) signs admins in through the LucyEco
relay, so its logins live on the relay workbook's 'Office Admins' tab (the
Streamlit page's 'Office Admins' tab on the Org workbook is the fallback's).
The relay checks SHA-256(salt + password); the password itself is never
stored. Mode (dry | live) is set HERE, per admin -- never by the extension.

    python -m automations.office_admin.relay_admins --add raf-admin --office raf --name "Raf's admin"
    python -m automations.office_admin.relay_admins --add raf-admin --office omar   # 2nd office, same password
    python -m automations.office_admin.relay_admins --remove-office raf-admin omar
    python -m automations.office_admin.relay_admins --reset raf-admin
    python -m automations.office_admin.relay_admins --mode raf-admin live
    python -m automations.office_admin.relay_admins --disable raf-admin
    python -m automations.office_admin.relay_admins --list
    python -m automations.office_admin.relay_admins --accounts raf 11280 11901   # approve accounts
    python -m automations.office_admin.relay_admins --accounts raf               # show them

APPROVED ACCOUNTS ARE THE GUARD (Megan 2026-11-06): an office's admins can
only use the ApplicantStream accounts approved here ('Office Settings' tab,
'Approved Accounts'). A calendar from any other account sends nothing, so
another ICD's applicants can never go out on this office's Sterling.

ONE ADMIN, SEVERAL OFFICES (Megan 2026-11-04): one row per (admin, office).
--add for a username that already exists adds the office and keeps their
password. A brand-new username, or --reset, prints a generated password
ONCE in this terminal: hand it to the admin yourself. The admin can enter or
change each office's ApplicantStream account number (and city + state) in
the extension; the AppStream column here is only its starting value.
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from typing import Dict, List, Optional

TAB = "Office Admins"
HEAD = ["Username", "Office", "Salt", "Hash", "Active", "Mode", "Name", "Last Login", "AppStream"]


def make_hash(password: str, salt: Optional[str] = None) -> tuple:
    """(salt, hex) -- the same SHA-256(salt + password) the relay computes."""
    salt = salt or secrets.token_hex(8)
    return salt, hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


# SIMPLE ON PURPOSE (Megan 2026-11-06: "super simple"): office admins type it
# once per computer. A word + 4 digits ("lucy4827"); the relay locks a login
# out for 15 minutes after repeated misses, and --disable ends it at once.
_WORDS = ("lucy", "sunny", "tiger", "maple", "river", "rocket", "peach", "comet")


def new_password() -> str:
    return secrets.choice(_WORDS) + "".join(secrets.choice("23456789") for _ in range(4))


def _tab():
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        return ss.worksheet(TAB)
    except Exception:  # noqa: BLE001 -- first use
        ws = _retry(ss.add_worksheet, title=TAB, rows=100, cols=len(HEAD))
        _retry(ws.update, [HEAD], "A1")
        return ws


def _rows(ws) -> List[List[str]]:
    from automations.recruiting_report.fill import _retry
    return _retry(ws.get_all_values)


def _find(rows: List[List[str]], username: str) -> Optional[int]:
    u = username.strip().lower()
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0].strip().lower() == u:
            return i
    return None


SETTINGS_TAB = "Office Settings"
SET_HEAD = ["Office", "State", "City", "Updated By", "Updated At", "AppStream", "Approved Accounts"]


def _set_accounts(office: str, numbers: List[str]) -> int:
    """Approve the ApplicantStream accounts an office may send from (replaces
    the list). No numbers = just show the current list. Numbers taken off
    the list are also switched off for the office's admins."""
    import datetime as dt
    import re
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    office = office.strip().lower()
    nums: List[str] = []
    for n in re.findall(r"\d+", " ".join(numbers)):
        if n not in nums:
            nums.append(n)
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        ws = ss.worksheet(SETTINGS_TAB)
    except Exception:  # noqa: BLE001 -- first use
        ws = _retry(ss.add_worksheet, title=SETTINGS_TAB, rows=100, cols=len(SET_HEAD))
    rows = _retry(ws.get_all_values)
    if not rows or len(rows[0]) < len(SET_HEAD) or rows[0][6:7] != ["Approved Accounts"]:
        _retry(ws.update, [SET_HEAD], "A1")
        rows = _retry(ws.get_all_values)
    hit = next((i for i, r in enumerate(rows[1:], start=2) if r and r[0].strip().lower() == office), None)
    cur = rows[hit - 1] + [""] * 7 if hit else [""] * 7
    if not numbers:
        print("%s approved: %s" % (office, cur[6] or "(none)"))
        print("%s in use:   %s" % (office, cur[5] or "(none)"))
        return 0
    approved = ", ".join(nums)
    in_use = [n for n in re.findall(r"\d+", cur[5] or "") if n in nums]
    if hit:
        _retry(ws.update, [[", ".join(in_use) or approved, approved]], "F%d:G%d" % (hit, hit))
    else:
        _retry(ws.append_row, [office, "", "", "megan", dt.datetime.now().isoformat(timespec="seconds"),
                               approved, approved])
    print("%s approved: %s" % (office, approved))
    return 0


def main(argv=None) -> int:
    from automations.office_admin import config as C
    from automations.recruiting_report.fill import _retry
    ap = argparse.ArgumentParser(description="Office admin logins (browser extension).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--add", metavar="USERNAME")
    g.add_argument("--reset", metavar="USERNAME")
    g.add_argument("--disable", metavar="USERNAME")
    g.add_argument("--mode", nargs=2, metavar=("USERNAME", "dry|live"))
    g.add_argument("--remove-office", nargs=2, metavar=("USERNAME", "OFFICE"))
    g.add_argument("--list", action="store_true")
    g.add_argument("--accounts", nargs="+", metavar=("OFFICE", "NUMBER"))
    ap.add_argument("--office")
    ap.add_argument("--name", default="")
    ap.add_argument("--password", default="",
                    help="with --add/--reset: use this password instead of a made-up one")
    a = ap.parse_args(argv)
    if a.accounts:
        return _set_accounts(a.accounts[0], a.accounts[1:])
    ws = _tab()
    rows = _rows(ws)

    if a.list:
        for r in rows[1:]:
            r = r + [""] * (len(HEAD) - len(r))
            print("%-18s %-8s active=%-5s mode=%-4s %-24s last=%s" % (r[0], r[1], r[4], r[5], r[6], r[7] or "-"))
        return 0

    if a.add:
        u = a.add.strip().lower()
        o = C.office(a.office or "")
        if not o:
            print("--office must be one of: %s" % ", ".join(sorted(C.OFFICES)), file=sys.stderr)
            return 2
        mine = [r for r in rows[1:] if r and r[0].strip().lower() == u]
        if any(len(r) > 1 and r[1].strip().lower() == o.key for r in mine):
            print("%s already has office %s" % (u, o.key), file=sys.stderr)
            return 2
        if mine:   # existing admin, another office: same password
            first = mine[0] + [""] * (len(HEAD) - len(mine[0]))
            _retry(ws.append_row, [u, o.key, first[2], first[3], "TRUE", o.bgc_mode,
                                   a.name.strip() or first[6], "", o.appstream_id],
                   value_input_option="RAW")
            print("added office %s to %s (same password, mode %s)" % (o.key, u, o.bgc_mode))
            return 0
        pw = a.password.strip() or new_password()
        salt, h = make_hash(pw)
        _retry(ws.append_row, [u, o.key, salt, h, "TRUE", o.bgc_mode, a.name.strip(), "",
                               o.appstream_id],
               value_input_option="RAW")
        print("added %s (office %s, mode %s)\n\nPassword (shown once):\n\n    %s\n"
              % (u, o.key, o.bgc_mode, pw))
        return 0

    if a.remove_office:
        u, off = a.remove_office[0].strip().lower(), a.remove_office[1].strip().lower()
        hit = [i for i, r in enumerate(rows[1:], start=2)
               if r and r[0].strip().lower() == u and len(r) > 1 and r[1].strip().lower() == off]
        if not hit:
            print("%s has no office %s" % (u, off), file=sys.stderr)
            return 2
        _retry(ws.update, [["FALSE"]], "E%d" % hit[0])
        print("office %s turned off for %s" % (off, u))
        return 0

    target = (a.reset or a.disable or (a.mode[0] if a.mode else "")).strip().lower()
    mine = [i for i, r in enumerate(rows[1:], start=2) if r and r[0].strip().lower() == target]
    if not mine:
        print("no such username", file=sys.stderr)
        return 2
    if a.disable:
        for row in mine:
            _retry(ws.update, [["FALSE"]], "E%d" % row)
        print("disabled %s (all offices)" % target)
    elif a.mode:
        m = a.mode[1].strip().lower()
        if m not in ("dry", "live"):
            print("mode is dry or live", file=sys.stderr)
            return 2
        for row in mine:
            _retry(ws.update, [[m]], "F%d" % row)
        print("%s is now %s (all offices)" % (target, m))
    else:
        pw = a.password.strip() or new_password()
        salt, h = make_hash(pw)
        for row in mine:   # one password across every office row
            _retry(ws.update, [[salt, h, "TRUE"]], "C%d:E%d" % (row, row))
        print("password reset for %s\n\nPassword (shown once):\n\n    %s\n" % (target, pw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
