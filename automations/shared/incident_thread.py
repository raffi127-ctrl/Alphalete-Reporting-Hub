"""One THREAD per problem: the first failure posts, every recurrence replies in
it, and the fix is announced in that same thread.

WHY THIS EXISTS (Eve 2026-08-14)
--------------------------------
#claudecorrections-and-requests had become unreadable. Every producer deduped
its alerts PER DAY — the day orchestrator via `failure_alerts_sent`, the
machine_digest watcher via `error_watch_<day>.json`, section_drop_alert via a
per-day dedup file. That is correct for one morning and wrong for a week: a
report that keeps failing (or a benign "no new emails today") opened a BRAND NEW
top-level message every single day, so the channel filled with near-identical
posts about ONE unfixed thing and the actual state of the morning had to be
reconstructed by scrolling. Eve: "es muy confuso y redundante … podemos
responder con un nuevo aviso de falla dentro del primer mensaje enviado? … y por
favor publicar dentro del mismo hilo cuando algo se resolvió".

So an alert is no longer a message, it's an INCIDENT:
  • first occurrence  → one top-level post (the channel gains ONE item)
  • same key, same day → NO new message: one status line in that thread is
                        edited in place ("Failed again today — 2 more runs")
  • same key, NEXT day → yesterday's thread is rolled over and today opens its
                        own post, so a day's channel reads as that day's problems
  • fixed             → a reply in the SAME thread + the parent edited to ✅,
                        then the incident is CLOSED, so the next occurrence
                        opens a fresh post rather than reviving a stale one.

A threaded reply doesn't bump the channel for people who aren't following it, so
a problem on day 9 costs the channel nothing while still being on the record.

ONE OUTAGE, ONE THREAD — even with several witnesses (Eve 2026-08-17). The rule
above deduped per DAY but not per PRODUCER: a report that broke once still got a
post from its drop alert, another from its post-watch, another from the
orchestrator. Failure-class keys now resolve to a shared SUBJECT (see
_FAMILY_PREFIXES / subject()), so the first witness opens the thread and the
others reply into it under ":link: Also failed: …" — which is also how the domino
case reads: one thread whose replies name each office that fell. Findings and
"nothing new today" keep their own threads on purpose.

CLOSED IS VISIBLE FROM THE CHANNEL (Eve 2026-08-17). Two people work these
tickets off the channel list, so "which of these is still real?" has to be
answerable without opening anything. A resolution now: replies in the thread,
re-badges the parent's headline (🚨/❌ → ✅ · *RESOLVED* <date>) and puts a ✅
REACTION on the parent — the reaction being the half that survives when Slack
refuses the edit (chat.update only touches your own messages, and these posts
come from three identities). And any CLEAN run closes it, not just the 4am loop:
`resolve_report(report_id)` runs off hub_publish, so a manual re-run from the Hub
at 2pm closes the thread the same way the orchestrator would have at 4am.

CROSS-MACHINE (the reason the marker lives in the message text)
--------------------------------------------------------------
These alerts are posted from Lucy 1, Lucy 2 and the mini. A local state file
can't be the source of truth, so — same trick as section_drop_alert's grouping —
each parent carries a visible marker line:

    _incident · failure-b2b_metrics · open 2026-08-14_

Any machine finds the open incident by scanning recent channel history for that
marker. The local index (output/state/incident_threads.json) is only a cache so
the common path costs no API call; losing it degrades to a channel scan, never
to a lost alert. Channel history is fetched at most ONCE per process and reused
for every lookup, so a sweep over 50 reports is still one API call.

LENGTH is delegated to `alert_thread` (the other half of this channel's cure,
2026-08-13): every message is chunked under Slack's 4000-char cap rather than
truncated. An incident post must never reintroduce the wall of text that made
this channel unreadable in the first place.

THE CHANNEL GETS ONE PLAIN LINE (Megan 2026-08-18)
--------------------------------------------------
The parent used to keep the headline plus ~420 chars of facts, emoji included.
That broke the channel a second way: Megan triages these tickets by REACTION —
:pending: on what someone has taken, ✅ on what is done — and "when an emoji is
in the actual alert that you send, it gets confusing and all bogged up … that
way I can just see the emojis that we're using as reactions." Three sentences
per alert was still a wall, too, once fifteen reports ran in a morning.

So the parent is now exactly:

    *Alphalete Org Sales Board* — ran, but 1 didn't fill
    _incident · failure-org_sales_board · open 2026-08-18_

and NOTHING else. No emoji in any message this module posts to the channel; the
full headline, the error, the missing list, the re-run command and the
paste-to-Claude block all move into the thread — ahead of the details, so the
first reply is the whole story. Nothing is dropped, it moves. A resolution
re-badges that same line with "· *RESOLVED* <date>" and adds the ✅ REACTION;
the word does the work in the text, the emoji does it in the reaction layer.
`alert_thread.headline` owns the wording.

FAILURE LADDER — every step is quieter than losing the alert:
  reply in the thread → post standalone → return None and let the caller do
  whatever it did before this module existed. Nothing here ever raises.

ONE THREAD PER DAY (Eve 2026-08-17). A thread is not allowed to run for days:
yesterday's is rolled over with a single line and today opens its own post, so
the channel for a given day reads as that day's problems. And WITHIN a day a
repeat never adds a message — one status line in the thread is edited in place
("Failed again today — 2 more runs, last 15:42 · Also failed today: …"), so a
retry loop can't turn a clean thread into a scroll. Every message and edit goes
out as Lucy (see LUCY_USER_ID); a laptop hands the job to the mini instead.

CLI:
    python -m automations.shared.incident_thread --list
    python -m automations.shared.incident_thread --resolve failure-b2b_metrics \
        --note "fixed by hand"
    python -m automations.shared.incident_thread --resolve-report b2b_metrics \
        --note "fixed by hand"   # don't need to know which witness opened it
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

_builtin_print = print


def print(*args, **kwargs):  # noqa: A001 — deliberate, module-local
    """print() that survives a cp1252 console (CLAUDE.md: every report runs on
    macOS AND Windows).

    Every message in this module is a "⚠ the alert degraded" line inside a
    best-effort path — and on Windows printing that ⚠ raises UnicodeEncodeError,
    which turns a degraded alert into a CRASHED run. Shadowing print here (rather
    than editing twenty call sites and hoping the next one remembers) makes that
    impossible for anything written in this file, now or later."""
    try:
        _builtin_print(*args, **kwargs)
    except UnicodeEncodeError:
        _builtin_print(*[str(a).encode("ascii", "replace").decode("ascii")
                         for a in args], **kwargs)

CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests
# Same sidecar the orchestrator's notify.py writes when it resolves "#name" to a
# numeric id (kept in sync by hand on purpose — importing notify here would make
# a cycle, and this module must stay importable from anywhere).
CHANNEL_ID_CACHE = REPO_ROOT / "output" / ".corrections_channel_id"
STATE_PATH = REPO_ROOT / "output" / "state" / "incident_threads.json"

# ONE THREAD PER PROBLEM PER DAY (Eve 2026-08-17): "si falla mañana que mañana se
# abra un nuevo hilo". A thread that runs for days is unreadable in a different
# way than a channel full of posts — you have to scroll a week of history to find
# out where something stands. So a new day gets a NEW post, and yesterday's thread
# is rolled over with one line pointing at it.
MAX_AGE_DAYS = 0
# More replies than this → roll over early. With the same-day repeats collapsed
# into ONE edited status line (see _today_line) a thread can't really reach this
# any more; it stays as the backstop.
MAX_FOLLOWUPS = 12
_HISTORY_PAGES = 3               # 3 × 200 messages of lookback for the scan
_HISTORY_LIMIT = 200

# Keys are code-generated ids ("failure-b2b_metrics"), never free text: the
# marker is parsed back out of Slack, so a key with a space or a "·" in it would
# be unfindable. Reject it loudly at the door instead of alerting into a void.
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:@/-]+$")
_MARK_RE = re.compile(
    r"_incident · (?P<key>[^ ·]+) · (?P<state>open|resolved) (?P<date>\d{4}-\d{2}-\d{2})_")

# What a RESOLVED parent looks like from the channel list (Eve 2026-08-17). The
# resolution used to be visible only inside the thread plus a grey italic marker
# at the bottom of the parent, so a fixed problem still read as an open one while
# scrolling — and two people work these tickets off that list. The parent's
# headline gains the word RESOLVED AND the message gets a ✅ reaction, which is
# what shows in the channel without opening anything.
#
# The REACTION is the only emoji on these posts now (Megan 2026-08-18): the alert
# text itself is emoji-free, so ✅ and :pending: stand out at a glance instead of
# competing with a 🚨 / 🕐 / 📋 in every message.
DONE_EMOJI = ":white_check_mark:"       # thread replies only, never the parent
DONE_REACTION = "white_check_mark"
# Somebody (or Claude) is ON it — Eve 2026-08-17. Two people pick these tickets
# up off the channel list, so "already being worked" has to be visible there or
# they both start on the same one. :pending: is the workspace's own emoji and is
# already used by hand for exactly this; the ✅ replaces it when it's done.
WORKING_REACTION = "pending"
# An approval-gated phase that is WAITING on its human checkmark — purple, the
# same color the Hub's approval pill shows for that state (Megan 2026-08-18).
# Set by the caller via open_or_followup(reaction=…); resolve() clears it along
# with :pending:, so a closed post only ever wears the ✅.
WAITING_REACTION = "large_purple_circle"
# NEEDS A PERSON — red, in a list that already speaks in colored circles (Megan
# 2026-08-26: "put some type of emoji on the ones that Eve and I need to look at
# personally so we know which ones to go to first"). Purple means waiting on a
# human checkmark, so red means waiting on a human FIX. Set by incident_triage,
# which is the only thing that decides it; resolve() clears it with the others.
NEEDS_HUMAN_REACTION = "red_circle"

# EVERY message and edit in this channel goes out as Lucy (Eve 2026-08-17: "todos
# los cambios y mensajes tienen que salir al canal desde Lucy"). It is not only
# cosmetic: chat.update and chat.delete only touch your OWN messages, so a
# resolution posted from another identity can neither re-badge the parent nor
# rewrite the marker — it leaves a half-closed thread every other machine still
# reads as open. The mini and Lucy 2 hold that token; a laptop does not, and its
# token is the person's own (Evelyn's, on the Windows box).
LUCY_USER_ID = "U0BCG8F9B5Z"


def whoami(client=None) -> str:
    """The Slack user id this machine's token authenticates as ("" if unknown)."""
    try:
        return (client or _client()).auth_test().get("user_id") or ""
    except Exception:  # noqa: BLE001
        return ""


def is_lucy(client=None) -> bool:
    return whoami(client) == LUCY_USER_ID

# One channel-history fetch per process, shared by every lookup (see docstring).
_HISTORY_CACHE: Dict[str, list] = {}


# --- FAMILIES: one broken report, one thread (Eve 2026-08-17) ------------------
# The thread-per-problem rule fixed "one post per DAY"; it did not fix "one post
# per PRODUCER". Three different modules describe the same broken report from
# three angles and each opened its own top-level post:
#
#   drop-box-order-log            the run dropped its Tableau pull, so it never posted
#   failure-box_order_log__watch  post_watch: no post landed by 8:45
#   failure-box_order_log         the orchestrator's own "didn't finish"
#
# Those are one event with three witnesses. Eve 2026-08-17: "no son sobre el
# mismo problema? … es muy redundante y confuso tener mil mensajes en el canal
# por el mismo problema porque impide ir resolviendo de a uno."
#
# So a failure-class key resolves to a SUBJECT, and the first witness to alert
# opens the thread; the rest reply in it. Three things map onto one subject:
#   • normalisation — `_`/`-` are the same word, and post_watch's `__watch`
#     pseudo-report is the report it watches, not a separate one.
#   • schedule_config's `verify.report_id` — the DECLARED link between an
#     orchestrator report id and the manifest/section id its drop alerts use
#     (carlos_focus -> carlos-1on1s-run). Read, never guessed, so a renamed
#     manifest id can't silently split a thread back in two.
#   • VARIANTS of one report — box_order_log_roshan / _abel / _per_office are the
#     same pull and the same module as box_order_log, aimed at another owner, and
#     on 2026-08-17 the stale-ID export broke all of them at once: the drop alert
#     already filed Roshan's and Abel's misses as `drop-box-order-log` replies
#     (run_owner.py passes the BASE id on purpose) while the mini's standalone
#     failure opened `standalone-box_order_log_roshan` as its own post. Same
#     event, two shapes. A variant is recognised from what schedule_config
#     already declares — an id that EXTENDS another registered report id AND runs
#     the same command package — so abel, per_office and every future owner join
#     without a list to maintain (see _variants).
#
# Deliberately NOT grouped: `finding-` (the report RAN — the conversation is
# about the numbers, not the outage) and `nonew-` (a benign "nothing today").
# Merging those would hide a real question inside a failure thread.
_FAMILY_PREFIXES = ("failure-", "drop-", "standalone-")
# Findings are their OWN family, not members of the outage one: an audit that
# found something is not an outage and must not land inside an outage thread
# (test_findings_and_nonew_keep_their_own_thread). But they still have to find
# EACH OTHER — see subject().
_FINDING_PREFIXES = ("finding-",)
# "does this string name a thread, or a report?" Every caller that asks needs
# BOTH families, or a finding- key gets mistaken for a report id and expanded
# into nonsense like 'failure-finding-vantura_board_audit'.
_KEY_PREFIXES = _FAMILY_PREFIXES + _FINDING_PREFIXES
# post_watch.WATCH_SUFFIX. Duplicated rather than imported: this module must stay
# importable from anywhere (shared/ does not depend on day_orchestrator/), the
# same reason CHANNEL_ID_CACHE is kept in sync by hand.
_WATCH_SUFFIX = "__watch"

_CONFIG_PATH = REPO_ROOT / "automations" / "day_orchestrator" / "schedule_config.json"
_ALIAS_CACHE: Optional[Dict[str, str]] = None


# ------------------------------------------------------------------ helpers ---

def _canon(rid: str) -> str:
    return rid.strip().lower().replace("_", "-")


def _pkg(report) -> str:
    """The module PACKAGE a report runs ("automations.box_order_log"), from its
    declared command. Empty when there's no command to read."""
    if not isinstance(report, dict):
        return ""
    cmd = (report.get("command") or [""])
    return ".".join(str(cmd[0] if cmd else "").split(".")[:2])


def _variants(reports: dict) -> Dict[str, str]:
    """{variant report id -> the base report it is a variant OF}, canon form.

    A variant is declared by two facts already in schedule_config agreeing: its
    id EXTENDS another registered report's id (`box_order_log_roshan` extends
    `box_order_log`) and it runs the same command package
    (`automations.box_order_log`). Both, never one — plenty of ids share a prefix
    by coincidence, and plenty of unrelated reports share a package. The LONGEST
    matching base wins, so a variant of a variant lands on its nearest parent.

    This is what keeps the rule from needing a hand-kept list: Abel was added the
    day after Roshan, per_office a week later, and each one joins its base's
    thread the moment it appears in the config."""
    ids = {_canon(rid): rid for rid in reports}
    out: Dict[str, str] = {}
    for c, rid in ids.items():
        pkg = _pkg(reports[rid])
        if not pkg:
            continue
        best = ""
        for other in ids:
            if other == c or not c.startswith(other + "-"):
                continue
            if len(other) > len(best) and _pkg(reports[ids[other]]) == pkg:
                best = other
        if best:
            out[c] = best
    return out


def _alias_map() -> Dict[str, str]:
    """{some report id -> the id whose thread it belongs in}, from schedule_config:
    manifest/section ids via the `verify` blocks, plus per-owner/per-step VARIANTS
    via _variants. Best-effort: an unreadable config costs us the declared half of
    the grouping (normalisation still works), never an alert."""
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE
    out: Dict[str, str] = {}
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        reports = cfg.get("reports") or {}
        for rid, r in reports.items():
            v = r.get("verify") if isinstance(r, dict) else None
            mid = (v or {}).get("report_id") if isinstance(v, dict) else None
            if mid and _canon(mid) != _canon(rid):
                out[_canon(mid)] = _canon(rid)
        # A verify alias is the more specific statement, so it wins a collision.
        for variant, base in _variants(reports).items():
            out.setdefault(variant, base)
    except Exception:  # noqa: BLE001 — no config = no aliases, never a crash
        pass
    _ALIAS_CACHE = out
    return out


def _root(rid: str) -> str:
    """Follow the alias chain to the id that owns the thread — a variant can point
    at a base that is itself a manifest alias. Cycle-safe: a config that ever
    aliased A->B->A must degrade to a thread, not to a hung run."""
    aliases = _alias_map()
    seen = {rid}
    while True:
        nxt = aliases.get(rid)
        if not nxt or nxt in seen:
            return rid
        seen.add(nxt)
        rid = nxt


def subject(key: str) -> Optional[str]:
    """What a failure-class incident is ABOUT — the shared identity that lets the
    drop / watch / failure alerts for one report (and its per-owner variants) find
    each other's thread.

    Two SEPARATE namespaces, and they never meet: an outage key answers with the
    bare report root, a finding key with "finding:<root>". So the drop / watch /
    failure witnesses of one outage share a thread, the finding witnesses of one
    audit share a DIFFERENT thread, and an audit finding is never filed inside an
    outage post.

    That second namespace is what 2026-08-18 was missing. The vantura board audit
    announced the same two Stations findings TWICE the same morning: run_manifest
    fired section_drop_alert (key `drop-vantura-board-audit`, the dashed manifest
    id) and the orchestrator then fired notify._post_findings_corrections (key
    `finding-vantura_board_audit`, the underscore registry id). Neither could see
    the other — the first was outage-class, the second answered None here — so
    the channel got two posts for one problem, which is exactly what the incident
    families were built to stop.

    None still means "this key stands alone" (nonew-, or any key in neither
    family), which keeps the old one-thread-per-key behaviour."""
    for p in _FAMILY_PREFIXES:
        if key.startswith(p):
            rid = key[len(p):]
            if rid.endswith(_WATCH_SUFFIX):
                rid = rid[:-len(_WATCH_SUFFIX)]
            return _root(_canon(rid)) or None
    for p in _FINDING_PREFIXES:
        if key.startswith(p):
            root = _root(_canon(key[len(p):]))
            return "finding:" + root if root else None
    return None

def marker(key: str, state: str = "open", day: Optional[dt.date] = None) -> str:
    return "_incident · {} · {} {}_".format(key, state,
                                            (day or dt.date.today()).isoformat())


def _resolved_headline(text: str, day: dt.date) -> str:
    """`text` with its FIRST line stamped done: "… · RESOLVED <date>".

    NO EMOJI IN THE TEXT (Megan 2026-08-18). This used to prepend ✅. The ✅ that
    matters is the REACTION — that is what Megan scans the channel by, together
    with :pending: for "someone is on it", and an alert whose own text is full of
    emoji makes those reactions impossible to pick out. The word RESOLVED carries
    the same meaning in the text and leaves the emoji layer to the humans.

    Only the headline changes — the rest stays readable, because the channel is
    also the record of what happened this morning. Idempotent: a parent that
    already says RESOLVED is returned untouched, so a second resolve (a sibling
    report recovering after the first) can't stack two stamps on one line."""
    from automations.shared import alert_thread
    lines = (text or "").splitlines() or [""]
    head = lines[0]
    if "RESOLVED" in head.upper():
        return text
    head = alert_thread.strip_emoji(head)
    lines[0] = "{} · *RESOLVED* {}".format(head.rstrip(), _human(day))
    return "\n".join(lines)


def _react(client, channel: str, ts: str, name: str, *, remove: bool = False) -> bool:
    """Add (or remove) one reaction. Best-effort in both directions: a reaction
    that's already there — or already gone — is success, and a missing
    reactions:write scope must never turn a fixed problem into an error."""
    try:
        if remove:
            client.reactions_remove(channel=channel, timestamp=ts, name=name)
        else:
            client.reactions_add(channel=channel, timestamp=ts, name=name)
        return True
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "already_reacted" in msg or "no_reaction" in msg:
            return True
        print("  - incident reaction :{}: {} ({}: {})".format(
            name, "removed" if remove else "refused", type(e).__name__,
            msg[:60]))
        return False


def _react_done(client, channel: str, ts: str) -> None:
    """✅ the parent post and clear the :pending: someone left on it.

    This is the ONLY part of a resolution visible in the channel list, which is
    where the two people working these tickets decide what is still open — Eve
    2026-08-17: "que se reaccione al thread original con un checkmark". The
    :pending: has to come OFF at the same moment, or a fixed problem still reads
    as work in progress — and so must the purple and red circles incident_triage
    puts on OPEN posts, for the same reason."""
    _react(client, channel, ts, DONE_REACTION)
    for r in (WORKING_REACTION, WAITING_REACTION, NEEDS_HUMAN_REACTION):
        _react(client, channel, ts, r, remove=True)


def _parent_still_open(client, channel: str, ts: str) -> Optional[bool]:
    """Fetch JUST this parent and read its marker: True = open, False = resolved,
    None = couldn't tell. One targeted history call — nowhere near the 3-page
    scan, and only used where a stale belief would put a WRONG reaction on a
    closed thread."""
    try:
        r = client.conversations_history(channel=channel, latest=ts, oldest=ts,
                                         inclusive=True, limit=1)
        for m in r.get("messages") or []:
            if m.get("ts") == ts:
                mk = _MARK_RE.search(m.get("text") or "")
                if mk:
                    return mk.group("state") == "open"
        return None
    except Exception:  # noqa: BLE001
        return None


def _human(day: dt.date) -> str:
    # No %-d / %#d: this runs on macOS AND Windows (CLAUDE.md).
    return "{} {}".format(day.strftime("%a %b"), day.day)


def _valid(key: str) -> bool:
    if key and _KEY_RE.match(key):
        return True
    print(f"  ⚠ incident key {key!r} is not marker-safe — alerting without a "
          "thread", flush=True)
    return False


def _load_index() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no index yet is the normal first run
        return {}


def _save_index(idx: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(idx, indent=2, sort_keys=True),
                              encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — the index is a cache, never critical
        print(f"  ⚠ incident index not saved: {type(e).__name__}: {e}", flush=True)


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _history(client, channel: str) -> list:
    """Recent channel messages, fetched at most once per process per channel."""
    if channel in _HISTORY_CACHE:
        return _HISTORY_CACHE[channel]
    msgs: list = []
    if channel.startswith("#"):
        # conversations_history needs an id, not a name. The first post resolves
        # and caches the id (see _post), so this only skips the very first run.
        _HISTORY_CACHE[channel] = msgs
        return msgs
    cursor = None
    try:
        for _ in range(_HISTORY_PAGES):
            kw = dict(channel=channel, limit=_HISTORY_LIMIT)
            if cursor:
                kw["cursor"] = cursor
            resp = client.conversations_history(**kw)
            msgs.extend(resp.get("messages") or [])
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:  # noqa: BLE001 — no history = open a new post, fine
        print(f"  ⚠ incident history scan failed ({type(e).__name__}: "
              f"{str(e)[:80]}) — treating as no open incident", flush=True)
    _HISTORY_CACHE[channel] = msgs
    return msgs


def _forget_history(channel: str) -> None:
    """Drop the cached history after we post, so a later lookup in the same
    process sees the incident we just opened."""
    _HISTORY_CACHE.pop(channel, None)


def _is_todays(ent: dict, day: dt.date) -> bool:
    """Is this index entry about a thread that is still TODAY's?

    `opened` is the day the post went up; `last` is the last day something
    happened in it. Either one landing on `day` means the thread is current.
    Unreadable/absent dates answer False on purpose — an entry we can't date is
    exactly the stale one this guard exists to skip, and the cost of being wrong
    here is a missed mark, not a false one."""
    if not isinstance(ent, dict):
        return False
    return day.isoformat() in (ent.get("opened"), ent.get("last"))


def _days_open(opened: str, day: dt.date) -> int:
    try:
        return (day - dt.date.fromisoformat(opened)).days
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------ lookup ----

def find(key: str, *, channel: str = CHANNEL, client=None,
         day: Optional[dt.date] = None, family: bool = True,
         trust_index: bool = True,
         ignore_closed: bool = False) -> Optional[dict]:
    """The OPEN incident for `key`, or None. Index first (no API call), then a
    channel scan so an incident opened on another machine is still found.

    `family` also accepts a SIBLING witness's open thread (see _FAMILY_PREFIXES)
    — the drop alert, the post-watch miss and the orchestrator failure for one
    report all land in whichever of them alerted first. The returned dict carries
    `marker_key` (the key that thread's marker actually names, which may differ
    from `key`) and `via_family`; resolve() needs the former so closing a shared
    thread can't rewrite its marker to the wrong key.

    `trust_index=False` skips the local fast path and asks the CHANNEL. resolve()
    uses it: a stale index still saying "open" for a thread another machine
    already closed would otherwise drop a SECOND ✅ into a thread that has one —
    the exact duplicate this module exists to prevent. It costs one history
    fetch, on a path that only runs when something looked open anyway."""
    if not _valid(key):
        return None
    day = day or dt.date.today()
    idx = _load_index() or {}
    ent = idx.get(key)
    if (trust_index and isinstance(ent, dict) and ent.get("ts")
            and not ent.get("resolved")):
        return dict(ent, key=key, source="index",
                    marker_key=ent.get("marker_key") or key,
                    via_family=bool(ent.get("marker_key")
                                    and ent.get("marker_key") != key))
    # A parent we CLOSED but couldn't edit still carries an "open" marker —
    # chat.update only works on your own messages, and these posts come from
    # three identities. Remember those ts so the scan below doesn't re-open a
    # thread we just resolved. Every resolved entry counts, not only this key's:
    # with families, the entry that closed a shared thread is usually a SIBLING's.
    #
    # `ignore_closed` drops that filter. It exists because the filter can go
    # WRONG in one direction and never recover: resolve() marks a key resolved
    # whenever it fails to find its thread, so a single miss puts the LIVE ts in
    # closed_ts and every later scan on that machine skips it — the thread is
    # invisible for good. resolve() re-asks with this flag and settles it against
    # the thread itself (see _thread_is_closed).
    closed_ts = set() if ignore_closed else {
        e.get("ts") for e in idx.values()
        if isinstance(e, dict) and e.get("resolved") and e.get("ts")}
    try:
        client = client or _client()
    except Exception as e:  # noqa: BLE001 — no Slack client = caller posts fresh
        print(f"  ⚠ incident lookup: no Slack client ({type(e).__name__}: "
              f"{str(e)[:60]})", flush=True)
        return None

    def _as_inc(msg, mark, *, via_family: bool) -> dict:
        return {"key": key, "marker_key": mark.group("key"), "ts": msg.get("ts"),
                "opened": mark.group("date"), "text": msg.get("text") or "",
                "count": int(msg.get("reply_count") or 0), "channel": channel,
                "resolved": False, "source": "channel", "via_family": via_family}

    # History is newest-first, so the first hit per key is the live thread.
    open_by_key: Dict[str, tuple] = {}
    for msg in _history(client, channel):
        m = _MARK_RE.search(msg.get("text") or "")
        if not m or m.group("state") != "open" or msg.get("ts") in closed_ts:
            continue
        open_by_key.setdefault(m.group("key"), (msg, m))

    hit = open_by_key.get(key)
    if hit:
        return _as_inc(*hit, via_family=False)
    if family:
        subj = subject(key)
        if subj:
            for other, hit in open_by_key.items():
                if other != key and subject(other) == subj:
                    return _as_inc(*hit, via_family=True)
    return None


def _spoken_before(key: str) -> bool:
    """Has THIS key already said its piece (in any thread, open or closed)? Read
    off the local index, so the worst a lost index can cause is one repeated
    detail block in a thread — never a missing one."""
    ent = (_load_index() or {}).get(key)
    return isinstance(ent, dict) and bool(ent.get("ts"))


def open_keys() -> List[str]:
    """Keys the local index still has OPEN — the cheap way for a caller to ask
    'is anything of mine outstanding?' without touching Slack."""
    return sorted(k for k, v in (_load_index() or {}).items()
                  if isinstance(v, dict) and v.get("ts") and not v.get("resolved"))


# ------------------------------------------------------------------ posting ---

def _post(client, channel: str, text: str, thread_ts: Optional[str] = None):
    kw = dict(channel=channel, text=text, unfurl_links=False, unfurl_media=False)
    if thread_ts:
        kw["thread_ts"] = thread_ts
    resp = client.chat_postMessage(**kw)
    cid = resp.get("channel")
    if cid and cid != channel:
        try:  # first post by "#name" — cache the numeric id for the scan
            CHANNEL_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
            CHANNEL_ID_CACHE.write_text(cid)
        except Exception:  # noqa: BLE001
            pass
    return resp.get("ts")


def _send(client, channel: str, lines: Sequence[str],
          thread_ts: Optional[str] = None):
    """Post `lines`, CHUNKED to stay under Slack's per-message limit.

    Every message this module sends goes through here. Slack hard-caps a message
    at 4000 chars and answers `msg_too_long` — a lost alert, which is the one
    outcome worse than a noisy channel. alert_thread.chunk splits on line
    boundaries and re-opens ``` fences across the split, so a paste-to-Claude
    block or a log tail survives being cut (Megan 2026-08-13)."""
    from automations.shared import alert_thread
    first = None
    for msg in alert_thread.chunk(list(lines)) or [""]:
        ts = _post(client, channel, msg, thread_ts=thread_ts)
        first = first or ts
    return first


def _remember(key: str, *, ts: str, channel: str, opened: str, count: int,
              text: str, resolved: bool = False,
              marker_key: Optional[str] = None,
              day: Optional[dt.date] = None,
              today: Optional[dict] = None) -> None:
    idx = _load_index()
    idx[key] = {"ts": ts, "channel": channel, "opened": opened,
                # The day the RUN is for, not the day the process runs (a
                # backfill stamps its own day).
                "last": (day or dt.date.today()).isoformat(),
                # Today's rolling status line: where it lives and what it says
                # (see _bump_today). This is what keeps a re-run from adding a
                # message instead of updating one.
                "today": today or {},
                "count": count,
                "text": text, "resolved": resolved,
                # Whose marker the PARENT carries. Differs from `key` when this
                # key joined a sibling's thread; resolve() rewrites that marker,
                # so getting it wrong would rename someone else's incident.
                "marker_key": marker_key or key}
    _save_index(idx)


# The words the roll-over line is recognised by later. Kept short and matched
# case-insensitively: this is read back out of Slack, so it has to survive the
# emoji and the bolding around it.
_ROLLOVER_SENTENCE = "this thread ends here"


def _thread_already_spoke(client, channel: str, ts: str) -> Optional[bool]:
    """Has this thread already been rolled over, or resolved?

    True = yes (a roll-over line or a resolution reply is under it), False = no,
    None = the read failed. The THREAD is the only state every machine can both
    write and read: the local index is per-machine, and the parent's marker can
    only be rewritten by whoever posted it. See _roll_over."""
    try:
        resp = client.conversations_replies(channel=channel, ts=ts, limit=200)
    except Exception as e:  # noqa: BLE001
        print("  - incident: couldn't read thread {} ({}: {})".format(
            ts, type(e).__name__, str(e)[:60]))
        return None
    for msg in (resp.get("messages") or []):
        if msg.get("ts") == ts:
            continue                      # the parent, not a reply
        text = msg.get("text") or ""
        if _ROLLOVER_SENTENCE in text.lower() or _is_resolution_reply(text):
            return True
    return False


def _roll_over(client, channel: str, inc: dict, key: str, age: int,
               day: dt.date) -> None:
    """Yesterday's thread ends here; today gets its own post.

    Eve 2026-08-17: "si falla mañana que mañana se abra un nuevo hilo". One line
    in the old thread so anyone reading it knows where the story continues, and
    the parent's marker flips to `resolved` — otherwise every machine keeps
    finding that old post and rolling it over again tomorrow. No ✅ reaction: it
    is superseded, not fixed.

    THE IN-PROGRESS MARKS COME OFF (Megan 2026-08-20). No ✅ was right; leaving
    the :pending: was not. Flipping the marker to `resolved` makes this post
    invisible to find() forever (it only ever returns `open` ones), so whatever
    ⏳ / 🟣 it is wearing can never be cleared by any later resolve — the channel
    keeps a post that reads "someone is on this" about a thread that ended.
    That is half of why the channel looked worked-on when nothing was: a report
    failing two mornings running rolls its post over wearing yesterday's mark.
    Strip both here, while we still have the ts, before the marker closes the
    door on it.

    SAY IT ONCE, EVEN WHEN THE MARKER CAN'T BE WRITTEN (Megan 2026-08-23:
    "these alerts don't make any sense posting on a fixed header thread from
    Wed"). The "otherwise every machine keeps finding that old post" above is
    exactly right, and it has a hole: flipping the marker is a chat.update, and
    chat.update only touches your OWN messages. A parent posted from a laptop
    belongs to that person, so Lucy is refused — the marker stays `open`, and
    nothing about tomorrow is different. drop-tableau-screenshots-box's parent
    went up under Megan's token on 08-19 and collected FOUR "Still open after N
    day(s)" lines (08-20, then 08-23 at 08:06, 08:12 and 12:00) on a thread that
    had already been resolved five times over.

    The local index can't fix it either — it is per machine, and this is three
    machines. The one piece of state every machine CAN both write and read is
    the THREAD, so that is what we ask: if the thread already carries this line
    (or a resolution), the story has been told and we stay quiet. The marker
    edit is still attempted; when it lands, this thread is done for good."""
    if _thread_already_spoke(client, channel, inc["ts"]) is False:
        try:
            _post(client, channel,
                  ":arrows_counterclockwise: *Still open after {} day(s)* — this "
                  "thread ends here; today's occurrence has its own post in the "
                  "channel.".format(age), thread_ts=inc["ts"])
        except Exception:  # noqa: BLE001
            pass
    else:
        # True (already said) or None (couldn't read). Unknown stays QUIET here,
        # the opposite of resolve()'s choice, because the costs are reversed: a
        # missing roll-over line is a lost pointer to a post sitting in the same
        # channel, while a repeated one is the noise being complained about.
        print("[incident] {}: thread {} has already been rolled over or "
              "resolved — not repeating the line".format(key, inc["ts"]))
    # Superseded, not fixed: no ✅. But it is no longer being worked either, and
    # a triage circle on a rolled-over post is unreachable forever (find() only
    # returns `open` ones), so all three come off here.
    for _r in (WORKING_REACTION, WAITING_REACTION, NEEDS_HUMAN_REACTION):
        _react(client, channel, inc["ts"], _r, remove=True)
    was = _MARK_RE.sub("", inc.get("text") or "").rstrip()
    if was:
        try:
            client.chat_update(channel=channel, ts=inc["ts"],
                               text="{}\n\n{}".format(
                                   was, marker(inc.get("marker_key") or key,
                                               "resolved", day)))
        except Exception:  # noqa: BLE001 — the local index still closes it
            pass
    _mark_resolved_in_index(key, ts=inc.get("ts"), channel=channel)
    print("[incident] {}: rolled over ({} day(s) old) — today opens a fresh "
          "post".format(key, age))


def _bump_today(key: str, day: dt.date, *, sibling: bool, label: str) -> dict:
    """The running tally for TODAY's thread: how many extra runs failed and which
    other reports/offices fell with it. Lives in the index because it is what the
    single status line is rendered from."""
    import time
    ent = (_load_index() or {}).get(key) or {}
    st = ent.get("today") if isinstance(ent.get("today"), dict) else {}
    if st.get("date") != day.isoformat():
        st = {"date": day.isoformat(), "repeats": 0, "also": [], "ts": None}
    if sibling:
        if label not in st.get("also", []):
            st.setdefault("also", []).append(label)
    else:
        st["repeats"] = int(st.get("repeats") or 0) + 1
    st["at"] = time.strftime("%H:%M")
    return st


def _today_line(st: dict, day: dt.date) -> str:
    """Render the one status line. Short on purpose — it is the only thing this
    module adds to a thread for the rest of the day.

    NO EMOJI, NO FOOTER (Megan 2026-08-26: "stop with all the fluff and
    confusion"). This line used to open with :repeat: / :link: and close with
    "_One line per day, kept up to date — no new message per run._" — a sentence
    explaining the mechanism, repeated on every status line in the channel.
    Nobody reading it needs to be told how the line is maintained; they need to
    know it failed again and when. The emoji went for the standing reason (they
    compete with the ✅ / :pending: reactions people triage by)."""
    parts = []
    n = int(st.get("repeats") or 0)
    if n:
        parts.append("*Failed again today* — {} more {}, last {}.".format(
            n, "run" if n == 1 else "runs", st.get("at") or ""))
    also = st.get("also") or []
    if also:
        parts.append("*Also failed today:* {}".format(", ".join(also)))
    if not parts:
        parts.append("*Still failing today* — last {}.".format(
            st.get("at") or ""))
    return "\n".join(parts)


def _put_status(client, channel: str, key: str, inc: dict, st: dict,
                day: dt.date) -> bool:
    """Write today's status line: EDIT the one we already posted in this thread
    today, or post it the first time. Editing is the whole point — a re-run that
    fails again must not add a message (Eve 2026-08-17).

    Mutates `st['ts']` so the caller stores where the line lives."""
    text = _today_line(st, day)
    ts = st.get("ts")
    if ts:
        try:
            client.chat_update(channel=channel, ts=ts, text=text)
            return True
        except Exception as e:  # noqa: BLE001 — refused (another identity posted
            # it, or it was deleted): fall through and post a fresh one.
            print("  - incident status edit refused ({}: {})".format(
                type(e).__name__, str(e)[:50]))
    try:
        new_ts = _post(client, channel, text, thread_ts=inc["ts"])
    except Exception as e:  # noqa: BLE001
        print("  - incident status post failed ({}: {})".format(
            type(e).__name__, str(e)[:60]))
        return False
    if not new_ts:
        return False
    st["ts"] = new_ts
    return True


def open_or_followup(*, key: str, title: str, body: Sequence[str],
                     channel_line: Optional[str] = None,
                     reaction: Optional[str] = None,
                     details: Optional[Sequence[str]] = None,
                     followup: Optional[Sequence[str]] = None,
                     stamp: Optional[str] = None, label: str = "",
                     channel: str = CHANNEL, day: Optional[dt.date] = None,
                     dry_run: bool = False, client=None,
                     max_age_days: int = MAX_AGE_DAYS,
                     max_followups: int = MAX_FOLLOWUPS) -> Optional[dict]:
    """Open a new incident post, or reply in the one that's already open.

      title     first line of the full alert (goes to the THREAD; the channel
                line is derived from it unless channel_line says otherwise)
      channel_line  the exact one-liner for the channel, when the caller knows a
                better short WHY than the title's first clause — e.g. a drop
                alert naming the channel that didn't post ("*tableau-screenshots*
                — precision management") instead of counting sections. Emoji are
                stripped; length is the caller's contract.
      body      the rest of the full alert (also goes to the thread)
      details   posted as a threaded reply ONLY when the incident is NEW (the
                re-run command, the paste-to-Claude block: unchanged from before)
      followup  kept for callers that still pass it; a same-day repeat no longer
                posts a message at all, it updates ONE status line (_today_line),
                so this is only read when a caller opens a fresh post.
      stamp     same — accepted, no longer needed for the repeat wording.
      label     human name of what is failing ("BOX Order Log — Roshan"). Used
                when this alert JOINS a sibling's thread, so the domino case
                reads as a list of who fell instead of a list of internal ids.

    Returns {'ts', 'new', 'key', 'text', 'count'} — 'ts' is always the PARENT, so
    a caller can thread more under it and resolve() can find it later. None means
    nothing was posted and the caller should fall back to its old path.
    """
    if not _valid(key):
        return None
    day = day or dt.date.today()
    body = list(body or [])
    details = list(details or [])

    # ONE PLAIN LINE IN THE CHANNEL (Megan 2026-08-18). The parent used to keep
    # the headline plus ~420 chars of facts, emoji and all. Two problems, one
    # cure: the emoji in the TEXT drowned out the ✅ / :pending: REACTIONS she
    # triages by, and three sentences per alert is still a wall when fifteen
    # reports run. So the channel gets `*What broke* — a few words on why` and
    # nothing else; the full headline and the whole body move into the thread,
    # ahead of the details. Nothing is dropped, it moves. See
    # alert_thread.headline for the wording rules.
    #
    # The marker is appended AFTER on purpose: it has to stay on the PARENT or
    # no other machine can find the thread.
    from automations.shared import alert_thread
    head = (alert_thread.strip_emoji(channel_line) if channel_line
            else alert_thread.headline(title, body))
    parent_text = "\n".join([head, "", marker(key, "open", day)])
    full = [l for l in ([title] + body) if str(l).strip()]
    if alert_thread.same_story(head, full):
        full = []               # a one-line ping: don't echo it under itself
    details = full + ([""] if full and details else []) + details

    if dry_run:
        ent = (_load_index() or {}).get(key) or {}
        again = bool(ent.get("ts") and not ent.get("resolved"))
        where = f"reply→{ent.get('ts')}" if again else "NEW POST"
        shown = "\n".join(followup or ([title] + body)) if again else parent_text
        print(f"[incident] DRY-RUN — {key} {where} → {channel}:\n{shown}\n",
              flush=True)
        if not again and details:
            print("[incident] DRY-RUN — thread detail:\n"
                  + "\n".join(details) + "\n", flush=True)
        return {"ts": ent.get("ts") or "dry-run-ts", "new": not again,
                "key": key, "text": parent_text, "count": ent.get("count", 0)}

    try:
        client = client or _client()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident post: no Slack client ({type(e).__name__}: "
              f"{str(e)[:60]})", flush=True)
        return None

    # The scan below may run on a history snapshot cached EARLIER in this
    # process (the orchestrator resolves other reports all morning), and a
    # sibling witness that posted seconds ago is invisible in it — 2026-08-21
    # the vantura audit's own alert (4:01:31) and the orchestrator's finding
    # (4:01:34) became two posts that way. So a cached "nothing open" is not
    # allowed to open a post: look once more at the channel as it is NOW.
    # Costs one fetch, only on the path that was about to double-post.
    had_cache = channel in _HISTORY_CACHE
    inc = find(key, channel=channel, client=client, day=day)
    if inc is None and had_cache:
        _forget_history(channel)
        inc = find(key, channel=channel, client=client, day=day)

    # A thread from a PREVIOUS day is rolled over: one line saying where it went,
    # and today opens a fresh post (see MAX_AGE_DAYS).
    if inc:
        n = int(inc.get("count") or 0)
        age = _days_open(inc.get("opened") or day.isoformat(), day)
        if age > max_age_days or n >= max_followups:
            _roll_over(client, channel, inc, key, age, day)
            inc = None

    if inc:
        # SAME DAY, SAME PROBLEM → no new message. The thread keeps exactly ONE
        # status line, edited in place (Eve 2026-08-17: "no quiero repitencias en
        # el mismo día … tenemos desorden dentro de los hilos"). It counts the
        # re-runs and names the other offices/reports that fell with it, so the
        # domino case is one always-current line rather than a pile of replies.
        opened = inc.get("opened") or day.isoformat()
        st = _bump_today(key, day, sibling=bool(inc.get("via_family")),
                         label=label or "`{}`".format(key))
        ok = _put_status(client, channel, key, inc, st, day)
        if ok and details and inc.get("via_family") and not _spoken_before(key):
            # A sibling witness speaking for the FIRST time carries new material
            # — its re-run command, its paste-to-Claude block — and the thin
            # witness usually posts first. Those land once; they are not a repeat.
            try:
                _send(client, channel, details, thread_ts=inc["ts"])
            except Exception:  # noqa: BLE001
                pass
        if ok:
            _remember(key, ts=inc["ts"], channel=channel, opened=opened,
                      count=n + 1, text=inc.get("text") or parent_text,
                      marker_key=inc.get("marker_key") or key, day=day,
                      today=st)
            print("[incident] {}: same-day repeat folded into the status line "
                  "of thread {}".format(key, inc["ts"]))
            return {"ts": inc["ts"], "new": False, "key": key,
                    "text": inc.get("text") or parent_text, "count": n + 1}
        print("  - incident status line failed — posting a fresh alert instead")

    try:
        ts = _post(client, channel, parent_text)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident post failed ({type(e).__name__}: {str(e)[:80]})",
              flush=True)
        return None
    if not ts:
        return None
    if details:
        try:
            _send(client, channel, details, thread_ts=ts)
        except Exception as e:  # noqa: BLE001 — parent landed; detail is a bonus
            print(f"  ⚠ incident detail reply failed ({type(e).__name__}: "
                  f"{str(e)[:80]})", flush=True)
    if reaction:
        _react(client, channel, ts, reaction)
    _remember(key, ts=ts, channel=channel, opened=day.isoformat(), count=0,
              text=parent_text, day=day)
    _forget_history(channel)
    print(f"[incident] {key}: opened {ts}", flush=True)
    return {"ts": ts, "new": True, "key": key, "text": parent_text, "count": 0}


def _mark_resolved_in_index(key: str, *, ts: Optional[str] = None,
                            channel: str = CHANNEL) -> None:
    """Close `key` — and every SIBLING pointing at the same thread.

    With families one parent can be several keys' incident. Closing only the key
    that happened to recover would leave its siblings' entries saying "open" with
    the ts of a thread that now reads ✅, so the next failure would reply into a
    closed thread instead of opening a fresh post.

    `ts` writes the entry when this machine has never seen the incident: the
    thread was opened on the mini and the clean run happened on Lucy 2, so there
    is nothing local to flip. Without it this machine would keep finding the
    thread "open" in the channel scan (the parent edit is refused across
    identities) and answer a fixed problem with "Happened again"."""
    idx = _load_index()
    ent = idx.get(key)
    if not isinstance(ent, dict):
        if not ts:
            return
        ent = idx[key] = {"ts": ts, "channel": channel, "count": 0,
                          "opened": dt.date.today().isoformat()}
    ts = ent.get("ts") or ts
    today = dt.date.today().isoformat()
    for k, e in idx.items():
        if isinstance(e, dict) and (k == key or (ts and e.get("ts") == ts)):
            e["resolved"] = True
            e["last"] = today
    _save_index(idx)


# ------------------------------------------------------------------ resolve ---

# The closing sentence every resolution reply carries, whichever entry point
# wrote it (resolve / resolve_report / resolve_any / resolved).
_CLOSING_SENTENCE = "opens a fresh post, not this thread"


def _is_resolution_reply(text: str) -> bool:
    """Is this reply OUR resolution, or just a reply that happens to have a ✅?

    A BARE ✅ is not proof (Eve 2026-08-19). The low-key `unfilled_icd` alert
    opens its own body with one — ":white_check_mark: *captainship-cancel-rate*
    ran fine — every tab filled. 2 ICDs didn't fill…" — because the run DID do
    its whole job. Reading that as a resolution made _thread_is_closed say CLOSED
    on a thread that had never been closed, so find_live handed back None and
    every close path answered "no OPEN incident" with the post sitting right
    there. Not a one-off: it locks out that entire family of alerts, and it takes
    both a --resolve <key> and a --resolve-report <id> down with it.

    A real resolution says so in words. All three writers stamp "— RESOLVED." and
    the same closing sentence, so ask for that instead of for an emoji.
    """
    low = (text or "").lower()
    if _CLOSING_SENTENCE in low:
        return True
    return DONE_EMOJI in (text or "") and "resolved" in low


def _thread_has_resolution(client, channel: str, ts: str) -> Optional[bool]:
    """Same question as _thread_is_closed, but honest about not knowing.

    True = there is already a resolution reply under this parent, False = there
    isn't, None = the read failed and we cannot tell. The two callers want
    OPPOSITE things on a failed read, which is why this is a separate function
    rather than a flag: find_live is deciding whether to REOPEN a thread (saying
    "closed" on error is safe — worst case a thread stays open), while resolve()
    is deciding whether to POST (saying "closed" on error would swallow a real
    resolution, and losing the announcement is the one outcome this module ranks
    worse than a duplicate — see the FAILURE LADDER note at the top)."""
    try:
        resp = client.conversations_replies(channel=channel, ts=ts, limit=200)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident: couldn't read thread {ts} "
              f"({type(e).__name__}: {str(e)[:60]})", flush=True)
        return None
    for msg in (resp.get("messages") or []):
        if msg.get("ts") == ts:
            continue                      # the parent, not a reply
        if _is_resolution_reply(msg.get("text") or ""):
            return True
    return False


def _thread_is_closed(client, channel: str, ts: str) -> bool:
    """Does this thread already carry a resolution reply?

    The one honest way to tell "we closed it and Slack refused the parent edit"
    from "our index is wrong" without trusting local state: resolve() always
    replies in the thread before touching the parent, so a closed incident has a
    ✅ reply under it. Conservative on error — if the read fails we say CLOSED,
    which at worst leaves the thread open, never doubles a ✅ on it."""
    try:
        resp = client.conversations_replies(channel=channel, ts=ts, limit=200)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident: couldn't read thread {ts} "
              f"({type(e).__name__}: {str(e)[:60]})", flush=True)
        return True
    for msg in (resp.get("messages") or []):
        if msg.get("ts") == ts:
            continue                      # the parent, not a reply
        if _is_resolution_reply(msg.get("text") or ""):
            return True
    return False


def _clear_resolved_in_index(key: str, ts: Optional[str] = None) -> None:
    """Undo a wrong `resolved` flag — this key's, and any sibling on the same ts."""
    idx = _load_index()
    changed = False
    for k, e in idx.items():
        if not isinstance(e, dict):
            continue
        if k == key or (ts and e.get("ts") == ts):
            if e.get("resolved"):
                e["resolved"] = False
                changed = True
    if changed:
        _save_index(idx)


def find_live(key: str, *, channel: str = CHANNEL, client=None,
              day: Optional[dt.date] = None) -> Optional[dict]:
    """find(), plus a second look that survives a POISONED index.

    Every caller that acts on an open thread (resolve, resolve_any, the
    :pending: mark) has to go through here, not through find(): a machine whose
    index wrongly lists the live ts as resolved gets None from find() forever,
    and that is invisible from the outside — the post is sitting in the channel
    and the CLI just says "no OPEN incident". The tie-break is the thread itself,
    never local state (see _thread_is_closed)."""
    inc = find(key, channel=channel, client=client, day=day, trust_index=False)
    if inc and inc.get("ts"):
        return inc
    again = find(key, channel=channel, client=client, day=day,
                 trust_index=False, ignore_closed=True)
    if not again or not again.get("ts"):
        return None
    try:
        client = client or _client()
    except Exception:  # noqa: BLE001 — no client, no tie-break
        return None
    if _thread_is_closed(client, channel, again["ts"]):
        return None
    _clear_resolved_in_index(key, again.get("ts"))
    print("[incident] {}: the index had this thread marked closed but it is "
          "still open — index corrected".format(key))
    return again


def resolve(*, key: str, lines: Sequence[str], channel: str = CHANNEL,
            parent_text: Optional[str] = None, day: Optional[dt.date] = None,
            dry_run: bool = False, client=None) -> bool:
    """Announce the fix IN THE INCIDENT'S OWN THREAD and close it.

    Eve 2026-08-14 asked for this explicitly: a resolution that only edited the
    parent (which is what the orchestrator did) is invisible to anyone who read
    the alert earlier — they keep working a problem that's already fixed. So the
    reply goes first (it's the part people see), and the parent edit to ✅ is
    best-effort on top: chat.update only works on your OWN messages, and these
    posts come from three different machines/identities.

    Closing matters as much as posting: once resolved, the NEXT occurrence opens
    a fresh top-level post instead of reviving a thread everyone stopped reading.

    Returns True when the incident was CLOSED — the thread was told, or the reply
    failed but the parent now shows ✅ plus the `resolved` marker. It used to
    return whether the REPLY landed, which cost b2b_metrics its marker on
    2026-08-17: Slack refused the reply (its sibling detail chunk went missing in
    the same second), so this returned False even though the parent edit had just
    succeeded, and notify.resolve_failure_alert took that as "resolve failed" and
    chat_update'd its own marker-less ✅ text straight over it. Two edits, and the
    second one erased the line every other machine uses to find the thread. False
    now means nothing landed at all, which is the only case a caller should
    re-edit. Never raises."""
    if not _valid(key):
        return False
    day = day or dt.date.today()
    if dry_run:
        ent = (_load_index() or {}).get(key) or {}
        print(f"[incident] DRY-RUN — would resolve {key} (ts {ent.get('ts')}) "
              f"→ {channel}:\n" + "\n".join(lines) + "\n", flush=True)
        return bool(ent.get("ts"))
    try:
        client = client or _client()
    except Exception:  # noqa: BLE001
        return False
    # Ask the CHANNEL, not the local cache: another machine may have closed this
    # thread already, and a second ✅ on it is exactly the duplicate we're here
    # to stop.
    inc = find_live(key, channel=channel, client=client, day=day)
    if not inc or not inc.get("ts"):
        # Nothing open there → whatever this machine still believes is out of
        # date. Fix the belief, or it will try again on every clean run.
        if key in open_keys():
            _mark_resolved_in_index(key)
            print(f"[incident] {key}: already closed in the channel — index "
                  f"caught up, nothing posted")
        return False
    ts = inc["ts"]
    # A STALE PARENT LIES THE SAME WAY A STALE INDEX DOES (Megan 2026-08-20).
    # find_live already refuses to trust the local index — but the thing it
    # trusts INSTEAD is the parent's marker, and that marker goes stale in one
    # very ordinary case: a resolve run from a LAPTOP posts its reply and is then
    # refused the chat.update (you may only edit your own messages, and these
    # parents are Lucy's). The thread is closed; the marker still says `open`.
    # The next machine to run a clean pass finds that `open` marker, believes it,
    # and says the whole thing again — which is what happened to
    # failure-daily_rep_breakdown: resolved from the laptop 08-19 16:59, resolved
    # AGAIN by the mini 08-20 09:25, two identical ✅ replies in one thread.
    #
    # _thread_is_closed exists for exactly this and was simply never reached: it
    # only runs on find_live's fallback lookup, which is skipped whenever the
    # first lookup succeeds. So ask the THREAD here, before speaking.
    #
    # Unknown (None) means post: losing a resolution is worse than repeating one
    # — people go on working a problem that is already fixed, which is the
    # complaint this module was built for. Only a definite True stays quiet.
    already = _thread_has_resolution(client, channel, ts) is True
    told = False
    if already:
        print(f"[incident] {key}: thread {ts} already says RESOLVED — not "
              f"repeating it; straightening the parent instead", flush=True)
    else:
        try:
            _send(client, channel, lines, thread_ts=ts)
            told = True
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ incident resolve reply failed ({type(e).__name__}: "
                  f"{str(e)[:80]})", flush=True)
    # THE PARENT KEEPS ITS OWN HEADLINE (Megan 2026-08-18). It is re-badged, not
    # rewritten: the channel line still says what broke and why, now ending in
    # "· *RESOLVED* <date>". A caller's `parent_text` is only the fallback for a
    # parent we somehow can't read — notify used to hand over a whole replacement
    # block (a ✅ line plus the old alert struck through), which put emoji and
    # four struck-through lines back into the channel this is here to keep clean.
    # What the fix WAS goes in the thread reply (`lines`), where it belongs.
    was = _MARK_RE.sub("", inc.get("text") or "").rstrip()
    new_parent = _resolved_headline(was, day) if was else parent_text
    if new_parent is None:
        new_parent = _resolved_headline("", day)
    # The marker keeps the PARENT's own key. On a shared thread the resolver is
    # often a sibling (box_order_log posting clean also clears the post-watch
    # miss), and stamping our key here would rename someone else's incident —
    # that line is what every other machine scans for.
    new_parent = "{}\n\n{}".format(new_parent.rstrip(),
                                  marker(inc.get("marker_key") or key,
                                         "resolved", day))
    edited = False
    try:
        client.chat_update(channel=channel, ts=ts, text=new_parent)
        edited = True
    except Exception as e:  # noqa: BLE001 — the thread reply already told people
        print(f"  ⚠ incident parent edit refused ({type(e).__name__}: "
              f"{str(e)[:60]}) — the in-thread note stands", flush=True)
    # The ✅ REACTION is the part that survives a refused edit: any identity can
    # react on anyone's message, so a thread closed from the wrong machine still
    # reads as done in the channel list.
    _react_done(client, channel, ts)
    _mark_resolved_in_index(key, ts=ts, channel=channel)
    _forget_history(channel)
    print(f"[incident] {key}: resolved in thread {ts}", flush=True)
    # `edited` counts: the parent already reads ✅ and carries the resolved
    # marker, so a caller's own "resolve failed" fallback edit would only strip
    # that marker back off (see the docstring). `already` counts for the same
    # reason and one more: the incident IS closed — that is what the caller
    # asked about — and answering False would send it down its own fallback
    # path to re-announce the very resolution we just declined to repeat.
    return told or edited or already


def resolve_if_open(key: str, *, what: str, detail: str = "",
                    channel: str = CHANNEL, dry_run: bool = False) -> bool:
    """"This just worked — close its alert thread if one is open."

    The shape every caller wants on its success path, so none of them has to
    hand-roll it: FREE when nothing is open (a local index read, no Slack call),
    so it is safe to call on every single clean run. `what` names the thing that
    recovered, in the channel's voice ("*Sara+ screenshots* download again").

    Never raises: closing an alert must never break the run that earned it."""
    try:
        if key not in open_keys():
            return False
        lines = [":white_check_mark: {} — RESOLVED. It just ran clean.".format(what)]
        if detail:
            lines.append(detail)
        lines.append("_Closed. If it happens again it opens a fresh post, not "
                     "this thread._")
        return resolve(key=key, lines=lines, channel=channel, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        print("  ⚠ couldn't close incident {} ({}: {})".format(
            key, type(e).__name__, str(e)[:80]), flush=True)
        return False


def mark_working(key_or_report: str, *, note: str = "", channel: str = CHANNEL,
                 day: Optional[dt.date] = None, dry_run: bool = False,
                 scan: bool = True, client=None) -> bool:
    """":pending: — this one is being worked on right now."

    Eve 2026-08-17: two people pull tickets out of this channel, so a problem
    somebody already picked up (or that Claude is mid-fix on) has to say so in
    the CHANNEL list, not inside a thread nobody opened. A reaction does that
    without another message.

    Takes either an incident key (`failure-b2b_metrics`) or a bare report id
    (`b2b_metrics`) — whichever the caller happens to have. Silent no-op when
    nothing is open for it: marking a problem that isn't on the board would be
    worse than not marking it. Never raises. resolve() clears the :pending: when
    the fix lands, so nothing has to remember to un-mark it.

    `scan=False` answers off the LOCAL index only (no Slack read at all) — for
    callers on a hot path, like every report start on the mini. It costs the case
    where the thread was opened on another machine; a missed :pending: is a much
    cheaper mistake than an API call per run.

    TODAY'S THREAD ONLY (Megan 2026-08-20). The index has no expiry — an entry
    sits there `resolved: false` until something closes it, and with MAX_AGE_DAYS
    at 0 a thread that is not from today is not a live thread at all, it is one
    roll-over away from being closed. Marking off a stale entry put ⏳ on posts
    from days back (the index on this laptop still carried
    `drop-tableau-stale-w-v-uuid-order-log` open from 2026-08-18), and
    _parent_still_open can't catch it: an old parent that hasn't been rolled over
    yet still says `open`. The day filter can only ever SUPPRESS a mark, never
    add one, which is the safe direction for this module."""
    day = day or dt.date.today()
    try:
        keys = candidate_keys(key_or_report)
        if not scan:
            idx = _load_index() or {}
            live = [idx[k] for k in keys
                    if isinstance(idx.get(k), dict) and idx[k].get("ts")
                    and not idx[k].get("resolved")
                    and _is_todays(idx[k], day)]
            if not live:
                return False
            inc = live[0]
            client = client or _client()
        else:
            client = client or _client()
            inc = next((i for i in (find_live(k, channel=channel,
                                              client=client, day=day)
                                    for k in keys) if i), None)
        if not inc or not inc.get("ts"):
            print("[incident] nothing open for {} — not marking it worked on"
                  .format(key_or_report))
            return False
        # THE INDEX CAN LIE ACROSS MACHINES (Megan 2026-08-18: the Applicant
        # Push post wore :pending: AND the ✅ at once — "it should only ever
        # have 1 or the other"). The index is a per-machine file: a resolve on
        # the mini never updates Lucy 2's copy, so a re-run starting on Lucy 2
        # still believed the incident was open. Ask the PARENT itself before
        # reacting — one targeted fetch, not a scan — and when it says
        # resolved, fix the local belief instead of decorating a closed thread.
        state = _parent_still_open(client, channel, inc["ts"])
        if state is False:
            _mark_resolved_in_index(key_or_report if key_or_report in
                                    (_load_index() or {}) else keys[0],
                                    ts=inc["ts"], channel=channel)
            print("[incident] {}: already resolved in the channel — index "
                  "caught up, no :pending: added".format(key_or_report))
            return False
        if state is None and not scan:
            # Can't read the parent and the only source was the local file: a
            # missed :pending: is a much cheaper mistake than a wrong one.
            print("[incident] {}: can't confirm it's still open — not marking"
                  .format(key_or_report))
            return False
        if dry_run:
            print("[incident] DRY-RUN — would react :{}: on {}".format(
                WORKING_REACTION, inc["ts"]))
            return True
        # ONLY LUCY MAY MARK IT (Eve 2026-08-19). Slack lets you remove your OWN
        # reaction and nobody else's, and the ✅ side of this — _react_done —
        # always runs as Lucy on the mini. So a :pending: added under any other
        # token can never come off: the post ends up wearing ⏳ AND ✅ at once,
        # which reads as "fixed, but someone is still on it". That is what
        # incident_reformat._clear_stray_pending exists to sweep up after, and
        # both of today's threads had to be un-marked by hand.
        #
        # Skipping is the cheap side of the trade, and the module already says
        # so: "a missed :pending: is a much cheaper mistake than a wrong one".
        # The CLI doesn't lose anything either — it hands the whole job to the
        # mini before it ever gets here (see main()), so the mark still lands,
        # just as Lucy a few seconds later.
        if not is_lucy(client):
            print("[incident] {}: not marking :{}: from {} — only Lucy can "
                  "take it off again, so a mark from here would outlive the "
                  "fix. Queue it on the mini (`lucy incident_working {}`)."
                  .format(key_or_report, WORKING_REACTION,
                          whoami(client) or "this machine", key_or_report))
            return False
        ok = _react(client, channel, inc["ts"], WORKING_REACTION)
        if note:
            try:
                _send(client, channel, [note], thread_ts=inc["ts"])
            except Exception:  # noqa: BLE001 — the reaction is the point
                pass
        print("[incident] {}: marked as being worked on ({})".format(
            key_or_report, inc["ts"]))
        return ok
    except Exception as e:  # noqa: BLE001
        print("  - couldn't mark {} as being worked on ({}: {})".format(
            key_or_report, type(e).__name__, str(e)[:80]))
        return False


def _find_any_state(key: str, *, channel: str, client) -> Optional[dict]:
    """This key's parent, open OR resolved — for the jobs that are about the
    REACTIONS on a post rather than about the incident's state. find() answers
    only `open` ones on purpose (it is used to decide where an alert goes); a
    mark left on a closed post still has to be reachable."""
    if not _valid(key):
        return None
    for msg in _history(client, channel):
        m = _MARK_RE.search(msg.get("text") or "")
        if m and m.group("key") == key:
            return {"ts": msg.get("ts"), "state": m.group("state"),
                    "text": msg.get("text") or ""}
    return None


def mark_not_working(key_or_report: str, *, channel: str = CHANNEL,
                     dry_run: bool = False, client=None) -> bool:
    """The inverse of mark_working: "nobody is on this one after all."

    Takes Lucy's :pending: / waiting mark back off a post without touching the
    incident's state — the ticket stays exactly as open (or as closed) as it was.
    Two uses, both real (Megan 2026-08-20):

      • a mark the OLD code left behind. The 4am batch imports hub_publish at
        04:00 and keeps it in memory all morning, so a `git pull` at 08:29 does
        not stop the running process from marking; failure-credico_fetch got a
        :pending: at 08:30 from code that had already been fixed on disk.
      • somebody picked a ticket up, then put it down.

    Only Lucy's own reaction can come off (Slack has no removing another user's),
    so this belongs on the mini — the CLI hands it there, same as --working.
    Works on a CLOSED post too, which is why it looks the parent up through
    _find_any_state rather than find(). Never raises."""
    try:
        client = client or _client()
        inc = next((i for i in (_find_any_state(k, channel=channel, client=client)
                                for k in candidate_keys(key_or_report)) if i), None)
        if not inc or not inc.get("ts"):
            print("[incident] no post found for {} — nothing to un-mark"
                  .format(key_or_report))
            return False
        if dry_run:
            print("[incident] DRY-RUN — would clear :{}: / :{}: on {}".format(
                WORKING_REACTION, WAITING_REACTION, inc["ts"]))
            return True
        ok = _react(client, channel, inc["ts"], WORKING_REACTION, remove=True)
        _react(client, channel, inc["ts"], WAITING_REACTION, remove=True)
        print("[incident] {}: in-progress mark cleared ({}, still {})".format(
            key_or_report, inc["ts"], inc.get("state")))
        return ok
    except Exception as e:  # noqa: BLE001
        print("  - couldn't un-mark {} ({}: {})".format(
            key_or_report, type(e).__name__, str(e)[:80]))
        return False


def candidate_keys(key_or_report: str) -> List[str]:
    """Every key a hand-typed string could name, most literal first.

    WHY (2026-08-19): "is this a KEY or a REPORT ID?" was answered by prefix
    alone — `failure-`/`drop-`/`standalone-`/`finding-` meant key, anything else
    meant report id and got expanded by keys_for(). But plenty of live threads
    are filed under a CUSTOM key with no prefix at all, because the producer
    picked one thread per KIND of problem rather than per report:
    `vantura-sales-week-hold` / `-failed` / `-roll-due` / `-unknown-poster`
    (vantura_slack_sales.alert), `org-sales-board`, `applicant-tracker-gaps`.
    Copy such a key off its own marker line into `lucy incident_resolve` and the
    prefix test called it a report id, expanded it to `failure-<key>` … which
    matches nothing — "no OPEN incident for 'vantura-sales-week-hold'" while the
    post sits right there. (`org-sales-board` was one of the five hand-offs that
    failed on 2026-08-18; this explains that one, not the prefixed ones.)

    So: try the string EXACTLY as given first, then the expansions. A custom key
    resolves as itself; a bare report id finds nothing under its own name and
    falls through to keys_for() exactly as before."""
    if any(key_or_report.startswith(p) for p in _KEY_PREFIXES):
        return [key_or_report]
    return [key_or_report] + keys_for(key_or_report)


def keys_for(report_id: str) -> List[str]:
    """Every key a report's alerts can be filed under — the orchestrator's, the
    standalone watcher's, the drop alert's AND the finding one, in both the
    underscore id and the dashed manifest id.

    finding- belongs here even though it is a separate FAMILY (see subject()):
    the two questions are different. "Which thread does this witness join?" must
    keep findings out of outage threads; "this report just ran clean, what did it
    leave open?" wants every one of them, and a finding thread is precisely what a
    clean run is supposed to close (2026-08-18)."""
    out: List[str] = []
    for rid in (report_id, _canon(report_id)):
        for p in _KEY_PREFIXES:
            k = p + rid
            if k not in out:
                out.append(k)
    return out


# How often a CLEAN run may ask the channel "is anything of mine open?" when this
# machine's index knows of nothing. A success is the common case (a few hundred a
# day across the machines) and an incident opened on ANOTHER machine is the rare
# one, so this is throttled rather than run per success. A cooldown, not a
# once-a-day flag: a report can break, get fixed, and break again inside one day,
# and a day-long flag would leave that second thread open until tomorrow.
_CLEAN_SCAN_DIR = REPO_ROOT / "output" / "state" / "incident_clean_scans"
_CLEAN_SCAN_COOLDOWN = 4 * 3600
# hub_publish._fail_marker: the "this report already alerted" stamp, dropped when
# the report next runs clean. Path duplicated rather than imported for the same
# reason as _WATCH_SUFFIX — shared/ must not depend on day_orchestrator/.
_FAIL_MARKER_DIR = REPO_ROOT / "output" / "logs"


def _alerted_recently(report_id: str) -> bool:
    """Is there a standing failure alert for this report on THIS machine?

    The cooldown below is sized for the common case — a few hundred clean runs a
    day, almost none of which have anything open. But a report that alerted and
    is now running clean is the exact opposite case: the one time the channel
    scan is certainly worth spending. Without this, a report that alerted on the
    mini and recovered on Lucy 2 inside four hours had its thread left open (and
    its ⏳ left standing), because Lucy 2's index knew nothing and the cooldown
    refused the look (Megan 2026-08-20)."""
    try:
        return (_FAIL_MARKER_DIR / ".failalert-{}".format(report_id)).exists()
    except Exception:  # noqa: BLE001
        return False


def _clean_scan_due(report_id: str) -> bool:
    """True when this machine may spend a channel read confirming that `report_id`
    has nothing open. Stamps the attempt. Any file trouble answers True — an extra
    API call is cheaper than an alert thread left open."""
    import time
    p = _CLEAN_SCAN_DIR / "{}.txt".format(_canon(report_id))
    try:
        if p.exists() and (time.time() - p.stat().st_mtime) < _CLEAN_SCAN_COOLDOWN:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return True


def resolve_report(report_id: str, *, what: str = "", note: str = "",
                   channel: str = CHANNEL, day: Optional[dt.date] = None,
                   dry_run: bool = False, client=None) -> bool:
    """"This report just ran CLEAN" → close whatever failure thread it left open.

    WHY (Eve 2026-08-17): the only things that closed an incident were the 4am
    orchestrator (for reports IN its loop) and the machine_digest watcher (for
    standalone ones, hours later). A person who saw the alert, fixed the cause and
    re-ran the report from the Hub at 2pm closed nothing — the thread sat open all
    day and the other person working the channel spent their time re-diagnosing a
    problem that was already fixed. Now ANY successful run closes it, from any
    machine, whichever witness opened the thread (failure- / standalone- / drop-,
    including a sibling's — see subject()).

    Cost control: the local index is free, and the channel scan that finds a
    thread opened on ANOTHER machine is throttled per report (_clean_scan_due).
    Never raises — closing an alert must never break the run that earned it."""
    day = day or dt.date.today()
    label = what or "*{}*".format(report_id)
    try:
        keys = keys_for(report_id)
        idx = _load_index() or {}
        hit = next((k for k in keys
                    if isinstance(idx.get(k), dict) and idx[k].get("ts")
                    and not idx[k].get("resolved")), None)
        if not hit:
            # Nothing local: either there is no incident, or another machine owns
            # it. A throttled scan decides which — unless this report is carrying
            # a standing failure alert, in which case the answer is worth the
            # call every time (see _alerted_recently).
            if not (_alerted_recently(report_id) or _clean_scan_due(report_id)):
                return False
            found = find(keys[0], channel=channel, client=client, day=day)
            if not found:
                return False
            hit = keys[0]
        lines = ["{} {} — RESOLVED. It just ran clean.".format(DONE_EMOJI, label)]
        if note:
            lines.append(note)
        lines.append("_Closed. If it happens again it opens a fresh post, not "
                     "this thread._")
        return resolve(key=hit, lines=lines, channel=channel, day=day,
                       dry_run=dry_run, client=client)
    except Exception as e:  # noqa: BLE001
        print("  ⚠ couldn't close the incident for {} ({}: {})".format(
            report_id, type(e).__name__, str(e)[:80]), flush=True)
        return False


def resolve_any(key_or_report: str, *, note: str = "", channel: str = CHANNEL,
                day: Optional[dt.date] = None, dry_run: bool = False,
                client=None) -> bool:
    """Close whatever `key_or_report` names — a person typed it, so it may be an
    incident key (custom or prefixed) OR a report id. Tries the string literally
    before expanding it (see candidate_keys), which is the difference between
    closing `vantura-sales-week-hold` and telling the person there is no such
    incident while its post sits in the channel.

    The by-hand counterpart of resolve_report(), which stays report-only on
    purpose: it runs off a CLEAN RUN, and a clean run of report X has no business
    closing a custom thread that merely mentions X."""
    day = day or dt.date.today()
    for key in candidate_keys(key_or_report):
        # find_live, not find: this gate runs BEFORE resolve() and would
        # otherwise skip a thread the local index wrongly believes is closed —
        # which is exactly how `incident_resolve vantura-sales-week-hold` kept
        # answering "no OPEN incident" on 2026-08-19 with the post right there.
        if not find_live(key, channel=channel, client=client, day=day):
            continue
        lines = [":white_check_mark: *{}* — RESOLVED.".format(key)]
        if note:
            lines.append(note)
        lines.append("_Closed by hand. If it happens again it opens a fresh "
                     "post, not this thread._")
        ok = resolve(key=key, lines=lines, channel=channel, day=day,
                     dry_run=dry_run, client=client)
        # resolve()'s dry-run answers off the LOCAL index, which on a laptop that
        # never posted is empty — but we just found the thread in the CHANNEL, so
        # don't report "nothing open" for a key that plainly is.
        return True if dry_run else ok
    return False


def close_stranded(*, channel: str = CHANNEL, client=None,
                   day: Optional[dt.date] = None, dry_run: bool = False,
                   max_age_days: int = 30) -> Dict[str, List[str]]:
    """Finish the parents whose ✅ landed but whose TEXT never got updated.

    WHY THIS KEEPS HAPPENING (Megan 2026-08-26). resolve() posts the reply, then
    edits the parent — and chat.update only touches your OWN messages. So when a
    problem is opened by one machine and fixed from another, the reply lands, the
    ✅ reaction lands, and the marker edit is refused. The thread is genuinely
    closed; the parent still reads `open` forever. resolve()'s own docstring
    describes this ("a resolve run from a LAPTOP posts its reply and is then
    refused the chat.update"), and it already guards against re-announcing such a
    thread — but nothing ever went back and finished the edit.

    Six posts were sitting in that state on 2026-08-26, four opened by Lucy and
    two by Megan's laptop. It is not a one-off: any incident opened on one
    machine and fixed on another lands here.

    THE FIX IS PER-IDENTITY, WHICH IS WHY THIS REPORTS AS WELL AS ACTS. Only the
    poster can edit a post, so this closes what THIS machine owns and NAMES the
    rest, so whoever owns them can run the same command. Returns
    {"closed": [...], "not_ours": [...]} — run it on both machines to finish.

    Narrow on purpose: it only ever touches a parent that ALREADY carries the ✅
    (or already says RESOLVED). It never posts, never replies, never resolves
    anything that isn't already resolved — the fix happened days ago; this is
    only the bookkeeping catching up. Idempotent: _resolved_headline leaves an
    already-stamped line alone, and a parent whose marker is already `resolved`
    is not returned by the scan at all.
    """
    day = day or dt.date.today()
    out: Dict[str, List[str]] = {"closed": [], "not_ours": []}
    try:
        client = client or _client()
        me = whoami(client)
    except Exception as e:  # noqa: BLE001
        print("  - close_stranded: no Slack client ({}: {})".format(
            type(e).__name__, str(e)[:60]))
        return out

    for m in _history(client, channel):
        text = m.get("text") or ""
        mark = _MARK_RE.search(text)
        if not mark or mark.group("state") != "open":
            continue
        reactions = [r.get("name") for r in (m.get("reactions") or [])]
        # The ✅ is the proof the fix landed. Without it this is just an open
        # incident, and closing it would erase a real problem from the board.
        if DONE_REACTION not in reactions and "RESOLVED" not in text.upper():
            continue
        if _days_open(mark.group("date"), day) > max_age_days:
            continue
        key, ts = mark.group("key"), m.get("ts") or ""
        if (m.get("user") or "") != me:
            out["not_ours"].append(key)
            print("  {} ({}) — posted by {}, not this machine. Run this there."
                  .format(key, ts, m.get("user") or "?"))
            continue
        if dry_run:
            print("  DRY-RUN — would close {} ({})".format(key, ts))
            out["closed"].append(key)
            continue
        new_text = "{}\n\n{}".format(
            _MARK_RE.sub("", _resolved_headline(text, day)).rstrip(),
            marker(mark.group("key"), "resolved", day))
        try:
            client.chat_update(channel=channel, ts=ts, text=new_text)
        except Exception as e:  # noqa: BLE001 — the reaction already says done
            print("  - {}: parent edit refused ({}: {})".format(
                key, type(e).__name__, str(e)[:60]))
            continue
        # A fixed problem must not still read as work in progress.
        for r in (WORKING_REACTION, WAITING_REACTION, NEEDS_HUMAN_REACTION):
            if r in reactions:
                _react(client, channel, ts, r, remove=True)
        _mark_resolved_in_index(key, ts=ts, channel=channel)
        out["closed"].append(key)
        print("  {} ({}) — closed".format(key, ts))

    print("[incident] close-stranded: {} closed, {} belong to another machine"
          .format(len(out["closed"]), len(out["not_ours"])))
    if out["not_ours"]:
        print("  run `lucy incident_close_stranded` (or this CLI on that box) "
              "to finish: {}".format(", ".join(sorted(set(out["not_ours"])))))
    return out


def close(key: str) -> None:
    """Forget an incident WITHOUT posting (e.g. it aged out of relevance)."""
    _mark_resolved_in_index(key)


# ---------------------------------------------------------------------- CLI ---

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Inspect / close corrections-channel "
                                             "incident threads.")
    ap.add_argument("--list", action="store_true", help="show open incidents")
    ap.add_argument("--resolve", metavar="KEY", help="close an incident and say "
                                                     "so in its thread")
    ap.add_argument("--working", metavar="KEY_OR_REPORT",
                    help="react :pending: on its post — somebody (or Claude) is "
                         "on it, so the other person doesn't start too")
    ap.add_argument("--unmark", metavar="KEY_OR_REPORT",
                    help="take the :pending: / waiting mark back OFF its post "
                         "— nobody is on it after all. Leaves the incident's "
                         "state alone; works on a closed post too")
    ap.add_argument("--resolve-report", metavar="REPORT_ID",
                    help="close whatever failure thread a report left open "
                         "(failure-/standalone-/drop-, its siblings included) — "
                         "for when a MANUAL fix, not a re-run, cleared it")
    ap.add_argument("--close-stranded", action="store_true",
                    help="finish the parents whose ✅ landed but whose text "
                         "still says `open` — run it on EVERY machine, each one "
                         "can only edit its own posts")
    ap.add_argument("--note", default="", help="one line to add to --resolve")
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    # EVERYTHING this channel shows must come from Lucy (see LUCY_USER_ID). From
    # a laptop the token is the person's own, so the post would land under their
    # name AND the parent could never be re-badged. Rather than half-do it, hand
    # the job to the mini, which is Lucy — the queue is serial, so it runs in
    # order behind whatever else is pending.
    # --close-stranded is DELIBERATELY not in this list. Everything else here is
    # handed to the mini because only Lucy may speak in the channel; that one
    # edits posts THIS machine wrote, and Slack lets nobody else edit them. Hand
    # it to the mini and the laptop's own stranded posts are never finished —
    # which is exactly the state it exists to clear. Run it on both boxes.
    if (a.working or a.unmark or a.resolve
            or a.resolve_report) and not (a.dry_run or is_lucy()):
        act, arg = (("incident_working", a.working) if a.working else
                    ("incident_unmark", a.unmark) if a.unmark else
                    ("incident_resolve", a.resolve or a.resolve_report))
        who = whoami() or "unknown"
        try:
            from automations.day_orchestrator import mini_control as mc
            # machine=DEFAULT_MACHINE ("Lucy 1"), i.e. the 'Mini Control' tab the
            # mini's poller actually drains. This used to say machine="Mini",
            # which _control_tab_for() turns into a SEPARATE tab
            # ('Mini Control - Mini') that no runner polls: every incident
            # hand-off from a laptop sat there 'queued' forever — 10 rows
            # between 2026-07-29 and 2026-08-18, so no :pending: and no ✅ ever
            # appeared while the CLI printed "queued on the MINI". NOT
            # machine=None either: that reads the LOCAL .machine-profile, which
            # would route Lucy 2's hand-off to Lucy 2's own tab. (2026-08-18)
            mc.enqueue(act, "{} {}".format(arg, a.note).strip(),
                       by="incident_thread-cli", machine=mc.DEFAULT_MACHINE)
        except Exception as e:  # noqa: BLE001
            print("this machine posts as {}, not Lucy, and the hand-off to the "
                  "mini failed ({}: {}). Run it on the mini: "
                  "`lucy {} {}`".format(who, type(e).__name__, str(e)[:60],
                                        act, arg))
            return 1
        print("queued on the MINI (`{} {}`) — this machine posts as {}, and "
              "every message in that channel goes out as Lucy.".format(
                  act, arg, who))
        return 0

    if a.working:
        ok = mark_working(a.working, note=a.note, channel=a.channel,
                          dry_run=a.dry_run)
        print("marked" if ok else "nothing open for that key/report")
        return 0 if ok else 1
    if a.close_stranded:
        out = close_stranded(channel=a.channel, dry_run=a.dry_run)
        return 0 if (out["closed"] or not out["not_ours"]) else 1
    if a.unmark:
        ok = mark_not_working(a.unmark, channel=a.channel, dry_run=a.dry_run)
        print("cleared" if ok else "no post found for that key/report")
        return 0 if ok else 1
    if a.resolve_report:
        ok = resolve_report(a.resolve_report, note=a.note, channel=a.channel,
                            dry_run=a.dry_run)
        print("resolved" if ok else "no open incident for that report")
        return 0 if ok else 1
    if a.resolve:
        lines = [":white_check_mark: *Resolved* — {}.".format(_human(dt.date.today()))]
        if a.note:
            lines.append(a.note)
        ok = resolve(key=a.resolve, lines=lines, channel=a.channel,
                     dry_run=a.dry_run)
        print("resolved" if ok else "no open incident for that key")
        return 0 if ok else 1
    idx = _load_index()
    rows = [(k, v) for k, v in sorted(idx.items())
            if isinstance(v, dict) and (a.list is False or not v.get("resolved"))]
    if not rows:
        print("no incidents recorded.")
        return 0
    for k, v in rows:
        print("{:<40} {:<12} opened {}  {} follow-up(s)  ts {}".format(
            k, "RESOLVED" if v.get("resolved") else "OPEN",
            v.get("opened", "?"), v.get("count", 0), v.get("ts", "?")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
