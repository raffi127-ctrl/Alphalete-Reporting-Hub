"""Read what the office computers answered, and tell the right person.

    social_post answered "posted"      -> 🚀 + "Posted to Instagram, Facebook"
                                          in the photo's thread
    social_post "signed_out" / "no_channels"
                                       -> a short note in the thread + a DM to
                                          the owner; it tries again on a later
                                          day once Zoho is back
    social_check (once a day)          -> DM the owner ONLY when one of the
                                          pages THEY CHOSE is missing, or Zoho
                                          signed them out. Pages they never
                                          picked are none of our business.
    zoho_signin                        -> printed, for the install call

THE SAME DM IS SENT AT MOST ONCE A DAY. A page that stays disconnected for a
week gets one nudge a day, not one every pass.

AN ERROR MID-POST IS NOT RETRIED. Zoho may have published before it broke,
and a retry would put the photo up twice. It is logged for us, never posted
in the office's room.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

_NAMES = {"instagram": "Instagram", "facebook": "Facebook", "google": "Google",
          "linkedin": "LinkedIn", "x": "X"}
# The daily check opens Zoho on the owner's screen for a few seconds, so it
# asks mid-day, not first thing in the morning or at night.
CHECK_HOURS = (11, 15)


def _load(path: Path) -> Dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, d: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2))


def _today(P) -> dt.date:
    return dt.datetime.now(ZoneInfo(P.timezone)).date()


def connected_pages(channels) -> set:
    from automations.brand_audit.zoho_draft import page_of
    return {page_of(c) for c in channels or ()} - {None}


def problems(P, result: Dict) -> List[str]:
    """What the owner has to fix, as page keys ('zoho' = signed out)."""
    if result.get("status") == "signed_out":
        return ["zoho"]
    have = connected_pages(result.get("channels"))
    return [p for p in P.pages if p not in have]


def dm_text(P, probs: List[str]) -> str:
    if probs == ["zoho"]:
        return (f":warning: *Lucy can't post for {P.business_name}*: Zoho Social is "
                "signed out on your office computer. Open Zoho Social there and "
                "sign back in; Lucy picks it up on her own.")
    names = " and ".join(_NAMES.get(p, p) for p in probs)
    return (f":warning: *Lucy can't post to your {names}*: "
            f"{'it is' if len(probs) == 1 else 'they are'} disconnected in Zoho "
            "Social. Open Zoho Social → Settings → Channels and reconnect "
            f"{names}. Nothing else is needed.")


def _dm(P, cl, probs: List[str], state: Dict, dry: bool) -> Dict:
    key, today = ",".join(sorted(probs)), _today(P).isoformat()
    sent = state.setdefault("dm_sent", {})
    if sent.get(key) == today:
        return {"action": "dm_already_sent_today", "note": key}
    act = {"action": "dm_owner", "note": dm_text(P, probs)}
    if not dry:
        cl.chat_postMessage(channel=P.owner_slack_id, text=act["note"])
        sent[key] = today
    return act


def collect(P, rows: List[Dict], cl, *, dry: bool) -> List[Dict]:
    """Act on one office's answered jobs. Returns actions; the caller marks
    the jobs read (only on a live pass)."""
    from automations.brand_audit import social_inbox as S
    inbox_file, watch_file = P.path("social_inbox.json"), P.path("watch.json")
    inbox, state = S._load_state(inbox_file), _load(watch_file)
    by_job = {st.get("eco_job"): (ts, st) for ts, st in inbox.items()
              if isinstance(st, dict) and st.get("eco_job")}
    acts: List[Dict] = []
    for r in rows:
        res, kind = r.get("result") or {}, r.get("kind")
        status = res.get("status")
        if kind == "zoho_signin":
            acts.append({"action": f"zoho_signin_{status}",
                         "note": ", ".join(res.get("channels") or []) or "no pages"})
            continue
        if kind == "social_check":
            state["last_check"] = {"day": _today(P).isoformat(), "result": res}
            probs = problems(P, res)
            acts.append({"action": "check_ok" if not probs else "check_problem",
                         "note": ", ".join(probs) or "all chosen pages connected"})
            if probs:
                acts.append(_dm(P, cl, probs, state, dry))
            continue
        # social_post
        ts, st = by_job.get(r.get("job_id"), (None, None))
        if st is None:
            acts.append({"action": "post_answer_unmatched", "note": r.get("job_id")})
            continue
        if status == "posted":
            pages = sorted(connected_pages(res.get("channels")))
            acts.append({"ts": ts, "action": "posted",
                         "note": ", ".join(_NAMES[p] for p in pages)})
            if not dry:
                cl.chat_postMessage(channel=P.slack_channel, thread_ts=ts,
                                    text=":rocket: *Posted* to "
                                    + ", ".join(_NAMES[p] for p in pages) + ".")
                try:
                    cl.reactions_add(channel=P.slack_channel,
                                     name=S.SOCIAL_POSTED_EMOJI, timestamp=ts)
                except Exception:
                    pass
                st.update(published=True, posted=True)
        elif status in ("signed_out", "no_channels"):
            probs = problems(P, res) or ["zoho"]
            acts.append({"ts": ts, "action": "post_blocked", "note": ",".join(probs)})
            if not dry:
                cl.chat_postMessage(channel=P.slack_channel, thread_ts=ts,
                                    text=":hourglass_flowing_sand: Approved, but it "
                                    "can't go out yet: the owner needs to reconnect "
                                    "Zoho. Lucy will post it once that's fixed.")
                st.pop("eco_job", None)       # re-queued on a later day
            acts.append(_dm(P, cl, probs, state, dry))
        else:
            acts.append({"ts": ts, "action": "post_error",
                         "error": res.get("error") or status})
            if not dry:
                st["post_error"] = res.get("error") or status   # never retried
    if not dry:
        S._save_state(inbox, inbox_file)
        _save(watch_file, state)
    return acts


def ensure_daily_check(P, *, live: bool) -> Dict | None:
    """Queue today's social_check once, mid-day on the office's clock."""
    from automations.online_presence import relay
    state_file = P.path("watch.json")
    state = _load(state_file)
    now = dt.datetime.now(ZoneInfo(P.timezone))
    day = now.date().isoformat()
    if state.get("check_queued") == day or not (CHECK_HOURS[0] <= now.hour < CHECK_HOURS[1]):
        return None
    if not live:
        return {"action": "would_queue_check"}
    job = relay.enqueue(P.key, "social_check", {}, live=True)
    state["check_queued"] = day
    _save(state_file, state)
    return {"action": "check_queued", "note": job}
