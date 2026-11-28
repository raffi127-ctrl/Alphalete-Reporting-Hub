"""Today's bundle folders: drop a part in, read the parts back.

    output/text_bundles/<YYYY-MM-DD>/<bundle>/<part>.json   + its pictures
    output/text_bundles/<YYYY-MM-DD>/<bundle>/SENT           once it went out

A part dropped twice keeps the LATEST copy (a re-run replaces, never doubles).
A part dropped after SENT is texted on its own through the outbox (late_send),
so a late report still reaches the chats instead of vanishing.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.text_bundles import config as C


def parse_token(name: str) -> Tuple[str, str]:
    rest = str(name or "")[len(C.PREFIX):]
    bundle, _, part = rest.partition(":")
    if bundle not in C.BUNDLES:
        raise ValueError("unknown text bundle %r in %r" % (bundle, name))
    known = [p[0] for p in C.BUNDLES[bundle]["parts"]]
    if part not in known:
        raise ValueError("unknown part %r for bundle %r (known: %s)" % (part, bundle, known))
    return bundle, part


def bundle_dir(bundle: str, day: dt.date) -> Path:
    return C.ROOT / day.isoformat() / bundle


def is_sent(bundle: str, day: dt.date) -> bool:
    return (bundle_dir(bundle, day) / "SENT").exists()


def mark_sent(bundle: str, day: dt.date, note: str = "") -> None:
    d = bundle_dir(bundle, day)
    d.mkdir(parents=True, exist_ok=True)
    (d / "SENT").write_text("%s %s" % (dt.datetime.now().isoformat(timespec="seconds"), note))


def drop(name: str, text: str, images: Sequence, now: Optional[dt.datetime] = None) -> Dict:
    """Keep one part for today's bundle. Returns what happened."""
    bundle, part = parse_token(name)
    now = now or dt.datetime.now()
    day = now.date()
    imgs = [Path(p) for p in (images or []) if Path(p).exists()]
    if is_sent(bundle, day):
        return late_send(bundle, part, text, imgs, day)
    d = bundle_dir(bundle, day)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("%s__*" % part):          # a re-run replaces its pictures
        old.unlink()
    kept = []
    for i, p in enumerate(imgs):
        dest = d / ("%s__%d%s" % (part, i, p.suffix or ".png"))
        shutil.copy(p, dest)
        kept.append(dest.name)
    (d / ("%s.json" % part)).write_text(json.dumps({
        "part": part, "at": now.isoformat(timespec="seconds"),
        "text": text or "", "images": kept}, indent=1), encoding="utf-8")
    return {"bundle": bundle, "part": part, "images": len(kept), "late": False}


def parts(bundle: str, day: dt.date) -> Dict[str, Dict]:
    """{part: {"text", "images": [abs paths], "at"}} for what arrived today."""
    d = bundle_dir(bundle, day)
    out = {}
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- a torn write is a missing part
            continue
        rec["images"] = [str(d / n) for n in rec.get("images") or [] if (d / n).exists()]
        out[rec.get("part") or f.stem] = rec
    return out


def late_send(bundle: str, part: str, text: str, images: List[Path], day: dt.date) -> Dict:
    """The bundle already went out today: text this part by itself to the
    bundle's chats, through the outbox like any other report."""
    from automations.b2b_dispositions import run as bd_run
    from automations.b2b_dispositions import text_post as tp
    from automations.day_orchestrator import text_outbox as tob
    spec = {"kind": C.late_kind(bundle), "title": text or "",
            "text": "" if images else (text or ""),
            "by_campaign": {C.TEXT_CAMPAIGN: [str(p) for p in images]}}
    if not images and not (text or "").strip():
        return {"bundle": bundle, "part": part, "late": True, "queued": False}
    mp = tp.write_manifest(spec, bd_run.OUTPUT_DIR / day.isoformat(),
                           "%s-%s-%s" % (spec["kind"], part, dt.datetime.now().strftime("%H%M%S")))
    tob.drop(mp, by="text_bundles", day=day.isoformat())
    return {"bundle": bundle, "part": part, "late": True, "queued": True}
