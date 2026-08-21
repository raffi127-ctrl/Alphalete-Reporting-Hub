"""Alphalete Reporting by Lucy — daily tracker sign-up (ICD self-serve).

Megan sends an ICD this link. They pick which tracker boards they want (each
with a preview image), tell us their Slack channel, and submit. The request
lands on the 'Tracker Onboarding' tab as status=PENDING and pings Megan in the
corrections channel with a confirm deep-link — NOTHING posts to their channel
until Megan opens ?confirm=<key> (access-code gated), verifies Lucy is in the
channel, and clicks Confirm. Confirm flips the row to "wired" and enqueues the
mini's onboard_apply, exactly like the old direct flow.

Run locally:   .venv/bin/streamlit run tracker_onboarding/app.py
On the web:    Streamlit Community Cloud, subdomain alphaletetrackerintake.

Secrets: [gcp_service_account]/[gcp_oauth] for the master sheet,
`slack_user_token` (TOP-LEVEL, above any [section]!) for the ping + the
Lucy-membership check, `tracker_onboarding_code` to gate the confirm view.
Without Sheets creds it saves to a local draft (sandbox).
TRACKER_ONBOARDING_LOCAL_ONLY=1 forces that.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.tracker_onboarding import schema as S, store  # noqa: E402

# Drag-and-drop ordering (same component the Thread Builder uses). Fall back to
# plain widgets if the Cloud deploy doesn't have it installed yet.
try:
    from streamlit_sortables import sort_items
    _HAS_SORT = True
except Exception:                                    # noqa: BLE001
    _HAS_SORT = False

st.set_page_config(page_title="Alphalete Reporting by Lucy", page_icon="📊",
                   layout="centered")

PREVIEW_DIR = Path(__file__).resolve().parent / "previews"
SLACK_ID_IMG = Path(__file__).resolve().parent / "slack_id_help.png"


def _inject_gs_client() -> dict:
    """Wire the Sheets client from secrets. Returns a KEYS-ONLY diagnostic (never
    secret values) so `?debug=1` can show WHY it fell back to a local draft."""
    diag = {"local_only": os.environ.get("TRACKER_ONBOARDING_LOCAL_ONLY"),
            "gspread_import": False, "secret_keys": None, "has_gcp_oauth": False,
            "has_gcp_service_account": False, "oauth_field_keys": None,
            "client_set": False, "error": ""}
    if os.environ.get("TRACKER_ONBOARDING_LOCAL_ONLY") == "1":
        diag["error"] = "TRACKER_ONBOARDING_LOCAL_ONLY=1 forces local draft"
        return diag
    try:
        import gspread
        diag["gspread_import"] = True
    except Exception as e:                       # noqa: BLE001
        diag["error"] = f"gspread import failed: {type(e).__name__}: {e}"
        return diag
    try:
        diag["secret_keys"] = sorted(list(st.secrets.keys()))
    except Exception as e:                       # noqa: BLE001
        diag["error"] = f"st.secrets unreadable: {type(e).__name__}: {e}"
    try:
        sa = st.secrets.get("gcp_service_account")
    except Exception:
        sa = None
    diag["has_gcp_service_account"] = bool(sa)
    if sa:
        try:
            store.set_client(gspread.service_account_from_dict(dict(sa)))
            diag["client_set"] = True
        except Exception as e:                   # noqa: BLE001
            diag["error"] = f"service_account client failed: {type(e).__name__}: {e}"
        return diag
    try:
        o = st.secrets.get("gcp_oauth")
    except Exception:
        o = None
    diag["has_gcp_oauth"] = bool(o)
    if o:
        try:
            diag["oauth_field_keys"] = sorted(list(dict(o).keys()))
        except Exception:
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
            store.set_client(gspread.authorize(creds))
            diag["client_set"] = True
        except Exception as e:                   # noqa: BLE001 — report, don't crash
            diag["error"] = f"oauth client build failed: {type(e).__name__}: {e}"
    return diag


def _inject_slack_token() -> None:
    """Export the `slack_user_token` secret as SLACK_USER_TOKEN so the corrections
    ping + the Lucy-membership check work on Streamlit Cloud. Best-effort —
    absent secret just means no ping/check (the request still saves)."""
    try:
        tok = st.secrets.get("slack_user_token")
    except Exception:                                # noqa: BLE001
        tok = None
    if tok and not os.environ.get("SLACK_USER_TOKEN"):
        os.environ["SLACK_USER_TOKEN"] = str(tok).strip()


def _enqueue_onboard(key: str, *, post: bool) -> "tuple":
    """Drop a mini_control `onboard_apply tracker <key>` job so the mini wires the
    office (apply --write into its working tree → joins the daily tracker run) and,
    with --post, runs the tracker post now. Trackers run on the default machine
    (Lucy 1). Reuses the form's own Sheets client (the queue is a tab on this same
    master sheet). Best-effort; returns (ok, note)."""
    gc = store.get_client()
    if gc is None:
        return False, "no Sheets client (local-draft mode)"
    try:
        from automations.day_orchestrator import queue_enqueue as qenq
        args = f"tracker {key}" + (" --post" if post else "")
        tab = qenq.enqueue(gc, "onboard_apply", args, by="Megan")
        return True, tab
    except Exception as e:                           # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _check_lucy(channel_id: str, channel_name: str) -> dict:
    from automations.tracker_onboarding import slack_check
    return slack_check.check_channel(channel_id, channel_name)


def _lucy_line(res: dict) -> str:
    from automations.tracker_onboarding import slack_check
    return slack_check.human_line(res)


def _preview_path(tracker_id: str) -> "Path | None":
    p = PREVIEW_DIR / f"{tracker_id}.png"
    return p if p.exists() else None


def _channel_owners() -> "tuple":
    """({channel_id: org_key}, {channel_name: org_key}) across every org that
    already posts trackers (live + onboarded + pending rows). Lets the form
    recognize 'this channel already gets trackers' and turn the submission
    into a CHANGE request instead of a dead end. Cached per session."""
    if "_chan_owners" not in st.session_state:
        by_id = {}
        by_name = {}
        try:
            by_id = dict(store.existing_registry()["channels"])
        except Exception:                            # noqa: BLE001
            pass
        try:
            from automations.tableau_screenshots import slack_post as _sp
            for k, lbl in getattr(_sp, "ORG_LABEL", {}).items():
                by_name[(lbl or "").strip().lstrip("#").lower()] = k
        except Exception:                            # noqa: BLE001
            pass
        try:
            for d in store.load_all():
                names = [d.get("channel_name", "")] + [
                    c.get("channel_name", "")
                    for c in d.get("extra_channels", [])]
                for nm in names:
                    nm = (nm or "").strip().lstrip("#").lower()
                    if nm:
                        by_name.setdefault(nm, d.get("key"))
        except Exception:                            # noqa: BLE001
            pass
        st.session_state["_chan_owners"] = (by_id, by_name)
    return st.session_state["_chan_owners"]


def _org_owning(channel_id: str, channel_name: str) -> "str | None":
    by_id, by_name = _channel_owners()
    k = by_id.get((channel_id or "").strip())
    if k:
        return k
    return by_name.get((channel_name or "").strip().lstrip("#").lower())


def _form_managed(key: str) -> bool:
    """True if this org lives in onboarded_trackers.json (the form can update
    it); False = hardcoded in slack_post.py, needs a code change."""
    import json
    p = (Path(__file__).resolve().parents[1] / "automations"
         / "tableau_screenshots" / "onboarded_trackers.json")
    try:
        return any(r.get("key") == key for r in json.loads(p.read_text()))
    except Exception:                                # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# ICD self-serve request view (the default page)
# ---------------------------------------------------------------------------

def request_view() -> None:
    st.markdown("## 📊 Alphalete Reporting by Lucy")
    st.markdown("### Daily Tableau Tracker Views Sign-Up")
    # After a successful submit, show ONLY the confirmation — the form (and
    # its submit button) is gone, so it can't be re-clicked into a duplicate.
    if st.session_state.get("_req_done"):
        _request_done_view()
        return
    st.caption("Pick the boards you want and Lucy will post fresh "
               "screenshots to your Slack channel every morning.")

    # ---- 1. You ----------------------------------------------------------
    st.divider()
    st.markdown("### 1. Who are you?")
    requested_by = st.text_input(
        "Your name (what you go by) *",
        help="Just what we should call you — the official OwnerVille "
             "spelling goes in the next box.")
    owner = st.text_input(
        "ICD Name as it appears in OwnerVille *",
        help="Your name exactly as OwnerVille shows it — this is how we file "
             "your office.")
    # ---- 2. Channels & the boards each one gets ---------------------------
    st.divider()
    st.markdown("### 2. Your Slack channel(s) & boards")
    st.caption("Check what each channel gets. Most offices use one channel "
               "for everything. If you want certain boards going somewhere "
               "else too — like a leaders-only channel — add a second "
               "channel and check just those.")
    st.info("**Important:** **Megan Hidalgo** must be added to **EACH** Slack "
            "channel you want the Tableau trackers posted in — she'll add "
            "Lucy (the bot that posts the boards) from there.")
    # Only UNIVERSAL national boards are offered. Opt-in boards (opt_in_only in
    # tableau_screenshots.pages, e.g. order_tiered_bonus) are OWNER-SCOPED —
    # posting one to a different office's channel shows THAT owner's numbers
    # (the jamis→Atef isolation failure, 2026-08-01) — so they are deliberately
    # NOT options here.
    catalog = [t for t in S.tracker_catalog() if not t["opt_in"]]
    if not catalog:
        st.error("Couldn't load the tracker list — please tell Megan the "
                 "sign-up form is down.")
    n_ch = st.number_input(
        "How many Slack channels should Lucy post in?", 1, 5, 1,
        help="Most offices use 1. Add more if you want certain boards in "
             "another channel too — each channel gets its own picks.")
    chan_pairs: list = []
    chan_plans: list = []
    picked: list = []                    # ordered union across every channel
    for i in range(int(n_ch)):
        with st.container(border=True):
            if int(n_ch) > 1:
                st.markdown(f"**Channel {i + 1}**")
            cname = st.text_input(
                "Slack channel name *", placeholder="#your-office-sales",
                key=f"ch_name_{i}",
                help="The channel where you want the boards posted each "
                     "morning.")
            cid = st.text_input(
                "Slack Channel ID *", placeholder="C0ABC12DE", key=f"ch_id_{i}",
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
                    st.image(str(SLACK_ID_IMG), width=397)
            st.caption("Boards to post in this channel:")
            here: list = []
            for t in catalog:
                on = st.checkbox(f"{t['emoji']} **{t['title']}**", value=False,
                                 key=f"trk_{i}_{t['id']}")
                # previews once, in the first channel's list — same boards.
                if i == 0:
                    pv = _preview_path(t["id"])
                    if pv is not None:
                        with st.expander("View preview"):
                            st.image(str(pv), use_container_width=True)
                if on:
                    here.append(t["id"])
                    if t["id"] not in picked:
                        picked.append(t["id"])
            chan_pairs.append((cid.strip(), cname.strip()))
            chan_plans.append({"channel_id": cid.strip(),
                               "channel_name": cname.strip(),
                               "trackers": here})
    picked = [t["id"] for t in catalog if t["id"] in picked]  # catalog order

    # Channel already enrolled? Turn this into a CHANGE request, not a dead end.
    change_of = _org_owning(chan_pairs[0][0], chan_pairs[0][1])
    if change_of:
        st.info("ℹ️ **This channel is already getting trackers posted.** Need "
                "to add more boards or change the lineup? Keep going — check "
                "the **full** set of boards you want (your picks replace the "
                "current lineup) and submit. Megan will update the existing "
                "setup.")

    # ---- 3. Order them (drag & drop) -------------------------------------
    labels = {t["id"]: f"{t['emoji']} {t['title']}" for t in catalog}
    rev = {v: k for k, v in labels.items()}
    st.divider()
    st.markdown("### 3. Put them in order")
    if picked and _HAS_SORT:
        st.caption("This is the order the Tableau images will post in each "
                   "morning, in every channel — drag to rearrange, top posts "
                   "first. If a board isn't checked in one of your channels, "
                   "that channel simply skips it; the rest still post in "
                   "this order.")
        # key includes the picked set so the drag list rebuilds when it changes
        sorted_labels = sort_items(
            [labels[i] for i in picked], direction="vertical",
            key="icd_order_" + "_".join(sorted(picked)))
        trackers = [rev[l] for l in sorted_labels if l in rev]
    elif not picked:
        st.caption("Check some boards above and they'll show up here for you "
                   "to drag into order.")
        trackers = []
    else:
        trackers = picked                            # catalog order = post order

    # ---- submit ----------------------------------------------------------
    st.divider()
    # A change request files under the EXISTING org's key, so Megan's confirm
    # + wire replaces that org's board lineup instead of creating a twin.
    key = change_of or S.slug_from(owner)
    rec = S.TrackerRecord(
        key=key, owner=owner.strip(),
        channel_id=chan_pairs[0][0], channel_name=chan_pairs[0][1],
        extra_channels=[{"channel_id": c, "channel_name": n}
                        for c, n in chan_pairs[1:]],
        channel_plans=[{"channel_id": p["channel_id"],
                        "channel_name": p["channel_name"],
                        "trackers": [t for t in trackers
                                     if t in p["trackers"]]}
                       for p in chan_plans],
        trackers=trackers, status="pending",
        requested_by=requested_by.strip())

    st.info("🔔 **Reminder:** add **Megan Hidalgo** to each Slack channel you "
            "listed above **BEFORE HITTING SUBMIT** — we can't start your "
            "posting without it!")
    # The button stays OFF until every required field is filled, with a live
    # list of what's still needed — no dead-end "submit then get yelled at".
    missing: list = []
    if not requested_by.strip():
        missing.append("your name")
    if not owner.strip():
        missing.append("your OwnerVille name")
    for i, (cid, cname) in enumerate(chan_pairs):
        tag = "" if len(chan_pairs) == 1 else f" (channel {i + 1})"
        if not cname:
            missing.append(f"Slack channel name{tag}")
        if not cid:
            missing.append(f"Slack Channel ID{tag}")
    for i, p in enumerate(chan_plans):
        tag = "" if len(chan_plans) == 1 else f" (channel {i + 1})"
        if not p["trackers"]:
            missing.append(f"at least one board{tag}")
    if missing:
        st.warning("⚠️ **Still needed before you can submit:** "
                   + ", ".join(missing) + ".")
    if st.button("📨 Send my sign-up to Megan", type="primary",
                 disabled=bool(missing)):
        # The Slack channel check takes a few seconds — show a spinner so
        # nobody thinks the click didn't take (and clicks it five more times).
        with st.spinner("📨 Sending your sign-up — this takes a few seconds, "
                        "hang tight..."):
            prior = store.load_one(key) if key else None
            # Overwrite our own pending row on a re-submit; a change request
            # for an already-live org also replaces that org's row (and is
            # excluded from the collision scan — colliding with itself is the
            # point).
            updating = bool(prior) and (prior.get("status") == "pending"
                                        or bool(change_of))
            reg = store.existing_registry(
                exclude_key=key if (updating or change_of) else None)
            problems = S.validate_request(rec, existing_keys=reg["keys"])
            if problems:
                st.error("A couple of things to fix first:")
                for p in problems:
                    st.markdown(f"- {p}")
                return
            rec.submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            rec.submitted_by = rec.requested_by
            lucy_all = [_check_lucy(cid, cname)
                        for cid, cname in rec.channel_pairs()]
            if lucy_all[0].get("channel_id") and not rec.channel_id:
                rec.channel_id = lucy_all[0]["channel_id"]
            for j, c in enumerate(rec.extra_channels, start=1):
                if lucy_all[j].get("channel_id") and not c.get("channel_id"):
                    c["channel_id"] = lucy_all[j]["channel_id"]
            for j, p in enumerate(rec.channel_plans):
                if (not p.get("channel_id") and j < len(lucy_all)
                        and lucy_all[j].get("channel_id")):
                    p["channel_id"] = lucy_all[j]["channel_id"]
            try:
                where = store.update(rec) if updating else store.save(rec)
            except Exception as e:                   # noqa: BLE001
                st.error(f"Couldn't save your request — please tell Megan. ({e})")
                return
            ping = (False, "not pinged (local draft)")
            if where == "sheet":
                from automations.tracker_onboarding import request_notify
                ping = request_notify.notify(rec, lucy_all,
                                             change=bool(change_of))
            st.session_state["_req_done"] = {"rec": rec.to_json(),
                                             "lucy": lucy_all,
                                             "where": where, "ping": ping,
                                             "updated": updating,
                                             "change": bool(change_of)}
        st.rerun()


def _request_done_view() -> None:
    res = st.session_state.get("_req_done")
    if not res:
        return
    catalog = [t for t in S.tracker_catalog() if not t["opt_in"]]
    d = res["rec"]
    st.divider()
    if res.get("change"):
        st.success("🎉 Change request sent! Once Megan confirms, the boards "
                   "you picked replace the channel's current lineup. Nothing "
                   "else for you to do.")
    else:
        st.success(f"🎉 You're signed up{' (updated)' if res.get('updated') else ''}! "
                   "Once everything's hooked up, Lucy starts fetching your boards "
                   "every morning. Nothing else for you to do — go sell "
                   "something. 🐾🚀")
    titles = {t["id"]: f"{t['emoji']} {t['title']}" for t in catalog}
    plans = [p for p in (d.get("channel_plans") or [])]
    differing = plans and any(set(p.get("trackers") or [])
                              != set(d.get("trackers", [])) for p in plans)
    if differing:
        for p in plans:
            st.markdown(f"**{p.get('channel_name', '?')}** will get, every "
                        "morning:")
            st.markdown("\n".join(
                f"{i+1}. {titles.get(tid, tid)}"
                for i, tid in enumerate(p.get("trackers", []))) or "—")
    else:
        ch_names = " + ".join(
            [d["channel_name"]] + [c.get("channel_name", "?")
                                   for c in d.get("extra_channels", [])])
        st.markdown(f"**{ch_names}** will get, every morning:")
        st.markdown("\n".join(f"{i+1}. {titles.get(tid, tid)}"
                              for i, tid in enumerate(d.get("trackers", []))))
    # ICD-facing: keep it simple — the detailed per-channel diagnostics go to
    # Megan's ping/confirm view, not here.
    missing = [r for r in (res.get("lucy") or [])
               if r.get("status") in ("not_member", "not_found")]
    if missing:
        chs = " and ".join(f"**{r.get('channel_name') or 'your channel'}**"
                           for r in missing)
        st.warning(f"⚠️ One last thing: Lucy isn't in {chs} yet. Make sure "
                   "**Megan Hidalgo** is added — she'll add Lucy and get "
                   "your boards posting.")
    ping_ok, ping_note = res.get("ping", (False, ""))
    if res["where"] == "sheet" and not ping_ok:
        st.warning("Your request is saved, but the automatic heads-up to Megan "
                   f"didn't go out ({ping_note}) — please message her that you "
                   "signed up.")
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
    (Sheets client set) with no code secret; open in local-draft sandbox."""
    try:
        code = st.secrets.get("tracker_onboarding_code")
    except Exception:                                # noqa: BLE001
        code = None
    if not code:
        if store.get_client() is not None:
            st.error("Confirm view is locked: add a `tracker_onboarding_code` "
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
    st.markdown("## 📊 Alphalete Reporting by Lucy")
    st.markdown(f"### Confirm tracker sign-up — `{key}`")
    if not _gate():
        return
    d = store.load_one(key)
    if not d:
        st.error(f"No request found for {key!r}.")
        return
    rec = store.record_from_json(d)
    if rec.status == "wired":
        st.info("This one is already confirmed + wired — confirming again just "
                "re-applies it (safe / idempotent).")
    # A change request files under an org that already posts. Say so, and how
    # confirming behaves — or that it CAN'T apply, for hardcoded orgs.
    try:
        from automations.tableau_screenshots import slack_post as _sp
        already_live = key in getattr(_sp, "ORG_CHANNELS", {})
    except Exception:                                # noqa: BLE001
        already_live = False
    if already_live:
        if _form_managed(key):
            st.info(f"🔁 **Change request:** {rec.channel_name or key} already "
                    "posts trackers. Confirming REPLACES its current board "
                    "lineup with the set below.")
        else:
            st.error(f"⚠️ {key!r} is a HARDCODED org in slack_post.py — the "
                     "form can't update it (apply never clobbers hardcoded "
                     "orgs). Confirming here would be a no-op; ask Claude to "
                     "change the code instead.")
    st.markdown(f"- **Requested by:** {rec.requested_by or rec.owner}\n"
                f"- **ICD (OwnerVille):** {rec.owner}\n"
                f"- **Submitted:** {rec.submitted_at or '—'}")

    # ---- Lucy membership check (each channel) ---------------------------
    pairs0 = rec.channel_pairs()
    ck_key = f"_lucy_{key}"
    if ck_key not in st.session_state:
        st.session_state[ck_key] = [_check_lucy(c, n) for c, n in pairs0]
    lucy_all = st.session_state[ck_key]
    for r in lucy_all:
        (st.success if r.get("status") == "member" else st.warning)(_lucy_line(r))
    if st.button("🔄 Re-check Lucy's membership"):
        st.session_state[ck_key] = [
            _check_lucy(st.session_state.get(f"_cf_cid_{i}", c),
                        st.session_state.get(f"_cf_cname_{i}", n))
            for i, (c, n) in enumerate(pairs0)]
        st.rerun()

    # ---- channels (fixable) ---------------------------------------------
    edited_pairs: list = []
    for i, (cid0, cname0) in enumerate(pairs0):
        tag = "" if len(pairs0) == 1 else f" — channel {i + 1}"
        c1, c2 = st.columns(2)
        with c1:
            cid = st.text_input(
                f"Channel ID *{tag}",
                value=(lucy_all[i].get("channel_id") or cid0
                       if i < len(lucy_all) else cid0),
                key=f"_cf_cid_{i}")
        with c2:
            cname = st.text_input(f"Channel name *{tag}", value=cname0,
                                  key=f"_cf_cname_{i}")
        if (rec.channel_plans and i < len(rec.channel_plans)
                and set(rec.channel_plans[i].get("trackers") or [])
                != set(rec.trackers)):
            _t = {t["id"]: t["title"]
                  for t in S.tracker_catalog()}
            st.caption("This channel's picks: " + ", ".join(
                _t.get(x, x)
                for x in rec.channel_plans[i].get("trackers") or []))
        edited_pairs.append((cid.strip(), cname.strip()))

    # ---- trackers (editable, drag & drop) -------------------------------
    st.markdown("#### Trackers")
    catalog = [t for t in S.tracker_catalog() if not t["opt_in"]]
    labels = {t["id"]: f"{t['emoji']} {t['title']}" for t in catalog}
    rev = {v: k for k, v in labels.items()}
    in_ids = [tid for tid in rec.trackers if tid in labels]
    out_ids = [t["id"] for t in catalog if t["id"] not in in_ids]
    if _HAS_SORT:
        st.caption("Drag between the buckets to add/remove, and within "
                   "'Posting' to set the order — top posts first.")
        buckets = [
            {"header": "✅ Posting (top = first)",
             "items": [labels[i] for i in in_ids]},
            {"header": "🚫 Not posting",
             "items": [labels[i] for i in out_ids]},
        ]
        result = sort_items(buckets, multi_containers=True,
                            direction="vertical", key=f"cf_sort_{key}")
        trackers = [rev[l] for l in result[0]["items"] if l in rev]
    else:
        want = {tid: i + 1 for i, tid in enumerate(in_ids)}
        picked: list = []
        for i, t in enumerate(catalog):
            oc1, oc2 = st.columns([6, 1])
            with oc1:
                on = st.checkbox(f"{t['emoji']} {t['title']}",
                                 value=(t["id"] in want), key=f"cf_trk_{t['id']}")
            with oc2:
                order = st.number_input("order", 1, 99,
                                        want.get(t["id"], len(want) + i + 1),
                                        key=f"cf_ord_{t['id']}",
                                        label_visibility="collapsed",
                                        disabled=not on)
            if on:
                picked.append((t["id"], int(order)))
        trackers = [tid for tid, _ in sorted(picked, key=lambda x: x[1])]

    # ---- confirm + wire --------------------------------------------------
    st.divider()
    if any(r.get("status") != "member" for r in lucy_all):
        st.caption("You can confirm anyway, but nothing will actually post "
                   "to a channel until Lucy is invited to it.")
    if st.button("✅ Confirm + wire up", type="primary"):
        # Per-channel board subsets ride through the confirm: same channels
        # (with any id/name fixes), each keeping its own picks filtered to
        # whatever survives Megan's final board set.
        plans2 = []
        if rec.channel_plans:
            for i, (cid, cname) in enumerate(edited_pairs):
                src = (rec.channel_plans[i]
                       if i < len(rec.channel_plans) else {})
                keep = src.get("trackers") or trackers
                plans2.append({"channel_id": cid, "channel_name": cname,
                               "trackers": [t for t in trackers if t in keep]})
        rec2 = S.TrackerRecord(
            key=key, owner=rec.owner, channel_id=edited_pairs[0][0],
            channel_name=edited_pairs[0][1],
            extra_channels=[{"channel_id": c, "channel_name": n}
                            for c, n in edited_pairs[1:]],
            channel_plans=plans2,
            trackers=trackers,
            status="wired", requested_by=rec.requested_by,
            submitted_by="Megan (confirm)",
            submitted_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        reg = store.existing_registry(exclude_key=key)
        problems = S.validate(rec2, existing_keys=reg["keys"],
                              existing_channels=reg["channels"])
        if problems:
            st.error("Fix these before confirming:")
            for p in problems:
                st.markdown(f"- {p}")
            return
        try:
            where = store.update(rec2)
        except Exception as e:                       # noqa: BLE001
            st.error(f"Couldn't save: {e}")
            return
        wired = _enqueue_onboard(key, post=False) if where == "sheet" else (False, "local")
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
    st.success(f"Confirmed {d['key']} — saved as wired.")
    if res["where"] == "sheet":
        wired_ok, wired_note = res.get("wired", (False, ""))
        if wired_ok:
            st.success("✅ Auto-wiring into the daily tracker run — the mini is "
                       "applying it now (live in the next run, ~1–2 min). "
                       "Remember: commit onboarded_trackers.json to make it "
                       "survive the morning self-update.")
        else:
            st.warning(f"Saved, but couldn't auto-wire ({wired_note}). "
                       "Fallback:")
            st.code(f"python -m automations.tracker_onboarding.apply --only {d['key']} --write",
                    language="bash")
        if st.button(f"▶️ Post to {d['channel_name']} now", type="primary"):
            ok, note = _enqueue_onboard(d["key"], post=True)
            if ok:
                st.success(f"Queued — the mini will post to {d['channel_name']} "
                           "in ~1–2 min. Watch the channel.")
            else:
                st.error(f"Couldn't queue the post: {note}")
    else:
        st.code(f"python -m automations.tracker_onboarding.apply --only {d['key']} --write",
                language="bash")


# ---------------------------------------------------------------------------
_diag = _inject_gs_client()
_inject_slack_token()
# ?debug=1 shows a KEYS-ONLY readout of what the app can see in its secrets
# (never any secret value) — so a "why is it still a local draft?" is answerable
# without guessing. Safe to leave in; invisible unless the query param is set.
try:
    _dbg = str(st.query_params.get("debug", "")).lower() in ("1", "true", "yes")
except Exception:
    _dbg = False
if _dbg:
    st.warning("🔧 secrets diagnostic (keys only, no values):")
    st.json(_diag)
try:
    _confirm = str(st.query_params.get("confirm", "")).strip()
except Exception:
    _confirm = ""
if _confirm:
    confirm_view(_confirm)
else:
    request_view()
