"""Sync the leader headshots to Lucy 1 via a PRIVATE Sheet tab.

The headshots (`resources/leader-headshots/processed/*.png`) are gitignored on
purpose — the repo is PUBLIC and these are photos of real people. So Lucy 1,
which only ever pulls from git, never has them, and its bulletin render shows
empty circles instead of faces.

This ships them WITHOUT the public repo and WITHOUT any new credential: each PNG
is base64'd and stashed in a `_headshots` tab of the private override workbook —
the same workbook (and the same spreadsheets-only OAuth) the reports already
read. Drive would have been cleaner but the report token has no Drive scope, and
adding one means a browser re-auth + re-provisioning the token to Lucy 1; the
Sheet path needs none of that.

Images are downscaled to 256px before upload — the cards display at 84px (×2 for
retina), so there is no visible loss, and it keeps the cache ~300 KB instead of
~5 MB. A base64 cell is capped at 45 000 chars (< Sheets' 50 000 limit), so a
photo spans a few columns; the reader concatenates them back.

    python -m automations.override_bulletin.headshot_sync --upload   # from the laptop (has the photos)
    lucy rerun dd_headshots_sync                                       # download onto Lucy 1
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

from automations.override_bulletin import dd_data as D

HEADSHOTS = (Path(__file__).resolve().parents[2] / "resources" /
             "leader-headshots" / "processed")
TAB = "_headshots"
CHUNK = 45000          # < Sheets' 50k char/cell limit
MAX_PX = 256           # cards render at 84px; 256 is plenty and keeps it small


def _ws():
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(D.WORKBOOK_ID)
    try:
        return sh.worksheet(TAB)
    except Exception:  # noqa: BLE001
        return sh.add_worksheet(title=TAB, rows=40, cols=20)


def _shrink(png_bytes):
    """Downscale to MAX_PX (longest side) so the cache stays tiny. Never upscales;
    if PIL is missing, ships the bytes as-is."""
    try:
        from PIL import Image
    except ImportError:                       # pragma: no cover
        return png_bytes
    im = Image.open(io.BytesIO(png_bytes))
    if max(im.size) > MAX_PX:
        im.thumbnail((MAX_PX, MAX_PX))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    return png_bytes


def upload(verbose=True):
    """Encode every headshot into the `_headshots` tab. Run from the laptop."""
    files = sorted(HEADSHOTS.glob("*.png"))
    if not files:
        raise RuntimeError(f"no headshots in {HEADSHOTS}")
    rows = []
    for f in files:
        b = _shrink(f.read_bytes())
        s = base64.b64encode(b).decode()
        chunks = [s[i:i + CHUNK] for i in range(0, len(s), CHUNK)]
        rows.append([f.name] + chunks)
        if verbose:
            print(f"  {f.name}: {len(b) // 1024} KB → {len(chunks)} chunk(s)")
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]           # pad to rectangle
    ws = _ws()
    ws.clear()
    ws.update(range_name=f"A1:{_col(width)}{len(rows)}", values=rows,
              value_input_option="RAW")
    print(f"✓ {len(files)} headshot(s) → '{TAB}' tab ({width} col(s))")
    return len(files)


def download(verbose=True):
    """Rebuild the PNGs from the `_headshots` tab. Run on Lucy 1 before the build.
    Returns the number written. Idempotent — overwrites the local files."""
    HEADSHOTS.mkdir(parents=True, exist_ok=True)
    ws = _ws()
    rows = ws.get_all_values()
    n = 0
    for r in rows:
        name = (r[0] or "").strip()
        if not name.lower().endswith(".png"):
            continue
        b64 = "".join(c for c in r[1:] if c)
        if not b64:
            if verbose:
                print(f"  ⚠ {name}: no data — skipped")
            continue
        (HEADSHOTS / name).write_bytes(base64.b64decode(b64))
        n += 1
        if verbose:
            print(f"  wrote {name}")
    if not n:
        raise RuntimeError(f"no headshots on the '{TAB}' tab — run --upload first")
    print(f"✓ {n} headshot(s) → {HEADSHOTS}")
    return n


def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def main(argv=None):
    argv = argv or sys.argv[1:]
    try:
        if "--upload" in argv:
            upload()
        else:
            download()
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
