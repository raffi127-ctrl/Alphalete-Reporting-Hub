"""Metrics Onboarding — Megan's one-form tool to add a new office to metrics
posting and drive wiring it into the right report family on the right machine.

This is FOR MEGAN (not ICDs), so the form is dense and honest rather than
7-year-old-simple: it shows the derived machine (Lucy 1 / Lucy 2), the report id,
and exactly what the apply step will wire, so she can sanity-check before it runs.

Flow:
  code gate → fill the office once → submit writes the config to the 'Office
  Onboarding' tab of the AUTOMATION MASTER sheet (the source of truth) → the page
  shows the wiring plan + the one command to materialize it into the registries.

Run locally:   .venv/bin/streamlit run office_onboarding/app.py
On the web:    deploy this repo to Streamlit Community Cloud with
               office_onboarding/app.py as the entry point.

No access-code gate — it's an internal Megan/Eve tool.

Secrets (Streamlit Cloud, or .streamlit/secrets.toml locally):
  [gcp_service_account] / [gcp_oauth]   # Google creds for the master sheet
Without creds the form still runs and saves to a local JSON (fine for building /
sandbox — it never touches the live master sheet until creds are present).
"""
from __future__ import annotations

import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.office_onboarding import schema as S, store  # noqa: E402

# Drag-and-drop posting order (same component the ICD request form + tracker
# sign-up use). Fall back to checkbox order if the deploy doesn't have it.
try:
    from streamlit_sortables import sort_items
    _HAS_SORT = True
except Exception:                                    # noqa: BLE001
    _HAS_SORT = False

st.set_page_config(page_title="Metrics Onboarding", page_icon="🏢",
                   layout="centered")


# --------------------------------------------------------------------------
# Google client (only needed to write the live master sheet; absent = local JSON)
# --------------------------------------------------------------------------
def _build_gs_client():
    if os.environ.get("OFFICE_ONBOARDING_LOCAL_ONLY") == "1":
        return None                    # sandbox: save to local JSON, never the sheet
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


def _inject_gs_client() -> None:
    """Share one client with BOTH stores: office_onboarding (the Office Onboarding
    tab) and pay_structure (the Pay Structure Codes tab) — both live in the same
    AUTOMATION MASTER sheet, so onboarding can register the office's pay code."""
    gc = _build_gs_client()
    if gc is None:
        return
    store.set_client(gc)
    try:
        os.environ.setdefault("PAY_STRUCTURE_SHEET_ID", store.MASTER_SHEET_ID)
        from automations.pay_structure import store as _ps
        _ps.set_client(gc)
    except Exception:
        pass
    # Thread Builder admin edits share the same master sheet ('Thread Plans' tab).
    try:
        from automations.thread_builder import store as _tbs
        _tbs.set_client(gc)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Email (Pay Structure invite) — sends only when [smtp] secrets are configured.
# --------------------------------------------------------------------------
def _smtp():
    try:
        return st.secrets.get("smtp")
    except Exception:
        return None


def send_pay_invite(to_addr: str, subject: str, html: str) -> "tuple":
    """Send the HTML invite from the team address; cc the team so there's a copy
    (mirrors Megan's 'to owner … Alphalete'). Returns (ok, note)."""
    s = _smtp()
    pw = (s or {}).get("password", "")
    if not s or not pw or pw.startswith("PASTE"):
        return False, "email isn't configured (add [smtp] secrets to send)"
    if not to_addr or "@" not in to_addr:
        return False, "no owner email to send to"
    cc = [a for a in [(s or {}).get("team"), S.EVE_EMAIL] if a and a != to_addr]
    msg = EmailMessage()
    msg["From"] = s.get("from", s["user"])
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = ", ".join(dict.fromkeys(cc))
    msg["Subject"] = subject
    msg.set_content(f"Set your office's payouts: open {S.PAY_STRUCTURE_URL} "
                    "and enter your code (see the HTML version of this email).")
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(s["host"], int(s.get("port", 587)), timeout=60) as srv:
            srv.starttls()
            srv.login(s["user"], s["password"])
            srv.send_message(msg)
        return True, ", ".join([to_addr] + cc)
    except Exception as e:                           # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def register_pay_code(rec) -> "tuple":
    """Pre-stage the office's Pay Structure code in the codes tab (load-merge-save
    so other offices aren't clobbered). It resolves for the owner once the office
    is wired (apply + commit → Pay Structure redeploys). Returns (ok, note)."""
    try:
        from automations.pay_structure import store as _ps, offices as _po
    except Exception as e:                           # noqa: BLE001
        return False, f"pay_structure import failed: {e}"
    try:
        codes = dict(_ps.load_codes() or {})
    except Exception:
        codes = {}
    codes[rec.key] = rec.pay_code
    business = {}
    try:
        for k in _po.ORDER:
            business[k] = _po.get(k).business_name
    except Exception:
        pass
    business[rec.key] = rec.business_name
    order = list(dict.fromkeys(list(codes.keys())))
    try:
        _ps.save_codes(codes, business, order)
        return True, ""
    except Exception as e:                           # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _machine_badge(machine: str) -> str:
    color = "#2563EB" if machine == "Lucy 1" else "#7C3AED"
    return (f"<span style='background:{color};color:white;padding:2px 10px;"
            f"border-radius:12px;font-weight:700;font-size:.95rem'>{machine}</span>")


def _enqueue_onboard(key: str, machine: str, *, post: bool) -> "tuple":
    """Drop a mini_control `onboard_apply metrics <key>` job on `machine`'s queue
    (Lucy 1 for D2D, Lucy 2 for B2B) so the office wires (apply --write → joins the
    morning run) and, with --post, posts to its channel now. Reuses the form's own
    Sheets client (the queue is a tab on this same master sheet). Returns (ok, note)."""
    gc = store.get_client()
    if gc is None:
        return False, "no Sheets client (local-draft mode)"
    try:
        from automations.day_orchestrator import queue_enqueue as qenq
        args = f"metrics {key}" + (" --post" if post else "")
        tab = qenq.enqueue(gc, "onboard_apply", args, by="Megan", machine=machine)
        return True, tab
    except Exception as e:                           # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------
def _pending_requests() -> "list":
    """Owner requests still waiting to be finalized (status 'new'), newest first."""
    try:
        reqs = store.load_requests(status="new")
    except Exception:                                # noqa: BLE001
        return []
    return list(reversed(reqs))


def _seed_from_request(d: dict) -> None:
    """Pre-fill every form widget from an owner's request dict. Seeds session_state
    for the keyed widgets (before they render) so Megan opens the form already
    filled with what the owner asked for — she only adds the Google Sheet + finalizes.
    """
    r = store.record_from_json(d)
    ss = st.session_state
    _camp = r.campaign or ("fiber_d2d" if r.family == "d2d" else "b2b_att")
    ss["on_campaign"] = S.CAMPAIGNS_BY_KEY.get(_camp, S.CAMPAIGNS[0])[1]
    ss["on_owner"] = r.owner
    ss["on_ov"] = r.ov_account
    ss["on_owner_office"] = r.owner_office
    # Always show the OwnerVille spelling Megan's side needs to verify — the
    # owner form collects it as `owner`, so equal values are the GOOD case,
    # not an omission (Megan 2026-08-20: it must fill here).
    ss["on_knocks"] = r.knocks_office or r.owner
    ss["on_business"] = r.business_name
    ss["on_website"] = r.website
    ss["on_channel_id"] = r.channel_id
    ss["on_channel_name"] = r.channel_name
    # Per-channel plan the owner asked for. Carry the full spec (name, metric keys,
    # labels, any owner-given id) so the Slack section can show the fan-out AND
    # collect a channel_id per channel — the runner needs an id for each to fan out.
    ss["_req_channel_plans"] = [
        {"channel_name": p.channel_name, "channel_id": p.channel_id,
         "report_keys": list(p.report_keys),
         "labels": [S.REPORTS_BY_KEY[k].label for k in p.report_keys
                    if k in S.REPORTS_BY_KEY]}
        for p in (r.channel_plans or [])]
    for i, p in enumerate(r.channel_plans or []):
        ss[f"chanid_{i}"] = p.channel_id
    ss["on_header"] = r.header_label
    ss["on_owner_email"] = r.owner_email
    ss["on_customid"] = False
    ss["on_key"] = r.key
    ss["on_sheet"] = ""                      # owner never gives this — Megan adds it
    ss.pop("on_pay_code", None)              # regen from the business name
    # Reports: check exactly what the owner asked for, in their order.
    wanted = {er.key: er.order for er in r.reports}
    for rk in S.REPORTS:
        if rk.family != r.family:
            continue
        ss[f"rep_{rk.key}"] = rk.key in wanted
        if rk.key in wanted:
            ss[f"ord_{rk.key}"] = int(wanted[rk.key])
    ss["_from_request_key"] = r.key




def form_view() -> None:
    st.markdown("## 🏢 Metrics Onboarding")
    st.caption("Add a new office to daily metrics posting. Fill it in once; on "
               "submit this writes the office's config to the **Office "
               "Onboarding** tab (the source of truth the reports + Hub read "
               "from) and shows you exactly how it wires — which machine runs it "
               "and what to apply.")

    # ---- 0. Start from an owner request ----------------------------------
    # Owners submit a partial request (program + metrics + who/where) on the
    # request form; pick one here to pre-fill everything they gave. You then just
    # create their Google Sheet and finalize.
    reqs = _pending_requests()
    # Deep link from the corrections ping: ?request=<key> opens straight onto that
    # owner's request, pre-filled. Seed once (guarded by _prefilled_idx).
    try:
        _qp_req = str(st.query_params.get("request", "")).strip()
    except Exception:                                # noqa: BLE001
        _qp_req = ""
    if _qp_req and reqs and st.session_state.get("_prefilled_idx") != _qp_req:
        for _j, _d in enumerate(reqs):
            if _d.get("key") == _qp_req:
                _seed_from_request(_d)
                st.session_state["_prefilled_idx"] = _qp_req
                st.session_state["_req_pick"] = _j + 1
                st.rerun()
    if reqs:
        st.divider()
        st.markdown("### ⬇️ Start from an owner request")
        opts = ["— none (fill from scratch) —"] + [
            "{} · {} [{}] — wants {} metric{}".format(
                d.get("owner") or d.get("key"), d.get("business_name") or "—",
                (d.get("family") or "").upper(), len(d.get("reports") or []),
                "" if len(d.get("reports") or []) == 1 else "s")
            for d in reqs]
        idx = st.selectbox("An office owner asked for these — pick one to pre-fill:",
                           range(len(opts)), format_func=lambda i: opts[i],
                           key="_req_pick")
        if idx > 0 and st.session_state.get("_prefilled_idx") != reqs[idx - 1].get("key"):
            _seed_from_request(reqs[idx - 1])
            st.session_state["_prefilled_idx"] = reqs[idx - 1].get("key")
            st.rerun()
        if idx > 0:
            st.success("Pre-filled from {}'s request. Add their Google Sheet below, "
                       "review, and submit.".format(
                           reqs[idx - 1].get("owner") or reqs[idx - 1].get("key")))

    # ---- 1. Campaign ------------------------------------------------------
    st.divider()
    st.markdown("### 1. Campaign")
    st.session_state.setdefault("on_campaign", S.CAMPAIGNS[0][1])
    camp_label = st.radio(
        "Which campaign does this office run?",
        [c[1] for c in S.CAMPAIGNS], key="on_campaign",
        help="Sets the metric menu, the report runner and the machine — D2D "
             "campaigns run on Lucy 1, B2B on Lucy 2. Almost every office "
             "just uses the shared team views; only add a per-office saved "
             "view under Advanced if one is truly needed.")
    campaign = next(c[0] for c in S.CAMPAIGNS if c[1] == camp_label)
    family = S.CAMPAIGNS_BY_KEY[campaign][2]

    # ---- 2. Office identity ----------------------------------------------
    st.divider()
    st.markdown("### 2. Office & owner")
    owner = st.text_input(
        "Canonical owner name *", key="on_owner",
        help="Exactly as the ICD Aliases sheet / roster spells it — this filters "
             "every owner-sliced metric. Fix spelling in the alias sheet, not here.")
    c1, c2 = st.columns(2)
    with c1:
        ov_account = st.text_input(
            "Ownerville account number", key="on_ov",
            help="The office's Ownerville account number, for cross-referencing / "
                 "impersonation. Note: it isn't guaranteed to match the AppStream "
                 "office id, so it's stored separately.")
    with c2:
        knocks = st.text_input(
            "Name as it appears in Ownerville", key="on_knocks",
            help="The office's name in ownerville for the Telemapper Knocks "
                 "scrape, IF it differs from the canonical owner. Blank = same "
                 "as owner.")
    c3, c4 = st.columns(2)
    with c3:
        business = st.text_input("Company name *", key="on_business",
                                help="The office's own brand, e.g. 'Alphalete'.")
    with c4:
        website = st.text_input(
            "Website", key="on_website",
            help="Their site — Pay Structure auto-pulls the logo + brand color "
                 "from it, so the office's editor is branded on first login.")

    # B2B ONLY: the exact "Owner & Office" value Tableau uses to slice churn +
    # activation. Without it those sections come back EMPTY for the office, so it's
    # required for B2B. Free-text (not derived) because it must match Tableau
    # character-for-character (case, brackets, punctuation).
    owner_office = ""
    if family == "b2b":
        # Pick from the REAL Tableau "Owner & Office" values (cached to the
        # "Tableau Owners" tab by the daily Box pull) so a wrong string can't
        # silently blank churn + activation — the jamis MIDSPIRE-vs-JAMIS-GARAY
        # trap (2026-08-01). Free-text stays as a guided fallback for an owner not
        # in the cache yet.
        try:
            from automations.office_onboarding import tableau_owners
            _known = tableau_owners.known_owners()
        except Exception:  # noqa: BLE001 — no cache = fall back to free-text
            _known = []
        _prefill = (st.session_state.get("on_owner_office", "") or "").strip()
        _TYPE_IT = "➕ Not listed — type it exactly as Tableau shows"
        if _known:
            _opts = [""] + _known + [_TYPE_IT]
            _idx = (_opts.index(_prefill) if _prefill in _known
                    else (_opts.index(_TYPE_IT) if _prefill else 0))
            _pick = st.selectbox(
                "Owner & Office (Tableau) *", options=_opts, index=_idx,
                key="on_owner_office_pick",
                help="Pick the owner exactly as Tableau's 'Owner & Office' filter "
                     "spells it — B2B churn + activation slice on this, and a wrong "
                     "value silently returns EMPTY. Not in the list? choose the last "
                     "option and type it.")
            if _pick == _TYPE_IT:
                owner_office = st.text_input(
                    "Type the exact 'Owner & Office' value *", key="on_owner_office",
                    placeholder="ATEF CHOUDHURY [domin8 acquisitions, inc.]",
                    help="In Tableau open any B2B board's 'Owner & Office' filter and "
                         "copy the value verbatim — case, brackets, commas and all.")
            else:
                owner_office = _pick
        else:
            owner_office = st.text_input(
                "Owner & Office (Tableau) *", key="on_owner_office",
                placeholder="ATEF CHOUDHURY [domin8 acquisitions, inc.]",
                help="Copy this EXACTLY as it appears in Tableau's 'Owner & Office' "
                     "filter — case, brackets and all. B2B churn + activation slice "
                     "on it; if it's off by a character those sections come back empty.")
        if not owner_office.strip():
            st.caption("⚠️ Required for B2B — churn + activation won't fill without it.")

    # Internal id — pure plumbing (the --office handle, the <id>_metrics schedule
    # entry, cache filenames). Auto-made from the owner's first name so Megan
    # never has to think about it; an override appears only if she wants one.
    key_default = S.slug_from_owner(owner)
    if st.checkbox("Set a custom internal id (rarely needed)", key="on_customid",
                   help="The internal id is auto-made from the owner's first name. "
                        "Only change it if another office already uses that id "
                        "(e.g. two owners share a first name)."):
        st.session_state.setdefault("on_key", key_default)
        key = st.text_input("Internal id", key="on_key").strip()
    else:
        key = key_default
        if owner.strip():
            st.caption(f"Internal id: `{key}` — auto-set from the owner's name "
                       "(used in commands + filenames).")

    # ---- 3. Slack channel -------------------------------------------------
    st.divider()
    st.markdown("### 3. Slack channel")
    c5, c6 = st.columns(2)
    with c5:
        channel_id = st.text_input("Channel ID *", placeholder="C0…", key="on_channel_id",
                                   help="The Slack channel id metrics post into. "
                                        "Right-click the channel → View channel "
                                        "details → the ID at the bottom.")
    with c6:
        channel_name = st.text_input("Channel name *", placeholder="#elevate-sales",
                                     key="on_channel_name")
    _plans = st.session_state.get("_req_channel_plans") or []
    if len(_plans) > 1:
        st.info("📣 **The owner asked for a per-channel fan-out.** Give each channel "
                "its Slack **Channel ID** below — the morning run posts each channel "
                "only its metrics. (Leave any ID blank and the office posts "
                "everything to the primary channel above until all IDs are set.)")
        for i, spec in enumerate(_plans):
            st.markdown("**{}** → {}".format(
                spec["channel_name"],
                ", ".join(spec["labels"]) if spec["labels"] else "(no metrics)"))
            st.text_input(f"Channel ID for {spec['channel_name']}", placeholder="C0…",
                          key=f"chanid_{i}",
                          help="Right-click the channel → View channel details → the "
                               "ID at the bottom.")
    # Live "is Lucy in the channel" check — the same helper the tracker
    # confirm view uses. A stale id / missing invite is the #1 wiring
    # firefight (drew), so surface it BEFORE Megan submits.
    if st.button("🔄 Check Lucy's membership"):
        from automations.tracker_onboarding import slack_check
        _pairs = [(channel_id.strip(), channel_name.strip())]
        for i, spec in enumerate(_plans):
            _pairs.append((
                (st.session_state.get(f"chanid_{i}") or "").strip(),
                spec.get("channel_name", "")))
        seen = set()
        st.session_state["_lucy_checks"] = [
            slack_check.check_channel(c, n) for c, n in _pairs
            if (c or n) and not ((c, n) in seen or seen.add((c, n)))]
    for _r in (st.session_state.get("_lucy_checks") or []):
        from automations.tracker_onboarding import slack_check as _sc
        (st.success if _r.get("status") == "member" else st.warning)(
            _sc.human_line(_r))

    header_label = st.text_input(
        "Thread name — only if another office shares this channel", key="on_header",
        help="Leave blank if this office has the channel to itself. If two "
             "offices post to the SAME channel (like Hammad + Salik → "
             "#elite-prime-sales), give this office a name here — it's added to "
             "the Metrics header so this office gets its OWN thread instead of "
             "merging into the other office's. Both offices sharing the channel "
             "must set one.")
    if header_label.strip():
        st.caption(f"→ This office's thread header will read "
                   f"**Metrics for: <date> — {header_label.strip()}** — the "
                   f"“— {header_label.strip()}” is what keeps it separate from "
                   f"the other office's thread in this channel.")

    # ---- 4. Google Sheet --------------------------------------------------
    st.divider()
    st.markdown("### 4. Office metrics Google Sheet")
    st.caption("This is the one thing the owner can't give — you create the sheet "
               "(duplicate the tabs below) and paste it here.")
    sheet_link = st.text_input(
        "Sheet link or ID *", key="on_sheet",
        help="The office's own metrics workbook — where the churn + ABP fills "
             "land. Paste the full URL or the bare id.")
    sheet_id = S.sheet_id_from(sheet_link)
    if sheet_link and sheet_id != sheet_link.strip():
        st.caption(f"→ sheet id: `{sheet_id}`")

    # One uniform setup for every campaign (Megan 2026-08-20): duplicate the
    # ENTIRE Master Metrics Templates workbook — it has every tab any campaign
    # needs; the morning runs write only this campaign's tabs and leave the
    # rest alone. No per-tab copying.
    st.markdown("**Duplicate the entire "
                f"[Master Metrics Templates workbook]({S.TEMPLATE_WORKBOOK_URL})** "
                "(File → Make a copy) — it has every tab any campaign needs. "
                "Rename the copy for this office and paste its link above.")
    tabs = S.needed_tabs(family,
                         [rk.key for rk in S.campaign_reports(campaign)])
    if tabs:
        st.caption("For this campaign the daily run will fill: "
                   + ", ".join(f"`{t['tab']}`" for t in tabs)
                   + " — the other tabs are simply left alone.")

    # ---- 5. Reports to enroll --------------------------------------------
    st.divider()
    st.markdown("### 5. Reports to enroll")
    st.caption("Check the metrics this office posts, then drag them into "
               "posting order below — top posts first.")
    fam_reports = S.campaign_reports(campaign)
    picked_kinds: list = []
    for i, rk in enumerate(fam_reports):
        st.session_state.setdefault(f"rep_{rk.key}", rk.default_on)
        # ord_ seeds still come in from an owner request pre-fill — they set
        # the INITIAL drag order below, so the owner's asked-for order sticks.
        st.session_state.setdefault(f"ord_{rk.key}", i + 1)
        if st.checkbox(rk.label, key=f"rep_{rk.key}"):
            picked_kinds.append(rk)
    picked_kinds.sort(key=lambda rk: int(st.session_state.get(f"ord_{rk.key}", 99)))

    if picked_kinds and _HAS_SORT:
        st.caption("This is the order they'll post in each morning — drag to "
                   "rearrange.")
        _labels = {rk.key: rk.label for rk in picked_kinds}
        _rev = {v: k for k, v in _labels.items()}
        # key includes the picked set so the drag list rebuilds when it changes
        _sorted = sort_items([_labels[rk.key] for rk in picked_kinds],
                             direction="vertical",
                             key="onb_order_" + "_".join(sorted(_labels)))
        _order_keys = [_rev[l] for l in _sorted if l in _rev]
    else:
        _order_keys = [rk.key for rk in picked_kinds]

    # Every office uses the shared team views (sliced to its owner), so the
    # machine is set by the campaign — D2D on Lucy 1, B2B on Lucy 2. No per-office
    # view picker: the only offices that ever needed their own view are the two
    # hardcoded B2B ones, which don't come through this form.
    enrolled = [S.EnrolledReport(key=k, order=i + 1)
                for i, k in enumerate(_order_keys)]

    # Box Order Log posts its OWN per-ICD thread from the team ALLEXP energy export,
    # sliced to this office's exact "Owner & Office" value (box_order_log.per_office).
    # It needs the Owner & Office field above to be exact — that's the slice.
    if any(er.key == "b2b_order_log_box" for er in enrolled):
        st.info("📦 **Box Order Log** posts as its own thread for this office, "
                "sliced to only its rows by the **Owner & Office** value above — so "
                "make sure that's exactly right (it's how Box finds this office's "
                "energy sales).")

    # ---- 6. Owner welcome email ------------------------------------------
    st.divider()
    st.markdown("### 6. Owner welcome email")
    st.caption("On submit, Lucy emails the owner a welcome to Lucy reporting + "
               "their Pay Structure code (so they can set their office's payouts). "
               "Uncheck to skip the send.")
    we1, we2 = st.columns([3, 2])
    with we1:
        owner_email = st.text_input(
            "Owner email", key="on_owner_email", help="Where the welcome email is sent.")
    with we2:
        st.session_state.setdefault("on_pay_code", S.gen_pay_code(business, key or ""))
        pay_code = st.text_input(
            "Pay Structure code", key="on_pay_code",
            help="Auto-made from the company name — edit if you want a cleaner "
                 "code. This is what the owner enters on the Pay Structure site.")
    send_welcome = st.checkbox(
        "✉️ Send the welcome email to the owner on submit", value=True,
        key="on_send_welcome")

    # ---- build the record -------------------------------------------------
    st.divider()
    # Rebuild the per-channel plans with the channel_ids Megan entered above, so the
    # fan-out can resolve. Falls back to the primary channel_id for the plan whose
    # name matches the primary channel (she already typed that id in section 3).
    built_plans = []
    for i, spec in enumerate(st.session_state.get("_req_channel_plans") or []):
        cid = (st.session_state.get(f"chanid_{i}", "") or "").strip()
        if not cid and spec["channel_name"] == channel_name.strip():
            cid = channel_id.strip()
        built_plans.append(S.ChannelPlan(
            channel_name=spec["channel_name"], report_keys=spec["report_keys"],
            channel_id=cid))
    rec = S.OnboardingRecord(
        key=(key or "").strip(), owner=owner.strip(),
        knocks_office=knocks.strip() or owner.strip(),
        business_name=business.strip(), website=website.strip(),
        channel_id=channel_id.strip(), channel_name=channel_name.strip(),
        sheet_id=sheet_id, family=family, campaign=campaign,
        channel_plans=built_plans,
        ov_account=ov_account.strip(), owner_office=owner_office.strip(),
        owner_email=owner_email.strip(), pay_code=pay_code.strip(),
        reports=enrolled, header_label=header_label.strip())

    # ---- submit -----------------------------------------------------------
    st.info("🔔 **Before you submit:** make sure the **Lucy user** AND the "
            "**Lucy bot** are both members of every Slack channel above — a "
            "private channel needs BOTH invited or the posts/uploads fail.")
    if st.button("💾 Submit office", type="primary"):
        reg = store.existing_registry(exclude_key=rec.key)
        problems = S.validate(
            rec, existing_channels=reg["channels"],
            existing_keys=reg["keys"], existing_views=reg["views"])
        if send_welcome and rec.owner_email and "@" not in rec.owner_email:
            problems.append("Owner email doesn't look valid (or uncheck 'Send the "
                            "welcome email').")
        if rec.family == "b2b" and not rec.owner_office.strip():
            problems.append("B2B needs the exact **Owner & Office** value (Tableau) "
                            "— churn + activation slice on it and come back empty "
                            "without it.")
        if problems:
            st.error("Fix these before submitting:")
            for p in problems:
                st.markdown(f"- {p}")
            return
        rec.submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        rec.submitted_by = "Megan"
        try:
            where = store.save(rec)
        except Exception as e:                       # noqa: BLE001
            st.error(f"Couldn't save: {e}")
            return
        # If this came from an owner request, mark it finalized so it drops off
        # the pending list (best-effort — never blocks the submit).
        from_req = st.session_state.get("_from_request_key")
        if from_req:
            try:
                store.mark_request_wired(from_req)
            except Exception:                        # noqa: BLE001
                pass
        result = {"rec": rec.to_json(), "where": where}
        # Auto-wire: hand the office's machine an apply job so it joins the morning
        # run with no manual apply/commit. Only when the submission hit the Sheet.
        if where == "sheet":
            result["wired"] = _enqueue_onboard(rec.key, rec.machine(), post=False)
        # Welcome email: pre-stage the pay code, then send.
        if send_welcome and rec.owner_email:
            code_ok, code_note = register_pay_code(rec)
            subject, html = S.welcome_email(rec.owner, rec.pay_code)
            sent_ok, sent_note = send_pay_invite(rec.owner_email, subject, html)
            result["welcome"] = {
                "sent": sent_ok, "note": sent_note, "code": rec.pay_code,
                "to": rec.owner_email, "code_ok": code_ok, "code_note": code_note}
        st.session_state["_last_submit"] = result
        st.rerun()

    _show_result()


def _show_result() -> None:
    res = st.session_state.get("_last_submit")
    if not res:
        return
    d = res["rec"]
    dv = d.get("_derived", {})
    st.divider()
    dest = ("the **Office Onboarding** tab" if res["where"] == "sheet"
            else "a **local draft file** (`output/office_onboarding_submissions.json`) "
                 "— no Google creds, so nothing was written to the live master sheet")
    st.success(f"Saved {d['key']} to {dest}.")
    st.markdown("#### Wiring plan")
    st.markdown(
        f"- Machine: {_machine_badge(dv.get('machine',''))}\n"
        f"- Registry: `{dv.get('runner_module','')}` office `{d['key']}` "
        f"→ {d['channel_name']}\n"
        f"- Schedule id: `{dv.get('report_id','')}` (P1 daily)\n"
        f"- Hub card **Office Daily Metrics** + **Pay Structure** pick this office "
        f"up automatically once applied (both read the registry).",
        unsafe_allow_html=True)
    if res["where"] == "sheet":
        wired_ok, wired_note = res.get("wired", (False, ""))
        machine = dv.get("machine", "Lucy 1")
        if wired_ok:
            st.success(f"✅ Auto-wiring into the morning run — {machine} is applying "
                       "it now (joins the 4am flow; live in ~1–2 min). No commands "
                       "to run.")
        else:
            st.warning(f"Saved to the Sheet, but couldn't auto-wire ({wired_note}). "
                       "Use the fallback command below.")
        st.markdown("#### Post it to the channel now")
        st.caption(f"Runs this office's metrics on {machine} and posts them to "
                   f"{d['channel_name']} immediately (otherwise they first appear "
                   "in tomorrow's 4am run).")
        if st.button(f"▶️ Post to {d['channel_name']} now", type="primary"):
            ok, note = _enqueue_onboard(d["key"], machine, post=True)
            if ok:
                st.success(f"Queued — {machine} will post to {d['channel_name']} in "
                           "~1–2 min. Watch the channel.")
            else:
                st.error(f"Couldn't queue the post: {note}")
        with st.expander("Prefer to run it by hand? (fallback command)"):
            st.code(f"python -m automations.office_onboarding.apply --only {d['key']} --write",
                    language="bash")
    else:
        st.markdown("#### Apply it")
        st.caption("No Google creds here, so it saved locally. Run this where the "
                   "repo lives, review `git diff`, then commit + push.")
        st.code(f"python -m automations.office_onboarding.apply --only {d['key']} --write",
                language="bash")

    # ---- welcome email outcome ----
    w = res.get("welcome")
    if w:
        st.markdown("#### Owner welcome email")
        if w["sent"]:
            st.success(f"✉️ Welcome email sent to {w['note']} — code **{w['code']}**.")
        else:
            st.warning(f"⚠️ Couldn't send the welcome email: {w['note']}. The code "
                       f"is **{w['code']}** — send it manually or add the [smtp] "
                       f"secrets and re-run.")
        if not w.get("code_ok"):
            st.caption(f"Pay code not pre-staged yet ({w.get('code_note','')}). It "
                       "registers once the office is wired + Pay Structure "
                       "redeploys — that's also when the code starts working.")
        else:
            st.caption("Pay code staged. It starts working for the owner once the "
                       "office is wired (apply + commit → Pay Structure redeploys).")
        subj, html = S.welcome_email(d.get("owner", ""), w["code"])
        with st.expander("Preview the email that was sent"):
            st.caption(f"Subject: {subj}")
            st.markdown(html, unsafe_allow_html=True)

    if st.button("Onboard another office"):
        _clear_form_state()
        del st.session_state["_last_submit"]
        st.rerun()


def _clear_form_state() -> None:
    """Wipe the keyed form widgets so the next office starts blank (the fields
    persist across reruns now that they're keyed)."""
    prefixes = ("on_", "rep_", "ord_", "chanid_")
    for k in [k for k in st.session_state
              if isinstance(k, str) and k.startswith(prefixes)]:
        del st.session_state[k]
    for k in ("_from_request_key", "_prefilled_idx", "_req_pick",
              "_req_channel_plans"):
        st.session_state.pop(k, None)


# --------------------------------------------------------------------------
# Thread Builder — password-gated admin editor for an ENROLLED office's thread
# (which sections post, and in what order). Edits save to the 'Thread Plans' tab
# and go live on the next morning sync (thread_builder.sync) — no deploy.
def _thread_admin_password():
    # Production: the app's secret. Fallback: a THREAD_ADMIN_PASSWORD env var for
    # local/dev preview (secret wins when both are set).
    try:
        val = st.secrets.get("thread_admin_password")
    except Exception:
        val = None
    return val or os.environ.get("THREAD_ADMIN_PASSWORD")


def thread_admin_view() -> None:
    st.subheader("✏️ Edit an enrolled office's thread")
    pw = _thread_admin_password()
    if not pw:
        st.warning("Admin editing is locked until a password is set. Add "
                   "`thread_admin_password = \"…\"` to the app's Secrets, then "
                   "reload.")
        return
    if not st.session_state.get("_thread_admin_ok"):
        entered = st.text_input("Admin password", type="password",
                                key="_thread_admin_pw")
        if not entered:
            st.stop()
        if entered != pw:
            st.error("Wrong password.")
            st.stop()
        st.session_state["_thread_admin_ok"] = True

    from automations.thread_builder.editor import SheetBackend, render_editor
    render_editor(SheetBackend(), by="admin")


# --------------------------------------------------------------------------
def _inject_slack_token() -> None:
    from automations.shared import onboarding_ui as _ui
    _ui.inject_slack_token()


_inject_gs_client()
_inject_slack_token()

_MODES = ("🏢 Enroll a new office", "✏️ Edit a thread (admin)")
# ?admin=1 (the Hub's Thread Builder button) opens straight into the editor.
try:
    _admin_q = str(st.query_params.get("admin", "")).lower() in ("1", "true", "yes")
except Exception:
    _admin_q = False
_mode = st.radio("What do you want to do?", _MODES, index=1 if _admin_q else 0,
                 horizontal=True)
st.write("---")
if _mode == _MODES[1]:
    thread_admin_view()
else:
    form_view()
