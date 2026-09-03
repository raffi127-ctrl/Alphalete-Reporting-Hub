"""The two B2B disposition shapes, against the headers OwnerVille really served.

LIVE_2 and LIVE_16 are verbatim from `gap_alerts.run --probe-campaigns
--campaign {2,16}` on 2026-09-02, kept in
output/probes/b2b-disposition-headers-campaign{2,16}-2026-09-02.log. They are
the fixture on purpose: a constant with a typo in it is invisible to a test that
invents its own headers, and the tolerant scrape would zero-fill the column
rather than complain.

WHY B2B NEEDS SHAPES OF ITS OWN. Both grids carry Total Knocks and no house
Talk-To split, so `_is_wireless_dispo` claims either one, and the wireless
scrape only REQUIRES ID / Rep / Total Knocks — everything else is zero-filled.
A B2B office therefore rendered a clean, plausible board with 0 under every
disposition. The English is near-identical and the strings are not: AT&T's grid
says "Talked To - Not Interested" where fiber says "Talk To - Not Interested".
"""
from automations.rashad_metrics import knocks_pull as K
from automations.total_knocks import pull as knocks
from automations.total_knocks import render as R

LIVE_2 = ("battery, come back, corp franchise local, corp franchise no opp, "
          "coverage, device, do not knock, first knock, id, inaccurate lead, "
          "last knock, none, presentation not interested, rep, sale, "
          "talked to not interested, territory name, tm version, total hours, "
          "total knocks, total leads knocked, total scheduled").split(", ")
LIVE_16 = ("am come back, battery, bill collected no sale, come back, "
           "contract signed, corp no opp, coverage, device, do not disturb, "
           "first knock, id, inaccessible, inaccurate lead, last knock, "
           "not interested, owner talked to, rep, talked to, territory name, "
           "tm version, total hours, total knocks, total leads knocked, "
           "total scheduled").split(", ")


def _idx(headers):
    return {h: i for i, h in enumerate(headers)}


def _other(headers):
    return _idx([knocks._norm(c) for c in headers])


ATT, BOX = _idx(LIVE_2), _idx(LIVE_16)
WIRELESS = _other(["ID", "Rep", "Total Knocks", "No answer", "Not Interested",
                   "Come Back", "Inaccessible", "Do Not Knock"])
ENERGYWELL = _other(["ID", "Rep", "Total Knocks", "VL", "Presentation",
                     "Not Interested"])
HOUSE = _other(["ID", "Rep", "Total Knocks", "Talk To - Not Interested",
                "Sale", "No answer"])


# --- every constant is a column that really exists --------------------------

def test_every_att_column_is_on_the_live_grid():
    missing = [c for c in K._B2B_ATT_COLUMNS
               if knocks._norm(c) not in LIVE_2]
    assert missing == []


def test_every_box_column_is_on_the_live_grid():
    missing = [c for c in K._B2B_BOX_COLUMNS
               if knocks._norm(c) not in LIVE_16]
    assert missing == []


def test_the_two_campaigns_really_are_different_vocabularies():
    """If they were the same, one shape would do. They share the spine, Come
    Back and Inaccurate Lead — and nothing else."""
    shared = set(K._B2B_ATT_COLUMNS) & set(K._B2B_BOX_COLUMNS)
    assert shared == {knocks.COL_ID, knocks.COL_REP,
                      knocks.COL_TOTAL_LEADS_KNOCKED, knocks.COL_TOTAL_KNOCKS,
                      knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
                      knocks.COL_COME_BACK, knocks.COL_B2B_INACCURATE_LEAD}


def test_neither_grid_has_a_no_answer_bucket():
    """Which is why the house scrape raised on both."""
    assert knocks._norm(knocks.COL_NO_ANSWER) not in LIVE_2
    assert knocks._norm(knocks.COL_NO_ANSWER) not in LIVE_16


# --- detection ---------------------------------------------------------------

def test_each_grid_is_detected_as_its_own_campaign():
    assert K._is_b2b_att_dispo(ATT) and not K._is_b2b_box_dispo(ATT)
    assert K._is_b2b_box_dispo(BOX) and not K._is_b2b_att_dispo(BOX)


def test_the_wireless_test_would_have_claimed_both():
    """The whole reason B2B has to be checked FIRST."""
    assert K._is_wireless_dispo(ATT) and K._is_wireless_dispo(BOX)


def test_no_other_campaign_is_mistaken_for_b2b():
    for idx in (WIRELESS, ENERGYWELL, HOUSE):
        assert not K.is_b2b_dispo(idx)


def test_the_two_corp_columns_are_spelled_differently():
    """AT&T says "Corp Franchise No Opp", Box says "Corp - No Opp". A single
    signature keyed on one of them catches half of B2B — which is exactly what
    the first version of this shipped as."""
    assert knocks._norm(knocks.COL_B2B_CORP_NO_OPP) in LIVE_2
    assert knocks._norm(knocks.COL_B2B_CORP_NO_OPP) not in LIVE_16
    assert knocks._norm(knocks.COL_BOX_CORP_NO_OPP) in LIVE_16
    assert knocks._norm(knocks.COL_BOX_CORP_NO_OPP) not in LIVE_2


# --- talk-to -----------------------------------------------------------------

def test_talk_to_excludes_only_the_buckets_nobody_was_spoken_to_in():
    att_out = set(K._B2B_ATT_COLUMNS) - set(K._B2B_ATT_TALK_TO_PARTS)
    assert knocks.COL_B2B_NONE in att_out
    assert knocks.COL_B2B_INACCURATE_LEAD in att_out
    box_out = set(K._B2B_BOX_COLUMNS) - set(K._B2B_BOX_TALK_TO_PARTS)
    assert knocks.COL_INACCESSIBLE in box_out
    assert knocks.COL_B2B_INACCURATE_LEAD in box_out


def test_box_keeps_its_three_talk_to_columns_separate():
    """Megan 2026-09-02, asked whether summing them double-counts: "they should
    be each their own column." So they are three distinct dispositions — each
    gets its own column on the board, and each counts once toward Total Talk to.
    Collapsing any two of them would lose a bucket Carlos's office reads."""
    three = [knocks.COL_BOX_TALKED_TO, knocks.COL_BOX_OWNER_TALKED_TO,
             knocks.COL_NOT_INTERESTED]
    for col in three:
        assert col in K._B2B_BOX_COLUMNS          # scraped
        assert col in K._B2B_BOX_TALK_TO_PARTS    # counted, once each
        assert col in R.B2B_BOX_KNOCKS_COLUMNS    # and shown on the board
    assert len(set(three)) == 3


def test_do_not_knock_and_do_not_disturb_both_count_as_talk_tos():
    """The house rule counts Do Not Knock; Box's Do Not Disturb is the same
    thing said in B2B."""
    assert knocks.COL_DO_NOT_KNOCK in K._B2B_ATT_TALK_TO_PARTS
    assert knocks.COL_BOX_DO_NOT_DISTURB in K._B2B_BOX_TALK_TO_PARTS


def test_talk_to_parts_are_columns_the_scrape_actually_produces():
    """A part that isn't scraped sums as a silent zero."""
    for parts, cols in ((K._B2B_ATT_TALK_TO_PARTS, K._B2B_ATT_COLUMNS),
                        (K._B2B_BOX_TALK_TO_PARTS, K._B2B_BOX_COLUMNS)):
        assert set(parts) <= set(cols)


def test_the_spine_is_never_summed_into_a_talk_to():
    for parts in (K._B2B_ATT_TALK_TO_PARTS, K._B2B_BOX_TALK_TO_PARTS):
        assert knocks.COL_TOTAL_KNOCKS not in parts
        assert knocks.COL_TOTAL_LEADS_KNOCKED not in parts


# --- the board ---------------------------------------------------------------

def _row(extra):
    base = {knocks.COL_TOTAL_KNOCKS: 40, knocks.COL_REP: "A Rep"}
    base.update(extra)
    return base


def test_rows_route_to_their_own_board():
    assert R.knocks_shape([_row({knocks.COL_B2B_CORP_NO_OPP: 1})]) \
        == R.SHAPE_B2B_ATT
    assert R.knocks_shape([_row({knocks.COL_BOX_OWNER_TALKED_TO: 1})]) \
        == R.SHAPE_B2B_BOX


def test_a_b2b_office_gets_one_board_not_a_pair():
    """Gaps + Total Gaps are in both column lists, so needs_time_gaps retires
    the separate Time Gaps post — the merge Megan asked for on every board."""
    assert not R.needs_time_gaps(R.SHAPE_B2B_ATT)
    assert not R.needs_time_gaps(R.SHAPE_B2B_BOX)


def test_every_board_column_is_one_the_scrape_or_the_merge_supplies():
    """Otherwise the board draws a column that is blank for everyone."""
    from automations.total_knocks.pull import COL_GAPS, COL_TOTAL_GAPS
    for board, scraped in ((R.B2B_ATT_KNOCKS_COLUMNS, K._B2B_ATT_COLUMNS),
                           (R.B2B_BOX_KNOCKS_COLUMNS, K._B2B_BOX_COLUMNS)):
        supplied = (set(scraped) | {knocks.COL_TOTAL_TALK_TO,
                                    COL_GAPS, COL_TOTAL_GAPS})
        assert set(board) <= supplied


def test_the_board_drops_the_rep_id_like_every_other_shape():
    assert knocks.COL_ID not in R.B2B_ATT_KNOCKS_COLUMNS
    assert knocks.COL_ID not in R.B2B_BOX_KNOCKS_COLUMNS


# --- the collision that draws a column blank ---------------------------------

def test_no_board_column_normalizes_onto_another():
    """A whole CLASS of silent-blank bug, not one instance.

    render._records_to_table seeds its header with SHEET_COLUMNS (fiber's set)
    and appends any extra key the records carry; the header is then indexed by
    NORMALIZED name, first-wins. So two columns that are different strings but
    normalize the same collapse onto one position — and the second one draws
    blank for every rep with 0 in the totals, which reads exactly like a bucket
    nobody used.

    That is how B2B AT&T's "Presentation - Not Interested" (hyphen) vanished
    behind the house "Presentation – Not Interested" (en-dash) on 2026-09-02.
    """
    from automations.total_knocks.pull import SHEET_COLUMNS
    for name, cols in (("b2b_att", R.B2B_ATT_KNOCKS_COLUMNS),
                       ("b2b_box", R.B2B_BOX_KNOCKS_COLUMNS),
                       ("energywell", R.ENERGYWELL_KNOCKS_COLUMNS),
                       ("wireless", R.WIRELESS_KNOCKS_COLUMNS)):
        seen = {}
        for col in list(SHEET_COLUMNS) + list(cols):
            key = knocks._norm(col)
            if key in seen and seen[key] != col:
                raise AssertionError(
                    "%s: %r and %r both normalize to %r — the second draws "
                    "blank for every rep" % (name, seen[key], col, key))
            seen[key] = col


def test_b2b_att_uses_the_house_presentation_column():
    """One constant for one column. The scrape resolves by normalized name, so
    the house spelling matches B2B's live header on its own."""
    assert knocks.COL_PRES_NI in K._B2B_ATT_COLUMNS
    assert knocks.COL_PRES_NI in K._B2B_ATT_TALK_TO_PARTS
    assert knocks._norm(knocks.COL_PRES_NI) in LIVE_2
    assert not hasattr(knocks, "COL_B2B_PRES_NI")


def test_talked_to_not_interested_does_NOT_collide():
    """It must stay its own constant: _is_wireless_dispo keys on the HOUSE
    "Talk To - Not Interested" being absent, which is what tells a B2B grid
    apart in the first place."""
    assert (knocks._norm(knocks.COL_B2B_TALKED_TO_NI)
            != knocks._norm(knocks.COL_TALK_TO_NI))
    assert knocks._norm(knocks.COL_TALK_TO_NI) not in LIVE_2


# --- the pin that did not take (2026-09-02) ---------------------------------

def test_a_pinned_campaign_must_produce_its_own_grid():
    """Impersonating Carlos Hidalgo and pinning invD2DClientId=16 returned the
    22-header B2B AT&T grid, not Box's 24-header one — in a FRESH session, grid
    warmed first, and the same pin on the master account DID serve Box. So the
    campaign can silently stay where it was under impersonation.

    Unchecked, that is a board titled "B2B Box" carrying AT&T's reps and AT&T's
    numbers, which nobody reading it can tell is wrong."""
    import pytest
    from automations.total_knocks.pull import KnocksPullFailed
    with pytest.raises(KnocksPullFailed) as e:
        K.assert_campaign_grid(ATT, "16")
    assert "did not take" in str(e.value)
    with pytest.raises(KnocksPullFailed):
        K.assert_campaign_grid(BOX, "2")


def test_the_matching_grid_passes():
    K.assert_campaign_grid(ATT, "2")
    K.assert_campaign_grid(BOX, "16")


def test_it_refuses_only_what_it_can_prove_wrong():
    """No pin, or a campaign whose grid has no signature we recognise, is not
    checked — never guessed at.

    "40" LEFT THIS LIST ON 2026-09-02. Energy Wells does have a signature we
    recognise — the VL column — and leaving it unchecked is what let Calvin's
    B2B-Box-shaped grid publish to his chat as ENERGYWELL. "3" stays: it is
    KNOCKS_CAMPAIGN_ID, the default for every un-overridden office, and a
    wireless office renders a wireless grid under it legitimately."""
    for campaign in (None, "", "3", "39"):
        K.assert_campaign_grid(ATT, campaign)
        K.assert_campaign_grid(HOUSE, campaign)


def test_a_non_b2b_grid_under_a_b2b_pin_is_also_refused():
    import pytest
    from automations.total_knocks.pull import KnocksPullFailed
    with pytest.raises(KnocksPullFailed) as e:
        K.assert_campaign_grid(HOUSE, "2")
    assert "not a B2B grid at all" in str(e.value)


# --- Energy Wells joined the table 2026-09-02 ---------------------------------

def test_energywell_pin_refuses_a_box_grid():
    """The live failure: Calvin is pinned to 40 and his 2:55 PM board came
    back B2B Box-shaped, then went to ENERGY WELLS DOMINATION titled
    "ENERGYWELL — CALVIN" with eight reps. It published because this map knew
    only the two B2B ids."""
    import pytest
    box = {K.knocks._norm(c): i for i, c in enumerate(K._B2B_BOX_COLUMNS)}
    with pytest.raises(K.KnocksPullFailed) as e:
        K.assert_campaign_grid(box, "40")
    assert "RES-ENERGYWELL" in str(e.value)
    assert "did not take" in str(e.value)


def test_energywell_pin_accepts_an_energywell_grid():
    ew = {K.knocks._norm(c): i for i, c in enumerate(K._ENERGYWELL_COLUMNS)}
    K.assert_campaign_grid(ew, "40")          # must not raise


def test_res_att_stays_out_of_the_table():
    """3 is KNOCKS_CAMPAIGN_ID — the default every un-overridden office gets,
    including wireless offices whose grid is legitimately wireless-shaped.
    An entry for it would refuse all of them."""
    assert "3" not in K.CAMPAIGN_EXPECTED_SHAPE
    wireless = {K.knocks._norm(c): i for i, c in enumerate(K._WIRELESS_COLUMNS)}
    K.assert_campaign_grid(wireless, "3")     # must not raise
