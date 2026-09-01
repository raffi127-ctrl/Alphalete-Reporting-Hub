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
        "Company name as it appears in OV *",
        help="Type it exactly as OwnerVille shows it. If OwnerVille lists your "
             "office under your own name, put that.")

    # ---- 2. Owner id -----------------------------------------------------
    st.divider()
    st.markdown("### 2. Your OwnerVille account number")
    ov_account = st.text_input(
        "Your OwnerVille account number *",
        help="It's how we find you for certain when two people share a name.")
    campaign_key = st.radio(
        "Which campaign are these dispositions for? *",
        [c["key"] for c in S.CAMPAIGNS],
        format_func=lambda k: (S.campaign(k) or {}).get("name", k),
        help="If your office runs both, sign up once here and tell us in the "
             "notes at the bottom — you'll get one report per campaign.")

    # ---- 3. Where it goes ------------------------------------------------
    # MANY destinations, each on its OWN clock (Megan 2026-09-01): the owners'
    # room every 15 minutes and the rep channel once an hour is one office, not
    # two sign-ups. Same count-then-container shape the tracker sign-up uses for
    # its channels — proven, and it needs no drag-and-drop component.
    st.divider()
    st.markdown("### 3. Where should it go?")
    st.caption("Add every chat, channel and inbox that should get it. Each one "
               "gets its own timing — your owners' chat can run every 15 "
               "minutes while your rep channel gets it once an hour.")
    st.info("**Add Megan Hidalgo to EVERY Slack channel or iMessage chat you "
            "want postings in.** She'll leave once it's set up.\n\n"
            "Her number for the iMessage chats: **419-769-7114**")

    destinations: list = []

    st.markdown("#### 📱 iMessage chats")
    n_chat = int(st.number_input(
        "How many iMessage chats?", 0, 5, 1, key="n_chat",
        help="0 if you don't want texts."))
    for i in range(n_chat):
        with st.container(border=True):
            nm = st.text_input(
                "Name of the group chat *", placeholder="Alphalete Partners",
                key="chat_name_%d" % i,
                help="The chat's name exactly as it shows on your phone.")
            cad = st.radio("How often? *", S.CADENCE_CHOICES,
                           index=S.CADENCE_CHOICES.index(S.DEFAULT_CADENCE),
                           format_func=lambda m: S.CADENCE_LABELS[m],
                           horizontal=True, key="chat_cad_%d" % i)
            destinations.append(S.destination("imessage", name=nm,
                                              cadence_min=cad))

    st.markdown("#### 💬 Slack channels")
    n_slack = int(st.number_input(
        "How many Slack channels?", 0, 5, 0, key="n_slack",
        help="0 if you don't want it in Slack."))
    for i in range(n_slack):
        with st.container(border=True):
            nm = st.text_input(
                "Slack channel name *", placeholder="#your-office-sales",
                key="slack_name_%d" % i)
            cid = st.text_input("Slack Channel ID *", placeholder="C0ABC12DE",
                                key="slack_id_%d" % i,
                                help=ui.CHANNEL_ID_HELP)
            if i == 0:
                ui.channel_id_help_expander(SLACK_ID_IMG)
            cad = st.radio("How often? *", S.CADENCE_CHOICES,
                           index=S.CADENCE_CHOICES.index(60),
                           format_func=lambda m: S.CADENCE_LABELS[m],
                           horizontal=True, key="slack_cad_%d" % i)
            st.caption("Once an hour is what we'd suggest for a channel of "
                       "reps — four times an hour is one they learn to scroll "
                       "past.")
            destinations.append(S.destination("slack", name=nm, channel_id=cid,
                                              cadence_min=cad))

    st.markdown("#### ✉️ Email")
    want_email = st.checkbox("Email it to me too", value=False)
    if want_email:
        with st.container(border=True):
            email_raw = st.text_area(
                "Email address(es) *", placeholder="you@example.com",
                help="One per line, or separated by commas. Everyone listed "
                     "gets the same email.")
            cad = st.radio("How often? *", S.CADENCE_CHOICES,
                           index=S.CADENCE_CHOICES.index(60),
                           format_func=lambda m: S.CADENCE_LABELS[m],
                           horizontal=True, key="email_cad")
            destinations.append(S.destination(
                "email", emails=S.parse_emails(email_raw), cadence_min=cad))

    # ---- 4. When (their clock, their hours) ------------------------------
    st.divider()
    st.markdown("### 4. When are your reps in the field?")
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

    st.divider()
    notes = st.text_area(
        "Anything else we should know?",
        placeholder="e.g. I run two campaigns, or only text me on weekdays",
        help="Optional.")

    # ---- submit ----------------------------------------------------------
    st.divider()
    key = S.slug_from(owner)
    rec = S.DispositionRecord(
        key=key, owner=owner.strip(), requested_by=requested_by.strip(),
        ov_account=ov_account.strip(), destinations=destinations,
        campaign_key=campaign_key, notes=notes.strip(), status="pending",
        knocks_office=knocks_office.strip(), tz=tz,
        day_start=day_start, day_end=day_end,
        sat_start=sat_start, sat_end=sat_end,
        saturday=bool(saturday))

    # The button stays OFF until every required field is filled, with a live
    # list of what's still needed — no dead-end "submit then get yelled at".
    # EVERY field we ask for is required (Megan 2026-09-01) — a half-filled
    # sign-up is a message to Megan asking for the rest, which is the thing
    # this link exists to avoid.
    missing: list = []
    if not requested_by.strip():
        missing.append("your name")
    if not owner.strip():
        missing.append("your OwnerVille name")
    if not knocks_office.strip():
        missing.append("your company name in OV")
    if not ov_account.strip():
        missing.append("your OwnerVille account number")
    if not destinations:
        missing.append("at least one place to send it")
    for i, d in enumerate(destinations):
        n = "" if len(destinations) == 1 else " #%d" % (i + 1)
        if d["kind"] == "imessage" and not d["name"]:
            missing.append("the group chat name%s" % n)
        if d["kind"] == "slack":
            if not d["name"]:
                missing.append("the Slack channel name%s" % n)
            if not d["channel_id"]:
                missing.append("the Slack Channel ID%s" % n)
        if d["kind"] == "email" and not d["emails"]:
            missing.append("an email address")
    # SECOND reminder, right at the button (Megan 2026-09-01) — the same place
    # the tracker sign-up puts it. The one up in section 3 is read while they
    # are picking destinations; this one is read while they are committing, and
    # it is the step that decides whether anything can post at all.
    _rooms = [d for d in destinations if d["kind"] in ("imessage", "slack")]
    if _rooms:
        st.info("🔔 **Reminder:** add **Megan Hidalgo** to every chat and "
                "channel you listed above **BEFORE HITTING SUBMIT** — we "
                "can't start your postings without it! Her number for the "
                "iMessage chats is **419-769-7114**. She'll leave once it's "
                "set up.")
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
            # One membership check per Slack destination — an office can list
            # several now, and "Lucy is in one of them" is not an answer.
            lucy = []
            for d in rec.destinations:
                if d.get("kind") != "slack":
                    continue
                res = ui.check_channel(d.get("channel_id", ""),
                                       d.get("name", ""))
                if res.get("channel_id") and not d.get("channel_id"):
                    d["channel_id"] = res["channel_id"]
                lucy.append(res)
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
    campaign_key = st.radio(
        "Campaign (pins invD2DClientId — a wrong pin silently reports the "
        "wrong business)", [c["key"] for c in S.CAMPAIGNS],
        index=([c["key"] for c in S.CAMPAIGNS].index(rec.campaign_key)
               if S.campaign(rec.campaign_key) else 0),
        format_func=lambda k: "%s (id %s)" % (
            (S.campaign(k) or {}).get("name", k),
            (S.campaign(k) or {}).get("id", "") or "no pin"),
        horizontal=True)
    label = st.text_input("Name on the card", value=rec.label
                          or (rec.owner.split()[0] if rec.owner else ""))
    knocks_office = st.text_input(
        "Company name as it appears in OV (impersonation resolves through this)",
        value=rec.knocks_office, placeholder=rec.owner,
        help="A mismatch here is the difference between a board and a failed "
             "tick every 15 minutes.")
    st.caption("Field hours: **%s**" % rec.hours_label())

    # Every destination, each editable, each with its own cadence. Kind is
    # fixed — changing an iMessage row into a Slack one is a different request,
    # not an edit.
    st.markdown("#### Destinations")
    dests: list = []
    lucy_checks: list = []
    for i, d in enumerate(rec.destinations):
        kind = d.get("kind", "")
        with st.container(border=True):
            st.markdown("**%s**" % S.DELIVERY_LABELS.get(kind, kind))
            keep = st.checkbox("Send here", value=True, key="cf_keep_%d" % i)
            if kind == "email":
                addrs = st.text_area("Address(es)",
                                     value="\n".join(d.get("emails") or []),
                                     key="cf_mail_%d" % i)
                nm = cid = ""
            else:
                nm = st.text_input(
                    "Chat name" if kind == "imessage" else "Channel name",
                    value=d.get("name", ""), key="cf_nm_%d" % i)
                cid = ""
                addrs = ""
                if kind == "slack":
                    cid = st.text_input("Channel ID",
                                        value=d.get("channel_id", ""),
                                        key="cf_cid_%d" % i)
            cad_now = int(d.get("cadence_min") or S.DEFAULT_CADENCE)
            cad = st.radio(
                "How often", S.CADENCE_CHOICES,
                index=(S.CADENCE_CHOICES.index(cad_now)
                       if cad_now in S.CADENCE_CHOICES
                       else S.CADENCE_CHOICES.index(S.DEFAULT_CADENCE)),
                format_func=lambda m: S.CADENCE_LABELS[m], horizontal=True,
                key="cf_cad_%d" % i)
            if kind == "slack":
                ck = "_lucy_%s_%d" % (key, i)
                if ck not in st.session_state:
                    st.session_state[ck] = ui.check_channel(cid, nm)
                res = st.session_state[ck]
                (st.success if res.get("status") == "member"
                 else st.warning)(ui.lucy_line(res))
                lucy_checks.append(res)
                if st.button("🔄 Re-check Lucy", key="cf_recheck_%d" % i):
                    st.session_state[ck] = ui.check_channel(cid, nm)
                    st.rerun()
            if keep:
                dests.append(S.destination(
                    kind, name=nm, channel_id=cid,
                    emails=S.parse_emails(addrs) if kind == "email" else None,
                    cadence_min=cad))

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
        ov_account=rec.ov_account, destinations=dests,
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
