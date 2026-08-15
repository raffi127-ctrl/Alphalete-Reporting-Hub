"""Tests for the parts that decide who gets tagged. No network.

Every case here is a real row or a real name off the 8/9-8/13 2026 data, because
the ways this can be wrong are all specific: a rep typing their own name three
different ways, two neighbours on one street reading as one sale, two people
called Miguel Vargas.

    python -m automations.energy_crossref.test_crossref

(A plain runner, not pytest: pytest isn't installed in this repo's venv and the
sibling test_parse.py runs the same way.)
"""
from __future__ import annotations

import datetime as dt

from automations.energy_crossref import roster as R
from automations.energy_crossref import webform as W


def _sub(row, rep, customer="", phone="", address="", date="8/13/2026"):
    return W.Submission(row=row, rep=rep, manager="Rafael Hidalgo",
                        customer=customer, phone=phone, address=address,
                        sale_date=W.parse_date(date), timestamp="")


# ---------------------------------------------------------------- dates ---

def test_parse_date_formats():
    assert W.parse_date("8/13/2026") == dt.date(2026, 8, 13)
    assert W.parse_date("08/13/2026") == dt.date(2026, 8, 13)
    assert W.parse_date("8/13/26") == dt.date(2026, 8, 13)
    assert W.parse_date("2026-08-13") == dt.date(2026, 8, 13)


def test_parse_date_rejects_junk():
    assert W.parse_date("") is None
    assert W.parse_date("yesterday") is None
    assert W.parse_date("13/13/2026") is None       # no month 13


def test_the_day_is_the_sale_date_not_the_timestamp():
    """Half of 8/13's submissions were for sales made days earlier."""
    rows = [_sub(1, "Edgar Camunez", date="8/11/2026"),
            _sub(2, "Edgar Camunez", date="7/29/2026"),
            _sub(3, "Ivan soto", date="8/13/2026")]
    by_rep, _w = W.for_day(rows, dt.date(2026, 8, 13))
    assert list(by_rep) == ["ivan soto"]


# ----------------------------------------------------------- duplicates ---

def test_same_phone_is_one_sale():
    """Zoria on 8/10: the same customer filed twice, same number."""
    rows = [_sub(552, "Zoria Johnson", "Jane Doe", "(781) 817-9550"),
            _sub(553, "Zoria Johnson", "jane doe!", "781-817-9550")]
    by_rep, _w = W.for_day(rows, dt.date(2026, 8, 13))
    rf = by_rep["zoria johnson"]
    assert rf.count == 1 and len(rf.dupes) == 1


def test_same_customer_name_is_one_sale_even_without_a_phone():
    rows = [_sub(1, "Willvim Marte", "HAILEE GROVER", ""),
            _sub(2, "Willvim Marte", "hailee grover", "")]
    by_rep, _w = W.for_day(rows, dt.date(2026, 8, 13))
    assert by_rep["willvim marte"].count == 1


def test_neighbours_on_one_street_are_TWO_sales():
    """The 8/13 referral pair. Normalising the address without its digits made
    these one sale and would have shown Pranish a duplicate he never filed."""
    rows = [_sub(580, "Pranish Shrestha", "SATYA BALAGAM", "2108637460",
                 " 7732 LA HAYE DR, IRVING, TX 75063"),
            _sub(581, "Pranish Shrestha", "Raghavendra yerawar ", "2145191354",
                 "7747 la haye dr irving tx 75063")]
    by_rep, warn = W.for_day(rows, dt.date(2026, 8, 13))
    assert by_rep["pranish shrestha"].count == 2
    assert not warn


def test_one_address_two_customers_is_counted_but_warned():
    rows = [_sub(1, "Ivan soto", "A Person", "2145360848", "7208 NOTRE DAME DR"),
            _sub(2, "Ivan soto", "Someone Else", "2145360849", "7208 notre dame dr")]
    by_rep, warn = W.for_day(rows, dt.date(2026, 8, 13))
    assert by_rep["ivan soto"].count == 2          # counted...
    assert len(warn) == 1 and "7208" in warn[0]    # ...and flagged


def test_a_rep_spelling_their_own_name_differently_is_one_rep():
    rows = [_sub(1, "Ivan soto", "A", "1112223333"),
            _sub(2, "IVAN SOTO", "B", "4445556666")]
    by_rep, _w = W.for_day(rows, dt.date(2026, 8, 13))
    assert len(by_rep) == 1 and by_rep["ivan soto"].count == 2


# --------------------------------------------------------------- header ---

def test_header_cols_found_by_text_not_position():
    hdr = ["Timestamp", "Your first and last name", "Your Managers Name?",
           "Customers first, last name? ", "Customers Phone number",
           "Customers address? include numbers, street, city state and zip code",
           "Please Provide customers bill here. ",
           "Is the customer interested in the battery? ",
           "Any notes we should know about the cx? ", "Date of Sale"]
    cols = W.header_cols(hdr)
    assert cols["rep"] == 1 and cols["sale_date"] == 9 and cols["customer"] == 3


def test_header_cols_survives_a_new_question_inserted_in_the_middle():
    hdr = ["Timestamp", "Your first and last name", "NEW QUESTION",
           "Your Managers Name?", "Customers first, last name?",
           "Customers Phone number", "Customers address? include numbers",
           "Date of Sale"]
    cols = W.header_cols(hdr)
    assert cols["manager"] == 3 and cols["sale_date"] == 7


def test_header_cols_raises_when_a_question_is_renamed():
    try:
        W.header_cols(["Timestamp", "Your first and last name",
                       "Your Managers Name?", "Customers first, last name?",
                       "Customers Phone number", "Customers address? include",
                       "Sale Day"])
    except RuntimeError as e:
        assert "sale_date" in str(e)
    else:
        raise AssertionError("a renamed 'Date of Sale' has to raise, not guess")


# --------------------------------------------------------------- roster ---

def test_the_five_evelyn_tagged_on_8_13():
    """Her post is the fixture: same people, same ids, same order."""
    names = ["Charley Alan Perez", "Edgar Camunez", "Zoria Johnson",
             "Rafael Hidalgo", "Dylan Twaddle"]
    assert [R._from_map(n) for n in names] == [
        "U0BD56X1H40", "U0A80F907N3", "U08LSELLCGY",
        "U045Z8N0ZQC", "U048V0YA5FC"]


def test_the_week_suffix_does_not_break_the_lookup():
    """'(Wk 2)' becomes '(Wk 3)' every Monday."""
    assert R._from_map("Ivan Soto (Wk 2)") == R._from_map("Ivan Soto (Wk 5)")
    assert R._from_map("Thomas Crenshaw (Wk 3)") == "U0AK05E6S11"


def test_the_parenthesised_english_name_is_kept():
    """'Qilu(Timothy) Zhao' — 'Timothy' only exists inside the parens."""
    assert R._from_map("Qilu(Timothy) Zhao (Wk 2)") == "U0BNJ9ZA4GG"


def test_a_first_name_alone_resolves_to_nobody():
    """Two active accounts are called 'Miguel Vargas'; a bare 'Miguel' must
    never pick one."""
    assert R._from_map("Miguel") == ""
    assert R._from_map("Zoria") == ""


def test_a_rep_with_no_slack_account_comes_back_empty_not_wrong():
    assert R._from_map("Christopher Jacob Rivera") == ""


def test_display_drops_the_tenure_tag():
    assert R.display("Ivan Soto (Wk 2)") == "Ivan Soto"


def main() -> int:
    import traceback
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            bad += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"{'FAILED' if bad else 'ok'} — {len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
