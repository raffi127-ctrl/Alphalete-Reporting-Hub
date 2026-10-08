"""Regression tests for the Vantura Slack sales parser.

Every message body below is a REAL post from #alphalete-gp-sales (2026-07-17
through 07-23; 2026-10-06/07 for Verizon), trimmed of shout-outs — the Verizon
ones verbatim. Each one broke, or nearly broke, an earlier version of the
parser, or was confirmed by Megan / Carlos directly.

  python -m automations.vantura_slack_sales.test_parse
"""
from __future__ import annotations

import datetime as dt

from automations.vantura_slack_sales import parse as P

CDT = dt.timezone(dt.timedelta(hours=-5))


def _post(text, hh=18, mm=0, day=22, author="Rep", files=0):
    return P.read_post("1.0", dt.datetime(2026, 7, day, hh, mm, tzinfo=CDT),
                       author, "U1", text, files=files)


def _tallied(text, campaign, **kw):
    """What one post contributes to the day's count. Not the same as
    PostRead.count, which is 0 for an unnumbered post — the day tally is what
    turns that into 1."""
    p = _post(text, **kw)
    rec = P.tally([p], p.sales_day, campaign)
    return p, (rec[p.author]["count"] if rec else 0)


CASES = [
    # (label, text, campaign, sales it contributes to the day)

    # Base cases RETIRED 2026-08-30 — the campaign ended; D2D/Base posts
    # now classify as None (both remaining campaigns exclude d2d).

    # --- BOX: business energy ---------------------------------------------
    ("box numbered", "B2B :package::zap:\nBill Submitted :white_check_mark:\n\n"
     "BF 1\n\n36 month term\n5,304KWH\nCX 3\nBox #3", "BOX", 3),
    # Megan 2026-07-23: "this would be 1 box sale" — BF 2 but ONE sale, so BF
    # is a bill reference, NOT the counter. CX is the counter.
    ("box bf is not the counter",
     "B2B :package::zap:\nBill Submitted :white_check_mark:\n\nBF 2\n\n"
     "36 month term\n51,840 KWH\nCX 1", "BOX", 1),
    ("box two in one post", "B2B :package::zap:\nBill Submitted\n\nBF 3\n"
     "60 month term\n116,568 KWH\nCX 2\nBox #2\nBox #3", "BOX", 3),
    ("box header spelled out", "BOX \n\nCX 1\n\nBF 1\n\nTerms 36 months\n"
     "Annual Usage 111,660kWh", "BOX", 1),

    # --- B2B: AT&T lines and fiber ----------------------------------------
    # Megan 2026-07-23: "this would be 3 at&t sales" / "NL=At&t sale".
    ("att three lines", "B2B(consumer)\nAutopay yes\nWrap up text sent\n\n"
     "CX1\nNL 1\nNL 2\nNL3", "B2B", 3),
    ("att lines plus fiber", "B2B (Business)\nAuto Pay on\n\nCx 1\n\nNL 1\n"
     "NL 2\n\nNL 3\n\nNL 4\n\nNL 5\n\nCX 2\n\nFiber 1000 #6", "B2B", 6),
    # Inseego on its OWN line IS a line item (William Bautista 7/16): 3 NL + 1.
    ("att standalone inseego line", "B2B (consumer)\nCx1\nNL #1\nCx2 (business)"
     "\nNL #2\nInseego #3\nCx3 (consumer)\nNL #4", "B2B", 4),
    # Inseego with no NL at all is the line itself (Nick Smedra 7/14) = 1.
    ("att inseego only", "B2B (Business)\nAutopay :white_check_mark:\n"
     "Wrap up text\nCx1 Inseego", "B2B", 1),
    # Bare "NL" with no number (Giovanni Monreal 7/16) = 1 line.
    ("att bare nl", "B2B (consumer)\nAuto pay :white_check_mark:\nCx1\nNL", "B2B", 1),
    # "NL - 1" with a dash (Eric Forsythe 7/18) = 1 line.
    ("att nl dash", "B2B BUSINESS\nCx1\nNL - 1", "B2B", 1),
    # "NL BYOD" — bare NL annotated with the device (Luis 7/14) = 1.
    ("att nl byod no number", "B2B (Business)\nWrapUp\nAutopay\nCx1\n"
     "NL BYOD (Premium)", "B2B", 1),
    ("att fiber only", "B2B (consumer)\nAuto pay :white_check_mark:\n\n"
     "Fiber 1g", "B2B", 1),
    ("att byod lines", "B2B (Business)\n\nCx 1\n\nNL 1 (BYOD)\n\nNL 2 (BYOD)\n\n"
     "NL 3 (BYOD)\n\nNL 4 (BYOD)", "B2B", 4),
    # Jolie/Carlos 2026-07-24: Eric was double-counted. "inseego air" is the
    # LINE TYPE, not a second sale — the one NL is one sale.
    ("att inseego is a line type", "B2B BUSINESS\nWrap Text sent W/ Taylor "
     ":white_check_mark:\nAuto Pay on\n\nNL 1 inseego air", "B2B", 1),
    # Same report: Diego wrote the number BEFORE "NL" and went uncounted.
    ("att number-first NL", "B2B (Business)\nWrap Text sent\nAuto Pay on\n\n"
     "AT&T\n\n1 NL ( PREMIUM )\n\n2 NL ( Premium )", "B2B", 2),

    # --- BYOD is a line item, not a device note (Carlos 2026-08-08) --------
    # THE post Carlos flagged: Jacob Ortega 8/7 12:51 posted four apps and only
    # the NL counted. Note "BOYD" — the transposition he actually types.
    ("att byod line items", "B2B (business)\nAuto pay :white_check_mark:\n\n"
     "AT&T\n\nNL 1 \n\nBOYD 2 \n\nBYOD 3 \n\nBYOD 4 ", "B2B", 4),
    # Same rep, 8/5 16:39 — three apps, counted as one.
    ("att byod three", "B2B (business)\nAuto pay :white_check_mark:\n\nAT&T\n\n"
     "NL 1 \n\nBYOD 2 \n\nBYOD 3 ", "B2B", 3),
    # Emmanuel Nieto 8/5 21:03, no spaces around the hash.
    ("att byod glued hash", "*B2B business* \n*Auto Pay on* :white_check_mark:\n"
     "\nNL #1\n\nNL #2\n\nByod#3\n\nByod#4", "B2B", 4),
    # An all-BYOD post with no NL/Fiber anywhere: the AT&T HEADER is the only
    # thing that says which campaign this is. Before the header rule this was
    # read as chatter and counted zero.
    ("att byod only, header carries it",
     "B2B (business)\n\nAT&T\n\nBYOD 1\n\nBYOD 2", "B2B", 2),
    # ...and BYOD hanging off an NL line is still ONE sale, same as inseego.
    ("att byod is a device note", "B2B (Business)\nWrap Text sent\nAuto Pay on\n"
     "\nAT&T\n\nNL 1 (BYOD)\n\nNL 2 (BYOD)", "B2B", 2),

    # --- the last-resort fallback -----------------------------------------
    # A product nobody has taught the parser yet. The header + the numbering is
    # all there is to go on, so the highest number wins (Carlos's rule).
    ("att unknown product falls back to the numbers",
     "B2B (business)\n\nAT&T\n\nHotspot 1\n\nHotspot 2\n\nHotspot 3", "B2B", 3),
    # ...but it must NOT fire when real products were counted. William Bautista
    # numbers ACROSS his posts (#1 in one, #2-#9 in the next), so a max() here
    # would score this post 9 instead of 8 and double his day.
    ("att fallback never overrides a real count",
     "*B2B BUSINESS*\n*Auto Pay on*\n\nNL #2\n\nNL #3\n\nNL #4\n\nNL #5\n\n"
     "NL #6\n\nNL #7\n\nNL #8\n\nFiber 300 #9", "B2B", 8),
    # Shout-out lines carry numbers too — they must never be read as line items.
    ("att fallback ignores mentions",
     "B2B (business)\n\nS/O <@U123> <@U456> 100\n\nAT&T\n\nBYOD 1\n\nBYOD 2",
     "B2B", 2),

    # --- BOX: two contracts under one counter ------------------------------
    # Jayden Luna 8/3 19:29 — two bills, one "Box #3". Before this the post was
    # worth 3 for the day; the second BF now has to be worth at least 4... which
    # it isn't, because #3 is already >= 2 contracts. What this case pins is the
    # SAFE half: the count never drops and never inflates past the counter.
    ("box two contracts under one counter",
     "B2B :package::zap:\n\nBF 1\n16,956 kWh\n\nBF 4\n43,800 kWh\n\nBox #3",
     "BOX", 3),
    # The one that actually gains: two bills, no counter at all. Was 1.
    ("box two contracts no counter",
     "B2B :package::zap:\nBill Submitted\n\nBF 1\n36 month term\n16,956 kWh\n\n"
     "BF 4\n36 month term\n43,800 kWh", "BOX", 2),
    # "Bill Submitted" and "BF 1" are the SAME contract said twice — the
    # standard post must not become 2.
    ("box standard post is still one",
     "B2B :package::zap:\nBill Submitted :white_check_mark:\n\nBF 1\n\n"
     "36 month term\n5,304KWH\nCX 1", "BOX", 1),
    # A BOX post that mentions autopay is still BOX — it used to be thrown to
    # the AT&T campaign by the exclude list.
    ("box mentioning autopay stays box",
     "B2B :package::zap:\nBill Submitted\nAuto Pay on :white_check_mark:\n\n"
     "BF 1\n36 month term\n21,204KWH\nBox #1", "BOX", 1),
    # Unhashed counter.
    ("box unhashed counter", "B2B :package::zap:\n\nBF 1\n21,204KWH\n\nBox 2",
     "BOX", 2),

    # --- Verizon: door-to-door Verizon lines (joined 2026-10-08) -----------
    # Verbatim 2026-10-06/07 posts. The word "Verizon" makes a post Verizon;
    # its NL items are the count (Carlos 2026-10-08).
    ("vz header + one line (Giovanni Monreal 10/7 15:13)",
     "*VERIZON D2D* \n*Wrap Text sent* \n*Auto Pay on* :white_check_mark:\n\n"
     "<@U0C6YL2U9UH|Alexis Alejo> *LETS GO ON THE BOARD ON HIS FIRST DAY*"
     ":fire::fire:\n\n*S/O Abram*:fire::fire::fire: *for being a goat*:fire:\n\n"
     "<@U047D64M0RW|Nico Murrugarra> *for being da GOAT*:goat:\n\n"
     "*S/O* <@U0A3XUYSB1U|Eric Forsythe> <@U0ABP13LU91|Richard Bautista>  "
     "<@U07R8Q3FTLM|William Bautista> <@U0B5WLHQ752|Luis Adan Valenciano> "
     "da team:fire::fire::fire:\n\n*S/O* <@U047D64M0RW|Nico Murrugarra> "
     "<@U046G04P5LG|Carlos Hidalgo> *for a the amazing opportunity!! \n\n"
     "NL #1* \n\n*\u201cAnd the LORD, He is the One who goes before you. He "
     "will be with you, He will not leave you nor forsake you; do not fear nor "
     "be dismayed.\u201d\u201d\n\u202d\u202dDeuteronomy\u202c \u202d31\u202c:"
     "\u202d8\u202c \u202dNKJV\u202c\u202c*\n"
     ":pray::skin-tone-3::sunrise_over_mountains:", "Verizon", 1),
    # "D2D Verizon" header, hashed line numbers (William Bautista 10/7 18:23).
    ("vz d2d verizon header, NL #1-#3",
     "*D2D Verizon* \nWrap up text \n*Auto Pay on* \n\n*S/O* <@U0ABP13LU91|Richard "
     "Bautista>  <@U0BBVDYCFB9|Giovanni Monreal> <@U0B5WLHQ752|Luis Adan "
     "Valenciano>  <@U0A80F907N3|Edgar Camunez> <@U0A0MPGHJ0G|Jayden Luna> "
     "<@U047D64M0RW|Nico Murrugarra> <@U0C5XCVMMS4|Angel Rivera> LOA'S:fire:\n\n"
     "S/O <@U047D64M0RW|Nico Murrugarra> <@U046G04P5LG|Carlos Hidalgo> for a the "
     "amazing opportunity!! \n\nNL #1\n\nNL #2\n\nNL #3\n\n\u201cStay hard\u201d"
     " - David goggins", "Verizon", 3),
    # His second post that evening (19:58) CONTINUES the numbering: #4-#9 is
    # six lines, and with the 18:23 post that is his board 9. A highest-number
    # reading would score this post 9 on its own and the day 12.
    ("vz numbering continues across posts, NL #4-#9",
     "*D2D Verizon* \nWrap up text \n*Auto Pay on* \n\n*S/O* <@U0ABP13LU91|Richard "
     "Bautista>  <@U0BBVDYCFB9|Giovanni Monreal> <@U0B5WLHQ752|Luis Adan "
     "Valenciano>  <@U0A80F907N3|Edgar Camunez> <@U0A0MPGHJ0G|Jayden Luna> "
     "<@U047D64M0RW|Nico Murrugarra> <@U0C5XCVMMS4|Angel Rivera> LOA'S:fire:\n\n"
     "S/O <@U047D64M0RW|Nico Murrugarra> <@U046G04P5LG|Carlos Hidalgo> for a the "
     "amazing opportunity!! \n\nNL #4\n\nNL #5\n\nNL #6\n\nNL #7\n\nNL #8\n\n"
     "NL #9\n\n\u201cStay hard\u201d - David goggins", "Verizon", 6),
    # CX1 is the customer index, never a sale (Gary Vanwhitaker 10/7 18:36).
    ("vz cx is a customer marker, not a sale",
     "*VERIZON (D2D)*\n:bangbang::bangbang::bangbang::bangbang::bangbang:"
     ":chart_with_upwards_trend:\n\n\n*S/O*  <@U07R8Q3FTLM|William Bautista> "
     "<@U0BBVDYCFB9|Giovanni Monreal> <@U0B5WLHQ752|Luis Adan Valenciano> "
     "<@U0A0MPGHJ0G|Jayden Luna> <@U0A80F907N3|Edgar Camunez> <@U09EA9XL9NZ|Hamid "
     "Asim>\n<@U047D64M0RW|Nico Murrugarra> <@U0A6XE8S36E|Diego Chacon> "
     "<@U0BAYDXHXB7|Thais> <@U0ABP13LU91|Richard Bautista>\n\nS/O "
     "<@U047D64M0RW|Nico Murrugarra> <@U046G04P5LG|Carlos Hidalgo> for a the "
     "amazing opportunity!! \n\nCX1\n\nNL#1 \n\n\n", "Verizon", 1),
    # BYOD is a line attribute, not a second line (Yariel caban 10/7 18:37).
    ("vz byod is a line attribute",
     "*VERIZON (D2D)*\n:bangbang::bangbang::bangbang::bangbang::bangbang:"
     ":chart_with_upwards_trend:\n\n\n*S/O*  <@U07R8Q3FTLM|William Bautista> "
     "<@U0BBVDYCFB9|Giovanni Monreal> <@U0B5WLHQ752|Luis Adan Valenciano> "
     "<@U0A0MPGHJ0G|Jayden Luna> <@U0A80F907N3|Edgar Camunez> <@U09EA9XL9NZ|Hamid "
     "Asim>\n<@U047D64M0RW|Nico Murrugarra> <@U0A6XE8S36E|Diego Chacon> "
     "<@U0BAYDXHXB7|Thais> <@U0ABP13LU91|Richard Bautista>\n\nS/O "
     "<@U047D64M0RW|Nico Murrugarra> <@U046G04P5LG|Carlos Hidalgo> for a the "
     "amazing opportunity!! \n\nCX1\n\nNL#1\nNL#2 BYOD \n\n\n", "Verizon", 2),
    # Number BEFORE the NL, "D2D (Verizon)" header (Diego Chacon 10/7 18:42).
    ("vz number-first NL",
     "D2D (Verizon)\n\nCx1 \n\n1 NL\n\n2 NL \n\n3 NL\n\nS/o <@U047D64M0RW|Nico "
     "Murrugarra> let's get this paper papa :triumph:\n\nS/o <@U046G04P5LG|Carlos "
     "Hidalgo> <@U047D64M0RW|Nico Murrugarra> thank you for this opportunity "
     ":pray::skin-tone-4::saluting_face:\n\nWHO HAS MY MONEY!!!! "
     ":triumph::triumph::triumph:", "Verizon", 3),
    # No D2D anywhere, glued "NL4" / "NL5" and a "BOX GIRLS" shout-out: this
    # read as 5 AT&T sales before the Verizon rule (Jayden Luna 10/6 19:38).
    ("vz no d2d header is still verizon, not att",
     "VERIZON :grey_heart::heart:\n:fire::fire::fire:\n\nS/o MY DAWGS :goat: "
     "<@U047D64M0RW|Nico Murrugarra> <@U0A80F907N3|Edgar Camunez> "
     "<@U07R8Q3FTLM|William Bautista>\n\nS/o MY BOX GIRLS :pink_heart: "
     "<@U0BL716KWJV|Kandice M Flores> <@U0BMT31A54L|Ruby Flores> :goat::fire: las "
     "DAWGS\n\nS/o <@U046G04P5LG|Carlos Hidalgo>  for the opportunity :goat:\n\n\n"
     "NL 1\nNL 2\nNL 3\nNL4\nNL5", "Verizon", 5),
    # A line attribute after the number ("16e", the phone) adds no line
    # (Gary Vanwhitaker 10/6 18:21).
    ("vz line attribute after the number",
     "*VERIZON (D2D)\n\n\n\nS/O*  <@U07R8Q3FTLM|William Bautista> "
     "<@U0BBVDYCFB9|Giovanni Monreal>\n\nS/O <@U047D64M0RW|Nico Murrugarra> "
     "<@U046G04P5LG|Carlos Hidalgo> for a the amazing opportunity!! \n\n"
     "CX1\n\nNL#1 16e\nNL#2 16e\n", "Verizon", 2),
    # The NL above the wrap-up lines (Thais 10/6 19:22).
    ("vz line before the wrap-up lines",
     "VERIZON D2D\n\nNL 1 \n\nWRAP UP TEXT :saluting_face:\nAUTO PAY "
     ":saluting_face:\n\nS/O <@U0A0MPGHJ0G|Jayden Luna> & Jayda W CAR RIDE \n\n"
     "S/O <@U047D64M0RW|Nico Murrugarra> <@U046G04P5LG|Carlos Hidalgo> thanks for "
     "the opportunity !\n\n\n", "Verizon", 1),
    # A Verizon post with no NL item at all is ONE sale, flagged in the log —
    # the early posts looked like this (Carlos 2026-10-08).
    ("vz no NL item counts as one",
     "VERIZON :grey_heart: :fire:\n\nS/o MY DAWGS :goat: <@U047D64M0RW|Nico "
     "Murrugarra>\n\nS/o <@U046G04P5LG|Carlos Hidalgo> for the opportunity :goat:",
     "Verizon", 1),

    # --- NOT Verizon: the AT&T program sells door to door too --------------
    # "D2D" alone never makes a post Verizon. These AT&T posts read exactly as
    # they did before the Verizon rule (an AT&T post with D2D is excluded).
    ("d2d at&t is not verizon (Nicholas Smedra 10/7)",
     "D2D AT&T\n\nWrap Text sent W/ <@U09PTHQJ481|Taylor Miller> :white_check_mark:"
     "\n\nAuto Pay on :white_check_mark:\n\nAT&T\n\nNL 1 \n\nNL 2 \n\nNL 3 \n\nNL 4",
     None, 0),
    ("bare d2d is not verizon (Diego Borres 10/7)",
     "D2D \n\nAuto pay :white_check_mark:/ <@U09PTHQJ481|Taylor Miller>"
     ":white_check_mark:\n\nAT&T\n\nNL 1 \n\nNL 2\n\nNL 3\n\nNL 4\n\nNL 5 \n",
     None, 0),
    ("at&t d2d is not verizon (Rodolfo Bazan 10/7)",
     "AT&T D2D \n\nAuto pay :white_check_mark:/ <@U09PTHQJ481|Taylor Miller>"
     ":white_check_mark:\n\nAT&T\n\n\nNL 1 \n", None, 0),
    ("box post is still box (Joelle Barajas 10/7)",
     "B2B :package::zap:\n\nS/O The team :pink_heart::revolving_hearts:  "
     "<@U0BCBF73GRF|Nathaly Benitez>\n\nBF 4\n24 months\n35,892 kwh \nBox #1\n"
     "Bill submitted :white_check_mark:", "BOX", 1),

    # --- not sales at all --------------------------------------------------
    # The office's running tally. Its numbers are the WHOLE FLOOR's day, so
    # reading one as a sale would hand one rep the entire office.
    ("bare office tally", "A&T - 16/20 :calling:\nBox - 10/12", None, 0),
    ("att line up is not a sale", "AT&T LINE UP", None, 0),
    ("goals post", "Todays Goals:bangbang:\nA&T - 9/20\nBox - 7/8\nBase -4/15",
     None, 0),
    # The same tally with a Verizon line (Sebastian Avellaneda 10/7 20:55):
    # the 16 is the whole floor's day, never one rep's.
    ("goals post with verizon", "Todays Goals:bangbang:\nA&T -20/12:calling:\n"
     "Box 12/10:package::zap:\nVerizon - 16/15:bangbang:", None, 0),
    ("bare verizon tally", "Verizon - 16/15:bangbang:", None, 0),
    ("hype", "WHOSSS FIRST (BASE ):eyes:!!", None, 0),
    ("line up", "LINE UP", None, 0),
]


def test_cases():
    bad = []
    for label, text, want_campaign, want_count in CASES:
        p = _post(text)
        count = _tallied(text, want_campaign)[1] if want_campaign else 0
        if p.campaign != want_campaign or count != want_count:
            bad.append(f"{label}: got campaign={p.campaign} count={count}, "
                       f"want {want_campaign}/{want_count}")
    return bad


def test_running_counter():
    """BOX numbers are cumulative for the day — max, never sum."""
    posts = [_post("B2B :package:\n\nBF 1\n998 kWh\n\nBox 1", hh=15),
             _post("B2B :package:\n\nBF 1\n1998 kwh\n\nBox 2", hh=16),
             _post("B2B :package:\n\nBF 1\n1299kwh\n\nBox 3", hh=16, mm=30)]
    got = P.tally(posts, dt.date(2026, 7, 22), "BOX")["Rep"]["count"]
    return [] if got == 3 else [f"running counter: got {got}, want 3"]


def test_units_sum():
    """AT&T line numbering RESTARTS each post, so units sum. Jacob Ortega
    2026-07-22: NL1-5, then a Fiber, then another 'NL 1' = 7, and the board
    had him at 7. max() would have said 5."""
    posts = [_post("B2B (consumer)\n\nNL 1\nNL 2\nNL 3\nNL 4\nNL 5", hh=13),
             _post("B2B (consumer)\n\nFiber 1g", hh=13, mm=44),
             _post("B2B (business)\n\nNL 1", hh=17)]
    got = P.tally(posts, dt.date(2026, 7, 22), "B2B")["Rep"]["count"]
    return [] if got == 7 else [f"units sum: got {got}, want 7"]


# test_run_on_address RETIRED with Base 2026-08-30 (Cx-address counting
# was a Base-only parse path).


def test_verizon_units_sum():
    """Verizon numbers CONTINUE across a rep's posts and SUM: William
    Bautista 2026-10-07 posted NL #1-#3 at 18:23 and NL #4-#9 at 19:58 — 9
    for the day, the board's 9. A per-day max() would have said 9 + 3."""
    posts = [_post("*D2D Verizon* \nWrap up text \n*Auto Pay on* \n\n"
                   "NL #1\n\nNL #2\n\nNL #3", hh=18, mm=23),
             _post("*D2D Verizon* \nWrap up text \n*Auto Pay on* \n\n"
                   "NL #4\n\nNL #5\n\nNL #6\n\nNL #7\n\nNL #8\n\nNL #9",
                   hh=19, mm=58)]
    got = P.tally(posts, dt.date(2026, 7, 22), "Verizon")["Rep"]["count"]
    return [] if got == 9 else [f"verizon units sum: got {got}, want 9"]


def test_verizon_office_tally():
    """The office's running tally has a Verizon line now. The LAST one of the
    day is the check (16 on 2026-10-07), no tally post is ever a sale, and
    the B2B / BOX readings of the same posts are untouched."""
    from automations.vantura_slack_sales import run as R
    day = dt.date(2026, 7, 22)
    posts = [_post("Todays Goals:bangbang:\nA&T -14/12:calling:\n"
                   f"Box 12/10:package::zap:\nVerizon - {v}:bangbang:",
                   hh=h, mm=m, author="Sebastian Avellaneda")
             for v, h, m in [("1/15", 17, 50), ("4/15", 18, 36),
                             ("10/15", 18, 46), ("16/15", 19, 58),
                             ("16/15", 20, 55)]]
    bad = []
    got = R.office_tally(posts, day, "Verizon")
    if not got or got[0] != 16:
        bad.append(f"office_tally(Verizon): got {got}, want 16")
    if any(p.campaign for p in posts):
        bad.append("a tally post was read as a sale")
    if P.tally(posts, day, "Verizon"):
        bad.append("a tally post counted toward a rep")
    if (R.office_tally(posts, day, "B2B")[0] != 14
            or R.office_tally(posts, day, "BOX")[0] != 12):
        bad.append("the B2B / BOX office tally changed")
    return bad


def test_image_only_post_is_noted():
    """A board rep's post with a picture and no words (Edgar Camunez, Verizon
    2026-10-07 18:32 — he forgot to type the post) counts nothing, writes
    nothing, and is said out loud under that rep's campaign; the board keeps
    the manager's number."""
    from automations.vantura_slack_sales import run as R

    g = [[""] * 12 for _ in range(7)]
    g[3][1], g[3][4] = "REP", "Wednesday"          # 2026-07-22 is a Wednesday
    g[4][1], g[4][4], g[4][11] = "Edgar Camunez", "2", "Verizon"
    g[5][1], g[5][4], g[5][11] = "Will Bautista", "", "Verizon"
    g[6][1] = "Verizon"                            # the subtotal label
    posts = [_post("", hh=18, mm=32, author="Edgar Camunez", files=1),
             _post("*D2D Verizon* \nWrap up text \n\nNL #1", hh=18, mm=23,
                   author="William Bautista")]
    lines = []
    res = R.run_campaign(posts, g, dt.date(2026, 7, 22), "Verizon",
                         log=lines.append)
    bad = []
    if not any("no text/count from Edgar Camunez" in ln and "18:32" in ln
               for ln in lines):
        bad.append(f"image-only post not noted: {lines}")
    if ("edgar camunez" in res["matched"]
            or any(a == "Edgar Camunez" for a, _ in res["unmatched"])):
        bad.append("an image-only post was counted")
    plan = R.fill_plan(g, res)
    if plan != [("Will Bautista", "E6", "(blank)", "1", "")]:
        bad.append(f"fill plan: got {plan}")
    return bad


def test_verizon_names_reach_the_board():
    """The Verizon crew's Slack names land on their board rows — through
    KNOWN_USERS' spelling today, or NAME_ALIASES once users.info works — and
    a poster who is not on the board (Alexis Alejo) matches nothing."""
    from automations.vantura_slack_sales import run as R
    rows = {R._norm(n): i for i, n in enumerate([
        "Will Bautista", "Diego Chacon", "Yariel Martin Caban",
        "Gary Van Whitaker", "Giovanni Monreal", "Luis Valenciano",
        "Thais Alvarez Aragon", "Kyara Nayibe Mancilla Hurtado",
        "Gavin Dimitri Natividad", "Jayden Willingham", "Edgar Camunez"], 5)}
    bad = []
    for slack_name, board_name in [
            ("William Bautista", "Will Bautista"),
            ("Yariel caban", "Yariel Martin Caban"),
            ("Gary Vanwhitaker", "Gary Van Whitaker"),
            ("Luis Adan Valenciano", "Luis Valenciano"),
            ("Thais", "Thais Alvarez Aragon"),
            ("Kyara", "Kyara Nayibe Mancilla Hurtado"),
            ("gavin natividaf", "Gavin Dimitri Natividad"),
            ("Jayden Luna", "Jayden Willingham"),
            ("Edgar Camunez", "Edgar Camunez"),    # the Base alias is retired
            ("Diego Chacon", "Diego Chacon")]:
        got = R.match_rep(slack_name, rows)
        if got != R._norm(board_name):
            bad.append(f"{slack_name!r} -> {got!r}, want {board_name!r}")
    if R.match_rep("Alexis Alejo", rows) is not None:
        bad.append("Alexis Alejo (not on the board) must not match a row")
    for uid, name in [("U0A6XE8S36E", "Diego Chacon"),
                      ("U0C2KSMN7Q8", "Yariel Martin Caban"),
                      ("U0BAYDXHXB7", "Thais Alvarez Aragon"),
                      ("U0C6YL2U9UH", "Alexis Alejo")]:
        if R.KNOWN_USERS.get(uid) != name:
            bad.append(f"KNOWN_USERS[{uid}] = {R.KNOWN_USERS.get(uid)!r}, "
                       f"want {name!r}")
    return bad


def test_campaigns_dont_poach():
    """Both campaigns quote kWh and/or CX — none may claim another's
    post."""
    bad = []
    box = _post("B2B :package::zap:\nBill Submitted\n\nBF 1\n36 month term\n"
                "45,000KWH\nCX 1\nBox #1")
    if box.campaign != "BOX":
        bad.append(f"BOX post read as {box.campaign}")
    att = _post("B2B (Business)\nWrap Text sent\nAuto Pay on\n\nCx 1\nNL 1")
    if att.campaign != "B2B":
        bad.append(f"AT&T post read as {att.campaign}")
    return bad


def test_day_rollover():
    """Late-night posts stay on their own day; 'YESTERDAY' moves one back."""
    bad = []
    late = _post("B2B :package:\n\nBF 1\n1000 kwh\n\nBox 1", hh=22, day=22)
    if late.sales_day != dt.date(2026, 7, 22):
        bad.append(f"22:00 post landed on {late.sales_day}")
    early = _post("B2B :package:\n\nBF 1\n1000 kwh\n\nBox 1", hh=2, day=23)
    if early.sales_day != dt.date(2026, 7, 22):
        bad.append(f"02:00 post landed on {early.sales_day}")
    tagged = _post("B2B :package::zap:\nYESTERDAY\n\nBill Submitted\nBF 1\n"
                   "36 month term\n32,568KWH\nCX 1\nBox #1", hh=8, day=23)
    if tagged.sales_day != dt.date(2026, 7, 22):
        bad.append(f"YESTERDAY post landed on {tagged.sales_day}")
    return bad


def test_fill_only_raises():
    """The fill raises a number, never lowers one (Megan 2026-07-23): sales
    reach the board by routes that aren't the channel, and those stand."""
    from automations.vantura_slack_sales import run as R

    # Minimal grid: row 4 day headers, row 5 a BOX rep, row 6 the totals
    # anchor so campaign_rows() stops there.
    def grid(cell_value):
        g = [[""] * 12 for _ in range(6)]
        g[3][1], g[3][4] = "REP", "Monday"
        g[4][1], g[4][4], g[4][11] = "Some Rep", cell_value, "BOX"
        g[5][1] = R.TOTALS_TOP
        return g

    bad = []
    for on_board, count, want in [("2", 5, [("2", "5")]),   # higher -> raise
                                  ("5", 2, []),             # lower  -> keep
                                  ("5", 5, []),             # equal  -> no-op
                                  ("", 3, [("(blank)", "3")]),
                                  ("0", 3, [("0", "3")]),
                                  ("X", 1, [("X", "1")])]:  # marker -> replace
        g = grid(on_board)
        res = {"col": 5, "rows": {"some rep": 5},
               "matched": {"some rep": {"count": count, "posts": [],
                                        "flags": []}}}
        got = [(p[2], p[3]) for p in R.fill_plan(g, res)]
        if got != want:
            bad.append(f"fill_plan board={on_board!r} count={count}: "
                       f"got {got}, want {want}")
    return bad


def test_week_guard():
    """The board shows one week at a time. Writing while the gold WE cell is on
    another week would land today's sales on last week's column.

    Monday is the case that matters: the 5:00am pass is closing out SUNDAY and
    the board is still correct, but by the 4:00pm pass the target is Monday
    itself and the board must have rolled.
    """
    from automations.vantura_slack_sales import run as R

    def board(we):
        g = [[""] * 3 for _ in range(2)]
        g[1][1] = we                      # B2, the gold WE cell
        return g

    bad = []
    for we, day, want_ok, label in [
        ("7.26", dt.date(2026, 7, 23), True,  "Thu, board on that week"),
        ("7.26", dt.date(2026, 7, 26), True,  "Mon 5am closing Sunday 7/26"),
        ("7.26", dt.date(2026, 7, 27), False, "Mon 4pm, board not rolled yet"),
        ("8.2",  dt.date(2026, 7, 27), True,  "Mon 4pm after the roll"),
        ("8.2",  dt.date(2026, 7, 26), False, "old Sunday once rolled away"),
    ]:
        ok = R.week_ok(board(we), day)[0]
        if ok != want_ok:
            bad.append(f"week guard ({label}): WE={we} day={day} "
                       f"got ok={ok}, want {want_ok}")
    return bad


def test_sara_overwrite():
    """Sara finalize: overwrite matched reps up OR down; leave unmatched (Megan
    2026-07-26)."""
    from automations.vantura_slack_sales import sara as S, run as R

    def grid(cells):  # {rowname: (b2b_value)}
        g = [[""] * 12 for _ in range(4 + len(cells) + 1)]
        g[3][1], g[3][4], g[3][11] = "REP", "Monday", "Campaign"
        for i, (name, val) in enumerate(cells.items()):
            r = 4 + i
            # the AT&T rows say "NDS" since 2026-10-03; a leftover "B2B" row
            # is the same campaign (vantura_boards.canon_campaign)
            g[r][1], g[r][4], g[r][11] = name, val, "B2B" if i == 2 else "NDS"
        g[4 + len(cells)][1] = R.TOTALS_TOP
        return g

    g = grid({"Jacob Ortega": "7", "Nick Smedra": "2", "Diego Borres": "3"})
    rows = R.campaign_rows(g, "B2B")
    bad = []
    if set(rows) != {"jacob ortega", "nick smedra", "diego borres"}:
        bad.append(f"campaign_rows('B2B') must find the NDS rows and the "
                   f"legacy B2B row alike: {sorted(rows)}")
    if R.campaign_rows(g, "NDS") != rows:
        bad.append("campaign_rows('NDS') and ('B2B') must agree")
    # Sara: Jacob down 7->5, Nick up 2->4, Diego absent (left), extra rep unknown
    writes, flags = S.plan_overwrite(g, 5, rows,
                                     {"Jacob Ortega": 5, "Nick Smedra": 4,
                                      "Ghost Rep": 2})
    got = {w[0]: w[3] for w in writes}
    if got != {"Jacob Ortega": 5, "Nick Smedra": 4}:
        bad.append(f"writes wrong: {got}")
    if not any("Diego Borres" in f and "LEFT" in f for f in flags):
        bad.append("Diego (absent from Sara) should be left+flagged")
    if not any("Ghost Rep" in f for f in flags):
        bad.append("Ghost Rep (not on board) should be flagged")
    return bad


def main() -> int:
    checks = [test_cases, test_running_counter, test_units_sum, test_week_guard,
              test_campaigns_dont_poach, test_day_rollover,
              test_fill_only_raises, test_sara_overwrite,
              test_verizon_units_sum, test_verizon_office_tally,
              test_image_only_post_is_noted, test_verizon_names_reach_the_board]
    bad = [b for chk in checks for b in chk()]
    for b in bad:
        print("FAIL", b)
    total = len(CASES) + 25 + 23          # + the 23 Verizon checks (2026-10-08)
    print(f"{total - len(bad)}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
