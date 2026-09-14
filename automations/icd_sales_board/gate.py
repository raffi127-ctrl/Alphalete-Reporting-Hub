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


def passed(hosted: bool) -> bool:
    """True when the reader may see the board."""
    if not hosted:
        return True                      # a Mac in the office
    want = _configured()
    if not want:
        st.error("This board has no access code set, so it is not being "
                 "shown. Ask Megan to add one.")
        return False
    if st.session_state.get(_KEY):
        return True

    st.markdown("#### Alphalete Marketing")
    st.write("Enter the code you were sent to open the sales board.")
    got = st.text_input("Access code", type="password",
                        label_visibility="collapsed",
                        placeholder="Access code")
    if got:
        # compare_digest so a wrong code takes the same time as a right one
        if hmac.compare_digest(got.strip(), want.strip()):
            st.session_state[_KEY] = True
            st.rerun()
        st.error("That code does not match. Check it and try again.")
    return False
