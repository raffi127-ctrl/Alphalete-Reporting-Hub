"""The Blue Ink field map, and the name matching that finds a person's packet.

Blue Ink's fields carry no labels, so everything downstream rests on the
calibration rules in `fieldmap`. These are the cases that actually went wrong
while it was being built.
"""
from __future__ import annotations

from automations.apex_new_starts import blueink_data as BID
from automations.apex_new_starts import fieldmap as FM

I9 = "UNIVERSAL I9 MASTER FORM"
DD = "RAFAEL DD FORM"


def _rows(packet_name, fields, doc=I9):
    return [{"doc": doc, "key": k, "kind": kind, "value": v,
             "packet_name": packet_name} for k, kind, v in fields]


def test_a_date_box_is_only_a_birthday_on_the_i9():
    """The W-4 and the DD form each carry one date box and it is the date they
    SIGNED. Reading that as a birthday put today's date in Apex's DOB field."""
    assert FM.classify("5/12/1998", "dat", "Ann Lee", I9) == "dob"
    assert FM.classify("9/3/2026", "dat", "Ann Lee", DD) is None


def test_a_two_word_surname_still_reads_as_the_surname():
    """'Urbina Finol' on the form, addressed to 'Jean Urbina Finol'. String
    equality against the last token called this nothing at all, which left the
    I-9's last-name box unnamed."""
    assert FM.classify("Urbina Finol", "inp", "Jean Urbina Finol", I9) == "last"
    assert FM.classify("Jean", "inp", "Jean Urbina Finol", I9) == "first"


def test_a_print_your_name_box_is_not_a_name_field():
    """The DD form's one text box holds the WHOLE name. Mapped to 'last' it
    would put 'Orlando Marines' in Apex's surname field."""
    assert FM.classify("Orlando Marines", "inp", "Orlando Marines", DD) == "full_name"


def test_shapes_that_cannot_be_confused():
    assert FM.classify("123-45-6789", "inp", "A B", I9) == "ssn"
    assert FM.classify("75060", "inp", "A B", I9) == "zip"
    assert FM.classify("(214) 555-0123", "inp", "A B", I9) == "phone"
    assert FM.classify("a@b.com", "inp", "A B", I9) == "email"
    assert FM.classify("317 Sample St", "inp", "A B", I9) == "address1"
    assert FM.classify("TX", "inp", "A B", I9) == "state"


def test_a_key_that_means_two_things_is_left_unnamed():
    """One packet's SSN box holding a phone number in the next is a key we do
    not understand. Naming it anyway is how a phone number gets typed into a
    Social Security field."""
    rows = (_rows("Ann Lee", [("k1", "inp", "123-45-6789")])
            + _rows("Bob Ray", [("k1", "inp", "(214) 555-0123")]))
    mapping, unresolved = FM.build(rows)
    assert "k1" not in mapping.get(I9, {})
    assert any(u[1] == "k1" for u in unresolved)


def test_one_odd_packet_does_not_block_a_key():
    """Somebody types a surname their packet wasn't addressed to -- a married
    name, a typo. Nine clean samples out of ten is a fact, and demanding all
    ten left the I-9's last-name box unnamed for real."""
    rows = []
    for i in range(9):
        rows += _rows(f"Ann Lee{i}", [("k1", "inp", f"Lee{i}")])
    rows += _rows("Zoe Quinn", [("k1", "inp", "Somethingelse")])
    mapping, _ = FM.build(rows)
    assert mapping[I9]["k1"] == "last"


def test_two_fields_claiming_the_same_thing_are_both_dropped():
    """The W-4 carries the EMPLOYER's address beside the employee's. Same
    shape, no way to tell them apart, so neither is trusted.

    Two samples, not one: a key is never named off a single packet -- one
    lucky-looking value is a coincidence, and `build` says so by requiring at
    least two readable samples to agree."""
    rows = (_rows("Ann Lee", [("k1", "inp", "317 Sample St"),
                              ("k2", "inp", "3100 Office Pkwy")])
            + _rows("Bob Ray", [("k1", "inp", "42 Other Rd"),
                                ("k2", "inp", "3100 Office Pkwy")]))
    mapping, unresolved = FM.build(rows)
    assert not mapping.get(I9, {})
    assert all("claimed by 2" in u[2] for u in unresolved)


def test_city_is_found_by_where_it_sits():
    """City is plain text -- no shape to match on. It is the field between the
    address and the two-letter state, which is the only place it can be."""
    rows = (_rows("Ann Lee", [("k1", "inp", "317 Sample St"),
                              ("k2", "inp", "Irving"), ("k3", "inp", "TX")])
            + _rows("Bob Ray", [("k1", "inp", "42 Other Rd"),
                                ("k2", "inp", "Denton"), ("k3", "inp", "TX")]))
    mapping, _ = FM.build(rows)
    assert mapping[I9]["k2"] == "city"


def test_the_board_and_blue_ink_spell_people_differently():
    """Every mismatch seen so far is punctuation or decoration, not a different
    person. Ja'Vanna Nash had a signed packet the whole time and the report
    reported her as having none."""
    assert BID._key("Ja'Vanna Nash") == BID._key("Javanna Nash")
    assert BID._key("Orlando Marines (Wk 2)") == BID._key("Orlando Marines")
    assert BID._key("Jean Urbina Finol") == BID._key("Jean Finol")
    assert BID._key("Luis Valenzuela Jr.") == BID._key("Luis Valenzuela")
    assert BID._key("Anibal  Delgado") == BID._key("Anibal Delgado")


def test_different_people_do_not_collide():
    assert BID._key("Ann Lee") != BID._key("Bob Lee")
    assert BID._key("Ann Lee") != BID._key("Ann Ray")


def test_a_wrong_shaped_value_is_refused_not_typed():
    """If a template edit shifts the keys, the map is stale. That shows up as a
    value of the wrong shape, and it has to come back as a refusal."""
    bundle = {"id": "x", "packets": [{"name": "Ann Lee"}],
              "documents": [{"key": "d1", "name": I9}]}
    mapping = {I9: {"f1": "zip", "f2": "city"}}
    rows = [{"doc_key": "d1", "field_key": "f1", "kind": "inp",
             "value": "(214) 555-0123"},
            {"doc_key": "d1", "field_key": "f2", "kind": "inp",
             "value": "Irving"}]
    orig = BID.bundle_data
    BID.bundle_data = lambda _bid: rows
    try:
        hire = BID.extract(bundle, mapping, "Ann Lee")
    finally:
        BID.bundle_data = orig
    assert "zip" not in hire.values
    assert hire.values["city"] == "Irving"
    assert hire.rejected and hire.rejected[0][0] == "zip"


def test_the_ssn_never_rides_along_with_the_fillable_values():
    """apex.apply_fill types whatever fillable() returns. If an SSN could get
    in there it would be typed."""
    hire = BID.NewHire(name="Ann Lee",
                       values={"first": "Ann", "ssn": "123-45-6789"})
    assert "ssn" not in hire.fillable()
    assert hire.sensitive == {"ssn": "123-45-6789"}
