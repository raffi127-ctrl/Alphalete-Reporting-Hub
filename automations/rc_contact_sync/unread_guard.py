"""Leave customer texts the way Lucy found them: Unread stays Unread.

Carlos 2026-11-27: "we need to make sure we leave customer responses unread
if you're the one that opened it." Taylor works her RingCentral inbox by the
Unread marker, so a customer reply that Lucy's own run turned Read -- reading
the thread, or texting into it (RingCentral marks a conversation read when a
text goes out in it) -- would look handled when nobody has answered it.

Every text job (delivered, wrap-up, check-ins, resends, one-off texts, the
inbox reads) runs inside `guarded(main)`:
  1. before: note every INBOUND text on Taylor's watched line, last
     LOOKBACK_DAYS, that is Unread;
  2. run the job;
  3. after: any of those that is now Read is set back to Unread.

Only messages that were Unread when the job started are touched, so a text
Taylor had already read stays read. Fails open: if the snapshot can't be
taken (no creds, network), the job still runs and the log says the guard was
off; a restore failure is logged, never turns a green run red.

Python 3.9-safe.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Dict, Optional, Set, Tuple

LOOKBACK_DAYS = 45


def _watch() -> Tuple[str, str]:
    from automations.rc_contact_sync import config as C
    from automations.rc_contact_sync import ringcentral as RC
    creds = C.rc_creds()
    token = RC.token(creds, jwt=creds["watch_jwt"]) if creds.get("watch_jwt") else RC.token(creds)
    return token, str(creds["watch_extension_id"])


def unread_inbound(msgs) -> Set[str]:
    return {str(m.get("id")) for m in msgs
            if m.get("direction") == "Inbound" and m.get("readStatus") == "Unread"}


def to_restore(before: Set[str], after_msgs) -> Set[str]:
    """The ids that were Unread before the run and are Read now."""
    return {str(m.get("id")) for m in after_msgs
            if str(m.get("id")) in before and m.get("readStatus") == "Read"}


def snapshot(log=print) -> Optional[Dict]:
    from automations.rc_contact_sync import inbox
    try:
        token, ext = _watch()
        since = dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)
        ids = unread_inbound(inbox._messages_since(token, ext, since))
    except Exception as e:  # noqa: BLE001
        log("[unread guard] OFF -- could not read the inbox first (%s: %s)"
            % (type(e).__name__, str(e)[:120]))
        return None
    log("[unread guard] %d unread customer text(s) will be kept unread" % len(ids))
    return {"since": since, "ids": ids}


def restore(snap: Optional[Dict], log=print) -> int:
    if not snap or not snap["ids"]:
        return 0
    from automations.rc_contact_sync import inbox
    from automations.rc_contact_sync import ringcentral as RC
    try:
        token, ext = _watch()
        back = to_restore(snap["ids"], inbox._messages_since(token, ext, snap["since"]))
    except Exception as e:  # noqa: BLE001
        log("[unread guard] could not re-check the inbox (%s: %s)" % (type(e).__name__, str(e)[:120]))
        return 0
    fixed = 0
    for mid in sorted(back):
        try:
            RC.set_read_status(token, ext, mid, "Unread")
            fixed += 1
        except Exception as e:  # noqa: BLE001
            log("[unread guard] could not set %s back to Unread: %s" % (mid, str(e)[:160]))
    log("[unread guard] %d text(s) had turned Read during this run -- %d set back to Unread"
        % (len(back), fixed))
    return fixed


def guarded(main: Callable[[], int], log=print) -> int:
    snap = snapshot(log=log)
    try:
        return main()
    finally:
        restore(snap, log=log)
