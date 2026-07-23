"""Post the captured tracker PNGs into their OWN dated thread -- in BOTH
#alphalete-sales AND #top-leaders-alphalete-org.

Each channel gets its OWN copy of the thread (Slack can't share one thread across
channels): a bold dated parent + one ":emoji: Tracker Name" line per tracker,
then each PNG as a threaded reply captioned "*Tracker Name - Mon D*" with the
tracker's emoji reacted onto the parent (the header's checkmark-emoji row).

Layout mirrors the Metrics thread (Megan 2026-07-04). The automation creates its
OWN parent in each channel each morning (find-or-create), posted AS Lucy -- no
human, no dependency on Jolie's post, not the Metrics thread.

Reuses the shared Slack token path (slack_metrics_post._client -> the 'Lucy'
xoxp user token that daily_metrics uses) and files_upload_v2.

NOTE: #top-leaders-alphalete-org (C067TTGFEFR) is PRIVATE -- Lucy must be a
member or files_upload_v2 there fails with not_in_channel.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from automations.shared import slack_metrics_post as smp

# The same 8 COUNTRY-wide trackers go to three orgs (Raf, 2026-07-14). Same
# images everywhere -- these are country/org-wide boards, not per-office cuts,
# which is why the title dropped "Alphalete". One card per org on the Hub, same
# convention as rashad_metrics (#elevate-sales) / aya_metrics (#indelible-sales).
# Lucy (U0BCFGCR5PV) is a MEMBER of all four channels -- verified 2026-07-14. The
# three private ones (#top-leaders, #elevate-sales, #indelible-sales) fail
# files_upload_v2 with not_in_channel if she is ever removed.
ORG_CHANNELS = {
    "alphalete":   ["C068PH3RFSM",        # #alphalete-sales
                    "C067TTGFEFR"],       # #top-leaders-alphalete-org (private)
    "elevate":     ["C0B3KTCCMT7"],       # #elevate-sales (private)
    "indelible":   ["C0AA85Y3FPE"],       # #indelible-sales (private)
    "palace":      ["C09AVM17PAR"],       # #palace-sales (private)
    "elite_prime": ["C06A6A8ED34"],       # #elite-prime-sales (private)
    "carlos_gp":   ["C07J46MQNUX"],       # #alphalete-gp-sales (private, Carlos)
    "ambient_1":   ["C0B1DHEFVLH"],       # #ambient-sales-1 (private, Cy Wade)
    "aeon":        ["C0849EPM4LD"],       # #aeon-sales (private, Cody Cannon)
    "domin8":      ["C0B395PUUCW"],       # #domin8-b2b-sales (private) — Lucy
                                          # (U0BCFGCR5PV) must be a MEMBER or
                                          # files_upload_v2 → not_in_channel.
}
ORGS = list(ORG_CHANNELS)
DEFAULT_ORG = "alphalete"

# Human labels for the Hub card / logs.
ORG_LABEL = {"alphalete": "#alphalete-sales + #top-leaders-alphalete-org",
             "elevate": "#elevate-sales",
             "indelible": "#indelible-sales",
             "palace": "#palace-sales",
             "elite_prime": "#elite-prime-sales",
             "carlos_gp": "#alphalete-gp-sales",
             "ambient_1": "#ambient-sales-1",
             "aeon": "#aeon-sales",
             "domin8": "#domin8-b2b-sales"}

# Per-org tracker ORDER override (Carlos wants the B2B trackers + Box first in his
# channel, 2026-07-14). An org NOT listed here posts in the default pages.py
# order. A tracker id missing from a listed order still posts — appended after the
# listed ones, in default order — so adding a new tracker never silently drops it
# from a custom-ordered feed. Keys are org keys from ORG_CHANNELS; values are
# lists of tracker ids (pages.py `id`s).
ORG_ORDER: dict[str, list[str]] = {
    # Carlos wants B2B (AT&T, CRU, Box, D2D) first, then the AT&T/NDS/Fiber ones.
    "carlos_gp": [
        "b2b_att_country", "b2b_att_country_cru", "b2b_box",
        "b2b_d2d_consolidated", "att_country", "att_country_internet_only",
        "nds", "quantum_fiber",
    ],
}

# Per-org tracker SELECTION — a channel that wants only a SUBSET of the trackers.
# An org listed here posts EXACTLY these ids, in this order, and NOTHING else; the
# list doubles as its order (no ORG_ORDER entry needed). An org NOT listed posts
# the default org-wide set (pages.default_ids() — everything not opt_in_only),
# still subject to its ORG_ORDER override if any. This is also the ONLY way an
# opt_in_only tracker (e.g. order_tiered_bonus) reaches a channel — so a
# channel-specific board can't leak org-wide.
#
# Cesar/Domin8 2026-07-23: #domin8-b2b-sales wants just B2B AT&T ("National
# Tracker"), B2B AT&T CRU ("National CRU"), and the Order Tiered Bonus ranking.
ORG_TRACKERS: dict[str, list[str]] = {
    "domin8": ["b2b_att_country", "b2b_att_country_cru", "order_tiered_bonus"],
}


def tracker_ids_for(org: str, pages: list) -> list:
    """The tracker ids `org` posts, in post order. An ORG_TRACKERS selection wins
    (that IS the channel's whole feed + order); otherwise the default org-wide set
    = every tracker not marked opt_in_only. Unknown ids in a selection are dropped
    defensively so a typo can't crash the run — it just posts one fewer board."""
    have = {p["id"] for p in pages}
    sel = ORG_TRACKERS.get(org)
    if sel is not None:
        return [t for t in sel if t in have]
    from automations.tableau_screenshots import pages as _pages_mod
    keep = set(_pages_mod.default_ids())
    return [p["id"] for p in pages if p["id"] in keep]


def select_for_org(captures: list, pages: list, org: str) -> tuple:
    """Filter + order `captures` and `pages` down to what ORG actually posts.
    Shared by post_all and preview_dm so a preview shows EXACTLY the channel's
    real feed — same subset, same order — and the two can't drift. Returns
    (captures, pages, wanted_ids)."""
    wanted = tracker_ids_for(org, pages)
    wanted_set = set(wanted)
    caps = [c for c in captures if c[0]["id"] in wanted_set]
    pgs = [p for p in pages if p["id"] in wanted_set]
    # An ORG_TRACKERS selection IS its order; otherwise honor any ORG_ORDER
    # override (Carlos's B2B-first). Reorder header (pages) + replies (captures).
    order_ids = wanted if org in ORG_TRACKERS else ORG_ORDER.get(org)
    if order_ids:
        caps = _ordered(caps, lambda c: c[0]["id"], order_ids)
        pgs = _ordered(pgs, lambda p: p["id"], order_ids)
    return caps, pgs, wanted


def _ordered(items: list, id_of, order_ids: list[str] | None) -> list:
    """Reorder `items` by `order_ids` (tracker ids). Items whose id isn't listed
    keep their original relative order, appended after the listed ones (stable
    sort), so a partial order never drops or shuffles the rest."""
    if not order_ids:
        return list(items)
    rank = {tid: i for i, tid in enumerate(order_ids)}
    return sorted(items, key=lambda it: rank.get(id_of(it), len(order_ids)))


def channels_for(org: str) -> list:
    """The channel id(s) this org posts into. Set TABLEAU_TRACKERS_CHANNEL_ID to a
    single scratch channel while building to keep every real channel safe (it
    overrides the whole list, for every org)."""
    override = os.environ.get("TABLEAU_TRACKERS_CHANNEL_ID")
    if override:
        return [override]
    try:
        return list(ORG_CHANNELS[org])
    except KeyError:
        raise SystemExit(f"unknown org {org!r}. known: {', '.join(ORGS)}")


TITLE_PREFIX = "Tableau Country Trackers"
# The pre-2026-07-14 title. Kept ONLY so find_thread_ts still recognises a thread
# posted under the old name (otherwise a same-day rerun would not find today's
# parent and would post a SECOND tracker thread into the channel). Retitled in
# place on the next touch; delete this once no live thread uses it.
_LEGACY_TITLE_PREFIX = "Alphalete Tableau Trackers"


def header_title(today: dt.date) -> str:
    """'Tableau Country Trackers 7/14/2026' (M/D/YYYY, matches Megan's spec)."""
    return f"{TITLE_PREFIX} {today.month}/{today.day}/{today.year}"


def _legacy_title(today: dt.date) -> str:
    return f"{_LEGACY_TITLE_PREFIX} {today.month}/{today.day}/{today.year}"


LATE_NOTE = "_(data lands ~7am — image posts then)_"


def header_text(pages: list, today: dt.date, pending_late=()) -> str:
    """Bold dated title + one ':react: Title' line per tracker (parent message).

    A tracker id in `pending_late` gets a note after its name: it IS listed, in
    its normal order, but its image isn't in the thread yet (see pages.py `late`).
    Without the note a reader just sees a tracker with no image and assumes the
    automation broke — which is exactly the report we got. The catch-up run drops
    the note when it posts the image."""
    pending = set(pending_late or ())
    lines = [f"*{header_title(today)}*", ""]
    lines += [f":{p['react']}: {p['title']}"
              + (f"  {LATE_NOTE}" if p["id"] in pending else "")
              for p in pages]
    return "\n".join(lines)


def reply_caption(spec: dict, today: dt.date) -> str:
    """'*AT&T Internet Country Sales Tracker - Jul 4*' -- bold, name + date."""
    return f"*{spec['title']} - {today.strftime('%b')} {today.day}*"


def find_thread_ts(client, channel: str, today: dt.date):
    """(ts, is_legacy) of today's tracker parent in `channel`, or (None, False).

    Matches the CURRENT title first, then the legacy one — a thread posted this
    morning under the old name must still be found, or a rerun would post a
    second tracker thread into the same channel."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    title, legacy = header_title(today), _legacy_title(today)
    resp = client.conversations_history(
        channel=channel, oldest=str(oldest), limit=200)
    msgs = resp.get("messages", [])
    for msg in msgs:
        if title in (msg.get("text", "") or ""):
            return (msg.get("thread_ts") or msg.get("ts")), False
    for msg in msgs:
        if legacy in (msg.get("text", "") or ""):
            return (msg.get("thread_ts") or msg.get("ts")), True
    return None, False


def ensure_thread(client, channel: str, pages: list, today: dt.date,
                  pending_late=()) -> dict:
    """Find today's tracker parent in `channel` or create it (bold header, Lucy).
    A parent still carrying the legacy title is RETITLED in place, so today's
    thread ends up reading the same as every other channel's."""
    ts, is_legacy = find_thread_ts(client, channel, today)
    if ts:
        if is_legacy:
            try:
                client.chat_update(channel=channel, ts=ts,
                                   text=header_text(pages, today, pending_late))
                print(f"  {channel}: retitled today's parent → {header_title(today)}",
                      flush=True)
            except Exception as e:
                print(f"  {channel}: retitle skipped ({type(e).__name__})", flush=True)
        return {"thread_ts": ts, "created": False}
    resp = client.chat_postMessage(channel=channel,
                                   text=header_text(pages, today, pending_late))
    return {"thread_ts": resp.get("ts"), "created": True}


def _unescape(text: str) -> str:
    """Slack stores message text HTML-escaped, so the caption we sent as
    'AT&T Internet Country Sales Tracker' reads back as 'AT&amp;T ...'. Verified
    against the live 2026-07-16 thread: 4 of the 8 titles contain '&', and a raw
    comparison missed every one of them. Slack escapes only these three."""
    return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def _reply_matches(msg: dict, spec: dict, today: dt.date) -> bool:
    """Is this thread reply the image for `spec`? Matched on the caption text OR
    the attached filename -- both are derived from the tracker's title, and either
    alone is enough. Two signals because Slack does not guarantee `initial_comment`
    survives as the file-share message's `text` in every upload path; a false
    negative here would re-post a duplicate image."""
    needle = f"{spec['title']} - {today.strftime('%b')} {today.day}"
    if needle in _unescape(msg.get("text") or ""):
        return True
    want = f"{_sanitize_title(spec['title'])}.png"
    return any((f.get("name") or "") == want for f in (msg.get("files") or []))


def _sanitize_title(name: str) -> str:
    """Mirror of capture._sanitize (the PNG filename), imported lazily to keep
    this module free of the capture/browser stack."""
    from automations.tableau_screenshots.capture import _sanitize
    return _sanitize(name)


def _image_replies(client, channel: str, thread_ts: str) -> list:
    resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    return [m for m in resp.get("messages", [])
            if m.get("ts") != thread_ts and m.get("files")]


def posted_ids(client, channel: str, thread_ts: str, pages: list,
               today: dt.date) -> set:
    """Tracker ids that ALREADY have an image reply under today's parent.

    Identity, not arithmetic. The old check compared a COUNT of replies to the
    number of images being posted, which silently skipped any run that posts a
    subset: the Box catch-up posts 1 image into a thread that already holds 7, and
    `7 >= 1` read as "already done" -- Box would never have posted."""
    msgs = _image_replies(client, channel, thread_ts)
    return {p["id"] for p in pages
            if any(_reply_matches(m, p, today) for m in msgs)}


def delete_image_replies(client, channel: str, thread_ts: str, pages: list,
                         today: dt.date, only_ids=None) -> int:
    """Delete the IMAGE replies under today's parent (the parent itself is never
    touched, so the thread link + its reactions survive). Used by --replace to
    re-post a corrected set of images IN ORDER: Slack appends replies, so a single
    re-upload would land at the bottom instead of in its header position.

    SCOPED by `only_ids` (default: only what this run is re-posting). A blanket
    wipe would delete a LATE tracker's image too -- the morning report's retry
    runs `--orgs X --replace` with only its own 7 boards, so after Box has landed
    an unscoped delete would take Box out and never put it back. An unrecognised
    reply (hand-posted, or a tracker since removed from pages.py) is left alone."""
    want = set(only_ids) if only_ids is not None else {p["id"] for p in pages}
    by_id_ = {p["id"]: p for p in pages}
    deleted = 0
    for msg in _image_replies(client, channel, thread_ts):
        spec = next((by_id_[i] for i in want
                     if i in by_id_ and _reply_matches(msg, by_id_[i], today)), None)
        if spec is None:
            continue
        for f in msg.get("files") or []:
            try:
                client.files_delete(file=f["id"])
            except Exception:
                pass          # already gone, or removed with the message
        try:
            client.chat_delete(channel=channel, ts=msg["ts"])
            deleted += 1
        except Exception:
            pass              # files_delete can take the message with it
    return deleted


def _post_to_channel(client, channel: str, captures: list, pages: list,
                     today: dt.date, replace: bool = False,
                     late_all=()) -> dict:
    """Ensure the parent + post every image reply (with parent reaction) in one
    channel. A failure in one channel is caught by the caller so the others still
    post.

    IDEMPOTENT — posting the same day twice must not duplicate. This matters
    because a partial run exits non-zero and the ORCHESTRATOR RETRIES IT (up to
    MAX_RUN_RETRIES): without this, every retry would append another set of images
    to the channels that already succeeded, so healing one broken channel would
    trash the healthy ones. Scoped to THIS RUN'S trackers (`captures`) — a run
    never reads or touches a reply for a tracker it isn't posting:
      this run's trackers all present -> SKIP (ok, nothing posted)
      some present, some missing      -> clear THIS RUN'S + re-post them in order
      none present                    -> post
      replace=True                    -> always clear THIS RUN'S + re-post in order

    "Clear + re-post" rather than "append the missing" is deliberate: Slack appends
    replies, so topping up a half-finished set would leave the images out of header
    order. The clear is scoped by tracker id, so a LATE tracker already sitting in
    the thread survives a morning-batch retry.
    """
    mine = [spec["id"] for spec, _ in captures]
    # Late trackers this run ISN'T posting are the ones still owed — that's both
    # the note a fresh header carries AND, after a late run posts, what's left.
    pending_late = [i for i in (late_all or []) if i not in set(mine)]
    thread = ensure_thread(client, channel, pages, today, pending_late)
    thread_ts = thread["thread_ts"]
    removed = 0
    already = (set() if thread["created"]
               else posted_ids(client, channel, thread_ts, pages, today))
    have = already & set(mine)
    if not replace and captures and len(have) == len(mine):
        print(f"  {channel}: already has today's {len(have)} image(s) for this "
              f"run — skipping (nothing re-posted)", flush=True)
        # present_ids = every tracker already in today's thread (the full posted
        # set, not just this run's `mine`), so the caller can tell a board that's
        # genuinely absent from one that a prior run already delivered.
        return {"channel": channel, "thread_ts": thread_ts, "created": False,
                "posted": [], "removed": 0, "skipped": True, "ok": True,
                "present_ids": sorted(already)}
    if (replace or have) and not thread["created"]:
        removed = delete_image_replies(client, channel, thread_ts, pages, today,
                                       only_ids=mine)
        if removed:
            why = "replacing" if replace else "healing a partial set"
            print(f"  {channel}: cleared {removed} old image reply(ies) ({why})",
                  flush=True)
    results = []
    for spec, png in captures:
        up = client.files_upload_v2(
            channel=channel, thread_ts=thread_ts, file=str(png),
            filename=Path(png).name, initial_comment=reply_caption(spec, today))
        out = {"id": spec["id"], "ok": up.get("ok"),
               "file": (up.get("file") or {}).get("id")}
        try:
            r = client.reactions_add(
                channel=channel, timestamp=thread_ts, name=spec["react"])
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            out["reaction_warning"] = str(e)[:80]
        results.append(out)
        # Slack posts a large file's message LATER than a small one uploaded
        # after it, so images land out of header order. Pause so each image's
        # message posts before the next upload starts (keeps them in order).
        time.sleep(3)
    # A late tracker just landed -> drop its "(data lands ~7am)" note from the
    # header, so the thread stops advertising something it's already delivered.
    # Best-effort: the image is what matters, and a stale note beats a failed run.
    if not thread["created"] and (set(mine) & set(late_all or ())):
        try:
            client.chat_update(channel=channel, ts=thread_ts,
                               text=header_text(pages, today, pending_late))
        except Exception as e:  # noqa: BLE001
            print(f"  {channel}: header note not cleared ({type(e).__name__}) — "
                  f"image posted fine", flush=True)
    # present_ids = what's in the thread AFTER this run: the boards already there
    # that we did NOT clear, plus the ones we just posted successfully. Lets the
    # caller distinguish a genuinely-absent board from one already delivered.
    present = (already - set(mine)) | {r["id"] for r in results if r.get("ok")}
    return {"channel": channel, "thread_ts": thread_ts,
            "created": thread["created"], "posted": results, "removed": removed,
            "skipped": False,
            "ok": all(r.get("ok") for r in results) if results else False,
            "present_ids": sorted(present)}


def _preview_into(client, channel: str, captures: list, pages: list,
                  today: dt.date, *, label: str | None = None) -> dict:
    """Post the PREVIEW thread (banner header + image replies) into one DM/MPIM.

    `label` names the channel(s) this preview is FOR (e.g. '#domin8-b2b-sales'),
    so the banner can't claim it's for a channel it isn't — a scoped preview must
    say exactly which channel it mirrors, or a reader thinks another channel is
    about to change (Megan 2026-07-23)."""
    where = f"to {label}" if label else "to its channel(s)"
    banner = (f"*(PREVIEW — this is what will post {where}; nothing has been "
              "posted to the channels yet.)*\n\n")
    hdr = client.chat_postMessage(channel=channel,
                                  text=banner + header_text(pages, today))
    ts = hdr["ts"]
    posted = []
    for spec, png in captures:
        up = client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(png),
            filename=Path(png).name, initial_comment=reply_caption(spec, today))
        posted.append({"id": spec["id"], "ok": up.get("ok")})
        # Same ordering guard as the live post (_post_to_channel): Slack posts a
        # big file's message LATER than a small one uploaded after it, so without
        # this pause the replies land out of header order — which is exactly what
        # the first Domin8 preview showed (Megan 2026-07-23).
        time.sleep(3)
    return {"channel": channel, "thread_ts": ts, "posted": posted,
            "ok": all(p.get("ok") for p in posted) if posted else False}


def preview_dm(captures: list, pages: list, users: list,
               today: dt.date | None = None, *, dry_run: bool = False,
               org: str | None = None) -> dict:
    """DM the thread (header + real image replies) to `users` for review, posting
    NOTHING to the channels. Tries one group DM (both people in one thread); falls
    back to an individual DM each if the workspace blocks MPIMs. Sent AS Lucy (the
    identity that will post for real).

    `org` scopes the preview to that channel's real feed (same subset + order as
    the live post) — so previewing #domin8-b2b-sales DMs just its 3 boards, not
    all of them. Omit to preview the full captured set."""
    today = today or dt.date.today()
    # The banner must name the channel(s) this preview is FOR — the org's label
    # when scoped, else the default org's (which is what an unscoped preview
    # mirrors). Never a hardcoded channel (Megan 2026-07-23: a domin8 preview that
    # said "#alphalete-sales" read as though alphalete's post was changing).
    label = ORG_LABEL.get(org or DEFAULT_ORG)
    if org is not None:
        captures, pages, _ = select_for_org(captures, pages, org)
    if dry_run:
        return {"dry_run": True, "to_users": users, "label": label,
                "header": header_text(pages, today),
                "replies": [{"file": Path(p).name,
                             "caption": reply_caption(s, today)}
                            for s, p in captures]}
    # Use the USER token (_client) -- on the mini that's Lucy, and it's the token
    # rashad_metrics' review run already uses to DM Megan + Raf (the bot token
    # isn't installed on the mini).
    client = smp._client()
    user_ids = [smp._resolve_user_id(client, u) for u in users]
    try:
        channel = client.conversations_open(
            users=",".join(user_ids))["channel"]["id"]
        res = _preview_into(client, channel, captures, pages, today, label=label)
        return {"ok": res["ok"], "mode": "group_dm", "user_ids": user_ids,
                **res}
    except Exception as e:
        print(f"  group DM unavailable ({type(e).__name__}) — DMing each "
              f"individually.", flush=True)
        results = []
        for uid in user_ids:
            ch = client.conversations_open(users=uid)["channel"]["id"]
            results.append(_preview_into(client, ch, captures, pages, today,
                                         label=label))
        return {"ok": all(r["ok"] for r in results), "mode": "individual_dms",
                "user_ids": user_ids, "results": results}


def retitle_today(pages: list, today: dt.date | None = None,
                  *, org: str = DEFAULT_ORG) -> dict:
    """Rename today's ALREADY-POSTED parent to the current title, touching nothing
    else. For the day the title changes: the images under the old thread are fine,
    so re-posting them just to fix the header would churn every reply's timestamp.
    Never creates a thread; a no-op if today's parent is already current."""
    today = today or dt.date.today()
    client = smp._client()
    out = []
    for channel in channels_for(org):
        ts, is_legacy = find_thread_ts(client, channel, today)
        if not ts:
            out.append({"channel": channel, "status": "no thread today"})
            continue
        if not is_legacy:
            out.append({"channel": channel, "status": "already current"})
            continue
        try:
            # Keep the "still coming" note on any late tracker whose image isn't
            # in the thread yet — a retitle must not quietly promise it landed.
            from automations.tableau_screenshots import pages as _pages_mod
            done = posted_ids(client, channel, ts, pages, today)
            pending_late = [i for i in _pages_mod.late_ids() if i not in done]
            client.chat_update(channel=channel, ts=ts,
                               text=header_text(pages, today, pending_late))
            out.append({"channel": channel, "status": "retitled", "ts": ts})
        except Exception as e:
            out.append({"channel": channel,
                        "status": f"FAILED {type(e).__name__}: {str(e)[:80]}"})
    return {"org": org, "results": out}


def post_all(captures: list, pages: list, today: dt.date | None = None,
             *, dry_run: bool = False, replace: bool = False,
             org: str = DEFAULT_ORG) -> dict:
    """Post the thread + one image reply per captured tracker, to every channel
    this ORG posts into. `captures` is (spec, png_path) in post order; `pages` is
    the full ordered list used to build the header (so the header lists every
    tracker even if one failed to capture). replace=True re-posts today's thread:
    clear the old image replies, then post this set in order (for a same-day crop
    fix). An org in ORG_ORDER gets its own tracker order (header + replies).

    A LATE tracker (pages.py `late`) that this run isn't posting is annotated in
    the header as still coming. Note the header keeps its normal ORDER either way
    (Megan 2026-07-16) — Box stays where it belongs in the list even though its
    image lands last in the thread, because Slack only ever appends replies."""
    today = today or dt.date.today()
    channels = channels_for(org)
    from automations.tableau_screenshots import pages as _pages_mod

    # Filter + order to THIS org's tracker selection FIRST (a subset channel like
    # #domin8-b2b-sales, and the only route an opt_in_only board takes to a
    # channel). Drops both the header line (pages) and the image reply (captures)
    # for anything this org doesn't post, so nothing downstream re-introduces it.
    captures, pages, wanted = select_for_org(captures, pages, org)
    wanted_set = set(wanted)

    # Only the late trackers THIS org actually posts can be "still coming".
    late_all = [i for i in _pages_mod.late_ids() if i in wanted_set]
    pending_late = [i for i in late_all
                    if i not in {spec["id"] for spec, _ in captures}]

    if dry_run:
        return {
            "dry_run": True,
            "replace": replace,
            "org": org,
            "channels": list(channels),
            "pending_late": pending_late,
            "header": header_text(pages, today, pending_late),
            "replies": [
                {"file": Path(p).name, "caption": reply_caption(spec, today),
                 "react": spec["react"]}
                for spec, p in captures
            ],
        }

    client = smp._client()
    channel_results = []
    for channel in channels:
        try:
            channel_results.append(
                _post_to_channel(client, channel, captures, pages, today,
                                 replace=replace, late_all=late_all))
        except Exception as e:
            channel_results.append(
                {"channel": channel, "ok": False,
                 "error": f"{type(e).__name__}: {str(e)[:120]}"})

    return {
        "ok": all(c.get("ok") for c in channel_results) if channel_results else False,
        "org": org,
        "channels": channel_results,
    }
