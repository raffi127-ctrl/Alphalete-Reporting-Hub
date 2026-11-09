"""Turn a handful of approved photos into a short vertical reel (9:16).

The BIS package sells "reel creation" (Megan 2026-11-09: "this is what we're
trying to replace"). This is the first, automatic version: the week's
approved photos -> one 1080x1920 video, each photo ~2.6 s with a slow zoom,
soft fades between them, the photo letterboxed over a blurred copy of itself
(so a sideways shot never gets its people's heads cropped off).

SOUND: a silent audio track by default -- royalty-free music only if a file
is dropped in the office's music folder (`music` argument). We never pull a
song from anywhere: a reel with somebody else's song on it can get the whole
post (or account) muted.

Uses imageio-ffmpeg's bundled ffmpeg (no system install), so it runs the
same on every Lucy. Pure function: photos in, one .mp4 out.

    python -m automations.brand_audit.reels out.mp4 a.jpg b.jpg c.jpg
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

W, H = 1080, 1920
FPS = 30
SECONDS_EACH = 2.6
FADE = 0.4
MAX_PHOTOS = 8


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def frame_for(photo: Path, out: Path) -> Path:
    """One 1080x1920 still: the photo fitted, over a blurred fill of itself."""
    from PIL import Image, ImageFilter, ImageOps
    img = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    bg = ImageOps.fit(img, (W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.eval(bg, lambda v: int(v * 0.55))          # darken the fill
    fg = ImageOps.contain(img, (W, H))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(out, "JPEG", quality=92)
    return out


def make_reel(photos: List[Path], out: Path, *, music: Optional[Path] = None,
              seconds_each: float = SECONDS_EACH) -> Path:
    """Photos -> out.mp4. Raises with ffmpeg's last lines if it fails."""
    photos = [Path(p) for p in photos][:MAX_PHOTOS]
    if len(photos) < 2:
        raise ValueError("a reel needs at least 2 photos")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = len(photos)
    total = n * seconds_each - (n - 1) * FADE
    frames = int(seconds_each * FPS)
    with tempfile.TemporaryDirectory(prefix="lucy-reel-") as tmp:
        stills = [frame_for(p, Path(tmp) / f"{i}.jpg") for i, p in enumerate(photos)]
        cmd = [_ffmpeg(), "-y", "-loglevel", "error"]
        for s in stills:
            cmd += ["-loop", "1", "-t", f"{seconds_each}", "-i", str(s)]
        if music:
            cmd += ["-i", str(music)]
        else:
            cmd += ["-f", "lavfi", "-t", f"{total}", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100"]
        parts = []
        for i in range(n):
            # slow push-in, alternating direction so it doesn't feel looped
            z = "min(zoom+0.0007,1.08)" if i % 2 == 0 else "if(eq(on,0),1.08,max(zoom-0.0007,1.0))"
            parts.append(f"[{i}:v]scale={int(W*1.1)}:{int(H*1.1)},"
                         f"zoompan=z='{z}':d={frames}:s={W}x{H}:fps={FPS},"
                         f"setsar=1,format=yuv420p[v{i}]")
        prev, offset = "v0", 0.0
        for i in range(1, n):
            offset += seconds_each - FADE
            label = f"x{i}"
            parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration={FADE}:"
                         f"offset={offset:.2f}[{label}]")
            prev = label
        audio = f"[{n}:a]atrim=0:{total:.2f},afade=t=out:st={max(total-1.5,0):.2f}:d=1.5[a]"
        parts.append(audio)
        cmd += ["-filter_complex", ";".join(parts), "-map", f"[{prev}]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "128k", "-shortest",
                "-movflags", "+faststart", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("ffmpeg failed: " + (r.stderr or "")[-400:])
    return out


def main(argv=None) -> int:
    a = list(argv if argv is not None else sys.argv[1:])
    if len(a) < 3:
        print(__doc__)
        return 1
    p = make_reel([Path(x) for x in a[1:]], Path(a[0]))
    print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
