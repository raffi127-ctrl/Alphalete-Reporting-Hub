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
OFFICES = {
    "11580": {
        "office_id": "11580",
        "hint": "CARLOS HIDALGO",
        "owner": "Carlos Hidalgo",
        "label": "office 11580 · Carlos Hidalgo — ATT Program",
        "short": "office 11580, Carlos",
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
        "allow_retext": True,
        "remove_blocked_read": False,
        # Atef's office keeps the confirmed-uncontactable removal (a resume that
        # opened and carries no number, or no resume at all). Never fires on a
        # BLOCKED read — that is our failure, and it retries.
        "remove_no_phone": True,
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
        "remove_blocked_read": True,
        # Matches the policy for every office that is not Carlos's: a resume that
        # opens and carries no number is a confirmed-uncontactable removal.
        "remove_no_phone": True,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "23411": {
        "office_id": "23411",
        "hint": "RASHAD REED",
        "owner": "Rashad Reed",
        "label": "office 23411 · Rashad Reed — Elevate Specialized Acquisitions, Inc",
        "short": "office 23411, Rashad",
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
        "remove_blocked_read": True,
        "remove_no_phone": True,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "22524": {
        "office_id": "22524",
        "hint": "HAYTHAM NAGI",
        "owner": "Haytham Nagi",
        "label": "office 22524 · Haytham Nagi — Horizon Edge Alliance, Inc.",
        "short": "office 22524, Haytham",
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
        "remove_blocked_read": True,
        "remove_no_phone": True,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "22815": {
        "office_id": "22815",
        "hint": "CYRUS WADE",
        "owner": "Cyrus Wade",
        "label": "office 22815 · Cyrus Wade — Ambient Marketing, Inc.",
        "short": "office 22815, Cyrus",
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
        "remove_blocked_read": True,
        "remove_no_phone": True,
    },
    # DIAGNOSTIC ONLY (Carlos, 2026-08-29) — same lazy-removal audit as 19592.
    # Not in ROTATION, posts no to-do list, and never texts an applicant.
    "21151": {
        "office_id": "21151",
        "hint": "CODY CANNON",
        "owner": "Cody Cannon",
        "label": "office 21151 · Cody Cannon — Aeon Specialized Consulting, Inc",
        "short": "office 21151, Cody",
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
        "remove_blocked_read": True,
        "remove_no_phone": True,
    },
}

DEFAULT_OFFICE = "11580"

# The order the scheduled agent rotates through, ONE office per tick. Each tick
# stays a single ~5-minute warm session (rather than doubling every tick and
# risking the wrapper's hard time cap), and a bad tick for one office cannot
# starve the other — which running both inside one tick would do, since the first
# office's wedge burns the cap before the second ever opens a session.
ROTATION = ["11580", "23467"]


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
