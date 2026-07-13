"""Orchestrate a swag-welcome batch: roster → name-on-card → iMessage.

Typical flow is driven by the preflight UI (preflight_app.py), which hands
this a reviewed roster JSON. It's also runnable from the CLI for testing.

    # dry run (default): composites every card + previews to output/, sends NOTHING
    python -m automations.swag_welcome.run --roster roster.json

    # real send from THIS machine's iMessage account (explicit + confirmed):
    python -m automations.swag_welcome.run --roster roster.json --send

Safety, per house rules:
- --dry-run is the DEFAULT; --send is required to actually text anyone.
- iMessage sends from whatever Mac runs this (no hardcoded account).
- We verify Messages is signed in before a real batch, and report per-person
  delivery so nothing silently vanishes.

roster.json shape (produced by preflight):
    {
      "template": "Hey {name}! ...",          # optional; omit for default
      "recipients": [
        {"chosen_name": "Davone", "phone_e164": "+12147321780", "include": true},
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from automations.swag_welcome import compose, imessage, message

WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT_DIR = WORKSPACE / "output" / "swag_welcome"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_") or "recipient"


def run(roster: dict, send: bool = False, out_dir: Path | None = None) -> dict:
    out_dir = out_dir or (OUTPUT_DIR / date.today().isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)
    template = roster.get("template")
    manager = roster.get("manager", "")
    recips = [r for r in roster.get("recipients", []) if r.get("include", True)]

    summary = {"total": len(recips), "sent": 0, "skipped": 0, "failed": 0,
               "dry_run": not send, "used_placeholder_card": False, "rows": []}

    # Confirm Messages is ready before a real batch — fail loud, not silent.
    if send:
        ok, detail = imessage.messages_ready()
        if not ok:
            raise RuntimeError(f"Not sending — {detail}. Sign into Messages and retry.")

    for r in recips:
        name = (r.get("chosen_name") or "").strip()
        phone = (r.get("phone_e164") or "").strip()
        row = {"name": name, "phone": phone, "sent": False, "error": None}

        if not name or not phone:
            row["error"] = "missing name or phone"
            summary["skipped"] += 1
            summary["rows"].append(row)
            continue

        card_path = out_dir / f"{_slug(name)}_{phone.lstrip('+')}.png"
        meta = compose.compose(name, card_path)
        row["card"] = meta["path"]
        if not meta["used_real_photo"]:
            summary["used_placeholder_card"] = True

        text = message.render(name, template, manager=manager)
        row["text"] = text

        res = imessage.send(phone, text, attachment=str(card_path), dry_run=not send)
        if res["error"]:
            row["error"] = res["error"]
            summary["failed"] += 1
        elif res["sent"]:
            row["sent"] = True
            summary["sent"] += 1
        summary["rows"].append(row)

    summary["out_dir"] = str(out_dir)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="New-hire swag welcome texts")
    ap.add_argument("--roster", required=True, help="path to reviewed roster JSON")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--send", action="store_true",
                   help="actually text people (from this Mac's iMessage account)")
    g.add_argument("--dry-run", action="store_true",
                   help="composite + preview only, send nothing (default)")
    args = ap.parse_args(argv)

    roster = json.loads(Path(args.roster).read_text())
    summary = run(roster, send=args.send)

    print(json.dumps(summary, indent=2))
    if summary["used_placeholder_card"]:
        print("\n⚠️  Used the PLACEHOLDER card — drop the real swag photo into "
              "resources/swag/ before a real send.", file=sys.stderr)
    if summary["dry_run"]:
        print(f"\n✓ Dry run. {summary['total']} card(s) previewed in "
              f"{summary['out_dir']}. Nothing was texted. Add --send to go live.",
              file=sys.stderr)
    else:
        print(f"\n✓ Sent {summary['sent']}/{summary['total']} "
              f"(failed {summary['failed']}, skipped {summary['skipped']}).",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
