"""Applicant -> alphaletereception's Google Contacts, from a Slack DM to Jiraiya.

Raf, 2026-10-22: "Can we have a DM bot or channel that I can text a screenshot
of applicant info or text the info and automatically gets added to
alphaletereception contact distro please?" Eve: the GENERAL contact list (no
group).

How it works:
  1. Raf DMs Jiraiya a screenshot and/or the applicant's info as text.
  2. A branch in Jiraiya's listener (due_diligence/bot.py) sees it. It counts
     as an applicant message when it carries an image, or its text has a phone
     number or an email -- a DD corrected-name reply has neither, so the two
     features never read each other's messages.
  3. Claude reads the text/picture -> name, phone, email (extract.py). It may
     only copy what is there; a missing field stays blank, never guessed.
  4. contacts.py creates the contact in alphaletereception@gmail.com. Same
     phone (last 10 digits) or same email already there -> not added twice.
  5. Jiraiya replies in the DM's thread with exactly what it added, or what it
     couldn't (no name, or neither phone nor email).

Only ALLOWED_USERS are served (dm.py). Read-write Contacts token for
reception: contacts-rw-token-alphaletereception.json, authorized once by
someone signed in as reception, then pushed to the box that runs Jiraiya.

    # one-time, on a machine with a browser (sign in as alphaletereception@):
    python -m automations.fiber_owners_distro.contacts_write --authorize --account alphaletereception@gmail.com

    # try it without Slack (dry-run unless --write):
    python -m automations.applicant_contacts.run --text "Juan Perez 214-555-0101 juan@x.com"
    python -m automations.applicant_contacts.run --image shot.png --write
"""
