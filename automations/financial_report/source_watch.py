"""Watch for an ICD's financials to SHOW UP, then start filling them.

WHY THIS EXISTS
The financial fill is incremental and name-matched: the moment a source carries
an office, the matching tab fills, and until then the tab is simply skipped.
That is the right behaviour for a book that's a day late — and the wrong one for
an ICD who has NEVER had a source, because "skipped" and "not there yet" look
identical in the log. Nobody notices the day the data starts arriving, and
nobody notices the month it never does. Aron Corral sat that way for 35 weeks.

So: a short list of ICDs we are actively waiting on. Every financial run checks
whether their data landed (free — it reads the same parse the fill already did,
no extra login), says so in the manifest note either way, and DMs on the week it
flips. On that first arrival it also walks Double Entry backwards to fill the
weeks already missed, so the tab gets a history instead of one lonely column.

  Eve 2026-08-26: "empezar a completar los financials de Andre Burton …
  vigilá cuándo un mail con su info entre a alphaletereporting o su financial
  info esté en doubleentry y empezala a cargar todas las semanas."

CHECKING BY HAND (probes both sources itself — costs a Double Entry login):
    python -m automations.financial_report.source_watch --check
    python -m automations.financial_report.source_watch --check --catch-up
    python -m automations.financial_report.source_watch --status   # no network

ADDING SOMEONE: one entry in WATCHLIST, keyed by the exact Sheet tab title.
Names are NOT this module's problem — `run._name_bridge()` already resolves a
tab to every spelling the sources use (Andrew Burton -> Andre Burton Jr), so a
watch never needs its own alias list. REMOVING someone: delete the entry once
their tab has filled for a few weeks — a watch that has arrived is noise.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import fill as ffill
from .parse import norm_name

WATCH_STATE = Path(__file__).resolve().parents[2] / "output" / "financial_source_watch.json"

# Slack DMs for the arrival ping — the same pair the session watch uses (Megan
# Hidalgo + Evelyn Sobrino), because "his numbers started coming" is a
# scheduling fact both of them act on.
ALERT_SLACK_TARGETS = ["U04G5HJBGFN", "U088E2KJEV8"]

# ICDs whose financials we are waiting on. `tab` is the Sheet tab title,
# verbatim; `who` is what a human needs in order to chase the source.
WATCHLIST: List[dict] = [
    {
        "tab": "Andrew Burton",
        "who": ("Andre Burton Jr — Kaizen Solutions, Inc. (AppStream office "
                "22041), Sahil Multani's captainship"),
        "since": "2026-08-26",
        "asked_by": "Eve",
        # What to look for in the raw mailbox — see `inbox_mentions`. Surname +
        # company, because a first mail about him may well spell the first name
        # any of the four ways this office is spelled elsewhere.
        "mail_terms": ["Burton", "Kaizen"],
        "note": ("Never had a financial source. Verified 2026-08-26: absent "
                 "from Double Entry (75 offices on raffi127's account) and "
                 "from every book in the inbox (30-day window). His tab's rows "
                 "67-73 are blank in every column ever; the Wireless Metrics "
                 "rows just below them fill from a different pull and are NOT "
                 "evidence that the financials arrived."),
    },
]


def _key(tab: str) -> str:
    return norm_name(tab)


def watched_tabs() -> List[str]:
    return [w["tab"] for w in WATCHLIST]


# ---------------------------------------------------------------------------
# State — so an arrival is announced ONCE, and so "how long have we waited"
# survives across runs.
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        return json.loads(WATCH_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a missing/corrupt state file is a fresh start
        return {}


def _save_state(s: dict) -> None:
    try:
        WATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        WATCH_STATE.write_text(json.dumps(s, indent=2, sort_keys=True),
                               encoding="utf-8")
    except Exception:  # noqa: BLE001 — best-effort; never sink a run over it
        pass


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def check(by_owner: Dict[str, List[dict]],
          bridge: Optional[dict] = None) -> List[dict]:
    """For each watched tab: did THIS parse carry its financials?

    `by_owner` is the first third of whatever the run parsed — either source, or
    the merge of both. Pure: reads no state and writes nothing, so it is safe to
    call from anywhere.

    Each result: {tab, who, found, offices, weeks} — `weeks` being the week
    endings that actually carry a value, which is what separates "his office
    appeared" from "his office appeared with numbers in it".
    """
    out: List[dict] = []
    for w in WATCHLIST:
        offices = ffill._match_owner(w["tab"], by_owner, bridge)
        weeks: set = set()
        for o in offices:
            for vals in (o.get("metrics") or {}).values():
                weeks |= {k for k, v in (vals or {}).items() if v not in (None, "")}
        out.append({"tab": w["tab"], "who": w["who"], "found": bool(offices),
                    "offices": offices, "weeks": sorted(weeks)})
    return out


def record(results: List[dict], *, today: Optional[dt.date] = None,
           persist: bool = True) -> List[dict]:
    """Fold `check()` into the state file and mark which arrivals are NEW.

    Adds `first_seen` / `weeks_waited` / `newly_arrived` to each result.
    `newly_arrived` is true exactly once per tab — the run that first sees data
    — so the DM fires on the flip and not every week after it.

    `persist=False` for a --dry-run: a rehearsal must not spend the one-shot
    arrival. Writing `first_seen` from a dry run would leave the real run
    thinking it had already announced him, and the DM would never be sent.
    """
    today = today or dt.date.today()
    st = _load_state()
    for r in results:
        k = _key(r["tab"])
        prev = st.get(k, {})
        r["newly_arrived"] = bool(r["found"]) and not prev.get("first_seen")
        r["first_seen"] = (prev.get("first_seen") or today.isoformat()
                           if r["found"] else prev.get("first_seen"))
        since = next((w.get("since") for w in WATCHLIST
                      if _key(w["tab"]) == k), None)
        try:
            r["weeks_waited"] = ((today - dt.date.fromisoformat(since)).days // 7
                                 if since else None)
        except Exception:  # noqa: BLE001 — a typo'd date shouldn't break the run
            r["weeks_waited"] = None
        # MERGE, never replace: `seen_mail` lives in the same entry and is
        # written by new_mentions(). Replacing here would wipe it every run and
        # re-announce the same mail forever.
        st[k] = {**prev,
                 "tab": r["tab"], "first_seen": r["first_seen"],
                 "last_checked": today.isoformat(),
                 "last_found": bool(r["found"]),
                 "weeks_with_data": [d.isoformat() for d in r["weeks"]],
                 "offices": [o["office"] for o in r["offices"]]}
    if persist:
        _save_state(st)
    return results


def log_lines(results: List[dict]) -> List[str]:
    """Human-readable status, for the run log."""
    lines: List[str] = []
    for r in results:
        if r["found"]:
            wk = ", ".join(d.isoformat() for d in r["weeks"]) or "no values yet"
            mark = "ARRIVED" if r.get("newly_arrived") else "filling"
            lines.append(f"financial watch: {mark} — {r['tab']} ({r['who']}): "
                         f"{len(r['offices'])} office(s), weeks {wk}")
        else:
            waited = r.get("weeks_waited")
            lines.append(f"financial watch: still no source for {r['tab']} "
                         f"({r['who']})"
                         + (f" — {waited} week(s) waiting" if waited else ""))
    return lines


def note_fragment(results: List[dict]) -> str:
    """One clause for the run manifest note, so the weekly summary carries the
    watch both ways: silence is a finding here, not the absence of one."""
    bits = []
    arrived = [r for r in results if r["found"]]
    waiting = [r for r in results if not r["found"]]
    if arrived:
        bits.append("financials ARRIVED for " + ", ".join(r["tab"] for r in arrived))
    if waiting:
        bits.append("still no financial source for "
                    + ", ".join(r["tab"]
                                + (f" ({r['weeks_waited']}w)"
                                   if r.get("weeks_waited") else "")
                                for r in waiting))
    return " · ".join(bits)


def alert_text(r: dict) -> str:
    wk = ", ".join(d.isoformat() for d in r["weeks"]) or "none yet"
    return (f"*{r['tab']}'s financials just showed up.*\n"
            f"• {r['who']}\n"
            f"• office(s): {', '.join(o['office'] for o in r['offices'])}\n"
            f"• weeks with values: {wk}\n"
            f"His ATT Program - Focus Report tab fills from here on, and the "
            f"weeks already missed are being backfilled now. Nothing to do — "
            f"this is the heads-up you asked for.")


def _dm(text: str, *, dry_run: bool) -> None:
    """DM both watchers. Best-effort: a Slack outage must never sink the fill."""
    print(f"[financial watch] ALERT -> {', '.join(ALERT_SLACK_TARGETS)}\n{text}")
    if dry_run:
        return
    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
    except Exception as e:  # noqa: BLE001
        print(f"[financial watch] (Slack client init failed: "
              f"{type(e).__name__}: {str(e)[:100]})")
        return
    for target in ALERT_SLACK_TARGETS:
        try:
            client.chat_postMessage(channel=target, text=text)
        except Exception as e:  # noqa: BLE001 — one recipient failing isn't fatal
            print(f"[financial watch] (Slack alert to {target} failed: "
                  f"{type(e).__name__}: {str(e)[:100]})")


def announce(results: List[dict], *, dry_run: bool = False) -> None:
    """DM the arrivals — the week a watched ICD's financials first parse."""
    for r in results:
        if r.get("newly_arrived"):
            _dm(alert_text(r), dry_run=dry_run)


def announce_mentions(mentions: List[dict], *, dry_run: bool = False) -> None:
    """DM mail that mentions a watched ICD but came from a sender we don't read."""
    for m in mentions:
        _dm(mention_alert_text(m), dry_run=dry_run)


# ---------------------------------------------------------------------------
# The raw mailbox — the half `check()` structurally cannot see
# ---------------------------------------------------------------------------
# `check()` can only find what the PARSE found, and the parse only ever sees
# attachments from the four senders in email_source.SOURCES. So the most likely
# way a new ICD's financials actually show up — someone we've never received a
# book from emails one in — is invisible to it: the file is never downloaded, so
# it is never parsed, so nothing is ever missing. This probe looks at the
# mailbox itself instead: any message, any sender, mentioning the ICD.
#
# It is deliberately a NOTICE, not a fill. A workbook from an unknown sender
# needs its layout read and a SOURCES entry written before anything can be
# filled from it; what this buys is finding out the week it lands rather than
# the month someone happens to ask.

def _mail_hits(terms: List[str], since_days: int, *,
               broad: bool = False) -> List[dict]:
    """Messages from ANY sender that could be about `terms`, newest first.

    The IMAP query is where the noise gets cut, not afterwards. A bare
    `TEXT "Burton"` matches every roster, commit digest and telecom tracker in
    the mailbox — measured: 15 hits, 0 real (Eve 2026-08-26). So the search asks
    the two questions that can actually be true of a financial source:

      * the name is in the SUBJECT             — `SUBJECT "Burton"`
      * the subject is about money AND the name is somewhere in the message
                                               — `SUBJECT "financial" TEXT "Burton"`

    `broad=True` drops back to plain full-text, for looking by hand.
    """
    import email as _email

    from automations.shared import email_ingest
    out: Dict[str, dict] = {}
    M = email_ingest._connect()
    try:
        since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
        queries: List[str] = []
        for term in terms:
            queries.append(f'(SINCE {since} SUBJECT "{term}")')
            if broad:
                queries.append(f'(SINCE {since} TEXT "{term}")')
            else:
                for word in _SUBJECT_MONEY_WORDS:
                    queries.append(f'(SINCE {since} SUBJECT "{word}" TEXT "{term}")')
        ids: List[bytes] = []
        for crit in queries:
            try:
                typ, data = M.search(None, crit)
            except Exception:  # noqa: BLE001 — one odd query mustn't kill the probe
                continue
            ids += (data[0] or b"").split()
        for mid in list(reversed(list(dict.fromkeys(ids))))[:25]:  # newest first, capped
            typ, d = M.fetch(mid, "(RFC822)")
            if not d or not d[0]:
                continue
            msg = _email.message_from_bytes(d[0][1])
            key = msg.get("Message-ID") or f"uid:{mid.decode()}"
            files = [email_ingest._filename(p)
                     for p in (msg.walk() if msg.is_multipart() else [msg])
                     if email_ingest._filename(p)]
            out[key] = {"id": key,
                        "from": email_ingest._decode(msg.get("From", "")),
                        "subject": email_ingest._decode(msg.get("Subject", "")),
                        "date": msg.get("Date", ""),
                        "files": files}
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return list(out.values())


# The reporting mailbox talks to itself — Hub push digests, board emails, the
# trackers it forwards. Those quote every ICD's name constantly and are never a
# financial source, so they are dropped before anything else is judged.
_IGNORE_SENDERS = ["alphaletereporting@gmail.com", "alphaletemarketing@gmail.com"]
_BOOK_EXTS = (".xlsx", ".xls", ".csv")
# Words that make a message ABOUT money rather than merely mentioning someone.
_FINANCIAL_WORDS = ("financial", "summary report", "p&l", "p and l",
                    "profit", "loss", "balance", "payroll", "expenses",
                    "bookkeep", "books")
# The subset used to NARROW the IMAP search itself (see `_mail_hits`). Short on
# purpose: every word here is another server-side query, and these four are what
# the books that already arrive actually say in their subjects.
_SUBJECT_MONEY_WORDS = ("financial", "summary", "profit", "p&l")


def _is_real_signal(hit: dict, terms: List[str]) -> bool:
    """Is this mail plausibly THIS ICD's financials, or just his name in passing?

    A free-text IMAP search on a surname is hopeless on its own — the first run
    of this probe returned 15 hits for "Burton", every one of them a roster, a
    commit digest or a telecom tracker (Eve 2026-08-26). What separates a
    financial source from a mention is WHERE the name sits and WHAT rides along,
    so a hit has to clear one of two bars:

      * the name is in the SUBJECT or an ATTACHMENT FILENAME, and the mail
        either carries a workbook or says money in its subject — "Kaizen
        Solutions financials", "Burton P&L.xlsx"; or
      * a workbook is attached AND the subject says money — a new captain's
        book that happens to list him inside, which is how most owners' data
        actually arrives.

    Deliberately allows the no-attachment case when subject says both the name
    and the money word: German spent two weeks typing his figures into the body
    while his workbook was rebuilt, and that must not read as silence.
    """
    subj = (hit.get("subject") or "").lower()
    files = [f.lower() for f in (hit.get("files") or [])]
    low_terms = [t.lower() for t in terms]
    has_book = any(f.endswith(_BOOK_EXTS) for f in files)
    named = (any(t in subj for t in low_terms)
             or any(t in f for f in files for t in low_terms))
    money = (any(w in subj for w in _FINANCIAL_WORDS)
             or any(w in f for f in files for w in _FINANCIAL_WORDS))
    return (named and (has_book or money)) or (has_book and money)


def inbox_mentions(*, since_days: int = 14, only_unknown_senders: bool = True,
                   strict: bool = True) -> List[dict]:
    """Per watched ICD, mail that plausibly carries their financials. Fail-open:
    any IMAP trouble returns [] rather than sinking the run that called it.

    `only_unknown_senders` drops the senders already wired into
    email_source.SOURCES — their attachments are downloaded and parsed already,
    so `check()` is the honest answer for them and a mention here would just be
    the same news twice. `strict=False` returns every text match instead, which
    is for looking by hand, never for alerting.
    """
    from . import email_source
    known = [s.lower() for s, _globs in email_source.SOURCES] + _IGNORE_SENDERS
    out: List[dict] = []
    for w in WATCHLIST:
        terms = w.get("mail_terms") or []
        if not terms:
            continue
        try:
            hits = _mail_hits(terms, since_days)
        except Exception as e:  # noqa: BLE001 — advisory only
            print(f"[financial watch] (mailbox probe skipped: "
                  f"{type(e).__name__}: {str(e)[:100]})")
            continue
        if only_unknown_senders:
            hits = [h for h in hits
                    if not any(k in h["from"].lower() for k in known)]
        if strict:
            hits = [h for h in hits if _is_real_signal(h, terms)]
        if hits:
            out.append({"tab": w["tab"], "terms": terms, "hits": hits})
    return out


def new_mentions(mentions: List[dict], *, persist: bool = True) -> List[dict]:
    """The mentions not reported before — so the DM fires on the mail that
    arrives, not on every mail that ever arrived."""
    st = _load_state()
    fresh: List[dict] = []
    for m in mentions:
        k = _key(m["tab"])
        seen = set((st.get(k) or {}).get("seen_mail") or [])
        new = [h for h in m["hits"] if h["id"] not in seen]
        if new:
            fresh.append({**m, "hits": new})
        entry = st.setdefault(k, {"tab": m["tab"]})
        entry["seen_mail"] = sorted(seen | {h["id"] for h in m["hits"]})[-200:]
    if persist and mentions:
        _save_state(st)
    return fresh


def mention_alert_text(m: dict) -> str:
    lines = [f"*Mail mentioning {m['tab']} just landed* "
             f"(searched: {', '.join(m['terms'])}).",
             "It is from a sender the financial ingest does NOT read, so "
             "nothing was downloaded or filled — someone has to look:"]
    for h in m["hits"][:5]:
        files = ", ".join(h["files"]) or "no attachment"
        lines.append(f"• {h['date']} — {h['from']}\n    “{h['subject']}” — {files}")
    lines.append("If it's his financials, wire the sender into "
                 "`financial_report/email_source.SOURCES` and the weekly fill "
                 "takes it from there.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Catch-up — the weeks already missed
# ---------------------------------------------------------------------------

def catch_up(tab: str, *, weeks_back: int = 52, dry_run: bool = False,
             logfn=print) -> dict:
    """Backfill every week Double Entry still holds for one watched tab.

    The weekly run only ever writes the four weeks its parse covers, so an ICD
    who first appears in August would otherwise show one column and a blank
    history. This walks the anchors back (see
    `web_source.fetch_office_history`) and writes the lot in one batch per tab.

    Only the focus-report spreadsheets are touched, and only the named tab —
    nothing else on the sheet is read or written.
    """
    from automations.recruiting_report import fill as rfill
    from . import web_source
    from .run import _name_bridge

    bridge = _name_bridge()
    # The owner key the SOURCE uses, not the tab title: the bridge is what turns
    # 'Andrew Burton' into 'andre burton', and it is already the reason the
    # normal fill matches him at all.
    keys = [norm_name(tab)] + [norm_name(a) for a in bridge.get(norm_name(tab), [])]
    offices: List[dict] = []
    weeks: List[dt.date] = []
    for k in dict.fromkeys(keys):
        offices, weeks = web_source.fetch_office_history(k, weeks_back=weeks_back)
        if offices:
            logfn(f"financial catch-up: {tab} — matched Double Entry owner key {k!r}")
            break
    if not offices:
        logfn(f"financial catch-up: {tab} — Double Entry has no history for "
              f"{' / '.join(dict.fromkeys(keys))}; nothing to backfill")
        return {"tab": tab, "weeks": [], "written": False}

    client = rfill._client()
    touched = []
    for sheet_name, sid in ffill.OUTPUT_SHEETS.items():
        try:
            sh = rfill.open_by_key(sid, client)
            ws = rfill._retry(lambda sh=sh: sh.worksheet(tab))
        except Exception:  # noqa: BLE001 — the tab lives on one sheet, not all three
            continue
        for line in ffill.fill_financial_for_tab(ws, offices, weeks, dry_run):
            logfn(f"  {sheet_name}: {line}")
        touched.append(sheet_name)
    return {"tab": tab, "weeks": [w.isoformat() for w in weeks],
            "offices": [o["office"] for o in offices],
            "written": bool(touched) and not dry_run, "sheets": touched}


# ---------------------------------------------------------------------------
# Standalone
# ---------------------------------------------------------------------------

def _probe_both(email_days: int, verbose: bool = True):
    """Parse both sources on demand — what the weekly run does, minus the fill."""
    import tempfile
    from . import email_source, parse, web_source
    from .run import merge_sources
    web = email = None
    try:
        web = web_source.fetch_offices(verbose=verbose)
    except Exception as e:  # noqa: BLE001 — one source down still lets the other answer
        print(f"  warning: Double Entry probe failed: {type(e).__name__}: {str(e)[:140]}")
    try:
        with tempfile.TemporaryDirectory(prefix="financial_watch_") as d:
            files = email_source.fetch(Path(d), since_days=email_days,
                                       verbose=verbose)
            if files:
                email = parse.parse_financial_files(files)
    except Exception as e:  # noqa: BLE001
        print(f"  warning: inbox probe failed: {type(e).__name__}: {str(e)[:140]}")
    if web and email:
        return merge_sources(web, email)
    return web or email or ({}, [], [])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watch for a pending ICD's "
                                             "financials and fill them.")
    ap.add_argument("--check", action="store_true",
                    help="Probe Double Entry AND the inbox now (costs a Double "
                         "Entry login) and report each watched ICD.")
    ap.add_argument("--status", action="store_true",
                    help="Print the last recorded state — no network.")
    ap.add_argument("--catch-up", action="store_true",
                    help="For any watched ICD whose data is there, backfill "
                         "every week Double Entry still holds.")
    ap.add_argument("--tab", help="Limit --catch-up to this tab title.")
    ap.add_argument("--weeks-back", type=int, default=52,
                    help="How far back --catch-up walks (default 52).")
    ap.add_argument("--email-days", type=int, default=30,
                    help="Inbox window for --check (default 30 days).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write to the Sheet and don't DM.")
    args = ap.parse_args(argv)

    if args.status or not (args.check or args.catch_up):
        st = _load_state()
        if not st:
            print("financial watch: nothing recorded yet — run --check.")
        for w in WATCHLIST:
            s = st.get(_key(w["tab"]), {})
            print(f"• {w['tab']} — {w['who']}")
            print(f"    waiting since {w['since']} (asked by {w.get('asked_by', '?')})")
            print(f"    last checked {s.get('last_checked', 'never')}: "
                  f"{'FOUND' if s.get('last_found') else 'no source'}"
                  + (f", first seen {s['first_seen']}" if s.get("first_seen") else ""))
        return 0

    from .run import _name_bridge
    results: List[dict] = []
    if args.check:
        by_owner, _weeks, _problems = _probe_both(args.email_days)
        results = record(check(by_owner, _name_bridge()),
                         persist=not args.dry_run)
        for line in log_lines(results):
            print(line)
        announce(results, dry_run=args.dry_run)
        # The other half: mail from a sender the ingest doesn't read, which no
        # parse could ever have surfaced.
        fresh = new_mentions(inbox_mentions(since_days=args.email_days),
                             persist=not args.dry_run)
        for m in fresh:
            print(mention_alert_text(m))
        announce_mentions(fresh, dry_run=args.dry_run)

    if args.catch_up:
        if args.tab:
            targets = [args.tab]
        elif args.check:
            targets = [r["tab"] for r in results if r["found"]]
        else:
            targets = watched_tabs()
        for tab in targets:
            catch_up(tab, weeks_back=args.weeks_back, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
