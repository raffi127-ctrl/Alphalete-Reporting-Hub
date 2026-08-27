"""SaraPlus spelling -> board spelling, editable by a person, no deploy.

WHY THIS EXISTS. On 2026-08-26 the sweep found "Kelvinton Scarbrough" selling
with no board row, and refused to add one because "Kelvinton ( BO ) Scarbough
(Wk 3)" was already there -- same man, three differences (a nickname in
parentheses, a missing 'r', a week suffix). Refusing was right: a second row
would have split his week and the totals would still have footed, so nobody
would have caught it.

But the text then named a decision nobody could act on. The only fix was a
code change to config.NAME_MAP, which means a deploy, which means me. So the
answer lives where the people who know the answer already are: a tab on the
sales board itself.

    Sales Text Aliases
      SaraPlus Name        | Board Name
      KELVINTON SCARBROUGH | Kelvinton ( BO ) Scarbough (Wk 3)

Read fresh on every sweep, so a row added at 2pm is honoured at 2:05. Blank
rows are ignored; a Board Name that matches nobody is reported rather than
silently swallowed. [[feedback_alias_list]] [[feedback_simple_ux]]
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import config as C

TAB = "Sales Text Aliases"
HEADERS = ["SaraPlus Name", "Board Name", "Added By", "Note"]


def _open_tab(client=None, create: bool = True):
    from automations.recruiting_report.fill import _client
    book = (client or _client()).open_by_key(C.SPREADSHEET_ID)
    for ws in book.worksheets():
        if ws.title.strip().lower() == TAB.lower():
            return ws
    if not create:
        return None
    ws = book.add_worksheet(title=TAB, rows=200, cols=4)
    ws.update("A1:D1", [HEADERS])
    ws.format("A1:D1", {"textFormat": {"bold": True}})
    return ws


def load(client=None) -> Dict[str, str]:
    """{SARAPLUS NAME (upper): board name}. Empty on ANY failure -- a missing
    or unreadable alias tab must never stop the sweep; the worst case is the
    rep stays unmatched and is reported, which is where we already were."""
    try:
        ws = _open_tab(client, create=False)
        if ws is None:
            return {}
        rows = ws.get_all_values()[1:]
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for r in rows:
        if len(r) < 2:
            continue
        sara, board = (r[0] or "").strip(), (r[1] or "").strip()
        if sara and board:
            out[sara.upper()] = board
    return out


def ensure_tab(client=None) -> str:
    """Create the tab (with headers) if it isn't there. Returns its title."""
    return _open_tab(client, create=True).title


def add(sara_name: str, board_name: str, *, by: str = "sweep",
        note: str = "", client=None) -> None:
    """Append one alias. Used by nobody automatically on purpose -- a person
    decides whether two spellings are one man."""
    ws = _open_tab(client, create=True)
    ws.append_row([sara_name.strip().upper(), board_name.strip(), by, note],
                  value_input_option="USER_ENTERED")
