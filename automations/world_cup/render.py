"""Render bracket HTML to PDF with patchright's bundled headless Chromium.

Replaces the handoff `make-flyers.sh`, which shelled out to Mac-only Chrome
(`/Applications/Google Chrome.app/...`). patchright is already a repo
dependency and ships its own Chromium; `page.pdf()` works headless on Windows
(verified 2026-06-10). No system Chrome required.

`prefer_css_page_size=True` honors the HTML's `@page { size: Letter; margin }`,
and `print_background=True` keeps the gold/green/grey row fills (the HTML sets
`print-color-adjust: exact`) — same output as Chrome's --print-to-pdf.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from patchright.sync_api import sync_playwright


def render_pdfs(items: Iterable[Tuple[str, Path]], verbose: bool = True) -> None:
    """Render each (html_string, out_pdf_path) to PDF in one headless Chromium
    session. Loads HTML via set_content — the bracket HTML is fully self-
    contained (inline CSS, no external images), so no file:// or network."""
    items = list(items)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for html_str, out_pdf in items:
                out_pdf.parent.mkdir(parents=True, exist_ok=True)
                page = browser.new_page()
                page.set_content(html_str, wait_until="load")
                page.pdf(
                    path=str(out_pdf),
                    prefer_css_page_size=True,
                    print_background=True,
                )
                page.close()
                if verbose:
                    print(f"  Rendered PDF: {out_pdf} "
                          f"({out_pdf.stat().st_size:,} bytes)", flush=True)
        finally:
            browser.close()
