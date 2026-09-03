"""SaraPlus B2B customers -> RingCentral contacts, plus a 'nobody texted them'
alert (Carlos, 3 Looms 2026-09-02).

Every morning, for YESTERDAY's B2B sales:

  0. SaraPlus asks for an emailed VERIFICATION CODE at login. Carlos has it
     filtered to alphaletereporting@gmail.com, so the login submits the
     password, reads the code out of that inbox (only mail that arrived AFTER
     the submit -- an older code is somebody else's, already expired, and
     would be typed in with total confidence and fail as "wrong password"),
     types it, and carries on. verify_code.py.
  1. SaraPlus -> Analytics -> Detail Reports -> Sales Order History, date range
     = yesterday, Customer Type = Both, Submit. Each row gives the rep
     (User Name) and the Business Name; 'View Customer' gives the customer's
     name and Primary Phone.
  2. RingCentral -> create a personal contact in TAYLOR's address book:
        Company   = business name
        First/Last= customer name
        Phone     = primary phone (Mobile)
        Notes     = "Rep Name: <the rep>"
  3. RingCentral -> was each customer EVER messaged on that line? (Megan
     2026-09-03: "we're just looking to see if that customer was ever
     messaged by ring[central] and if not, putting those names in the thread
     of that header message.") Matched by phone, and as a backstop by
     customer or business name. The window opens at the sale day and runs to
     now, not just the sale's own calendar day: a customer sold at 5:55pm and
     messaged next morning HAS been contacted.

     Two Slack messages, in #a-players-b2b only ("we dont need a text. slack
     works"): a HEADER post carrying Carlos's own sentence -- "Customers who
     didn't receive wrap up text" -- and the names as a REPLY in that
     header's thread, grouped by the rep who sold them.

     THE HEADER SAYS 'WRAP UP TEXT' AND THE CHECK IS 'ANY MESSAGE'. That is
     not a bug to tidy up. Asked what he wanted the message to SAY, Carlos
     answered with that sentence; he was naming the post, not narrowing the
     test. (Megan corrected exactly that misreading on 2026-09-03.)

RUNS ON LUCY 2 (Carlos's box) -- his SaraPlus login and his RingCentral account.

IDENTITY MATTERS TWICE HERE and both are easy to get wrong silently:
  * SaraPlus must be CARLOS's login (carhi1816@gmail.com, Megan 2026-09-02).
    Lucy 1's alphaletemarketing@ login reaches a different dealer's orders --
    it would return rows, just not these rows. Hence its own creds file and
    its own Chrome profile, never the sales-board sweep's.
    [[reference_ov_session_identity]]
  * RingCentral must be TAYLOR's login (taylormkmiller7@gmail.com, ext 134 --
    Megan 2026-09-02), and there are TWO RingCentral accounts in this
    business. The one wired into rc_autoread / disconnect_followup is the
    HR/AT&T account (main +1 207-464-7960: Dylan Twaddle, AIsha Ceron, ...)
    and Taylor has NO extension in it. The B2B one is 'Alphalete Specialized
    Marketing' -- Carlos ext 101, Mayra Cruz 113, Taylor Miller 134. Signing
    in as Taylor is what makes this one identity instead of two: the contacts
    land on the line that texts these customers, and that same line's inbox is
    the one the follow-up check reads. ringcentral.assert_identity() refuses
    to write until the token proves it is her.

Nothing here writes a Sheet.
"""
