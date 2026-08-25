"""The shared Sheets-export guards.

Seven modules ask the Sheets PDF-export endpoint for a range and rasterise the
answer. A HIDDEN tab answers HTTP 200 with a valid, EMPTY 993-byte PDF — no
error anywhere — so the caller renders a white rectangle and posts it as if it
were the report (2026-08-25, Carlos's B2B thread).

The floor is calibrated, not guessed. Measured against the live endpoint that
day: the empty answer is 993 bytes, and the SMALLEST real export — a single
populated cell, A1:A1 — is 14,570. 2000 sits an order of magnitude under the
smallest real one and at twice the empty one.

Run:  python -m automations.shared.test_sheets_export
"""
from __future__ import annotations

from automations.shared import sheets_export as sx


def _pdf(nbytes: int) -> bytes:
    """A byte string that passes as a PDF of a given size."""
    body = b"%PDF-1.4" + b"\x00" * max(0, nbytes - 8)
    return body[:nbytes] if nbytes >= 8 else b"%PDF"


def test_the_empty_export_is_rejected():
    """993 bytes is the real measured size of the hidden-tab answer."""
    try:
        sx.check_pdf(_pdf(993), where="LUCY CHURN!A1:N22")
    except RuntimeError as e:
        assert "EMPTY" in str(e), e
        assert "LUCY CHURN!A1:N22" in str(e), e
    else:
        raise AssertionError("993 bytes must not pass")


def test_the_message_names_the_tab_before_the_token():
    """Both causes produce an identical empty PDF, so the ORDER of the hints is
    the whole value of the message — the tab is checkable in seconds."""
    try:
        sx.check_pdf(_pdf(993), where="x")
    except RuntimeError as e:
        msg = str(e)
        assert msg.index("HIDDEN") < msg.index("token"), msg
        assert "sheets_whoami" in msg, msg


def test_the_smallest_real_export_passes():
    """A1:A1 of one populated cell measured 14,570 bytes on the live endpoint."""
    assert sx.check_pdf(_pdf(14570), where="x")


def test_a_value_just_over_the_floor_passes():
    assert sx.check_pdf(_pdf(sx.EMPTY_PDF_BYTES + 1), where="x")


def test_something_that_is_not_a_pdf_is_its_own_error():
    """An HTML login page saved as .pdf must not read as 'hidden tab'."""
    try:
        sx.check_pdf(b"<!DOCTYPE html><html>Sign in", where="x")
    except RuntimeError as e:
        assert "did not return a PDF" in str(e), e
    else:
        raise AssertionError("non-PDF content must not pass")


def test_empty_content_is_rejected():
    try:
        sx.check_pdf(b"", where="x")
    except RuntimeError as e:
        assert "did not return a PDF" in str(e), e
    else:
        raise AssertionError("no content must not pass")


class _FakeSpreadsheet:
    def __init__(self, hidden):
        self._hidden = hidden
        self.calls = []

    def fetch_sheet_metadata(self):
        return {"sheets": [{"properties": {"sheetId": 7,
                                           "hidden": self._hidden}}]}

    def batch_update(self, body):
        req = body["requests"][0]["updateSheetProperties"]
        self._hidden = req["properties"]["hidden"]
        self.calls.append(self._hidden)


class _FakeWs:
    id = 7
    title = "LUCY CHURN"

    def __init__(self, hidden):
        self.spreadsheet = _FakeSpreadsheet(hidden)


def test_a_hidden_tab_is_revealed_and_put_back():
    ws = _FakeWs(hidden=True)
    with sx.visible_for_export(ws):
        assert ws.spreadsheet._hidden is False, "must be visible during the export"
    assert ws.spreadsheet._hidden is True, "must go back to hidden"
    assert ws.spreadsheet.calls == [False, True]


def test_it_is_put_back_even_when_the_export_blows_up():
    """A crash must not leave someone's board rearranged."""
    ws = _FakeWs(hidden=True)
    try:
        with sx.visible_for_export(ws):
            raise RuntimeError("export exploded")
    except RuntimeError:
        pass
    assert ws.spreadsheet._hidden is True
    assert ws.spreadsheet.calls == [False, True]


def test_a_visible_tab_is_never_touched():
    """This reveals; it must never hide anything that wasn't already hidden."""
    ws = _FakeWs(hidden=False)
    with sx.visible_for_export(ws):
        pass
    assert ws.spreadsheet.calls == [], "a visible tab needs no writes at all"


def _main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok   " + name)
            except AssertionError as e:
                fails += 1
                print("  FAIL " + name + ": " + str(e))
    print(("FAILED " + str(fails)) if fails else "all green")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())
