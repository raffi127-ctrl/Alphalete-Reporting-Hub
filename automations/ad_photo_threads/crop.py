"""Cut a group-call screenshot down to the candidate(s) from THIS ad.

Raf 2026-09-21: "Screenshots have photos of multiple candidates that don't
belong in from the ad of the thread" — each 1st-round slot is one group Zoom,
so the raw screenshot shows everybody in the slot, whatever ad they came from.
Zoom labels every tile with the person's name, so Claude is handed the
screenshot plus the names we want and returns each one's tile; we cut those
out with Pillow and post only them.

A name the model can't find on any tile (Zoom showed a phone number, a
nickname, camera off) comes back EMPTY and the caller posts NO photo for that
person, with a "No photo" line instead (Eve 9/21: never show candidates from
other ads). A tile that fills the whole screenshot comes back as the whole
screenshot — it IS that person. If Claude can't be reached at all, this
RAISES: the night's post waits for the next tick rather than going out with
no photos.

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
# Sonnet since 9/24 (Eve, after a side-by-side on 15 of Raf's 9/23 shots:
# "la gran mayoría se ve bien"): a fraction of Opus's cost, which ran the
# API balance dry in two days of bulk loads. Haiku was tried first and cut
# the wrong tile. If anyone complains about a crop, go back to Opus:
# MODEL = "claude-opus-5"
MODEL = "claude-sonnet-5"
# The cheaper model on trial (Eve 9/24: the API balance ran out after two days
# of bulk loads). `--compare-crop` puts its crops next to MODEL's cached ones.
CHEAP_MODEL = "claude-haiku-4-5-20251001"
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
        # Every tile label on the screenshot — only for the run log, so a
        # "not visible" can be told apart from a name Zoom spelled otherwise.
        "all_labels": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tiles", "all_labels"],
    "additionalProperties": False,
}


def _cache_path(file_id: str, name: str) -> Path:
    h = hashlib.sha1(f"{file_id}|{name.lower().strip()}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{file_id or 'img'}_{h}.png"


def _ask(img_bytes: bytes, media_type: str, size: Tuple[int, int],
         names: List[str], client=None,
         aliases: Optional[Dict[str, List[str]]] = None,
         model: Optional[str] = None) -> dict:
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    w, h = size
    resp = client.messages.create(
        model=model or MODEL, max_tokens=4000, system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type,
                "data": base64.standard_b64encode(img_bytes).decode("ascii")}},
            {"type": "text", "text":
                f"Image size: {w} x {h} pixels.\nNames to find (return each "
                "under the name before any parentheses):\n"
                + "\n".join(f"- {n}" + (f" (may also appear as: "
                                        f"{', '.join((aliases or {})[n])})"
                                        if (aliases or {}).get(n) else "")
                            for n in names)
                + "\nAlso list every tile label you can read in all_labels."},
        ]}])
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"model stopped: {resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text)


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
               client=None, aliases: Optional[Dict[str, List[str]]] = None,
               model: Optional[str] = None, use_cache: bool = True
               ) -> Dict[str, bytes]:
    """{name: PNG of that person's tile, or b"" = not on this screenshot}.
    `model`/`use_cache=False`: a trial run that neither reads nor writes the
    cache the live report uses."""
    from PIL import Image

    out: Dict[str, bytes] = {}
    todo = []
    for n in names:
        p = _cache_path(file_id, n)
        if use_cache and file_id and p.exists():
            out[n] = p.read_bytes()
        else:
            todo.append(n)
    if not todo:
        return out
    img = Image.open(io.BytesIO(data))
    img.load()
    img = img.convert("RGB")
    scale = min(1.0, MAX_EDGE / max(img.size))
    small = img if scale >= 1.0 else img.resize(
        (round(img.width * scale), round(img.height * scale)))
    buf = io.BytesIO()
    small.save(buf, "PNG")
    got = _ask(buf.getvalue(), "image/png", small.size, todo, client, aliases,
               model=model)
    tiles = got.get("tiles") or []

    by_name = {str(t.get("name", "")).strip().lower(): t for t in tiles}
    for n in todo:
        t = by_name.get(n.strip().lower())
        box = _box(t, small.width, small.height) if t and t.get("found") else None
        if not box:
            out[n] = b""
            print(f"  crop: {n!r} not found on {file_id or 'shot'}; labels seen: "
                  f"{', '.join(got.get('all_labels') or []) or '(none)'}")
            continue
        full = tuple(round(v / scale) for v in box)
        # A tile that is basically the whole screenshot: the shot is just them.
        if (full[2] - full[0]) * (full[3] - full[1]) > 0.85 * img.width * img.height:
            full = (0, 0, img.width, img.height)
        buf = io.BytesIO()
        img.crop(full).save(buf, "PNG")
        out[n] = buf.getvalue()
        if file_id and use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(file_id, n).write_bytes(out[n])
    return out


def compare(rep, user: str, limit: int = 15, model: str = CHEAP_MODEL,
            cl=None) -> Dict[str, int]:
    """Trial (Eve 9/24): for up to `limit` candidates of the day whose crop
    is already cached (made by MODEL), crop the same screenshot with `model`
    and DM `user` both, side by side. The cached crop costs nothing; only
    `model`'s calls are billed."""
    from automations.ad_photo_threads import collect
    from automations.sara_down.run import _download_image
    cl = cl or collect._client()
    dm = cl.conversations_open(users=user)["channel"]["id"]
    cl.chat_postMessage(channel=dm, text=(
        f"*Crop trial — {rep.day:%a} {rep.day.month}/{rep.day.day}*\n"
        f"Each pair: first = today's crop ({MODEL}), second = {model}."))
    counts = {"pairs": 0, "same_found": 0, "cheap_missed": 0, "cheap_extra": 0}
    for c in rep.candidates:
        if counts["pairs"] >= limit:
            break
        f = next((f for f in c.images if _cache_path(f.get("id", ""), c.name).exists()), None)
        if not f:
            continue
        old = _cache_path(f["id"], c.name).read_bytes()
        data, _ = _download_image(f)
        new = crop_names(data, [c.name], f["id"], aliases={c.name: c.alt_names},
                         model=model, use_cache=False).get(c.name, b"")
        counts["pairs"] += 1
        if old and new:
            counts["same_found"] += 1
        elif old and not new:
            counts["cheap_missed"] += 1
        elif new and not old:
            counts["cheap_extra"] += 1
        files = [{"content": old, "filename": f"{c.name} - {MODEL}.png"}] if old else []
        if new:
            files.append({"content": new, "filename": f"{c.name} - {model}.png"})
        note = f"{c.name}" + ("" if new else f" — {model} did NOT find them")
        if files:
            cl.files_upload_v2(channel=dm, file_uploads=files, initial_comment=note)
        else:
            cl.chat_postMessage(channel=dm, text=note)
    cl.chat_postMessage(channel=dm, text=(
        f"Done: {counts['pairs']} pairs · both found {counts['same_found']} · "
        f"{model} missed {counts['cheap_missed']} · found extra {counts['cheap_extra']}"))
    return counts
