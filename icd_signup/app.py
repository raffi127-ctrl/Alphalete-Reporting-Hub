"""Alphalete Reporting by Lucy — join Lucy Eco (ICD self-serve sign-up).

Megan 2026-09-13: "they should be 'signing' up first and then I'm alerted."
Before this, enrolling an office started with US -- someone typed them into the
roster, minted a key and sent a link, then collected their hours and their
OwnerVille name over Slack afterwards. This asks the office once, up front, and
turns the request into a real office only when Megan approves it.

WHAT THIS FORM NEVER ASKS FOR: a password. The whole design rests on the
SaraPlus login staying on their own laptop, and a sign-up page that asked for
one would quietly undo that -- so the login is collected by the installer, on
their machine, and travels nowhere.

Their answers land on the 'ICD Signup' tab of the relay workbook as PENDING and
ping Megan in the corrections channel. NOTHING is created until she runs
`python -m automations.icd_signup.approve <office>` -- no key, no roster entry,
no push -- so an abandoned form leaves nothing behind.

Run locally:   .venv/bin/streamlit run icd_signup/app.py
On the web:    Streamlit Community Cloud.

Secrets: [gcp_service_account]/[gcp_oauth] for the relay workbook and
`slack_user_token` (TOP-LEVEL) for the ping. Without Sheets creds it saves a
local draft. ICD_SIGNUP_LOCAL_ONLY=1 forces that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import json

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.icd_signup import schema as S, store          # noqa: E402
from automations.shared import onboarding_ui as ui             # noqa: E402

MAX_CHANNELS = 3      # the installer allows 4; three is plenty to type
MAX_KNOCKS = 3

st.set_page_config(page_title="Join Lucy ECOsystem", page_icon="🛰️")
ui.render_header(
    "Join Lucy ECOsystem",
    "Your office's numbers, in your team's Slack channel, all day long.")

ui.inject_slack_token()

# --- the approve view -------------------------------------------------------
# Reached from the link in Megan's Slack ping: ?approve=<office>. Gated by the
# same access code the dispositions confirm view uses, because this is the
# switch that puts an office's numbers in front of their whole team.
#
# The click does NOT do the approving. It marks the row, and the poster on
# Lucy 3 does the real work -- resolving channels, checking Lucy is in each
# one, writing the sign-off -- and reports back in the thread. This app cannot
# do that itself: it runs on Streamlit Cloud with a token that is a stranger
# to the workspace, which is exactly how the sign-up ping failed.
_approve_for = (st.query_params.get("approve") or "").strip().lower()
if _approve_for:
    from automations.icd_signup import store as _store

    st.title("Approve an office")
    try:
        _code = st.secrets.get("disposition_signup_code")
    except Exception:  # noqa: BLE001
        _code = None
    if not _code:
        st.error("This view is locked: add a `disposition_signup_code` secret.")
        st.stop()

    _rec = _store.get(_approve_for)
    if not _rec:
        st.error("No sign-up for **%s**." % _approve_for)
        st.stop()

    st.markdown("### %s — `%s`" % (_rec.owner, _rec.office_key))
    _rooms = []
    for _c in list(_rec.alert_channels) + [d.get("channel") for d
                                           in _rec.knocks_destinations]:
        if _c and _c not in _rooms:
            _rooms.append(_c)
    st.markdown("**Lucy has to be in every one of these before you approve:**")
    for _c in _rooms:
        st.markdown("- `%s`" % _c)
    st.caption("She cannot post into a room she has not been invited to, and "
               "approving one she is not in signs off a channel that will "
               "stay silent.")
    st.divider()

    if _rec.status == "approved":
        st.success("**%s** is already approved." % _rec.owner)
        st.stop()

    _typed = st.text_input("Access code", type="password")
    _ok = st.checkbox("Lucy is in every channel listed above")
    if st.button("Approve this office", type="primary",
                 disabled=not _ok):
        if _typed != _code:
            st.error("That access code is not right.")
        elif _store.request_approval(_rec.office_key, by="the approve link"):
            st.success(
                "**Sent.** Lucy will switch %s on within a couple of minutes "
                "and post the result in #claudecorrections — including if "
                "anything was wrong." % _rec.owner)
        else:
            st.error("Could not record that. Run it from the terminal "
                     "instead: `python -m automations.icd_signup.approve %s`"
                     % _rec.office_key)
    st.stop()


# THE SHEETS CLIENT, BUILT FROM STREAMLIT'S SECRETS. Without this the store
# falls back to authenticating from credential files in the repo -- which do
# not exist on Community Cloud, so every submission threw and was silently
# written to a local draft on a disposable filesystem. Megan's first live
# sign-up was lost exactly that way (2026-09-13), and the page told her it had
# worked. Mirrors disposition_signup/app.py, which had it right all along.
_gc, _diag = ui.build_gs_client("ICD_SIGNUP_LOCAL_ONLY")
if _gc is not None:
    store.set_client(_gc)
if st.query_params.get("debug") == "1":
    # Keys only, never values -- see onboarding_ui.build_gs_client.
    st.json(_diag)

# WHAT LUCY ECO IS, before what it does. An owner arriving here has been sent
# a link by somebody and has no idea what they are being offered -- the page
# used to open on "get your sales in Slack", which reads like a product they
# have to evaluate rather than the reporting they already half know about.
st.markdown("**What your office gets**")
c1, c2, c3 = st.columns(3)
c1.markdown("🔍 **Credit checks**")
c2.markdown("💰 **Sales**")
c3.markdown("🚪 **Knocks & dispositions**")
st.write("")

st.warning(
    "**NOTHING POSTS while your computer is off.** Lucy reads your numbers "
    "from the machine in your office, so it has to be **on, awake and on "
    "wifi** during your selling hours. A laptop that is shut or asleep means "
    "your channel goes quiet until it wakes up.\n\n"
    "Nothing is lost when that happens — SaraPlus and OwnerVille keep "
    "counting, and the first check-in after it wakes hands over the whole "
    "day. It arrives late, not missing.")

st.divider()

# NOT st.form, deliberately. A form batches every widget until submit, so the
# Saturday checkbox could not grey out the Saturday times under it -- an
# office unticking it was still shown two boxes asking for hours it had just
# said it does not work (Megan 2026-09-13). A bordered container looks the
# same and re-runs on every change.
with st.container(border=True):
    st.subheader("Who you are")
    owner = st.text_input("Your full name",
                          placeholder="e.g. Cyrus Wade")
    contact = st.text_input(
        "Email or phone, in case we need to reach you",
        help="Your setup link appears on this page the moment you submit — "
             "nothing is emailed. This is so the reporting team can reach you "
             "if something goes wrong.")
    ov_name = st.text_input(
        "How your name is spelled in OwnerVille",
        placeholder="Leave blank if it is the same as above",
        help="OwnerVille often spells names differently, and we would rather "
             "ask than guess.")

    st.subheader("The computer it will run on")
    st.caption("It has to be a **desktop that stays on in the office** — an "
               "iMac, a Mac mini or a Mac Studio. The installer will not run "
               "on a laptop: a closed lid means your channel goes quiet, and "
               "that is the problem this has hit most often.")
    platform = st.radio("Is it a Mac or a Windows PC?",
                        options=["mac", "windows"],
                        format_func=lambda p: "Mac" if p == "mac" else "Windows PC",
                        horizontal=True)

    st.subheader("Your selling hours")
    st.caption("Nothing posts outside these — this is how Lucy knows your reps "
               "are actually out.")
    tz = st.selectbox("Your timezone",
                      options=[z for z, _label in S.TIMEZONES],
                      format_func=S.tz_label)
    def _time_picker(col, label, default, key, disabled=False):
        return col.selectbox(label, options=list(S.TIME_CHOICES),
                             index=S.TIME_CHOICES.index(default),
                             format_func=S.time_label, key=key,
                             disabled=disabled)

    c1, c2 = st.columns(2)
    day_start = _time_picker(c1, "Monday–Friday, start", "13:30", "d_start")
    day_end = _time_picker(c2, "Monday–Friday, end", "20:30", "d_end")
    saturday = st.checkbox("We sell on Saturdays too", value=True)
    c3, c4 = st.columns(2)
    sat_start = _time_picker(c3, "Saturday, start", "10:45", "s_start",
                             disabled=not saturday)
    sat_end = _time_picker(c4, "Saturday, end", "17:00", "s_end",
                           disabled=not saturday)

    st.subheader("Where your credit checks and sales should post")
    st.caption("Most offices pick one channel. Add a second if the owners' "
               "room and the rep channel should both get them.")
    st.caption("A channel **ID** is safest — in Slack, click the channel name "
               "at the top, scroll to the bottom of the About tab, and copy "
               "the ID (it looks like C09AVM17PAR). A #name works too.")
    # SAID TWICE ON PURPOSE (Megan 2026-09-13: "it needs to be on there twice
    # so they actually read it"). Here, while they are choosing the room, and
    # again above Send where it is the thing to go and do. It is the most
    # common reason a sign-up stalls, and the cost of repeating it is one line
    # somebody skims -- the cost of missing it is an office sitting silent
    # waiting on us.
    st.info(
        "**Add Megan and Eve to any channel you name here.** They cannot "
        "switch your alerts on for a channel they are not in.")
    alert_channels = []
    for i in range(MAX_CHANNELS):
        label = ("Channel for alerts" if i == 0
                 else "Another channel (optional)")
        val = st.text_input(label, key="alert_ch_%d" % i,
                            placeholder="C09AVM17PAR  or  #palace-sales")
        alert_channels.append(val.strip())

    st.subheader("Your knocks and dispositions board")
    st.caption("This is the board showing who is out, who is knocking and who "
               "has gone quiet. Each channel can post on its own schedule.")
    knocks = []
    for i in range(MAX_KNOCKS):
        c1, c2 = st.columns([3, 2])
        label = ("Channel for the board" if i == 0
                 else "Another channel (optional)")
        ch = c1.text_input(label, key="kn_ch_%d" % i,
                           placeholder="Leave blank if not needed"
                           if i else "C09AVM17PAR  or  #palace-sales")
        cad = c2.selectbox("How often?", key="kn_cad_%d" % i,
                           options=[c[0] for c in S.KNOCKS_CHOICES if c[0] != -1],
                           format_func=lambda v: dict(S.KNOCKS_CHOICES)[v],
                           index=1)
        knocks.append((ch.strip(), int(cad)))
    st.caption("Do not want this board at all? Leave every channel above "
               "blank.")

    # LAST THING BEFORE THEY SEND, because it is the one action of theirs
    # that has to happen OUTSIDE this page -- sitting up beside the channel
    # boxes, it read as advice about typing rather than a thing to go and do.
    #
    # Only their half: Lucy also has to be in the room, and getting her there
    # is ours (Megan 2026-09-13: "this reads like they need to add lucy which
    # isn't the case").
    st.info(
        "**Before you send this — add Megan and Eve to every channel you "
        "named above.** They cannot switch your alerts on for a channel they "
        "are not in, and that is the most common reason a sign-up stalls.")

    submitted = st.button("Send my sign-up", type="primary")

if submitted:
    alerts = [c for c in alert_channels if c]
    dests = [{"channel": c, "cadence_min": n,
              "label": dict(S.KNOCKS_CHOICES).get(n, "")}
             for c, n in knocks if c]
    # -1 is the installer's "no board at all". Deriving it from an empty list
    # keeps ONE way of saying that, rather than a checkbox that can disagree
    # with the channels underneath it.
    first_cadence = dests[0]["cadence_min"] if dests else -1
    summary = ", ".join(alerts) or "(not sure yet)"
    if dests:
        summary += "  ·  board: " + ", ".join(
            "%s %s" % (d["channel"], d["label"]) for d in dests)

    rec = S.IcdSignup(
        owner=owner, office_label="", platform=platform, timezone=tz,
        day_start=day_start.strip(), day_end=day_end.strip(),
        saturday=bool(saturday),
        sat_start=sat_start.strip(), sat_end=sat_end.strip(),
        ov_name=ov_name.strip(), knocks_cadence=first_cadence,
        wanted_channels=summary, contact=contact.strip(),
        alert_channels_json=json.dumps(alerts),
        knocks_json=json.dumps(dests))
    problems = rec.problems()
    if problems:
        for p in problems:
            st.error(p)
    else:
        saved, link, landed = store.submit_and_key(rec)

        if not landed:
            # NOTHING WAS SAVED. Saying "that is in" here is how an office
            # waits a week for a reply nobody can send -- there is no row, no
            # key and no ping, and only they know they tried.
            st.error(
                "**Something went wrong on our end and your sign-up was not "
                "saved.**\n\n"
                "Nothing you did caused this, and nothing was lost on your "
                "computer. Please tell Megan or Eve that the Lucy ECOsystem form "
                "not saving — they can add you by hand in a couple of "
                "minutes.")
            st.stop()

        # THE FORM DOES NOT POST TO SLACK. It used to, and it never arrived:
        # this app runs on Streamlit Cloud with whatever token is in its
        # secrets, in a workspace it is otherwise a stranger to -- a bot that
        # is not in the channel, a scope nobody granted, a secret that
        # expires, and every one of those is silent from here.
        #
        # The poster on Lucy 3 announces it instead, within a couple of
        # minutes, from the machine that already holds Lucy's token and
        # already posts to that channel [[post.notify_new_signups]]. One path,
        # and it is the one that was already working.

        # NOT "that is in" (Megan 2026-09-13: "it shouldn't say 'thanks -
        # that's it' when there is another step"). Their sign-up is saved, but
        # the computer is not set up and that is the half that matters -- a
        # green tick reads as finished and is how somebody closes the tab.
        st.success(
            "Got it, %s — now there is one more step."
            % (owner.split()[0] if owner else "thanks"))

        if link:
            # THEY SET UP NOW, NOT AFTER WE GET ROUND TO THEM. The key is
            # theirs the moment they sign up; approval decides where their
            # numbers POST, not whether they can install.
            st.markdown("### Set your computer up now")
            st.markdown(
                "Do this on the office computer it will run on. It takes "
                "about five minutes and asks you for your SaraPlus and "
                "OwnerVille logins **on that machine** — they stay there.")
            st.link_button("Open my setup page", link, type="primary")
            st.caption("This link is yours alone — it carries your office's "
                       "code. Please do not forward it.")
            st.warning(
                "**Save this link before you close the page.** Email it to "
                "yourself, or open it on the office computer now. If you lose "
                "it the reporting team can send it again.")
            st.markdown(
                "Once it is done, your computer starts handing in your "
                "numbers straight away. They begin appearing in your Slack "
                "channel as soon as the reporting team approves where they "
                "should go.")
            st.markdown("**Two things to do now:**")
            st.markdown(
                "1. **Add Megan and Eve** to every channel you named — "
                "they cannot switch it on for a room they are not in.\n"
                "2. **Leave that computer on** during selling hours — on "
                "power, lid open, on wifi. Nothing posts while it is asleep.")
        else:
            # THE FALLBACK, shown when no key could be written -- Sheets was
            # unreachable, or the relay refused. Their answers are saved
            # either way, and Megan's alert says to send the link by hand, so
            # what they need here is to know it landed and stop waiting for a
            # screen that is not coming.
            st.markdown(
                "**Thanks for joining Lucy ECOsystem.** We will process "
                "your request and reach out soon.")
