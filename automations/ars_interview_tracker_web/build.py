"""Builds Index.html (the page pasted into Apps Script) from src/shell.html + src/app.js.

Why the page code is packed: Apps Script's HtmlService strips what it thinks are
comments from inline <script> blocks and mangles real code along the way
(found 2026-11-13, "SyntaxError: Invalid or unexpected token"). The app code is
made ASCII-only and base64-encoded, and a one-line loader runs it, so nothing in
it looks like a comment to Google. Non-ASCII characters are escaped for the same
reason: the Apps Script editor rewrites some of them on paste.

Usage:  python build.py v12      (the label shows under the title while loading)
"""
import base64
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def build(label: str) -> str:
    app = (HERE / "src" / "app.js").read_text(encoding="utf-8")
    shell = (HERE / "src" / "shell.html").read_text(encoding="utf-8")
    app_ascii = "".join(ch if ord(ch) < 128 else "\\u%04x" % ord(ch) for ch in app)
    packed = base64.urlsafe_b64encode(app_ascii.encode("ascii")).decode("ascii")
    if "@@CODE@@" not in shell:
        raise SystemExit("src/shell.html has no @@CODE@@ placeholder")
    html = shell.replace("@@CODE@@", packed).replace("(v4)", f"({label})").replace("page v4", f"page {label}")
    return "".join(ch if ord(ch) < 128 else "&#x%X;" % ord(ch) for ch in html)


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "dev"
    out = HERE / "Index.html"
    out.write_text(build(label), encoding="ascii", newline="\n")
    print(f"wrote {out} ({label})")
