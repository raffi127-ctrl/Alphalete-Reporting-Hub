"""Turn a draft .eml into a browser-previewable .html.

Gmail won't render an .eml you drag in, and the inline `cid:` image
references only resolve inside a mail client — in a browser they show
blank. This walks the message, pulls each related image part, and
rewrites every `cid:<id>` into a `data:<type>;base64,...` URI so the
whole thing renders standalone in any browser."""
from __future__ import annotations

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path


def _collect_images(msg: EmailMessage) -> dict:
    """Map Content-ID (no angle brackets) -> (mime_type, raw_bytes)."""
    images: dict = {}
    for part in msg.walk():
        cid = part.get("Content-ID")
        if not cid or part.get_content_maintype() != "image":
            continue
        key = cid.strip().lstrip("<").rstrip(">")
        images[key] = (part.get_content_type(), part.get_payload(decode=True))
    return images


def _html_body(msg: EmailMessage) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_content()
    raise ValueError("no text/html part found in the message")


def eml_to_html(eml_path: Path, html_path: Path | None = None) -> Path:
    """Write a self-contained .html next to (or at) html_path. Returns it."""
    eml_path = Path(eml_path)
    # policy.default gives EmailMessage instances with a working
    # content_manager (get_content); compat32 (the bare default) does not.
    msg = message_from_bytes(eml_path.read_bytes(), policy=policy.default)
    html = _html_body(msg)
    images = _collect_images(msg)

    for key, (mime, raw) in images.items():
        b64 = base64.b64encode(raw).decode("ascii")
        html = html.replace(f"cid:{key}", f"data:{mime};base64,{b64}")

    out = Path(html_path) if html_path else eml_path.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(eml_to_html(Path(p)))
