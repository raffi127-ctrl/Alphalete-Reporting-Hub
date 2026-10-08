"""The second B2B vocabulary (2026-10-08).

Overnight 10/7 -> 10/8 OwnerVille/TeleMapper replaced both B2B grids'
disposition sets. The headers below are what Roshan's, Carlos's and Eveliz's
machines relayed that morning, what Raf's classic session served for Roshan,
and what Megan saw on Carlos's own account (Column Visibility listing only
these). Three B2B knock boards were withheld by the guard until this landed.
"""
from automations.icd_alerts import campaign_guard as G
from automations.icd_alerts import knocks_map as M
from automations.rashad_metrics import knocks_pull as K
from automations.total_knocks import pull as knocks
from automations.total_knocks import render as R

LIVE_16_V2 = ("id, rep, first knock, last knock, talk to, come back, "
              "inaccessible, inaccurate, dnk, sale, presentation, close, "
              "total leads knocked, total knocks, total scheduled, coverage, "
              "device, tm version, battery, total hours, territory name"
              ).split(", ")
LIVE_2_V2 = ("id, rep, first knock, last knock, talk to, presentation, "
             "come back, client acquired, inaccurate, dnk, no contact, "
             "qualifying questions, close, sara plus, customer gave review, "
             "total leads knocked, total knocks, total scheduled, coverage, "
             "device, tm version, battery, total hours, territory name"
             ).split(", ")


def _idx(headers):
    return {h: i for i, h in enumerate(headers)}


BOX2, ATT2 = _idx(LIVE_16_V2), _idx(LIVE_2_V2)
HOUSE = _idx([knocks._norm(c) for c in (
    "ID", "Rep", "Total Knocks", "Talk To - Not Interested", "Sale",
    "No answer", "Inaccessible", "Do Not Knock", "Close", "Quick Quote")])


# --- every v2 constant is a column that really exists -------------------------

def test_every_v2_att_column_is_on_the_live_grid():
    assert [c for c in K._B2B_ATT_COLUMNS_V2 if knocks._norm(c) not in LIVE_2_V2] == []


def test_every_v2_box_column_is_on_the_live_grid():
    assert [c for c in K._B2B_BOX_COLUMNS_V2 if knocks._norm(c) not in LIVE_16_V2] == []


# --- detection -----------------------------------------------------------------

def test_each_v2_grid_is_detected_as_its_own_campaign():
    assert K._is_b2b_att_dispo(ATT2) and not K._is_b2b_box_dispo(ATT2)
    assert K._is_b2b_box_dispo(BOX2) and not K._is_b2b_att_dispo(BOX2)
    assert K.b2b_vocab(ATT2) == "v2" and K.b2b_vocab(BOX2) == "v2"


def test_the_house_grid_is_still_not_b2b():
    """It has Close and Inaccessible too; it says "Do Not Knock" and "Talk To
    - Not Interested", so neither DNK nor plain Talk To is there."""
    assert not K.is_b2b_dispo(HOUSE)


def test_v1_grids_still_read_as_v1():
    from automations.rashad_metrics.test_b2b_shapes import ATT, BOX
    assert K.b2b_vocab(ATT) == "v1" and K.b2b_vocab(BOX) == "v1"


def test_the_pin_check_accepts_the_new_grids():
    K.assert_campaign_grid(ATT2, "2")
    K.assert_campaign_grid(BOX2, "16")


# --- talk-to ------------------------------------------------------------------

def test_v2_talk_to_excludes_only_the_no_contact_buckets():
    att_out = set(K._B2B_ATT_COLUMNS_V2) - set(K._B2B_ATT_TALK_TO_PARTS_V2)
    assert knocks.COL_B2B_NO_CONTACT in att_out
    assert knocks.COL_B2B_INACCURATE in att_out
    box_out = set(K._B2B_BOX_COLUMNS_V2) - set(K._B2B_BOX_TALK_TO_PARTS_V2)
    assert knocks.COL_INACCESSIBLE in box_out
    assert knocks.COL_B2B_INACCURATE in box_out
    for parts, cols in ((K._B2B_ATT_TALK_TO_PARTS_V2, K._B2B_ATT_COLUMNS_V2),
                        (K._B2B_BOX_TALK_TO_PARTS_V2, K._B2B_BOX_COLUMNS_V2)):
        assert set(parts) <= set(cols)
        assert knocks.COL_TOTAL_KNOCKS not in parts


# --- the relay path (ICD machines) ---------------------------------------------

def _box_row(rep, rid, **kw):
    d = {"id": rid, "rep": rep, "first knock": "10:39 AM", "last knock": "11:25 AM",
         "talk to": "2", "come back": "3", "inaccessible": "1", "inaccurate": "1",
         "dnk": "", "sale": "1", "presentation": "", "close": "",
         "total leads knocked": "8", "total knocks": "8", "total scheduled": "206",
         "% coverage": "2%", "device": "iPhone18,2", "tm version": "3.68.48",
         "battery": "", "total hours": "", "territory name": ""}
    d.update(kw)
    return d


def test_relayed_v2_box_rows_route_to_the_box_board_with_talk_to_summed():
    rows = M.to_rows([_box_row("Emily Chavira", "9502160")])
    assert R.knocks_shape(rows) == R.SHAPE_B2B_BOX
    assert R.b2b_vocab(rows) == "v2"
    assert rows[0][knocks.COL_TOTAL_TALK_TO] == 2 + 3 + 1    # talk to + come back + sale


def test_relayed_v2_att_rows_route_to_the_att_board():
    raw = {"id": "1", "rep": "Aleen A", "first knock": "9:00 AM", "last knock": "9:30 AM",
           "talk to": "1", "presentation": "", "come back": "", "client acquired": "1",
           "inaccurate": "1", "dnk": "", "no contact": "2", "qualifying questions": "",
           "close": "", "sara plus": "", "customer gave review": "",
           "total leads knocked": "5", "total knocks": "5"}
    rows = M.to_rows([raw])
    assert R.knocks_shape(rows) == R.SHAPE_B2B_ATT
    assert rows[0][knocks.COL_TOTAL_TALK_TO] == 2        # talk to + client acquired


def test_the_guard_passes_the_new_grids_and_still_catches_a_swap():
    box_rows = [{"dnk": "", "talk to": "2", "inaccessible": "1", "sale": "1", "rep": "A"}]
    att_rows = [{"client acquired": "1", "talk to": "1", "dnk": "", "rep": "A"}]
    assert G.check("b2b_box", box_rows) is None
    assert G.check("b2b_att", att_rows) is None
    assert "B2B AT&T SBS-shaped" in G.check("b2b_box", att_rows)
    assert "B2B-BOX-Energy-shaped" in G.check("b2b_att", box_rows)


def test_the_guard_still_passes_the_old_grids():
    from automations.icd_alerts.test_campaign_guard import BOX, ATT
    assert G.check("b2b_box", BOX) is None
    assert G.check("b2b_att", ATT) is None


# --- the boards -----------------------------------------------------------------

def test_v2_board_columns_are_all_supplied():
    from automations.total_knocks.pull import COL_GAPS, COL_TOTAL_GAPS
    for board, scraped in ((R.B2B_ATT_KNOCKS_COLUMNS_V2, K._B2B_ATT_COLUMNS_V2),
                           (R.B2B_BOX_KNOCKS_COLUMNS_V2, K._B2B_BOX_COLUMNS_V2)):
        supplied = set(scraped) | {knocks.COL_TOTAL_TALK_TO, COL_GAPS, COL_TOTAL_GAPS}
        assert set(board) <= supplied
        assert knocks.COL_ID not in board


def test_v2_box_board_picks_the_v2_columns_and_v1_rows_keep_v1():
    v2 = M.to_rows([_box_row("A B", "1")])
    assert R.b2b_columns(R.SHAPE_B2B_BOX, v2) == (R.B2B_BOX_KNOCKS_COLUMNS_V2,
                                                 R.B2B_BOX_KNOCKS_HEADERS_V2)
    v1 = [{knocks.COL_BOX_OWNER_TALKED_TO: 1, knocks.COL_TOTAL_KNOCKS: 3, knocks.COL_REP: "A"}]
    assert R.b2b_columns(R.SHAPE_B2B_BOX, v1) == (R.B2B_BOX_KNOCKS_COLUMNS,
                                                 R.B2B_BOX_KNOCKS_HEADERS)


def test_actual_talk_tos_on_the_new_box_grid_subtracts_inaccessible_and_inaccurate():
    rows = M.to_rows([_box_row("A B", "1", **{"total knocks": "20", "inaccessible": "3",
                                             "inaccurate": "2"}),
                      _box_row("C D", "2", **{"total knocks": "10", "inaccessible": "0",
                                             "inaccurate": "1"})])
    header, table = R._table_from_rows(rows)
    sub = R._combined_sub(header, table, base_cols=R.B2B_BOX_KNOCKS_COLUMNS_V2,
                          out_cols=R.B2B_BOX_KNOCKS_HEADERS_V2)
    at = R.B2B_BOX_KNOCKS_HEADERS_V2.index(R.COL_BOX_ACTUAL_TALK_TO)
    rep_at = R.B2B_BOX_KNOCKS_HEADERS_V2.index(knocks.COL_REP)
    got = {r[rep_at]: r[at] for r in sub}
    assert got["A B"] == "15" and got["C D"] == "9"
    totals = R._combined_totals("OFFICE TOTAL", sub, R.B2B_BOX_KNOCKS_HEADERS_V2)
    assert totals[at] == "24"


def test_every_v2_box_column_is_in_ryans_order_list():
    """An unlisted column is appended at the far right, never dropped -- but
    the new buckets should sit where their v1 cousins did."""
    for c in R.B2B_BOX_KNOCKS_COLUMNS_V2:
        if c in (knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED, knocks.COL_TOTAL_KNOCKS,
                 knocks.COL_TOTAL_TALK_TO, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
                 knocks.COL_GAPS, knocks.COL_TOTAL_GAPS):
            continue
        assert c in R.BOX_BOARD_ORDER, c
