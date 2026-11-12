"""Highlight each owner's own row on the tracker images we send to THEM.

Rafael 2026-11-12 ("Highlighted trackers"): "When we post a tracker on these
guys' Slacks, can we also get their names highlighted on whatever tracker that
they're on?" First scoped to Lucy Eco owners; Megan 2026-11-12 widened it:
"we can do it for all 38 ICDs we post to" (Eve: "Yes!").

HOW IT WORKS (no OCR install needed — runs the same on Mac and Windows):
  1. rows_of(png)  — Tableau tables draw a grey rule under every row, so the
     row bands come straight off the pixels: a horizontal run of grey that is
     long and unbroken is a rule, a run of text is not.
  2. the image goes to Claude ONCE per tracker per day with a small red number
     drawn in the left margin of every band. Claude answers "which numbered
     band has each of these names" and quotes the text it read there.
  3. the quoted text must match the owner (letters only, or an alias) or the
     answer is thrown away. A wrong row is worse than no row.
  4. highlighted copy = the band tinted yellow (multiply, so the numbers stay
     readable), written next to the original as <name>__hl_<key>.png.

NEVER BLOCKS A POST. Any failure — no API key, Claude down, name not on the
board, ambiguous match — returns the ORIGINAL png and the post goes out exactly
as it did before this file existed.

Who gets it: EVERY owner row in onboarded_trackers.json — their Slack
channel, or their email for the rows delivered by mail. Shared channels
(#alphalete-sales, org channels) never get a highlight: no one owner.

  python -m automations.tableau_screenshots.highlight <png> "Starr Rodenhurst"
      -> writes the highlighted copy, prints where. Preview tool.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
import sys
from pathlib import Path

MODEL = "claude-sonnet-5"

# OFF until Eve OKs the preview ("preview before rollout"). While False only a
# run with --highlight (run.py) paints anything; flip to True to go live in
# every owner's channel and email.
LIVE = False
FORCE = False            # set by run.py --highlight


# Row-rule detection. A rule is grey (not white, not black text) and long.
_GREY_MAX = 248          # lighter than this is background (Quantum/VZ rules are ~242)
_GREY_MIN = 90           # darker than this is text, not a rule
_MIN_RULE_PX = 180       # a solid grey run at least this wide is a rule
_INK = 110                # darker than this is text
_RULE_RUN = 40           # ink wider than this in one stroke is a rule
_RULE_INK = 215          # rules are drawn lighter than text
_MIN_TEXT_PX = 5         # shorter ink runs are rules / specks
_MAX_TEXT_PX = 16        # one line of text is never taller than this
_MAX_CELL_PX = 34        # two-line cells (NDS: name + [city]) — taller is a title bar/logo
_EDGE = 5                # how much darker than above/below a rule is
_GAP = 3                 # off-grey pixels a rule may cross (cell borders)
_MIN_BAND_PX = 8         # rows shorter than this are double rules, not rows
_MAX_BAND_PX = 40        # taller than this is a header / chart, not a row
_MARGIN = 34             # white strip added on the left for the band numbers

HL_COLOR = (255, 236, 64)   # highlighter yellow


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


# --------------------------------------------------------------------------- rows
def _rules(im) -> list:
    """[(y, [(x0, x1), ...])] — every horizontal grey rule and the segments it
    spans (two tables side by side = two segments). Adjacent y's merged."""
    g = im.convert("L")
    W, H = g.size
    px = g.load()
    hits = []
    for y in range(H):
        # A rule is crossed by the dark vertical cell borders every column, so
        # a few off-grey pixels do not end it; a gap wider than _GAP does.
        # Text rows also chain grey anti-aliasing, so a run must be DENSE
        # (>= 90% grey) to count — a rule is solid, a line of text is not.
        segs = []
        start = last = -1
        n = 0

        def close():
            if start >= 0 and last - start + 1 >= _MIN_RULE_PX                     and n >= 0.9 * (last - start + 1):
                segs.append((start, last))
        up, dn = max(0, y - 2), min(H - 1, y + 3)
        for x in range(W):
            v = px[x, y]
            # A RULE is thin: darker than the pixels 2 above and 3 below (a
            # 1-2px line). Plain light-grey row shading is not, so banded
            # tables do not read as one solid block.
            if (_GREY_MIN <= v <= _GREY_MAX and v <= px[x, up] - _EDGE
                    and v <= px[x, dn] - _EDGE):
                if start < 0 or x - last > _GAP:
                    close()
                    start, n = x, 0
                last = x
                n += 1
        close()
        if segs:
            hits.append((y, segs))
    merged = []
    for y, segs in hits:
        if merged and y - merged[-1][0] <= 2:
            merged[-1] = (y, _union(merged[-1][1] + segs))
        else:
            merged.append((y, segs))
    return merged


def _union(segs: list) -> list:
    out = []
    for a, b in sorted(segs):
        if out and a <= out[-1][1] + _GAP:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _overlap(top: list, bot: list) -> list:
    """Segments present in BOTH rules — the cells this row actually has."""
    out = []
    for a0, a1 in top:
        for b0, b1 in bot:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo >= _MIN_RULE_PX // 2:
                out.append((lo, hi))
    return out


def rows_of(im) -> list:
    """[(top, bottom, [(x0, x1)])] — one band per LINE OF TEXT, top to bottom.

    Text lines, not grid rules: every tracker prints its names as dark text,
    but the rules differ per board (solid grey, ~242 near-white on Quantum,
    none at all on the Fios/VZ board). A line of text is a run of y's that
    have dark pixels; the band reaches halfway into the gap on each side so
    the yellow covers the whole cell."""
    import numpy as np
    a = np.asarray(im.convert("L")) < _INK
    H, W = a.shape
    # Vertical cell borders are ink on every y of a table and would glue all
    # rows into one. Drop any ink that is part of a vertical run taller than
    # a line of text could be.
    run = np.zeros_like(a, dtype=np.int32)
    for y in range(H):
        run[y] = np.where(a[y], (run[y - 1] + 1) if y else 1, 0)
    tall = np.zeros_like(a)
    for y in range(H - 1, -1, -1):
        nxt = tall[y + 1] if y + 1 < H else np.zeros(W, dtype=bool)
        tall[y] = a[y] & ((run[y] > _MAX_TEXT_PX) | nxt)
    # Same for HORIZONTAL rules: on tight boards the rule under a row is
    # dark enough in places to read as ink and glues it to the next row. A
    # rule is a THIN, long grey stroke: _RULE_RUN+ px of not-white on one y
    # with mostly white just above or just below. Letters are never that.
    g = np.asarray(im.convert("L"))
    loose = g < _RULE_INK
    wide = np.zeros_like(a)
    for y in range(H):
        row = loose[y]
        if row.sum() < _RULE_RUN:
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        for x0, x1 in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            if x1 - x0 < _RULE_RUN:
                continue
            above = loose[max(0, y - 1), x0:x1].mean()
            below = loose[min(H - 1, y + 1), x0:x1].mean()
            if min(above, below) < 0.5:
                wide[y, x0:x1] = True
    a &= ~(tall | wide)
    ink = []
    for y in range(H):
        xs = np.flatnonzero(a[y])
        ink.append((int(xs[0]), int(xs[-1])) if len(xs) >= 2 else None)
    runs, y = [], 0
    while y < H:
        if ink[y] is None:
            y += 1
            continue
        y0 = y
        while y < H and ink[y] is not None:
            y += 1
        runs.append((y0, y - 1))
    out = []
    for i, (t, b) in enumerate(runs):
        h = b - t + 1
        if not (_MIN_TEXT_PX <= h <= _MAX_CELL_PX):
            continue
        prev_b = runs[i - 1][1] if i else max(0, t - 4)
        next_t = runs[i + 1][0] if i + 1 < len(runs) else min(H - 1, b + 4)
        top = max(t - 4, (prev_b + t + 1) // 2)
        bot = min(b + 4, (b + next_t) // 2)
        x0 = min(ink[yy][0] for yy in range(t, b + 1))
        x1 = max(ink[yy][1] for yy in range(t, b + 1))
        out.append((top, bot, [(max(0, x0 - 6), min(W - 1, x1 + 6))]))
    return out


def numbered(im, bands: list):
    """Copy with a white left margin and the band number beside each band."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = im.size
    canvas = Image.new("RGB", (W + _MARGIN, H), "white")
    canvas.paste(im.convert("RGB"), (_MARGIN, 0))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=11)
    except TypeError:          # Pillow < 10.1
        font = ImageFont.load_default()
    for i, (top, bot, _segs) in enumerate(bands, 1):
        d.text((2, top + max(0, (bot - top - 11) // 2)), str(i),
               fill=(220, 0, 0), font=font)
    return canvas


def paint(im, band):
    """The image with one band tinted highlighter-yellow (text stays readable)."""
    from PIL import Image, ImageChops
    top, bot, segs = band
    out = im.convert("RGB").copy()
    for x0, x1 in segs:
        region = out.crop((x0, top, x1 + 1, bot))
        tint = Image.new("RGB", region.size, HL_COLOR)
        out.paste(ImageChops.multiply(region, tint), (x0, top))
    return out


# ------------------------------------------------------------------------ claude
_SCHEMA = {
    "type": "object",
    "properties": {"found": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"},
                       "band": {"type": "integer"},
                       "text_read": {"type": "string"}},
        "required": ["name", "band", "text_read"],
        "additionalProperties": False}}},
    "required": ["found"], "additionalProperties": False}

_PROMPT = """This is a sales tracker table. Every table row has a small RED number
in the left margin (the band number). For each person below, find the row whose
owner / ICD name column shows that person, and return its red band number and
the name text exactly as printed in that row. Names are often ALL CAPS and may
be shortened. Only return a person if you are sure; leave them out otherwise.
If a person appears in more than one table, return each row.

People:
{people}"""


def _ask(img, people: dict) -> list:
    import anthropic
    from automations.brand_audit import credentials
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    plist = "\n".join(f"- {k}: {', '.join(v)}" for k, v in people.items())
    # Short leash: this rides a run that already brushes its 30-min cap.
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key(),
                                 timeout=90, max_retries=1)
    resp = client.messages.create(
        model=MODEL, max_tokens=4000,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": base64.standard_b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": _PROMPT.format(people=plist)}]}])
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text).get("found", [])


def _matches(text_read: str, spellings: list) -> bool:
    t = norm(text_read)
    if not t:
        return False
    for s in spellings:
        n = norm(s)
        # Tableau truncates long names ('CHRISTOPHER HU..'), so a read that is
        # a clean prefix of 8+ letters of the full name also counts.
        if t == n or (len(t) >= 8 and n.startswith(t)):
            return True
        # A one-word owner row ('Haytham') against the board's full name
        # ('HAYTHAM NAGI').
        if " " not in s.strip() and len(n) >= 5 and t.startswith(n):
            return True
    return False


def locate(png: Path, people: dict, cache_dir: Path | None = None) -> dict:
    """{key: [band, ...]} for every person found on this image.

    `people` = {key: [spellings]}. One Claude call for all of them; the answer
    is cached next to the image (keyed by the image bytes) so a retry or a
    --replace run never pays twice."""
    from PIL import Image
    im = Image.open(png)
    bands = rows_of(im)
    if not bands or not people:
        return {}
    digest = hashlib.sha1(Path(png).read_bytes()).hexdigest()[:16]
    want = hashlib.sha1(json.dumps(people, sort_keys=True).encode()).hexdigest()[:8]
    cache = (cache_dir or Path(png).parent) / f".hl_{Path(png).stem}_{digest}_{want}.json"
    if cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            return {k: [(t, b, [tuple(x) for x in sg]) for t, b, sg in v]
                    for k, v in raw.items()}
        except Exception:   # noqa: BLE001
            pass
    found = _ask(numbered(im, bands), people)
    out: dict = {}
    for f in found:
        k, i = f.get("name", ""), int(f.get("band") or 0)
        if k not in people or not (1 <= i <= len(bands)):
            continue
        if not _matches(f.get("text_read", ""), people[k]):
            print(f"   highlight: {k} -> band {i} read "
                  f"{f.get('text_read')!r}, not a match - skipped", flush=True)
            continue
        out.setdefault(k, []).append(bands[i - 1])
    try:
        cache.write_text(json.dumps(out), encoding="utf-8")
    except Exception:   # noqa: BLE001
        pass
    return out


def highlighted(png: Path, key: str, bands: list) -> Path:
    """Write (once) and return the copy of `png` with `bands` painted."""
    from PIL import Image
    png = Path(png)
    dest = png.with_name(f"{png.stem}__hl_{key}{png.suffix}")
    im = Image.open(png)
    for b in bands:
        im = paint(im, b)
    im.save(dest)
    return dest


# ------------------------------------------------------------------ who gets it
def spellings(owner: str) -> list:
    """The owner's name plus every alias the ICD Aliases sheet knows."""
    out = [owner]
    try:
        from automations.focus_office_att import aliases as A
        for canon, als in (A.load_aliases() or {}).items():
            als = [als] if isinstance(als, str) else list(als or [])
            if norm(owner) in {norm(canon), *map(norm, als)}:
                out += [canon, *als]
    except Exception:   # noqa: BLE001
        pass
    seen, uniq = set(), []
    for s in out:
        if s and norm(s) not in seen:
            seen.add(norm(s))
            uniq.append(s)
    return uniq


def channel_owners(rows: list) -> dict:
    """{channel_id: owner} for every Slack row in onboarded_trackers. Shared
    channels (ORG_CHANNELS) are not rows there, so they are never here."""
    out = {}
    for r in rows:
        owner = (r.get("owner") or "").strip()
        if not owner:
            continue
        for c in r.get("channel_ids") or []:
            out[c] = owner
    return out


class Highlighter:
    """One per run: decides per channel which png to upload. Never raises."""

    def __init__(self, rows: list | None = None):
        self._by_channel: dict | None = None
        self._owners: set = set()
        self._rows = rows
        self._located: dict = {}   # png path -> {owner: bands}

    def _channels(self) -> dict:
        if self._by_channel is None and not (LIVE or FORCE):
            self._by_channel = {}
        if self._by_channel is None:
            try:
                rows = self._rows
                if rows is None:
                    p = Path(__file__).with_name("onboarded_trackers.json")
                    rows = json.loads(p.read_text(encoding="utf-8"))
                self._rows = rows
                self._by_channel = channel_owners(rows)
                self._owners = {(r.get("owner") or "").strip() for r in rows
                                if (r.get("owner") or "").strip()}
                print(f"   highlight: on for {len(self._owners)} owner(s)",
                      flush=True)
            except Exception as e:   # noqa: BLE001
                print(f"   highlight: off ({type(e).__name__}: {e})", flush=True)
                self._by_channel = {}
        return self._by_channel

    def owner_for_org(self, org: str) -> str:
        """The owner behind an onboarded org key ('starr'), or ''."""
        rows = self._rows
        if rows is None:
            try:
                p = Path(__file__).with_name("onboarded_trackers.json")
                rows = json.loads(p.read_text(encoding="utf-8"))
            except Exception:   # noqa: BLE001
                return ""
        self._channels()
        for r in rows:
            if r.get("key") == org and r.get("owner") in self._owners:
                return r["owner"]
        return ""

    def png_for(self, channel: str, png, spec: dict | None = None):
        return self.png_for_owner(self._channels().get(channel, ""), png, spec)

    def png_for_owner(self, owner: str, png, spec: dict | None = None):
        if not owner or self._by_channel == {}:
            return png
        try:
            key = str(png)
            if key not in self._located:
                people = {o: spellings(o) for o in sorted(self._owners)}
                self._located[key] = locate(Path(png), people)
            bands = self._located[key].get(owner)
            if not bands:
                return png
            out = highlighted(Path(png), norm(owner), bands)
            print(f"   highlight: {owner} on {(spec or {}).get('id', Path(png).name)}"
                  f" ({len(bands)} row(s))", flush=True)
            return out
        except Exception as e:   # noqa: BLE001
            # One failure (no key, Claude down) turns it off for the rest of
            # the run, so nine boards never each wait out the same timeout.
            print(f"   highlight: {owner} skipped ({type(e).__name__}: {e})"
                  f" - highlights off for this run", flush=True)
            self._by_channel, self._owners = {}, set()
            return png


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__)
        return 2
    png, names = Path(argv[0]), argv[1:]
    people = {n: spellings(n) for n in names}
    hits = locate(png, people)
    for n in names:
        if hits.get(n):
            print(f"{n}: rows {hits[n]} -> {highlighted(png, norm(n), hits[n])}")
        else:
            print(f"{n}: not found on {png.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
