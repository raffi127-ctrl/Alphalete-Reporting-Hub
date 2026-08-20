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


# ---------------------------------------------------------------------------
# ICD self-serve request view (the default page)
# ---------------------------------------------------------------------------

def request_view() -> None:
    st.markdown("## 📊 Alphalete Reporting by Lucy")
    st.markdown("### Daily Sales Tracker Sign-Up")
    st.caption("Pick the boards you want and Lucy will post fresh "
               "screenshots to your Slack channel every morning.")

    # ---- 1. You & your channel -------------------------------------------
    st.divider()
    st.markdown("### 1. Who are you & where do we post?")
    requested_by = st.text_input(
        "Your name (what you go by) *",
        help="Just what we should call you — the official OwnerVille "
             "spelling goes in the next box.")
    owner = st.text_input(
        "ICD Name as it appears in OwnerVille *",
        help="Your name exactly as OwnerVille shows it — this is how we file "
             "your office.")
    n_ch = st.number_input(
        "How many Slack channels should Lucy post in?", 1, 5, 1,
        help="Most offices use 1. Add more if you also want the boards in "
             "another channel (like a leaders channel). Every channel gets "
             "the same boards.")
    chan_pairs: list = []
    for i in range(int(n_ch)):
        if int(n_ch) > 1:
            st.markdown(f"**Channel {i + 1}**")
        cname = st.text_input(
            "Slack channel name *", placeholder="#your-office-sales",
            key=f"ch_name_{i}",
            help="The channel where you want the boards posted each morning.")
        cid = st.text_input(
            "Slack Channel ID *", placeholder="C0ABC12DE", key=f"ch_id_{i}",
            help="This is a CODE (letters + numbers) that starts with C — NOT "
                 "the channel's name. To find it: in Slack, click the "
                 "channel's name at the top of the screen, scroll to the very "
                 "bottom of the pop-up, and copy the Channel ID shown there.")
        if SLACK_ID_IMG.exists():
            with st.expander("Where do I find my Channel ID?"):
                st.caption("In Slack, click the channel's name at the top of "
                           "the screen, scroll to the bottom of the pop-up, "
                           "and copy the Channel ID:")
                # 397 = half the source's 794px — pixel-perfect on retina
                # screens. Bigger = the browser upscales and it goes soft.
                st.image(str(SLACK_ID_IMG), width=397)
        chan_pairs.append((cid.strip(), cname.strip()))
    st.info("**Important:** **Megan Hidalgo** must be added to **EACH** Slack "
            "channel you want the Tableau trackers posted in — she'll add "
            "Lucy (the bot that posts the boards) from there.")

    # ---- 2. Pick your boards ---------------------------------------------
    st.divider()
    st.markdown("### 2. Pick your tracker boards")
    # Only UNIVERSAL national boards are offered. Opt-in boards (opt_in_only in
    # tableau_screenshots.pages, e.g. order_tiered_bonus) are OWNER-SCOPED —
    # posting one to a different office's channel shows THAT owner's numbers
    # (the jamis→Atef isolation failure, 2026-08-01) — so they are deliberately
    # NOT options here.
    catalog = [t for t in S.tracker_catalog() if not t["opt_in"]]
    if not catalog:
        st.error("Couldn't load the tracker list — please tell Megan the "
                 "sign-up form is down.")
    st.caption("Check every board you want. Tap View preview to see exactly "
               "what would land in your channel.")
    picked: list = []
    for t in catalog:
        on = st.checkbox(f"{t['emoji']} **{t['title']}**", value=False,
                         key=f"trk_{t['id']}")
        pv = _preview_path(t["id"])
        if pv is not None:
            with st.expander("View preview"):
                st.image(str(pv), use_container_width=True)
        if on:
            picked.append(t["id"])

    # ---- 3. Order them (drag & drop) -------------------------------------
    labels = {t["id"]: f"{t['emoji']} {t['title']}" for t in catalog}
    rev = {v: k for k, v in labels.items()}
    st.divider()
    st.markdown("### 3. Put them in order")
    if picked and _HAS_SORT:
        st.caption("This is the order the Tableau images will post in each "
                   "morning in your Slack channel — drag to rearrange, top "
                   "posts first.")
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
    key = S.slug_from(owner)
    rec = S.TrackerRecord(
        key=key, owner=owner.strip(),
        channel_id=chan_pairs[0][0], channel_name=chan_pairs[0][1],
        extra_channels=[{"channel_id": c, "channel_name": n}
                        for c, n in chan_pairs[1:]],
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
    if not trackers:
        missing.append("at least one tracker board")
    if missing:
        st.warning("⚠️ **Still needed before you can submit:** "
                   + ", ".join(missing) + ".")
    if st.button("📨 Send my sign-up to Megan", type="primary",
                 disabled=bool(missing)):
        prior = store.load_one(key) if key else None
        updating = bool(prior) and prior.get("status") == "pending"
        reg = store.existing_registry(exclude_key=key if updating else None)
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
        try:
            where = store.update(rec) if updating else store.save(rec)
        except Exception as e:                       # noqa: BLE001
            st.error(f"Couldn't save your request — please tell Megan. ({e})")
            return
        ping = (False, "not pinged (local draft)")
        if where == "sheet":
            from automations.tracker_onboarding import request_notify
            ping = request_notify.notify(rec, lucy_all)
        st.session_state["_req_done"] = {"rec": rec.to_json(), "lucy": lucy_all,
                                         "where": where, "ping": ping,
                                         "updated": updating}
        st.rerun()

    _request_done_view(catalog)


def _request_done_view(catalog) -> None:
    res = st.session_state.get("_req_done")
    if not res:
        return
    d = res["rec"]
    st.divider()
    st.success(f"🎉 You're signed up{' (updated)' if res.get('updated') else ''}! "
               "Once everything's hooked up, Lucy starts fetching your boards "
               "every morning. Nothing else for you to do — go sell "
               "something. 🐾🚀")
    titles = {t["id"]: f"{t['emoji']} {t['title']}" for t in catalog}
    ch_names = " + ".join(
        [d["channel_name"]] + [c.get("channel_name", "?")
                               for c in d.get("extra_channels", [])])
    st.markdown(f"**{ch_names}** will get, every morning:")
    st.markdown("\n".join(f"{i+1}. {titles.get(tid, tid)}"
                          for i, tid in enumerate(d.get("trackers", []))))
    missing = [r for r in (res.get("lucy") or [])
               if r.get("status") in ("not_member", "not_found")]
    if missing:
        lines = "\n".join(f"- {_lucy_line(r)}" for r in missing)
        st.warning(f"⚠️ Lucy can't post everywhere yet:\n{lines}\n\nJust make "
                   "sure **Megan Hidalgo** is added to **each** of those "
                   "channels — she'll add Lucy from there.")
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
        rec2 = S.TrackerRecord(
            key=key, owner=rec.owner, channel_id=edited_pairs[0][0],
            channel_name=edited_pairs[0][1],
            extra_channels=[{"channel_id": c, "channel_name": n}
                            for c, n in edited_pairs[1:]],
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
