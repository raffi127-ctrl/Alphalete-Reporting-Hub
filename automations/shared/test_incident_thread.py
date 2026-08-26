"""Tests for the corrections-channel incident threads.

The behaviour these lock down is the whole point of the module (Eve 2026-08-14):
a repeat must REPLY in the first message's thread, never add a second top-level
post, and a fix must be announced IN that thread and close it.

    python -m unittest automations.shared.test_incident_thread -v
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.shared import alert_thread as at
from automations.shared import incident_thread as inc


class FakeClient:
    """Records posts; serves them back as channel history the way Slack does."""

    def __init__(self):
        self.posts = []          # (thread_ts or None, text)
        self.updates = []        # (ts, text)
        self.reactions = []      # (ts, emoji name)
        self.history_calls = 0
        self._n = 0

    def auth_test(self):
        """The fake IS Lucy — that's the machine these flows run on. mark_working
        refuses to add a :pending: it could never remove, so a client with no
        identity would silently stop marking anything (see OnlyLucyMarksItWorked)."""
        return {"user_id": inc.LUCY_USER_ID}

    def chat_postMessage(self, *, channel, text, thread_ts=None, **_kw):
        self._n += 1
        ts = f"{self._n}.0000"
        self.posts.append((thread_ts, text))
        return {"ok": True, "ts": ts, "channel": channel}

    def chat_update(self, *, channel, ts, text, **_kw):
        self.updates.append((ts, text))
        # Slack really does rewrite the message, and the marker lives in it — a
        # fake that skipped this would hide whether resolve() closes the scan.
        i = int(float(ts)) - 1
        if 0 <= i < len(self.posts):
            self.posts[i] = (self.posts[i][0], text)
        return {"ok": True}

    def refuse_updates(self):
        """Simulate posting from a DIFFERENT machine/identity: chat.update is
        refused (`cant_update_message`), only replies get through."""
        def _boom(**_kw):
            raise RuntimeError("cant_update_message")
        self.chat_update = _boom

    def refuse_replies(self):
        """The other half: the PARENT edit works but Slack rejects threaded
        posts (what happened to b2b_metrics on 2026-08-17 — its detail chunk
        went missing in the same second)."""
        real = self.chat_postMessage

        def _maybe(*, channel, text, thread_ts=None, **kw):
            if thread_ts:
                raise RuntimeError("ratelimited")
            return real(channel=channel, text=text, thread_ts=thread_ts, **kw)
        self.chat_postMessage = _maybe

    def reactions_add(self, *, channel, timestamp, name):
        if (timestamp, name) in self.reactions:
            raise RuntimeError("already_reacted")
        self.reactions.append((timestamp, name))
        return {"ok": True}

    def reactions_remove(self, *, channel, timestamp, name):
        if (timestamp, name) not in self.reactions:
            raise RuntimeError("no_reaction")
        self.reactions.remove((timestamp, name))
        return {"ok": True}

    def conversations_history(self, *, channel, limit=200, cursor=None,
                              latest=None, oldest=None, inclusive=False):
        # Newest first, parents only — same shape as the real API. latest/oldest
        # + inclusive narrows to the window, which is how _parent_still_open
        # fetches exactly one message.
        self.history_calls += 1
        msgs = []
        for i, (thread_ts, text) in enumerate(self.posts, start=1):
            if thread_ts:
                continue
            ts = f"{i}.0000"
            if latest is not None and (float(ts) > float(latest)
                                       or (not inclusive
                                           and float(ts) == float(latest))):
                continue
            if oldest is not None and (float(ts) < float(oldest)
                                       or (not inclusive
                                           and float(ts) == float(oldest))):
                continue
            replies = sum(1 for t, _ in self.posts if t == ts)
            msgs.append({"ts": ts, "text": text, "reply_count": replies})
        return {"messages": list(reversed(msgs))}

    def conversations_replies(self, *, channel, ts, limit=200, **_kw):
        """Parent first, then its replies — the shape _thread_is_closed reads."""
        msgs = []
        i = int(float(ts)) - 1
        if 0 <= i < len(self.posts):
            msgs.append({"ts": ts, "text": self.posts[i][1]})
        for j, (thread_ts, text) in enumerate(self.posts, start=1):
            if thread_ts == ts:
                msgs.append({"ts": f"{j}.0000", "text": text})
        return {"messages": msgs}

    # helpers
    @property
    def top_level(self):
        return [t for th, t in self.posts if not th]

    @property
    def replies(self):
        return [t for th, t in self.posts if th]


class IncidentThreadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._real_state = inc.STATE_PATH
        inc.STATE_PATH = Path(self.tmp.name) / "incident_threads.json"
        self.addCleanup(lambda: setattr(inc, "STATE_PATH", self._real_state))
        self._real_scans = inc._CLEAN_SCAN_DIR
        inc._CLEAN_SCAN_DIR = Path(self.tmp.name) / "clean_scans"
        self.addCleanup(lambda: setattr(inc, "_CLEAN_SCAN_DIR", self._real_scans))
        inc._HISTORY_CACHE.clear()
        self.addCleanup(inc._HISTORY_CACHE.clear)
        self.c = FakeClient()

    def _open(self, day, *, title="🚨 *r* — broke", body=("*Error:* boom",),
              details=("detail",), followup=None):
        inc._HISTORY_CACHE.clear()
        return inc.open_or_followup(key="failure-r", title=title, body=list(body),
                                    details=list(details), followup=followup,
                                    channel="C1", day=day, client=self.c)

    def test_first_time_posts_parent_and_detail(self):
        res = self._open(dt.date(2026, 8, 14))
        self.assertTrue(res["new"])
        self.assertEqual(len(self.c.top_level), 1)
        self.assertIn("_incident · failure-r · open 2026-08-14_",
                      self.c.top_level[0])
        self.assertIn("detail", "\n".join(self.c.replies))

    # --- what the CHANNEL shows vs what the THREAD shows (Megan 2026-08-18) ---

    def test_the_channel_line_is_short_and_emoji_free(self):
        """"Too hard to read … an emoji in the alert gets confusing and all
        bogged up." The parent is one plain line — what broke, a few words on
        why — so the ✅ / :pending: REACTIONS are the only emoji on it."""
        self._open(dt.date(2026, 8, 14),
                   title="🚨 :rotating_light: *Alphalete Org Sales Board* — ran, "
                         "but 1 didn't fill",
                   body=["*Error:* Didn't fill: section: BOX — 1 part(s) missing.",
                         "🕐 2 new captainship rep(s) waiting for a ✅"])
        head = self.c.top_level[0].splitlines()[0]
        self.assertEqual(head, "*Alphalete Org Sales Board* — ran, but 1 didn't fill")
        # No emoji anywhere in the channel message, marker line included.
        self.assertEqual(self.c.top_level[0],
                         at.strip_emoji(self.c.top_level[0]))
        # …and the parent is the headline + the marker, nothing else.
        self.assertEqual(len([l for l in self.c.top_level[0].splitlines()
                              if l.strip()]), 2)

    def test_nothing_is_lost_it_moves_into_the_thread(self):
        """The error and the extra facts still arrive — in the reply, which is
        where the whole story lives now."""
        self._open(dt.date(2026, 8, 14),
                   title="🚨 *r* — broke",
                   body=["*Error:* Didn't fill: section: BOX",
                         "🕐 2 rep(s) waiting"],
                   details=["*To re-run it:* `lucy r`"])
        thread = "\n".join(self.c.replies)
        for kept in ("Didn't fill: section: BOX", "2 rep(s) waiting",
                     "To re-run it"):
            self.assertIn(kept, thread)

    def test_a_repeat_the_same_day_edits_one_line_and_posts_nothing(self):
        """Eve 2026-08-17: "no quiero repitencias en el mismo día". A re-run that
        fails again must not add a message to the channel OR to the thread — the
        thread keeps ONE status line and it gets edited."""
        day = dt.date(2026, 8, 14)
        first = self._open(day)
        replies = len(self.c.replies)
        again = self._open(day)
        self.assertFalse(again["new"])
        self.assertEqual(again["ts"], first["ts"])
        self.assertEqual(len(self.c.top_level), 1, "a repeat must not add a post")
        self.assertEqual(len(self.c.replies), replies + 1, "one status line")
        self.assertIn("Failed again today", self.c.replies[-1])
        self.assertIn("1 more run", self.c.replies[-1])
        # A third failure edits that same line — still no new message.
        self._open(day)
        self.assertEqual(len(self.c.replies), replies + 1, "still one line")
        self.assertIn("2 more run", self.c.updates[-1][1])

    def test_the_next_day_opens_its_own_post(self):
        """Eve 2026-08-17: "si falla mañana que mañana se abra un nuevo hilo"."""
        first = self._open(dt.date(2026, 8, 14))
        tomorrow = self._open(dt.date(2026, 8, 15))
        self.assertTrue(tomorrow["new"])
        self.assertNotEqual(tomorrow["ts"], first["ts"])
        self.assertEqual(len(self.c.top_level), 2)
        # Yesterday's thread says where the story went, and its marker is closed
        # so no machine keeps rolling it over.
        self.assertIn("this thread ends here",
                      "\n".join(self.c.replies).lower())
        self.assertIn("· resolved 2026-08-15", self.c.updates[-1][1])

    def test_a_thread_is_only_rolled_over_once_ever(self):
        """Megan 2026-08-23: "these alerts don't make any sense posting on a
        fixed header thread from Wed". drop-tableau-screenshots-box's parent was
        posted from a LAPTOP on 08-19, so Lucy could never chat.update it — the
        marker stayed `open`, and the thread collected FOUR "Still open after N
        day(s)" lines (08-20, then 08-23 at 08:06, 08:12 and 12:00) on top of
        five resolutions. The marker can only be written by whoever posted the
        parent; the THREAD can be read by anyone, so that is the signal."""
        first = self._open(dt.date(2026, 8, 19))
        self.c.refuse_updates()                  # a parent this token can't edit
        parent = {"ts": first["ts"], "text": self.c.top_level[0],
                  "marker_key": "failure-r"}
        # The same stale-open parent, found again on four separate runs — the
        # real shape: three of drop-tableau-screenshots-box's four lines landed
        # on ONE day, 08:06 / 08:12 / 12:00, because nothing about it had changed.
        for age, dayn in ((1, 20), (4, 23), (4, 23), (4, 23)):
            inc._HISTORY_CACHE.clear()
            inc.STATE_PATH.unlink(missing_ok=True)   # each run, another machine
            inc._roll_over(self.c, "C1", parent, "failure-r", age,
                           dt.date(2026, 8, dayn))
        rolled = [r for r in self.c.replies if "thread ends here" in r]
        self.assertEqual(len(rolled), 1, "one roll-over line, however many runs")
        # The marker really is still `open` — the edit was refused every time,
        # exactly as Slack does it. Silence has to come from the THREAD instead.
        self.assertIn("· open 2026-08-19", self.c.top_level[0])

    def test_a_resolved_thread_is_never_rolled_over(self):
        """It isn't "still open after 4 days" — it was closed on day one. That
        thread had five resolution replies when the fourth roll-over landed."""
        self._open(dt.date(2026, 8, 19))
        self.c.refuse_updates()
        inc.resolve(key="failure-r", lines=[
            ":white_check_mark: *r* — RESOLVED. It just ran clean.",
            "_Closed. If it happens again it opens a fresh post, not this "
            "thread._"], channel="C1", day=dt.date(2026, 8, 19), client=self.c)
        inc._HISTORY_CACHE.clear()
        inc.STATE_PATH.unlink(missing_ok=True)
        self._open(dt.date(2026, 8, 23))
        self.assertEqual([r for r in self.c.replies if "thread ends here" in r],
                         [], "a closed thread is not rolled over")

    def test_an_unreadable_thread_stays_quiet(self):
        """The reverse of resolve()'s tie-break, on purpose: a missing roll-over
        line is a lost pointer to a post in the same channel, a repeated one is
        the noise being complained about."""
        self._open(dt.date(2026, 8, 19))

        def _boom(**_kw):
            raise RuntimeError("ratelimited")
        self.c.conversations_replies = _boom
        self._open(dt.date(2026, 8, 20))
        self.assertEqual([r for r in self.c.replies if "thread ends here" in r],
                         [])

    def test_yesterdays_thread_is_found_and_rolled_over_with_no_local_index(self):
        """Another machine opened it — the marker in the message is the state,
        so the rollover has to work off the channel scan alone."""
        self._open(dt.date(2026, 8, 14))
        inc.STATE_PATH.unlink()
        inc._HISTORY_CACHE.clear()
        again = self._open(dt.date(2026, 8, 15))
        self.assertTrue(again["new"])
        self.assertEqual(len(self.c.top_level), 2)

    def test_resolve_posts_in_thread_and_closes(self):
        first = self._open(dt.date(2026, 8, 14))
        ok = inc.resolve(key="failure-r", lines=["✅ *r* — RESOLVED."],
                         channel="C1", day=dt.date(2026, 8, 15), client=self.c)
        self.assertTrue(ok)
        self.assertEqual(self.c.replies[-1], "✅ *r* — RESOLVED.")
        self.assertEqual(self.c.updates[-1][0], first["ts"])
        self.assertIn("resolved 2026-08-15", self.c.updates[-1][1])
        self.assertNotIn("failure-r", inc.open_keys())
        # A NEW failure after the fix opens a fresh post, not the closed thread.
        after = self._open(dt.date(2026, 8, 20))
        self.assertTrue(after["new"])

    def test_resolve_closes_even_when_the_parent_edit_is_refused(self):
        """Cross-machine: the reply lands, the edit doesn't, and the incident
        still has to count as closed — otherwise the next failure replies into a
        thread everyone has stopped reading."""
        self._open(dt.date(2026, 8, 14))
        self.c.refuse_updates()
        self.assertTrue(inc.resolve(key="failure-r", lines=["✅ done"],
                                    channel="C1", day=dt.date(2026, 8, 15),
                                    client=self.c))
        self.assertEqual(self.c.replies[-1], "✅ done")
        after = self._open(dt.date(2026, 8, 20))
        self.assertTrue(after["new"])
        self.assertEqual(len(self.c.top_level), 2)

    def test_resolve_counts_when_only_the_parent_edit_lands(self):
        """The 2026-08-17 b2b_metrics case: Slack refuses the in-thread reply but
        the parent edit succeeds. resolve() must report SUCCESS — it returned the
        reply's fate before, and notify.resolve_failure_alert read that as
        'resolve failed' and overwrote the parent with its own marker-less ✅,
        erasing the line every other machine scans for."""
        first = self._open(dt.date(2026, 8, 14))
        self.c.refuse_replies()
        self.assertTrue(inc.resolve(key="failure-r", lines=["✅ done"],
                                    channel="C1", day=dt.date(2026, 8, 15),
                                    client=self.c))
        self.assertEqual(self.c.updates[-1][0], first["ts"])
        self.assertIn("_incident · failure-r · resolved 2026-08-15_",
                      self.c.updates[-1][1])
        self.assertNotIn("failure-r", inc.open_keys())

    def test_resolve_is_false_when_nothing_landed_at_all(self):
        """Both halves refused → the caller's own fallback edit is the only thing
        left, so it must still be told the resolve didn't take."""
        self._open(dt.date(2026, 8, 14))
        self.c.refuse_replies()
        self.c.refuse_updates()
        self.assertFalse(inc.resolve(key="failure-r", lines=["✅ done"],
                                     channel="C1", day=dt.date(2026, 8, 15),
                                     client=self.c))

    def test_resolve_with_nothing_open_is_a_no_op(self):
        self.assertFalse(inc.resolve(key="failure-nope", lines=["x"],
                                     channel="C1", client=self.c))
        self.assertEqual(self.c.posts, [])

    def test_an_old_thread_says_how_long_it_has_been_open(self):
        self._open(dt.date(2026, 8, 1))
        res = self._open(dt.date(2026, 9, 1))
        self.assertTrue(res["new"], "a month-old thread should start over")
        self.assertEqual(len(self.c.top_level), 2)
        self.assertIn("Still open after 31 day(s)", "\n".join(self.c.replies))

    def test_unsafe_key_is_refused_not_posted_wrong(self):
        self.assertIsNone(inc.open_or_followup(key="has space", title="t",
                                               body=["b"], channel="C1",
                                               client=self.c))
        self.assertEqual(self.c.posts, [])

    # --- families: one outage, several witnesses, ONE thread ------------------

    def _open_key(self, key, day, *, title=None, body=("*Error:* boom",)):
        inc._HISTORY_CACHE.clear()
        return inc.open_or_followup(key=key, title=title or f"🚨 *{key}* — broke",
                                    body=list(body), channel="C1", day=day,
                                    client=self.c)

    def test_watch_miss_replies_in_the_drop_thread(self):
        """The 2026-08-17 case: box_order_log dropped its pull so nothing posted,
        and 13 minutes later the post-watch reported no post. One outage, two
        witnesses — the channel must gain ONE item, not two."""
        day = dt.date(2026, 8, 17)
        first = self._open_key("drop-box-order-log", day)
        second = self._open_key("failure-box_order_log__watch", day)
        self.assertFalse(second["new"])
        self.assertEqual(second["ts"], first["ts"])
        self.assertEqual(len(self.c.top_level), 1)
        thread = "\n".join(self.c.replies)
        self.assertIn("Also failed today:", thread)
        self.assertIn("failure-box_order_log__watch", thread)
        # …and it is NOT miscounted as a recurrence of the first witness.
        self.assertNotIn("Happened again", thread)

    def test_family_uses_the_declared_manifest_alias(self):
        """carlos_focus's drop alerts are filed under its manifest id
        (`carlos-1on1s-run`, from schedule_config's verify block), which no amount
        of string normalising would match — the config is what links them."""
        self.assertEqual(inc.subject("failure-carlos_focus"),
                         inc.subject("drop-carlos-1on1s-run"))

    def test_normalisation_and_watch_suffix(self):
        for a, b in (("failure-tableau_screenshots", "drop-tableau-screenshots"),
                     ("failure-box_order_log__watch", "drop-box-order-log"),
                     ("standalone-att_cancels", "failure-att_cancels")):
            self.assertEqual(inc.subject(a), inc.subject(b), f"{a} vs {b}")

    def test_findings_and_nonew_keep_their_own_thread(self):
        """A finding is about the NUMBERS of a report that ran; a nonew is
        benign. Neither belongs inside an outage thread."""
        self.assertNotEqual(inc.subject("finding-b2b_metrics"),
                            inc.subject("failure-b2b_metrics"))
        self.assertIsNone(inc.subject("nonew-applicant_push"))
        day = dt.date(2026, 8, 17)
        self._open_key("failure-b2b_metrics", day)
        res = self._open_key("finding-b2b_metrics", day)
        self.assertTrue(res["new"])
        self.assertEqual(len(self.c.top_level), 2)

    def test_two_finding_witnesses_share_one_thread(self):
        """2026-08-18: vantura_board_audit posted the same two Stations findings
        TWICE in one morning — run_manifest's section_drop_alert under the dashed
        manifest id, then the orchestrator's finding post under the underscore
        registry id. Two layers, one problem, one thread."""
        day = dt.date(2026, 8, 18)
        first = self._open_key("finding-vantura-board-audit", day)
        second = self._open_key("finding-vantura_board_audit", day)
        self.assertFalse(second["new"])
        self.assertEqual(second["ts"], first["ts"])
        self.assertEqual(len(self.c.top_level), 1)
        # …and it still isn't an outage: a real failure of the same report opens
        # its own post rather than replying under the findings.
        third = self._open_key("failure-vantura_board_audit", day)
        self.assertTrue(third["new"])
        self.assertEqual(len(self.c.top_level), 2)

    def test_a_clean_run_closes_the_finding_thread(self):
        """resolve_report() is "this just ran clean" — and a finding thread is
        exactly what a clean run should close. keys_for() has to reach it."""
        self.assertIn("finding-vantura_board_audit",
                      inc.keys_for("vantura_board_audit"))
        self.assertIn("finding-vantura-board-audit",
                      inc.keys_for("vantura_board_audit"))

    def test_resolving_a_shared_thread_keeps_the_parents_own_marker(self):
        """The sibling that recovers closes the thread — but the marker must keep
        naming the key that OPENED it, or every other machine loses the thread."""
        day = dt.date(2026, 8, 17)
        self._open_key("drop-box-order-log", day)
        self._open_key("failure-box_order_log__watch", day)
        ok = inc.resolve(key="failure-box_order_log__watch", lines=["✅ posted"],
                         channel="C1", day=dt.date(2026, 8, 18), client=self.c)
        self.assertTrue(ok)
        self.assertIn("_incident · drop-box-order-log · resolved 2026-08-18_",
                      self.c.updates[-1][1])
        # Both witnesses are closed, so tomorrow's failure opens a FRESH post
        # rather than replying into a thread that already reads ✅.
        self.assertEqual(inc.open_keys(), [])
        after = self._open_key("drop-box-order-log", dt.date(2026, 8, 19))
        self.assertTrue(after["new"])
        self.assertEqual(len(self.c.top_level), 2)

    def test_owner_variant_joins_the_base_reports_thread(self):
        """The other half of 2026-08-17: box_order_log_roshan is the SAME pull and
        the same module as box_order_log aimed at another owner, and the stale-ID
        export broke both. The drop alert already filed Roshan's miss as
        `drop-box-order-log`; the mini's standalone failure opened its own post."""
        day = dt.date(2026, 8, 17)
        first = self._open_key("drop-box-order-log", day)
        second = self._open_key("standalone-box_order_log_roshan", day)
        self.assertFalse(second["new"])
        self.assertEqual(second["ts"], first["ts"])
        self.assertEqual(len(self.c.top_level), 1)
        self.assertIn("Also failed today:", "\n".join(self.c.replies))
        # Abel and per_office were registered days apart and need no list.
        for variant in ("standalone-box_order_log_abel",
                        "failure-box_order_log_per_office"):
            self.assertEqual(inc.subject(variant), inc.subject("drop-box-order-log"),
                             variant)

    def test_a_shared_prefix_alone_is_not_a_family(self):
        """country_sales_board_email extends country_sales_board's id but runs a
        DIFFERENT module (board_emails) — the board filling short and its email
        failing are two problems, so a prefix alone must not merge them."""
        self.assertNotEqual(inc.subject("failure-country_sales_board_email"),
                            inc.subject("failure-country_sales_board"))

    def test_a_sibling_witness_keeps_its_paste_to_claude_block(self):
        """The thin witness posts first (the Hub's "closed a run FAILED" beat the
        mini's full alert by 4 minutes), so the rich sibling joins its thread. Its
        details are new information, not a repeat — they must land."""
        day = dt.date(2026, 8, 17)
        inc._HISTORY_CACHE.clear()
        inc.open_or_followup(key="failure-box_order_log_roshan", title="❌ failed",
                             body=["*Error:* status failed"], details=["thin"],
                             channel="C1", day=day, client=self.c)
        inc._HISTORY_CACHE.clear()
        inc.open_or_followup(key="standalone-box_order_log_roshan", title="❌ failed",
                             body=["*Error:* status failed"],
                             details=["```PASTE THIS TO CLAUDE```"],
                             channel="C1", day=day, client=self.c)
        self.assertEqual(len(self.c.top_level), 1)
        self.assertIn("PASTE THIS TO CLAUDE", "\n".join(self.c.replies))
        # A same-day repeat of that key doesn't repeat them — it only edits the
        # status line. (Tomorrow is a NEW post and does carry them again, which
        # is the point of a per-day thread: it stands on its own.)
        before = "\n".join(self.c.replies).count("PASTE THIS TO CLAUDE")
        inc._HISTORY_CACHE.clear()
        inc.open_or_followup(key="standalone-box_order_log_roshan", title="❌ failed",
                             body=["*Error:* status failed"],
                             details=["```PASTE THIS TO CLAUDE```"],
                             channel="C1", day=day, client=self.c)
        self.assertEqual("\n".join(self.c.replies).count("PASTE THIS TO CLAUDE"),
                         before)
        self.assertEqual(len(self.c.top_level), 1)

    def test_dry_run_touches_nothing(self):
        res = inc.open_or_followup(key="failure-r", title="t", body=["b"],
                                   channel="C1", dry_run=True, client=self.c)
        self.assertTrue(res["new"])
        self.assertEqual(self.c.posts, [])
        self.assertFalse(inc.STATE_PATH.exists())

    # --- a repeat the SAME day still lands in the thread (Eve 2026-08-17) -----

    def _age_last_alert(self, key, seconds):
        """Pretend this key's last reply happened `seconds` ago."""
        import json
        idx = json.loads(inc.STATE_PATH.read_text(encoding="utf-8"))
        idx[key]["last_alert"] = idx[key]["last_alert"] - seconds
        inc.STATE_PATH.write_text(json.dumps(idx), encoding="utf-8")

    def test_a_second_report_breaking_still_gets_its_own_post(self):
        """Folding a repeat into one status line is per KEY: a DIFFERENT report
        breaking in the same minute is news, and still gets its own post."""
        day = dt.date(2026, 8, 17)
        self._open(day)
        inc._HISTORY_CACHE.clear()
        other = inc.open_or_followup(key="failure-other", title="🚨 other",
                                     body=["*Error:* boom"], channel="C1",
                                     day=day, client=self.c)
        self.assertTrue(other["new"])
        self.assertEqual(len(self.c.top_level), 2)

    # --- what a reader sees in the CHANNEL LIST (Eve 2026-08-17) --------------

    def test_resolved_parent_says_so_in_its_headline_and_gets_a_check(self):
        """A grey italic marker at the bottom is not an answer to "which of these
        is still real?" — the headline gains the WORD RESOLVED and the post gets
        the ✅ reaction, which is the part visible without opening anything.

        No ✅ in the text (Megan 2026-08-18): the reaction is the emoji layer, and
        it only stands out if the message itself has none."""
        first = self._open(dt.date(2026, 8, 14))
        inc.resolve(key="failure-r", lines=["done"], channel="C1",
                    day=dt.date(2026, 8, 15), client=self.c)
        head = self.c.updates[-1][1].splitlines()[0]
        self.assertIn("*RESOLVED* Sat Aug 15", head)
        self.assertEqual(head, at.strip_emoji(head), head)
        self.assertIn((first["ts"], "white_check_mark"), self.c.reactions)

    def test_the_check_lands_even_when_the_parent_edit_is_refused(self):
        """Cross-machine: chat.update only touches your own messages, but ANY
        identity can react — so the reaction is what carries the state."""
        first = self._open(dt.date(2026, 8, 14))
        self.c.refuse_updates()
        inc.resolve(key="failure-r", lines=["done"], channel="C1",
                    day=dt.date(2026, 8, 15), client=self.c)
        self.assertIn((first["ts"], "white_check_mark"), self.c.reactions)

    def test_working_on_it_reacts_pending_and_the_fix_clears_it(self):
        first = self._open(dt.date(2026, 8, 17))
        self.assertTrue(inc.mark_working("r", channel="C1", client=self.c))
        self.assertIn((first["ts"], "pending"), self.c.reactions)
        inc.resolve(key="failure-r", lines=["done"], channel="C1",
                    day=dt.date(2026, 8, 17), client=self.c)
        self.assertNotIn((first["ts"], "pending"), self.c.reactions)
        self.assertIn((first["ts"], "white_check_mark"), self.c.reactions)

    def test_a_stale_index_cannot_put_pending_on_a_resolved_thread(self):
        """Megan 2026-08-18: the Applicant Push post wore :pending: AND ✅ at
        once — "it should only ever have 1 or the other". The index is a
        per-machine file: resolve on the mini, re-run on Lucy 2, and Lucy 2's
        copy still said open. mark_working now asks the PARENT before reacting
        and fixes the stale belief instead."""
        first = self._open(dt.date(2026, 8, 14))
        inc.resolve(key="failure-r", lines=["done"], channel="C1",
                    day=dt.date(2026, 8, 14), client=self.c)
        idx = inc._load_index()
        idx["failure-r"]["resolved"] = False        # the OTHER machine's belief
        inc._save_index(idx)
        n_reacts = len(self.c.reactions)
        self.assertFalse(inc.mark_working("failure-r", channel="C1",
                                          client=self.c, scan=False))
        self.assertEqual(len(self.c.reactions), n_reacts,
                         "no reaction may land on a resolved thread")
        self.assertTrue((inc._load_index()["failure-r"]).get("resolved"),
                        "the stale local belief is corrected")

    def test_a_waiting_alert_wears_purple_and_the_fix_swaps_it_for_the_check(self):
        """Approval-gated phases react :large_purple_circle: — the Hub's own
        approval color (Megan 2026-08-18) — and a resolved post only ever wears
        the ✅: purple comes off with :pending: in the same moment."""
        res = inc.open_or_followup(key="standalone-captainship-drafts-approved",
                                   title="*Captainship Reports* — waiting for "
                                         "approval to send email",
                                   body=["*Error:* the day's post hasn't been "
                                         "approved yet"],
                                   reaction=inc.WAITING_REACTION,
                                   channel="C1", day=dt.date(2026, 8, 14),
                                   client=self.c)
        self.assertIn((res["ts"], "large_purple_circle"), self.c.reactions)
        inc._HISTORY_CACHE.clear()
        inc.resolve(key="standalone-captainship-drafts-approved",
                    lines=["approved and sent"], channel="C1",
                    day=dt.date(2026, 8, 14), client=self.c)
        self.assertIn((res["ts"], "white_check_mark"), self.c.reactions)
        self.assertNotIn((res["ts"], "large_purple_circle"), self.c.reactions)

    def test_a_rolled_over_thread_does_not_keep_wearing_pending(self):
        """Megan 2026-08-20: "Lucy is putting a pending reaction on things that
        she's not actually working … it looks like it's been worked on, but it's
        not." The roll-over is how they got STUCK: it flips the parent's marker
        to `resolved`, and find() only ever returns `open` ones, so from that
        moment no resolve on earth can reach the post — whatever mark it is
        wearing is frozen there. Superseded still isn't fixed, so no ✅ appears;
        it just stops claiming somebody is on it."""
        day = dt.date(2026, 8, 17)
        first = self._open(day)
        self.assertTrue(inc.mark_working("r", channel="C1", day=day,
                                         client=self.c))
        self.assertIn((first["ts"], "pending"), self.c.reactions)
        self._open(dt.date(2026, 8, 18))          # next day → roll-over
        self.assertNotIn((first["ts"], "pending"), self.c.reactions)
        self.assertNotIn((first["ts"], "white_check_mark"), self.c.reactions,
                         "superseded is not fixed — no ✅ on a rolled-over post")

    def test_the_purple_waiting_mark_also_comes_off_on_roll_over(self):
        """Same hole, same cure, for the approval-gated alerts."""
        res = inc.open_or_followup(key="failure-r", title="*r* — waiting",
                                   body=["*Error:* not approved yet"],
                                   reaction=inc.WAITING_REACTION, channel="C1",
                                   day=dt.date(2026, 8, 17), client=self.c)
        self.assertIn((res["ts"], "large_purple_circle"), self.c.reactions)
        inc._HISTORY_CACHE.clear()
        self._open(dt.date(2026, 8, 18))
        self.assertNotIn((res["ts"], "large_purple_circle"), self.c.reactions)

    def test_the_cheap_path_will_not_mark_a_thread_from_another_day(self):
        """The index has no expiry — an entry sits there `resolved: false` until
        something closes it. With one thread per DAY, a thread that isn't
        today's is one roll-over from being closed, and marking off it put ⏳ on
        posts from days back (this laptop's index still carried
        `drop-tableau-stale-w-v-uuid-order-log` open from 2026-08-18 on the
        20th). _parent_still_open can't catch it either: an old parent nobody
        has rolled over yet still says `open`."""
        day = dt.date(2026, 8, 17)
        self._open(day)
        idx = inc._load_index()
        idx["failure-r"]["opened"] = "2026-08-17"
        idx["failure-r"]["last"] = "2026-08-17"     # not today
        inc._save_index(idx)
        self.assertFalse(inc.mark_working("failure-r", channel="C1",
                                          client=self.c, scan=False))
        self.assertEqual(self.c.reactions, [],
                         "a stale index entry may not put a mark anywhere")

    def test_the_cheap_path_still_marks_todays_thread(self):
        """The day guard may only ever SUPPRESS a mark — today's still lands."""
        today = dt.date.today()
        first = self._open(today)
        self.assertTrue(inc.mark_working("failure-r", channel="C1",
                                         client=self.c, scan=False))
        self.assertIn((first["ts"], "pending"), self.c.reactions)

    # --- a thread only gets told ONCE (Megan 2026-08-20) ---------------------

    def _resolve_from_a_laptop(self, day):
        """What a resolve run off a laptop leaves behind: the reply lands, the
        parent edit is REFUSED (chat.update only touches your own messages and
        these parents are Lucy's), so the marker still reads `open`."""
        self.c.refuse_updates()
        inc.resolve(key="failure-r", lines=[
            ":white_check_mark: *r* — RESOLVED. It just ran clean.",
            "_Closed. If it happens again it opens a fresh post, not this "
            "thread._"], channel="C1", day=day, client=self.c)

    def test_a_thread_already_resolved_is_not_resolved_a_second_time(self):
        """failure-daily_rep_breakdown, 2026-08-20: resolved from the laptop at
        16:59 (reply posted, parent edit refused, marker left `open`), then
        resolved AGAIN by the mini at 09:25 the next morning — the mini read
        that stale `open` marker and said the whole thing over. Two identical ✅
        replies in one thread. find_live guards against a stale INDEX; the
        parent's MARKER goes stale the same way and nothing was checking it."""
        day = dt.date(2026, 8, 19)
        first = self._open(day)
        self._resolve_from_a_laptop(day)
        replies_after_first = len(self.c.replies)
        self.assertIn("RESOLVED", "\n".join(self.c.replies))
        self.assertIn("· open ", self.c.top_level[0], "the marker is still stale")

        # Now the MINI runs its own clean-run close. Its index never saw the
        # laptop's resolve — that flag is per-machine — so it still believes the
        # incident is open, which is what sends it past find_live's index guard
        # and straight at the stale marker.
        idx = inc._load_index()
        idx["failure-r"]["resolved"] = False
        inc._save_index(idx)
        fresh = FakeClient()
        fresh.posts = list(self.c.posts)
        fresh._n = self.c._n
        fresh.reactions = list(self.c.reactions)
        inc._HISTORY_CACHE.clear()
        ok = inc.resolve(key="failure-r", lines=["✅ *r* — RESOLVED."],
                         channel="C1", day=dt.date(2026, 8, 20), client=fresh)
        self.assertTrue(ok, "the incident IS closed — the caller must be told so")
        self.assertEqual(len(fresh.replies), replies_after_first,
                         "no second resolution reply")
        # …and it still does the half the laptop couldn't: the marker is fixed.
        self.assertIn("· resolved 2026-08-20", fresh.top_level[0])
        self.assertIn((first["ts"], "white_check_mark"), fresh.reactions)

    def test_an_unreadable_thread_still_gets_told(self):
        """The tie-break on a failed read is POST, not stay quiet: losing a
        resolution leaves people working a fixed problem, which this module
        ranks worse than repeating one (the FAILURE LADDER)."""
        self._open(dt.date(2026, 8, 19))
        before = len(self.c.replies)

        def _boom(**_kw):
            raise RuntimeError("ratelimited")
        self.c.conversations_replies = _boom
        inc.resolve(key="failure-r", lines=["✅ *r* — RESOLVED."], channel="C1",
                    day=dt.date(2026, 8, 19), client=self.c)
        self.assertEqual(len(self.c.replies), before + 1)

    # --- taking the mark back off (Megan 2026-08-20) -------------------------

    def test_a_mark_can_be_taken_back_off_without_closing_the_ticket(self):
        """The 4am batch keeps its code in memory all morning, so a mid-morning
        `git pull` doesn't stop it marking the old way — failure-credico_fetch
        got a :pending: at 08:30 from code fixed on disk at 08:29."""
        day = dt.date.today()
        first = self._open(day)
        inc.mark_working("failure-r", channel="C1", day=day, client=self.c)
        self.assertIn((first["ts"], "pending"), self.c.reactions)
        inc._HISTORY_CACHE.clear()
        self.assertTrue(inc.mark_not_working("failure-r", channel="C1",
                                             client=self.c))
        self.assertNotIn((first["ts"], "pending"), self.c.reactions)
        # The ticket is still OPEN — this is about the mark, not the state.
        self.assertIn("· open ", self.c.top_level[0])
        self.assertNotIn((first["ts"], "white_check_mark"), self.c.reactions)

    def test_the_mark_comes_off_a_closed_post_too(self):
        """find() only ever answers `open` posts, so the un-mark has to look the
        parent up a different way or a mark stuck on a resolved post — the exact
        thing being cleaned up — would be unreachable."""
        day = dt.date.today()
        first = self._open(day)
        inc.mark_working("failure-r", channel="C1", day=day, client=self.c)
        inc._HISTORY_CACHE.clear()
        inc.resolve(key="failure-r", lines=["done"], channel="C1", day=day,
                    client=self.c)
        self.c.reactions.append((first["ts"], "pending"))   # left behind
        inc._HISTORY_CACHE.clear()
        self.assertTrue(inc.mark_not_working("failure-r", channel="C1",
                                             client=self.c))
        self.assertNotIn((first["ts"], "pending"), self.c.reactions)

    def test_unmarking_something_that_was_never_posted_is_a_no_op(self):
        self.assertFalse(inc.mark_not_working("failure-nope", channel="C1",
                                              client=self.c))

    def test_working_on_nothing_open_is_a_no_op(self):
        self.assertFalse(inc.mark_working("r", channel="C1", client=self.c))
        self.assertEqual(self.c.reactions, [])

    def test_a_custom_key_can_be_marked_and_closed_by_hand(self):
        """Threads filed under a key with NO family prefix — one thread per KIND
        of problem, not per report (vantura-sales-week-hold, org-sales-board,
        applicant-tracker-gaps). Copying that key off its own marker line into
        `lucy incident_resolve` used to expand it to `failure-<key>` and die on
        "no OPEN incident" with the post sitting right there (2026-08-19)."""
        day = dt.date(2026, 8, 19)
        first = self._open_key("vantura-sales-week-hold", day)
        self.assertTrue(inc.mark_working("vantura-sales-week-hold",
                                         channel="C1", day=day, client=self.c))
        self.assertIn((first["ts"], "pending"), self.c.reactions)
        self.assertTrue(inc.resolve_any("vantura-sales-week-hold",
                                        note="the board was rolled to 8.23",
                                        channel="C1", day=day, client=self.c))
        self.assertIn((first["ts"], "white_check_mark"), self.c.reactions)

    def test_a_bare_report_id_still_expands_after_the_literal_try(self):
        """candidate_keys() puts the literal first, but a report id must still
        reach its prefixed thread — the old behaviour, not replaced by it."""
        day = dt.date(2026, 8, 19)
        first = self._open_key("drop-box-order-log", day)
        self.assertTrue(inc.resolve_any("box_order_log", channel="C1", day=day,
                                        client=self.c))
        self.assertIn((first["ts"], "white_check_mark"), self.c.reactions)

    def test_a_clean_run_closes_whichever_witness_opened_the_thread(self):
        """resolve_report is what hub_publish calls on ANY successful run: the
        person who fixed the cause and re-ran the report from the Hub shouldn't
        have to know that the thread was opened by the drop alert."""
        day = dt.date(2026, 8, 17)
        self._open_key("drop-box-order-log", day)
        self.assertTrue(inc.resolve_report("box_order_log", what="*BOX Order Log*",
                                           channel="C1", day=day, client=self.c))
        self.assertIn("RESOLVED", self.c.replies[-1])
        self.assertEqual(inc.open_keys(), [])

    def test_a_stale_index_does_not_put_a_second_check_on_a_closed_thread(self):
        """This machine's index says open; the channel says it was closed
        elsewhere. Believing the index would ✅ a thread that already reads ✅."""
        day = dt.date(2026, 8, 17)
        self._open(day)
        # Another machine resolves it: the parent's marker now reads `resolved`.
        text = self.c.top_level[0].replace("· open ", "· resolved ")
        self.c.posts[0] = (None, text)
        replies = len(self.c.replies)
        self.assertFalse(inc.resolve(key="failure-r", lines=["done"],
                                     channel="C1", day=day, client=self.c))
        self.assertEqual(len(self.c.replies), replies, "no second ✅")
        self.assertEqual(inc.open_keys(), [], "and the index catches up")

    def test_a_clean_run_with_nothing_open_does_not_scan_every_time(self):
        """The clean path is the common one — hundreds of runs a day — so it must
        not cost a channel read per run."""
        day = dt.date(2026, 8, 17)
        self.assertFalse(inc.resolve_report("nothing_broken", channel="C1",
                                            day=day, client=self.c))
        calls = self.c.history_calls
        self.assertFalse(inc.resolve_report("nothing_broken", channel="C1",
                                            day=day, client=self.c))
        self.assertEqual(self.c.history_calls, calls,
                         "a second clean run inside the cooldown must not re-scan")


    def test_a_poisoned_index_cannot_hide_a_live_thread(self):
        """One missed lookup used to blind a machine for good: resolve() marks
        the key resolved whenever it can't find the thread, and find() then skips
        that ts on every later scan. Five hand-offs died on 2026-08-18 and
        vantura-sales-week-hold could not be closed from either Mac on 8/19,
        while the post sat in the channel the whole time."""
        day = dt.date(2026, 8, 19)
        opened = self._open(day)
        inc._mark_resolved_in_index("failure-r", ts=opened["ts"], channel="C1")
        inc._HISTORY_CACHE.clear()
        self.assertIsNone(
            inc.find("failure-r", channel="C1", client=self.c, day=day,
                     trust_index=False),
            "this is the poisoning being reproduced, not the behaviour we want")
        live = inc.find_live("failure-r", channel="C1", client=self.c, day=day)
        self.assertTrue(live and live["ts"] == opened["ts"],
                        "the thread is open in the channel and has no check")
        self.assertTrue(inc.resolve_any("failure-r", note="fixed", channel="C1",
                                        day=day, client=self.c))
        self.assertTrue(any("RESOLVED" in t for t in self.c.replies))

    def test_a_thread_that_already_has_a_check_is_left_alone(self):
        """The closed-ts filter guards a real case — a parent we closed whose
        edit Slack refused still reads `open`. find_live must NOT re-open that
        one: the check-mark reply in the thread is the tell, so the second look
        can never double a resolution."""
        day = dt.date(2026, 8, 19)
        self.c.refuse_updates()
        self._open(day)
        self.assertTrue(inc.resolve_any("failure-r", note="fixed", channel="C1",
                                        day=day, client=self.c))
        inc._HISTORY_CACHE.clear()
        self.assertIsNone(inc.find_live("failure-r", channel="C1",
                                        client=self.c, day=day))


class ABareCheckIsNotAResolution(unittest.TestCase):
    """The real 2026-08-19 lockout: the `unfilled_icd` alert opens its body with
    a ✅ because the run did its whole job, and _thread_is_closed read that as
    "already resolved" — so captainship-cancel-rate could not be closed by any
    path, key or report id, while its post sat open in the channel."""

    ALERT_BODY = (":white_check_mark: *captainship-cancel-rate* ran fine — every "
                  "tab filled. 2 ICDs didn't fill: Jason Strid (Starr's team, "
                  "0-30), Jason Strid (Starr's team, 30-60).  Detail in thread.")

    def test_the_alerts_own_check_does_not_close_it(self):
        self.assertFalse(inc._is_resolution_reply(self.ALERT_BODY))

    def test_every_writers_resolution_still_counts(self):
        for real in (
                ":white_check_mark: *drop-x* — RESOLVED.",
                ":white_check_mark: *x* — RESOLVED. It just ran clean.",
                "_Closed. If it happens again it opens a fresh post, not this "
                "thread._",
                "_Closed by hand. If it happens again it opens a fresh post, "
                "not this thread._"):
            self.assertTrue(inc._is_resolution_reply(real), real[:40])

    def test_a_thread_holding_only_that_alert_reads_OPEN(self):
        class _C:
            def conversations_replies(self, channel, ts, limit=200):
                return {"messages": [{"ts": ts, "text": "*x* — ran fine"},
                                     {"ts": "2", "text": ABareCheckIsNotAResolution.ALERT_BODY}]}
        self.assertFalse(inc._thread_is_closed(_C(), "C0BK5PRG259", "1"))

    def test_a_thread_that_really_was_closed_still_reads_CLOSED(self):
        class _C:
            def conversations_replies(self, channel, ts, limit=200):
                return {"messages": [
                    {"ts": ts, "text": "*x* — broke"},
                    {"ts": "2", "text": ":white_check_mark: *x* — RESOLVED."}]}
        self.assertTrue(inc._thread_is_closed(_C(), "C0BK5PRG259", "1"))


class OnlyLucyMarksItWorked(unittest.TestCase):
    """Slack only lets you remove your OWN reaction, and the ✅ side always runs
    as Lucy. A :pending: added under any other token therefore never comes off —
    the post wears ⏳ and ✅ at once. Both of 2026-08-19's threads did."""

    class _Client:
        def __init__(self, uid):
            self.uid, self.added = uid, []

        def auth_test(self):
            return {"user_id": self.uid}

        def conversations_history(self, **kw):
            return {"messages": []}

        def reactions_add(self, channel, timestamp, name):
            self.added.append(name)

    def _run(self, uid):
        c = self._Client(uid)
        inc._HISTORY_CACHE.clear()
        found = {"ts": "1787160187.277349", "key": "drop-x"}
        real_find, real_open = inc.find_live, inc._parent_still_open
        inc.find_live = lambda k, **kw: found
        inc._parent_still_open = lambda *a, **kw: True
        try:
            ok = inc.mark_working("drop-x", client=c)
        finally:
            inc.find_live, inc._parent_still_open = real_find, real_open
        return ok, c.added

    def test_lucy_marks_it(self):
        ok, added = self._run(inc.LUCY_USER_ID)
        self.assertTrue(ok)
        self.assertEqual(added, [inc.WORKING_REACTION])

    def test_anyone_else_does_not(self):
        ok, added = self._run("U088E2KJEV8")   # evelyns.sobrino, the Windows box
        self.assertFalse(ok)
        self.assertEqual(added, [], "a mark nobody can remove is worse than none")


class CloseStranded(unittest.TestCase):
    """The parents whose ✅ landed but whose text never got the edit.

    Only the poster can edit a post, so the contract under test is: close what
    THIS identity wrote, name the rest, and never touch a parent with no ✅.
    """

    OURS = inc.LUCY_USER_ID      # FakeClient.auth_test authenticates as Lucy
    THEIRS = "ULAPTOP"

    def setUp(self):
        self.c = FakeClient()
        inc._HISTORY_CACHE.clear()
        self.addCleanup(inc._HISTORY_CACHE.clear)

    def _post(self, key, user, reactions=(), state="open"):
        for r in reactions:
            self.c.reactions.append(("1.0", r))
        return {"ts": "1.0", "user": user,
                "text": "*{}* — broke\n\n_incident · {} · {} 2026-08-26_".format(
                    key, key, state),
                "reactions": [{"name": r} for r in reactions]}

    def _run(self, messages, **kw):
        with mock.patch.object(inc, "_history", return_value=messages), \
             mock.patch.object(inc, "_mark_resolved_in_index"):
            return inc.close_stranded(client=self.c,
                                      day=dt.date(2026, 8, 26), **kw)

    def test_closes_our_own_checked_post(self):
        out = self._run([self._post("a", self.OURS, ["white_check_mark"])])
        self.assertEqual(out["closed"], ["a"])
        self.assertTrue(self.c.updates, "the parent should have been edited")
        new = self.c.updates[-1][-1]
        self.assertIn("RESOLVED", new)
        self.assertIn("· a · resolved", new)

    def test_names_but_never_edits_another_machines_post(self):
        out = self._run([self._post("a", self.THEIRS, ["white_check_mark"])])
        self.assertEqual((out["closed"], out["not_ours"]), ([], ["a"]))
        self.assertEqual(self.c.updates, [],
                         "editing someone else's post can only fail")

    def test_a_post_without_the_check_is_a_real_open_problem(self):
        """No ✅ means the fix never landed. Closing it would erase it."""
        out = self._run([self._post("a", self.OURS, ["pending"])])
        self.assertEqual((out["closed"], out["not_ours"]), ([], []))
        self.assertEqual(self.c.updates, [])

    def test_already_resolved_marker_is_not_rewritten(self):
        out = self._run([self._post("a", self.OURS, ["white_check_mark"],
                                    state="resolved")])
        self.assertEqual(out["closed"], [])
        self.assertEqual(self.c.updates, [])

    def test_in_progress_marks_come_off_a_closed_post(self):
        self._run([self._post("a", self.OURS, ["white_check_mark", "pending"])])
        self.assertNotIn(("1.0", "pending"), self.c.reactions,
                         "a fixed problem must not still read as in progress")
        self.assertIn(("1.0", "white_check_mark"), self.c.reactions,
                      "the ✅ is the whole proof — it stays")

    def test_dry_run_touches_nothing(self):
        out = self._run([self._post("a", self.OURS, ["white_check_mark"])],
                        dry_run=True)
        self.assertEqual(out["closed"], ["a"])
        self.assertEqual(self.c.updates, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
