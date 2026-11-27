"""Resend every text from Taylor's RingCentral line that FAILED to send.

Carlos 2026-11-27 (RingCentral billing ran out of text credits): "go through
every text send failure and just copy and paste and resend the message that
should have been sent, unless you already see that I already did it for that
text chain."

How it decides, per failed outbound text (messageStatus SendingFailed /
DeliveryFailed) since --since:
  * the CHAIN is the set of numbers it went to (the customer, plus the rep in
    a group thread) -- a resend goes to exactly that set, as one thread;
  * ALREADY REDONE when a LATER outbound text to the same chain (or a part
    of it, e.g. 1:1 to the customer without the rep) went through
    with the same words (difflib ratio >= SAME_TEXT, so a fixed typo or an
    added name still counts) -- that is someone having resent it by hand;
  * the same words failing several times to one chain are ONE resend;
  * a picture that rode along (the wrap-up flyer, a screenshot) is downloaded
    off the failed message and sent with it.
  * a failed message id resent once is remembered (SENT_PATH): a rerun never
    texts anyone twice.

DRY RUN by default: lists every failure and what would be resent, to the
log and the control sheet's 'Resend Preview' tab. --live sends.

    lucy rerun rc_resend_failed --since 2026-11-20            # preview
    lucy rerun rc_resend_failed --since 2026-11-20 --live     # send

Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
from typing import Dict, List, Optional, Sequence, Tuple

from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC

REPORT_ID = "rc_resend_failed"
TAB = "Resend Preview"
FAILED = ("SendingFailed", "DeliveryFailed")
SAME_TEXT = 0.85
SENT_PATH = C.CONFIG_DIR / "rc-resent-failed.json"


def _text(m: dict) -> str:
    return " ".join(str(m.get("subject") or "").split())


def _chain(m: dict, own: str) -> Tuple[str, ...]:
    return tuple(sorted({RC.norm_phone(t.get("phoneNumber", ""))
                         for t in (m.get("to") or [])} - {"", own}))


def _covers(later: Tuple[str, ...], chain: Tuple[str, ...]) -> bool:
    """The later text went to the same thread, or to a part/superset of it
    (resent 1:1 to the customer without the rep, or with someone added).
    Another customer's group with the same rep is neither, so never counts."""
    a, b = set(later), set(chain)
    return bool(a) and (a <= b or b <= a)


def _same(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    if not a or not b:
        return a == b
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= SAME_TEXT


def _pictures(m: dict) -> List[dict]:
    return [a for a in (m.get("attachments") or [])
            if str(a.get("contentType") or "").lower().startswith("image/")]


def plan(msgs: Sequence[dict], own: str, already: Sequence[str] = ()) -> List[Dict]:
    """[{msg, chain, text, action, why}] for every failed outbound text,
    oldest first. action: 'resend' | 'skip'."""
    msgs = sorted(msgs, key=lambda x: x.get("creationTime") or "")
    out: List[Dict] = []
    queued: List[Tuple[Tuple[str, ...], str]] = []
    for i, m in enumerate(msgs):
        if m.get("direction") != "Outbound" or m.get("messageStatus") not in FAILED:
            continue
        chain, text = _chain(m, own), _text(m)
        row = {"msg": m, "chain": chain, "text": text, "pics": len(_pictures(m))}
        if not chain:
            row.update(action="skip", why="no recipient on the message")
        elif str(m.get("id")) in already:
            row.update(action="skip", why="already resent by this tool")
        elif not text and not row["pics"]:
            row.update(action="skip", why="empty message")
        else:
            redo = next((x for x in msgs[i + 1:]
                         if x.get("direction") == "Outbound"
                         and x.get("messageStatus") not in FAILED
                         and _covers(_chain(x, own), chain) and _same(_text(x), text)), None)
            if redo is not None:
                row.update(action="skip", why="already resent %s" % _when(redo))
            elif any(c == chain and _same(t, text) for c, t in queued):
                row.update(action="skip", why="same text failed more than once -- resent once")
            else:
                row.update(action="resend", why="")
                queued.append((chain, text))
        out.append(row)
    return out


def _when(m: dict) -> str:
    raw = str(m.get("creationTime") or "")
    try:
        t = dt.datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return t.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw[:16]


def _download(token: str, att: dict) -> Optional[Tuple[str, bytes, str]]:
    import requests
    uri = att.get("uri")
    if not uri:
        return None
    r = requests.get(uri, headers={"Authorization": "Bearer %s" % token}, timeout=60)
    if not r.ok:
        raise RC.RCError("picture download failed (%s)" % r.status_code)
    ctype = str(att.get("contentType") or "image/png")
    ext = ctype.split("/")[-1].split(";")[0] or "png"
    return ("picture.%s" % ext, r.content, ctype)


def _load_sent() -> Dict[str, dict]:
    try:
        return json.loads(SENT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_sent(state: Dict[str, dict]) -> None:
    SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run(since: dt.date, *, live: bool = False, limit: Optional[int] = None, log=print) -> int:
    from automations.rc_contact_sync import inbox
    log("Resend failed texts — since %s%s" % (since, "" if live else "  (DRY RUN)"))
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    RC.assert_identity(RC.identity(info), creds.get("expected_owner_id") or C.RC_OWNER_ID)
    watch_token = RC.token(creds, jwt=creds["watch_jwt"]) if creds.get("watch_jwt") else token
    from_number = RC.sender_number(token)
    own = RC.norm_phone(from_number)
    names = inbox.name_map(RC.address_book(token, str(creds["contacts_extension_id"])))
    msgs = inbox._messages_since(watch_token, str(creds["watch_extension_id"]), since)
    outs = sorted((m for m in msgs if m.get("direction") == "Outbound"),
                  key=lambda x: x.get("creationTime") or "")
    ok = [m for m in outs if m.get("messageStatus") not in FAILED]
    bad = [m for m in outs if m.get("messageStatus") in FAILED]
    lines = ["%d outbound since %s: %d went through, %d FAILED" % (len(outs), since, len(ok), len(bad))]
    if bad:
        lines.append("failures from %s to %s" % (_when(bad[0]), _when(bad[-1])))
    if ok:
        lines.append("last text that went through: %s" % _when(ok[-1]))
    sent = _load_sent()
    rows = plan(msgs, own, already=list(sent))
    todo = [r for r in rows if r["action"] == "resend"]
    lines.append("%d to resend, %d skipped" % (len(todo), len(rows) - len(todo)))

    def who(chain):
        return ", ".join("%s (%s)" % (names.get(n, "?"), "…" + n[-4:]) for n in chain)

    lines.append("")
    for r in rows:
        lines.append("%s  %-6s %s%s -> %s" % (
            _when(r["msg"]), r["action"].upper(), r["msg"].get("messageStatus"),
            " +%d picture" % r["pics"] if r["pics"] else "", who(r["chain"])))
        lines.append("      \"%s\"" % (r["text"][:300] or "(picture only)"))
        if r["why"]:
            lines.append("      skip: %s" % r["why"])
    for l in lines:
        log(l)
    try:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        _upload_bytes("\n".join(lines).encode(), TAB, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (preview upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    if not live:
        log("DRY RUN -- nothing sent (pass --live)")
        print("=== done ===", flush=True)
        return 0

    failed = 0
    for r in todo[:limit] if limit else todo:
        m = r["msg"]
        try:
            pics = _pictures(m)
            att = _download(token, pics[0]) if pics else None
            res = RC.send_group_mms(token, from_number, list(r["chain"]), r["text"], attachment=att)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log("  ✗ %s: %s" % (who(r["chain"]), str(e)[:200]))
            continue
        sent[str(m.get("id"))] = {"at": dt.datetime.now().isoformat(timespec="seconds"),
                                  "to": list(r["chain"]), "new_id": res.get("id"),
                                  "status": res.get("messageStatus")}
        _save_sent(sent)
        log("  ✓ resent to %s (%s)" % (who(r["chain"]), res.get("messageStatus")))
    log("resent %d, failed %d" % (len(todo) - failed if not limit else min(limit, len(todo)) - failed,
                                  failed))
    print("=== done ===", flush=True)
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rc_resend_failed",
                                 description="Resend texts that failed on Taylor's line (dry run by default).")
    ap.add_argument("--since", required=True, metavar="YYYY-MM-DD")
    ap.add_argument("--live", action="store_true", help="send (default: preview only)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N resends")
    a = ap.parse_args(argv)
    return run(dt.date.fromisoformat(a.since), live=a.live, limit=a.limit)


if __name__ == "__main__":
    raise SystemExit(main())
