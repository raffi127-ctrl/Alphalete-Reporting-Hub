"""A B2B Disposition grid must RAISE, not render a board of zeros.

The B2B column set has never been mapped. What makes that dangerous rather than
merely missing is that a B2B grid satisfies `_is_wireless_dispo` — it carries
Total Knocks and no house Talk-To split — and the wireless scrape is tolerant by
design (only ID / Rep / Total Knocks are required, every other bucket is
zero-filled). So without this guard a B2B office renders a clean, plausible
wireless board with 0 in every disposition column.
"""
import pytest

from automations.rashad_metrics import knocks_pull as K
from automations.total_knocks import pull as knocks
from automations.total_knocks.pull import KnocksPullFailed


def _idx(*headers):
    return {knocks._norm(h): i for i, h in enumerate(headers)}


B2B = _idx("ID", "Rep", "Total Leads Knocked", "Total Knocks", "First Knock",
           "Last Knock", "No answer", "Corp - No Opp", "Come Back")
WIRELESS = _idx("ID", "Rep", "Total Knocks", "No answer", "Not Interested",
                "Come Back", "Inaccessible", "Do Not Knock")
ENERGYWELL = _idx("ID", "Rep", "Total Knocks", "Not Interested",
                  "Presentation", "VL", "Come Back")
HOUSE = _idx("ID", "Rep", "Total Knocks", "Talk To - Not Interested", "Sale")


def test_a_b2b_grid_is_recognised():
    assert K._is_b2b_dispo(B2B)


def test_the_wireless_test_would_have_claimed_it():
    """The whole reason the B2B check has to run FIRST."""
    assert K._is_wireless_dispo(B2B)


def test_no_other_shape_is_mistaken_for_b2b():
    for idx in (WIRELESS, ENERGYWELL, HOUSE):
        assert not K._is_b2b_dispo(idx)


def test_refusing_says_how_to_map_it():
    with pytest.raises(KnocksPullFailed) as e:
        K._refuse_b2b(B2B)
    msg = str(e.value)
    assert "--probe-campaigns" in msg
    assert "--campaign 2" in msg          # and 16 for Box Energy
    assert "Corp - No Opp" in msg
