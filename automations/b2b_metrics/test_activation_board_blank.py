"""The blank-image guard on the recreated Activation Rate board.

2026-08-25: Carlos's Activation Rate section reached the B2B thread as a blank
image. Everything upstream said it worked — the activation source parsed clean
(344/534 = 64.4%, 35 reps), the board was rebuilt ("recreated, all rows"), no
fallback fired, and the section logged as posted. `render_png` simply never
looked at the file it returned, so an empty screenshot was indistinguishable
from a good one until a person opened the thread.

These pin the floor: a real board passes, an empty capture is caught and named,
and a machine without Pillow gets no opinion rather than a false alarm.

Run:  python -m automations.b2b_metrics.test_activation_board_blank
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from automations.b2b_metrics import activation_board as ab


def _cell(n, d, colour):
    return ab.Cell(num=n, den=d, pct=n / d, color=colour)


def _board(nreps: int) -> ab.Board:
    return ab.Board(
        owner_office="CARLOS HIDALGO [alphalete specialized marketing inc(tx]",
        reps=[(f"Rep Number {i:02d}", {w: _cell(17, 22, "Green") for w in ab.WINDOWS})
              for i in range(nreps)],
        grand_total={w: _cell(344, 534, "Yellow") for w in ab.WINDOWS},
        national={w: _cell(1000, 1800, "") for w in ab.WINDOWS})


def _white(path: Path, w: int = 2360, h: int = 3834) -> Path:
    from PIL import Image
    Image.new("RGB", (w, h), (255, 255, 255)).save(path)
    return path


def test_an_all_white_capture_is_caught():
    with tempfile.TemporaryDirectory() as d:
        p = _white(Path(d) / "blank.png")
        why = ab._looks_blank(p)
        assert why, "an all-white PNG must not pass"
        assert "ink" in why, why


def test_a_header_band_alone_is_still_blank():
    """The navy title bar renders even when the table doesn't. A whole-image ink
    floor does NOT catch that — a box filter smears the band into enough grey to
    clear it — which is why the guard measures the bottom half separately."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "header_only.png"
        im = Image.new("RGB", (2360, 3834), (255, 255, 255))
        for y in range(300):
            for x in range(2360):
                im.putpixel((x, y), (26, 54, 93))
        im.save(p)
        why = ab._looks_blank(p)
        assert why, "a bare header band is not a board"
        assert "table area is empty" in why, why


def test_a_one_rep_office_is_not_mistaken_for_blank():
    """The smallest real board there can be. Height tracks content, so even this
    one is ~46% ink below the fold — the guard must not argue with it."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "one.png"
        ab.render_png(_board(1), out, title_date="2026-08-25")
        assert ab._looks_blank(out) == ""


def test_a_real_render_passes():
    """The 35-rep board that this guard must never argue with."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "act.png"
        ab.render_png(_board(35), out, title_date="2026-08-25")
        assert ab._looks_blank(out) == "", "a real board must pass the guard"


def test_render_png_raises_on_a_blank_capture():
    """The guard is wired into render_png, not just available beside it."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "act.png"
        real = ab._looks_blank
        ab._looks_blank = lambda _p: "only 0.00% of pixels carry ink"
        try:
            try:
                ab.render_png(_board(3), out)
            except RuntimeError as e:
                assert "rendered blank" in str(e), e
                assert "3 rep row(s)" in str(e), e
            else:
                raise AssertionError("render_png swallowed a blank capture")
        finally:
            ab._looks_blank = real


def test_no_pillow_means_no_opinion():
    """A machine without Pillow must not start failing working boards."""
    import builtins
    real_import = builtins.__import__

    def _no_pil(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL here")
        return real_import(name, *a, **k)

    with tempfile.TemporaryDirectory() as d:
        p = _white(Path(d) / "blank.png")
        builtins.__import__ = _no_pil
        try:
            assert ab._looks_blank(p) == ""
        finally:
            builtins.__import__ = real_import


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
