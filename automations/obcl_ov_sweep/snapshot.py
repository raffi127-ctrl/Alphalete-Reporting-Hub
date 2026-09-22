"""The hourly OBCL picture for the ORIENTATION CREW group (Megan 2026-09-21).

After a live pass: draw this week's chart as a PNG and, ONLY IF something on it
changed since the last picture sent, queue it for the mini_control poller to
text to "ORIENTATION CREW - Real". "A change MUST have happened" — so the
comparison is on what the picture shows (every cell value + colour), and the
very first pass only records a baseline.

Who's in it: this week's chart, people with a Location AND a Final Status of
at least "Showed Up To CR" (anything filled that isn't quit / no-show / etc.).

Why the poller sends it and not this process: macOS grants "control Messages"
per responsible process. The Lucy 3 poller holds that grant; this job runs
from a launchd bash wrapper, which does not — sending from here would block on
a consent dialog nobody clicks (reference: Messages grant is per identity).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import List, Optional

from automations.obcl_ov_sweep import config, sweep
from automations.shared import obcl_charts as oc

GROUP = "ORIENTATION CREW - Real"
ROOT = Path(__file__).resolve().parents[2]
SHOT_DIR = ROOT / "output" / "obcl_ov_sweep" / "shots"
STATE = ROOT / "output" / "obcl_ov_sweep" / "last_shot_state.json"

COLUMNS = ["Start Time", "Name", "Last Name", "Classroom", "Location",
           "Final Status", "BG Status : Last Checked", "Digi Docs",
           "Onboarding Quizzes", "Blue Ink", "Headshot Photo", "UID Request",
           "Owner Submit"]
LABELS = {"BG Status : Last Checked": "BG Status",
          "Onboarding Quizzes": "Quizzes", "Headshot Photo": "Headshot"}
CHECKBOXES = set(COLUMNS[7:])

# Final Status is a dropdown whose colours live on the CHIPS, and the Sheets
# API does not expose chip colours (it returns the option list only, and the
# cell background is plain white). So the picture carries its own palette,
# matched by eye to the OBCL's chips (Megan 2026-09-22: "missing the colors we
# need on final status"). (fill, text). Unknown status = plain white/black.
STATUS_COLORS = {
    "showed up to cr":        ((39, 106, 64), (255, 255, 255)),
    "owner submitted":        ((205, 235, 139), (0, 0, 0)),
    "pending on ov":          ((201, 218, 233), (31, 60, 110)),
    "needs blueink":          ((17, 85, 204), (255, 255, 255)),
    "activations email sent": ((134, 72, 12), (255, 255, 255)),
    "missing id":             ((244, 204, 204), (153, 0, 0)),
    "waiting on bgc":         ((255, 229, 153), (0, 0, 0)),
    "sara+ received":         ((183, 225, 205), (0, 0, 0)),
    "roadmap?":               ((230, 230, 230), (0, 0, 0)),
}


def _start_key(s: str):
    """12:30 before 1:00 — these are all PM (digi_docs roster rule)."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})", s or "")
    if not m:
        return (99, 0)
    h, mi = int(m.group(1)), int(m.group(2))
    if h < 12 and h <= 6:
        h += 12
    return (h, mi)


def this_weeks_chart(values):
    charts = oc.find_charts(values)
    if not charts:
        return None
    return max(charts, key=lambda c: (oc.chart_date(c) or dt.date.min,
                                      c["header_row"]))


def included(row_vals: dict) -> bool:
    fs = (row_vals.get("Final Status") or "").strip()
    return bool(fs and (row_vals.get("Location") or "").strip()
                and not sweep._gone(fs))


def collect(ws, values) -> List[dict]:
    """[{col: {"v": value, "bg": (r,g,b)}}] for each included person, sorted by
    start time. Colours are EFFECTIVE (conditional formatting included), so the
    picture matches what people see in the sheet."""
    ch = this_weeks_chart(values)
    if not ch:
        return []
    cols = ch["cols"]
    rows = []
    for r in range(ch["start_row"], ch["end_row"] + 1):
        row = values[r - 1] if r - 1 < len(values) else []
        vals = {c: (row[cols[c] - 1].strip() if c in cols
                    and cols[c] - 1 < len(row) else "") for c in COLUMNS}
        if vals.get("Name") and vals["Name"] != "Name" and included(vals):
            rows.append((r, vals))
    if not rows:
        return []
    first, last = rows[0][0], rows[-1][0]
    meta = ws.spreadsheet.fetch_sheet_metadata(params={
        "ranges": [f"'{ws.title}'!A{first}:AF{last}"], "includeGridData": "true",
        "fields": "sheets(data(rowData(values(effectiveFormat(backgroundColor)))))"})
    grid = meta["sheets"][0]["data"][0].get("rowData", [])
    out = []
    for r, vals in rows:
        cells = (grid[r - first].get("values", [])
                 if r - first < len(grid) else [])
        rec = {}
        for c in COLUMNS:
            bg = None
            if c in cols and cols[c] - 1 < len(cells):
                b = (cells[cols[c] - 1].get("effectiveFormat") or {}).get(
                    "backgroundColor")
                if b:
                    bg = tuple(round(b.get(k, 0.0), 3)
                               for k in ("red", "green", "blue"))
            rec[c] = {"v": vals[c], "bg": bg}
        out.append(rec)
    out.sort(key=lambda x: (_start_key(x["Start Time"]["v"]),
                            x["Name"]["v"].lower()))
    return out


def fingerprint(recs: List[dict]) -> str:
    return hashlib.sha256(json.dumps(recs, sort_keys=True).encode()).hexdigest()


def changed(recs: List[dict]) -> Optional[bool]:
    """True/False vs the last recorded picture; None when there is no baseline
    yet (the first pass records one and sends nothing)."""
    try:
        prev = json.loads(STATE.read_text()).get("fingerprint")
    except Exception:                                       # noqa: BLE001
        return None
    return prev != fingerprint(recs)


def record(recs: List[dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"fingerprint": fingerprint(recs),
                                 "at": dt.datetime.now().isoformat(
                                     timespec="seconds")}))


# --- drawing ---------------------------------------------------------------

def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in ("/System/Library/Fonts/Supplemental/Georgia Bold.ttf" if bold
              else "/System/Library/Fonts/Supplemental/Georgia.ttf",
              "/Library/Fonts/Arial Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:                                   # noqa: BLE001
            continue
    return ImageFont.load_default()


def _rgb(bg, default=(255, 255, 255)):
    return tuple(int(x * 255) for x in bg) if bg else default


def render(recs: List[dict], title: str, out: Path) -> Path:
    from PIL import Image, ImageDraw
    f, fh = _font(22), _font(22)
    rh, hh, pad = 40, 64, 14
    heads = [LABELS.get(c, c) for c in COLUMNS]
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    def w(t):
        return probe.textlength(t, font=f)

    widths = []
    for c, h in zip(COLUMNS, heads):
        if c in CHECKBOXES:
            widths.append(max(w(h) + 2 * pad, 90))
        else:
            widths.append(max([w(h)] + [w(r[c]["v"]) for r in recs]) + 2 * pad)
    widths = [int(x) for x in widths]
    W = sum(widths)
    H = 56 + hh + rh * len(recs)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 56], fill=(0, 0, 0))
    d.text((pad, 14), title, font=_font(26), fill="white")
    x = 0
    for c, h, cw in zip(COLUMNS, heads, widths):
        d.rectangle([x, 56, x + cw, 56 + hh], fill=(204, 204, 204),
                    outline=(120, 120, 120))
        d.text((x + cw / 2, 56 + hh / 2), h, font=fh, fill="black",
               anchor="mm")
        x += cw
    for i, r in enumerate(recs):
        y = 56 + hh + i * rh
        x = 0
        for c, cw in zip(COLUMNS, widths):
            cell = r[c]
            fill, ink = _rgb(cell["bg"]), None
            if c == "Final Status":
                fill, ink = STATUS_COLORS.get(cell["v"].strip().lower(),
                                              (fill, None))
            d.rectangle([x, y, x + cw, y + rh], fill=fill,
                        outline=(170, 170, 170))
            if c in CHECKBOXES:
                ticked = cell["v"].lower() in config.TRUTHY
                s = 22
                bx, by = x + cw / 2 - s / 2, y + rh / 2 - s / 2
                if ticked:
                    d.rectangle([bx, by, bx + s, by + s], fill=(56, 118, 29))
                    d.line([bx + 5, by + 11, bx + 9, by + 16, bx + 17, by + 6],
                           fill="white", width=3)
                else:
                    d.rectangle([bx, by, bx + s, by + s], outline=(90, 90, 90),
                                width=2)
            else:
                color = ink or ((255, 0, 255) if c in ("Name", "Last Name")
                                else "black")
                d.text((x + cw / 2, y + rh / 2), cell["v"], font=f,
                       fill=color, anchor="mm")
            x += cw
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


# --- the hourly step -------------------------------------------------------

def _is(bg, colour) -> bool:
    return bool(bg) and all(abs(bg[i] - colour[k]) < 0.01
                            for i, k in enumerate(("red", "green", "blue")))


GROUPS = ("Owner Submitted", "Ready for Owner Submit",
          "Waiting on BG / Still Missing Checks")


def split(recs: List[dict]):
    """Three pictures (Megan 2026-09-22): owner submitted (the box is ticked) /
    ready for owner submit (the box is BLUE — the sweep's own verdict) /
    everyone else. Yellow (only the BG check pending) goes in the third: it
    can't be submitted yet."""
    out = {g: [] for g in GROUPS}
    for r in recs:
        box = r["Owner Submit"]
        if box["v"].strip().lower() in config.TRUTHY:
            out[GROUPS[0]].append(r)
        elif _is(box["bg"], config.READY_BLUE):
            out[GROUPS[1]].append(r)
        else:
            out[GROUPS[2]].append(r)
    return [(g, out[g]) for g in GROUPS]


def draw_set(recs: List[dict], week: str, stamp: str, clock: str) -> list:
    """Render one PNG per non-empty group; returns [(group, count, png)]. An
    empty group is skipped, never drawn as a blank picture."""
    made = []
    for i, (g, rows) in enumerate(split(recs), start=1):
        if not rows:
            continue
        png = render(rows, f"{g} ({len(rows)})  ·  New Starts {week}  ·  {clock}",
                     SHOT_DIR / f"obcl_{stamp}_{i}.png")
        made.append((g, len(rows), png))
    return made


def caption(made) -> str:
    counts = {g: n for g, n, _ in made}
    return "OBCL update — " + " · ".join(
        f"{counts.get(g, 0)} {g.lower()}" for g in GROUPS)


def after_pass(ws, values, *, live: bool, text: bool) -> str:
    """Called by run.py after a pass. Returns a one-line outcome for the log."""
    recs = collect(ws, values)
    if not recs:
        return "picture: nobody on this week's chart qualifies — nothing drawn"
    now = dt.datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H%M")
    clock = f"{now.hour % 12 or 12}:{now.minute:02d} {'PM' if now.hour >= 12 else 'AM'}"
    ch = this_weeks_chart(values)
    made = draw_set(recs, ch.get("date_text") or ws.title, stamp, clock)
    names = " ".join(p.name for _, _, p in made)
    if made:  # the caption travels with the pictures, next to the first one
        made[0][2].with_suffix(".txt").write_text(caption(made))
    ch_ = changed(recs)
    if not (live and text):
        return f"pictures: {names} — not texting (dry)"
    if ch_ is None:
        record(recs)
        return f"pictures: {names} — first pass, baseline recorded, not sent"
    if not ch_:
        return f"pictures: {names} — nothing changed since last send, not sent"
    from automations.day_orchestrator import mini_control as mc
    from automations.day_orchestrator.registry import this_machine
    mc.enqueue("text_obcl", names, by="obcl_ov_sweep",
               machine=this_machine(), auto=True)
    record(recs)
    return f"pictures: {names} — CHANGED, queued text_obcl to {GROUP!r}"


def send(png_names, *, dry_run: bool = True) -> dict:
    """Called BY THE POLLER: one message, the caption then every picture.
    Idempotent via a .sent marker next to the FIRST picture."""
    from automations.b2b_dispositions import text_post as tp
    # Accept one space-joined string OR a list whose items may themselves be
    # space-joined (2026-09-22: a quoted queue arg arrived as ONE name).
    if isinstance(png_names, str):
        png_names = [png_names]
    png_names = [n for item in png_names for n in str(item).split()]
    pngs = [SHOT_DIR / n for n in png_names]
    missing = [str(p) for p in pngs if not p.exists()]
    if missing or not pngs:
        raise FileNotFoundError(f"no picture(s) {missing or png_names}")
    marker = pngs[0].with_suffix(".sent")
    if marker.exists() and not dry_run:
        return {"skipped": marker.read_text().strip(), "ok": True}
    cap = pngs[0].with_suffix(".txt")
    text = cap.read_text().strip() if cap.exists() else "OBCL update"
    res = tp.send_to_group(GROUP, text, pngs, dry_run=dry_run)
    if res.get("ok") and not dry_run:
        marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
    return res
