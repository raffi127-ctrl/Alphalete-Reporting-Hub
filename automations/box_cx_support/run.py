"""BOX CX-support poster — Carlos's email triage -> #box-cx-support threads.

Carlos 2026-10-03: Taylor has been hand-posting BOX follow-ups ("Business -
ContractID @rep" + the action as a thread reply) in #box-cx-support
(C0C23QWTRNC). Lucy takes that over. Posts go out AS LUCY (the provisioned
'Lucy' user token in ~/.config/recruiting-report/slack-user-token), never as
Carlos — that was his one complaint about the manual pass on 10/3.

Sources (BOX emails forwarded by Carlos's Gmail filter to
alphaletereporting@gmail.com — original From/To/Cc survive a filter-forward):
  * Chrea's "Pending deals" lists  -> one post per row under Carlos's agency
  * INCOMPLETE NOTICE              -> post, note = "Action Needed"
  * Enrollment Rejection           -> post, note = "Utility Rejection Reason"
  * REJECTION NOTICE               -> post, note = rejection reason/action
  * Cynthia's "Business- ID // Rep" asks -> post, note = her first ask line

Never posted (Carlos's rules, 2026-10-03):
  * REINSTATEMENT / CANCELLED notices, Contract History Daily Report
  * anything whose To/Cc includes Ryan McSpadden or Roshan (outside deals)
  * notices whose Agency is not Alphalete Specialized Marketing
  * DROP notices — v1 never auto-posts a drop; they go in Carlos's DM digest
    so he can make the 45-day call himself (post only if sale < 45 days old
    is the v2 rule, needs a sale-date source wired in)

Dedupe: a contract id already visible in the channel's recent history (or in
the local posted-state file) is never re-posted — Taylor or Carlos may still
post by hand.

Dry-run by default; pass --live to actually post. Python 3.9 on Lucy 2.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import imaplib
import json
import os
import re
import sys
import unicodedata
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IMAP_HOST = "imap.gmail.com"
ACCOUNT = os.environ.get("BOXCX_IMAP_ACCOUNT", "alphaletereporting@gmail.com")
APP_PW_PATH = Path(os.environ.get(
    "BOXCX_IMAP_APPPW_PATH",
    str(Path.home() / ".config" / "recruiting-report" / "gmail-app-password")))

CHANNEL_ID = os.environ.get("BOXCX_CHANNEL_ID", "C0C23QWTRNC")  # #box-cx-support
CARLOS_ID = "U046G04P5LG"
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "box_cx_posted.json"

BOX_SENDERS = ("myservicecloud.net", "brokeronlinexchange.com")
# Outside-org owners Carlos only oversees (same set Shikamaru files to
# "Alphalete/Box Outside Deals"): never post their customers here.
OUTSIDE = ("rmcspadden95@gmail.com", "ryanhighline19@gmail.com",
           "roshanaminahmad10@gmail.com")
AGENCY_OK = "alphalete"

SKIP_SUBJECTS = ("REINSTATEMENT", "CANCELLED NOTICE", "CONTRACT HISTORY",
                 "TPV PHONE")  # policy blasts handled elsewhere
UTILITIES = ("Oncor", "Centerpoint", "CenterPoint", "AEP", "TNMP", "Texas-New Mexico")


def _say(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, "replace").decode(enc, "replace"), flush=True)


# ---------------------------------------------------------------- email side
def _app_password() -> str:
    if not APP_PW_PATH.exists():
        raise RuntimeError("Gmail app password not found at %s" % APP_PW_PATH)
    return APP_PW_PATH.read_text(encoding="utf-8-sig").strip().replace(" ", "")


def _dh(v: str) -> str:
    if not v:
        return ""
    out = []
    for t, c in decode_header(v):
        out.append(t.decode(c or "utf-8", "replace") if isinstance(t, bytes) else t)
    return "".join(out)


def _best_text(msg) -> str:
    plain, html_body = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        try:
            body = part.get_payload(decode=True)
        except Exception:
            body = None
        if not body:
            continue
        text = body.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html_body:
            html_body = text
    if plain:
        return plain
    return re.sub(r"<[^>]+>", " ", html_body)


def fetch_box_emails(days: int) -> List[dict]:
    """[{subject, frm, rcpts, body, date}] for BOX senders in the window."""
    since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=60)
    imap.login(ACCOUNT, _app_password())
    imap.select('"[Gmail]/All Mail"', readonly=True)
    out = []
    for dom in BOX_SENDERS:
        typ, d = imap.uid("SEARCH", None, '(SINCE %s FROM "%s")' % (since, dom))
        uids = d[0].split() if d and d[0] else []
        for i in range(0, len(uids), 25):
            batch = b",".join(uids[i:i + 25]).decode()
            typ, md = imap.uid("FETCH", batch, "(BODY.PEEK[])")
            for part in md:
                if not isinstance(part, tuple):
                    continue
                msg = email.message_from_bytes(part[1])
                try:
                    d0 = parsedate_to_datetime(msg.get("Date"))
                except Exception:
                    d0 = None
                out.append({
                    "subject": _dh(msg.get("Subject", "")),
                    "frm": _dh(msg.get("From", "")).lower(),
                    "rcpts": (_dh(msg.get("To", "")) + " " + _dh(msg.get("Cc", ""))).lower(),
                    "body": _best_text(msg),
                    "date": d0,
                })
    imap.logout()
    out.sort(key=lambda e: e["date"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    return out


# ------------------------------------------------------------- parsing rules
def _field(body: str, label: str) -> str:
    """Value of a 'Label:' line in an MSC notice (value may sit on the next
    non-empty line, the plaintext renderer splits them)."""
    lines = [l.strip() for l in body.splitlines()]
    for i, l in enumerate(lines):
        if l.lower().startswith(label.lower() + ":"):
            inline = l.split(":", 1)[1].strip()
            if inline:
                return inline
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j]:
                    return lines[j]
    return ""


def parse_msc_notice(e: dict) -> Optional[dict]:
    body, subj = e["body"], e["subject"].upper()
    agency = _field(body, "Agency")
    if agency and AGENCY_OK not in agency.lower():
        return None
    biz = _field(body, "Customer Name")
    cid = _field(body, "Contract ID")
    rep = _field(body, "Agent")
    if not (biz and cid):
        return None
    note = ""
    if "INCOMPLETE" in subj:
        note = _field(body, "Action Needed")
    elif "ENROLLMENT REJECTION" in subj:
        note = _field(body, "Utility Rejection Reason")
    elif "REJECTION NOTICE" in subj:
        note = _field(body, "Rejection Reason")
        act = _field(body, "Action Needed")
        if act:
            note = (note + " — " + act) if note else act
    if not note:
        return None
    note = re.sub(r"\s+", " ", note).strip()
    return {"biz": biz, "cid": cid, "rep": rep, "note": note,
            "src": e["subject"][:60]}


def parse_pending_rows(e: dict) -> List[dict]:
    """Rows under Carlos's agency in Chrea's 'Pending deals' plaintext table."""
    rows, in_mine = [], False
    for raw in e["body"].splitlines():
        line = raw.strip()
        low = line.lower()
        if not line:
            continue
        if (not line[0].isdigit()
                and re.search(r"\b(inc\.?|llc|corp\.?|partnership)\b", low)):
            # an agency section header ("Alphalete Specialized Marketing, Inc.",
            # "High Value Acquisitions, Inc.", ...) flips whose rows these are
            in_mine = AGENCY_OK in low
            continue
        m = re.match(r"^(\d{6})\s+(.*)$", line)
        if not (m and in_mine):
            continue
        cid, rest = m.group(1), m.group(2)
        util = next((u for u in UTILITIES if " " + u + " " in " " + rest + " "), None)
        if util:
            left, right = rest.split(util, 1)
            words = left.split()
            rep = " ".join(words[-2:]) if len(words) >= 3 else ""
            biz = " ".join(words[:-2]) if len(words) >= 3 else left.strip()
            note = " ".join(right.split()[1:]) or "see pending-deals email"
        else:
            biz, rep, note = rest, "", "see pending-deals email"
        rows.append({"biz": biz.strip(), "cid": cid, "rep": rep.strip(),
                     "note": note.strip(), "src": e["subject"][:60]})
    return rows


def parse_cyn_ask(e: dict) -> Optional[dict]:
    """Cynthia's 'Business- 123456 // Rep Name' one-off asks."""
    m = re.match(r"^(?:Re:\s*|Fwd:\s*)?(.+?)[-–]\s*(\d{6})\s*//\s*(.+)$",
                 e["subject"].strip())
    if not m:
        return None
    biz, cid, rep = m.group(1).strip(), m.group(2), m.group(3).strip()
    rep = re.split(r"[-–]", rep)[0].strip()  # "Jaslene Reyes -Reliant to NRG"
    note = ""
    for line in e["body"].splitlines():
        l = line.strip()
        if not l or l.lower().startswith(("hi ", "hello", "hey")):
            continue
        if l.startswith(("[image", ">", "On ")) or l.lower().startswith("thanks"):
            break
        note = (note + " " + l).strip()
        if len(note) > 40:
            break
    return {"biz": biz, "cid": cid, "rep": rep,
            "note": note or "see Cynthia's email", "src": e["subject"][:60]}


def collect(days: int) -> Tuple[List[dict], List[str], List[str]]:
    """-> (candidates, drops_for_digest, skipped_log)."""
    cands, drops, skipped = [], [], []
    for e in fetch_box_emails(days):
        subj_u = e["subject"].upper()
        if any(o in e["rcpts"] for o in OUTSIDE):
            skipped.append("outside: " + e["subject"][:70])
            continue
        if any(s in subj_u for s in SKIP_SUBJECTS):
            continue
        if "DROP NOTICE" in subj_u:
            biz = _field(e["body"], "Customer Name") or e["subject"]
            cid = _field(e["body"], "Contract ID")
            why = _field(e["body"], "Drop Reason")
            drops.append("%s - %s (%s)" % (biz, cid, why or "drop"))
            continue
        if "PENDING DEALS" in subj_u:
            cands.extend(parse_pending_rows(e))
            continue
        got = parse_msc_notice(e)
        if got:
            cands.append(got)
            continue
        got = parse_cyn_ask(e)
        if got:
            cands.append(got)
    # last word wins per contract id (a later email supersedes)
    by_cid = {}
    for c in cands:
        by_cid[c["cid"]] = c
    return list(by_cid.values()), drops, skipped


# ------------------------------------------------------------------ slack side
def _client():
    from slack_sdk import WebClient
    from automations.shared.slack_metrics_post import _load_token
    return WebClient(token=_load_token())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def member_name_map(client) -> Dict[str, str]:
    """normalized member name -> user id, for rep tagging."""
    ids = []
    cursor = None
    while True:
        r = client.conversations_members(channel=CHANNEL_ID, cursor=cursor, limit=200)
        ids.extend(r["members"])
        cursor = (r.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    out = {}
    for uid in ids:
        try:
            p = client.users_info(user=uid)["user"]
        except Exception:
            continue
        for nm in (p.get("real_name"), (p.get("profile") or {}).get("display_name")):
            if nm:
                out[_norm(nm)] = uid
    return out


def rep_mention(rep: str, names: Dict[str, str]) -> str:
    n = _norm(rep)
    if not n:
        return ""
    if n in names:
        return "<@%s>" % names[n]
    # first name + last initial, then first+last token containment
    toks = n.split()
    for cand, uid in names.items():
        ct = cand.split()
        if toks and ct and toks[0] == ct[0] and (len(toks) < 2 or ct[-1].startswith(toks[-1][0])):
            return "<@%s>" % uid
    return rep  # not in channel: spell the name out (Carlos 2026-10-03)


def already_posted(client, cid: str, state: dict) -> bool:
    if cid in state.get("posted", []):
        return True
    try:
        hist = client.conversations_history(channel=CHANNEL_ID, limit=200)
        return any(cid in (m.get("text") or "") for m in hist["messages"])
    except Exception as exc:
        _say("history check failed (%s) — relying on state file only" % exc)
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="actually post (default dry-run)")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--limit", type=int, default=10, help="max posts per run")
    ap.add_argument("--posts-b64", default="",
                    help="base64 JSON [{biz,cid,rep,note}] prepared on the mini "
                         "(Shikamaru reads Carlos's inbox there) — skips IMAP")
    ap.add_argument("--drops-b64", default="",
                    help="base64 JSON [str] drop lines for Carlos's DM digest")
    args = ap.parse_args(argv)

    if args.posts_b64:
        import base64
        cands = json.loads(base64.b64decode(args.posts_b64).decode("utf-8"))
        drops = (json.loads(base64.b64decode(args.drops_b64).decode("utf-8"))
                 if args.drops_b64 else [])
        skipped = []
        _say("using %d handed-off candidates (mini bridge), IMAP skipped" % len(cands))
    else:
        cands, drops, skipped = collect(args.days)
    _say("candidates: %d | drops(digest only): %d | outside skipped: %d"
         % (len(cands), len(drops), len(skipped)))

    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except Exception:
            state = {}
    state.setdefault("posted", [])

    client = _client()
    names = member_name_map(client) if cands else {}
    posted, would = [], []
    for c in cands:
        if already_posted(client, c["cid"], state):
            _say("dedupe: %s - %s already in channel/state" % (c["biz"], c["cid"]))
            continue
        mention = rep_mention(c["rep"], names)
        parent = "%s - %s %s" % (c["biz"], c["cid"], mention)
        if len(posted) >= args.limit:
            _say("limit reached, leaving the rest for next run")
            break
        if not args.live:
            would.append("%s  ||  %s" % (parent.strip(), c["note"]))
            continue
        r = client.chat_postMessage(channel=CHANNEL_ID, text=parent.strip())
        client.chat_postMessage(channel=CHANNEL_ID, thread_ts=r["ts"], text=c["note"])
        state["posted"].append(c["cid"])
        posted.append(parent.strip())
        _say("posted: " + parent.strip())

    if args.live:
        state["posted"] = state["posted"][-500:]
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state))
        digest = []
        if posted:
            digest.append("Posted %d to <#%s>:\n• %s"
                          % (len(posted), CHANNEL_ID, "\n• ".join(posted)))
        if drops:
            digest.append("DROP notices (not posted — your 45-day call):\n• "
                          + "\n• ".join(sorted(set(drops))))
        if digest:
            client.chat_postMessage(channel=CARLOS_ID, text="\n\n".join(digest))
    else:
        for w in would:
            _say("DRY-RUN would post: " + w)
        if drops:
            _say("DRY-RUN drop digest: " + "; ".join(sorted(set(drops))))
    _say("finished box_cx_support (%s)" % ("LIVE" if args.live else "dry-run"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
