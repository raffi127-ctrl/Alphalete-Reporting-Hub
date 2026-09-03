"""Text each disposition posting into its campaign's iMessage group.

Runs on Lucy 2, where Messages is signed in as `alphletegp` — the same machine
and the same AppleScript path the mini_control `sendtext` action proved working
unattended on 2026-08-03.

Two things make this different from `sendtext`, and both matter:

1. It targets a GROUP, not a phone number. `sendtext` resolves a buddy from a
   number and has no group path at all. Groups are addressed by `chat id`.
2. It carries the IMAGE. Sending an image to a bare number is unsolved on macOS
   (see swag_welcome.imessage — the card auto-send is switched off for exactly
   that reason), but sending one to a GROUP works and is proven: Texas de Brazil
   delivered multi-page images with `send (POSIX file ...) to theChat`. So the
   group requirement is what makes the image requirement achievable.

THE RULE HERE: resolve the group by NAME on every single send, never store a
GUID. A group's chat id is regenerated whenever its membership changes, and a
stale id does not raise — Messages happily "sends" into a thread nobody can see.
That is precisely how the TdB texts went missing for weeks. Carlos is actively
adding people to these groups, so the ids are guaranteed to churn.

An ambiguous or missing name raises. It must never fall back to "pick the first
match" — texting an office's numbers into the wrong leaders' group is worse than
not texting at all.

Python 3.9-safe (Lucy 2's runtime).
"""
from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from automations.b2b_dispositions import config as cfg


class GroupTextError(RuntimeError):
    """Raised when a group can't be resolved, or Messages refuses the send."""


# Messages is a SANDBOXED app, and it silently drops an attachment it isn't
# allowed to read — the send returns success and the picture simply never
# appears. Proven on Lucy 2 2026-08-06: the identical PNG sent from the repo's
# output/ tree, the home folder, Downloads and /tmp all vanished, while the copy
# in ~/Pictures arrived. Nothing about the addressing, the image format or Full
# Disk Access mattered; only the directory did.
#
# So every attachment is copied into ~/Pictures before it is handed over. Keep
# this staging step — sending straight from output/ looks like it works and
# quietly delivers text with no picture.
STAGING_DIR = Path.home() / "Pictures" / "AlphaleteDispositions"


def _stage_for_messages(path: Path) -> Path:
    """Copy an image somewhere Messages is permitted to read it."""
    import shutil
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    dest = STAGING_DIR / path.name
    if path.resolve() != dest.resolve():
        shutil.copy(path, dest)
    return dest


def _osascript(script: str, timeout: int = 300) -> str:
    """One AppleScript against Messages.

    The wide default timeout is deliberate and load-bearing. Every Apple Event to
    Messages from a not-yet-authorized process pops the one-time macOS "… wants
    to control Messages" consent dialog and BLOCKS until a human answers it. A
    short timeout kills osascript and dismisses that dialog before anyone can
    click Allow — which is why the first `sendtext` attempts failed on a machine
    with nobody watching (commit 7dbbefb). 300s keeps it clickable.
    """
    if platform.system() != "Darwin":
        raise GroupTextError("iMessage sending needs macOS + Messages.app")
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GroupTextError(
            "Messages did not answer in %ds — most likely the one-time "
            "'… wants to control Messages' dialog is sitting unanswered on this "
            "machine. A human at Lucy 2 has to click Allow once." % timeout)
    except Exception as e:  # noqa: BLE001
        raise GroupTextError("osascript failed to launch: %s" % str(e)[:160])
    if proc.returncode != 0:
        raise GroupTextError((proc.stderr or "osascript failed").strip()[:300])
    return (proc.stdout or "").strip()


def find_groups(name: str) -> List[Dict]:
    """Every chat whose display name contains `name`, as {id, name, participants}.

    Substring, not equality: the AT&T group's real name ends in a trailing space
    ("ATT B2B Leaders "), and Messages preserves it.
    """
    safe = (name or "").replace("\\", "\\\\").replace('"', '\\"')
    out = _osascript(
        'tell application "Messages"\n'
        '  set res to ""\n'
        '  try\n'
        '    set hits to (chats whose name contains "%s")\n'
        '  on error\n'
        '    set hits to {}\n'
        '    repeat with c in chats\n'
        '      set nm to ""\n'
        '      try\n'
        '        set nm to name of c as text\n'
        '      end try\n'
        '      if nm contains "%s" then set end of hits to c\n'
        '    end repeat\n'
        '  end try\n'
        '  repeat with c in hits\n'
        '    set nm to ""\n'
        '    try\n'
        '      set nm to name of c as text\n'
        '    end try\n'
        '    set pc to 0\n'
        '    try\n'
        '      set pc to count of participants of c\n'
        '    end try\n'
        '    set res to res & (id of c) & tab & nm & tab & pc & linefeed\n'
        '  end repeat\n'
        '  return res\n'
        'end tell' % (safe, safe))
    found = []
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        found.append({"id": parts[0].strip(),
                      "name": parts[1] if len(parts) > 1 else "",
                      "participants": parts[2].strip() if len(parts) > 2 else "?"})
    return found


def resolve_group(name: str) -> Dict:
    """The ONE live chat matching `name`. Raises on 0 or 2+ — never guesses.

    Called fresh for every send; the returned id is used immediately and thrown
    away. Do not cache it, and do not put it in config: see the module docstring.
    """
    hits = find_groups(name)
    if not hits:
        raise GroupTextError(
            "no iMessage group named %r on this machine — either Lucy isn't a "
            "member (Carlos adds her), or the name changed. Check with "
            "`lucy find_group %s --machine \"Lucy 2\"`." % (name, name))
    if len(hits) > 1:
        raise GroupTextError(
            "%d chats match %r (%s) — refusing to guess which one. Narrow the "
            "name in config.TEXT_ROUTES." % (
                len(hits), name,
                ", ".join("%s/%s participants" % (h["name"], h["participants"])
                          for h in hits)))
    return hits[0]


def send_to_group(name: str, text: str, image_paths: Sequence,
                  *, dry_run: bool = True,
                  allow_textonly: bool = False) -> Dict:
    """Send one posting — its Slack text, then its image(s) — to a named group.

    Text first so the images arrive under a labelled header, matching how Slack
    reads (bold title, images beneath).

    `allow_textonly` lifts the no-image refusal below for a caller whose
    message is genuinely text. OFF by default because for this module's own
    posting the image IS the post. gap_alerts is the exception: its "15 min of
    gaps — <office>" list is a text message that happens to travel under a
    board flyer, and when an office's board comes back empty the list is still
    the half somebody acts on (Megan 2026-09-02).
    """
    images = [Path(p) for p in (image_paths or [])]
    missing = [str(p) for p in images if not p.exists()]
    images = [p for p in images if p.exists()]

    result = {"group": name, "text": text, "dry_run": dry_run,
              "images": [str(p) for p in images], "missing": missing,
              "sent_images": [], "ok": False}

    # Resolve even on a dry run: it's read-only, and it's the half most likely to
    # be wrong (membership churn). A dry run that skipped it would prove nothing.
    info = resolve_group(name)
    result["chat_id"] = info["id"]
    result["resolved_name"] = info["name"]
    result["participants"] = info["participants"]

    if dry_run:
        result["ok"] = True
        return result

    if not images and not allow_textonly:
        raise GroupTextError(
            "refusing to text %r with no image — the posting IS the image; a "
            "bare title would read as a broken send. missing=%s" % (name, missing))
    if not images and not (text or "").strip():
        # allow_textonly permits a message with no flyer, never a message with
        # nothing in it — an empty send is the blank post, by another route.
        raise GroupTextError(
            "refusing to text %r with neither an image nor any text" % name)

    cid = info["id"].replace("\\", "\\\\").replace('"', '\\"')

    def _to_chat(action: str, timeout: int = 300) -> None:
        _osascript('tell application "Messages"\n'
                   '  set theChat to a reference to chat id "%s"\n'
                   '  %s\n'
                   'end tell' % (cid, action), timeout=timeout)

    if text:
        safe = text.replace("\\", "\\\\").replace('"', '\\"')
        _to_chat('send "%s" to theChat' % safe)
        result["sent_text"] = True

    for img in images:
        staged = _stage_for_messages(img)
        ip = str(staged).replace("\\", "\\\\").replace('"', '\\"')
        _to_chat('send (POSIX file "%s") to theChat' % ip)
        # Messages uploads asynchronously; crowding it drops images silently.
        time.sleep(cfg.IMAGE_SEND_DELAY_S)
        result["sent_images"].append(str(img))

    result["ok"] = True
    return result


def send_text_to_group(name: str, text: str, *, dry_run: bool = True) -> Dict:
    """Send a TEXT-ONLY message to a named group.

    send_to_group refuses image-less sends because for the disposition posts
    the image IS the content. The new-start reminders (new_start_followup) are
    the opposite — pure text plus a Slack link that iMessage unfurls on its
    own — so this is the text-only twin. Same rules as send_to_group: the
    group is resolved by NAME fresh on every send (never a stored GUID), and
    resolution runs even on a dry run because it's the half most likely to be
    wrong.
    """
    if not (text or "").strip():
        raise GroupTextError("refusing to send an empty text to %r" % name)

    result = {"group": name, "text": text, "dry_run": dry_run, "ok": False}
    info = resolve_group(name)
    result["chat_id"] = info["id"]
    result["resolved_name"] = info["name"]
    result["participants"] = info["participants"]
    if dry_run:
        result["ok"] = True
        return result

    cid = info["id"].replace("\\", "\\\\").replace('"', '\\"')
    # AppleScript 2.0 string literals understand \n, so newlines are escaped
    # rather than embedded — a raw newline inside the quoted literal is a
    # compile error.
    safe = (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n"))
    _osascript('tell application "Messages"\n'
               '  set theChat to a reference to chat id "%s"\n'
               '  send "%s" to theChat\n'
               'end tell' % (cid, safe))
    result["ok"] = True
    return result


def send_specs(specs: List[Dict], *, dry_run: bool = True) -> Dict:
    """Route every captured spec to its group and send.

    Routing is keyed on (campaign, post-type) and reads the spec's per-campaign
    image map — NOT positional order. A stitch or stack failure changes how many
    images a campaign produces, and a positional read would then hand Box's
    numbers to the AT&T leaders. Attribution has to survive partial failure.

    One campaign's failure never blocks the others: each is reported on its own.
    """
    sent, errors, skipped = [], [], []
    for spec in specs:
        kind = spec.get("kind") or ""
        by_campaign = spec.get("by_campaign") or {}
        title = spec.get("title") or ""
        for campaign, paths in sorted(by_campaign.items()):
            groups = cfg.TEXT_ROUTES.get((campaign, kind)) or []
            if not groups:
                skipped.append("%s/%s (no route)" % (campaign, kind))
                continue
            # One campaign can land in several groups (each campaign's own
            # leaders plus the shared one). A failure in one must not stop the
            # rest — they're independent audiences.
            for group in groups:
                try:
                    res = send_to_group(group, title, paths, dry_run=dry_run)
                    res["campaign"] = campaign
                    res["kind"] = kind
                    sent.append(res)
                except Exception as e:  # noqa: BLE001
                    errors.append("%s -> %s: %s: %s" % (
                        campaign, group, type(e).__name__, str(e)[:200]))
    return {"sent": sent, "errors": errors, "skipped": skipped,
            "dry_run": dry_run, "ok": not errors}


# --- handing the send to the process that already has permission --------------
# macOS grants "control Messages" per executable identity, and the two jobs on
# Lucy 2 are NOT the same one:
#   * mini_control poller  -> launchd runs .venv/bin/python directly
#   * b2b-dispositions     -> launchd runs /bin/bash on a wrapper script
# The poller earned the grant on 2026-08-03 when a human clicked Allow, and a
# subprocess of the poller inherits it — proven 2026-08-04, when the --text
# dry-run resolved both groups through Apple Events with no prompt. The scheduled
# dispositions agent has never been authorized, and nobody sits at Lucy 2 to
# authorize it: a prompt there would block for 5 minutes and then fail.
#
# So the scheduled job never touches Messages. It writes a manifest of what to
# text and drops a `text_dispositions` row on its own machine's control queue;
# the poller — the identity that already holds the grant — does the sending.
MANIFEST_PREFIX = "text_manifest"


def manifest_path(out_dir, kind: str, slot: str):
    """One manifest per (post-type, slot) so a re-run overwrites rather than
    piles up, and the filename alone says what it is."""
    safe_slot = "".join(ch if ch.isalnum() else "-" for ch in (slot or "")).strip("-")
    return Path(out_dir) / ("%s_%s_%s.json" % (MANIFEST_PREFIX, kind, safe_slot.lower()))


def write_manifest(spec: Dict, out_dir, slot: str):
    """Record exactly what should be texted, so the poller sends the same thing
    this run captured — no re-deriving titles or re-globbing for images."""
    import json
    p = manifest_path(out_dir, spec.get("kind") or "", slot)
    payload = {
        "kind": spec.get("kind"),
        "title": spec.get("title"),
        "slot": slot,
        "by_campaign": {c: [str(x) for x in paths]
                        for c, paths in (spec.get("by_campaign") or {}).items()},
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return p


def send_manifest(path, *, dry_run: bool = True) -> Dict:
    """Send a manifest written by the capture run. Called BY THE POLLER.

    Idempotent: a `.sent` marker is dropped next to the manifest, because the
    control queue retries and an hourly cadence means a double-send would be a
    duplicate text to 20 leaders, not a harmless retry.
    """
    import json
    p = Path(path)
    if not p.exists():
        raise GroupTextError("no manifest at %s" % p)
    marker = p.with_suffix(".sent")
    if marker.exists() and not dry_run:
        return {"skipped": "already sent at %s" % marker.read_text().strip()[:40],
                "ok": True, "sent": [], "errors": [], "skipped_routes": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    spec = {"kind": data.get("kind"), "title": data.get("title"),
            "by_campaign": data.get("by_campaign") or {}}
    res = send_specs([spec], dry_run=dry_run)
    if res.get("ok") and not dry_run:
        import datetime as _dt
        marker.write_text(_dt.datetime.now().isoformat(timespec="seconds"))
    return res


def describe(res: Dict) -> str:
    """Human-readable dry-run report: what would go where, with the LIVE id."""
    lines = []
    for s in res.get("sent", []):
        lines.append("  %s %s" % ("WOULD TEXT" if s.get("dry_run") else "TEXTED",
                                  s.get("group")))
        lines.append("    chat id     : %s (%s participants, name=%r)" % (
            s.get("chat_id"), s.get("participants"), s.get("resolved_name")))
        lines.append("    text        : %s" % (s.get("text") or "(none)"))
        for p in s.get("images", []):
            lines.append("    image       : %s" % p)
        for p in s.get("missing", []):
            lines.append("    MISSING FILE: %s" % p)
    for sk in res.get("skipped", []):
        lines.append("  skipped %s" % sk)
    for e in res.get("errors", []):
        lines.append("  ERROR %s" % e)
    return "\n".join(lines) if lines else "  (nothing to text)"
