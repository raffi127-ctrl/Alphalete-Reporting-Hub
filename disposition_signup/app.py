"""Alphalete Reporting by Lucy — daily dispositions sign-up (owner self-serve).

Raf's #11280 thread 2026-09-01: owners sign up to get their daily disposition
data every 15 / 30 / 60 minutes, by email or iMessage or both, plus an optional
hourly post to their team's Slack channel. Megan's answer — "we have enrollment
links not web forms" — is why this is the same shape as the tracker sign-up
rather than a new kind of thing.

Megan sends an owner this link. They answer five questions and submit. The
request lands on the 'Disposition Signup' tab as status=PENDING and pings Megan
in the corrections channel with a confirm deep-link — NOTHING is sent to them
until Megan opens ?confirm=<key> (access-code gated), sets the campaign, checks
Office Access, and clicks Confirm.

Run locally:   .venv/bin/streamlit run disposition_signup/app.py
On the web:    Streamlit Community Cloud, subdomain alphaletedispositions.

Secrets: [gcp_service_account]/[gcp_oauth] for the master sheet,
`slack_user_token` (TOP-LEVEL, above any [section]!) for the ping + the
Lucy-membership check, `disposition_signup_code` to gate the confirm view.
Without Sheets creds it saves to a local draft (sandbox).
DISPOSITION_SIGNUP_LOCAL_ONLY=1 forces that.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.disposition_signup import schema as S, store   # noqa: E402
from automations.shared import onboarding_ui as ui              # noqa: E402

st.set_page_config(page_title="Alphalete Reporting by Lucy", page_icon="📊",
                   layout="centered")

SLACK_ID_IMG = (Path(__file__).resolve().parents[1] / "tracker_onboarding"
                / "slack_id_help.png")


def _inject_gs_client() -> dict:
    """Wire the Sheets client from secrets (shared builder). Returns a
    KEYS-ONLY diagnostic (never secret values) so `?debug=1` can show WHY it
    fell back to a local draft."""
    gc, diag = ui.build_gs_client("DISPOSITION_SIGNUP_LOCAL_ONLY")
    if gc is not None:
        store.set_client(gc)
    return diag


# A dropdown of quarter-hours in plain 12-hour English, NOT st.time_input:
# that widget shows a 24-hour clock ("13:30"), and an owner reading their own
# sign-up should not have to do the arithmetic. Quarter-hours only, because the
# job itself ticks on the quarter hour — offering 1:37 PM would promise a
# precision the schedule does not have.
_TIME_CHOICES = ["%02d:%02d" % (h, m)
                 for h in range(6, 24) for m in (0, 15, 30, 45)]


def _ampm(hhmm: str) -> str:
    h, m = [int(x) for x in hhmm.split(":")]
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def _time_picker(label: str, default: str, key: str) -> str:
    return st.selectbox(label, _TIME_CHOICES,
                        index=_TIME_CHOICES.index(default),
                        format_func=_ampm, key=key)


def _enqueue_onboard(key: str, *, preflight: bool = True) -> "tuple":
    """Drop a mini_control `onboard_apply disposition <key>` job so the runner
    materializes the office into its working tree — it then joins the next
    tick. With `preflight` (the default) it also adds --post, which on this
    kind means: impersonate the office, resolve its iMessage room, and switch
    it on if both hold. Reuses the form's own Sheets client (the queue is a tab
    on this same master sheet). Best-effort; returns (ok, note)."""
    gc = store.get_client()
    if gc is None:
        return False, "no Sheets client (local-draft mode)"
    try:
        from automations.day_orchestrator import queue_enqueue as qenq
        args = "disposition %s%s" % (key, " --post" if preflight else "")
        tab = qenq.enqueue(gc, "onboard_apply", args, by="Megan")
        return True, tab
    except Exception as e:                           # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------------------
# Owner self-serve request view (the default page)
# ---------------------------------------------------------------------------

def request_view() -> None:
    ui.render_header("Daily Dispositions Sign-Up")
    # After a successful submit, show ONLY the confirmation — the form (and its
    # submit button) is gone, so it can't be re-clicked into a duplicate.
    if st.session_state.get("_req_done"):
        _request_done_view()
        return
    st.caption("Get your office's knocks and dispositions — who's out, who's "
               "knocking, and who's gone quiet — sent to you all day long.")

    # ---- 1. You ----------------------------------------------------------
    st.divider()
    st.markdown("### 1. Who are you?")
    requested_by = st.text_input(
        "Your name (what you go by) *",
        help="Just what we should call you — the official OwnerVille spelling "
             "goes in the next box.")
    owner = st.text_input(
        "Your first and last name as it appears in OwnerVille *",
        help="Exactly as OwnerVille shows it. This is how we find your office.")
    knocks_office = st.text_input(
        "Company name as it appears in OV (only if it's different from your name)",
        help="Leave blank if OwnerVille lists your office under your own "
             "name. Some offices are listed under a company name instead — "
             "if yours is, type it exactly as OwnerVille shows it.")

    # ---- 2. Owner id -----------------------------------------------------
    st.divider()
    st.markdown("### 2. Your OwnerVille account number")
    ov_account = st.text_input(
        "Your OwnerVille account number (if you know it)",
        help="Optional — it just helps us find you faster if two people share "
             "a name. Leave it blank if you don't have it handy.")
    campaign_key = st.radio(
        "Which campaign are these dispositions for? *",
        [c["key"] for c in S.CAMPAIGNS],
        format_func=lambda k: (S.campaign(k) or {}).get("name", k),
        help="If your office runs both, sign up once here and tell us in the "
             "notes at the bottom — you'll get one report per campaign.")

    # ---- 3. How you want it ---------------------------------------------
    st.divider()
    st.markdown("### 3. How do you want it sent?")
    st.caption("Pick one or both.")
    want_text = st.checkbox("📱 iMessage text", value=True)
    imessage_group = ""
    if want_text:
        imessage_group = st.text_input(
            "Name of the group chat to text *",
            placeholder="Alphalete Partners",
            help="The chat's name exactly as it shows on your phone. Lucy "
                 "must already be in that chat — Megan sets that up.")
    want_email = st.checkbox("✉️ Email", value=False)
    email_raw = ""
    if want_email:
        email_raw = st.text_area(
            "Email address(es) *", placeholder="you@example.com",
            help="One per line, or separated by commas. Everyone listed gets "
                 "the same email.")
    email_to = S.parse_emails(email_raw) if want_email else []

    # ---- 4. How often ----------------------------------------------------
    st.divider()
    st.markdown("### 4. How often?")
    cadence = st.radio(
        "Send it to me *", S.CADENCE_CHOICES,
        index=S.CADENCE_CHOICES.index(S.DEFAULT_CADENCE),
        format_func=lambda m: S.CADENCE_LABELS[m])
    st.caption("It only sends while your reps are in the field. Those hours "
               "are the next question.")

    # ---- 4b. When (their clock, their hours) -----------------------------
    st.divider()
    st.markdown("### When are your reps in the field?")
    st.caption("We only send during these hours, on your local time. Most "
               "offices leave these as they are.")
    tz = st.selectbox(
        "Your office's time zone *", [z["tz"] for z in S.TIMEZONES],
        format_func=S.tz_label,
        help="So a 9 PM board lands at 9 PM for YOU, not for Texas.")
    h1, h2 = st.columns(2)
    with h1:
        day_start = _time_picker("Monday-Friday, from",
                                 S.DEFAULT_HOURS["day_start"], "day_start")
    with h2:
        day_end = _time_picker("until", S.DEFAULT_HOURS["day_end"], "day_end")
    saturday = st.checkbox("We knock on Saturdays too", value=True)
    sat_start = S.DEFAULT_HOURS["sat_start"]
    sat_end = S.DEFAULT_HOURS["sat_end"]
    if saturday:
        s1, s2 = st.columns(2)
        with s1:
            sat_start = _time_picker("Saturday, from", sat_start, "sat_start")
        with s2:
            sat_end = _time_picker("until ", sat_end, "sat_end")
    st.caption("Sundays are off for everyone.")

    # ---- 5. Slack --------------------------------------------------------
    st.divider()
    st.markdown("### 5. Do you want it in a Slack channel for your team?")
    st.caption("We recommend once an hour — a leaderboard four times an hour "
               "is one your reps learn to scroll past.")
    slack_hourly = st.checkbox("Yes — post it to my team's Slack channel "
                               "once an hour", value=False)
    slack_channel_name = slack_channel_id = ""
    if slack_hourly:
        slack_channel_name = st.text_input(
            "Slack channel name *", placeholder="#your-office-sales",
            key="slack_name")
        slack_channel_id = st.text_input(
            "Slack Channel ID", placeholder="C0ABC12DE", key="slack_id",
            help=ui.CHANNEL_ID_HELP)
        ui.channel_id_help_expander(SLACK_ID_IMG)
        st.info("**Please add Megan Hidalgo and Eve to that channel** — Megan "
                "adds Lucy (the bot that posts) from there.")

    st.divider()
    notes = st.text_area(
        "Anything else we should know?",
        placeholder="e.g. I run two campaigns, or only text me on weekdays",
        help="Optional.")

    # ---- submit ----------------------------------------------------------
    st.divider()
    deliver = ([d for d, on in (("imessage", want_text), ("email", want_email))
                if on])
    key = S.slug_from(owner)
    rec = S.DispositionRecord(
        key=key, owner=owner.strip(), requested_by=requested_by.strip(),
        ov_account=ov_account.strip(), cadence_min=int(cadence),
        deliver=deliver, email_to=email_to,
        imessage_group=imessage_group.strip(), slack_hourly=bool(slack_hourly),
        slack_channel_id=slack_channel_id.strip(),
        slack_channel_name=slack_channel_name.strip(),
        campaign_key=campaign_key, notes=notes.strip(), status="pending",
        knocks_office=knocks_office.strip(), tz=tz,
        day_start=day_start, day_end=day_end,
        sat_start=sat_start, sat_end=sat_end,
        saturday=bool(saturday))

    # The button stays OFF until every required field is filled, with a live
    # list of what's still needed — no dead-end "submit then get yelled at".
    missing: list = []
    if not requested_by.strip():
        missing.append("your name")
    if not owner.strip():
        missing.append("your OwnerVille name")
    if not deliver and not slack_hourly:
        missing.append("at least one way to send it")
    if want_text and not imessage_group.strip():
        missing.append("the group chat name")
    if want_email and not email_to:
        missing.append("an email address")
    if slack_hourly and not slack_channel_name.strip():
        missing.append("your Slack channel name")
    if missing:
        st.warning("⚠️ **Still needed before you can submit:** "
                   + ", ".join(missing) + ".")
    if st.button("📨 Send my sign-up to Megan", type="primary",
                 disabled=bool(missing)):
        with st.spinner("📨 Sending your sign-up — hang tight..."):
            prior = store.load_one(key) if key else None
            updating = bool(prior) and prior.get("status") == "pending"
            reg = store.existing_registry(exclude_key=key if updating else None)
            problems = S.validate_request(rec, existing_keys=reg["keys"])
            if problems:
                st.error("A couple of things to fix first:")
                for pr in problems:
                    st.markdown("- %s" % pr)
                return
            rec.submitted_at = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC")
            rec.submitted_by = rec.requested_by
            lucy = None
            if slack_hourly:
                lucy = ui.check_channel(rec.slack_channel_id,
                                        rec.slack_channel_name)
                if lucy.get("channel_id") and not rec.slack_channel_id:
                    rec.slack_channel_id = lucy["channel_id"]
            try:
                where = store.update(rec) if updating else store.save(rec)
            except Exception as e:                   # noqa: BLE001
                st.error("Couldn't save your sign-up — please tell Megan. (%s)"
                         % e)
                return
            ping = (False, "not pinged (local draft)")
            if where == "sheet":
                from automations.disposition_signup import request_notify
                ping = request_notify.notify(rec, lucy)
            st.session_state["_req_done"] = {"rec": rec.to_json(),
                                             "lucy": lucy, "where": where,
                                             "ping": ping, "updated": updating}
        st.rerun()


def _request_done_view() -> None:
    res = st.session_state.get("_req_done")
    if not res:
        return
    d = res["rec"]
    st.divider()
    st.success("🎉 You're signed up%s! Once Megan hooks it up, your knocks and "
               "dispositions start arriving on their own. Nothing else for you "
               "to do — go sell something. 🐾🚀"
               % (" (updated)" if res.get("updated") else ""))
    st.markdown("**What you'll get, %s:**" % d["_derived"]["cadence"].lower())
    st.caption("During your field hours: %s" % d["_derived"]["hours"])
    for r in d["_derived"]["routes"]:
        st.markdown("- %s" % r)
    lucy = res.get("lucy") or {}
    if lucy and lucy.get("status") in ("not_member", "not_found"):
        st.warning("⚠️ One last thing: Lucy isn't in **%s** yet. Add **Megan "
                   "Hidalgo** to it and she'll get the posting started."
                   % (lucy.get("channel_name") or "your channel"))
    ping_ok, ping_note = res.get("ping", (False, ""))
    if res["where"] == "sheet" and not ping_ok:
        st.warning("Your sign-up is saved, but the automatic heads-up to Megan "
                   "didn't go out (%s) — please message her that you signed "
                   "up." % ping_note)
    if res["where"] == "local":
        st.warning("Saved as a LOCAL DRAFT (this deploy has no Google creds) — "
                   "please message Megan that you signed up.")
    if st.button("Start over"):
        del st.session_state["_req_done"]
        st.rerun()


# ---------------------------------------------------------------------------
# Megan's confirm view (?confirm=<key>, access-code gated)
# ---------------------------------------------------------------------------

def _gate() -> bool:
    """Access-code gate for the confirm view. Fail-CLOSED on a live deploy
    (Sheets client set) with no code secret; open in the local sandbox."""
    try:
        code = st.secrets.get("disposition_signup_code")
    except Exception:                                # noqa: BLE001
        code = None
    if not code:
        if store.get_client() is not None:
            st.error("Confirm view is locked: add a `disposition_signup_code` "
                     "secret to this deploy first.")
            return False
        st.warning("Local sandbox — confirm gate skipped (no code secret).")
        return True
    if st.session_state.get("_gate_ok"):
        return True
    got = st.text_input("Access code", type="password")
    if got and got == str(code):
        st.session_state["_gate_ok"] = True
        st.rerun()
    elif got:
        st.error("Wrong code.")
    return False


def confirm_view(key: str) -> None:
    ui.render_header("Confirm disposition sign-up — `%s`" % key)
    if not _gate():
        return
    d = store.load_one(key)
    if not d:
        st.error("No sign-up found for %r." % key)
        return
    rec = store.record_from_json(d)
    if rec.status == "wired":
        st.info("This one is already confirmed + wired — confirming again just "
                "re-applies it (safe / idempotent).")
    st.markdown("- **Requested by:** %s\n- **ICD (OwnerVille):** %s\n"
                "- **OwnerVille account #:** %s\n- **Submitted:** %s"
                % (rec.requested_by or rec.owner, rec.owner,
                   rec.ov_account or "—", rec.submitted_at or "—"))
    if rec.notes:
        st.markdown("- **Notes:** %s" % rec.notes)

    # ---- what they asked for, all editable ------------------------------
    st.markdown("#### What they get")
    cadence = st.radio("How often", S.CADENCE_CHOICES,
                       index=S.CADENCE_CHOICES.index(
                           int(rec.cadence_min)
                           if int(rec.cadence_min) in S.CADENCE_CHOICES
                           else S.DEFAULT_CADENCE),
                       format_func=lambda m: S.CADENCE_LABELS[m],
                       horizontal=True)
    campaign_key = st.radio(
        "Campaign (pins invD2DClientId — a wrong pin silently reports the "
        "wrong business)", [c["key"] for c in S.CAMPAIGNS],
        index=max(0, [c["key"] for c in S.CAMPAIGNS].index(rec.campaign_key))
        if S.campaign(rec.campaign_key) else 0,
        format_func=lambda k: "%s (id %s)" % ((S.campaign(k) or {}).get("name", k),
                                              (S.campaign(k) or {}).get("id", "?")),
        horizontal=True)
    label = st.text_input("Name on the card", value=rec.label
                          or (rec.owner.split()[0] if rec.owner else ""))
    knocks_office = st.text_input(
        "Company name as it appears in OV (impersonation resolves through this)",
        value=rec.knocks_office,
        placeholder=rec.owner,
        help="Blank = the owner's own name. A mismatch here is the difference "
             "between a board and a failed tick every 15 minutes.")
    st.caption("Field hours: **%s**" % rec.hours_label())
    c1, c2 = st.columns(2)
    with c1:
        want_text = st.checkbox("iMessage", value="imessage" in rec.deliver)
        group = st.text_input("Group chat name", value=rec.imessage_group,
                              disabled=not want_text)
    with c2:
        want_email = st.checkbox("Email", value="email" in rec.deliver)
        emails = st.text_area("Email address(es)",
                              value="\n".join(rec.email_to),
                              disabled=not want_email)
    slack_hourly = st.checkbox("Hourly Slack post", value=rec.slack_hourly)
    s1, s2 = st.columns(2)
    with s1:
        ch_name = st.text_input("Slack channel name",
                                value=rec.slack_channel_name,
                                disabled=not slack_hourly)
    with s2:
        ch_id = st.text_input("Slack Channel ID", value=rec.slack_channel_id,
                              disabled=not slack_hourly)

    # ---- Lucy membership -------------------------------------------------
    if slack_hourly:
        ck = "_lucy_%s" % key
        if ck not in st.session_state:
            st.session_state[ck] = ui.check_channel(ch_id, ch_name)
        res = st.session_state[ck]
        (st.success if res.get("status") == "member" else st.warning)(
            ui.lucy_line(res))
        if st.button("🔄 Re-check Lucy's membership"):
            st.session_state[ck] = ui.check_channel(ch_id, ch_name)
            st.rerun()

    # ---- the two things the form can't know ------------------------------
    st.divider()
    st.markdown("#### Before it can actually run")
    st.caption("Two things decide whether this office can run, and neither is "
               "visible from here: whether Office Access is granted for the "
               "owner, and whether Lucy is in that iMessage room. Confirming "
               "hands both to the runner — it impersonates the office, "
               "resolves the chat, and switches the office on only if both "
               "hold. You get the result in the corrections channel.")
    enabled = st.checkbox(
        "Skip the check — switch it on now",
        value=rec.enabled,
        help="Only if you've already verified Office Access yourself. An "
             "office we can't impersonate fails EVERY tick and opens "
             "incidents instead of posting.")

    rec2 = S.DispositionRecord(
        key=key, owner=rec.owner, requested_by=rec.requested_by,
        ov_account=rec.ov_account, cadence_min=int(cadence),
        deliver=[d for d, on in (("imessage", want_text), ("email", want_email))
                 if on],
        email_to=S.parse_emails(emails) if want_email else [],
        imessage_group=group.strip() if want_text else "",
        slack_hourly=bool(slack_hourly),
        slack_channel_id=ch_id.strip() if slack_hourly else "",
        slack_channel_name=ch_name.strip() if slack_hourly else "",
        campaign_key=campaign_key, label=label.strip(), notes=rec.notes,
        knocks_office=knocks_office.strip(), tz=rec.tz,
        day_start=rec.day_start, day_end=rec.day_end,
        sat_start=rec.sat_start, sat_end=rec.sat_end, saturday=rec.saturday,
        status="wired", enabled=bool(enabled),
        submitted_by="Megan (confirm)",
        submitted_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    reg = store.existing_registry(exclude_key=key)
    for w in S.warnings(rec2, existing_groups=reg["groups"]):
        st.warning(w)

    if st.button("✅ Confirm + verify + wire up", type="primary"):
        problems = S.validate(rec2, existing_keys=reg["keys"],
                              existing_groups=reg["groups"])
        if problems:
            st.error("Fix these before confirming:")
            for pr in problems:
                st.markdown("- %s" % pr)
            return
        try:
            where = store.update(rec2)
        except Exception as e:                       # noqa: BLE001
            st.error("Couldn't save: %s" % e)
            return
        # --post = run the preflight on the runner and switch the office on if
        # it passes. Skipped only when Megan ticked the manual override, since
        # the office is already on and there is nothing left to prove.
        wired = (_enqueue_onboard(key, preflight=not enabled)
                 if where == "sheet" else (False, "local"))
        st.session_state["_cf_done"] = {"rec": rec2.to_json(), "where": where,
                                        "wired": wired}
        st.rerun()

    _confirm_done_view()


def _confirm_done_view() -> None:
    res = st.session_state.get("_cf_done")
    if not res:
        return
    d = res["rec"]
    st.divider()
    st.success("Confirmed %s — saved as wired." % d["key"])
    if res["where"] == "sheet":
        wired_ok, wired_note = res.get("wired", (False, ""))
        if wired_ok:
            if d.get("enabled"):
                st.success("✅ Wiring it in now (switched on by hand — no "
                           "preflight). Live on the next tick, ~1–2 min.")
            else:
                st.success("✅ Handed to the runner — it's impersonating the "
                           "office and resolving the iMessage room now. If "
                           "both check out it switches itself on and joins the "
                           "next tick; either way you get the result in "
                           "#claudecorrections-and-requests in a minute or "
                           "two. Nothing else for you to do.")
            st.caption("The nightly auto-commit keeps it — no manual commit "
                       "needed.")
        else:
            st.warning("Saved, but couldn't auto-wire (%s). Fallback:"
                       % wired_note)
            st.code("python -m automations.disposition_signup.apply --only %s "
                    "--write" % d["key"], language="bash")
    else:
        st.code("python -m automations.disposition_signup.apply --only %s "
                "--write" % d["key"], language="bash")


# ---------------------------------------------------------------------------
_diag = _inject_gs_client()
ui.inject_slack_token()
# ?debug=1 shows a KEYS-ONLY readout of what the app can see in its secrets
# (never any secret value) — so a "why is it still a local draft?" is
# answerable without guessing.
try:
    _dbg = str(st.query_params.get("debug", "")).lower() in ("1", "true", "yes")
except Exception:                                    # noqa: BLE001
    _dbg = False
if _dbg:
    st.warning("🔧 secrets diagnostic (keys only, no values):")
    st.json(_diag)
try:
    _confirm = str(st.query_params.get("confirm", "")).strip()
except Exception:                                    # noqa: BLE001
    _confirm = ""
if _confirm:
    confirm_view(_confirm)
else:
    request_view()
