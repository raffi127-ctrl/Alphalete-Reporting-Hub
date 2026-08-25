"""The blank-page guard on the Sheets PDF-export renderer.

2026-08-25: Carlos's `customer_churn` and `activation_by_rep` sections reached
the B2B thread as white rectangles. The cause is not the board — it is the
export CREDENTIAL. `/export?format=pdf` is a Drive endpoint, and the runner's
OAuth token carries only `.../auth/spreadsheets` (confirmed on Lucy 2 via
`lucy sheets_whoami`). Asked with a token that lacks the scope, Google does not
answer 403: it answers **HTTP 200 with a valid, empty 993-byte PDF**. So
`_fetch` raises nothing, `_trim` finds no bounding box and passes the untrimmed
blank page through, and the section posts looking exactly like a good capture.

These pin that an empty export is now an error, and that a real one still isn't.

Run:  python -m automations.vantura_churn.test_shot_blank
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from automations.vantura_churn import shot


class _FakeSheet:
    id = "SHEETID"


class _FakeWs:
    title = "LUCY CHURN"
    id = 0
    spreadsheet = _FakeSheet()


class _Resp:
    status_code = 200

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def _pdf(text: str | None) -> bytes:
    """A one-page PDF, blank or with a line of text."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 144), text, fontsize=48)
    return doc.tobytes()


def _run(pdf_bytes: bytes, out: Path):
    real_get, real_tok = shot.requests.get, shot._access_token
    shot.requests.get = lambda *a, **k: _Resp(pdf_bytes)
    shot._access_token = lambda: "fake-token"
    try:
        return shot.render(_FakeWs(), out, rng="A1:N22")
    finally:
        shot.requests.get, shot._access_token = real_get, real_tok


def test_an_empty_export_raises_instead_of_saving_a_white_png():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "shot.png"
        try:
            _run(_pdf(None), out)
        except RuntimeError as e:
            assert "blank page" in str(e), e
            # The message has to send the reader at the credential, because the
            # board being empty is the wrong place to look and costs an hour.
            assert "sheets_whoami" in str(e), e
        else:
            raise AssertionError("a blank export must not produce a file")
        assert not out.exists(), "nothing should be written on a blank export"


def test_a_real_export_still_renders():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "shot.png"
        p = _run(_pdf("LUCY CHURN 22/383"), out)
        assert p.exists() and p.stat().st_size > 0


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
