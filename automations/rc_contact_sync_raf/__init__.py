"""Raf's office wrap-up check — "who texted the customer and who didn't."

A mirror of automations/rc_contact_sync (Carlos's B2B Customer Contacts) for
RAF's office, run against DYLAN's RingCentral line — the same account
rc_autoread / disconnect_followup already use (main +1 214-845-6450, ext
62883924016). Built with Dylan 2026-10-20.

Every morning, for YESTERDAY's sales under Raf's SaraPlus dealer code (ALL
reps, not just a roster):

  1. Raf's SaraPlus -> Sales Order History -> yesterday. The pull runs on
     LUCY 1 (Raf's verified sales-board profile, no emailed-passcode step —
     see sp_order_log/raf_guest.py) and the raw, UNFILTERED export crosses to
     the run box the way every sp_order_log artifact does: base64-chunked into
     a control-sheet tab. pull_raf.py does the Lucy 1 half; customers.py
     decodes it.
  2. RingCentral -> was each customer EVER messaged on Dylan's line? (Matched
     by phone, backstop by customer/business name. Window opens at the sale
     day and runs to now — a customer sold at 5:55pm and texted next morning
     HAS been contacted.) Reuses rc_contact_sync.ringcentral.{sms_since,
     texted_any} verbatim; only the token and the watched extension differ.
  3. Slack -> a HEADER post "Customers who didn't receive wrap up text" and
     the names as a REPLY in its thread, grouped by the rep who sold them, in
     #alphalete-sales.

WHAT THIS MIRROR DOES NOT DO: create RingCentral contacts. Carlos's version
writes each B2B customer into Taylor's address book so a reply shows a name.
Dylan's RingCentral app (the rc_autoread one) holds the scopes
`ReadMessages ReadAccounts EditMessages` but NOT `ReadContacts` — the
address-book API returns 403 InsufficientPermissions. The message check (the
whole point: who got a wrap-up and who didn't) needs only ReadMessages and
works today. To light up the contacts half, add ReadContacts + Contacts to
that RingCentral app and re-mint the JWT; nothing here has to change but the
scope.

IDENTITY: the token must belong to Dylan's extension (owner_id 62672491016),
the same JWT baked into automations/rc_autoread/run.py. A token for any other
RingCentral user would read the wrong inbox and name the wrong reps in Slack,
so run() verifies owner_id before it posts. Nothing here writes a Sheet.
"""
