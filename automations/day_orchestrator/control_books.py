"""Where each Lucy's queue and the fleet heartbeats live (2026-10-29).

WHY (Megan, 2026-10-29: "each lucy should have their own right?"). Every
Lucy's queue tab, every heartbeat and the Hub activity log all sat in ONE
workbook, AUTOMATION MASTER. When Google slowed that one file down — reads at
40-170s, Chrome itself stuck on "Trying to connect…" — every Lucy's queue froze
together, and Lucy 1 sat for 90 minutes with 14 jobs queued and nothing taken.
Now each Lucy reads her own workbook ("LUCY N - Automations Master"), and the
heartbeats have a small one of their own, so one slow file holds up one Lucy.

THE CUT-OVER IS SAFE BY CONSTRUCTION — there is no flag day:
  * a Lucy on this code drains BOTH her own workbook and her old tab in
    AUTOMATION MASTER (the old one at a slow cadence), so a row queued by a
    laptop still on old code is never stranded;
  * a queue command only writes into a Lucy's own workbook once that tab is
    PROVEN live (a runner wrote done/failed there — see mini_control
    _tab_is_live). Her poller proves it the first time it opens the tab. Until
    then the row goes to the old tab, exactly as before.

Tab names inside each workbook are unchanged ("Mini Control" for Lucy 1,
"Mini Control - Lucy N" otherwise), so every message and log still reads the
same. Add a Lucy 5 = make her workbook, share it, add one line here.
"""
from __future__ import annotations

#: The old shared workbook. Still the fallback, and still drained.
LEGACY_BOOK = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # AUTOMATION MASTER

#: machine -> its own queue workbook. Owner raffi127@; shared (writer) with
#: alphaletereporting@ (Lucy 2/3/4's Sheets login) and the team.
BOOKS = {
    "Lucy 1": "1yLFW3o5bT8wN9GK7c6GJWscaQoFpgEjJglWH7lrbHIo",  # LUCY 1 - Automations Master
    "Lucy 2": "1DSKQth2UUBoqVN2HuUWEQiq2XDQmpY7Ec4IqQWEz440",  # LUCY 2 - Automations Master
    "Lucy 3": "1grUC4VY4-fsLK2HKsRu_lGOqiX8JojCA8gBNujELKAc",  # LUCY 3 - Automations Master
    "Lucy 4": "1zQhg4jhlLP8OM8SySlIA-VtDmXjKpZnSBcWDONx2suI",  # LUCY 4 - Automations Master
}

#: The fleet heartbeats ("Job Heartbeats" tab). One book, not one per Lucy:
#: routing and the peer watch read EVERY Lucy's beat at once, and four books
#: would turn that one read into four.
HEARTBEAT_BOOK = "1GpXR5jfIEoTijp8uv9HBJAg0Q4d_iR5bdH5CvumRcyk"   # LUCY FLEET - Heartbeats

#: While some machine may still be on old code, beats are ALSO written to the
#: old tab and reads merge both (newest beat wins). Turn off once every Lucy
#: and every laptop that runs `lucy` has pulled this change.
MIRROR_LEGACY_BEATS = True


def _canon(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def book_for(machine: str | None) -> str | None:
    """This machine's own queue workbook, or None (= stay on AUTOMATION MASTER).
    Loose match, so 'lucy2' and 'Lucy 2' are the same machine."""
    want = _canon(machine or "")
    for name, key in BOOKS.items():
        if _canon(name) == want:
            return key
    return None
