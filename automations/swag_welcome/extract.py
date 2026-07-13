"""Screenshot → roster rows, via Claude vision.

The team drops in a screenshot of a table with Name / Last Name / Phone
columns (colored text, quoted pronunciation/nickname bits, mixed phone
formats). Local OCR (Tesseract) chokes on colored cells and quote marks, so
we hand the image to Claude — the same pattern brand_audit/design_review.py
already uses — and ask for structured rows. Phone normalization and
quoted-name splitting then happen deterministically in roster.py, NOT here,
so the fragile vision step only has to read pixels, not make decisions.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from automations.brand_audit import credentials

MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The exact text of the first-name (Name) "
                        "cell, INCLUDING any quoted part verbatim, e.g. "
                        "'Davone \"Day VEON\"' or 'Jose Angel'.",
                    },
                    "last_name": {"type": "string"},
                    "phone": {
                        "type": "string",
                        "description": "The phone cell text exactly as shown, "
                        "digits/dashes and all — do NOT reformat.",
                    },
                },
                "required": ["name", "phone"],
            },
        }
    },
    "required": ["rows"],
}

_PROMPT = (
    "This is a screenshot of a new-hire roster table with three columns: "
    "Name (first name), Last Name, and Phone. Read every data row top to "
    "bottom and return them in order.\n\n"
    "Rules:\n"
    "- Copy the Name cell EXACTLY, including anything in quotes (e.g. "
    "'Auryn \"RN\"'). Do not strip or interpret the quotes — a human decides "
    "later whether a quoted part is a pronunciation or a nickname.\n"
    "- Copy the Phone cell exactly as printed; keep all digits and any dashes. "
    "Do not add or drop a leading 1.\n"
    "- Include a row even if a cell looks unusual; never invent or skip rows.\n"
    "- Ignore the header row and any filter icons."
)


def _image_block(image_path: str | Path) -> dict:
    path = Path(image_path)
    data = path.read_bytes()
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode(),
        },
    }


def extract_rows(image_path: str | Path) -> list[dict]:
    """Return [{'name': ..., 'last_name': ..., 'phone': ...}, ...] read off the
    screenshot. Raises with a clear message if the API key isn't configured."""
    import anthropic

    content = [_image_block(image_path), {"type": "text", "text": _PROMPT}]
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)
    return data.get("rows", [])
