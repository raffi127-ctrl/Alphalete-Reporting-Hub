"""Reading View Progress from getStatus instead of from the rendered table.

python -m pytest automations/obcl_ov_sweep/test_ov_json.py
"""
from __future__ import annotations

import pytest

from automations.obcl_ov_sweep import ov_json as J
from automations.obcl_ov_sweep import ov_table as T

# Two columns' worth of the real served markup, entities and all.
PAGE = """
<table id="table-setup-status"><thead><tr>
  <th>Name</th><th>Contact</th><th>Upload Documents</th>
  <th>AT&amp;T UID Request</th><th>Owner Submit</th>
</tr></thead></table>
<script>
  columns: [
    {data: 'full_name_att_link'}, {data: 'pinfo_email_phone'},
    {data: 'type_155'}, {data: 'type_965'}, {data: 'type_156'}
  ]
</script>
"""


class TestHeaders:
    def test_entities_are_decoded(self):
        """"AT&amp;T" has to come back as "AT&T" or header_index misses it,
        and done_columns then answers None for every column -- which the
        caller reads as "this person's row was not visible"."""
        assert J.headers(PAGE)[3] == "AT&T UID Request"

    def test_the_order_is_the_table_s(self):
        assert J.headers(PAGE)[0] == "Name"
        assert J.headers(PAGE)[-1] == "Owner Submit"

    def test_a_decoded_header_is_findable(self):
        heads = J.headers(PAGE)
        assert T.header_index(heads, "at&t uid request") == 3
        assert T.header_index(heads, "owner submit") == 4

    def test_no_thead_is_no_headers(self):
        assert J.headers("<table></table>") == []


class TestColumnKeys:
    def test_they_come_back_in_column_order(self):
        assert J.column_keys(PAGE) == [
            "full_name_att_link", "pinfo_email_phone",
            "type_155", "type_965", "type_156"]

    def test_the_step_ids_are_not_sorted_or_contiguous(self):
        """Why the order is read and never computed: 965 sits between 155 and
        156 in the TABLE, and the ids differ per programme."""
        keys = [k for k in J.column_keys(PAGE) if k.startswith("type_")]
        nums = [int(k.split("_")[1]) for k in keys]
        assert nums != sorted(nums)


class TestCells:
    def test_a_cell_carries_the_html_untouched(self):
        rec = {"type_155": '<div class="label label-success">x</div>'}
        cells = J.cells_for(rec, ["type_155"], 1)
        assert cells[0]["html"] == rec["type_155"]

    def test_the_text_is_the_pill_s_words(self):
        rec = {"type_156": '<div class="label label-success">'
                           ' <i class="fa fa-check"></i> Approved </div>'}
        assert J.cells_for(rec, ["type_156"], 1)[0]["text"] == "Approved"

    def test_a_missing_field_is_an_empty_cell_not_a_gap(self):
        """The judging walks by index, so the row has to be table-width."""
        cells = J.cells_for({}, ["a", "b", "c"], 3)
        assert len(cells) == 3
        assert all(c == {"text": "", "html": ""} for c in cells)

    def test_a_null_is_not_the_string_None(self):
        assert J.cells_for({"a": None}, ["a"], 1)[0]["text"] == ""

    def test_the_row_is_padded_when_the_keys_run_short(self):
        assert len(J.cells_for({"a": "x"}, ["a"], 4)) == 4

    def test_a_real_pill_still_reads_as_done(self):
        """The states are judged by the same functions as before, so a
        success pill out of the JSON has to satisfy them.

        The pill is copied from a live record: the date is part of it, and
        cell_done requires one -- a tick with no date is not a completion.
        """
        pill = ('<div class="m-t-2 m-b-2 text-center"> <div class="label '
                'label-success"><i class="fa fa-check"></i> </div> '
                '<div class="date-font-12"> 11/16/26<br>11:00 AM </div> </div>')
        c = J.cells_for({"type_148": pill}, ["type_148"], 1)[0]
        assert c["text"] == "11/16/26 11:00 AM"
        assert T.cell_done(c["text"], c["html"])

    def test_a_tick_with_no_date_is_still_not_done(self):
        """Tag-stripping must not invent a completion where the scrape saw
        none: cell_done keys on the date, not on the checkmark."""
        pill = ('<div class="label label-success">'
                '<i class="fa fa-check"></i> </div>')
        c = J.cells_for({"type_148": pill}, ["type_148"], 1)[0]
        assert not T.cell_done(c["text"], c["html"])

    def test_an_empty_cell_is_not_done(self):
        c = J.cells_for({"type_148": ""}, ["type_148"], 1)[0]
        assert not T.cell_done(c["text"], c["html"])


class TestRepName:
    def test_it_is_the_name_fields_not_the_name_cell(self):
        """The NAME cell is a block of markup holding the person's id, an Edit
        link and the Action menu -- no use as a key."""
        assert J.rep_name({"fname": "Ricardo", "lname": "Doleo"}) == \
            "Ricardo Doleo"

    def test_a_half_filled_record_does_not_grow_a_space(self):
        assert J.rep_name({"fname": "Cher", "lname": ""}) == "Cher"
        assert J.rep_name({}) == ""


class _Page:
    def __init__(self, body, status=200, opts=None):
        self._body, self._status = body, status
        self._opts = opts if opts is not None else [["19", "RES-AT&T"]]

    def evaluate(self, js, arg=None):
        if "select[name='bid']" in js:
            return self._opts
        return {"status": self._status, "body": self._body}


class TestFetch:
    def test_the_records_come_out_of_the_data_key(self):
        page = _Page('{"data": [{"fname": "A", "lname": "B"}]}')
        assert J.fetch_records(page, "tok", 19) == [{"fname": "A", "lname": "B"}]

    def test_a_sign_in_page_is_not_an_empty_roster(self):
        """HTML with HTTP 200 is how this endpoint says "signed out". Reading
        it as zero records would blank every box on the board."""
        with pytest.raises(RuntimeError, match="did not answer JSON"):
            J.fetch_records(_Page("<html>sign in</html>"), "tok", 19)

    def test_a_non_200_is_raised_not_swallowed(self):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            J.fetch_records(_Page("{}", status=500), "tok", 19)

    def test_json_without_a_record_list_is_refused(self):
        with pytest.raises(RuntimeError, match="no record list"):
            J.fetch_records(_Page('{"error": "nope"}'), "tok", 19)


class TestBidLookup:
    def test_the_label_picks_the_id(self):
        assert J.bid_for(_Page("{}"), "RES-AT&T") == "19"

    def test_case_and_padding_do_not_matter(self):
        assert J.bid_for(_Page("{}"), " res-at&t ") == "19"

    def test_a_programme_the_login_lacks_says_what_it_has(self):
        page = _Page("{}", opts=[["242", "Water - Primo"]])
        with pytest.raises(RuntimeError, match="Water - Primo"):
            J.bid_for(page, "RES-AT&T")


class TestRead:
    """The guard that matters: never map columns by position unless the two
    lists agree on how many there are."""

    def test_a_header_count_mismatch_is_refused(self):
        page = _Page('{"data": []}')
        bad = PAGE.replace("{data: 'type_156'}", "")
        with pytest.raises(RuntimeError, match="refusing to map"):
            J.read(page, bid=19, page_html=bad, verbose=False)

    def test_no_columns_array_is_refused(self):
        page = _Page('{"data": []}')
        with pytest.raises(RuntimeError, match="columns array"):
            J.read(page, bid=19,
                   page_html="<table><thead><tr><th>Name</th></tr></thead>",
                   verbose=False)
