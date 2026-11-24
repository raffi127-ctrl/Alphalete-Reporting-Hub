"""What the 6pm nudge publishes for the ApplicantStream pop-up.

The pop-up (extension/office-admin/bob.js) draws nothing it has not been told,
so every rule that keeps a card off somebody's screen when it should not be
there is a rule about this file.

    python -m pytest automations/office_admin/test_bob_owed.py -q
"""
import datetime as dt
import json

import pytest

from automations.office_admin import bob_owed as OWED

DAY = dt.date(2026, 11, 24)


class _WS:
    def __init__(self):
        self.grid = [list(OWED.HEADERS)]
        self.appended = []
        self.updates = []

    def get_all_values(self):
        return self.grid

    def append_row(self, row, **kw):
        self.appended.append((row, kw))
        self.grid.append(list(row))

    def update(self, values, rng, **kw):
        self.updates.append((values, rng, kw))
        row = int("".join(c for c in rng.split(":")[0] if c.isdigit()))
        self.grid[row - 1] = list(values[0])


@pytest.fixture(autouse=True)
def _own_tab(monkeypatch):
    ws = _WS()
    monkeypatch.setattr(OWED, "_tab", lambda sheet_id="": ws)
    return ws


def test_nothing_published_is_not_zero_owed():
    """THE SAFETY STOP. An office with nothing on today and an office whose
    calendar would not load look identical from here, and the second must
    never become a card."""
    assert OWED.owed("raf", DAY) is None


def test_a_published_read_comes_back_as_it_went_in(_own_tab):
    OWED.publish("raf", ["Jane Doe", "Sam Vega"], nudge=True, day=DAY)
    got = OWED.owed("raf", DAY)
    assert got["count"] == 2
    assert got["names"] == ["Jane Doe", "Sam Vega"]
    assert got["nudge"] is True
    assert got["day"] == "2026-11-24"


def test_a_real_zero_is_published_and_is_not_none(_own_tab):
    """"We read the calendar and everybody is marked" is a real answer, and it
    is the one that stops the card."""
    OWED.publish("raf", [], nudge=True, day=DAY)
    got = OWED.owed("raf", DAY)
    assert got is not None
    assert got["count"] == 0 and got["names"] == []


def test_the_hourly_ticks_keep_one_row_per_office_per_day(_own_tab):
    """The nudge reads again every hour through the evening. Five rows for one
    answer would leave the pop-up picking between them."""
    OWED.publish("raf", ["Jane Doe", "Sam Vega"], nudge=False, day=DAY)
    OWED.publish("raf", ["Sam Vega"], nudge=True, day=DAY)
    assert len(_own_tab.appended) == 1
    assert len(_own_tab.updates) == 1
    assert len(_own_tab.grid) == 2            # header + the one row
    got = OWED.owed("raf", DAY)
    assert got["count"] == 1 and got["nudge"] is True


def test_a_snapshot_is_only_for_its_own_day_and_office(_own_tab):
    OWED.publish("raf", ["Jane Doe"], nudge=True, day=DAY)
    assert OWED.owed("raf", DAY + dt.timedelta(days=1)) is None
    assert OWED.owed("omar", DAY) is None


def test_the_key_is_not_case_sensitive(_own_tab):
    OWED.publish("RAF", ["Jane Doe"], nudge=True, day=DAY)
    assert OWED.owed("raf", DAY)["count"] == 1


def test_the_day_and_the_stamp_are_written_RAW(_own_tab):
    """Sheets parses '2026-11-24' into a Date given the chance, and the
    press's own lookup compares strings -- a coerced cell stops matching."""
    OWED.publish("raf", ["Jane Doe"], nudge=True, day=DAY)
    row, kw = _own_tab.appended[0]
    assert kw.get("value_input_option") == "RAW"
    assert row[OWED.HEADERS.index("Day")] == "2026-11-24"


def test_the_stamp_says_what_timezone_it_is_in(_own_tab):
    """The relay works out whether a snapshot is stale, and it does not run on
    the Lucy that wrote it. A naive stamp is hours wrong, silently."""
    OWED.publish("raf", ["Jane Doe"], nudge=True, day=DAY)
    stamp = _own_tab.appended[0][0][OWED.HEADERS.index("Read At")]
    when = dt.datetime.fromisoformat(stamp)
    assert when.tzinfo is not None


def test_an_unreadable_sheet_reads_as_no_snapshot(monkeypatch):
    """Not as zero owed, and not as a card either: a pop-up that appears when
    the read failed is the one that teaches people to dismiss the real ones."""
    def boom(sheet_id=""):
        raise OSError("no sheet")
    monkeypatch.setattr(OWED, "_tab", boom)
    assert OWED.owed("raf", DAY) is None


def test_rubbish_in_the_names_cell_does_not_crash_the_read(_own_tab):
    OWED.publish("raf", ["Jane Doe"], nudge=True, day=DAY)
    _own_tab.grid[1][OWED.HEADERS.index("Names JSON")] = "{not json"
    got = OWED.owed("raf", DAY)
    assert got["names"] == [] and got["count"] == 1


def test_names_are_tidied_and_blanks_dropped(_own_tab):
    OWED.publish("raf", ["  Jane   Doe ", "", None, "Sam Vega"],
                 nudge=True, day=DAY)
    assert OWED.owed("raf", DAY)["names"] == ["Jane Doe", "Sam Vega"]


def test_no_office_key_is_refused():
    with pytest.raises(ValueError):
        OWED.publish("", [], nudge=True, day=DAY)
    assert OWED.owed("", DAY) is None


def test_publishing_does_not_post_or_send_anything():
    """It is a record of a read, nothing else. The DM is bob_nudge's and the
    post is the daily update's."""
    import inspect
    src = inspect.getsource(OWED)
    for word in ("chat_postMessage", "post_reply", "_slack", "dm_office"):
        assert word not in src, word


# ------------------------------------------- the nudge, and what it publishes

def test_the_nudge_publishes_what_it_read():
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.run)
    assert "publish_owed(" in src, "the nudge must hand its read over"
    # Before the gates that skip an owner: an empty list and a not-yet-6pm
    # read are both answers the pop-up needs.
    assert src.index("publish_owed(") < src.index("all BOB calls marked")


def test_a_failed_read_publishes_nothing():
    """`continue` on an unreadable calendar, an empty table or a wrong-office
    read happens BEFORE the publish, so no snapshot is written -- which is how
    "nobody looked" stays different from "nobody owes anything"."""
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.run)
    at = src.index("publish_owed(")
    for guard in ("the calendar could not be read", "NUDGING NOBODY -- the "
                  "second interviews table came", "so the office did not "):
        assert src.index(guard) < at, guard


def test_the_snapshot_carries_the_offices_own_6pm():
    """The nudge decides the hour off the office's own timezone; the relay
    checks nothing but how old the snapshot is."""
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.publish_owed)
    assert "is_nudge_time(office, utc_now, hour)" in src


def test_a_snapshot_we_could_not_write_never_costs_the_DM():
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.publish_owed)
    assert "except Exception" in src and "return False" in src


def test_the_nudge_respects_the_press():
    """Megan's button is the whole point: an office that has said its calls
    are made does not get nudged about them, on either surface."""
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.run)
    assert "pressed_today(office, today)" in src
    assert src.index("pressed_today(office, today)") < src.index("text = message(")
    press = inspect.getsource(N.pressed_today)
    assert "BOB.done(" in press


def test_an_unreadable_press_still_nudges():
    """The two failures are "somebody who was done got a DM" and "somebody is
    removed at 7pm with no warning", and they are not equals."""
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.pressed_today)
    tail = src[src.index("except Exception"):]
    assert "return False" in tail


def test_the_two_halves_agree_on_how_stale_is_too_stale():
    """The relay enforces it; this file defines it. Two numbers drifting apart
    is a card that shows up on a read nobody trusts."""
    import pathlib
    import re
    gs = (pathlib.Path(__file__).resolve().parents[2] / "resources"
          / "icd-alerts-relay.gs").read_text(encoding="utf-8")
    m = re.search(r"var BOB_STALE_MINUTES = (\d+);", gs)
    assert m, "the relay has no BOB_STALE_MINUTES"
    assert int(m.group(1)) == OWED.STALE_MINUTES


def test_the_relay_and_this_file_agree_on_the_columns():
    """The relay reads this tab by header name; a column renamed on one side
    only would read blank, which looks exactly like "nothing owed"."""
    import pathlib
    gs = (pathlib.Path(__file__).resolve().parents[2] / "resources"
          / "icd-alerts-relay.gs").read_text(encoding="utf-8")
    assert "var BOB_OWED_TAB = '%s';" % OWED.TAB in gs
    for h in OWED.HEADERS:
        assert "'%s'" % h in gs, "the relay never names the %r column" % h


def test_the_relay_and_the_press_agree_on_the_columns():
    """The relay writes a press row the admin page and the daily update both
    read back."""
    import pathlib
    from automations.office_admin import bob_calls as BOB
    gs = (pathlib.Path(__file__).resolve().parents[2] / "resources"
          / "icd-alerts-relay.gs").read_text(encoding="utf-8")
    assert "var BOB_DONE_TAB = '%s';" % BOB.TAB in gs
    head = "var BOB_DONE_HEAD = [%s];" % ", ".join("'%s'" % h for h in BOB.HEADERS)
    assert head in gs, "the relay's press columns have drifted from bob_calls"


# ------------------------------------- the card itself (the pop-up half)
#
# Nothing compiles the extension here and nothing imports it, so these are
# the same kind of check as test_relay_script's: the rules that keep a card
# off somebody's screen, asked of the file on disk.

def _ext(name: str) -> str:
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[2] / "extension"
            / "office-admin" / name).read_text(encoding="utf-8")


def test_the_card_is_part_of_the_extension():
    """Megan's own install is the repo folder, so a file the manifest does
    not name simply never runs."""
    import json
    m = json.loads(_ext("manifest.json"))
    js = m["content_scripts"][0]["js"]
    assert "bob.js" in js
    # After offered.js and content.js: it shares nothing with them, but the
    # BGC panel owns the bottom-right corner and loads first.
    assert js.index("bob.js") > js.index("content.js")
    assert _ext("bob.js")


def test_the_card_is_switched_off():
    """The DM half's LaunchAgent is disarmed (Megan 2026-11-19: "don't take
    anything live yet for actual posting"), so the half that pops up must not
    go live on a `git pull` either."""
    src = _ext("bob.js")
    assert "var ARMED = false;" in src
    assert "if (!(await armed()))" in src, "and the switch is actually checked"


def test_the_card_draws_nothing_unless_the_relay_says_so():
    """FAIL QUIET. No snapshot, a stale one, before 6pm, already pressed,
    signed out, any error: nothing appears. A card that shows up when the
    calls ARE made is the one that teaches people to dismiss the real ones."""
    src = _ext("bob.js")
    body = src[src.index("async function check()"):]
    assert "if (!info.nudge)" in body
    assert body.index("if (!info.nudge)") < body.index("draw(office, info)")
    for guard in ("!me.ok", "!info.ok", "!office"):
        assert guard in body, "nothing covers %s" % guard
    # Every one of those paths ends in a console line, never in UI.
    assert "quiet(" in body and body.count("draw(") == 1


def test_the_card_does_not_read_the_calendar():
    """bob_nudge reads it, through a login, with rules that took a day of
    probing. The only thing read off the page here is the account number in
    the page header."""
    # The CODE, not the comments -- the file explains at length why it does
    # not touch LucyOffered, and that sentence is the opposite of a problem.
    code = "\n".join(l for l in _ext("bob.js").splitlines()
                     if not l.lstrip().startswith("//"))
    for bad in ("SECOND INTERVIEW", "sOfferPosition", "LucyOffered"):
        assert bad not in code, "it should ask the relay, not re-read the page"
    assert "ask('bob_nudge'" in code


def test_the_card_goes_away_for_the_day_when_it_is_dismissed():
    """Megan asked for dismissible, and a card that comes back on the next
    page load is not dismissible."""
    src = _ext("bob.js")
    assert "bobSeen" in src
    assert "markSeen(office.office, info.day)" in src
    assert "map[office.office] === info.day" in src, \
        "and a dismissed day is checked before drawing"


def test_the_cards_button_is_the_same_press_and_posts_nothing():
    """"link to or offer the same press the admin page has" -- so somebody
    who sees it can answer it where they are."""
    src = _ext("bob.js")
    assert "ask('bob_done'" in src
    assert "I\\'ve made today\\'s BOB calls" in src
    for bad in ("fetch(", "postMessage"):
        assert bad not in src, bad


def test_a_press_that_did_not_save_says_so():
    """An office sitting all evening waiting for an update that is still held,
    with nothing on screen saying why, is the failure that matters here."""
    src = _ext("bob.js")
    at = src.index("ask('bob_done'")
    body = src[at:at + 1200]
    assert "did not save" in body
    assert "go.disabled = false" in body, "and the button comes back"


def test_the_card_has_its_own_styles():
    src = _ext("content.css")
    assert "#lucy-bob-card {" in src
    # Its own corner: the BGC button and panel are bottom-right.
    assert "top: 22px" in src[src.index("#lucy-bob-card {"):]


def test_the_card_is_valid_javascript():
    """A syntax error in a content script is silent -- the page just never
    gets the card. Checked with whatever this machine has (node, else the
    plain parse Chrome would do)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("no node on this machine")
    src = _ext("bob.js")
    p = subprocess.run([node, "--check", "-"], input=src, text=True,
                       capture_output=True)
    assert p.returncode == 0, p.stderr


def test_a_dry_run_writes_no_snapshot():
    """The house rule for anything still being built: a --dry-run writes
    nothing to a Sheet. `--publish` is the opt-in that previews the card, and
    it still DMs nobody."""
    import inspect
    from automations.second_round_contacts import bob_nudge as N
    src = inspect.getsource(N.run)
    assert "if publish:" in src
    assert "publish = send if publish is None else publish" in src
    main = inspect.getsource(N.main)
    assert '"--publish"' in main
    assert "publish=True if args.publish else None" in main
