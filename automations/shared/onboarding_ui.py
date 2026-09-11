"""Shared building blocks for the onboarding Streamlit apps.

One place for the pieces the three Cloud forms (tracker sign-up, metrics
request, metrics finalize) used to each carry their own copy of — so a fix
lands once and every form stays uniform (Megan 2026-08-20: "everything to
look very uniform and not built from scratch each time").

Import-light on purpose: streamlit + google-auth/gspread only, and only
inside the functions, so any app (or a test) can import this module without
dragging the whole Hub in.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


# --- branding ---------------------------------------------------------------

def render_header(subtitle: str, caption: str = "") -> None:
    """The house header every ICD-facing form opens with."""
    import streamlit as st
    st.markdown("## 📊 Alphalete Reporting by Lucy")
    st.markdown(f"### {subtitle}")
    if caption:
        st.caption(caption)


# --- secrets → clients ------------------------------------------------------

def build_gs_client(local_only_env: str):
    """(gspread client | None, keys-only diagnostic dict).

    The one true secrets→Sheets wiring: service account first, then the
    [gcp_oauth] secret, then the laptop's oauth-token.json (local sandbox).
    `local_only_env`=1 forces the local-draft sandbox. The diagnostic never
    contains secret VALUES — safe to show behind ?debug=1."""
    import streamlit as st

    diag = {"local_only": os.environ.get(local_only_env),
            "gspread_import": False, "secret_keys": None, "has_gcp_oauth": False,
            "has_gcp_service_account": False, "oauth_field_keys": None,
            "client_set": False, "error": ""}
    if os.environ.get(local_only_env) == "1":
        diag["error"] = f"{local_only_env}=1 forces local draft"
        return None, diag
    try:
        import gspread
        diag["gspread_import"] = True
    except Exception as e:                           # noqa: BLE001
        diag["error"] = f"gspread import failed: {type(e).__name__}: {e}"
        return None, diag
    try:
        diag["secret_keys"] = sorted(list(st.secrets.keys()))
    except Exception as e:                           # noqa: BLE001
        diag["error"] = f"st.secrets unreadable: {type(e).__name__}: {e}"
    try:
        sa = st.secrets.get("gcp_service_account")
    except Exception:                                # noqa: BLE001
        sa = None
    diag["has_gcp_service_account"] = bool(sa)
    if sa:
        try:
            gc = gspread.service_account_from_dict(dict(sa))
            diag["client_set"] = True
            return gc, diag
        except Exception as e:                       # noqa: BLE001
            diag["error"] = f"service_account client failed: {type(e).__name__}: {e}"
            return None, diag
    try:
        o = st.secrets.get("gcp_oauth")
    except Exception:                                # noqa: BLE001
        o = None
    diag["has_gcp_oauth"] = bool(o)
    if o:
        try:
            diag["oauth_field_keys"] = sorted(list(dict(o).keys()))
        except Exception:                            # noqa: BLE001
            pass
    if not o:
        tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
        if tok.exists():
            import json
            o = json.loads(tok.read_text())
    if o:
        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials(
                token=o.get("token"), refresh_token=o.get("refresh_token"),
                token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=o.get("client_id"), client_secret=o.get("client_secret"),
                scopes=list(o.get("scopes") or
                            ["https://www.googleapis.com/auth/spreadsheets"]))
            gc = gspread.authorize(creds)
            diag["client_set"] = True
            return gc, diag
        except Exception as e:                       # noqa: BLE001 — report, don't crash
            diag["error"] = f"oauth client build failed: {type(e).__name__}: {e}"
    return None, diag


def inject_slack_token() -> None:
    """Export the `slack_user_token` secret as SLACK_USER_TOKEN so the
    corrections ping + the Lucy membership check work on Streamlit Cloud.
    Best-effort — an absent secret just means no ping/check (submissions
    still save)."""
    import streamlit as st
    try:
        tok = st.secrets.get("slack_user_token")
    except Exception:                                # noqa: BLE001
        tok = None
    if tok and not os.environ.get("SLACK_USER_TOKEN"):
        os.environ["SLACK_USER_TOKEN"] = str(tok).strip()


# --- channel id help --------------------------------------------------------

CHANNEL_ID_HELP = ("This is a CODE (letters + numbers) that starts with C — "
                   "NOT the channel's name. To find it: in Slack, click the "
                   "channel's name at the top of the screen, scroll to the "
                   "very bottom of the pop-up, and copy the Channel ID shown "
                   "there.")


# A Slack channel id is an uppercase CODE: a leading C (public), G (old private)
# or D (DM), then letters+digits. "loganlegacygroup" is a workspace handle and
# "#joseph-logan-office" is a name — neither can ever resolve, and both used to
# sail straight through to the sheet, where the only thing that noticed was
# Lucy's membership check failing hours later (Joseph Logan, 2026-09-11).
# 9 chars minimum and at least one digit: without the digit rule a plain word
# that starts with C ("Corporate", "cancels") is a legal-looking id.
_CHANNEL_ID_RE = re.compile(r"^[CGD](?=[A-Z0-9]*\d)[A-Z0-9]{8,22}$")

# People paste the whole Slack link as often as the bare id. Take it either way
# — /archives/<id> (copy-link) and /client/<team>/<id> (address bar).
_CHANNEL_ID_IN_URL = re.compile(r"/(?:archives|client)/(?:[A-Z0-9]+/)?"
                                r"([CGD][A-Z0-9]{6,22})", re.I)

_NOT_AN_ID = ("That's the channel's **name**, not its ID. The ID is a code like "
              "`C0ABC12DE` — in Slack, click the channel's name at the top of "
              "the screen, scroll to the very bottom of the pop-up, and copy "
              "the Channel ID.")


def normalize_channel_id(raw: str) -> tuple:
    """(clean id, problem sentence). Exactly one of the two is ever filled.

    Empty in -> empty out with NO problem: "you left it blank" is the required-
    field check's job, not this one's. A pasted Slack link gives up its id; a
    lowercase id is just shouted back uppercase. Anything else is refused with a
    sentence that says what to do instead of what went wrong.
    """
    got = (raw or "").strip()
    if not got:
        return "", ""
    m = _CHANNEL_ID_IN_URL.search(got)
    # A url's id still has to BE an id — the extract narrows where to look, it
    # is not a second, looser rule.
    cand = (m.group(1) if m else got.strip("<>#@ ").split("|")[0]).strip().upper()
    if _CHANNEL_ID_RE.match(cand):
        return cand, ""
    return "", _NOT_AN_ID


def channel_id_input(label: str, *, key: str, **kw) -> str:
    """A Channel ID box that refuses a name. Returns the CLEAN id ("" if the
    box is empty or holds something that can't be one), and shows the fix
    inline the moment they type it — not at submit, and never hours later."""
    import streamlit as st
    raw = st.text_input(label, key=key, placeholder="C0ABC12DE",
                        help=CHANNEL_ID_HELP, **kw)
    clean, problem = normalize_channel_id(raw)
    if problem:
        st.error("⚠️ " + problem)
    elif clean and clean != (raw or "").strip():
        # Took a pasted link or fixed the case — say so, so it isn't a surprise.
        st.caption("Using channel ID `{}`".format(clean))
    return clean


def channel_id_help_expander(img_path: Path) -> None:
    """The 'Where do I find my Channel ID?' expander with Megan's full
    screenshot. No-op when the app doesn't ship the image."""
    import streamlit as st
    if not img_path.exists():
        return
    with st.expander("Where do I find my Channel ID?"):
        st.caption("In Slack, click the channel's name at the top of the "
                   "screen, scroll to the bottom of the pop-up, and copy "
                   "the Channel ID:")
        st.image(str(img_path), use_container_width=True)


# --- lucy membership check (re-exports) -------------------------------------
# The check itself lives in tracker_onboarding.slack_check (works off
# SLACK_USER_TOKEN, so inject_slack_token() first on Cloud).

def check_channel(channel_id: str = "", channel_name: str = "") -> dict:
    from automations.tracker_onboarding.slack_check import check_channel as _c
    return _c(channel_id, channel_name)


def lucy_line(res: dict) -> str:
    from automations.tracker_onboarding.slack_check import human_line
    return human_line(res)
