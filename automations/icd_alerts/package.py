"""Build one ICD's installer folder. Runs on OUR side, never on a laptop.

  python -m automations.icd_alerts.package kash

WHAT GOES IN IS THE POINT. An ICD gets the ten files the agent actually
imports, and nothing else -- not `post.py`, not `offices.py`, not the tests,
and above all not the Hub repo, which carries every office's sheet ids, channel
ids and a committed oauth client secret. Handing a contractor a clone of the
reporting codebase is not a thing to do once, let alone 52 times.

THE OFFICE KEY AND THE RELAY KEY ARE BAKED IN, so nobody types a code. The one
thing the ICD supplies is their own SaraPlus login, which never leaves their
machine.

THE BUILT FOLDER CONTAINS A SECRET -- that office's relay key -- so it is
written to output/ (gitignored) and is meant to be handed over directly, not
posted anywhere a second office could read it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

from automations.icd_alerts import offices as O

APP_SUBDIR = "program files"        # a name that says "not for you"
REPO = Path(__file__).resolve().parents[2]
DIST = Path(__file__).resolve().parent / "dist"
OUT = REPO / "output" / "icd-alerts"

# The exact closure the agent imports. Listed explicitly rather than globbed:
# a glob is how `post.py` or a test fixture ends up on somebody's laptop the
# day someone adds one.
AGENT_FILES = [
    "automations/icd_alerts/__init__.py",
    "automations/icd_alerts/config.py",
    "automations/icd_alerts/relay.py",
    # Ships itself, necessarily: an office that does not have this file
    # can never receive it automatically, so the one manual update that
    # delivers it is the last one they ever have to run.
    "automations/icd_alerts/selfupdate.py",
    # Ships with selfupdate, which calls it: an office that does not have this
    # file keeps the cadence its installer wrote and nothing says so.
    "automations/icd_alerts/sweep_cadence.py",
    # Ships with the agent so the awake status in every relay is read by the
    # SAME code that set it. A machine reporting from an older copy of this
    # file would be answering a question we are no longer asking.
    "automations/icd_alerts/stay_awake.py",
    # Makes the machine start at BOOT instead of at login. Ships because
    # setup.py does NOT: an office already enrolled would otherwise need a
    # full re-install, which needs the enrolment code they no longer have.
    "automations/icd_alerts/boot_schedule.py",
    # THE ONLY LINK AN OFFICE IS EVER SENT. Does whatever that machine is
    # missing and skips the rest, so a new requirement becomes a step in one
    # function rather than a new page and five more messages.
    "automations/icd_alerts/finish_setup.py",
    "automations/icd_alerts/sara_read.py",
    # The Box half of the same job. Ships for the same reason sara_read does:
    # the read happens on the office's own machine, against their own account.
    "automations/icd_alerts/box_read.py",
    # THE REMEDY ITSELF. The sign-in DM tells the office to open Lucy's own
    # browser on that computer and sign in -- and without this file the one
    # instruction we give them fails on arrival, at the exact moment their
    # sales have stopped. It was left out of the bundle when it was written
    # (2026-09-15).
    "automations/icd_alerts/box_signin.py",
    "automations/icd_alerts/optix_read.py",
    "automations/icd_alerts/optix_signin.py",
    # THE LUCY OPTIX CHROME EXTENSION (Verizon). Data, not imports: setup.py
    # copies this folder to the owner's Documents for a one-click Load
    # unpacked, with their office code + key pre-filled (config.json).
    "automations/icd_alerts/optix_extension/manifest.json",
    "automations/icd_alerts/optix_extension/background.js",
    "automations/icd_alerts/optix_extension/popup.html",
    "automations/icd_alerts/optix_extension/popup.js",
    "automations/icd_alerts/optix_extension/rules.json",
    "automations/icd_alerts/optix_extension/README.md",
    "automations/icd_alerts/optix_extension/icons/lucy-16.png",
    "automations/icd_alerts/optix_extension/icons/lucy-32.png",
    "automations/icd_alerts/optix_extension/icons/lucy-48.png",
    "automations/icd_alerts/optix_extension/icons/lucy-128.png",
    "automations/icd_alerts/sara_signin.py",
    # The code screen cleared by itself, with the code from Lucy 1
    # (2026-10-29). code_answer only for its request wording -- the half
    # that runs on Lucy 1 is imported late and never on a Mac.
    "automations/icd_alerts/sara_code.py",
    "automations/icd_alerts/code_answer.py",
    # Setup asks for the code forward right there (Megan 2026-10-29).
    "automations/icd_alerts/code_forward.py",
    "automations/icd_alerts/gmail_filters.py",
    "automations/icd_alerts/gmail_browser.py",
    "automations/icd_alerts/ov_signin.py",
    # Resume pushing on the office's own machine: the installer's AppStream
    # check runs it, so it has to be there when setup.py is.
    "automations/icd_alerts/as_signin.py",
    "automations/icd_alerts/resume_push.py",
    "automations/icd_alerts/batch_push.py",
    # THE WALK ITSELF, shipped whole rather than copied (2026-10-20): the
    # office machine runs the same One App at a time walk as Lucy 2 and
    # Lucy 4, so a walk fix reaches every office on its next self-update.
    # Its few Hub-only reach-outs are listed in HUB_ONLY_IMPORTS below.
    "automations/oat_processing/__init__.py",
    "automations/oat_processing/config.py",
    "automations/oat_processing/classify.py",
    "automations/oat_processing/resume_download.py",
    "automations/oat_processing/run.py",
    # Numbers a person looked up for applicants the resume read came up
    # empty on, pulled off the relay's 'Phone Lookups' tab by the walk
    # (2026-11-16). phone_lookups_add.py, which puts them there, is ours.
    "automations/oat_processing/phone_lookups.py",
    # Indeed's own number, looked up through Octo Browser on the office
    # computer at 5am for the walk's no-number list (Carlos 2026-11-16).
    "automations/oat_processing/octo_lookup.py",
    "automations/oat_processing/octo_profiles.json",
    # The Await text's interview times, retuned to the clock before each live
    # push (Carlos/Megan 2026-10-28).
    "automations/oat_processing/await_window.py",
    "automations/oat_processing/await_template.py",
    # The Mac's own text recognition for resumes Indeed draws as a picture
    # (no Claude key ships to an office; 2026-10-22, Jorge Banos).
    "automations/oat_processing/bin/ocr_screen.js",
    # ...and downloaded resume FILES: PDF text + picture PDFs (no PyMuPDF there).
    "automations/oat_processing/bin/read_file.js",
    # The Lucys' own office switch (stdlib + patchright only), for an office
    # computer holding a login that sees more than one office.
    "automations/recruiting_report/__init__.py",
    "automations/recruiting_report/fetch_office.py",
    # The weekend quiet window, the Lucys' own rule (stdlib only).
    "automations/applicant_push/__init__.py",
    "automations/applicant_push/window.py",
    "automations/icd_alerts/watchdog.py",
    "automations/icd_alerts/presence.py",
    "automations/icd_alerts/autoprompt.py",
    "automations/icd_alerts/state.py",
    # SHIPS WITH run.py, WHICH IMPORTS IT AT MODULE LEVEL. Leaving it out does
    # not degrade the close-out, it stops the agent dead: the next self-update
    # would hand every office a run.py that cannot import, on a machine nobody
    # can reach. The manifest test compares this list against agent_files.txt
    # and passes happily when BOTH are missing a file, so it is no guard here.
    "automations/icd_alerts/closeout.py",
    "automations/icd_alerts/sales_closeout.py",
    "automations/icd_alerts/run.py",
    "automations/icd_alerts/dialogs.py",
    "automations/icd_alerts/ov_read.py",
    "automations/icd_alerts/quiet_window.py",
    "automations/shared/ownerville_knocks.py",
    "automations/shared/saraplus.py",
    "automations/shared/sara_passcode.py",
    # My Service Cloud: where a Box office's sales live. Ships for the same
    # reason saraplus.py does -- the read happens on the office's machine.
    "automations/shared/servicecloud.py",
    # Both wording modules below case the rep's name through it.
    "automations/shared/name_case.py",
    "automations/shared/credit_check_line.py",
    "automations/shared/sale_hype.py",
    "automations/shared/browser_banner.py",
    # Headshots: the office's computer uploads its new starts' photos into its
    # own OwnerVille with the SAME uploader Raf's bot uses (Megan 2026-10-26).
    "automations/icd_alerts/headshot_jobs.py",
    "automations/headshots/__init__.py",
    "automations/headshots/ov_upload.py",
    # Office admin page jobs (Raf 2026-11-01): the admin's buttons, done on
    # this computer with this office's own logins.
    "automations/icd_alerts/office_jobs.py",
    # Online presence (2026-11-08): the office's OWN Zoho, signed in on this
    # computer; office_jobs hands it the admin's approved posts. These four
    # were added to agent_files.txt -- so every office has had them since --
    # but never to this list, which is one half of why the manifest test sat
    # red for three days.
    "automations/icd_alerts/social_post.py",
    "automations/icd_alerts/office_reviews.py",
    "automations/icd_alerts/office_facebook.py",
    "automations/icd_alerts/office_fb_browser.py",
    "automations/icd_alerts/sealed.py",
    "automations/brand_audit/__init__.py",
    "automations/brand_audit/config.py",
    "automations/brand_audit/zoho_draft.py",
    "automations/icd_alerts/sterling_send.py",
    "automations/icd_alerts/sterling_forward.py",
    "automations/icd_alerts/sterling_setup.py",
    # finish_setup's Leader In Calendar step (cb6a46b put it in agent_files.txt only).
    "automations/icd_alerts/leader_in_calendar.py",
    # The owner's PNL, done on their own computer (Eve + Megan 2026-10-29).
    "automations/icd_alerts/pnl.py",
    # The PNL's Apex half: the owner's one sign-in window, and Carlos's
    # export shipped whole (stdlib at the top; its Google writes are never
    # called on an office Mac).
    "automations/icd_alerts/apex_signin.py",
    # The owner's Apex sign-in, lock and 2-step code (lucy eco pnl, 2026-11-17
    # releases .1-.3): they were in agent_files.txt -- so every office already
    # downloads them -- but not declared here, and UpdateScriptTests blocked
    # every release after. Declared 2026-11-18.
    "automations/icd_alerts/apex_login.py",
    "automations/icd_alerts/apex_guard.py",
    "automations/icd_alerts/apex_2fa_setup.py",
    "automations/carlos_payroll_pull/__init__.py",
    "automations/carlos_payroll_pull/run.py",
    # Whether this Mac can read the owner's SaraPlus code texts (Eve 2026-10-29).
    "automations/icd_alerts/messages_probe.py",
    # SaraPlus's code read off the owner's texts in Messages (Eve 2026-10-31).
    "automations/icd_alerts/sms_code.py",
    # THE ONBOARDING BOARD ON THE OFFICE'S OWN COMPUTER (Megan, 2026-11-24:
    # "build an installer now like we have for Lucy Eco to run on the ICDs
    # machine to fully launch all of these steps on an eco machine").
    #
    # THE INSTALLER AND THE CLOCK, NOT THE STEPS. `onboarding_setup` puts every
    # per-office login on the machine and PROVES each one; `eco_job` is the
    # clock the board will run on, and it is inert here on purpose -- what it
    # would start is `icd_onboarding.run`, which cannot ship (see
    # ONBOARDING_STEP_FILES below for the measurement and what is in the way).
    # So an office machine can be got READY now, which is the half that needs
    # somebody sitting at it, and the steps follow without another visit.
    #
    # `relay_board` is this machine's ONLY way to the board: the board is a
    # Google Sheet and an office Mac has no Google access at all. `board` is
    # pure (column names, week maths) and `shared/onboarding_week` is what
    # `tab_name` moved into so this set would close.
    #
    # The contacts chain is here for ONE step, Contact Added: Megan, 2026-11-11,
    # "each ICD will have their own reception email", so the account it reads is
    # the office's own and the token belongs on the office's own computer. It
    # has been running on Lucy 1 against Alphalete's account, which is the right
    # answer for exactly one office.
    "automations/shared/onboarding_week.py",
    "automations/icd_onboarding/__init__.py",
    "automations/icd_onboarding/board.py",
    "automations/icd_onboarding/relay_board.py",
    "automations/icd_onboarding/eco_job.py",
    "automations/icd_alerts/onboarding_setup.py",
    "automations/second_round_contacts/__init__.py",
    "automations/second_round_contacts/config.py",
    "automations/second_round_contacts/state.py",
    "automations/second_round_contacts/contacts.py",
    "automations/applicant_contacts/__init__.py",
    "automations/applicant_contacts/extract.py",
    "automations/applicant_contacts/contacts.py",
    "automations/fiber_owners_distro/__init__.py",
    "automations/fiber_owners_distro/roster.py",
    "automations/fiber_owners_distro/contacts_write.py",
    "automations/brand_audit/credentials.py",
    # `board.status_rank` ranks the two background-check columns with
    # bg_check_sync's OWN table, so the board and the OBCL agree about
    # what counts as further along -- and that ranking IS the on-only
    # rule, so it has to work on an office machine rather than be
    # guarded away. Both files are pure parsing (stdlib + shared.names).
    "automations/shared/names.py",
    "automations/bg_check_sync/__init__.py",
    "automations/bg_check_sync/parse.py",
    # THE FIVE OWNERVILLE COLUMNS, on the office's own machine
    # (2026-11-24). ONE read of View Progress answers Digi Docs, the six
    # quizzes, the headshot, the UID and the BG status, plus the three
    # gates that hold Owner Submit -- with the office's OWN login and
    # campaign, so nothing queues behind another office's read.
    #
    # Measured before building rather than guessed: seven files, not a
    # cascade, because `headshots/ov_upload.py` already ships and that is
    # where most of the page-driving lives. `config.PROFILE_DIR` moved out
    # of `obcl_ov_sweep/run.py` in the same change -- it is a path, and
    # reaching for it used to drag the whole sweep and gspread with it.
    "automations/obcl_ov_sweep/__init__.py",
    "automations/obcl_ov_sweep/config.py",
    "automations/obcl_ov_sweep/ov_table.py",
    "automations/icd_onboarding/ov_misses.py",
    "automations/shared/new_start_steps.py",
    "automations/b2b_dispositions/__init__.py",
    "automations/b2b_dispositions/capture.py",
    "automations/digi_docs/__init__.py",
    # THE OWNER SUBMIT PRESS (2026-11-24). The only step on an office
    # machine that ACTS: the confirm box attests a criminal background
    # check was reviewed AND PASSED, and there is no unsubmit.
    #
    # SHIPPED, NOT ARMED. `config.owner_submit_live` answers per office
    # and `OWNER_SUBMIT_LIVE_OFFICES` is EMPTY -- Alphalete keeps the
    # gate it has had since 2026-09-22, and every other office walks a
    # READY person up to the confirm box and submits nobody. Inheriting
    # September's switch would have armed forty offices at once for the
    # one action in this chain that cannot be taken back.
    #
    # `uid_request` comes with it because `presses` reads it: there is no
    # UID press (OwnerVille has no button), only a reader of whose move
    # each outstanding one is.
    "automations/icd_onboarding/presses.py",
    "automations/obcl_ov_sweep/owner_submit.py",
    "automations/obcl_ov_sweep/uid_request.py",
    # BLUE INK: WHO HAS SIGNED (2026-11-24). The packet is in the
    # OFFICE'S OWN account -- each ICD got one on 2026-11-09, because an
    # office falling back to Alphalete's sends its new starts' documents
    # out of somebody else's and the send SUCCEEDS.
    #
    # `recent_ui` reads the same screens a person does, which is the route
    # that always works: API Access is Enterprise-only on this plan, so a
    # normal-plan ICD may not be able to make a key at all.
    "automations/blueink_docs/recent_ui.py",
    "automations/blueink_docs/roster.py",
    "automations/icd_onboarding/office_steps.py",
    # NEW STARTS -> APEX, DELIVERED AT LAST (2026-11-24). Declared on
    # 2026-11-08 and held back ever since -- the reasons are kept in full under
    # APEX_WEEK_FILES below, and every one of them is now closed:
    #
    #   the board read      `eco_run._removed_on_the_board` went through
    #                       gspread; it goes through `fillers.rows_anywhere`,
    #                       which is the relay on an office machine. It was the
    #                       last Sheets call on this path, and "the removals
    #                       have to reach the office another way (in the job,
    #                       through the relay)" is what that note asked for.
    #   the gender column   `_genders_from_board` read a Google Sheet; gender
    #                       is guessed from the first name at the moment Apex
    #                       is typed and the column has left the board.
    #   the pure helpers    `week_start_of` and `tab_name` moved into
    #                       `shared/onboarding_week`, which ships.
    #   the AppStream       `applicantstream.session` binds to the Hub's warm
    #     session           console; `eco_steps.appstream_here` drives the
    #                       office's own Chrome instead.
    #   three Hub reaches   each now inside its own try with a safe answer on an
    #                       office machine (HUB_ONLY_IMPORTS above).
    #
    # Megan, 2026-11-11, on where it belongs: "apex has to run on the ECO
    # machine since it's that ICDs independent login." It still presses nothing
    # unattended -- the typing is behind APEX_FILL_PROVEN, which no scheduled
    # run can set, and the two state answers hold anybody whose office has not
    # given them.
    "automations/apex_new_starts/__init__.py",
    "automations/apex_new_starts/apex.py",
    "automations/apex_new_starts/values.py",
    "automations/apex_new_starts/fieldmap.py",
    "automations/apex_new_starts/field_map.json",
    "automations/apex_new_starts/blueink_data.py",
    "automations/apex_new_starts/ssn_prompt.py",
    "automations/apex_new_starts/eco_run.py",
    # THE TWO THAT ACTUALLY TYPE THE RECORD. Declared on the ship list
    # 2026-11-08 and never added to the list an office downloads, so an
    # apex_week job on an office machine answered "no module named
    # automations.apex_new_starts.drive" -- and always would have. Nobody
    # noticed because no job has ever been queued to one: Raf is apex_mode
    # "dry" and every other office is "off".
    #
    # `drive` is the browser walk (open the roster, press Add Employee, set
    # the Kendo dropdowns with real clicks) and it imports `filler`, so the
    # two travel together or neither works.
    "automations/apex_new_starts/drive.py",
    "automations/apex_new_starts/filler.py",
    "automations/blueink_docs/__init__.py",
    "automations/blueink_docs/blueink.py",
    "automations/blueink_docs/config.py",
    "automations/office_admin/config.py",
    "automations/shared/workbooks.py",
    "automations/shared/new_start_eligibility.py",
    "automations/shared/hub_autopublish.py",
    # THE FIRST STEP THE OFFICE DOES FOR ITSELF (Megan, 2026-11-24: "we
    # need it to work like lucy eco does"). `eco_steps` holds the step
    # bodies that reach their source the ECO way -- today Contact Added,
    # read off the office's OWN reception Google Contacts -- and `fillers`
    # is what routes every read and write through the relay on a machine
    # with no Google access. `run.py` delegates to it, so a step has one
    # implementation and not a Hub copy beside an office copy.
    "automations/icd_onboarding/fillers.py",
    "automations/icd_onboarding/eco_steps.py",
    # READING APPLICANTSTREAM FROM THE OFFICE'S OWN COMPUTER, which the
    # seed and the no-shows walk both need. `eco_steps.appstream_here`
    # binds the DRIVER to the same Chrome the push already signs into
    # (resume_push), because `applicantstream.session` binds to the warm
    # console `tableau_patchright` keeps on OUR machines and that module
    # cannot ship -- it pulls in recruiting_report.opt_phase and the Hub
    # behind it. Measured 2026-11-24: the driver class needs nothing but a
    # Playwright page, and the readers below are pure page-scraping --
    # `retention` and `cal_nav` import no automations module at all.
    "automations/applicant_tracker/__init__.py",
    "automations/applicant_tracker/applicantstream.py",
    "automations/office_admin/__init__.py",
    "automations/office_admin/cal_nav.py",
    "automations/office_admin/retention.py",
    "automations/office_admin/fdot.py",
]

# NEW STARTS -> APEX: DELIVERED 2026-11-24. The list below is kept because the
# reasons are worth reading -- it is the record of what "ship it" actually
# costs when the thing being shipped reads Google Sheets and the destination
# has no Google access at all. Every file here is now in AGENT_FILES above,
# which names the five blockers and how each was closed.
#
# WHAT HAS NOT CHANGED: no office computer presses anything unattended. The
# typing is behind APEX_FILL_PROVEN, a flag no scheduled run can set, and an
# office that has not answered its two state questions holds every person back
# rather than filing them under Texas.
#
# THE ORIGINAL NOTE, 2026-11-11:
#
# These went into AGENT_FILES on 2026-11-08 ("apex_week: ship it to the office
# machines") and were never added to agent_files.txt -- and agent_files.txt is
# the list an office actually downloads (install.sh, update.sh, selfupdate).
# So no office computer has ever had one of them: an `apex_week` job handed to
# an office machine answers "No module named automations.office_admin", and
# always has. Nobody noticed because no apex_week job has been queued yet.
#
# THEY STAY OUT until the job can really run there, which is more than adding
# nineteen lines to a text file. Since the 8th the path has grown imports an
# office Mac cannot satisfy, because it has no Google access at all:
#
#   eco_run._removed_on_the_board   reads the office's onboarding board, a
#       Google Sheet (icd_onboarding.sheet / fillers -> recruiting_report.fill).
#       Unreadable there, and unreadable means REFUSE -- "a board that cannot
#       be read is NOT a board with nobody removed" -- so the job stops before
#       it adds anyone. Right answer, but it is every run. The removals have
#       to reach the office another way (in the job, through the relay).
#   office_jobs.work                icd_onboarding.office_steps (uses_blueink)
#   office_admin.fdot               icd_onboarding.board.week_start_of, and
#                                   raf_daily_update.run._CAL_NAV_JS
#   apex_new_starts.blueink_data    terminated_reps.board.base_name -- a module
#                                   that opens Google Sheets as it imports
#   applicant_tracker.applicantstream.session
#                                   shared.tableau_patchright
#
# WHERE IT RUNS IS SETTLED (Megan, 2026-11-11): "apex has to run on the ECO
# machine since it's that ICDs independent login." So it is not moving to a
# Lucy, and the office Mac is not getting Google access: what the job needs
# from our Sheets has to TRAVEL WITH THE JOB -- who the board says was removed
# that week (and that the board was really read: a missing list is not an
# empty one), whether the office uses Blue Ink -- and the "Added to APEX" tick
# has to be written on our side from the result the office sends back. The
# pure helpers (week_start_of, base_name, the calendar-nav script) need to
# live in files that can ship.
#
# Shipping the files without settling those would put a payroll job on forty
# office computers that can only ever answer "error". When it is ready: move
# these back into AGENT_FILES, add them (and what they import) to
# agent_files.txt in the same commit, and the two tests in
# test_knocks.ShippedClosureTests / UpdateScriptTests will say what is left.
APEX_WEEK_FILES = [
    "automations/apex_new_starts/__init__.py",
    "automations/apex_new_starts/eco_run.py",
    "automations/apex_new_starts/values.py",
    "automations/apex_new_starts/apex.py",
    "automations/apex_new_starts/blueink_data.py",
    "automations/apex_new_starts/fieldmap.py",
    "automations/apex_new_starts/field_map.json",
    "automations/apex_new_starts/ssn_prompt.py",
    "automations/office_admin/__init__.py",
    "automations/office_admin/config.py",
    "automations/office_admin/fdot.py",
    "automations/blueink_docs/__init__.py",
    "automations/blueink_docs/blueink.py",
    "automations/blueink_docs/config.py",
    "automations/shared/workbooks.py",
    "automations/shared/new_start_eligibility.py",
    "automations/shared/hub_autopublish.py",
    "automations/applicant_tracker/__init__.py",
    "automations/applicant_tracker/applicantstream.py",
]

# HUB-ONLY IMPORTS THAT SHIP ON PURPOSE, each inside a function, never at
# module level. (shipped file, module it reaches for, the function it sits in.)
#
# The One App at a time walk ships whole (see AGENT_FILES) so office machines
# and the Lucys run ONE walk. A few of its extras exist only on our side: the
# Sheets diag rows, a Slack DM of a screenshot, the vision read. On an office
# machine those imports raise, and every one of them is either inside a
# try/except that drops the extra and carries on, or in a function the office
# push never calls. test_resume_walk_ships pins both, so an entry here cannot
# quietly become a crash.
HUB_ONLY_IMPORTS = {
    # THE GSPREAD HALF OF THE BOARD, never reached on an office machine.
    # `fillers` chooses its route with `on_office_machine` (relay_board): on an
    # office Mac every read and write goes through the relay, and
    # `workbook_for` -- the only thing in this file that opens a Sheet -- is
    # not called at all. Pinned by test_fillers, which holds every board
    # resolver to `sheet.board_for`, and by the relay path's own tests.
    ("automations/icd_onboarding/fillers.py",
     "automations.recruiting_report.fill", "workbook_for"),
    ("automations/icd_onboarding/fillers.py",
     "automations.office_metrics", "workbook_for"),
    ("automations/icd_onboarding/fillers.py",
     "automations.shared.workbooks", "workbook_for"),
    # The second-round ROSTER is ours: a Google Sheet. An office machine
    # answers from what the ICD told the installer
    # (onboarding_setup.reception_email) and never reaches this; the whole
    # fallback sits in one try, and an unreachable roster answers "" rather
    # than raising -- which is why a box without it skips the step instead of
    # claiming nobody has been contacted.
    ("automations/icd_onboarding/eco_steps.py",
     "automations.icd_onboarding", "reception_account"),
    ("automations/icd_onboarding/eco_steps.py",
     "automations.second_round_contacts", "reception_account"),
    # THE WARM-CONSOLE SESSION, ours alone. `applicantstream.session` binds to
    # the console `tableau_patchright` keeps alive on a Lucy; an office machine
    # calls `eco_steps.appstream_here` instead, which drives its OWN Chrome.
    # The import sits inside `session()` and nothing on an office box calls it.
    ("automations/applicant_tracker/applicantstream.py",
     "automations.shared.tableau_patchright", "session"),
    # THE APEX JOB'S THREE HUB REACHES, each inside its own try and each with a
    # safe answer on an office machine (2026-11-24, when the job finally
    # shipped -- see APEX_WEEK_FILES below for the reasons it could not).
    #
    #   hub_autopublish          lights a card on the Hub -- `_resolve` finds
    #                              which card, `_publish` marks it. Both are in
    #                              their own try: off the Hub the answer is "no
    #                              pill", which is not an error.
    #   config.template_name_for   an office's Blue Ink bundle name, off the
    #                              enrolment. Unreadable answers "" and NOT
    #                              Alphalete's name, which is the whole point
    #                              of the guard -- a fallback to ours would
    #                              send somebody else's documents.
    #   config.sheet_id            the admin workbook's id. Nothing on an
    #                              office's computer opens it; guarded above so
    #                              a box without it gets a sentence instead of
    #                              ModuleNotFoundError.
    ("automations/shared/hub_autopublish.py",
     "automations.day_orchestrator", "_resolve"),
    ("automations/shared/hub_autopublish.py",
     "automations.day_orchestrator", "_publish"),
    ("automations/blueink_docs/config.py",
     "automations.eco_onboarding", "template_name_for"),
    ("automations/office_admin/config.py",
     "automations.org_sales_board.run", "sheet_id"),
    # WHETHER AN OFFICE DOES BLUE INK, the Hub's way: `office_steps._rows`
    # reads the relay workbook with gspread, inside a try that returns [] --
    # which reads as "nobody has asked" off the Hub, not as "no". Right for a
    # Lucy and useless on an office box, which is why `eco_steps._has_blueink`
    # asks THAT MACHINE first and only falls through to this on the Hub.
    ("automations/icd_onboarding/office_steps.py",
     "automations.recruiting_report.fill", "_rows"),
    ("automations/icd_onboarding/office_steps.py",
     "automations.icd_alerts", "_rows"),
    # `save_blueink` WRITES that same tab, and only the Hub ever does: an
    # office answers this on its enrolment form, not by Lucy writing a cell
    # for them.
    ("automations/icd_onboarding/office_steps.py",
     "automations.recruiting_report.fill", "save_blueink"),
    ("automations/icd_onboarding/office_steps.py",
     "automations.icd_alerts", "save_blueink"),
    # Best effort, inside try: the walk goes on without them.
    ("automations/oat_processing/run.py", "automations.recruiting_report",
     "_write_walk_diag"),
    ("automations/oat_processing/run.py", "automations.recruiting_report",
     "probe_resume"),
    ("automations/oat_processing/run.py", "automations.shared",
     "_shot"),
    ("automations/oat_processing/run.py", "automations.brand_audit",
     "_ocr_phone"),
    # Lucy-only entry points the office push never calls.
    ("automations/oat_processing/run.py", "automations.recruiting_report",
     "_nophone_ws"),
    ("automations/oat_processing/run.py", "automations.shared.tableau_patchright",
     "run"),
    ("automations/oat_processing/run.py", "automations.recruiting_report",
     "run"),
    # The headshot uploader: an office machine calls upload_on_page with its
    # own rqst, so find_rep never reaches the b2b reader; upload() and
    # announce() are Lucy 3's entry points only.
    ("automations/headshots/ov_upload.py", "automations.b2b_dispositions.capture",
     "_lucy_rqst"),
    ("automations/headshots/ov_upload.py", "automations.shared.tableau_patchright",
     "upload"),
    ("automations/headshots/ov_upload.py", "automations.headshots",
     "announce"),
    # ---- everything below was added 2026-11-11, when the closure test had
    # ---- been red for weeks and so was guarding nothing. Each was checked
    # ---- by hand against what an office machine actually calls.
    #
    # The push window: an office calls in_hours / due / needs_batch_check.
    # gate() is the Lucys' own tick (deploy/*.sh, `python -m ...window`) and
    # is the only thing that asks the mini whether the 4am run is going.
    ("automations/applicant_push/window.py",
     "automations.day_orchestrator.mini_control", "gate"),
    # Zoho: social_post uses wait_for_signin / channel_check / page_of /
    # select_channels / post_now. launch_login and main are the Hub's own
    # sign-in command for Alphalete's and the online-presence offices' Zoho.
    ("automations/brand_audit/zoho_draft.py",
     "automations.shared.tableau_patchright", "launch_login"),
    ("automations/brand_audit/zoho_draft.py",
     "automations.online_presence", "main"),
    # code_answer ships for its request WORDING. Reading the code out of the
    # inbox is Lucy 1's half, and so is everything that writes the forwards
    # down in a Sheet -- each of those inside a try that carries on without.
    ("automations/icd_alerts/code_answer.py",
     "automations.rc_contact_sync", "_newest_code"),
    ("automations/icd_alerts/code_answer.py",
     "automations.rc_contact_sync", "_sterling_inbox_code"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "_main"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "answer_requests"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "record_forwards"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "confirm_forwards"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "publish_confirmed"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "publish_working"),
    ("automations/icd_alerts/code_answer.py",
     "automations.recruiting_report.fill", "check_forward_scope"),
    # Setup offers the standard AppStream login when the Hub's provisioner is
    # there; on an office machine it is not, and setup says so and goes on.
    ("automations/icd_alerts/finish_setup.py",
     "automations.shared.appstream_provision", "_standard_appstream_login"),
    # NEW STARTS -> APEX IS NOT ON OFFICE MACHINES YET (APEX_WEEK_FILES, up by
    # AGENT_FILES, says why). office_jobs.work is one big try: an `apex_week` job
    # that reaches an office today answers status "error" naming the module
    # it could not import, and adds nobody. _appstream_id is only ever called
    # from that same branch, after the import that fails first.
    ("automations/icd_alerts/office_jobs.py", "automations.office_admin", "work"),
    ("automations/icd_alerts/office_jobs.py", "automations.icd_onboarding", "work"),
    ("automations/icd_alerts/office_jobs.py", "automations.apex_new_starts", "work"),
    ("automations/icd_alerts/office_jobs.py", "automations.office_admin",
     "_appstream_id"),
}
# The functions in that list the office push must never reach.
HUB_ONLY_ENTRY_POINTS = {"_nophone_ws", "run",
                         # Lucy 3's side of the headshot uploader
                         "_lucy_rqst", "upload", "announce",
                         # 2026-11-11: the Lucys' tick, the Hub's Zoho sign-in,
                         # Lucy 1's inbox read, and the Apex branch's helper
                         "gate", "launch_login", "main",
                         "_newest_code", "_sterling_inbox_code", "_main",
                         "_appstream_id"}

# The repo's automations/__init__.py installs the Hub's auto-publish hook. That
# is Hub machinery and has no business on an ICD's laptop, so the bundle gets
# this instead.
BUNDLE_INIT = '''"""Alphalete Alerts."""
'''

GATEKEEPER = """
IF NOTHING HAPPENS WHEN YOU DOUBLE-CLICK IT
    That is macOS being careful about files from the internet, not
    something being wrong. Two ways past it -- try the first, and if your
    Mac is a recent one, use the second.

    1. Right-click (or control-click) the installer, choose Open, then
       click Open again.

    2. Double-click it once and let it be blocked. Then open
       System Settings > Privacy & Security, scroll down, and you will
       see a line about "Install Lucy Reports" with an "Open Anyway"
       button. Click that, then double-click the installer again.

    You only have to do this once.
"""

README = """Lucy Reports -- {label}
{underline}

WHAT THIS IS
    Lucy watches your own SaraPlus account through the day and tells the
    reporting team when one of your reps runs a credit check -- the same
    Lucy that already posts in your team's Slack. Those alerts show up in
    {channel}.

    If you asked for it, she also posts your knocks and dispositions
    board on the schedule you picked.

TO INSTALL
{how}

    (The "program files" folder next to it is the program itself -- you
    never need to open it.)

    Boxes will pop up asking for your SaraPlus login and your OwnerVille
    login, and where you would like things posted. That is everything it
    asks for. A Lucy Reports window also opens showing its progress --
    you can ignore that one and close it at the end.
{gatekeeper}
ABOUT YOUR PASSWORDS
    They are saved on your computer only, and are used to sign in from
    your computer. They are never sent to us or to anyone else. The only
    thing that leaves your computer is the number of credit checks each
    rep has run today.

AFTER IT IS INSTALLED
    Nothing. It checks every few minutes between 10am and 9:30pm (4pm on
    Saturdays) and does nothing on Sundays. Just leave the computer on and
    connected to the internet during selling hours -- plugged in, so it
    does not go to sleep. If it does sleep, no alerts are lost; they
    simply arrive when it wakes up.

IF A BROWSER WINDOW OPENS BY ITSELF
    That is Lucy signing in to OwnerVille. It has a red bar across the
    top. Please leave it completely alone -- do not type your password
    and do not tick the security box. It clears on its own, and touching
    it stops the sign-in. The window closes by itself.

IF YOU CHANGE A PASSWORD
    Run the installer again and enter the new one. Nothing else changes.

QUESTIONS
    Tell the reporting team. Please do not share this folder with anyone --
    it contains a code that is specific to your office.
"""


def build(office_key: str, relay_key: Optional[str] = None,
          make_zip: bool = True, platform: str = "both", log=print) -> Path:
    office = O.get(office_key)
    if not office:
        raise SystemExit(
            "no office %r in offices.py. Add the row there first -- it is what "
            "decides where the alerts post and whether they post at all."
            % office_key)

    if not relay_key:
        relay_key = _relay_key_from_sheet(office.key, log=log)

    folder = OUT / ("lucy-reports-%s" % office.key)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    # EVERYTHING EXCEPT THE INSTALLER GOES IN A SUBFOLDER. An owner who
    # unzipped this saw six items -- ask.py, setup.py, install.json, a folder
    # called automations -- and told Megan "nothing happened, there are just a
    # bunch of files" (2026-09-12, live on the enrolment call). The installer
    # has no icon and does not stand out among them. Two items, one of which
    # says Install, is a folder somebody can act on.
    app = folder / APP_SUBDIR
    for rel in AGENT_FILES:
        dest = app / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)
    (app / "automations" / "__init__.py").write_text(BUNDLE_INIT)
    (app / "automations" / "shared" / "__init__.py").write_text("")

    shutil.copy2(DIST / "setup.py", app / "setup.py")

    if platform in ("mac", "both"):
        shutil.copy2(DIST / "Install Lucy Reports.command",
                     folder / "Install Lucy Reports.command")
        (folder / "Install Lucy Reports.command").chmod(0o755)

    if platform in ("windows", "both"):
        # CRLF, always. A .bat with bare LF endings is parsed unreliably by
        # cmd.exe, and this repo is developed on a Mac -- so the file on disk
        # here has LF and would ship that way unless converted on the way out.
        bat = (DIST / "Install Lucy Reports.bat").read_text()
        (folder / "Install Lucy Reports.bat").write_bytes(
            bat.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    (app / "install.json").write_text(json.dumps({
        "office_key": office.key,
        "owner": office.owner,
        "relay_url": O.RELAY_URL,
        "relay_key": relay_key,
        # The knocks report IS the KNOCKS & DISPOSITIONS board that
        # disposition_signup already enrolls offices into (Megan 2026-09-11:
        # "it's the same thing"), so the installer offers ITS choices, in its
        # words, and hands back ITS canonical values. Baked in at build time
        # rather than retyped in the installer: one source of truth, and a
        # rebuilt package picks up any change to the picker for free. A second
        # vocabulary would be two things to keep in step forever.
        "knocks_picker": _knocks_picker(),
        "knocks_default_hours": _default_hours(office),
    }, indent=2))

    label = "%s (%s)" % (office.label, office.owner)
    how = {
        "mac": '    Double-click "Install Lucy Reports.command"',
        "windows": '    Double-click "Install Lucy Reports.bat"',
        "both": ('    Mac:      double-click "Install Lucy Reports.command"\n'
                 '    Windows:  double-click "Install Lucy Reports.bat"'),
    }[platform]
    gatekeeper = GATEKEEPER if platform in ("mac", "both") else ""
    (folder / "README.txt").write_text(README.format(
        label=label, underline="=" * (len("Lucy Reports -- ") + len(label)),
        channel=_channel_blurb(office), how=how, gatekeeper=gatekeeper))

    log("built %s" % folder)
    for f in sorted(p.relative_to(folder) for p in folder.rglob("*") if p.is_file()):
        log("   %s" % f)

    if make_zip:
        archive = folder.with_suffix(".zip")
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(folder.parent))
        log("\nzipped -> %s (%d KB)" % (archive, archive.stat().st_size // 1024))
        return archive
    return folder


def _knocks_picker():
    """[{'value': minutes, 'label': '...'}] straight from the disposition schema."""
    from automations.disposition_signup import schema as S
    return [{"value": m, "label": S.cadence_picker_label(m)}
            for m in S.CADENCE_PICKER]


def _default_hours(office):
    """THIS office's field hours, in its own clock.

    Off the office record, NOT the org default. The record is what the board
    is actually gated on, so shipping the org's 10:45-18:30 to an office whose
    Saturday is 10:30-17:00 would show the owner hours to confirm that are not
    the hours we use -- and they would confirm them, because they were asked.

    The timezone comes from the record too: it is already known, and "which
    timezone are you in" is a question with a wrong answer available.
    """
    return {"day_start": office.day_start, "day_end": office.day_end,
            "sat_start": office.sat_start, "sat_end": office.sat_end,
            "saturday": office.saturday, "tz": office.timezone}


def _channel_blurb(office) -> str:
    """What the README tells the owner about where their alerts land.

    An office with no channel decided yet must NOT be told a room name -- they
    would go looking for it, not find it, and ask why it is broken.
    """
    if not office.channels:
        return "your team's Slack channel"
    return ", ".join(c.name for c in office.channels)


def _relay_key_from_sheet(office_key: str, log=print) -> str:
    """Read this office's key off the 'Relay Keys' tab.

    Read rather than generated, so the key in the package and the key the
    endpoint will accept cannot drift apart -- a mismatch presents as 'not
    authorised' on a laptop nobody can log into.
    """
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    tab = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet("Relay Keys")
    for row in tab.get_all_values()[1:]:
        if len(row) > 2 and row[0].strip().lower() == office_key:
            if row[2].strip().upper() not in ("TRUE", "YES", "Y"):
                raise SystemExit(
                    "%r is on the 'Relay Keys' tab but is not Active. Switch it "
                    "on before building, or its laptop will install fine and "
                    "then be refused." % office_key)
            log("read %s's relay key off the sheet" % office_key)
            return row[1].strip()
    raise SystemExit(
        "no row for %r on the 'Relay Keys' tab. Add one (Office | Key | Active "
        "| Note) before building -- the package has to carry a key the "
        "endpoint will actually accept." % office_key)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build an ICD's installer folder")
    ap.add_argument("office", help="office key, e.g. kash")
    ap.add_argument("--no-zip", action="store_true")
    # GMAIL BLOCKS .bat FILES, INCLUDING INSIDE A ZIP. A package built "both"
    # cannot reliably be emailed at all -- it is stripped or bounced, and the
    # bounce does not say why. Build for the platform the office actually uses.
    ap.add_argument("--platform", choices=("mac", "windows", "both"),
                    default=None,
                    help="which launcher to include. Defaults to the office's "
                         "own `platform` in offices.py, because GMAIL BLOCKS "
                         ".bat EVEN INSIDE A ZIP -- a 'both' package cannot "
                         "reliably be emailed and the bounce does not say why.")
    args = ap.parse_args(argv)
    office = O.get(args.office)
    platform = args.platform or (office.platform if office else "both")
    build(args.office, make_zip=not args.no_zip, platform=platform)
    return 0


if __name__ == "__main__":
    sys.exit(main())
