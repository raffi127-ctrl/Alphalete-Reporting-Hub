"""Every ApplicantStream account Lucy's login can see: Office ID, Owner Name,
Office Name -> the relay's 'AppStream Offices' tab.

WHY (Megan 2026-11-09): approving an office's accounts on the Office Admin
Logins card shouldn't mean typing account numbers -- "link that owner's name to
their account number in app stream automatically. If multiple accounts are
assigned to that ICD, their name is still the first thing." The office picker
(#searchMC) lists every account with its owner when the box is empty; this
reads that list once a day, and the Hub card ticks the accounts whose owner
matches the ICD for Megan to confirm.

TICKED, NOT APPROVED. An account can carry the wrong owner (Omar's old office
listed "Rafael Hidalgo"), so the card only suggests; a person saves, and the
one-account-one-office guard still refuses a double.

    python -m automations.office_admin.appstream_offices            # read + save
    python -m automations.office_admin.appstream_offices --dry-run  # read + print
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Dict, List

TAB = "AppStream Offices"
HEAD = ["Office ID", "Owner Name", "Office Name", "Updated"]


def read(app, log=print) -> List[Dict]:
    """The picker's full list, off the warm session. Raises if it shows nothing."""
    app.open_retention_details()
    page = app.page
    box = page.locator("#searchMC")
    box.wait_for(timeout=30000)
    box.click()
    box.fill("")
    page.keyboard.press("Space")          # an empty search opens the full list
    page.keyboard.press("Backspace")
    page.wait_for_timeout(3000)
    rows = page.evaluate("""() => [...document.querySelectorAll('ul.ui-autocomplete li')]
        .map(li => (li.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean))""")
    out, seen = [], set()
    for parts in rows:
        if not parts or not re.fullmatch(r"\d+", parts[0]) or parts[0] in seen:
            continue
        seen.add(parts[0])
        out.append({"id": parts[0], "owner": parts[1] if len(parts) > 1 else "",
                    "office": parts[2] if len(parts) > 2 else ""})
    if not out:
        raise RuntimeError("the office picker listed no accounts")
    log("appstream offices: %d accounts" % len(out))
    return out


def write(offices: List[Dict]) -> None:
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    titles = [w.title for w in _retry(ss.worksheets)]
    ws = (_retry(ss.worksheet, TAB) if TAB in titles
          else _retry(ss.add_worksheet, title=TAB, rows=600, cols=len(HEAD)))
    now = dt.datetime.now().isoformat(timespec="minutes")
    _retry(ws.clear)
    _retry(ws.update, [HEAD] + [[o["id"], o["owner"], o["office"], now] for o in offices], "A1")


def cached() -> List[Dict]:
    """The last saved list (the Hub card reads this)."""
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        rows = _retry(_retry(ss.worksheet, TAB).get_all_values)
    except Exception:  # noqa: BLE001 -- never read yet
        return []
    return [{"id": r[0].strip(), "owner": r[1].strip(), "office": r[2].strip()}
            for r in rows[1:] if r and r[0].strip()]


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", (name or "").lower()).split())


def for_owner(owner: str, offices: List[Dict], aliases=None) -> List[Dict]:
    """Accounts whose Owner Name is this ICD: exact, then first + last name,
    then any name the team's ICD Aliases sheet gives for them ("Kash Rai" is
    "Akashdeep Rai" in ApplicantStream)."""
    hit = _for_name(owner, offices)
    if hit:
        return hit
    try:
        from automations.focus_office_att import aliases as AL
        raw = aliases if aliases is not None else AL.load_aliases()
        for name in AL.get_search_candidates(owner, raw):
            hit = _for_name(name, offices)
            if hit:
                return hit
    except Exception:  # noqa: BLE001 -- the sheet unreadable: no extra names
        pass
    return []


def _for_name(owner: str, offices: List[Dict]) -> List[Dict]:
    want = _norm(owner)
    if not want:
        return []
    exact = [o for o in offices if _norm(o["owner"]) == want]
    if exact:
        return exact
    # Same first + last name, middle names ignored ("Trang Canavan" is
    # "Trang Le Nguyen Canavan" in ApplicantStream).
    w = want.split()
    def fl(n):
        p = _norm(n).split()
        return (p[0], p[-1]) if p else None
    return [o for o in offices if len(w) > 1 and fl(o["owner"]) == (w[0], w[-1])]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Save ApplicantStream's office list for the Hub card.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from automations.applicant_tracker.applicantstream import session
    with session() as app:
        offices = read(app)
    if a.dry_run:
        for o in offices[:15]:
            print("  %s  %s  %s" % (o["id"], o["owner"], o["office"]))
        return 0
    write(offices)
    print("saved %d accounts to the relay's '%s' tab" % (len(offices), TAB))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
