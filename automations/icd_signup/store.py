"""Where a Lucy Eco sign-up goes: the 'ICD Signup' tab of the relay workbook.

THE SAME WORKBOOK THE RELAY ALREADY USES, on purpose. Everything about an ICD
office already lives in 'Lucy Access App' -- their keys, their relayed numbers,
their channel approvals -- and a sign-up that landed somewhere else would be
the one fact about an office you had to go looking for.

Mirrors disposition_signup.store: one row per office, a local-JSON fallback so
the form can be built and tested without touching the sheet, and an append that
never overwrites somebody else's row.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_signup.schema import (IcdSignup, STATUS_PENDING,
                                          STATUS_APPROVE_REQUESTED, stamp)

SIGNUP_TAB = "ICD Signup"
_HEADER = ["office_key", "owner", "office_label", "contact", "platform",
           "timezone", "day_start", "day_end", "saturday", "sat_start",
           "sat_end", "ov_name", "knocks_cadence", "wanted_channels",
           "status", "submitted_at", "note",
           # APPENDED, never inserted. The tab already exists and the Apps
           # Script writes nothing here, but a person may be looking at it --
           # and reordering columns under somebody is how a sheet stops
           # meaning what it says.
           "alert_channels_json", "knocks_json", "campaign"]

_LOCAL_FALLBACK = (Path(__file__).resolve().parents[2] / "output"
                   / "icd_signup_submissions.json")

try:                                     # gspread >= 5
    from gspread.exceptions import WorksheetNotFound as _WorksheetNotFound
except Exception:                        # noqa: BLE001
    class _WorksheetNotFound(Exception):
        pass


_CLIENT = None


def set_client(gspread_client) -> None:
    """Hand this module the client the FORM built from Streamlit's secrets.

    THIS IS WHY THE FIRST LIVE SIGN-UP VANISHED (2026-09-13). _book() went
    straight to recruiting_report.fill.open_by_key, which authenticates from
    credential FILES in the repo -- fine on a Lucy or on Megan's laptop, and
    nonexistent on Streamlit Cloud, where the credentials live in st.secrets
    and nowhere else. So every submission from the deployed form threw, fell
    into the local-draft fallback, and was lost on a disposable filesystem.
    The secrets were correct the whole time; nothing ever read them.

    Every other form in this repo already did it this way. This one did not,
    because it grew up being tested from a laptop where the file path worked.
    """
    global _CLIENT
    _CLIENT = gspread_client


def _book():
    from automations.icd_alerts import post as P
    if _CLIENT is not None:
        return _CLIENT.open_by_key(P.RELAY_SPREADSHEET_ID)
    # No injected client: a Lucy, a laptop, or a test. The file path is right
    # there and is what every non-Streamlit caller uses.
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(P.RELAY_SPREADSHEET_ID)


def _tab(book=None):
    book = book or _book()
    try:
        tab = book.worksheet(SIGNUP_TAB)
    except _WorksheetNotFound:
        tab = book.add_worksheet(title=SIGNUP_TAB, rows=200,
                                 cols=len(_HEADER))
        tab.append_row(_HEADER)
        return tab
    _ensure_header(tab)
    return tab


def _ensure_header(tab) -> None:
    """Add any column _HEADER has gained since this tab was created.

    THE BUG THIS FIXES WAS INVISIBLE. Adding alert_channels_json and
    knocks_json to _HEADER did not add them to a tab that already existed, so
    append_row wrote those values PAST the end of the header -- present in the
    sheet, under no column name. Everything looked like it had worked: the
    sign-up saved, the key was minted, the link came back. But the relay reads
    those columns BY NAME to hand them to the installer, found no such column,
    and served an empty list. The office's channels were silently dropped
    between the form and their own machine (caught live 2026-09-13).

    APPENDS ONLY, never reorders or renames. Somebody may be reading this tab,
    and a column that moves under them is worse than a column that is missing.
    """
    try:
        head = tab.row_values(1)
    except Exception:  # noqa: BLE001
        return
    missing = [h for h in _HEADER if h not in head]
    if not missing:
        return
    try:
        tab.update(range_name="%s1" % _a1_col(len(head) + 1),
                   values=[missing], value_input_option="RAW")
    except Exception:  # noqa: BLE001 — a sign-up must never be lost to this
        pass


def _a1_col(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _local() -> List[Dict]:
    try:
        return json.loads(_LOCAL_FALLBACK.read_text())
    except (OSError, ValueError):
        return []


def _save_local(rows: List[Dict]) -> None:
    _LOCAL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_FALLBACK.write_text(json.dumps(rows, indent=2))


def office_key_for(owner: str, taken=(), campaign: str = "") -> str:
    """This enrollment's key: first name, then the campaign if that is taken.

    ONE KEY PER CAMPAIGN, because a campaign IS a reporting unit here -- its
    own channels, its own cadence, its own board, its own relay key. An owner
    running two enrols twice and gets `ryan` and `ryan-box`, which is also
    what somebody reading the sheet needs to see.

    The campaign suffix rather than a number, because "ryan2" tells nobody
    which campaign it is, and this key appears in the approve command, the
    relay row and the office's own setup code.
    """
    import re
    first = (owner or "").strip().split()[0] if (owner or "").strip() else ""
    base = re.sub(r"[^a-z]", "", first.lower()) or "office"
    if base not in taken:
        return base
    camp = re.sub(r"[^a-z0-9]", "", (campaign or "").lower())
    if camp and "%s-%s" % (base, camp) not in taken:
        return "%s-%s" % (base, camp)
    n = 2
    while "%s%d" % (base, n) in taken:
        n += 1
    return "%s%d" % (base, n)


# The page that shows them their one line. Same page the invite command hands
# out, so an office that signs up and an office we enrol by hand end up
# looking at exactly the same thing.
SETUP_PAGE = "https://raffi127-ctrl.github.io/Alphalete-Reporting-Hub/?code=%s"


def setup_link(relay_key: str) -> str:
    return SETUP_PAGE % relay_key


def mint_and_record_key(office_key: str, owner: str, book=None) -> str:
    """Give this office its relay key, at SIGN-UP time rather than at approval.

    WHY IT IS SAFE TO HAND OUT BEFORE MEGAN APPROVES (Megan 2026-09-13: "their
    machine is set up so that when I approve it's good to go"). The key does
    exactly one thing -- it lets that office hand in ITS OWN numbers. It cannot
    read anything, cannot reach another office's row, and cannot put a single
    message in a Slack channel: where alerts post is a separate approval on the
    'Office Channels' tab, and an office with nothing approved is HELD. So the
    worst an un-approved sign-up can do is relay numbers nobody looks at, and
    one cell on 'Relay Keys' switches it off.

    Minting here is what lets them install while they are still sitting there,
    instead of waiting on us -- which was the whole complaint.
    """
    from automations.icd_alerts.enroll import mint_key

    key = mint_key(office_key)
    book = book or _book()
    tab = book.worksheet("Relay Keys")
    for row in tab.get_all_values()[1:]:
        if row and (row[0] or "").strip().lower() == office_key:
            # Already has one. Hand back what they already have rather than
            # minting a second: two live keys for one office is a revocation
            # that does not revoke.
            return (row[1] or "").strip()
    tab.append_row([office_key, key, "TRUE",
                    "self sign-up — %s" % owner])
    return key


def all_signups(book=None) -> List[IcdSignup]:
    try:
        rows = _tab(book).get_all_records()
    except Exception:  # noqa: BLE001 — no sheet access: fall back to local
        rows = _local()
    return [IcdSignup.from_row(r) for r in rows if (r.get("owner") or "").strip()]


def pending(book=None) -> List[IcdSignup]:
    return [s for s in all_signups(book) if s.status == STATUS_PENDING]


def get(office_key: str, book=None) -> Optional[IcdSignup]:
    key = (office_key or "").strip().lower()
    return next((s for s in all_signups(book) if s.office_key == key), None)


def submit(rec: IcdSignup, book=None) -> IcdSignup:
    """Append one sign-up as PENDING. Never overwrites an existing row.

    The office key is assigned HERE rather than by the form, because it has to
    be unique across everyone who has ever signed up and the form cannot see
    the others.
    """
    existing = all_signups(book)
    taken = {s.office_key for s in existing if s.office_key}
    rec = rec._replace(
        office_key=rec.office_key or office_key_for(rec.owner, taken,
                                                    rec.campaign),
        status=STATUS_PENDING,
        submitted_at=rec.submitted_at or stamp(),
    )
    row = rec.as_row()
    ordered = [row.get(h, "") for h in _HEADER]
    try:
        _tab(book).append_row(["TRUE" if v is True else
                               "FALSE" if v is False else v for v in ordered])
        return rec, True
    except Exception:  # noqa: BLE001 — the owner's answers must not be lost
        # A LOCAL DRAFT IS NOT A SAVE, and the caller has to know the
        # difference. On Streamlit Cloud this file is on a disposable
        # filesystem, so the draft is gone the moment the app restarts. Megan
        # submitted on 2026-09-13, was told "that is in", and nothing existed
        # anywhere: no row, no key, no ping. Reporting success for a write
        # that failed is worse than failing loudly, because nobody goes
        # looking for something they were told had worked.
        rows = _local()
        rows.append(row)
        _save_local(rows)
        return rec, False


def submit_and_key(rec: IcdSignup, book=None) -> tuple:
    """Save the sign-up AND give them their key.

    Returns (record, setup_link, landed) where `landed` says whether the
    sign-up actually reached the sheet. An empty link with landed=True is a
    real sign-up whose key failed -- Megan sends the link by hand. landed=
    False means nobody has it at all and the page must say so.
    """
    saved, landed = submit(rec, book=book)
    if not landed:
        return saved, "", False
    try:
        key = mint_and_record_key(saved.office_key, saved.owner, book=book)
    except Exception:  # noqa: BLE001
        return saved, "", True
    return saved, (setup_link(key) if key else ""), True


def set_status(office_key: str, status: str, note: str = "", book=None) -> bool:
    key = (office_key or "").strip().lower()
    try:
        tab = _tab(book)
        values = tab.get_all_values()
    except Exception:  # noqa: BLE001
        return False
    head = values[0] if values else _HEADER
    try:
        c_key = head.index("office_key")
        c_status = head.index("status")
        c_note = head.index("note")
    except ValueError:
        return False
    for i, row in enumerate(values[1:], start=2):
        if len(row) > c_key and (row[c_key] or "").strip().lower() == key:
            tab.update_cell(i, c_status + 1, status)
            if note:
                tab.update_cell(i, c_note + 1, note)
            return True
    return False


def request_approval(office_key: str, by: str = "", book=None) -> bool:
    """Mark an office APPROVE_REQUESTED. The click, not the work.

    A person pressing a button in a browser cannot do the approving: it means
    resolving Slack channels, checking Lucy is in each one and writing the
    sign-off, and this form runs on Streamlit Cloud with a token that is a
    stranger to that workspace -- which is exactly how the sign-up ping failed
    (2026-09-13). So the click leaves a mark and the poster on Lucy 3 does the
    real thing, with every check intact, and says what happened.
    """
    return set_status(office_key, STATUS_APPROVE_REQUESTED,
                      note="approve clicked%s %s" % (" by %s" % by if by else "",
                                                     stamp()), book=book)


def approval_requested(book=None) -> List[IcdSignup]:
    return [s_ for s_ in all_signups(book)
            if s_.status == STATUS_APPROVE_REQUESTED]
