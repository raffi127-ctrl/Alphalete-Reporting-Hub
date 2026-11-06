"""Build the Chrome Web Store upload for the Lucy Office Admin extension.

The store wants manifest.json at the TOP of the zip (not inside a folder),
and every upload needs a higher version than the last one. So:

    python -m automations.office_admin.store_zip            # bump 1.1.0 -> 1.1.1, build
    python -m automations.office_admin.store_zip --no-bump  # build as-is

-> output/chrome-web-store/lucy-office-admin-<version>.zip. Upload it at
chrome.google.com/webstore/devconsole -> Lucy Office Admin -> Package ->
Upload new package -> Submit for review. Admins get it automatically once
Google approves it (Megan 2026-11-06: no more zips by hand).
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension" / "office-admin"
OUT = ROOT / "output" / "chrome-web-store"
SKIP = {"README.md", ".DS_Store"}


def bump(version: str) -> str:
    parts = [int(x) for x in version.split(".")]
    parts[-1] += 1
    return ".".join(str(x) for x in parts)


def build(do_bump: bool = True) -> Path:
    mpath = EXT / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if do_bump:
        manifest["version"] = bump(manifest["version"])
        mpath.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / ("lucy-office-admin-%s.zip" % manifest["version"])
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(EXT.rglob("*")):
            if f.is_file() and f.name not in SKIP:
                z.write(f, f.relative_to(EXT).as_posix())
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Chrome Web Store zip.")
    ap.add_argument("--no-bump", action="store_true", help="keep the current version")
    a = ap.parse_args(argv)
    dest = build(do_bump=not a.no_bump)
    print("built %s" % dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
