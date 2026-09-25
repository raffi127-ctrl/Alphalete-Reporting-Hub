"""The ApplicantStream offices the Applicant Push works — one declarative table.

WHY A TABLE: the push started as a single-office job (Carlos, 11580) with the
office id hard-coded in three modules and every artefact it writes keyed by DATE
alone. Adding a second office (Atef, 23467 — Carlos asked 2026-08-26 for his
resumes to be pushed on the same schedule) is NOT a new login: the flow signs in
with the shared fleet 'Raf – Captain' session and then SWITCHES office, and that
account can see both. What it needs is NAMESPACING — two offices sharing
`output/oat-flagged-<date>.json`, `/tmp/rp_cdp_profile` or the 'OAT Walk Diag'
tab would overwrite each other's queue state and could post one office's
applicants under the other's name.

So each office declares its own: browser profile + debug port, per-day file
suffix, Sheet diag tabs, log stem, and Hub/schedule ids. 11580 keeps EMPTY /
unchanged values on purpose — Carlos's live files, tabs, log and Hub card do not
move, so nothing in flight breaks on the day this ships.

`activate(office_id)` points resume_pushing + oat_processing at one office for
the life of the process. Only ONE office runs per process — the wrapper walks
them one tick at a time (see deploy/applicant_push.sh) rather than running two
warm AppStream sessions at once, which has never been proven safe and whose
failure mode (a crossed session sending one office's applicants from the other's
queue) is irreversible.
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

# Port 9246 is deliberately skipped: resume_pushing's one-off `--office` override
# claims it, so a human running a manual one-off can never collide with a
# scheduled office here.
# THE ONLY LOGIN THIS JOB MAY USE (Megan 2026-09-02: "the resume pushing can
# ONLY HAPPEN on the Resume pushing login"). Every row states it, activate()
# enforces it, and test_offices pins it. The account is scoped to the offices the
# push is allowed to touch, and that permission — not a UI control, not a table —
# is what bounds an irreversible send.
RESUME_ACCOUNT = "lucyresume"

OFFICES = {
    "11580": {
        "office_id": "11580",
        "hint": "CARLOS HIDALGO",
        "owner": "Carlos Hidalgo",
        "label": "office 11580 · Carlos Hidalgo — ATT Program",
        "short": "office 11580, Carlos",
        # Scoped account (Megan 2026-08-31). The two ROTATION offices sign in
        # as LucyResume, which can see ONLY these two. On 8/30 the push sent to
        # ~22 offices: it bounds itself with an office SWITCH, but the v2 batch
        # select-all -> Send To AI reaches whatever the ACCOUNT can see, and the
        # shared Raf-Captain login sees all 28. Send-to-AI is irreversible, so
        # the bound has to be a permission, not a UI control.
        "account": "lucyresume",
        # EMPTY = Carlos's existing filenames stay byte-identical. Do not change.
        "suffix": "",
        "cdp_profile": "/tmp/rp_cdp_profile",
        "cdp_port": "9245",
        "cdp_kill_pat": "rp_cdp_profile",
        "walk_diag_tab": "OAT Walk Diag",
        "push_diag_tab": "Applicant Push Diag",
        "log_stem": "applicant-push",
        "hub_report_id": "applicant_push",
        "hub_display": "Applicant Push",
        # #alphaletegp-recruiting. Stated EXPLICITLY rather than left blank to
        # fall through to summary.CHANNEL_ID's default: a blank meant activate()
        # skipped the assignment, so a process that had already activated another
        # office kept ITS channel — i.e. Carlos's to-do list posting into Atef's
        # channel. Every office names its own channel; none inherits.
        "post_channel": "C09L1S3MQ1E",
        "post_todo": True,
        # Carlos and Atef are the only offices that text an applicant when the
        # override is unavailable (Carlos, 2026-08-29).
        "allow_retext": True,
        "remove_blocked_read": False,
        # Carlos, 2026-08-27: "in my specific office, if they don't have a phone
        # number on the resume, you don't remove them. You leave them there."
        # So the confirmed-uncontactable removal (config.REMOVE_NO_PHONE, added
        # the same day) is OFF here: those applicants stay in the OAT queue and
        # keep flagging to the manual to-do list, exactly as before. Atef's office
        # keeps the removal. This is a per-office POLICY difference, not a bug —
        # do not "fix" the inconsistency by aligning them.
        "remove_no_phone": False,
    },
    "23467": {
        "office_id": "23467",
        "hint": "ATEF CHOUDHURY",
        "owner": "Atef Choudhury",
        "label": "office 23467 · Atef Choudhury — Domin8 Acquisitions",
        "short": "office 23467, Atef",
        # Scoped account (Megan 2026-08-31). The two ROTATION offices sign in
        # as LucyResume, which can see ONLY these two. On 8/30 the push sent to
        # ~22 offices: it bounds itself with an office SWITCH, but the v2 batch
        # select-all -> Send To AI reaches whatever the ACCOUNT can see, and the
        # shared Raf-Captain login sees all 28. Send-to-AI is irreversible, so
        # the bound has to be a permission, not a UI control.
        "account": "lucyresume",
        "suffix": "-23467",
        "cdp_profile": "/tmp/rp_cdp_23467",
        "cdp_port": "9247",
        "cdp_kill_pat": "rp_cdp_23467",
        "walk_diag_tab": "OAT Walk Diag 23467",
        "push_diag_tab": "Applicant Push Diag 23467",
        "log_stem": "applicant-push-23467",
        "hub_report_id": "applicant_push_atef",
        "hub_display": "Applicant Push (Atef)",
        # Atef's OWN recruiting channel (private):
        # #23467-domin8-acquisitions-inc-atef-choudhury. Carlos created it and
        # added Megan + both Lucy apps on 2026-08-26; Megan: "that's where his
        # unable-to-push update will land". So Atef's noon/4pm to-do posts here,
        # NOT into Carlos's #alphaletegp-recruiting — one office's applicant names
        # never show up in another office's channel.
        "post_channel": "C0B85KRS5FU",
        "post_todo": True,
        # Texting OFF since 9/12 (Carlos) — 11580 is the only texting office.
        "allow_retext": False,
        "remove_blocked_read": False,
        # Atef's office keeps the confirmed-uncontactable removal (a resume that
        # opened and carries no number, or no resume at all). Never fires on a
        # BLOCKED read — that is our failure, and it retries.
        # 9/12 (Carlos): no-number applicants STAY in Atef's queue now, same as 11580.
        "remove_no_phone": False,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29). Added to run the same lazy-removal
    # audit we ran on Atef: restore a day of "Removed Apps at Processing" and let
    # the push re-decide each one. It is deliberately NOT in ROTATION — nothing
    # scheduled touches Jamis's office — and post_todo is OFF so his applicant
    # names never land in a Slack channel that was not set up for them.
    "19592": {
        "office_id": "19592",
        "hint": "JAMIS GARAY",
        "owner": "Jamis Garay",
        "label": "office 19592 · Jamis Garay — MIDSPIRE INC",
        "short": "office 19592, Jamis",
        # THE RESUME LOGIN, like every other row (Megan 2026-09-02: "the resume
        # pushing can ONLY HAPPEN on the Resume pushing login"). This said
        # "primary" because Lucy Resume Pushing cannot SEE this office — but
        # that is the guarantee working, not a reason to go around it. An
        # office the resume login cannot see is an office the pusher cannot
        # push, and send-to-AI is irreversible. The run fails here instead.
        "account": "lucyresume",
        "suffix": "-19592",
        "cdp_profile": "/tmp/rp_cdp_19592",
        "cdp_port": "9248",
        "cdp_kill_pat": "rp_cdp_19592",
        "walk_diag_tab": "OAT Walk Diag 19592",
        "push_diag_tab": "Applicant Push Diag 19592",
        "log_stem": "applicant-push-19592",
        "hub_report_id": "applicant_push_jamis",
        "hub_display": "Applicant Push (Jamis)",
        # Stated explicitly so a process that already activated another office
        # cannot keep ITS channel; with post_todo False nothing posts anyway.
        "post_channel": "C09L1S3MQ1E",
        "post_todo": False,
        # Diagnostic office: never texts anyone. Only Carlos's and Atef's do.
        "allow_retext": False,
        "remove_blocked_read": False,
        # Matches the policy for every office that is not Carlos's: a resume that
        # opens and carries no number is a confirmed-uncontactable removal.
        "remove_no_phone": False,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "23411": {
        "office_id": "23411",
        "hint": "RASHAD REED",
        "owner": "Rashad Reed",
        "label": "office 23411 · Rashad Reed — Elevate Specialized Acquisitions, Inc",
        "short": "office 23411, Rashad",
        # THE RESUME LOGIN, like every other row (Megan 2026-09-02: "the resume
        # pushing can ONLY HAPPEN on the Resume pushing login"). This said
        # "primary" because Lucy Resume Pushing cannot SEE this office — but
        # that is the guarantee working, not a reason to go around it. An
        # office the resume login cannot see is an office the pusher cannot
        # push, and send-to-AI is irreversible. The run fails here instead.
        "account": "lucyresume",
        "suffix": "-23411",
        "cdp_profile": "/tmp/rp_cdp_23411",
        "cdp_port": "9249",
        "cdp_kill_pat": "rp_cdp_23411",
        "walk_diag_tab": "OAT Walk Diag 23411",
        "push_diag_tab": "Applicant Push Diag 23411",
        "log_stem": "applicant-push-23411",
        "hub_report_id": "applicant_push_rashad",
        "hub_display": "Applicant Push (Rashad)",
        "post_channel": "C09L1S3MQ1E",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "22524": {
        "office_id": "22524",
        "hint": "HAYTHAM NAGI",
        "owner": "Haytham Nagi",
        "label": "office 22524 · Haytham Nagi — Horizon Edge Alliance, Inc.",
        "short": "office 22524, Haytham",
        # THE RESUME LOGIN, like every other row (Megan 2026-09-02: "the resume
        # pushing can ONLY HAPPEN on the Resume pushing login"). This said
        # "primary" because Lucy Resume Pushing cannot SEE this office — but
        # that is the guarantee working, not a reason to go around it. An
        # office the resume login cannot see is an office the pusher cannot
        # push, and send-to-AI is irreversible. The run fails here instead.
        "account": "lucyresume",
        "suffix": "-22524",
        "cdp_profile": "/tmp/rp_cdp_22524",
        "cdp_port": "9250",
        "cdp_kill_pat": "rp_cdp_22524",
        "walk_diag_tab": "OAT Walk Diag 22524",
        "push_diag_tab": "Applicant Push Diag 22524",
        "log_stem": "applicant-push-22524",
        "hub_report_id": "applicant_push_haytham",
        "hub_display": "Applicant Push (Haytham)",
        "post_channel": "C09L1S3MQ1E",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "22815": {
        "office_id": "22815",
        "hint": "CYRUS WADE",
        "owner": "Cyrus Wade",
        "label": "office 22815 · Cyrus Wade — Ambient Marketing, Inc.",
        "short": "office 22815, Cyrus",
        # THE RESUME LOGIN, like every other row (Megan 2026-09-02: "the resume
        # pushing can ONLY HAPPEN on the Resume pushing login"). This said
        # "primary" because Lucy Resume Pushing cannot SEE this office — but
        # that is the guarantee working, not a reason to go around it. An
        # office the resume login cannot see is an office the pusher cannot
        # push, and send-to-AI is irreversible. The run fails here instead.
        "account": "lucyresume",
        "suffix": "-22815",
        "cdp_profile": "/tmp/rp_cdp_22815",
        "cdp_port": "9251",
        "cdp_kill_pat": "rp_cdp_22815",
        "walk_diag_tab": "OAT Walk Diag 22815",
        "push_diag_tab": "Applicant Push Diag 22815",
        "log_stem": "applicant-push-22815",
        "hub_report_id": "applicant_push_cyrus",
        "hub_display": "Applicant Push (Cyrus)",
        "post_channel": "C09L1S3MQ1E",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "21151": {
        "office_id": "21151",
        "hint": "CODY CANNON",
        "owner": "Cody Cannon",
        "label": "office 21151 · Cody Cannon — Aeon Specialized Consulting, Inc",
        "short": "office 21151, Cody",
        # THE RESUME LOGIN, like every other row (Megan 2026-09-02: "the resume
        # pushing can ONLY HAPPEN on the Resume pushing login"). This said
        # "primary" because Lucy Resume Pushing cannot SEE this office — but
        # that is the guarantee working, not a reason to go around it. An
        # office the resume login cannot see is an office the pusher cannot
        # push, and send-to-AI is irreversible. The run fails here instead.
        "account": "lucyresume",
        "suffix": "-21151",
        "cdp_profile": "/tmp/rp_cdp_21151",
        "cdp_port": "9252",
        "cdp_kill_pat": "rp_cdp_21151",
        "walk_diag_tab": "OAT Walk Diag 21151",
        "push_diag_tab": "Applicant Push Diag 21151",
        "log_stem": "applicant-push-21151",
        "hub_report_id": "applicant_push_cody",
        "hub_display": "Applicant Push (Cody)",
        "post_channel": "C09L1S3MQ1E",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # LIVE PUSH OFFICE #5 (Carlos, 2026-09-18: "can you have Lucy2 push resumes
    # for all three of Raf's applicant streams"). Was a DIAGNOSTIC row from
    # 2026-08-29 — the lazy-removal audit — and the comment here said the resume
    # login could not see it. That stopped being true on 9/18: Megan assigned
    # 11280, 23965 and 24065 to Lucy Resume Pushing in the ApplicantStream admin
    # (screenshot, "Offices Already Assigned"), which is the permission this job
    # bounds itself with. Nothing else about the row changes — it kept its own
    # profile, port, suffix, tabs and log stem from the day it was added, so
    # going live is a ROTATION entry, not a rename.
    "11280": {
        "office_id": "11280",
        "hint": "RAFAEL HIDALGO",
        "owner": "Rafael Hidalgo",
        "label": "office 11280 · Rafael Hidalgo — ALPHALETE MARKETING, INC.",
        "short": "office 11280, Rafael",
        "account": "lucyresume",
        "suffix": "-11280",
        "cdp_profile": "/tmp/rp_cdp_11280",
        "cdp_port": "9253",
        "cdp_kill_pat": "rp_cdp_11280",
        "walk_diag_tab": "OAT Walk Diag 11280",
        "push_diag_tab": "Applicant Push Diag 11280",
        "log_stem": "applicant-push-11280",
        "hub_report_id": "applicant_push_rafael",
        "hub_display": "Applicant Push (Rafael)",
        # #rafs-office-recruiting-11280 — Raf's OWN live recruiting channel (the
        # one bg_check_sync and the new-start posts already use; the retired
        # C06881A7WLV is a different, dead channel). Stated even though posting
        # is OFF: a blank would let activate() leave whatever channel the last
        # activated office set, and the module default is Carlos's
        # #alphaletegp-recruiting — i.e. Raf's applicants named in Carlos's
        # channel. post_todo is what decides whether anything is sent; this key
        # only decides WHERE, if it ever is.
        "post_channel": "C0AUAS88FGW",
        # OFF until Megan/Carlos ask for it: pushing resumes is what Carlos
        # asked for on 9/18, a daily to-do post into Raf's channel is not, and a
        # Slack send is never a side effect of a config flip.
        # ONE THREAD FOR ALL THREE OF RAF'S STREAMS (Megan
        # 2026-09-18): "a general overview post and then in the thread
        # break down each account and what is needed in it". So the
        # per-office post stays OFF — three offices posting into one
        # channel would be three separate parents — and post_group
        # names the rollup that posts once for all of them.
        "post_group": "raf",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # LIVE PUSH OFFICE #3 (Carlos, 2026-09-08: "can we add khalil mansour to
    # list of people we push for"). Safe-default policies until Carlos says
    # otherwise: NO texting (only 11580/23467 text — standing rule 8/29), NO
    # Slack to-do posts (his office has no channel wired yet, and one office's
    # applicant names never land in another office's channel), and the
    # non-Carlos removal policies (confirmed-uncontactable and never-opening
    # resumes are removed).
    "11901": {
        "office_id": "11901",
        "account": "lucyresume",
        "hint": "KHALIL MANSOUR",
        "owner": "Khalil Mansour",
        "label": "office 11901 · Khalil Mansour — ALPHALETE MANAGEMENT GROUP, INC.",
        "short": "office 11901, Khalil",
        "suffix": "-11901",
        "cdp_profile": "/tmp/rp_cdp_11901",
        "cdp_port": "9254",
        "cdp_kill_pat": "rp_cdp_11901",
        "walk_diag_tab": "OAT Walk Diag 11901",
        "push_diag_tab": "Applicant Push Diag 11901",
        "log_stem": "applicant-push-11901",
        "hub_report_id": "applicant_push_khalil",
        "hub_display": "Applicant Push (Khalil)",
        # #11901-alphalete-management-group-inc-khalil-mansour (private). Carlos
        # added the Lucy Slack apps 2026-09-08 ("ive added you to his slack") —
        # his flagged-applicant to-do posts land HERE and nowhere else.
        "post_channel": "C0AUKHN120L",
        "post_todo": True,
        "allow_retext": False,
        # 9/12 (Carlos): "If the page won't open or there's no number found, let's
        # leave it." Both removal policies OFF — Khalil matches 11580/23467.
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # LIVE PUSH OFFICE #4 (Carlos, 2026-09-10): Rafael's iMessage-funnel TEST
    # office. Standard non-texting policies; no Slack channel wired yet (flags
    # stay in the diag tab until Carlos names one). Joins the wrapper ROTATION
    # only after tonight's window closes so its first ticks land 2026-09-11
    # 7:00 AM — "have her start tomorrow at our regular time".
    "23965": {
        "office_id": "23965",
        "account": "lucyresume",
        "hint": "RAFAEL HIDALGO",
        "owner": "Rafael Hidalgo",
        "label": "office 23965 · Rafael Hidalgo — 2nd Funnel iMessage Test",
        "short": "office 23965, Rafael 2nd funnel",
        "suffix": "-23965",
        "cdp_profile": "/tmp/rp_cdp_23965",
        "cdp_port": "9255",
        "cdp_kill_pat": "rp_cdp_23965",
        "walk_diag_tab": "OAT Walk Diag 23965",
        "push_diag_tab": "Applicant Push Diag 23965",
        "log_stem": "applicant-push-23965",
        "hub_report_id": "applicant_push_raf_funnel2",
        "hub_display": "Applicant Push (Raf 2nd Funnel)",
        # Was blank until 2026-09-18, which meant activate() left whatever
        # channel the previously activated office had set and a hand-run summary
        # would fall back to Carlos's #alphaletegp-recruiting. Now states Raf's
        # own #rafs-office-recruiting-11280 like his other two offices — posting
        # is still OFF, this only fixes WHERE it would go.
        "post_channel": "C0AUAS88FGW",
        # ONE THREAD FOR ALL THREE OF RAF'S STREAMS (Megan
        # 2026-09-18): "a general overview post and then in the thread
        # break down each account and what is needed in it". So the
        # per-office post stays OFF — three offices posting into one
        # channel would be three separate parents — and post_group
        # names the rollup that posts once for all of them.
        "post_group": "raf",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
    # LIVE PUSH OFFICE #6 (Carlos, 2026-09-18) — the third of Raf's streams,
    # "New Recruiter Test". A separate ApplicantStream office, so it gets the
    # full isolation set like every other row: its own Chrome profile and port
    # (9256 — the next free one after 23965's 9255), its own day-file suffix,
    # its own diag tabs and log stem. Sharing any of those with 11280 would let
    # two of Raf's own offices overwrite each other's queue state, which is the
    # single failure this table exists to prevent.
    "24065": {
        "office_id": "24065",
        "account": "lucyresume",
        "hint": "RAFAEL HIDALGO",
        "owner": "Rafael Hidalgo",
        "label": "office 24065 · Rafael Hidalgo — New Recruiter Test",
        "short": "office 24065, Raf new recruiter test",
        "suffix": "-24065",
        "cdp_profile": "/tmp/rp_cdp_24065",
        "cdp_port": "9256",
        "cdp_kill_pat": "rp_cdp_24065",
        "walk_diag_tab": "OAT Walk Diag 24065",
        "push_diag_tab": "Applicant Push Diag 24065",
        "log_stem": "applicant-push-24065",
        "hub_report_id": "applicant_push_raf_recruiter_test",
        "hub_display": "Applicant Push (Raf New Recruiter Test)",
        # Raf's own channel, stated for the same reason 11280 states it: with a
        # blank, a process that already activated another office keeps ITS
        # channel. Posting stays OFF — this is a test stream and nobody has
        # asked for its flagged names in Slack.
        "post_channel": "C0AUAS88FGW",
        # ONE THREAD FOR ALL THREE OF RAF'S STREAMS (Megan
        # 2026-09-18): "a general overview post and then in the thread
        # break down each account and what is needed in it". So the
        # per-office post stays OFF — three offices posting into one
        # channel would be three separate parents — and post_group
        # names the rollup that posts once for all of them.
        "post_group": "raf",
        "post_todo": False,
        "allow_retext": False,
        "remove_blocked_read": False,
        "remove_no_phone": False,
    },
}

DEFAULT_OFFICE = "11580"

# OFFICES THAT SHARE ONE SLACK THREAD ---------------------------------------
# A post GROUP is a set of offices whose to-do list is posted ONCE, together,
# into one channel: an overview parent, then one threaded reply per office.
#
# Raf owns three ApplicantStream streams and ONE recruiting channel. Posting
# per office there would open three parents a day in the same channel and leave
# the reader to add them up; Megan asked for the opposite — "a general overview
# post and then in the thread break down each account and what is needed in it"
# (2026-09-18). Carlos's and Khalil's offices are each their own channel, so
# they keep the per-office post (post_todo) and belong to no group.
#
# An office in a group must have post_todo False, or it would post twice — the
# rollup AND its own parent. test_offices pins that.
POST_GROUPS = {
    "raf": {
        # #rafs-office-recruiting-11280, confirmed by Megan 2026-09-18. The same
        # channel the BG-check and new-start posts already use.
        "channel": "C0AUAS88FGW",
        "owner": "Rafael Hidalgo",
        "short": "Raf",
        # Order the replies appear in the thread: biggest/oldest stream first.
        "offices": ["11280", "23965", "24065"],
    },
}


def group_of(office_id: str) -> str:
    """The post group this office belongs to, or '' when it posts for itself."""
    return str(get(office_id).get("post_group") or "")


def group(name: str) -> dict:
    try:
        return POST_GROUPS[name]
    except KeyError:
        raise SystemExit(
            "[push] unknown post group %r — known: %s (see POST_GROUPS in "
            "automations/applicant_push/offices.py)"
            % (name, ", ".join(sorted(POST_GROUPS))))


# The order the scheduled agent rotates through, ONE office per tick. Each tick
# stays a single ~5-minute warm session (rather than doubling every tick and
# risking the wrapper's hard time cap), and a bad tick for one office cannot
# starve the other — which running both inside one tick would do, since the first
# office's wedge burns the cap before the second ever opens a session.
ROTATION = ["11580", "23467", "11901", "23965", "11280", "24065"]

# WHICH MACHINE WORKS WHICH OFFICES (2026-09-13, Megan: "we can move Raf's push
# to lucy 3 since she's not got a lot on her").
#
# One machine runs one office per tick, ticks are ~6 minutes, and the box is
# already running them back to back — 144 walks in the 900-minute window on 9/10.
# So an office's wait between passes is simply (offices on that machine) x ~6 min,
# and every office added to a machine slows down every other office on it. Raf's
# 23965 joining on 9/12 pushed Carlos, Atef and Khalil from ~19 to ~25 minutes.
#
# SIX OFFICES SINCE 2026-09-18 (Carlos: push all three of Raf's streams). 11280
# and 24065 joined 23965, so one machine now works six and every office waits
# ~36 minutes between passes — Carlos, Atef and Khalil included. That is the
# price of Raf's three on one box, and it is the strongest argument yet for
# finishing the Lucy 3 split below: three and three would put everybody back to
# ~18. Told Megan the number rather than absorbing it quietly.
#
# Splitting across machines is the only lever that changes that number by more
# than a few percent: Lucy 3 has spare capacity, so Raf's office moves there and
# gets a pass every ~6 minutes instead of every ~25, while the other three drop
# back to ~19 on Lucy 2.
#
# THE SAME SCOPED ACCOUNT SIGNS IN ON BOTH BOXES, which is new and is the thing to
# watch: `lucyresume` has only ever been used from Lucy 2. Each machine keeps its
# own Chrome profile and mints its own session, so they do not SHARE one — but if
# applicantstream turns out to allow only one live session per account, Lucy 3
# signing in would log Lucy 2 out and take the offices still on it down too. That
# is why the first Lucy 3 pass must be a supervised --dry-run with Lucy 2's next
# tick checked afterwards, before anything else moves.
#
# WHY TWO AND TWO (2026-09-13, Megan: "let's move another one to lucy 3"). With
# four live offices the per-office wait is the same whichever pair sits on which
# box — both machines end up working two, so everybody lands at ~2 x ~6 min
# instead of Lucy 2's three at ~19 and Lucy 3's one at ~6. Since throughput does
# not care which office moves, the choice is purely which move risks least, and
# that is Khalil's 11901: it is the newest live office (9/8), its queue actually
# drains (2 -> 8 across 9/10, against Atef's 16 -> 33), and it is the only live
# office with no `machine`-pinned rerun entry in schedule_config — Carlos's
# `applicant_push` and Atef's `applicant_push_atef` are both bound to Lucy 2, and
# 11580 additionally carries the unsuffixed day-files and the v2->classic
# Cloudflare quirk. Moving either of those is a bigger change for an identical
# result.
#
# An UNKNOWN machine gets an EMPTY rotation on purpose — Megan's laptop has no
# `.machine-profile`, so hub_identity.machine_name() falls back to its hostname,
# and a default-to-something here would let a laptop start sending real
# applicants. Nothing scheduled means nothing runs.
# PARKED 2026-09-13 (Megan: "just leave all 4 on lucy 2 for now"). The split is
# built and tested; it is simply not switched on. Everything below is what the
# attempt actually established, so nobody has to rediscover it.
#
# HOW FAR IT GOT ON LUCY 3, in order:
#   1. `lucyresume` was not on the box at all. All three Lucys auto-login, but
#      that is the PRIMARY account ("Lucy Reports"); the scoped resume login is a
#      SECOND credential, and it lives in ~/.config/recruiting-report/
#      appstream-accounts.json — outside the repo, because the repo is public.
#      So `lucy update` has never carried it and never will.
#   2. Megan installed it (set_appstream_account). The account now RESOLVES on
#      Lucy 3 — the "No AppStream account named 'lucyresume'" error is gone.
#   3. The login itself still does not complete: "console never rendered
#      #searchMC (Cloudflare re-challenge?)", on the real-Chrome/CDP path that
#      the report actually uses. Two candidates remain and the log does not yet
#      separate them: a Cloudflare state on Lucy 3 needing one human clear, or
#      the credential. NOT a code problem — Lucy 2 runs this same code fine.
#   4. Separately: Lucy 3's Chrome profile has NO Resume Helper extension
#      ("plugin present: False"). It is installed by hand, not by `lucy update`,
#      so Lucy 3 could never run the BATCH stage even once login works. The
#      scheduled push is --oat-only and does not need it, but do not assume the
#      two boxes are interchangeable.
#
# STILL UNANSWERED: whether two machines can hold the `lucyresume` session at
# once. Lucy 2 kept walking (13:52) straight through Lucy 3's login attempts —
# but those attempts never got a console, so nothing was ever competing. Do not
# read that as a green light; it is simply untested.
#
# Assigning an office to a machine that cannot run it means that office is worked
# by NOBODY — Lucy 2 skips it as not-its-rotation and Lucy 3 never runs. That
# happened for ~30 minutes today. The orphan check in test_offices is what caught
# it and is the guard to keep. Flip the split in ONE line once a Lucy 3 dry-run
# comes back clean.
#
#   "Lucy 2": ["11580", "23467"],
#   "Lucy 3": ["23965", "11901"],
#
# What the probe proved and did not prove: it did NOT test whether two machines
# can hold the `lucyresume` session at once — Lucy 3 never got a session to
# begin with. That question is still open and still needs Lucy 2 checked
# immediately after Lucy 3's first successful login.
# SPLIT 2026-09-19 (Megan: "lucy 4 is launched — can we move Raf's 3 accounts
# to it?"). Raf's three streams move as a UNIT, not one at a time: they share
# one to-do thread (POST_GROUPS "raf"), and the rollup reads each stream's
# flagged snapshot off the LOCAL disk — split them across boxes and the thread
# would report the far box's streams as "no walk yet today" forever. Three and
# three puts every office on a ~18-minute pass instead of ~36.
#
# Lucy 4 signs in as the same scoped `lucyresume` login Lucy 2 uses, on its own
# Chrome profile. It does NOT hold the shared `Lucy Reports` session (its fleet
# AppStream flags stay off), so this adds no churn to the token the 4am
# batches share.
ROTATION_BY_MACHINE = {
    # 2026-09-24 late (Carlos): 11580 + Raf's main 11280 back in; Raf's
    # 23965 + 24065 stay paused for now.
    "Lucy 2": ["11580", "23467", "11901"],
    "Lucy 4": ["11280"],
}


def rotation_for(machine: str = None) -> list:
    """The offices THIS machine is responsible for, in tick order.

    Empty for any machine not named above — see the note on ROTATION_BY_MACHINE.
    Matched case-insensitively so a marker written "lucy 3" still resolves."""
    if machine is None:
        try:
            from automations.shared import hub_identity
            machine = hub_identity.machine_name()
        except Exception:  # noqa: BLE001
            machine = ""
    want = str(machine or "").strip().lower()
    for name, offices in ROTATION_BY_MACHINE.items():
        if name.lower() == want:
            return list(offices)
    return []


def get(office_id: str) -> dict:
    try:
        return OFFICES[str(office_id)]
    except KeyError:
        known = ", ".join(sorted(OFFICES))
        raise SystemExit(
            "[push] unknown office %r — known offices: %s. Add it to "
            "automations/applicant_push/offices.py (it needs its OWN cdp profile, "
            "port and file suffix, or it will collide with the others)."
            % (office_id, known))


def activate(office_id: str) -> dict:
    """Point resume_pushing + oat_processing at ONE office for this process.

    Rebinds, on the modules that hard-coded 11580:
      * the office the AppStream session switches into (both modules),
      * the CDP Chrome profile / debug port / pkill pattern — so a run for one
        office cannot pkill another office's Chrome (they all `pkill -f` their
        own profile marker on start),
      * the per-day file suffix + the Sheet diag tab names,
      * the labels the Slack post and the scorecard print.

    Returns the office row. Call this BEFORE any session is opened.
    """
    from automations.resume_pushing import run as rp
    from automations.oat_processing import config as oat_config
    from automations.oat_processing import summary as oat_summary

    o = get(office_id)

    # THE RESUME PUSHER SIGNS IN AS THE RESUME LOGIN. Only. Ever.
    #
    # Megan 2026-09-02: "the resume pushing can ONLY HAPPEN on the Resume
    # pushing login." Not a default, not a per-row preference — a property of
    # the job. Four diagnostic rows carried "primary" so a manual --office run
    # could reach offices the scoped account cannot see; that is the 2026-08-30
    # over-push written down as configuration, and send-to-AI is irreversible.
    #
    # Still read with [] not .get(), so a row that forgot to state its account
    # fails loudly — but the value is now CHECKED rather than trusted. A table
    # is edited by people; a rule this expensive should not be one row's typo
    # away from being broken.
    if o["account"] != RESUME_ACCOUNT:
        raise SystemExit(
            "[push] office %s is configured to sign in as %r, but the resume "
            "pusher may only ever use %r — the 'Lucy Resume Pushing' login "
            "(Megan 2026-09-02). An office the "
            "resume login cannot see is an office this job cannot push — that "
            "is the guarantee, not a problem to route around. Fix the row in "
            "automations/applicant_push/offices.py."
            % (o["office_id"], o["account"], RESUME_ACCOUNT))
    rp.APPSTREAM_ACCOUNT = o["account"]

    rp.OFFICE_ID = o["office_id"]
    rp.OFFICE_HINT = o["hint"]
    rp.CDP_PROFILE = o["cdp_profile"]
    rp.CDP_PORT = o["cdp_port"]
    rp._CDP_KILL_PAT = o["cdp_kill_pat"]
    # Derived at import from CDP_PROFILE, so it has to move with it or a second
    # office would read the FIRST office's "already seeded" marker and skip its
    # own profile seed.
    rp._CDP_SEED_MARKER = o["cdp_profile"] + "/.rp_seeded"

    oat_config.OFFICE_ID = o["office_id"]
    oat_config.OFFICE_HINT = o["hint"]
    oat_config.FILE_SUFFIX = o["suffix"]
    oat_config.WALK_DIAG_TAB = o["walk_diag_tab"]
    # Missing-contact-info policy is the office owner's call, not a global.
    oat_config.REMOVE_NO_PHONE = bool(o.get("remove_no_phone", True))
    # Whether a CONFIRMED-uncontactable applicant (resume opened, no number, or no
    # resume at all) is removed or left in the queue. Per-office on purpose —
    # Carlos's 11580 leaves them, Atef's 23467 removes them. Defaulting a new
    # office to the module default would silently remove people in an office
    # nobody chose that for, so .get() is deliberately NOT used with a True
    # fallback: a row must state its policy.
    oat_config.REMOVE_NO_PHONE = o["remove_no_phone"]
    # Texting a real person is opt-in per office; a row must state it, and a row
    # that does not gets NO texting rather than inheriting someone else's policy.
    oat_config.ALLOW_RETEXT = bool(o.get("allow_retext", False))
    # Blocked-read removal is audit-office-only; unstated means OFF.
    oat_config.REMOVE_BLOCKED_READ = bool(o.get("remove_blocked_read", False))

    oat_summary.OFFICE_LABEL = o["label"]
    oat_summary.OFFICE_SHORT = o["short"]
    if o["post_channel"]:
        oat_summary.CHANNEL_ID = o["post_channel"]

    return o
