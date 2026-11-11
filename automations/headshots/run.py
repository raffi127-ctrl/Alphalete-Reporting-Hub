"""Headshot bot — watch the Monday headshot threads, return finished headshots.

Raf's ask (2026-08-23, #l10-alphalete "Headshot Orientation posting"), shaped
by Megan 2026-08-23: weekly_thread.py starts a thread each Monday in
#rafs-office-recruiting-11280 asking people to reply with the
headshot photo AND the person's name. This side runs on a tick and:

  1. Finds this week's and last week's Monday threads (by their marker line —
     last week's still catches stragglers).
  2. For each unhandled reply that carries an image: the reply text is the
     person's name ("First Last" — capitalization is fixed automatically).
     Photo but no name -> ask once in the thread and retry next tick.
  3. Cut the background, put the person on pure white, crop to
     head-and-shoulders. No text on the photo — the name is the FILENAME.
  4. Post the finished image back in the thread and ✅ the reply.
     A copy is archived in output/headshots/ for the Roadmap upload —
     automating the Roadmap portal itself is Phase 2.
  5. Record the reply ts in a state file so nothing processes twice.
     (No go-live baseline needed: the threads only exist because WE post
     them, so every reply in them is real work.)

Safe by default: --dry-run (the default until Megan flips it live) processes
the photos and writes previews locally but posts NOTHING to Slack.

    # preview: process replies in the current threads, post nothing
    python -m automations.headshots.run --dry-run

    # one local file end-to-end, no Slack at all:
    python -m automations.headshots.run --file photo.jpg --name "First Last"

    # live (after Megan's go):
    python -m automations.headshots.run

Cross-platform: Slack API + Pillow + rembg; no Mac-only paths.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from automations.headshots import config
from automations.headshots import form as hs_form
from automations.shared.name_case import titlecase_name

_STATE = Path.home() / ".config" / "headshots" / "state.json"
_LOCK = Path.home() / ".config" / "headshots" / "headshots.lock"
_STALE_LOCK_SECONDS = 20 * 60


class HeadshotError(RuntimeError):
    pass


# ---- singleton lock / state (same idiom as sara_down) ------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def acquire_lock() -> bool:
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    if _LOCK.exists():
        try:
            old = int(_LOCK.read_text().strip() or "0")
        except ValueError:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            # A healthy run takes a few minutes. One holding the lock longer
            # is hung (2026-11-11: a stuck model download held it for an hour
            # and every 5-min tick quietly skipped) -- end it and carry on.
            try:
                age = time.time() - _LOCK.stat().st_mtime
            except OSError:
                age = 0
            if age < _STALE_LOCK_SECONDS:
                return False
            print(f"  headshots lock held {int(age // 60)} min by pid {old} "
                  "-- ending the stuck run")
            try:
                os.kill(old, signal.SIGKILL)
            except OSError:
                pass
    _LOCK.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        if _LOCK.exists() and _LOCK.read_text().strip() == str(os.getpid()):
            _LOCK.unlink()
    except OSError:
        pass


def _load_state() -> dict:
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {}


def _save_state(s: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s, indent=2))


# ---- Slack plumbing (shared Lucy tokens; downloads verified like sara_down) --
def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _image_files(msg: dict) -> list[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


def _download_image(f: dict) -> bytes:
    """Download one Slack file, verified to be real image bytes (a token
    missing files:read gets an HTML sign-in page with HTTP 200 — the exact
    trap sara_down documents). Reuses its sniffer + token fallback."""
    from automations.sara_down.run import SaraDownError, _download_image as dl
    try:
        data, _subtype = dl(f)
    except SaraDownError as e:
        raise HeadshotError(str(e)) from e
    return data


# ---- the name comes from the caption ----------------------------------------
_MENTION = re.compile(r"<[@#!][^>]*>|<https?://[^>]*>|:[a-z0-9_+-]+:")

# Words that mean the caption is chatter, not a name. Keeps "headshot for
# roadmap pls" from becoming somebody called Headshot For Roadmap Pls.
_NOT_NAMES = {
    "headshot", "headshots", "photo", "photos", "pic", "picture", "picture.",
    "new", "hire", "hires", "start", "starts", "for", "the", "a", "an",
    "please", "pls", "plz", "here", "is", "this", "team", "roadmap", "and",
    "today", "orientation", "submission", "upload", "needs", "need", "asap",
}


def name_from_caption(text: str) -> str | None:
    """Pull "First Last" out of the post's caption, or None if it isn't one.

    Strips mentions/links/emoji, then accepts 2-4 capitalizable words that
    look like a name (letters, hyphens, apostrophes, a roman suffix). The
    admins' habit is to post the photo with just the name as the caption.
    """
    cleaned = _MENTION.sub(" ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    # A hyphenated surname typed with spaces around the hyphen — JD posted
    # "Damarrion Hawkins - Brown" (2026-09-28) and the bare "-" made this a
    # 4-word caption with a non-name word in it, so the bot asked "who is
    # it?" about a caption that named him. The OBCL spells these the same
    # way ("Manuel Quiroz - Lebron"), so the spacing is house style, not a
    # typo. Joining is safe: _name_key flattens both spellings anyway.
    cleaned = re.sub(r"(?<=[A-Za-z])\s*[-\u2010-\u2015]\s*(?=[A-Za-z])",
                     "-", cleaned)
    words = cleaned.split()
    if not 2 <= len(words) <= 4:
        return None
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words):
        return None
    # Chatter check runs on each HYPHEN PART, so joining can't sneak a
    # non-name through ("headshot - John Smith" stays a question).
    parts = [q for w in words for q in w.split("-")]
    if any(q.lower().strip(".") in _NOT_NAMES for q in parts):
        return None
    return titlecase_name(cleaned)


# ---- outputs -----------------------------------------------------------------
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _archive_dir() -> Path:
    d = _repo_root() / config.OUTPUT_DIR / datetime.now().strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 '-]", "", name).strip() or "headshot"


def process_one(data: bytes, name: str) -> Path:
    """Run the pipeline and archive the finished headshot, named for the
    person so the admins (and Phase 2) know whose it is."""
    from automations.headshots import process as P
    out = P.process(data)
    path = _archive_dir() / f"{_safe_stem(name)} - Headshot.png"
    out.save(path)
    return path


# Our own posts, recognised WITHOUT trusting a single API call. The 5-min
# tick spent 2026-08-25 asking itself "who is this?" about every headshot it
# had already made: the only guard was `user == auth_test().user_id`, and
# auth_test() sits in a bare try/except — one failed call set `me` to None
# and the guard quietly became a no-op. A finished headshot is an image
# reply like any other, so the loop fed on its own output. Now ANY of these
# marks a message as ours, and no single failure can open the loop again.
_MAX_ASKS_PER_RUN = 3
_OURS_MARKERS = ("— headshot ready", "-- headshot ready", "headshot ready")


def _is_our_post(m: dict, me: str | None) -> bool:
    if m.get("bot_id"):                       # posted by an app (us)
        return True
    if m.get("subtype") == "bot_message":
        return True
    if me and m.get("user") == me:
        return True
    text = (m.get("text") or "").lower()
    if any(k in text for k in _OURS_MARKERS):
        return True
    # Our own output files are always "<Name> - Headshot.png".
    for f in (m.get("files") or []):
        if str(f.get("name", "")).lower().endswith(" - headshot.png"):
            return True
    return False


# ---- OwnerVille upload (Phase 2) ---------------------------------------------
def _ov_upload_note(name: str, photo, act: dict, *,
                    replace: bool = False) -> str:
    """Upload to the rep's OV profile; return the line to append to the
    thread reply. Never raises — an OV problem must not stop the photo post.

    `replace` is only ever set by redo(): a photo already on file is
    overwritten instead of left alone."""
    from automations.headshots import config as _cfg
    if not _cfg.OV_UPLOAD_ENABLED:
        return ""
    try:
        import time as _t

        from automations.headshots.ov_upload import upload
        # Back-to-back uploads in one tick share the persistent browser
        # profile, and Chromium's ProcessSingleton lock does not always clear
        # between them ("profile is already in use"). That threw on Luis
        # Valenzuela and Miley Aragon on 2026-08-31 and told the thread the
        # upload had failed when a plain retry worked — so settle, then retry
        # ONCE before believing it.
        _t.sleep(3)
        try:
            res = upload(name, photo, dry_run=False, headless=True,
                         verbose=True, replace=replace)
        except Exception as first:  # noqa: BLE001
            print(f"  OV attempt 1 failed for {name} ({type(first).__name__}:"
                  f" {str(first)[:100]}) — settling 20s and retrying once")
            _t.sleep(20)
            res = upload(name, photo, dry_run=False, headless=True,
                         verbose=True, replace=replace)
            print(f"  OV retry succeeded for {name}")
        act["ov"] = res
        # A forgiven typo must be VISIBLE — say whose profile it landed on.
        as_who = (f" (matched to *{res['matched_as']}* in OwnerVille)"
                  if res.get("matched_as") else "")
        if res["status"] == "uploaded":
            ok = "" if res.get("verified") else " (verify pill manually)"
            what = ("replaced the photo on their profile"
                    if res.get("replaced") else "uploaded to their profile")
            return (f"\nOwnerVille: {what} ✅{ok}{as_who}"
                    + _sheet_note(name, act))
        if res["status"] == "owner_submitted":
            return ("\nOwnerVille: already *Owner Submitted*, so the photo on "
                    "their profile was NOT replaced — swap it by hand if it "
                    "still needs changing")
        if res["status"] == "owner_submit_unknown":
            return ("\n⚠ OwnerVille: couldn't tell if they're Owner "
                    "Submitted, so the photo was NOT replaced — check and "
                    "swap it by hand")
        if res["status"] == "already_uploaded":
            return ("\nOwnerVille: a photo is already on their profile — "
                    f"left as-is{as_who}" + _sheet_note(name, act))
        return (f"\n⚠ OwnerVille: couldn't find *{name}* in View Progress "
                "(tried every campaign + Show All) — please upload this one "
                "manually")
    except Exception as e:  # noqa: BLE001
        act["ov"] = {"status": "error", "error": str(e)[:200]}
        print(f"  ⚠ OV upload failed for {name}: {type(e).__name__}: "
              f"{str(e)[:150]}")
        return ("\n⚠ OwnerVille: upload didn't go through — please upload "
                "this one manually")


def _sheet_note(name: str, act: dict) -> str:
    """Tick the rep's "Headshot Photo" box on the week's D2D OBCL tab and
    return the line for the thread reply. Never raises — the photo and the
    OV upload already happened; a sheet problem must not hide that.

    Only NEW STARTS have a row (the tab's Name/Last Name columns). Office
    staff submitting their own headshot have no row to tick, which is not an
    error — it is just reported quietly."""
    from automations.headshots import config as _cfg
    if not getattr(_cfg, "SHEET_LOG_ENABLED", True):
        return ""
    try:
        from automations.headshots.sheet_log import log_upload
        res = log_upload(name, verbose=True)
        act["sheet"] = res
        if res["status"] in ("marked", "already_marked"):
            # WHICH tab it landed on is part of the answer. On 2026-09-14 a
            # gap row hid 21 people on the week's tab, the mark went to the
            # rolling stack instead, and this line still said "✅ ticked" —
            # true, and useless. Say so when it isn't the week's tab.
            from automations.headshots.sheet_log import tab_date
            where = ("" if tab_date(res.get("tab", "")) else
                     f" (on the rolling *{res.get('tab', '')}* tab, not this "
                     "week's)")
            if res["status"] == "already_marked":
                return f"\nOBCL Sheet: already ticked{where}"
            as_who = (f" (as *{res['matched_as']}*)"
                      if res.get("matched_as", "").lower() != name.lower()
                      else "")
            return f"\nOBCL Sheet: Headshot Photo ✅ ticked{as_who}{where}"
        # Not on the tab (or too close to two names to be sure). One plain
        # line, Megan's wording (2026-08-24) — the admin just needs to know
        # to log this one by hand; the reason is in the run log.
        return "\nNot found on OBCL Sheet"
    except Exception as e:  # noqa: BLE001
        act["sheet"] = {"status": "error", "error": str(e)[:200]}
        print(f"  ⚠ sheet log failed for {name}: {type(e).__name__}: "
              f"{str(e)[:150]}")
        return "\n⚠ OBCL sheet: couldn't tick the Headshot Photo box"


# ---- the polled processor ----------------------------------------------------
def _week_anchors(cl, channel: str) -> list[dict]:
    """This week's and last week's Monday threads (last week's catches
    stragglers who reply over the weekend)."""
    import datetime as dt

    from automations.headshots import weekly_thread as wt
    anchors = []
    this_mon = wt.week_monday()
    for monday in (this_mon, this_mon - dt.timedelta(days=7)):
        a = wt.find_week_anchor(cl, channel, monday=monday)
        if a and all(a["ts"] != b["ts"] for b in anchors):
            anchors.append(a)
    return anchors


def _name_key_of(s: str) -> str:
    from automations.headshots.ov_upload import _name_key
    return _name_key(s or "")


def redo(name: str, *, dry_run: bool = True,
         channel: str | None = None, office: str = "raf") -> dict:
    """Re-make ONE person's headshot from their ORIGINAL submitted photo.

    Megan 2026-09-28, after the bun bug cut Jordan Jones off at the eyes:
    "redo jordan's". Her reply is marked done and will never reprocess, and
    the archived PNG is the bad one — so this goes back to the photo she
    actually posted, runs it through the fixed pipeline, REPLACES the photo
    on her OwnerVille profile and posts the new headshot in the thread.

    Replacing is the point, so this is a named-person command only and is
    never part of the tick.

    `office` (2026-10-26) picks the row in config.OFFICES. For a LucyEco
    office the new headshot goes to the office's OWN computer as a REPLACE
    job -- the only job that may upload over a photo already on file -- and
    its answer comes back into the thread like any other.
    """
    off = config.OFFICES.get((office or "raf").strip().lower())
    if off is None:
        return {"status": "unknown_office", "name": name,
                "reason": f"no office {office!r} in headshots config.OFFICES"}
    channel = channel or off.channel
    cl = _client()
    me = None
    try:
        me = cl.auth_test().get("user_id")
    except Exception:
        pass

    want = _name_key_of(name)
    found = None                          # newest submission wins
    for anchor in _week_anchors(cl, channel):
        for m in cl.conversations_replies(
                channel=channel, ts=anchor["ts"],
                limit=200).get("messages", []):
            fm = hs_form.parse(m)
            if m.get("ts") == anchor["ts"] or (not fm and _is_our_post(m, me)):
                continue
            imgs = _image_files(m)
            if not imgs:
                continue
            # A form post's name, or (threads from before the form) a caption.
            got = fm[0] if fm else name_from_caption(m.get("text", ""))
            if got and _name_key_of(got) == want:
                if found is None or m["ts"] > found[0]["ts"]:
                    found = (m, imgs[0], anchor, got)
    if found is None:
        return {"status": "no_submission", "name": name,
                "reason": "no photo reply in this week's or last week's "
                          "thread"}

    m, img, anchor, got = found
    out_p = process_one(_download_image(img), got)
    if dry_run:
        return {"status": "would_redo", "name": got, "ts": m["ts"],
                "file": str(out_p)}

    act: dict = {}
    if off.uploader == "lucy":
        ov = _ov_upload_note(got, out_p, act, replace=True)
    elif not off.eco_key or not config.ECO_REDO_READY:
        from automations.headshots import eco
        act["eco"] = {"status": "manual"}
        ov = eco.manual_line(replace=True)
    else:
        from automations.headshots import eco
        try:
            job = eco.enqueue(off.eco_key, got, out_p, mode=off.mode,
                              channel=channel, thread_ts=anchor["ts"],
                              replace=True)
            act["eco"] = {"status": "queued", "job": job, "replace": True}
            ov = eco.queued_line(off.mode, replace=True)
        except Exception as e:  # noqa: BLE001 -- the new photo still posts
            act["eco"] = {"status": "error", "error": str(e)[:200]}
            ov = ("\n⚠ OwnerVille: couldn't hand this to your office "
                  "computer — please replace the photo by hand")
    with open(out_p, "rb") as fh:
        cl.files_upload_v2(
            channel=channel, thread_ts=anchor["ts"], file=fh,
            filename=out_p.name,
            initial_comment=(f"*{got}* — headshot redone ⤵{ov}"
                             + by_hand_tags(ov, hs_form.submitter(m),
                                            off.admin_slack_id)))
    return {"status": "redone", "name": got, "ts": m["ts"],
            "file": str(out_p), **act}


def scan(*, dry_run: bool = True, channel: str | None = None) -> list[dict]:
    """One tick over every LIVE office's threads (config.OFFICES).

    `channel` (the old --channel flag) watches just that channel the way Raf's
    is watched -- Lucy 3 uploads, OBCL sheet ticked."""
    if channel:
        offices = [config.Office(key="raf", owner="Rafael Hidalgo",
                                 channel=channel, uploader="lucy",
                                 mode="live", sheet_log=True)]
    else:
        offices = config.live_offices()
    if not offices:
        raise HeadshotError(
            "No channel to watch. Set config.OFFICES (or pass --channel / "
            "HEADSHOTS_CHANNEL_ID).")

    cl = _client()
    me = None            # Lucy's own user id — never process our own replies
    try:
        me = cl.auth_test().get("user_id")
    except Exception:
        pass

    state = _load_state()
    actions: list[dict] = []
    run = {"asked": 0}
    for off in offices:
        try:
            _scan_office(cl, me, off, state, actions, run, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 -- one office never stops the rest
            print(f"  ⚠ {off.key}: {type(e).__name__}: {str(e)[:150]}")
            actions.append({"ts": "", "action": "office_failed",
                            "office": off.key, "error": str(e)[:200]})

    # LucyEco offices: their computers' answers go back into their threads.
    if any(o.uploader == "eco" and o.eco_key for o in offices):
        from automations.headshots import eco
        admins = {o.eco_key: o.admin_slack_id for o in offices if o.eco_key}
        by_job = {v.get("job"): v.get("by", "") for v in state.values()
                  if isinstance(v, dict) and v.get("job")}

        def tags(r):
            return by_hand_tags(eco.result_line(r), by_job.get(r.get("job_id"), ""),
                                admins.get(str(r.get("office", "")).lower(), ""))
        eco.post_results(cl, dry_run=dry_run, tags=tags)
    return actions


def by_hand_tags(note: str, submitter: str, admin: str) -> str:
    """When a headshot has to be done by hand, tag who submitted it and the
    office's headshot admin (Megan 2026-11-10: "David needs done manually"
    sat there unseen). Returns "" when nothing needs a person."""
    low = (note or "").lower()
    if not any(k in low for k in ("by hand", "manually", "didn't go through")):
        return ""
    who = [u for u in dict.fromkeys([submitter, admin]) if u]
    if not who:
        return ""
    return "\n" + " ".join(f"<@{u}>" for u in who) + " this one needs doing by hand in OwnerVille."


def _state_key(off, ts: str) -> str:
    # Raf's keys stay bare ts -- the state file already holds months of them.
    return ts if off.key == "raf" else f"{off.key}:{ts}"


def _scan_office(cl, me, off, state: dict, actions: list, run: dict, *,
                 dry_run: bool) -> None:
    channel = off.channel
    anchors = _week_anchors(cl, channel)
    if not anchors:
        print(f"No Monday headshot thread up yet in {off.key}'s channel "
              "(weekly_thread posts it).")
        return

    for anchor in anchors:
        replies = cl.conversations_replies(
            channel=channel, ts=anchor["ts"], limit=200).get("messages", [])
        for m in sorted(replies, key=lambda x: x.get("ts", "")):
            if m.get("ts") == anchor["ts"]:
                continue
            # A post from the 📸 Add headshot form (form.py) is Jiraiya's,
            # so it looks like "ours" -- read it BEFORE that check.
            fm = hs_form.parse(m)
            if not fm and _is_our_post(m, me):
                continue
            imgs = _image_files(m)
            if not imgs and fm:
                continue
            if not imgs:
                # A text reply can be a "redo First Last" ask (Megan
                # 2026-10-29: leaders ask in the thread, nobody gets tagged).
                _maybe_redo_reply(cl, off, m, anchor, state, actions, run,
                                  dry_run=dry_run)
                continue
            ts = m["ts"]
            sk = _state_key(off, ts)
            st = state.get(sk, {})
            if st.get("done"):
                continue

            if not fm:
                # FORM ONLY (Megan 2026-11-09: "so we don't have errors"). A
                # photo dropped straight in is never guessed at -- no name
                # read out of chatter, no second photo silently dropped. It
                # gets the 📸 Add headshot button back, once, and is left.
                if not st.get("asked") and run["asked"] < _MAX_ASKS_PER_RUN:
                    run["asked"] += 1
                    actions.append({"ts": ts, "action": "ask_form"})
                    if not dry_run:
                        _ask_with_button(cl, channel, anchor["ts"], m,
                                         "headshots go through the button now, "
                                         "so I get the name right.")
                        state.setdefault(sk, {})["asked"] = True
                        _save_state(state)
                continue
            # The form's fixed line: the name is exactly what they typed, and
            # the Redo box decides whether the profile photo is replaced.
            name, is_redo = fm

            try:
                data = _download_image(imgs[0])
            except HeadshotError as e:
                print(f"  ⚠ SKIPPED ts={ts} — {e}")
                actions.append({"ts": ts, "action": "download_failed",
                                "error": str(e)})
                continue

            out_p = process_one(data, name)
            act = {"ts": ts, "action": "processed", "name": name,
                   "file": str(out_p), "office": off.key}

            if dry_run:
                act["dry_run"] = True
                actions.append(act)
                continue

            # Phase 2: push the clean headshot onto the rep's OwnerVille
            # profile. Best-effort — the thread post below goes out either
            # way, carrying the OV outcome so a miss gets handled by hand.
            if off.uploader == "lucy":
                ov_note = _ov_upload_note(name, out_p, act, replace=is_redo)
            else:
                ov_note = _eco_handoff_note(off, name, out_p, anchor["ts"],
                                            state, sk, act, replace=is_redo)
            what = "headshot redone" if is_redo else "headshot ready"
            by = hs_form.submitter(m)
            state.setdefault(sk, {})["by"] = by
            ov_note += by_hand_tags(ov_note, by, off.admin_slack_id)

            # Post the finished image into the week's thread + ✅ the reply.
            with open(out_p, "rb") as fh:
                cl.files_upload_v2(
                    channel=channel, thread_ts=anchor["ts"], file=fh,
                    filename=out_p.name,
                    initial_comment=f"*{name}* — {what} ⤵{ov_note}")
            state.setdefault(sk, {})["done"] = True
            state[sk]["name"] = name
            _save_state(state)
            try:
                cl.reactions_add(channel=channel, timestamp=ts,
                                 name="white_check_mark")
            except Exception:
                pass
            try:
                from automations.day_orchestrator.hub_publish import publish_done
                publish_done("headshots", "Headshot Bot", "success")
            except Exception:
                pass
            act["posted"] = True
            actions.append(act)


def _ask_with_button(cl, channel: str, thread_ts: str, m: dict,
                     why: str) -> None:
    """Answer a reply the bot can't use with the 📸 Add headshot button
    (form.py), posted by Jiraiya so the tap reaches the form. Plain words
    from Lucy if the button can't be posted."""
    who = m.get("user", "")
    text = f"<@{who}> {why} Tap *📸 Add headshot*."
    if hs_form.post_button(channel, thread_ts, text=text).get("action") == "posted":
        return
    try:
        cl.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=(f"<@{who}> {why} Tap the *📸 Add headshot* button in "
                  "this thread to send it."))
    except Exception:  # noqa: BLE001
        pass


# "redo First Last" (also "Redo: First Last", "redo - First Last").
_REDO_RE = re.compile(r"^\s*redo\b[\s:,\-]*(.+)$", re.I | re.S)
_MAX_REDOS_PER_RUN = 3


def _maybe_redo_reply(cl, off, m: dict, anchor: dict, state: dict,
                      actions: list, run: dict, *, dry_run: bool) -> None:
    """A text reply asking for a "redo": answer with the 📸 Add headshot
    button (a new photo + the Redo box), once per reply. Redos go through the
    form like everything else (Megan 2026-11-09)."""
    if not _REDO_RE.match(m.get("text") or ""):
        return
    ts = m["ts"]
    sk = _state_key(off, ts)
    if state.get(sk, {}).get("done"):
        return
    if run.get("redos", 0) >= _MAX_REDOS_PER_RUN:
        return
    run["redos"] = run.get("redos", 0) + 1
    actions.append({"ts": ts, "action": "redo_needs_form"})
    if dry_run:
        return
    _ask_with_button(cl, off.channel, anchor["ts"], m,
                     "to redo a headshot, tap the button, add a NEW photo "
                     "and tick *Redo*.")
    state.setdefault(sk, {})["done"] = True
    _save_state(state)


def _eco_handoff_note(off, name: str, photo, thread_ts: str, state: dict,
                      sk: str, act: dict, replace: bool = False) -> str:
    """Hand the headshot to the office's own computer (LucyEco) and return the
    line for the thread post. Never raises -- the photo post goes out either
    way. Queued at most once per reply: the job id is saved BEFORE the post,
    so a post that fails and retries next tick cannot queue it twice."""
    from automations.headshots import eco
    if replace and not config.ECO_REDO_READY:
        # Their computer's uploader can't check Owner Submit yet (needs the
        # next agent release) -- so it doesn't get a replace job at all.
        act["eco"] = {"status": "manual", "why": "eco redo not ready"}
        return eco.manual_line(replace=True)
    if not off.eco_key:
        # Live before the office's computer is enrolled: nothing to hand to.
        act["eco"] = {"status": "manual"}
        return eco.manual_line(replace=replace)
    job = (state.get(sk) or {}).get("job")
    if not job:
        try:
            job = eco.enqueue(off.eco_key, name, photo, mode=off.mode,
                              channel=off.channel, thread_ts=thread_ts,
                              replace=replace)
        except Exception as e:  # noqa: BLE001
            act["eco"] = {"status": "error", "error": str(e)[:200]}
            print(f"  ⚠ could not queue {name} for {off.key}'s computer: {e}")
            return ("\n⚠ OwnerVille: couldn't hand this to your office "
                    "computer — please upload it by hand")
        state.setdefault(sk, {})["job"] = job
        _save_state(state)
    act["eco"] = {"status": "queued", "job": job, "replace": replace}
    return eco.queued_line(off.mode, replace=replace)


def diag(channel: str | None = None) -> int:
    """READ-ONLY: say exactly what the tick sees and why it skips each reply.

    Added 2026-08-24 when two submissions sat unprocessed while the tick
    kept logging "No new headshot replies" — the per-reply decision was
    invisible. Touches nothing."""
    channel = channel or config.CHANNEL_ID
    cl = _client()
    try:
        me = cl.auth_test().get("user_id")
    except Exception:
        me = None
    print(f"channel: {channel}   this bot: {me}")
    anchors = _week_anchors(cl, channel)
    print(f"anchors found: {len(anchors)}")
    state = _load_state()
    print(f"state entries: {len(state)}  ({_STATE})")
    for a in anchors:
        print(f"\nanchor ts={a['ts']}  {(a.get('text') or '')[:60]!r}")
        replies = cl.conversations_replies(
            channel=channel, ts=a["ts"], limit=200).get("messages", [])
        print(f"  replies: {len(replies)}")
        for m in sorted(replies, key=lambda x: x.get("ts", "")):
            if m.get("ts") == a["ts"]:
                continue
            ts = m["ts"]
            st = state.get(ts, {})
            imgs = _image_files(m)
            why = []
            if m.get("subtype"):
                why.append(f"subtype={m['subtype']}")
            if _is_our_post(m, me):
                why.append("own message")
            if not imgs:
                why.append(f"no image (files={len(m.get('files') or [])})")
            if st.get("done"):
                why.append("state=DONE")
            nm = name_from_caption(m.get("text", ""))
            verdict = "SKIP: " + ", ".join(why) if why else (
                f"WOULD PROCESS as {nm!r}" if nm else "SKIP: name not parsed")
            print(f"    {ts} u={m.get('user')} "
                  f"txt={(m.get('text') or '')[:28]!r} -> {verdict}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="White-background headshot bot.")
    ap.add_argument("--dry-run", action="store_true",
                    help="process + save previews locally, post nothing")
    ap.add_argument("--channel", default=None,
                    help="channel id to watch (overrides config / env)")
    ap.add_argument("--diag", action="store_true",
                    help="READ-ONLY: show what the tick sees per reply")
    ap.add_argument("--file", default=None,
                    help="process ONE local photo instead of polling Slack")
    ap.add_argument("--name", default=None,
                    help="the person's name (with --file)")
    ap.add_argument("--office", default="raf",
                    help="with --redo: whose thread (a key in headshots "
                         "config.OFFICES, e.g. omar). Default raf.")
    ap.add_argument("--redo", default=None, metavar="FIRST LAST",
                    help="re-make ONE person's headshot from the photo they "
                         "posted and REPLACE it on their OwnerVille profile "
                         "(for one that came out wrong)")
    args = ap.parse_args(argv)

    if args.diag:
        return diag(channel=args.channel)

    if args.redo:
        res = redo(args.redo, dry_run=args.dry_run, channel=args.channel,
                   office=args.office)
        print(res)
        return 0 if res["status"] in ("redone", "would_redo") else 1

    if args.file:
        if not args.name:
            ap.error("--file needs --name \"First Last\"")
        out_p = process_one(Path(args.file).read_bytes(),
                            titlecase_name(args.name))
        print(f"headshot: {out_p}")
        return 0

    if not acquire_lock():
        print("Another headshots run is active — skipping this tick.")
        return 0
    try:
        actions = scan(dry_run=args.dry_run, channel=args.channel)
    finally:
        release_lock()

    if not actions:
        print("No new headshot replies.")
        return 0
    for a in actions:
        if a["action"] == "download_failed":
            print(f"  download failed: ts={a['ts']}")
        elif a["action"] in ("ask_form", "redo_needs_form"):
            print(f"  pointed to the button: ts={a['ts']}")
        elif a["action"] == "office_failed":
            print(f"  office {a['office']} failed: {a['error']}")
        elif a.get("dry_run"):
            print(f"  WOULD post: {a['name']}  [{a['file']}]")
        else:
            print(f"  POSTED: {a['name']}")
    if any(a["action"] in ("download_failed", "office_failed")
           for a in actions):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
