"""The email fetcher's console output must never abort a download.

2026-09-01: regenerating output/financial-source-gap.md from Windows, this
came back before a single attachment hit disk:

    File "automations/shared/email_ingest.py", line 215, in fetch_all
      print(f"  \u2713 {out.name}", flush=True)
    UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'

The download had already SUCCEEDED — `out.write_bytes` ran, `seen[key]` was
set. The crash was the announcement line, and it took the whole sweep with it:
every attachment after the first never downloaded and the caller could only
report "no source arrived". Windows consoles default to cp1252, so this fires
on any hand-run from Lucy 2/3 while the scheduled runs on the mini (UTF-8)
stay green — which is why it hid for so long.

The marker is only half of it: attachment names come straight off the sender
(`_decode`), so an accent or an emoji in a filename lands in the same print.
_say has to survive BOTH.

Run:  python -m automations.shared.test_email_ingest
"""
from __future__ import annotations

import io
import sys

from automations.shared import email_ingest as ei


class _Cp1252Stdout(io.TextIOWrapper):
    """A stdout that behaves like a Windows console: anything outside cp1252
    raises on write, exactly as the real one does."""

    def __init__(self):
        super().__init__(io.BytesIO(), encoding="cp1252", errors="strict",
                         line_buffering=True)

    def written(self) -> str:
        self.flush()
        return self.buffer.getvalue().decode("cp1252", "replace")


def _under_cp1252(msg: str) -> str:
    real, fake = sys.stdout, _Cp1252Stdout()
    sys.stdout = fake
    try:
        ei._say(msg)
        return fake.written()
    finally:
        sys.stdout = real


def test_the_check_mark_does_not_raise():
    """The exact line that killed the sweep."""
    out = _under_cp1252("  \u2713 RAF ADD 1 FINANCIAL SUMMARY 2026.08.29.xlsx")
    assert "RAF ADD 1 FINANCIAL SUMMARY 2026.08.29.xlsx" in out, out


def test_a_non_ascii_filename_does_not_raise():
    """Senders put accents in attachment names; escaping only the marker
    would have left this second path still fatal."""
    out = _under_cp1252("  \u2713 Informe Financiero \u2014 Mu\u00f1oz \U0001f4c8.xlsx")
    assert "Informe Financiero" in out, out
    assert ".xlsx" in out, out


def test_the_error_line_survives_too():
    """The '!' branch prints a repr of the same sender-supplied name. The
    character has to be one cp1252 genuinely LACKS \u2014 a curly quote, an em dash
    and an accent all encode fine there, so a name built from those would let
    this test pass against the unfixed code."""
    out = _under_cp1252("  ! '\u4f1a\u8ba1 book \U0001f4c8.xlsx': OSError boom")
    assert "OSError boom" in out, out


def test_plain_ascii_is_passed_through_untouched():
    """The fallback must not kick in — and must not mangle — normal output."""
    out = _under_cp1252("  ! 'plain.xlsx': OSError boom")
    assert out.strip() == "! 'plain.xlsx': OSError boom", repr(out)


def test_a_utf8_console_keeps_the_real_characters():
    """On the mini nothing changes: the check mark stays a check mark."""
    real, fake = sys.stdout, io.TextIOWrapper(io.BytesIO(), encoding="utf-8",
                                              line_buffering=True)
    sys.stdout = fake
    try:
        ei._say("  \u2713 book.xlsx")
    finally:
        sys.stdout = real
    fake.flush()
    assert "\u2713" in fake.buffer.getvalue().decode("utf-8")


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
