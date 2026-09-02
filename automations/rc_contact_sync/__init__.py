"""SaraPlus B2B customers -> RingCentral contacts, plus a 'nobody texted them'
alert (Carlos, 3 Looms 2026-09-02).

Every morning, for YESTERDAY's B2B sales:

  1. SaraPlus -> Analytics -> Detail Reports -> Sales Order History, date range
     = yesterday, Customer Type = Both, Submit. Each row gives the rep
     (User Name) and the Business Name; 'View Customer' gives the customer's
     name and Primary Phone.
  2. RingCentral -> create a personal contact in TAYLOR's address book:
        Company   = business name
        First/Last= customer name
        Phone     = primary phone (Mobile)
        Notes     = "Rep Name: <the rep>"
  3. RingCentral -> read Taylor Miller's (ext 134) SMS for yesterday. Any
     customer with NO message to/from that line gets named in one Slack post
     into the day's metrics thread in #a-players-b2b and #alphalete-gp-sales.

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
