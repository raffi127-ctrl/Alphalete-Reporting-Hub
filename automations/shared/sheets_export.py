"""Shared guards for the Google Sheets PDF-export endpoint.

Seven modules in this repo screenshot a Sheet by asking
`docs.google.com/spreadsheets/d/<id>/export?format=pdf&gid=<gid>&range=<a1>`
and rasterising the answer. The endpoint has one failure mode that looks
exactly like success, and it cost a full morning on 2026-08-25:

    A HIDDEN tab exports as an EMPTY PAGE — HTTP 200, a valid PDF, 993 bytes,
    no text, no error, no toast.

So `requests` raises nothing, the rasteriser produces a clean white PNG, the
report logs "posted", and a white rectangle lands in Slack looking like a good
capture. That day it was Carlos's `customer_churn` and `activation_by_rep`,
both shooting the `LUCY CHURN` tab, which he keeps hidden along with every
other 'Lucy …' working tab.

Measured that day on his board — the gap is not subtle:

    Sales Board          visible     95 KB   text
    Commission           visible    129 KB   text
    LUCY CHURN           HIDDEN     993 B    none
    Lucy Wireless Churn  HIDDEN     993 B    none

An insufficient OAuth scope produces the SAME 993-byte answer, which is why
the symptom alone can't tell you which one you have. It is worth knowing that
the export of the whole FILE (no `gid`) works fine and simply omits hidden
tabs, so that is not a workaround either.

Two things live here:

  * `check_pdf`         — refuse an empty export instead of rasterising it.
  * `visible_for_export` — reveal a hidden tab for the length of the export
                          and put it back, so a board's own layout is not
                          rewritten to make a report work.
"""
from __future__ import annotations

from contextlib import contextmanager

# The empty answer is 993 bytes. The SMALLEST real export measured — a single
# populated cell, A1:A1 — is 14,570. Two thousand sits an order of magnitude
# below the smallest real one and at twice the empty one, so it cannot argue
# with a legitimately tiny shot.
EMPTY_PDF_BYTES = 2000


def check_pdf(content: bytes, *, where: str) -> bytes:
    """Return `content`, or raise if the export came back empty.

    `where` names the shot for the error message — "<tab>!<range>" is ideal,
    because the FIRST thing to check is whether that tab is hidden.
    """
    if content and content[:4] == b"%PDF" and len(content) > EMPTY_PDF_BYTES:
        return content
    if not content or content[:4] != b"%PDF":
        raise RuntimeError(
            f"{where}: the Sheets export did not return a PDF "
            f"({len(content or b'')} bytes) — check the token and the URL.")
    raise RuntimeError(
        f"{where}: the Sheets PDF export came back EMPTY ({len(content)} "
        f"bytes, under the {EMPTY_PDF_BYTES}-byte floor). Check the TAB "
        "first: a HIDDEN tab exports as a blank page with HTTP 200 and no "
        "error, which is the usual cause. Second suspect is the OAuth token, "
        "which produces an identical empty PDF when it lacks the scope — "
        "`lucy sheets_whoami` on the runner, and try another spreadsheet to "
        "tell the two apart. An actually-empty range is the least likely.")


def tab_hidden(ws) -> bool:
    """Is this worksheet hidden? False on any lookup problem — a visibility
    read must never be what breaks a screenshot."""
    try:
        for sh in (ws.spreadsheet.fetch_sheet_metadata().get("sheets") or []):
            props = sh.get("properties", {})
            if props.get("sheetId") == ws.id:
                return bool(props.get("hidden", False))
    except Exception:  # noqa: BLE001
        pass
    return False


def set_tab_hidden(ws, hidden: bool) -> None:
    ws.spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id, "hidden": hidden},
        "fields": "hidden"}}]})


@contextmanager
def visible_for_export(ws):
    """Reveal `ws` if it is hidden, and hide it again on the way out.

    The re-hide is in a `finally` on purpose: people hide these tabs
    deliberately (Carlos hides every 'Lucy …' working tab), so a crash must not
    leave someone's board rearranged. A tab that was already visible is left
    exactly as it was — this never hides anything that wasn't hidden.
    """
    was_hidden = tab_hidden(ws)
    if was_hidden:
        set_tab_hidden(ws, False)
    try:
        yield
    finally:
        if was_hidden:
            try:
                set_tab_hidden(ws, True)
            except Exception:  # noqa: BLE001 — surface the real error, not this
                pass
