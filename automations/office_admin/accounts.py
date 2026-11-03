"""Office admin logins: one username + password per admin, one office each.

The 'Office Admins' tab stores a salted PBKDF2 hash, never the password.

    # add an admin (asks for the password twice, or --generate makes one and
    # prints it ONCE in this terminal -- hand it to the admin yourself):
    python -m automations.office_admin.accounts --add omar-admin --office omar --name "Omar's admin" --generate

    # reset a password / turn a login off:
    python -m automations.office_admin.accounts --reset omar-admin --generate
    python -m automations.office_admin.accounts --disable omar-admin

    python -m automations.office_admin.accounts --list
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sys
from typing import Dict, List, Optional

from automations.office_admin import config as C
from automations.office_admin import sheets as S

_ITER = 200_000
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
MIN_PASSWORD = 8


def hash_password(pw: str, *, salt: Optional[bytes] = None, iterations: int = _ITER) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, base64.b64encode(salt).decode(),
                                      base64.b64encode(dk).decode())


def check_password(pw: str, stored: str) -> bool:
    try:
        algo, it, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                                 base64.b64decode(salt), int(it))
        return hmac.compare_digest(base64.b64encode(dk).decode(), want)
    except (ValueError, TypeError):
        return False


def norm_username(u: str) -> str:
    return (u or "").strip().lower()


def find(admins: List[Dict[str, str]], username: str) -> Optional[Dict[str, str]]:
    u = norm_username(username)
    for a in admins:
        if norm_username(a.get("Username")) == u:
            return a
    return None


def is_active(a: Dict[str, str]) -> bool:
    return (a.get("Active") or "").strip().lower() in ("yes", "y", "true", "on")


def authenticate(admins: List[Dict[str, str]], username: str, pw: str) -> Optional[Dict[str, str]]:
    """The admin row when username + password match an ACTIVE login whose
    office is set up; else None. Same answer for every kind of miss, so the
    page never tells a stranger which usernames exist."""
    a = find(admins, username)
    if not a or not is_active(a) or not C.office(a.get("Office Key", "")):
        # Burn the same time as a real check either way.
        check_password(pw or "", hash_password("x", iterations=_ITER))
        return None
    return a if check_password(pw or "", a.get("Password Hash", "")) else None


def _new_password() -> str:
    # Readable: no 0/O/1/l. 12 chars.
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _ask_password(generate: bool) -> str:
    if generate:
        pw = _new_password()
        print("\nPassword (shown once -- give it to the admin, it is not stored):\n\n    %s\n" % pw)
        return pw
    while True:
        pw = getpass.getpass("New password: ")
        if len(pw) < MIN_PASSWORD:
            print("At least %d characters." % MIN_PASSWORD)
            continue
        if pw != getpass.getpass("Again: "):
            print("Did not match.")
            continue
        return pw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Office admin logins.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--add", metavar="USERNAME")
    g.add_argument("--reset", metavar="USERNAME")
    g.add_argument("--disable", metavar="USERNAME")
    g.add_argument("--list", action="store_true")
    ap.add_argument("--office", help="office key, e.g. omar (with --add)")
    ap.add_argument("--name", default="", help="admin's name (with --add)")
    ap.add_argument("--generate", action="store_true", help="make the password for me")
    args = ap.parse_args(argv)

    ws = S.admins_tab()
    admins = S.read_admins(ws)

    if args.list:
        for a in admins:
            print("%-20s %-10s %-24s active=%s last login=%s" % (
                a.get("Username"), a.get("Office Key"), a.get("Admin Name"),
                a.get("Active"), a.get("Last Login") or "-"))
        return 0

    if args.add:
        u = norm_username(args.add)
        if not USERNAME_RE.match(u):
            print("username: 3-40 chars, lowercase letters/numbers/. _ -", file=sys.stderr)
            return 2
        if find(admins, u):
            print("%s already exists -- use --reset" % u, file=sys.stderr)
            return 2
        if not C.office(args.office or ""):
            print("--office must be one of: %s (add the office to office_admin/config.OFFICES first)"
                  % ", ".join(sorted(C.OFFICES)), file=sys.stderr)
            return 2
        pw = _ask_password(args.generate)
        S.append_admin(ws, {"Username": u, "Password Hash": hash_password(pw),
                            "Office Key": args.office.strip().lower(),
                            "Admin Name": args.name.strip(), "Active": "Yes",
                            "Created": S.now_str()})
        print("added %s for office %s" % (u, args.office))
        return 0

    a = find(admins, args.reset or args.disable)
    if not a:
        print("no such username", file=sys.stderr)
        return 2
    if args.disable:
        S.set_admin_cells(ws, a["_row"], {"Active": "No"})
        print("disabled %s" % a["Username"])
        return 0
    pw = _ask_password(args.generate)
    S.set_admin_cells(ws, a["_row"], {"Password Hash": hash_password(pw), "Active": "Yes"})
    print("password reset for %s" % a["Username"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
