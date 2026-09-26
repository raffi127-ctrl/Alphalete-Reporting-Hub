"""Read the week's new-start roster off AISHA'S SCREENSHOT in Slack, not the sheet.

Raf's call (2026-08-03): the live OBCL tab carries people we're NOT moving
forward with (plus duplicate/leftover rows), so the only true reach-out list is
the screenshot Aisha posts each week. This module finds that post in
#rafs-office-recruiting-11280, downloads the roster-table image, and reads the
"2ND Round Interviewer -> new start" rows off it with Claude vision — the same
pattern automations/swag_welcome/extract.py uses for the swag roster.

Anh Đinh etc. come back with real accents; roster._norm folds them for matching.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

import requests

from automations.shared import slack_metrics_post as smp
from automations.shared import slack_retry
from automations.brand_audit import credentials
from automations.shared import new_start_eligibility as eligibility
from automations.shared.new_start_steps import SLACK_CHANNEL_ID

# Moved from #rafs-office-recruiting (C06881A7WLV, retired) on 2026-08-21 — Aisha now
# posts the weekly thread in #rafs-office-recruiting-11280.
CHANNEL_ID = os.environ.get("NSF_CHANNEL_ID", SLACK_CHANNEL_ID)
# Aisha's weekly post — matched loosely on wording (she has some variance).
POST_RE = re.compile(r"new\s*starts?.*scheduled.*monday", re.I)
MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "interviewer": {
                        "type": "string",
                        "description": "The '2ND Round Interviewer' cell EXACTLY as "
                        "shown (this is the LEADER, e.g. 'Jessie Gomez', 'Anh Đinh', "
                        "'rhea mckee'). Copy accents verbatim.",
                    },
                    "name": {"type": "string", "description": "the new-start first name"},
                    "last_name": {"type": "string", "description": "the new-start last name"},
                    "confirmation": {
                        "type": "string",
                        "description": "the LAST status column ('Friday "
                        "Confirmation'), copied EXACTLY, e.g. 'Confirmed: OTP', "
                        "'BOB Friday', 'NA: Sent Text', 'Declined', 'Failed "
                        "Background'. Empty string if the cell is blank.",
                    },
                    "bg_status": {
                        "type": "string",
                        "description": "the 'BG Status : Last Checked' cell, "
                        "copied EXACTLY, e.g. 'Passed', 'Taken - Pending', "
                        "'Review', 'Sent'. Empty string if blank.",
                    },
                },
                "required": ["interviewer", "name", "last_name", "confirmation",
                             "bg_status"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rows"],
    "additionalProperties": False,
}

_PROMPT = (
    "This is a screenshot of a new-start roster table. Each row is one new "
    "start. Columns include a '#', '2ND Round Interviewer', maybe a Trainer/time, "
    "'Name' (first), 'Last Name', and status columns. Read EVERY visible data row "
    "top to bottom and return them in order.\n\n"
    "Rules:\n"
    "- interviewer = the '2ND Round Interviewer' cell, copied EXACTLY including "
    "accents and casing (e.g. 'Anh Đinh', 'rhea mckee', 'De'Avion Allen').\n"
    "- name / last_name = the new start's first and last name cells, exactly.\n"
    "- Only rows that are actually visible in the image — do NOT invent rows and "
    "do NOT skip any visible row. Ignore the header row and any filter icons.\n"
    "- If an interviewer cell is blank because it's a continuation of the row "
    "above, repeat that same interviewer.\n"
    "- confirmation = the LAST status column, headed 'Friday Confirmation'. "
    "Copy the cell text EXACTLY. Some are colour-filled (red for 'Declined' "
    "and 'Failed Background'); read the TEXT, not the colour, and use an empty "
    "string when the cell has none.\n"
    "- bg_status = the 'BG Status : Last Checked' cell, exactly."
)


# A new start who declined, or whose background check failed, is not starting —
# so their interviewer owes them nothing and must not be tagged about them.
# Raf, 2026-08-30: "Lucy is tagging people where the new start has either
# declined the position or failed the BGC, can we make it where it doesn't tag
# those folks please."
#
# THE STATUSES NOW COME OFF THE SHEET, NOT THIS IMAGE (Megan 2026-09-26: "as
# long as we read the correct statuses — but it has to be after Aisha posts the
# screenshot because that's when she has updated the sheet"). So the post is the
# GATE and the FUNNEL SPLIT, and `enrich_from_sheet` replaces every status on
# every row with the live cell. Two reasons that is strictly better:
#
#   1. This schema never captured Final Status at all — only Friday Confirmation
#      and BG Status. "Quit before Classroom", "Terminated" and "Backed Out"
#      were invisible here, so those leaders were still being tagged.
#   2. A status read off a JPEG is a status somebody has to re-read every time
#      the wording drifts. The cell is the cell.
#
# The screenshot's own status fields are kept as the FALLBACK for a row the
# sheet has no match for, so a late-renamed name can never delete a new start.
# DROPPED_MARKERS REMOVED 2026-09-26 — `is_dropped` calls
# shared.new_start_eligibility.not_starting, which is also what Blue Ink, Digi
# Docs and the Slack/Skool email use.


class RosterNotPostedYet(RuntimeError):
    """This week's roster screenshot simply is not up yet.

    A WAIT, not a fault. It clears the moment a person posts the roster, and
    nothing is wrong in the meantime — so callers must not page about it. Before
    this existed the refusal was a bare RuntimeError, indistinguishable from a
    real break, and the thread-scan agent (every 30 min, all day) raised a fresh
    incident on every tick: 7 follow-ups on one thread by mid-afternoon on
    2026-09-01, none of them actionable, for a report that was behaving
    correctly (Megan: "the new start thread I'm pretty sure is a Friday only
    thing?" — it is not the schedule that is wrong, it is calling a wait a
    failure)."""


def is_dropped(row: dict) -> bool:
    """Not starting, so nobody is owed a text about them.

    Reads each status as the column it is, via the family-wide rule in
    shared.new_start_eligibility — the same one Blue Ink, Digi Docs and the
    Slack/Skool email use, so one tab cannot produce two answers.
    """
    return bool(eligibility.not_starting(
        final_status=row.get("final_status") or "",
        bg_status=row.get("bg_status") or "",
        friday=row.get("confirmation") or ""))


def enrich_from_sheet(rows: List[dict], monday, sheet_id: str = "") -> List[str]:
    """Overwrite each row's statuses with the live OBCL cells. Returns notes.

    The screenshot says WHO is in this funnel; the sheet says how each of them
    is doing. Matching is on the folded "first last" (roster._norm), the same
    key the leader lookup uses.

    ADVISORY, never fatal: if the sheet can't be read the rows keep the values
    the screenshot gave them and the caller gets a warning. Losing the statuses
    costs accuracy; raising here would cost the whole roll call.

    A name the sheet doesn't have keeps its screenshot statuses too — Aisha adds
    and renames rows, and a failed match must never silently delete a new start
    who is starting.

    Where the sheet holds the same name TWICE and the rows disagree about
    whether they are starting, nobody is dropped and the disagreement is
    reported. Duplicate rows are exactly what Raf flagged in the first place,
    and a leader nudged about someone who isn't coming is a smaller harm than a
    real new start nobody reaches out to.
    """
    from automations.new_start_followup import obcl
    from automations.new_start_followup import roster as roster_mod

    notes = []  # type: List[str]
    try:
        _, tab, starts = obcl.read_new_starts(
            monday, **({"sheet_id": sheet_id} if sheet_id else {}))
    except Exception as exc:  # noqa: BLE001 — advisory, see the docstring
        notes.append("WARNING: couldn't read the OBCL sheet for statuses ({}); "
                     "using the screenshot's own status columns, which do not "
                     "include Final Status.".format(exc))
        return notes

    by_key = {}  # type: dict
    for st in starts:
        by_key.setdefault(roster_mod._norm(st.name), []).append(st)

    matched = unmatched = 0
    for row in rows:
        key = roster_mod._norm("{} {}".format(row.get("name", ""),
                                              row.get("last_name", "")))
        hits = by_key.get(key) or []
        if not hits:
            unmatched += 1
            notes.append("not on {}: {} {} — keeping the screenshot's statuses"
                         .format(tab, row.get("name", ""),
                                 row.get("last_name", "")))
            continue
        matched += 1
        reasons = {st.drop_reason for st in hits}
        if len(hits) > 1 and len(reasons) > 1:
            notes.append(
                "{} {} is on {} {} times and the rows disagree ({}) — NOT "
                "dropped; somebody should tidy the tab".format(
                    row.get("name", ""), row.get("last_name", ""), tab,
                    len(hits), " / ".join(sorted(r or "(starting)"
                                                 for r in reasons))))
            row["final_status"] = row["bg_status"] = row["confirmation"] = ""
            continue
        st = hits[0]
        row["final_status"] = st.status
        row["bg_status"] = st.bg_status
        row["confirmation"] = st.confirmation
    notes.insert(0, "[roster] statuses read off {}: {} matched, {} not on the "
                    "tab".format(tab, matched, unmatched))
    return notes


def all_interviewers(rows):
    """Every interviewer the screenshot NAMES, including on dropped rows.

    Distinct from owed_counts' keys on purpose. Somebody whose only new start
    declined is not "missing from the screenshot" — the screenshot lists them
    and says don't chase. The sheet cross-read needs that distinction or it
    reads them as a sheet-only row and hands them back (2026-09-13: Raf's only
    new start was Declined, the sheet had the same row with a blank status, and
    he ended up tagged in his own roll call).
    """
    return set((r.get("interviewer") or "").strip()
               for r in rows or [] if (r.get("interviewer") or "").strip())


def owed_counts(rows):
    """-> (interviewer -> count, [dropped row description, ...]).

    The ONE place screenshot rows become owed counts, so the roll call, the
    snapshot and the checklist can't drift on who counts (they each had their
    own copy of this loop before 2026-08-30).
    """
    owed, dropped = {}, []
    for r in rows:
        intv = (r.get("interviewer") or "").strip()
        if not intv:
            continue
        reason = eligibility.not_starting(
            final_status=r.get("final_status") or "",
            bg_status=r.get("bg_status") or "",
            friday=r.get("confirmation") or "")
        if reason:
            # The reason NAMES ITS COLUMN ("Final Status: Quit before
            # Classroom"), because "?" was what this printed whenever the
            # blocking value was one the screenshot never carried.
            dropped.append("{} — {} {} ({})".format(
                intv, r.get("name", ""), r.get("last_name", ""), reason))
            continue
        owed[intv] = owed.get(intv, 0) + 1
    return owed, dropped


def _image_block(image_path) -> dict:
    path = Path(image_path)
    data = path.read_bytes()
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.standard_b64encode(data).decode()}}


def extract_rows(image_path) -> List[dict]:
    """[{'interviewer','name','last_name'}, ...] read off the screenshot via Claude."""
    import anthropic
    content = [_image_block(image_path), {"type": "text", "text": _PROMPT}]
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL, max_tokens=8000,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": content}])
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text).get("rows", [])


def _find_roster_image(client, monday_iso: Optional[str] = None,
                       poster: Optional[str] = None) -> Optional[dict]:
    """The 'New Starts Scheduled for Monday' post's roster image.
    Returns the Slack file dict (with url_private_download) for the LARGEST image
    in that post's thread (the roster table, not the small funnel-count image).
    With `poster` given, only that author's post counts (one post per funnel
    since the week of 8/24 — see thread.FUNNELS)."""
    # PAGED, not one limit=200 call: on Lucy 1 that response is ~180 KB and
    # truncates at ~74 KB every attempt, which is the failure this report kept
    # dying on all of 2026-09-20. [[slack_retry.read_paged]]
    hist = slack_retry.read_paged(client.conversations_history,
                                  channel=CHANNEL_ID, limit=200, _log=print)
    matches = [m for m in hist.get("messages", [])
               if POST_RE.search(m.get("text", "") or "")
               and (not poster or m.get("user") == poster)]
    if not matches:
        # NOBODY HAS POSTED THIS WEEK'S ROSTER YET — waiting, not broken.
        # Aisha posts it Friday afternoon, and the thread-scan agent ticks
        # every 30 minutes from Monday, so this branch is the normal state for
        # most of the week. It used to fall through to a plain RuntimeError,
        # which the caller reports as INCOMPLETE: that opened a failure
        # incident on 2026-09-11 and re-alerted on every tick after it.
        #
        # Distinct from "a post exists but carries no image" further down,
        # which keeps the generic error — a roster post WITHOUT its screenshot
        # is a real problem somebody has to fix.
        raise RosterNotPostedYet(
            "No 'New Starts Scheduled for Monday' post in {}{} for the week of "
            "{} yet. Aisha posts it Friday afternoon; nothing to do until "
            "then.".format(CHANNEL_ID,
                           " by <@{}>".format(poster) if poster else "",
                           monday_iso or "this week"))
    if monday_iso:
        # Two guards, both learned the week of 8/24:
        #  - A week where the roster hasn't been posted yet would otherwise
        #    find LAST week's — which reads fine and stamps itself as this week
        #    (that almost shipped a wrong-week snapshot on 2026-08-22). The
        #    post lands the Friday before, so only this week's window counts.
        #  - There are TWO same-titled Friday posts now (one per funnel), so
        #    without a poster filter take the EARLIEST in-window match (the
        #    main funnel posts first), never the newest.
        import datetime as dt
        monday = dt.date.fromisoformat(monday_iso)

        def _posted(m):
            return dt.datetime.fromtimestamp(float(m["ts"])).date()

        in_week = [m for m in matches
                   if monday - dt.timedelta(days=6) <= _posted(m) <= monday]
        if not in_week:
            raise RosterNotPostedYet(
                "Newest roster post in {}{} is from {} — the week of a "
                "different Monday, not {}. This week's roster isn't up yet; "
                "refusing to read last week's screenshot.".format(
                    CHANNEL_ID,
                    " by <@{}>".format(poster) if poster else "",
                    _posted(matches[0]).isoformat(), monday_iso))
        parent = min(in_week, key=lambda m: float(m["ts"]))
    else:
        parent = matches[0]  # history is newest-first
    ts = parent["ts"]
    files = list(parent.get("files", []) or [])
    replies = client.conversations_replies(channel=CHANNEL_ID, ts=ts, limit=100)
    for m in replies.get("messages", []):
        files.extend(m.get("files", []) or [])
    images = [f for f in files if (f.get("mimetype") or "").startswith("image/")]
    if not images:
        return None
    # the roster table is the biggest image; the funnel-count one is tiny (~35 KB)
    images.sort(key=lambda f: f.get("size", 0), reverse=True)
    return images[0]


# PNG / JPEG / GIF / WEBP(RIFF) magic bytes. Slack answers an un-authorised
# url_private with 200 + an HTML sign-in page, which raise_for_status() waves
# through -- the bad bytes then surface much later as an opaque API
# "400 Could not process image" (what broke the 2026-08-08 8am roll call and got
# Bill Hirwa mis-tagged off the sheet fallback). Fail here, where the cause is
# still legible.
_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")


def _fetch_bytes(url: str, token: str) -> bytes:
    """One attempt at the image. Reading `.content` is INSIDE the attempt on
    purpose: with a chunked body the truncation surfaces when the content is
    read, not when get() returns, so a retry wrapped around get() alone would
    re-raise on exactly the same half-downloaded response."""
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "?")


def _download(file_obj: dict, token: str) -> Path:
    url = file_obj.get("url_private_download") or file_obj["url_private"]
    # Retried: Slack truncated this download twice on 2026-09-20 (74,352 of
    # 178,741 bytes at 08:01, and again at 08:32), and each one failed the whole
    # report over a fault that was gone seconds later. [[slack_retry]]
    body, ctype = slack_retry.read(_fetch_bytes, url, token, _log=print)
    if not body.startswith(_IMAGE_MAGIC):
        raise RuntimeError(
            "Slack returned {} bytes of {!r} instead of the roster image for "
            "{!r}. Usually the token can't read files in that channel "
            "(needs files:read) -- check ~/.config/recruiting-report/"
            "slack-user-token on this machine.".format(
                len(body), ctype, file_obj.get("name", "?")))
    suffix = mimetypes.guess_extension(file_obj.get("mimetype", "image/png")) or ".png"
    fd, path = tempfile.mkstemp(prefix="nsf_roster_", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(body)
    return Path(path)


# OCR results, keyed by the Slack FILE the rows were read from.
#
# The roster is a picture that changes only when Aisha posts a new one, but
# every pass (roll call, nudge, checklist, sat-texts, and now the @Lucy
# responder) re-downloaded and re-OCR'd it. That's a paid vision call and the
# single flakiest step in this report -- an un-authorised download returns an
# HTML sign-in page that surfaces as an opaque "400 Could not process image",
# which is what broke the 8/8 roll call. Running a responder hourly off an
# uncached read would multiply both the cost and that failure surface.
#
# Keyed on the file's own id AND timestamp, never on the week: if Aisha
# replaces the screenshot the key changes and we re-read it. A stale roster is
# the one thing this cache must never serve.
CACHE_DIR = (Path(__file__).resolve().parents[2] / "output"
             / "new_start_followup" / "roster_ocr")


def _cache_path(img: dict) -> Path:
    key = "{}-{}".format(img.get("id") or "noid", img.get("timestamp") or "0")
    return CACHE_DIR / ("%s.json" % key)


def _with_sheet_statuses(rows: List[dict], monday_iso: Optional[str],
                         from_sheet: bool) -> List[dict]:
    """Apply enrich_from_sheet and print its notes. Never raises."""
    if not from_sheet:
        return rows
    if not monday_iso:
        # Without a week we cannot pick the tab, and guessing the newest one is
        # how last week's statuses get stamped onto this week (the 8/22 near
        # miss). Leave the screenshot's own values and say so.
        print("[roster] no week given, so statuses stay as the screenshot read "
              "them (no Final Status).")
        return rows
    try:
        monday = dt.date.fromisoformat(monday_iso)
    except ValueError:
        print("[roster] couldn't read {!r} as a date; statuses stay as the "
              "screenshot read them.".format(monday_iso))
        return rows
    for line in enrich_from_sheet(rows, monday):
        print("   " + line if not line.startswith("[") else line)
    return rows


def fetch_roster_rows(monday_iso: Optional[str] = None,
                      poster: Optional[str] = None,
                      use_cache: bool = True,
                      from_sheet: bool = True) -> List[dict]:
    """End-to-end: find the weekly screenshot, OCR it, then take the STATUSES
    off the OBCL sheet.

    Returns [{'interviewer','name','last_name','confirmation','bg_status',
              'final_status'}]. Raises RosterNotPostedYet if Aisha hasn't
    posted — which is also what makes reading the sheet safe: her post is how
    we know the sheet is current for this week (Megan 2026-09-26).

    The OCR half is cached per image; the status half is re-read EVERY call,
    because statuses move through the week and the image doesn't.
    `from_sheet=False` is for tests and for showing what the picture alone said.
    """
    client = smp._client()
    img = _find_roster_image(client, monday_iso, poster=poster)
    if not img:
        raise RuntimeError(
            "No 'New Starts Scheduled for Monday' roster image found in "
            "{}{}. Has it been posted yet?".format(
                CHANNEL_ID, " by <@{}>".format(poster) if poster else ""))

    cache = _cache_path(img)
    if use_cache and cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            rows = cached.get("rows") or []
            # Only trust a cache written by the CURRENT schema. An older file
            # has no status columns, and silently reusing it would count the
            # declined rows again.
            if rows and all("confirmation" in r for r in rows):
                print("[roster] using cached OCR of {} ({} rows)".format(
                    img.get("name", "?"), len(rows)))
                return _with_sheet_statuses(rows, monday_iso, from_sheet)
        except Exception as exc:  # noqa: BLE001 — a bad cache just means re-read
            print("[roster] ignoring unreadable OCR cache ({}).".format(exc))

    path = _download(img, smp._load_token())
    try:
        rows = extract_rows(path)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(img).write_text(
                json.dumps({"file": img.get("name"), "id": img.get("id"),
                            "rows": rows}, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — caching is an optimisation
            print("[roster] couldn't write the OCR cache ({}).".format(exc))
    finally:
        try:
            path.unlink()
        except Exception:
            pass
    # The CACHE stores what the picture said; the rows we hand back carry the
    # sheet's live statuses. Enriching after the write on purpose, so a cache
    # entry is never a snapshot of a status that has since changed.
    return _with_sheet_statuses(rows, monday_iso, from_sheet)


def diagnose() -> int:
    """Why can't THIS machine read the roster screenshot? Prints identity,
    scopes, and the raw download result. Never calls the vision API, never
    prints the token.

    Exists because the failure is machine-specific and silent: the same file
    reads fine from the laptop and 400'd on the mini (2026-08-08), which is what
    sent the roll call down the sheet fallback and mis-tagged Bill Hirwa.
    """
    print("channel: {}".format(CHANNEL_ID))
    try:
        client = smp._client()
    except Exception as exc:  # noqa: BLE001
        print("FAIL: no usable Slack token on this machine -> {}".format(exc))
        return 1

    try:
        who = client.auth_test()
        print("identity: user={} id={} team={}".format(
            who.get("user"), who.get("user_id"), who.get("team")))
        scopes = (who.headers or {}).get("x-oauth-scopes") or ""
        print("scopes  : {}".format(scopes or "(not reported)"))
        for need in ("files:read", "channels:history", "groups:history"):
            if scopes:
                print("   {} {}".format("OK  " if need in scopes else "MISSING", need))
    except Exception as exc:  # noqa: BLE001
        print("FAIL: auth.test -> {}".format(exc))
        return 1

    try:
        img = _find_roster_image(client)
    except Exception as exc:  # noqa: BLE001
        print("FAIL: couldn't read channel history -> {}".format(exc))
        return 1
    if not img:
        print("FAIL: no roster image found in the newest 'New Starts Scheduled "
              "for Monday' post. Has Aisha posted it?")
        return 1
    print("image   : name={!r} size={} mimetype={} id={}".format(
        img.get("name"), img.get("size"), img.get("mimetype"), img.get("id")))

    url = img.get("url_private_download") or img["url_private"]
    try:
        r = requests.get(url, headers={"Authorization": "Bearer {}".format(
            smp._load_token())}, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print("FAIL: download raised -> {}".format(exc))
        return 1
    body = r.content
    print("download: http={} content-type={} bytes={}".format(
        r.status_code, r.headers.get("Content-Type", "?"), len(body)))
    print("first16 : {!r}".format(body[:16]))
    if body.startswith(_IMAGE_MAGIC):
        print("RESULT  : OK — real image bytes. The vision call should work here.")
        return 0
    print("RESULT  : BAD — this is NOT an image. Slack served a sign-in/error "
          "page, which is what reaches the API as '400 Could not process "
          "image'. This machine's token can't read files in this channel: "
          "it needs files:read AND the token's user must be a member. "
          "Fix: `lucy set_slack_token <xoxp-...>` with the same token the "
          "laptop uses.")
    return 1


if __name__ == "__main__":
    import sys
    if "--diag" in sys.argv:
        raise SystemExit(diagnose())
    rows = fetch_roster_rows()
    by = {}
    for r in rows:
        by.setdefault(r["interviewer"].strip(), []).append(
            f"{r['name']} {r['last_name']}".strip())
    print(f"{len(rows)} new starts across {len(by)} interviewers:\n")
    for intv in sorted(by):
        print(f"  {intv} ({len(by[intv])}): {', '.join(by[intv])}")
    sys.exit(0)
