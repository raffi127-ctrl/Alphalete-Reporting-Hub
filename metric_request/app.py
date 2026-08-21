"""Request Your Office Metrics — the OWNER-facing form.

This is the link Megan sends to an office owner. It is deliberately
7-year-old-simple: the owner picks how they sell (D2D / B2B) and checks the
metrics they want to see posted to their Slack every morning, tells us who they
are and where to post, and submits. That's it — no channel IDs to hunt down, no
Google Sheet, no wiring.

On submit it saves a PARTIAL record to the 'Metric Requests' tab of the
AUTOMATION MASTER sheet and pings Megan in the corrections channel. Megan then
creates the office's Google Sheet and finalizes the wiring in the Office
Onboarding form — where this request shows up pre-filled under "start from a
request", so she never has to guess what the owner wanted.

Run locally:   .venv/bin/streamlit run metric_request/app.py
On the web:    deploy this repo to Streamlit Community Cloud with
               metric_request/app.py as the entry point (suggested subdomain
               alphaletemetricsrequest).

Secrets (Streamlit Cloud, or .streamlit/secrets.toml locally):
  [gcp_service_account] / [gcp_oauth]   # Google creds for the master sheet
Without creds it saves to a local JSON draft (fine for building / sandbox).
Set METRIC_REQUEST_LOCAL_ONLY=1 to force the local-draft sandbox.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.office_onboarding import schema as S, store  # noqa: E402
from automations.office_onboarding import request_notify        # noqa: E402

st.set_page_config(page_title="Request Your Office Metrics", page_icon="📊",
                   layout="centered")


# --------------------------------------------------------------------------
def _build_gs_client():
    if os.environ.get("METRIC_REQUEST_LOCAL_ONLY") == "1":
        return None
    try:
        import gspread
    except Exception:
        return None
    try:
        sa = st.secrets.get("gcp_service_account")
    except Exception:
        sa = None
    if sa:
        return gspread.service_account_from_dict(dict(sa))
    try:
        o = st.secrets.get("gcp_oauth")
    except Exception:
        o = None
    if not o:
        tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
        if tok.exists():
            import json
            o = json.loads(tok.read_text())
    if o:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=o.get("token"), refresh_token=o.get("refresh_token"),
            token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=o.get("client_id"), client_secret=o.get("client_secret"),
            scopes=list(o.get("scopes") or
                        ["https://www.googleapis.com/auth/spreadsheets"]))
        return gspread.authorize(creds)
    return None


def _inject_client() -> None:
    gc = _build_gs_client()
    if gc is not None:
        store.set_client(gc)


def _inject_slack_token() -> None:
    """On Streamlit Cloud there's no token file or SLACK_USER_TOKEN env var, so the
    corrections ping can't post. If a `slack_user_token` secret is set, export it as
    the env var the shared Slack poster reads (slack_metrics_post._load_token).
    Best-effort — absent secret just means no ping (the request still saves)."""
    try:
        tok = st.secrets.get("slack_user_token")
    except Exception:                                # noqa: BLE001
        tok = None
    if tok and not os.environ.get("SLACK_USER_TOKEN"):
        os.environ["SLACK_USER_TOKEN"] = str(tok).strip()


# --------------------------------------------------------------------------
def form_view() -> None:
    st.markdown("## 📊 Request your office metrics")
    st.caption("Tell us what you'd like to see in your Slack every morning. "
               "Pick your campaign and check the metrics you want — "
               "we'll set up the rest and get them posting for you.")

    # ---- 1. Campaign -------------------------------------------------------
    st.divider()
    st.markdown("### 1. What campaign are you in?")
    camp_label = st.radio(
        "Choose one:", [c[1] for c in S.CAMPAIGNS],
        help="Your campaign decides which metrics exist for your office — "
             "you'll only be offered the ones we can actually pull for you.")
    campaign = next(c[0] for c in S.CAMPAIGNS if c[1] == camp_label)
    family = S.CAMPAIGNS_BY_KEY[campaign][2]

    fam_reports = S.campaign_reports(campaign)

    # ---- 2. Who you are ---------------------------------------------------
    st.divider()
    st.markdown("### 2. About your office")
    owner = st.text_input(
        "Your name (the office owner) *",
        help="However your name normally appears on our reports.")
    c1, c2 = st.columns(2)
    with c1:
        business = st.text_input("Company / office name *",
                                 placeholder="e.g. Alphalete")
    with c2:
        website = st.text_input("Website *", placeholder="https://…",
                                help="Your office's site — we use it to brand your "
                                     "pay-structure page automatically.")
    owner_email = st.text_input(
        "Your email *",
        help="We'll send you a welcome + how to set your commission payouts.")

    # ---- 3. Channels & what goes in each ----------------------------------
    st.divider()
    st.markdown("### 3. Where should we post — and what goes where?")
    st.caption("Add a channel and check the metrics you want in THAT channel. Most "
               "offices use one channel for everything — but you can add more and "
               "send, say, only Canceled Orders to a leaders channel.")
    st.warning("**Important:** add **Megan Hidalgo** to every channel below — we "
               "can't post to a channel she isn't in.")

    n_chan = int(st.number_input(
        "How many Slack channels do you want to post in?",
        min_value=1, max_value=8, value=1, step=1, key="_chan_count",
        help="Most offices use 1. Pick more only if you want different metrics in "
             "different channels (e.g. a leaders channel that gets only cancels)."))
    plans: list = []
    for i in range(n_chan):
        with st.container(border=True):
            cname = st.text_input(
                (f"Channel {i + 1}" if n_chan > 1 else "Channel") + " *",
                key=f"chan_name_{i}", placeholder="#your-office-sales")
            st.caption("Metrics to post in this channel:")
            keys_here: list = []
            for rk in fam_reports:
                st.session_state.setdefault(f"chan_met_{i}_{rk.key}", rk.default_on)
                on = st.checkbox(rk.label, key=f"chan_met_{i}_{rk.key}")
                if rk.blurb and i == 0:
                    st.caption(rk.blurb)
                if on:
                    keys_here.append(rk.key)
            plans.append(S.ChannelPlan(channel_name=cname.strip(),
                                       report_keys=keys_here))

    with st.expander("Optional: Ownerville account number"):
        ov_account = st.text_input(
            "Ownerville account number (optional)",
            help="If you know your Ownerville account number, it helps us match "
                 "your office. Leave blank if you're not sure.")

    # ---- build + submit ---------------------------------------------------
    st.divider()
    named_plans = [p for p in plans if p.channel_name]
    channels = [p.channel_name for p in named_plans]
    # union of every metric asked for across all channels, in report order
    union = [rk.key for rk in fam_reports
             if any(rk.key in p.report_keys for p in named_plans)]
    enrolled = [S.EnrolledReport(key=k, order=idx + 1)
                for idx, k in enumerate(union)]
    rec = S.OnboardingRecord(
        key=S.slug_from_owner(owner), owner=owner.strip(),
        knocks_office=owner.strip(),
        business_name=business.strip(), website=website.strip(),
        channel_id="", channel_name=(channels[0] if channels else ""),
        sheet_id="", family=family, channels=channels,
        channel_plans=named_plans, ov_account=ov_account.strip(),
        owner_email=owner_email.strip(), pay_code="",
        reports=enrolled, campaign=campaign)

    if st.button("📨 Send my request", type="primary"):
        problems = S.validate_request(rec)
        if problems:
            st.error("Almost there — please fix these:")
            for p in problems:
                st.markdown(f"- {p}")
            return
        rec.submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        rec.submitted_by = rec.owner or "owner"
        try:
            where = store.save_request(rec)
        except Exception as e:  # noqa: BLE001
            st.error(f"Sorry — couldn't send that ({e}). Please try again.")
            return
        alerted = (False, "")
        if where == "sheet":
            alerted = request_notify.notify(rec)
        summary = []
        for p in named_plans:
            labels = [S.REPORTS_BY_KEY[k].label for k in p.report_keys
                      if k in S.REPORTS_BY_KEY]
            summary.append((p.channel_name, labels))
        st.session_state["_req_done"] = {
            "owner": rec.owner, "business": rec.business_name,
            "summary": summary, "where": where, "alerted": alerted}
        st.rerun()


def _done_view() -> None:
    d = st.session_state["_req_done"]
    st.markdown("## ✅ Request sent!")
    first = d["owner"].split()[0] if d["owner"] else "there"
    n_ch = len(d.get("summary") or [])
    st.success(f"Thanks, {first}! We got your request for "
               f"**{n_ch} channel{'s' if n_ch != 1 else ''}**.")
    for cname, labels in (d.get("summary") or []):
        st.markdown(f"**{cname}** — {', '.join(labels) if labels else '(no metrics)'}")
    st.markdown(
        "\nHere's what happens next:\n"
        "1. Our team sets up your office's report sheet and wires it in.\n"
        "2. Your metrics start posting to your Slack channel(s) every morning.\n"
        "3. You'll get a welcome email with how to set your commission payouts.\n\n"
        "One reminder: make sure **Megan Hidalgo** is added to each **Slack** "
        "channel above. You don't need to do anything else. 🎉")
    if d["where"] == "sheet" and not d["alerted"][0]:
        # Owner-facing reassurance + a diagnostic line for the team, shown only on a
        # ping failure (the request still saved to the tab).
        st.caption("(Saved — our team will pick it up.)")
        st.caption("⚙️ team note: notification didn't send — {}".format(
            d["alerted"][1]))
    if st.button("Send another request"):
        for k in list(st.session_state.keys()):
            if isinstance(k, str) and (k.startswith("chan_") or k in ("_chan_count", "_req_done")):
                del st.session_state[k]
        st.rerun()


# --------------------------------------------------------------------------
_inject_client()
_inject_slack_token()
if st.session_state.get("_req_done"):
    _done_view()
else:
    form_view()
