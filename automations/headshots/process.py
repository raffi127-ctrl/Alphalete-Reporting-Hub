"""Turn any posted photo into a clean white-background headshot.

Pipeline (all local, no paid API):
  1. Decode the bytes (HEIC included) and honor the EXIF rotation.
  2. Cut the person out with rembg's people-trained model (u2net_human_seg,
     downloads once to ~/.u2net/).
  3. Crop to head-and-shoulders using the cutout mask itself: the top of the
     mask is the head, and the shoulder line is the first row wide enough to
     BE the shoulders (near the mask's widest point).
     A full-body dress-code-style photo and a chest-up selfie both land on
     the same framing. If the heuristic can't find a sane crop it falls back
     to fitting the whole person.
  4. Center on a pure-white 1200x1500 canvas with breathing room.

One output: the clean headshot. No name bar — the person's name goes in the
FILENAME only (Megan 2026-08-23, "we don't need names added").

Cross-platform: Pillow + rembg only.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from automations.headshots import config

_session = None


FALLBACK_MODEL = "u2net_human_seg"   # small (~170MB); used until the big one lands


def _model_file(name: str) -> Path:
    home = os.environ.get("U2NET_HOME") or str(Path.home() / ".u2net")
    return Path(home) / f"{name}.onnx"


def _ready_marker(name: str) -> Path:
    return _model_file(name).with_suffix(".ready")


def _model_ready(name: str) -> bool:
    """Only a download that FINISHED counts: the background downloader writes
    the .ready marker right after rembg loaded the model. The marker alone is
    the test -- where rembg keeps the .onnx depends on its version (~/.u2net
    on Lucy 3's rembg, ~/.rembg/models on newer ones)."""
    return _ready_marker(name).exists()


def _start_background_download(name: str) -> None:
    """Fetch a big model in its OWN process so no headshot waits on it.

    birefnet-portrait is ~973MB. Downloading it inside the 5-min tick timed
    out on Lucy 3 every run (2026-11-11), so no headshot got processed at all.
    One detached download at a time (lock file holds the downloader's pid)."""
    lock = _model_file(name).with_suffix(".downloading")
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists():
            try:
                pid = int(lock.read_text().strip() or "0")
                os.kill(pid, 0)          # downloader still alive: leave it be
                return
            except (ValueError, OSError):
                pass                     # dead or unreadable: start again
        failed = _model_file(name).with_suffix(".failed")
        if failed.exists() and time.time() - failed.stat().st_mtime < 3600:
            return                       # last try failed: wait an hour
        lock.write_text(str(os.getpid()))
        # A half file left by a killed download looks "present" -- rembg then
        # re-downloads it in the foreground and the tick hangs. Start clean.
        if not _model_ready(name):
            _model_file(name).unlink(missing_ok=True)
        code = ("import pathlib\n"
                "from rembg import new_session\n"
                "try:\n"
                f"    new_session({name!r})\n"
                f"    pathlib.Path({str(_ready_marker(name))!r}).write_text('ok')\n"
                "except Exception:\n"
                f"    pathlib.Path({str(_model_file(name).with_suffix('.failed'))!r}).write_text('x')\n"
                "finally:\n"
                f"    pathlib.Path({str(lock)!r}).unlink(missing_ok=True)\n")
        proc = subprocess.Popen([sys.executable, "-c", code],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        lock.write_text(str(proc.pid))
    except Exception:  # noqa: BLE001 -- the fallback model still works
        pass


def prefetch_model() -> None:
    """Start the big model's background download if it isn't ready yet.
    Called every tick, so it lands BEFORE the next photo arrives instead of
    that photo being the one that kicks it off."""
    name = config.REMBG_MODEL
    if name != FALLBACK_MODEL and not _model_ready(name):
        _start_background_download(name)


def _rembg_session():
    global _session
    if _session is None:
        from rembg import new_session
        name = config.REMBG_MODEL
        if name != FALLBACK_MODEL and not _model_ready(name):
            _start_background_download(name)
            name = FALLBACK_MODEL
        print(f"  cutout model: {name}", flush=True)
        _session = new_session(name)
    return _session


def decode(data: bytes) -> Image.Image:
    """Bytes -> upright RGB image (iPhone HEIC + sideways EXIF handled)."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


def cut_subject(im: Image.Image) -> Image.Image:
    """RGB photo -> RGBA cutout of the person (background alpha = 0)."""
    from rembg import remove
    out = remove(im, session=_rembg_session())
    return out.convert("RGBA")


def _mask_rows(alpha: Image.Image, thresh: int = 40) -> list[tuple[int, int, int]]:
    """Per-row (y, left, right) span of the subject in the alpha channel."""
    import numpy as np
    a = np.asarray(alpha) > thresh
    rows = []
    for y in range(a.shape[0]):
        xs = a[y].nonzero()[0]
        if xs.size:
            rows.append((y, int(xs[0]), int(xs[-1])))
    return rows


def head_shoulders_box(cutout: Image.Image) -> tuple[int, int, int, int] | None:
    """Head-and-shoulders crop box from the subject mask, or None to keep all.

    The head is the top of the mask; scanning down, the shoulder line is the
    first row that reaches most of the subject's full width. Crop ends a bit
    below the shoulders so the frame reads as a badge headshot. A photo that
    is ALREADY head-and-shoulders has its shoulder line far down the mask —
    that returns None on purpose, and the whole subject is kept.
    """
    rows = _mask_rows(cutout.getchannel("A"))
    if len(rows) < 40:
        return None
    top = rows[0][0]
    subj_h = rows[-1][0] - top
    if subj_h <= 0:
        return None

    widths = {y: r - l + 1 for y, l, r in rows}
    ys = sorted(widths)
    w_max = max(widths.values())
    if w_max <= 0:
        return None

    # The shoulders are the subject's WIDEST part, so the shoulder line is the
    # first row that gets near the full width of the mask.
    #
    # This used to measure a "head width" in the top 12% of the subject and
    # call the first row 1.55x wider the shoulders. A top-knot bun broke it
    # (Jordan Jones, 2026-09-28): the band saw only the bun (573px), 1.55x of
    # that is 888px, and her FOREHEAD is 888px — so the crop ended at her
    # eyes and the headshot had no face in it. Any narrow crown — a bun, a
    # ponytail, a cap — did the same thing. Nothing above the shoulders comes
    # close to the shoulders' own width, so this reads the picture instead of
    # guessing a ratio.
    shoulder_y = None
    for y in ys:
        if y <= top + subj_h * 0.05:
            continue
        if widths[y] >= w_max * 0.70:
            shoulder_y = y
            break
    # No flare found inside the top half -> already a tight face crop (or
    # something odd like a hand up) — keep the whole subject.
    if shoulder_y is None or shoulder_y > top + subj_h * 0.55:
        return None

    head_h = shoulder_y - top
    # Head-top to shoulder is roughly a sixth of a standing body and much more
    # of a chest-up photo. Anything under a tenth is the mask widening for
    # some other reason (hair, a hand, a second person) — keep the whole
    # subject rather than cut a face in half.
    if head_h < subj_h * 0.10:
        return None
    bottom = min(rows[-1][0], int(shoulder_y + head_h * 1.05))

    # Horizontal span of what's inside the vertical crop, widened a touch.
    ls = [l for y, l, r in rows if top <= y <= bottom]
    rs = [r for y, l, r in rows if top <= y <= bottom]
    left, right = min(ls), max(rs)
    pad = int((right - left) * 0.06)
    return (max(0, left - pad), top, min(cutout.width, right + pad + 1), bottom)


# ---- the look (Megan 2026-11-10: "bright/clear/good cropping ... a very
# light blue texture background instead of white") --------------------------
def enhance_subject(cutout: Image.Image) -> Image.Image:
    """A clearer person WITHOUT changing who they look like.

    First try (2026-11-10) judged exposure on the whole person: dark clothes
    pulled the average down, the lift washed faces out and lightened skin.
    So: exposure is judged on the FACE band only and capped small (skin tone
    must stay true), contrast is a light touch, then a gentle sharpen.

    The halo: the cutout's edge pixels still carry the original wall (often
    white), which reads as a glowing outline on a coloured backdrop. Pull the
    edge in ~2px, then soften it."""
    import numpy as np
    from PIL import ImageEnhance

    rgb, alpha = cutout.convert("RGB"), cutout.getchannel("A")
    a = np.asarray(alpha) > 128
    if a.sum() < 500:
        return cutout
    ys = np.where(a.any(axis=1))[0]
    top, bot = ys[0], ys[-1]
    face = a.copy()
    face[top + int((bot - top) * 0.32):] = False          # head + face only
    px = np.asarray(rgb).astype(np.float32)
    lum = 0.299 * px[..., 0] + 0.587 * px[..., 1] + 0.114 * px[..., 2]
    fmed = float(np.median(lum[face])) if face.sum() > 200 else float(np.median(lum[a]))
    gain = float(np.clip(150.0 / max(fmed, 1.0), 0.97, 1.12))   # small, capped
    out = Image.fromarray(np.clip(px * gain, 0, 255).astype("uint8"))
    out = ImageEnhance.Contrast(out).enhance(1.05)
    # Light cleanup: a little of a 3px median smooths sensor noise and harsh
    # skin texture without the plastic look; the sharpen after brings eyes,
    # lashes and hair back.
    out = Image.blend(out, out.filter(ImageFilter.MedianFilter(3)), 0.35)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=3))
    out.putalpha(alpha)
    return decontaminate(out)


def decontaminate(cutout: Image.Image) -> Image.Image:
    """Hair and edges without the old wall in them (Megan 2026-11-10: "the
    hair is still weird"). The cutout's half-transparent edge pixels still
    hold the original background's colour -- usually a white wall -- which
    shows as a pale rim. pymatting re-estimates each edge pixel's colour as
    if nothing were behind it. Shrinking the edge instead (the first fix)
    cut hair off."""
    import numpy as np
    try:
        from pymatting import estimate_foreground_ml
    except Exception:  # noqa: BLE001 -- no pymatting: keep the plain cutout
        return cutout
    rgba = np.asarray(cutout).astype(np.float64) / 255.0
    fg = estimate_foreground_ml(rgba[..., :3], rgba[..., 3])
    out = Image.fromarray((np.clip(fg, 0, 1) * 255).astype("uint8"), "RGB")
    out.putalpha(cutout.getchannel("A"))
    return out


def white_balance(original: Image.Image, cutout: Image.Image) -> Image.Image:
    """Take the office light's colour cast out, using the WALL we just cut
    away as the reference: a white/grey wall should read neutral, so whatever
    tint it carries is the lighting's. Only when the wall is bright and plain
    enough to trust, and never more than a 10% nudge per channel."""
    import numpy as np
    a = np.asarray(cutout.getchannel("A"))
    px = np.asarray(original.convert("RGB")).astype(np.float32)
    if px.shape[:2] != a.shape:
        return cutout
    wall = px[a < 10]
    if wall.shape[0] < 5000:
        return cutout
    m = wall.mean(axis=0)
    if m.mean() < 150 or (m.max() - m.min()) / m.mean() > 0.25:
        return cutout                      # dark or colourful wall: no reference
    gains = np.clip(m.mean() / np.maximum(m, 1), 0.9, 1.1)
    rgb = np.asarray(cutout.convert("RGB")).astype(np.float32) * gains
    out = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"))
    out.putalpha(cutout.getchannel("A"))
    return balance_on_person(out)


def balance_on_person(cutout: Image.Image) -> Image.Image:
    """Second pass, on the PERSON (Megan 2026-11-10: "we need to color
    balance more" -- the wall alone moved colours only ~4%).

    The reference is ONLY what should truly be grey: low-saturation pixels
    on the person (grey/white/black clothing, eye whites, teeth). Skin is
    never the reference -- a first try levelled each channel's brightest
    pixels, which on a person in a dark shirt IS skin, and turned faces
    grey-green. Capped at 10% per channel."""
    import numpy as np
    a = np.asarray(cutout.getchannel("A")) > 200
    px = np.asarray(cutout.convert("RGB")).astype(np.float32)
    mx, mn = px.max(axis=2), px.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    lum = px.mean(axis=2)
    neutral = a & (sat < 0.12) & (lum > 45) & (lum < 245)
    if neutral.sum() < 3000:
        return cutout                      # nothing on them is reliably grey
    m = px[neutral].mean(axis=0)
    gains = np.clip(m.mean() / np.maximum(m, 1), 0.9, 1.1)
    out = Image.fromarray(np.clip(px * gains, 0, 255).astype("uint8"))
    out.putalpha(cutout.getchannel("A"))
    return out


def studio_shadow(canvas: Image.Image, subject: Image.Image, at) -> Image.Image:
    """A soft shadow just behind the shoulders, so the person sits IN the
    backdrop instead of floating on it."""
    sh = Image.new("RGBA", subject.size, (60, 75, 100, 0))
    alpha = subject.getchannel("A").point(lambda v: int(v * 0.22))
    sh.putalpha(alpha.filter(ImageFilter.GaussianBlur(28)))
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(sh, (at[0] + 14, at[1] + 18))
    return canvas.convert("RGB")


def studio_background(W: int, H: int, seed: int = 7) -> Image.Image:
    """A very light blue studio backdrop: soft mottled texture, a touch
    brighter behind the head, a touch deeper at the bottom corners."""
    import numpy as np

    rng = np.random.default_rng(seed)

    def mottle(cells, blur):
        """Tiny noise blown up + blurred = soft cloudy patches, -0.5..0.5."""
        small = rng.normal(0, 1, cells).astype(np.float32)
        im = Image.fromarray(((small - small.min()) / (np.ptp(small) or 1)
                              * 255).astype("uint8"))
        return np.asarray(im.resize((W, H), Image.BICUBIC)
                          .filter(ImageFilter.GaussianBlur(blur))
                          ).astype(np.float32) / 255 - 0.5
    # "lighter blue and more textured" (Megan 2026-11-10): big soft clouds
    # plus a finer layer of mottle, like a painted studio backdrop.
    mott = mottle((9, 7), 60) * 1.0 + mottle((36, 28), 12) * 0.7 \
        + mottle((120, 96), 3) * 0.25
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # Glow centered where the head sits (upper third), falling off outward.
    d = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.33) / H) ** 2)
    light = 1.0 - np.clip(d * 0.9, 0, 0.45)
    base = np.array([238, 244, 252], np.float32)      # very light blue
    edge = np.array([222, 233, 247], np.float32)      # a shade deeper
    img = edge + (base - edge) * light[..., None]
    img = img + mott[..., None] * np.array([30, 26, 16], np.float32)  # texture
    img = img + rng.normal(0, 1.6, (H, W, 1))          # fine grain, no banding
    return Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "RGB")


def compose_clean(cutout: Image.Image) -> Image.Image:
    """Cutout -> the person centered on a pure-white portrait canvas."""
    box = head_shoulders_box(cutout)
    if box:
        cutout = cutout.crop(box)
    else:
        bbox = cutout.getchannel("A").getbbox()
        if bbox:
            cutout = cutout.crop(bbox)

    W, H = config.PHOTO_W, config.PHOTO_H
    margin = config.HEAD_MARGIN
    # Fill the frame TOP to bottom (white margin above the head only), then
    # center the width on the head. Shoulders running off the sides is normal
    # badge framing; empty sky above the head is not.
    avail_h = H * (1 - margin)
    scale = avail_h / cutout.height
    sized = cutout.resize((max(1, round(cutout.width * scale)),
                           max(1, round(cutout.height * scale))),
                          Image.LANCZOS)

    # Head center = midpoint of the mask in the top 15% of the subject.
    rows = _mask_rows(sized.getchannel("A"))
    top_band = [r for r in rows if r[0] <= rows[0][0] + sized.height * 0.15] \
        if rows else []
    head_cx = (sum((l + r) / 2 for _, l, r in top_band) / len(top_band)) \
        if top_band else sized.width / 2

    if getattr(config, "BACKGROUND", "white") == "blue":
        sized = enhance_subject(sized)
        canvas = studio_background(W, H)
    else:
        canvas = Image.new("RGB", (W, H), "white")
    x = round(W / 2 - head_cx)
    x = min(0, max(x, W - sized.width)) if sized.width > W \
        else max(0, min(x, W - sized.width))
    if getattr(config, "BACKGROUND", "white") == "blue":
        canvas = studio_shadow(canvas, sized, (x, H - sized.height))
    canvas.paste(sized, (x, H - sized.height), sized)
    return canvas


def process(data: bytes) -> Image.Image:
    """Photo bytes -> finished white-background headshot."""
    im = decode(data)
    cut = cut_subject(im)
    if getattr(config, "BACKGROUND", "white") == "blue":
        cut = white_balance(im, cut)
    return compose_clean(cut)
