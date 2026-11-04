"""Office admin logins for the BROWSER EXTENSION -- kept on the relay workbook.

The extension (extension/office-admin) signs admins in through the LucyEco
relay, so its logins live on the relay workbook's 'Office Admins' tab (the
Streamlit page's 'Office Admins' tab on the Org workbook is the fallback's).
The relay checks SHA-256(salt + password); the password itself is never
stored. Mode (dry | live) is set HERE, per admin -- never by the extension.

    python -m automations.office_admin.relay_admins --add raf-admin --office raf --name "Raf's admin"
    python -m automations.office_admin.relay_admins --reset raf-admin
    python -m automations.office_admin.relay_admins --mode raf-admin live
    python -m automations.office_admin.relay_admins --disable raf-admin
    python -m automations.office_admin.relay_admins --list

--add/--reset print a generated password ONCE in this terminal: hand it to
the admin yourself.
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


def new_password() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(14))


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


def main(argv=None) -> int:
    from automations.office_admin import config as C
    from automations.recruiting_report.fill import _retry
    ap = argparse.ArgumentParser(description="Office admin logins (browser extension).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--add", metavar="USERNAME")
    g.add_argument("--reset", metavar="USERNAME")
    g.add_argument("--disable", metavar="USERNAME")
    g.add_argument("--mode", nargs=2, metavar=("USERNAME", "dry|live"))
    g.add_argument("--list", action="store_true")
    ap.add_argument("--office")
    ap.add_argument("--name", default="")
    a = ap.parse_args(argv)
    ws = _tab()
    rows = _rows(ws)

    if a.list:
        for r in rows[1:]:
            r = r + [""] * (len(HEAD) - len(r))
            print("%-18s %-8s active=%-5s mode=%-4s %-24s last=%s" % (r[0], r[1], r[4], r[5], r[6], r[7] or "-"))
        return 0

    if a.add:
        u = a.add.strip().lower()
        if _find(rows, u):
            print("%s exists -- use --reset" % u, file=sys.stderr)
            return 2
        if not C.office(a.office or ""):
            print("--office must be one of: %s" % ", ".join(sorted(C.OFFICES)), file=sys.stderr)
            return 2
        pw = new_password()
        salt, h = make_hash(pw)
        o = C.office(a.office)
        _retry(ws.append_row, [u, o.key, salt, h, "TRUE", o.bgc_mode, a.name.strip(), "",
                               o.appstream_id],
               value_input_option="RAW")
        print("added %s (office %s, mode %s)\n\nPassword (shown once):\n\n    %s\n"
              % (u, a.office, C.office(a.office).bgc_mode, pw))
        return 0

    target = a.reset or a.disable or (a.mode[0] if a.mode else "")
    row = _find(rows, target)
    if not row:
        print("no such username", file=sys.stderr)
        return 2
    if a.disable:
        _retry(ws.update, [["FALSE"]], "E%d" % row)
        print("disabled %s" % target)
    elif a.mode:
        m = a.mode[1].strip().lower()
        if m not in ("dry", "live"):
            print("mode is dry or live", file=sys.stderr)
            return 2
        _retry(ws.update, [[m]], "F%d" % row)
        print("%s is now %s" % (target, m))
    else:
        pw = new_password()
        salt, h = make_hash(pw)
        _retry(ws.update, [[salt, h, "TRUE"]], "C%d:E%d" % (row, row))
        print("password reset for %s\n\nPassword (shown once):\n\n    %s\n" % (target, pw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
