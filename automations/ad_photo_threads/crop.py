"""Cut a group-call screenshot down to the candidate(s) from THIS ad.

Raf 2026-09-21: "Screenshots have photos of multiple candidates that don't
belong in from the ad of the thread" — each 1st-round slot is one group Zoom,
so the raw screenshot shows everybody in the slot, whatever ad they came from.
Zoom labels every tile with the person's name, so Claude is handed the
screenshot plus the names we want and returns each one's tile; we cut those
out with Pillow and post only them.

Anything that goes wrong (no API key, model can't find the name, a box that
makes no sense) returns None for that name and the caller posts the full
screenshot instead, exactly as before — a missing crop must never cost the
day's photos.

Crops are cached under output/ad_photo_threads/crops/ by (Slack file id, name)
so a re-run doesn't pay for the same screenshot twice.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO / "output" / "ad_photo_threads" / "crops"
MODEL = "claude-opus-5"
MAX_EDGE = 1568          # the model sees images at most this long; send that
PAD = 0.04               # grow each tile a little so the name label isn't clipped
MIN_SIDE = 0.06          # a "tile" thinner than 6% of the image is a misread

_SYSTEM = (
    "You locate people in screenshots of Zoom video calls. Each participant "
    "is shown in a tile (a rectangle with their video or profile picture) and "
    "Zoom writes the participant's display name inside the tile, usually in "
    "the bottom-left corner. You are given the image size and a list of "
    "names. For each name, find the tile whose label matches it and return "
    "that whole tile's rectangle in pixel coordinates of the image as given "
    "(x0,y0 = top-left, x1,y1 = bottom-right), covering the full tile "
    "including its name label. Match leniently: a first name alone, a last "
    "name alone, a nickname, a missing accent or a typo still counts when it "
    "clearly points to that person and to no other tile. If the label is a "
    "phone number, blank, or could be more than one person, set found=false. "
    "Never return a rectangle for a name you did not actually see.")

_SCHEMA = {
    "type": "object",
    "properties": {
        "tiles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "found": {"type": "boolean"},
                    "label_seen": {"type": "string"},
                    "x0": {"type": "integer"}, "y0": {"type": "integer"},
                    "x1": {"type": "integer"}, "y1": {"type": "integer"},
                },
                "required": ["name", "found", "label_seen",
                             "x0", "y0", "x1", "y1"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tiles"],
    "additionalProperties": False,
}


def _cache_path(file_id: str, name: str) -> Path:
    h = hashlib.sha1(f"{file_id}|{name.lower().strip()}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{file_id or 'img'}_{h}.png"


def _ask(img_bytes: bytes, media_type: str, size: Tuple[int, int],
         names: List[str], client=None) -> List[dict]:
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    w, h = size
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type,
                "data": base64.standard_b64encode(img_bytes).decode("ascii")}},
            {"type": "text", "text":
                f"Image size: {w} x {h} pixels.\nNames to find:\n"
                + "\n".join(f"- {n}" for n in names)},
        ]}])
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"model stopped: {resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text).get("tiles") or []


def _box(t: dict, w: int, h: int) -> Optional[Tuple[int, int, int, int]]:
    """Sanity-check and pad the model's rectangle; None if it's not a tile."""
    x0, y0, x1, y1 = (int(t.get(k) or 0) for k in ("x0", "y0", "x1", "y1"))
    x0, x1 = sorted((max(0, min(w, x0)), max(0, min(w, x1))))
    y0, y1 = sorted((max(0, min(h, y0)), max(0, min(h, y1))))
    if (x1 - x0) < MIN_SIDE * w or (y1 - y0) < MIN_SIDE * h:
        return None
    px, py = int((x1 - x0) * PAD), int((y1 - y0) * PAD)
    return (max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py))


def crop_names(data: bytes, names: List[str], file_id: str = "",
               client=None) -> Dict[str, Optional[bytes]]:
    """{name: PNG bytes of that person's tile, or None = post the full shot}."""
    from PIL import Image

    out: Dict[str, Optional[bytes]] = {}
    todo = []
    for n in names:
        p = _cache_path(file_id, n)
        if file_id and p.exists():
            out[n] = p.read_bytes()
        else:
            todo.append(n)
    if not todo:
        return out
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGB")
        scale = min(1.0, MAX_EDGE / max(img.size))
        small = img if scale >= 1.0 else img.resize(
            (round(img.width * scale), round(img.height * scale)))
        buf = io.BytesIO()
        small.save(buf, "PNG")
        tiles = _ask(buf.getvalue(), "image/png", small.size, todo, client)
    except Exception as e:                         # noqa: BLE001 — full shot instead
        print(f"  crop skipped ({type(e).__name__}: {str(e)[:120]})")
        for n in todo:
            out[n] = None
        return out

    by_name = {str(t.get("name", "")).strip().lower(): t for t in tiles}
    for n in todo:
        t = by_name.get(n.strip().lower())
        box = _box(t, small.width, small.height) if t and t.get("found") else None
        if not box:
            out[n] = None
            continue
        full = tuple(round(v / scale) for v in box)
        # A "tile" that is basically the whole screenshot is no crop at all.
        if (full[2] - full[0]) * (full[3] - full[1]) > 0.85 * img.width * img.height:
            out[n] = None
            continue
        buf = io.BytesIO()
        img.crop(full).save(buf, "PNG")
        out[n] = buf.getvalue()
        if file_id:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(file_id, n).write_bytes(out[n])
    return out
