"""Who may open the sales board when it is not running on one of our Macs.

The board shows every rep's name and daily production across every office. On
a Mac in the office that is fine — you had to be at the machine. On a public
URL it is not, and Community Cloud has no login of its own, so this is the
login.

FAILS CLOSED WHEN HOSTED. If the page is running off host credentials and no
code has been configured, it shows nothing and says who to ask. An
unconfigured gate that quietly lets everyone in is the failure mode worth
designing out.
"""
from __future__ import annotations

import hmac

import streamlit as st

_KEY = "board_access_ok"


def _configured() -> str:
    try:
        return str(st.secrets.get("board_code", "") or "")
    except Exception:   # noqa: BLE001 — no secrets file at all
        return ""


ALL = "*"
_SCOPE = "board_scope"


def scope() -> str:
    """Who this viewer may see: ALL, or one ICD's name.

    Set by passed(). A viewer on one of our own Macs was never asked for a
    code, so they see everything, as they always have."""
    return st.session_state.get(_SCOPE, ALL)


def _match(got: str) -> str:
    """The scope a typed code opens, or '' when it opens nothing.

    Megan's board_code opens every office. An ICD's code — from the Board
    Access tab — opens that office alone, which is what makes the link theirs
    rather than a window onto everybody (Megan 2026-09-22)."""
    got = (got or "").strip()
    if not got:
        return ""
    admin = _configured()
    # compare_digest so a wrong code takes the same time as a right one
    if admin and hmac.compare_digest(got.lower(), admin.strip().lower()):
        return ALL
    try:
        from automations.icd_sales_board import board_access as BA
        table = BA.codes()
    except Exception:   # noqa: BLE001 — an unreadable tab opens nothing
        table = {}
    for code, icd in table.items():
        if hmac.compare_digest(got.lower(), code):
            return icd
    return ""


def passed(hosted: bool) -> bool:
    """True when the reader may see the board; records WHAT they may see."""
    if not hosted:
        st.session_state[_SCOPE] = ALL     # a Mac in the office
        return True
    if not _configured():
        st.error("This board has no access code set, so it is not being "
                 "shown. Ask Megan to add one.")
        return False
    if st.session_state.get(_KEY):
        return True

    # Drawn into a placeholder so it can be taken DOWN the moment the code is
    # accepted. Left in place, the old screen stayed up for as long as the
    # board took to paint, which read as a code that had not worked.
    box = st.empty()
    with box.container():
        st.markdown("#### Your sales board")
        st.write("Enter the code you were sent.")
        got = st.text_input("Access code", type="password",
                            label_visibility="collapsed",
                            placeholder="Access code")
    if got:
        opens = _match(got)
        if opens:
            st.session_state[_KEY] = True
            st.session_state[_SCOPE] = opens
            box.empty()
            st.rerun()
        st.error("That code does not match. Check it and try again.")
    return False
