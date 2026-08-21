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

# Drag-and-drop ordering (same component the tracker sign-up + Thread Builder
# use). Fall back to catalog order if the deploy doesn't have it installed.
try:
    from streamlit_sortables import sort_items
    _HAS_SORT = True
except Exception:                                    # noqa: BLE001
    _HAS_SORT = False

st.set_page_config(page_title="Alphalete Reporting by Lucy", page_icon="📊",
                   layout="centered")

PREVIEW_DIR = Path(__file__).resolve().parent / "previews"
SLACK_ID_IMG = Path(__file__).resolve().parent / "slack_id_help.png"


def _preview_path(campaign: str, report_key: str) -> "Path | None":
    """Preview image for a metric — campaign-specific file first (the same
    report can look different per campaign, e.g. the NDS order log board vs
    the fiber xlsx), then the generic one. None = no expander shown."""
    for name in (f"{campaign}_{report_key}.png", f"{report_key}.png"):
        p = PREVIEW_DIR / name
        if p.exists():
            return p
    return None


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
    st.markdown("## 📊 Alphalete Reporting by Lucy")
    st.markdown("### Daily Office Metrics Sign-Up")
    st.caption("Tell us what you'd like to see in your Slack every morning. "
               "Pick your campaign and check the metrics you want — "
               "we'll set up the rest and get them posting for you.")

    # ---- 1. Campaign -------------------------------------------------------
    st.divider()
    st.markdown("### 1. What campaign are you in?")
    # No default on purpose (Megan 2026-08-20): the owner must actually read
    # and pick — the metric menu doesn't exist until they do.
    camp_label = st.radio(
        "Choose one:", [c[1] for c in S.CAMPAIGNS], index=None,
        help="Your campaign decides which metrics exist for your office — "
             "you'll only be offered the ones we can actually pull for you.")
    campaign = next((c[0] for c in S.CAMPAIGNS if c[1] == camp_label), None)
    family = S.CAMPAIGNS_BY_KEY[campaign][2] if campaign else ""
    fam_reports = S.campaign_reports(campaign) if campaign else []

    # ---- 2. Who you are ---------------------------------------------------
    st.divider()
    st.markdown("### 2. About your office")
    requested_by = st.text_input(
        "Your name (what you go by) *",
        help="Just what we should call you — the official OwnerVille "
             "spelling goes in the next box.")
    owner = st.text_input(
        "ICD Name as it appears in OwnerVille *",
        help="JUST your name, spelled the way OwnerVille spells it — no "
             "company name.")
    ov_account = st.text_input(
        "OwnerVille account number *",
        help="The number on your OwnerVille account (e.g. 22583). This is "
             "how we match your office exactly — names vary, the number "
             "doesn't.")
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
    if not campaign:
        st.info("👆 Pick your campaign in step 1 to see the metrics we can "
                "post for you.")
        return
    st.markdown("### 3. Where should we post — and what goes where?")
    st.caption("Check what each channel gets. Most offices use one channel "
               "for everything. If you want certain metrics going somewhere "
               "else too — like a leaders-only channel — add a second "
               "channel and check just those.")
    st.info("**Important:** **Megan Hidalgo** must be added to **EACH** Slack "
            "channel you want the metrics posted in — she'll add Lucy (the "
            "bot that posts them) from there.")

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
            cid = st.text_input(
                "Slack Channel ID *", placeholder="C0ABC12DE",
                key=f"chan_id_{i}",
                help="This is a CODE (letters + numbers) that starts with C — "
                     "NOT the channel's name. To find it: in Slack, click the "
                     "channel's name at the top of the screen, scroll to the "
                     "very bottom of the pop-up, and copy the Channel ID "
                     "shown there.")
            if i == 0 and SLACK_ID_IMG.exists():
                with st.expander("Where do I find my Channel ID?"):
                    st.caption("In Slack, click the channel's name at the top "
                               "of the screen, scroll to the bottom of the "
                               "pop-up, and copy the Channel ID:")
                    # 397 = half the source's 794px — pixel-perfect on retina
                    # screens. Bigger = the browser upscales, it goes soft.
                    st.image(str(SLACK_ID_IMG), use_container_width=True)
            st.caption("Metrics to post in this channel:")
            keys_here: list = []
            for rk in fam_reports:
                st.session_state.setdefault(f"chan_met_{i}_{rk.key}", rk.default_on)
                on = st.checkbox(rk.label, key=f"chan_met_{i}_{rk.key}")
                if rk.blurb and i == 0:
                    st.caption(rk.blurb)
                # previews once, in the first channel's list — same metrics.
                if i == 0:
                    pv = _preview_path(campaign, rk.key)
                    if pv is not None:
                        with st.expander("View preview"):
                            st.image(str(pv), use_container_width=True)
                if on:
                    keys_here.append(rk.key)
            plans.append(S.ChannelPlan(channel_name=cname.strip(),
                                       report_keys=keys_here,
                                       channel_id=cid.strip()))

    # ---- 4. Posting order (drag & drop) -----------------------------------
    st.divider()
    st.markdown("### 4. Put them in order")
    labels = {rk.key: rk.label for rk in fam_reports}
    rev = {v: k for k, v in labels.items()}
    # union of every metric asked for across all channels, in report order
    picked_union = [rk.key for rk in fam_reports
                    if any(rk.key in p.report_keys for p in plans)]
    if picked_union and _HAS_SORT:
        st.caption("This is the order the metrics will post in each morning, "
                   "in every channel — drag to rearrange, top posts first. "
                   "If a metric isn't checked in one of your channels, that "
                   "channel simply skips it; the rest still post in this "
                   "order.")
        # key includes the picked set so the drag list rebuilds when it changes
        sorted_labels = sort_items(
            [labels[k] for k in picked_union], direction="vertical",
            key="met_order_" + "_".join(sorted(picked_union)))
        picked_union = [rev[l] for l in sorted_labels if l in rev]
    elif not picked_union:
        st.caption("Check some metrics above and they'll show up here for "
                   "you to drag into order.")

    # ---- build + submit ---------------------------------------------------
    st.divider()
    named_plans = [p for p in plans if p.channel_name]
    channels = [p.channel_name for p in named_plans]
    union = [k for k in picked_union
             if any(k in p.report_keys for p in named_plans)]
    enrolled = [S.EnrolledReport(key=k, order=idx + 1)
                for idx, k in enumerate(union)]
    rec = S.OnboardingRecord(
        key=S.slug_from_owner(owner), owner=owner.strip(),
        knocks_office=owner.strip(),
        business_name=business.strip(), website=website.strip(),
        channel_id=(named_plans[0].channel_id if named_plans else ""),
        channel_name=(channels[0] if channels else ""),
        sheet_id="", family=family, channels=channels,
        channel_plans=named_plans, ov_account=ov_account.strip(),
        owner_email=owner_email.strip(), pay_code="",
        reports=enrolled, campaign=campaign)

    st.info("🔔 **Reminder:** add **Megan Hidalgo** to each Slack channel you "
            "listed above **BEFORE HITTING SUBMIT** — we can't start your "
            "posting without it!")
    # The button stays OFF until every required field is filled, with a live
    # list of what's still needed — same gate as the tracker sign-up.
    missing: list = []
    if not requested_by.strip():
        missing.append("your name")
    if not owner.strip():
        missing.append("your OwnerVille name")
    if not ov_account.strip():
        missing.append("your OwnerVille account number")
    if not business.strip():
        missing.append("company / office name")
    if not website.strip():
        missing.append("website")
    if not owner_email.strip():
        missing.append("your email")
    for i, p in enumerate(plans):
        tag = "" if len(plans) == 1 else f" (channel {i + 1})"
        if not p.channel_name:
            missing.append(f"Slack channel name{tag}")
        if not p.channel_id:
            missing.append(f"Slack Channel ID{tag}")
        if not p.report_keys:
            missing.append(f"at least one metric{tag}")
    if missing:
        st.warning("⚠️ **Still needed before you can submit:** "
                   + ", ".join(missing) + ".")
    if st.button("📨 Send my sign-up to Megan", type="primary",
                 disabled=bool(missing)):
        problems = S.validate_request(rec)
        if problems:
            st.error("Almost there — please fix these:")
            for p in problems:
                st.markdown(f"- {p}")
            return
        rec.submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        rec.submitted_by = requested_by.strip() or rec.owner or "owner"
        # Live "is Lucy in this channel" check per channel (same helper the
        # tracker form uses) — surfaced in Megan's ping + the confirmation
        # page, so a stale/uninvited channel is caught at sign-up, not on the
        # first 4am run (the drew lesson).
        try:
            from automations.tracker_onboarding import slack_check
            lucy_all = [slack_check.check_channel(p.channel_id, p.channel_name)
                        for p in named_plans]
        except Exception:                            # noqa: BLE001
            lucy_all = []
        for j, p in enumerate(named_plans):
            if (not p.channel_id and j < len(lucy_all)
                    and lucy_all[j].get("channel_id")):
                p.channel_id = lucy_all[j]["channel_id"]
        if named_plans and not rec.channel_id:
            rec.channel_id = named_plans[0].channel_id
        try:
            where = store.save_request(rec)
        except Exception as e:  # noqa: BLE001
            st.error(f"Sorry — couldn't send that ({e}). Please try again.")
            return
        alerted = (False, "")
        if where == "sheet":
            alerted = request_notify.notify(rec, lucy=lucy_all)
        summary = []
        for p in named_plans:
            labels = [S.REPORTS_BY_KEY[k].label for k in p.report_keys
                      if k in S.REPORTS_BY_KEY]
            summary.append((p.channel_name, labels))
        st.session_state["_req_done"] = {
            "owner": rec.owner, "business": rec.business_name,
            "goes_by": requested_by.strip(), "lucy": lucy_all,
            "summary": summary, "where": where, "alerted": alerted}
        st.rerun()


def _done_view() -> None:
    d = st.session_state["_req_done"]
    st.markdown("## ✅ Request sent!")
    goes_by = d.get("goes_by") or d.get("owner") or "there"
    first = goes_by.split()[0]
    n_ch = len(d.get("summary") or [])
    st.success(f"Thanks, {first}! We got your request for "
               f"**{n_ch} channel{'s' if n_ch != 1 else ''}**.")
    for cname, labels in (d.get("summary") or []):
        st.markdown(f"**{cname}** will get, every morning:")
        st.markdown("\n".join(f"- {l}" for l in labels) or "- (no metrics)")
    _missing = [r for r in (d.get("lucy") or [])
                if r.get("status") in ("not_member", "not_found")]
    if _missing:
        _chs = " and ".join(f"**{r.get('channel_name') or 'your channel'}**"
                            for r in _missing)
        st.warning(f"⚠️ One thing: Lucy isn't in {_chs} yet. Make sure "
                   "**Megan Hidalgo** is added — she'll add Lucy and get "
                   "your metrics posting.")
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


# --------------------------------------------------------------------------
_inject_client()
_inject_slack_token()
if st.session_state.get("_req_done"):
    _done_view()
else:
    form_view()
