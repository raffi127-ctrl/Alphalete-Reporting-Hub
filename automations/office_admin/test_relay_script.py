"""The relay script is deployed by hand, so a missing function is a live bug.

`resources/icd-alerts-relay.gs` is pasted into Apps Script. Nothing compiles
it here and nothing imports it, so the usual safety net does not apply: a call
to a function that does not exist is perfectly valid JavaScript and only fails
when an admin presses the button.

That is not hypothetical. On 2026-11-06 `_admApexWeek` was added, the dispatch
line calling it was added, and the function body was then lost -- a concurrent
session rewrote the file between the edit and the commit (the hazard CLAUDE.md
warns about, and [[reference_generated_files_eat_hand_edits]]). It was COMMITTED
that way. A syntax check with `new Function()` passed, because an undefined
function is a runtime error, not a syntax error.

So this walks the script and checks that every one of its own functions that
gets called is also defined. Cheap, and it would have caught that in a second.
"""
from __future__ import annotations

import re
from pathlib import Path

RELAY = (Path(__file__).resolve().parents[2]
         / "resources" / "icd-alerts-relay.gs")

# The relay names its own internals with a leading underscore (_admSend,
# _officeJobEnqueue, _book). Those are what this checks; anything else is a
# built-in or a method on an object and is none of our business.
DEFINED = re.compile(r"\bfunction\s+(_[A-Za-z0-9_]*)\s*\(")
#  `_foo(` not preceded by a dot -- so `x._foo(` (a method) does not count.
CALLED = re.compile(r"(?<![.\w])(_[A-Za-z0-9_]*)\s*\(")


def _source() -> str:
    return RELAY.read_text(encoding="utf-8")


def test_the_relay_script_is_still_there():
    assert RELAY.exists(), "resources/icd-alerts-relay.gs has gone missing"
    assert len(_source()) > 10000


def test_every_function_the_relay_calls_is_one_it_defines():
    """The check that would have caught the lost _admApexWeek."""
    src = _source()
    defined = set(DEFINED.findall(src))
    called = set(CALLED.findall(src))
    missing = sorted(called - defined - {"_"})
    assert not missing, (
        "the relay calls %d function(s) it never defines: %s. Something was "
        "edited away -- check git log for resources/icd-alerts-relay.gs."
        % (len(missing), ", ".join(missing)))


def test_the_apex_week_job_is_wired_end_to_end():
    """All three pieces, named. Any one of them alone is a broken deploy:
    the kind without the call does nothing, the call without the function
    throws for the admin who presses the button."""
    src = _source()
    assert "apex_week: true" in src, "apex_week is not an allowed job kind"
    assert "_admApexWeek(sess, office, a)" in src, "nothing dispatches apex_week"
    assert "function _admApexWeek(" in src, "apex_week's handler is missing"


def test_apex_week_will_not_queue_two_runs_for_one_week():
    """This job creates payroll records. Two queued runs would read the same
    calendar and try to create the same people."""
    src = _source()
    body = src[src.index("function _admApexWeek("):]
    body = body[:body.index("\nfunction ")]
    assert "already_running" in body
    assert "OJ.RESULT_AT" in body, "it must ignore FINISHED runs when checking"


def test_a_week_that_is_not_a_date_is_refused():
    src = _source()
    body = src[src.index("function _admApexWeek("):]
    assert r"^\d{4}-\d{2}-\d{2}$" in body[:1200]


def test_the_board_calls_are_wired_end_to_end():
    """Three pieces each: the dispatch line and the function behind it. A
    dispatch with no function is valid JavaScript that throws for whoever
    presses the button — which is how 2f9d48d shipped broken."""
    src = _source()
    for call, fn in (("board_week", "_boardWeek"),
                     ("board_mark", "_boardMark"),
                     ("board_classroom", "_boardClassroom"),
                     ("board_gender", "_boardGender")):
        assert "what === '%s'" % call in src, "nothing dispatches %s" % call
        assert "function %s(" % fn in src, "%s has no handler" % fn


def _fn(src: str, name: str) -> str:
    """One function's body out of the Apps Script source.

    Sliced by hand in three tests already; named once here so a function that
    gets split in two is a one-line fix instead of three silent passes.
    """
    at = src.index("function %s(" % name)
    rest = src[at:]
    end = rest.index("\nfunction ", 1)
    return rest[:end]


def test_the_board_is_read_from_the_offices_own_workbook():
    """Each office sees its own people and nobody else's. The sheet id comes
    from the office's settings row, never from the caller.

    THE PROTECTION MOVED, so this test did too (2026-11-24). It used to look
    for `_admSettings(office)` inside `_boardTab`; the per-week book split that
    function in two, and the settings read now lives in `_boardBook`, which
    `_boardTab` calls. The test went red for days while the rule it guards was
    never broken -- and a suite with permanent reds is one people stop reading,
    which is how a real failure hides.

    So it asks the question of the chain rather than of one function: the book
    comes from the office's settings, `_boardTab` gets its book only from
    there, and NEITHER lets the caller name a workbook.
    """
    src = _source()
    assert "'Onboarding Sheet'" in src

    book = _fn(src, "_boardBook")
    assert "_admSettings(office)" in book, \
        "the workbook comes from the office's own settings row"
    assert "openById(set.sheet)" in book

    tab = _fn(src, "_boardTab")
    assert "_boardBook(office)" in tab, \
        "and _boardTab gets its book only from there"
    for body, where in ((book, "_boardBook"), (tab, "_boardTab")):
        assert "a.sheet" not in body, \
            "the caller does not get to name the workbook (%s)" % where


def test_marking_somebody_off_never_deletes_their_row():
    src = _source()
    body = src[src.index("function _boardMark("):]
    body = body[:body.index("\nfunction ")]
    for bad in ("deleteRow", "deleteRows", "clearContent"):
        assert bad not in body, "a terminated row is hidden, never deleted"
    assert "restore" in body, "and it can be undone"


def test_the_settings_tab_is_read_by_header_not_by_position():
    """Two columns were added to that tab on the same day — 'Onboarding Sheet'
    and 'Owner' — and whichever landed second shifted the other's index. A read
    by number returns the wrong cell SILENTLY, which is the worst kind."""
    src = _source()
    body = src[src.index("function _admSettings("):]
    body = body[:body.index("\n\n// One office")] if "\n\n// One office" in body else body[:2000]
    import re
    numeric = re.findall(r"rows\[i\]\[([1-9])\]", body)
    assert not numeric, "reads column %s by position" % ", ".join(numeric)
    for name in ("'State'", "'City'", "'AppStream'", "'Onboarding Sheet'"):
        assert name in body, "%s should be looked up by header" % name


def test_saving_an_office_never_writes_over_the_newer_columns():
    """Approved Accounts is the guard, Onboarding Sheet points at the board.
    A fixed span of columns would take both out the moment the order moved."""
    src = _source()
    body = src[src.index("function _admSetOffice("):]
    body = body[:body.index("\nfunction ")]
    assert "cur.cols[name]" in body, "it should place each value under its own header"
    assert "1, 1, row.length" not in body, "no fixed column span"


def test_the_phone_lookups_road_is_wired_end_to_end():
    """Numbers a person looked up for the resume push (2026-11-16). Office
    key: fetch / sent / add for its own office; admin key: add. Each piece
    named, as for apex_week -- a dispatch line without its function throws
    for every office's walk."""
    src = _source()
    assert ("if (body.phone_lookups) return _reply(_phoneLookups(office, body.phone_lookups));"
            in src), "the office-key call is not dispatched"
    assert "if (body.phone_lookups_add)" in src, "the admin road is not dispatched"
    for fn in ("_phoneLookups", "_phoneLookupsFor", "_phoneLookupsSent",
               "_phoneLookupsAdd", "_plSheet"):
        assert "function %s(" % fn in src, "%s is not defined" % fn
    # An office only ever sees, marks or adds its own rows.
    fetch = src[src.index("function _phoneLookupsFor("):src.index("function _phoneLookupsSent(")]
    assert "String(r[PL.OFFICE]).trim().toLowerCase() !== office" in fetch
    assert "PL.SENT" in fetch, "a sent row must never be handed out again"
    sent = src[src.index("function _phoneLookupsSent("):src.index("// --- OFFICE ADMINS")]
    assert "String(rows[i][PL.OFFICE]).trim().toLowerCase() === office" in sent
    assert "_phoneLookupsAdd(office, a.add, 'office:' + office)" in src, \
        "the office road must file rows under the caller's own office"
    # Nothing on this road removes a row or an applicant.
    section = src[src.index("// --- PHONE LOOKUPS"):src.index("// --- OFFICE ADMINS")]
    assert "deleteRow" not in section and ".clear(" not in section


# ------------- the pop-up: look up, confirm the genders, then send

# Megan, 2026-11-24: "when someone pushes the button to send to apex - we
# should pop up the names and gender we assume - then the admin/icd sending
# can change if they want before hitting send."

def _relay_src():
    import pathlib
    return pathlib.Path("resources/icd-alerts-relay.gs").read_text()


def test_apex_week_carries_preview_and_genders():
    src = _relay_src()
    body = src.split("function _admApexWeek(", 1)[1].split("\nfunction ", 1)[0]
    assert "preview: preview" in body, "a look-up must reach the office"
    assert "genders: genders" in body, "the confirmed answers must ride along"


def test_a_gender_has_to_be_a_word():
    """The only thing that travels in from the admin's machine is a gender,
    so nothing but a word may reach the form."""
    src = _relay_src()
    body = src.split("function _admApexWeek(", 1)[1].split("\nfunction ", 1)[0]
    assert "g !== 'Male' && g !== 'Female'" in body


def test_a_look_up_is_not_blocked_by_the_one_at_a_time_rule():
    """That rule stops two SENDS creating the same people twice. A preview
    creates nothing, and refusing it leaves a button that does nothing."""
    src = _relay_src()
    body = src.split("function _admApexWeek(", 1)[1].split("\nfunction ", 1)[0]
    assert "preview ? null :" in body
    assert "if (p.preview) continue;" in body


def test_who_is_in_the_week_is_still_read_at_the_office():
    """A name must not be postable from the admin's machine -- only a
    gender answered for one."""
    src = _relay_src()
    body = src.split("function _admApexWeek(", 1)[1].split("\nfunction ", 1)[0]
    assert "a.people" not in body
    assert "people:" not in body


# --------------------------------------------- the week-3 drug test (11/25)

def _drug_body(code_only: bool = False) -> str:
    src = _source()
    body = src[src.index("function _admDrugSend("):]
    body = body[:body.index("\nfunction ")]
    if not code_only:
        return body
    # CODE ONLY, because a test that reads comments tests its own prose. The
    # comment above this very function says "NOT `o.mode`" -- asserting on the
    # raw text made the check pass or fail on how the warning was WORDED
    # rather than on what the code does.
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("//"))


def test_the_drug_send_job_is_wired_end_to_end():
    """Same three pieces as apex_week. Raf asked for this button on
    2026-11-24; a kind without a dispatch line does nothing at all."""
    src = _source()
    assert "drug_send: true" in src, "drug_send is not an allowed job kind"
    assert "_admDrugSend(sess, office, a)" in src, "nothing dispatches drug_send"
    assert "function _admDrugSend(" in src, "drug_send's handler is missing"


def test_the_drug_send_never_falls_back_to_the_background_check_switch():
    """`o.mode` is the BACKGROUND CHECK's switch. If the drug send read it,
    every office already live on background checks would start placing drug
    orders the moment this shipped, and the first anybody would know is the
    owner's bill. No drug_mode on the sheet means dry."""
    body = _drug_body(code_only=True)
    assert "o.drug_mode || 'dry'" in body, body[-600:]
    assert "o.mode" not in body, "the drug send is reading the BGC mode"


def test_the_drug_send_does_not_use_the_background_check_duplicate_ledger():
    """`_admAlready` records background checks, and everybody in week 3 has
    had one. Running the drug list through it would flag the whole week as a
    duplicate and ask the admin to confirm a repeat that is not one."""
    body = _drug_body(code_only=True)
    assert "_admAlready" not in body, body[-600:]


def test_the_drug_send_still_asks_about_a_big_send():
    """Any order billed to an owner is worth 'is this many right?'."""
    body = _drug_body(code_only=True)
    assert "needs_big_confirm" in body


def test_both_sterling_sends_share_one_account_guard():
    """The 'is this calendar's account approved for this office' question has
    one answer, so it has one implementation. A guard copied in two places is
    a guard fixed in one of them."""
    src = _source()
    assert "function _admSterlingGuard(" in src
    assert src.count("_admSterlingGuard(sess, office, a)") >= 2, (
        "both _admSend and _admDrugSend must go through the shared guard")
