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


# --------------------------------------------------------------------------
def form_view() -> None:
    st.markdown("## 🏢 Metrics Onboarding")
    st.caption("Add a new office to daily metrics posting. Fill it in once; on "
               "submit this writes the office's config to the **Office "
               "Onboarding** tab (the source of truth the reports + Hub read "
               "from) and shows you exactly how it wires — which machine runs it "
               "and what to apply.")

    # ---- 1. Campaign ------------------------------------------------------
    st.divider()
    st.markdown("### 1. Campaign")
    fam_label = st.radio(
        "Which campaign does this office run?",
        ["D2D — Office Daily Metrics (Lucy 1)",
         "B2B — B2B Metrics (Lucy 2)"],
        help="Sets the report runner + which machine posts it — D2D runs on "
             "Lucy 1, B2B on Lucy 2. Almost every office just uses the shared "
             "team views; only add a per-office saved view under Advanced if one "
             "is truly needed.")
    family = "d2d" if fam_label.startswith("D2D") else "b2b"

    # ---- 2. Office identity ----------------------------------------------
    st.divider()
    st.markdown("### 2. Office & owner")
    owner = st.text_input(
        "Canonical owner name *",
        help="Exactly as the ICD Aliases sheet / roster spells it — this filters "
             "every owner-sliced metric. Fix spelling in the alias sheet, not here.")
    c1, c2 = st.columns(2)
    with c1:
        ov_account = st.text_input(
            "Ownerville account number",
            help="The office's Ownerville account number, for cross-referencing / "
                 "impersonation. Note: it isn't guaranteed to match the AppStream "
                 "office id, so it's stored separately.")
    with c2:
        knocks = st.text_input(
            "Name as it appears in Ownerville",
            help="The office's name in ownerville for the Telemapper Knocks "
                 "scrape, IF it differs from the canonical owner. Blank = same "
                 "as owner.")
    c3, c4 = st.columns(2)
    with c3:
        business = st.text_input("Company name *",
                                help="The office's own brand, e.g. 'Aeon'.")
    with c4:
        website = st.text_input(
            "Website",
            help="Their site — Pay Structure auto-pulls the logo + brand color "
                 "from it, so the office's editor is branded on first login.")

    # Internal id — pure plumbing (the --office handle, the <id>_metrics schedule
    # entry, cache filenames). Auto-made from the owner's first name so Megan
    # never has to think about it; an override appears only if she wants one.
    key_default = S.slug_from_owner(owner)
    if st.checkbox("Set a custom internal id (rarely needed)", value=False,
                   help="The internal id is auto-made from the owner's first name. "
                        "Only change it if another office already uses that id "
                        "(e.g. two owners share a first name)."):
        key = st.text_input("Internal id", value=key_default).strip()
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
        channel_id = st.text_input("Channel ID *", placeholder="C0…",
                                   help="The Slack channel id metrics post into. "
                                        "Right-click the channel → View channel "
                                        "details → the ID at the bottom.")
    with c6:
        channel_name = st.text_input("Channel name *", placeholder="#elevate-sales")
    header_label = st.text_input(
        "Thread name — only if another office shares this channel",
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
    sheet_link = st.text_input(
        "Sheet link or ID *",
        help="The office's own metrics workbook — where the churn + ABP fills "
             "land. Paste the full URL or the bare id.")
    sheet_id = S.sheet_id_from(sheet_link)
    if sheet_link and sheet_id != sheet_link.strip():
        st.caption(f"→ sheet id: `{sheet_id}`")

    # Which tabs the office's sheet must contain (only the reports that WRITE to
    # the sheet — the Slack-only metrics like order log / knocks post images and
    # need none). Duplicate each from the template workbook.
    tabs = S.needed_tabs(family)
    if tabs:
        st.markdown("**This office's sheet needs these tabs** — duplicate each "
                    f"from the [template workbook]({S.TEMPLATE_WORKBOOK_URL}):")
        for t in tabs:
            if t["template"]:
                st.markdown(f"- `{t['tab']}` — [copy this tab]({t['template']})")
            else:
                st.markdown(f"- `{t['tab']}`")

    # ---- 5. Reports to enroll --------------------------------------------
    st.divider()
    st.markdown("### 5. Reports to enroll")
    st.caption("Check the metrics this office posts. The number sets the order "
               "they appear in the thread (lower = earlier) — it's pre-filled, "
               "change it only if you want a different order.")
    fam_reports = [r for r in S.REPORTS if r.family == family]
    picked: list = []            # (ReportKind, order)
    for i, rk in enumerate(fam_reports):
        oc1, oc2 = st.columns([6, 1])
        with oc1:
            on = st.checkbox(rk.label, value=rk.default_on, key=f"rep_{rk.key}")
        with oc2:
            order = st.number_input("order", 1, 99, i + 1, key=f"ord_{rk.key}",
                                    label_visibility="collapsed", disabled=not on)
        if on:
            picked.append((rk, int(order)))

    # Every office uses the shared team views (sliced to its owner), so the
    # machine is set by the campaign — D2D on Lucy 1, B2B on Lucy 2. No per-office
    # view picker: the only offices that ever needed their own view are the two
    # hardcoded B2B ones, which don't come through this form.
    enrolled = [S.EnrolledReport(key=rk.key, order=order)
                for rk, order in sorted(picked, key=lambda t: t[1])]

    # ---- 6. Owner welcome email ------------------------------------------
    st.divider()
    st.markdown("### 6. Owner welcome email")
    st.caption("On submit, Lucy emails the owner a welcome to Lucy reporting + "
               "their Pay Structure code (so they can set their office's payouts). "
               "Uncheck to skip the send.")
    we1, we2 = st.columns([3, 2])
    with we1:
        owner_email = st.text_input(
            "Owner email", help="Where the welcome email is sent.")
    with we2:
        pay_code = st.text_input(
            "Pay Structure code", value=S.gen_pay_code(business, key or ""),
            help="Auto-made from the company name — edit if you want a cleaner "
                 "code. This is what the owner enters on the Pay Structure site.")
    send_welcome = st.checkbox(
        "✉️ Send the welcome email to the owner on submit", value=True)

    # ---- build the record -------------------------------------------------
    st.divider()
    rec = S.OnboardingRecord(
        key=(key or "").strip(), owner=owner.strip(),
        knocks_office=knocks.strip() or owner.strip(),
        business_name=business.strip(), website=website.strip(),
        channel_id=channel_id.strip(), channel_name=channel_name.strip(),
        sheet_id=sheet_id, family=family, ov_account=ov_account.strip(),
        owner_email=owner_email.strip(), pay_code=pay_code.strip(),
        reports=enrolled, header_label=header_label.strip())

    # ---- submit -----------------------------------------------------------
    if st.button("💾 Submit office", type="primary"):
        reg = store.existing_registry(exclude_key=rec.key)
        problems = S.validate(
            rec, existing_channels=reg["channels"],
            existing_keys=reg["keys"], existing_views=reg["views"])
        if send_welcome and rec.owner_email and "@" not in rec.owner_email:
            problems.append("Owner email doesn't look valid (or uncheck 'Send the "
                            "welcome email').")
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
        result = {"rec": rec.to_json(), "where": where}
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
    st.markdown("#### Apply it")
    st.caption("Run on the machine shown above (or from the laptop and let the "
               "sync ship it). Dry-run first; review `git diff`; then commit + "
               "push. Nothing is auto-pushed.")
    st.code(f"python -m automations.office_onboarding.apply --only {d['key']}\n"
            f"python -m automations.office_onboarding.apply --only {d['key']} --write",
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
        del st.session_state["_last_submit"]
        st.rerun()


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
_inject_gs_client()

_MODES = ("🏢 Enroll a new office", "✏️ Edit a thread (admin)")
_mode = st.radio("What do you want to do?", _MODES, index=0, horizontal=True)
st.write("---")
if _mode == _MODES[1]:
    thread_admin_view()
else:
    form_view()
