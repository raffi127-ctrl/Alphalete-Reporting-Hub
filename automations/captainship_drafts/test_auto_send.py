"""El envío automático de los Captainship Reports (Eve 2026-10-05).

Fija las tres condiciones que puso Eve y la regla de qué se re-arma y qué frena:
  * una sección faltante (la nota amarilla, como Fiber Activations de Tony) no
    sale sola;
  * un tracker de Tableau atrasado frena; uno que se puso al día re-arma;
  * lo que ve la revisión visual se re-arma UNA vez y, si sigue, frena;
  * si la revisión visual no puede correr, NO sale (falla cerrado);
  * los avisos van una vez, y a corrections en un solo hilo por día.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import time
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from automations.captainship_drafts import auto_send as A
from automations.captainship_drafts import config, email_build

DAY = dt.date(2026, 10, 6)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 400


def _write_eml(out: Path, key: str, *, pending: str = "", cid_ok: bool = True):
    msg = EmailMessage()
    msg["Subject"] = "x"
    body = '<div>Hi</div><img src="cid:img1@x">'
    if pending:
        body += (f'<div>— {pending} {email_build.PENDING_MARK} '
                 f'(re-run after fixing the source) —</div>')
    msg.set_content("x")
    msg.add_alternative(body, subtype="html")
    msg.get_payload()[1].add_related(
        PNG, "image", "png", cid="<img1@x>" if cid_ok else "<other@x>")
    (out / f"captainship_draft_{key}_{DAY:%Y%m%d}.eml").write_bytes(bytes(msg))


def _clean_visual(_today, _key):
    return {"ok": True, "issues": []}


def _no_tableau(_today=None):
    return {}, {}, []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(A, "_OUTPUT_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.fiber = next(c.key for c in config.CAPTAINS if c.flavor == "fiber")
        self.b2b = next(c.key for c in config.CAPTAINS if c.flavor == "b2b")


class TestStructural(Base):
    def test_missing_draft(self):
        self.assertEqual(A.structural_issues(DAY, self.fiber),
                         ["the draft was never built"])

    def test_pending_section_is_named(self):
        _write_eml(self.tmp, self.fiber, pending="Fiber Activations PNG")
        got = A.structural_issues(DAY, self.fiber)
        self.assertEqual(len(got), 1)
        self.assertIn("Fiber Activations PNG", got[0])

    def test_broken_image(self):
        _write_eml(self.tmp, self.fiber, cid_ok=False)
        self.assertTrue(any("broken image" in r
                            for r in A.structural_issues(DAY, self.fiber)))

    def test_clean(self):
        _write_eml(self.tmp, self.fiber)
        self.assertEqual(A.structural_issues(DAY, self.fiber), [])


class TestJudge(Base):
    def test_clean_sends(self):
        _write_eml(self.tmp, self.fiber)
        v = A.judge(DAY, [self.fiber], state={}, visual=_clean_visual,
                    tableau=_no_tableau, verbose=False)[self.fiber]
        self.assertTrue(v.send)

    def test_missing_section_rebuilds_once_then_holds(self):
        _write_eml(self.tmp, self.fiber, pending="Fiber Activations PNG")
        state = {}
        v = A.judge(DAY, [self.fiber], state=state, visual=_clean_visual,
                    tableau=_no_tableau, verbose=False)[self.fiber]
        self.assertTrue(v.fixable and not v.blocked)
        state["rebuilds"][self.fiber] = 1
        v = A.judge(DAY, [self.fiber], state=state, visual=_clean_visual,
                    tableau=_no_tableau, verbose=False)[self.fiber]
        self.assertFalse(v.send)
        self.assertTrue(v.blocked and not v.fixable)

    def test_stale_tracker_holds_only_that_flavor(self):
        _write_eml(self.tmp, self.fiber)
        _write_eml(self.tmp, self.b2b)
        tab = lambda _t: ({"tableau:tracker_att": "only through 10/4"}, {}, [])
        out = A.judge(DAY, [self.fiber, self.b2b], state={},
                      visual=_clean_visual, tableau=tab, verbose=False)
        self.assertTrue(out[self.fiber].blocked)
        self.assertIn("Tableau not updated", out[self.fiber].blocked[0])
        self.assertTrue(out[self.b2b].send)

    def test_tracker_caught_up_rebuilds_once(self):
        _write_eml(self.tmp, self.fiber)
        tab = lambda _t: ({}, {"tableau:tracker_att": "fresh"}, [])
        state = {}
        v = A.judge(DAY, [self.fiber], state=state, visual=_clean_visual,
                    tableau=tab, verbose=False)[self.fiber]
        self.assertEqual(v.fixable, [A.TABLEAU_CAUGHT_UP])
        state["tableau_rebuilt"] = [self.fiber]
        v = A.judge(DAY, [self.fiber], state=state, visual=_clean_visual,
                    tableau=tab, verbose=False)[self.fiber]
        self.assertTrue(v.send)

    def test_frozen_source_hit_by_captainship_holds(self):
        _write_eml(self.tmp, self.b2b)
        tab = lambda _t: ({}, {}, ["OrderLog → Sheet (data only through 10/2)"])
        v = A.judge(DAY, [self.b2b], state={}, visual=_clean_visual,
                    tableau=tab, verbose=False)[self.b2b]
        self.assertTrue(v.blocked)

    def test_visual_blocker_rebuilds_then_holds(self):
        _write_eml(self.tmp, self.b2b)
        asked = []

        def bad(_t, _k, prior=()):
            asked.append(list(prior))
            return {"ok": False, "issues": [
                {"image": 3, "section": "Luke's box", "problem": "different font",
                 "severity": "blocker"}]}
        state = {}
        v = A.judge(DAY, [self.b2b], state=state, visual=bad,
                    tableau=_no_tableau, verbose=False)[self.b2b]
        self.assertEqual(v.fixable, ["Luke's box: different font"])
        state["rebuilds"][self.b2b] = 1
        state["visual"] = {}
        v = A.judge(DAY, [self.b2b], state=state, visual=bad,
                    tableau=_no_tableau, verbose=False)[self.b2b]
        self.assertEqual(v.blocked, ["Luke's box: different font"])
        # La segunda mirada sabe qué buscar (10/6: sin eso salió Wayne).
        self.assertEqual(asked, [[], ["Luke's box: different font"]])

    def test_rebuilt_draft_is_rechecked_for_what_was_found_before(self):
        _write_eml(self.tmp, self.b2b)
        state = {"visual_flagged": {self.b2b: ["5. NI churn: copies Wireless"]}}
        asked = []

        def look(_t, _k, prior=()):
            asked.append(list(prior))
            return {"ok": True, "issues": []}
        A.judge(DAY, [self.b2b], state=state, visual=look,
                tableau=_no_tableau, verbose=False)
        self.assertEqual(asked, [["5. NI churn: copies Wireless"]])

    def test_prior_blockers_go_into_the_prompt(self):
        _write_eml(self.tmp, self.b2b)
        sent = {}
        client = mock.Mock()

        def create(**kw):
            sent.update(kw)
            r = mock.Mock(stop_reason="end_turn")
            r.content = [mock.Mock(type="text", text='{"ok": true, "issues": []}')]
            return r
        client.messages.create.side_effect = create
        A.visual_review(DAY, self.b2b, client=client,
                        prior=["NI churn copies Wireless"])
        texts = [c["text"] for c in sent["messages"][0]["content"]
                 if c["type"] == "text"]
        self.assertTrue(any("NI churn copies Wireless" in t for t in texts))

    def test_minor_issue_still_sends(self):
        _write_eml(self.tmp, self.b2b)
        minor = lambda _t, _k: {"ok": True, "issues": [
            {"image": 1, "section": "x", "problem": "y", "severity": "minor"}]}
        v = A.judge(DAY, [self.b2b], state={}, visual=minor,
                    tableau=_no_tableau, verbose=False)[self.b2b]
        self.assertTrue(v.send)

    def test_visual_failure_fails_closed(self):
        _write_eml(self.tmp, self.b2b)

        def boom(_t, _k):
            raise RuntimeError("Missing API key")
        v = A.judge(DAY, [self.b2b], state={}, visual=boom,
                    tableau=_no_tableau, verbose=False)[self.b2b]
        self.assertFalse(v.send)
        self.assertIn("could not run the visual check", v.blocked[0])

    def test_visual_is_cached_by_draft_hash(self):
        _write_eml(self.tmp, self.b2b)
        calls = []

        def vis(_t, k):
            calls.append(k)
            return {"ok": True, "issues": []}
        state = {}
        for _ in range(3):
            A.judge(DAY, [self.b2b], state=state, visual=vis,
                    tableau=_no_tableau, verbose=False)
        self.assertEqual(calls, [self.b2b])
        _write_eml(self.tmp, self.b2b)      # a rebuild = new bytes = new look
        A.judge(DAY, [self.b2b], state=state, visual=vis,
                tableau=_no_tableau, verbose=False)
        self.assertEqual(calls, [self.b2b, self.b2b])


class TestSwitch(unittest.TestCase):
    def test_starts_tomorrow(self):
        self.assertFalse(A.is_on(dt.date(2026, 10, 5)))
        self.assertTrue(A.is_on(dt.date(2026, 10, 6)))
        self.assertFalse(A.is_on(dt.date(2026, 10, 6), enabled=False))

    def test_one_corrections_thread_per_day(self):
        self.assertEqual(A.incident_key(DAY), "captainship-autosend-2026-10-06")


class TestGateFlow(Base):
    """review_gate.auto_day: todo bien = sale SIN postear; lo arreglado sale con
    su link; lo frenado deja link + nota + un aviso a corrections."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(A, "STATE_DIR", self.tmp / "state")
        p.start()
        self.addCleanup(p.stop)
        from automations.captainship_drafts import review_gate as rg
        self.rg = rg
        self.posted = []          # every Slack message text
        self.links = []           # block keys whose link was posted
        self.sent = []            # captains mailed
        self.parent = None
        client = mock.Mock()
        client.chat_postMessage.side_effect = \
            lambda **kw: self.posted.append(kw["text"]) or {"ts": "1"}

        def ensure_parent(*_a, **_k):
            self.parent = {"ts": "p"}
            return self.parent

        def post_block(_link, _t, block, *_a, **_k):
            self.links.append(block.key)
            self.posted.append(f"{rg.BLOCK_MARKER} {DAY} {block.key}")

        def send_reviewed(_t, only=None, **_k):
            go = [k for k in only if k not in self.fail_send]
            self.sent.extend(go)
            return len(only) - len(go), go
        self.fail_send = set()
        for name, val in (
                ("_client", lambda: client),
                ("_find_post", lambda *_a, **_k: self.parent),
                ("replies", lambda *_a, **_k: [{"text": t} for t in self.posted]),
                ("block_posts", lambda *_a, **_k: {k: {"text": "", "ts": "1"}
                                                   for k in self.links}),
                ("scope_today", lambda *_a, **_k: (set(), "ok")),
                ("_channel", lambda c=None: "C"),
                ("ensure_parent", ensure_parent),
                ("post_block", post_block),
                ("build_pdf", lambda *_a, **_k: "x.pdf"),
                ("upload_pdf", lambda *_a, **_k: "http://link"),
                ("eml_digest", lambda *_a, **_k: "d"),
                ("preview_htmls", lambda *_a, **_k: [("x", "y")]),
                ("send_reviewed", send_reviewed)):
            p = mock.patch.object(rg, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.alerts = []
        p = mock.patch.object(A, "alert_corrections",
                              lambda today, held, **k: self.alerts.append(held))
        p.start()
        self.addCleanup(p.stop)

    def _blocks(self, *keys):
        return [config.block_of(k) for k in keys]

    def _run(self, keys, tab=_no_tableau, rebuild=lambda *a: 0, act=True,
             ticks=1, building_since=None):
        with mock.patch.object(A, "rebuild", rebuild), \
                mock.patch.dict(A.judge.__kwdefaults__,
                                {"visual": _clean_visual, "tableau": tab}):
            for _ in range(ticks):
                rc = self.rg.auto_day(DAY, self._blocks(*keys), act=act,
                                      building_since=building_since)
        return rc

    def test_clean_day_sends_and_posts_nothing(self):
        _write_eml(self.tmp, self.fiber)
        _write_eml(self.tmp, self.b2b)
        rc = self._run([self.fiber, self.b2b], ticks=3)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(self.sent), sorted([self.fiber, self.b2b]))
        self.assertEqual(self.posted, [])        # no link, no thread
        self.assertIsNone(self.parent)
        self.assertEqual(self.alerts, [])
        self.assertEqual(A.local_sent(DAY), {self.fiber, self.b2b})

    def test_rebuilt_one_goes_out_with_its_link(self):
        _write_eml(self.tmp, self.fiber, pending="Fiber Activations PNG")
        _write_eml(self.tmp, self.b2b)

        def fake_rebuild(_t, keys):
            for k in keys:
                _write_eml(self.tmp, k)
            return 0
        self._run([self.fiber, self.b2b], rebuild=fake_rebuild)
        self.assertEqual(sorted(self.sent), sorted([self.fiber, self.b2b]))
        self.assertEqual(self.links, [config.block_of(self.fiber).key])
        self.assertTrue(any("rebuilt automatically" in t for t in self.posted))
        self.assertEqual(self.alerts, [])

    def test_held_gets_link_note_and_one_alert(self):
        _write_eml(self.tmp, self.fiber)
        _write_eml(self.tmp, self.b2b)
        tab = lambda _t: ({"tableau:tracker_att": "behind"}, {}, [])
        rc = self._run([self.fiber, self.b2b], tab=tab, ticks=2)
        self.assertEqual(rc, 1)
        self.assertEqual(self.sent, [self.b2b])
        self.assertEqual(self.links, [config.block_of(self.fiber).key])
        self.assertEqual(len([t for t in self.posted if A.HELD_MARKER in t]), 1)
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(list(self.alerts[0]), [self.fiber])

    def test_upstream_reason_reaches_slack_in_english(self):
        _write_eml(self.tmp, self.fiber)
        with mock.patch.object(self.rg, "scope_today",
                               lambda *_a, **_k: ({self.fiber},
                                                  "fallo sin decir que parte")), \
                mock.patch.object(self.rg.wr, "blocking_reports",
                                  lambda *_a, **_k: ["captainship_knocks"]):
            self._run([self.fiber])
        reason = self.alerts[0][self.fiber][1][0]
        self.assertIn("captainship_knocks", reason)
        self.assertNotIn("fallo", reason)

    def test_failed_send_is_held_not_locked(self):
        _write_eml(self.tmp, self.b2b)
        self.fail_send = {self.b2b}
        rc = self._run([self.b2b])
        self.assertEqual(rc, 1)
        self.assertEqual(A.local_sent(DAY), set())
        self.assertEqual(list(self.alerts[0]), [self.b2b])

    def test_dry_mode_posts_sends_and_rebuilds_nothing(self):
        _write_eml(self.tmp, self.fiber, pending="Fiber Activations PNG")
        rebuilt = []
        self._run([self.fiber], rebuild=lambda t, k: rebuilt.append(k),
                  act=False)
        self.assertEqual((rebuilt, self.posted, self.sent), ([], [], []))


def _age(out: Path, key: str, seconds_ago: float):
    p = out / f"captainship_draft_{key}_{DAY:%Y%m%d}.eml"
    t = time.time() - seconds_ago
    os.utime(p, (t, t))


class TestWhileBuilding(TestGateFlow):
    """Eve 2026-10-06: "que vayan saliendo a medida que se va cerrando cada
    capitania". Con un armado corriendo sale el que ese armado ya cerro; el que
    falta, el viejo o el recien escrito esperan; nada se re-arma ni se frena."""

    def setUp(self):
        super().setUp()
        self.since = time.time() - 3600          # el armado arranco hace 1 h

    def test_finished_one_goes_the_rest_waits(self):
        _write_eml(self.tmp, self.fiber)
        _age(self.tmp, self.fiber, 600)          # lo cerro hace 10 min
        rc = self._run([self.fiber, self.b2b], building_since=self.since)
        self.assertEqual(rc, 1)                  # b2b sigue esperando
        self.assertEqual(self.sent, [self.fiber])
        self.assertEqual((self.posted, self.alerts), ([], []))

    def test_missing_draft_is_not_a_failure_after_ten(self):
        late = mock.Mock(wraps=dt.datetime)
        late.now = lambda: dt.datetime(2026, 10, 6, 11)
        with mock.patch.object(self.rg.dt, "datetime", late):
            rc = self._run([self.b2b], building_since=self.since)
        self.assertEqual(rc, 1)
        self.assertEqual((self.sent, self.posted, self.alerts), ([], [], []))

    def test_draft_from_before_this_build_waits(self):
        _write_eml(self.tmp, self.fiber)
        _age(self.tmp, self.fiber, 7200)         # de antes que arrancara
        self._run([self.fiber], building_since=self.since)
        self.assertEqual(self.sent, [])

    def test_draft_still_being_written_waits(self):
        _write_eml(self.tmp, self.fiber)         # mtime = ahora
        self._run([self.fiber], building_since=self.since)
        self.assertEqual(self.sent, [])

    def test_needs_rebuild_waits_without_rebuilding_or_holding(self):
        _write_eml(self.tmp, self.fiber, pending="Fiber Activations PNG")
        _age(self.tmp, self.fiber, 600)
        rebuilt = []
        rc = self._run([self.fiber], building_since=self.since,
                       rebuild=lambda t, k: rebuilt.append(k))
        self.assertEqual(rc, 1)
        self.assertEqual((rebuilt, self.sent, self.posted, self.alerts),
                         ([], [], [], []))

    def test_tableau_behind_still_holds(self):
        _write_eml(self.tmp, self.fiber)
        _age(self.tmp, self.fiber, 600)
        tab = lambda _t: ({"tableau:tracker_att": "behind"}, {}, [])
        self._run([self.fiber], tab=tab, building_since=self.since)
        self.assertEqual(self.sent, [])
        self.assertEqual(list(self.alerts[0]), [self.fiber])


class TestBuildStarted(unittest.TestCase):
    PS = ("  101  01:12:30 python -m automations.captainship_drafts.review_gate"
          " --ensure-posted\n"
          "  102     05:10 python -m automations.captainship_drafts.run"
          " --dry-run --block luke\n"
          "  103     00:02 python -m automations.captainship_drafts.review_gate"
          " --check --send --building\n"
          "  104  1-00:00:00 /usr/sbin/cron\n")

    def test_oldest_build_process_wins(self):
        got = A.build_started(self.PS)
        self.assertAlmostEqual(time.time() - got, 4350, delta=5)

    def test_the_check_itself_is_not_a_build(self):
        ps = ("  103  00:02 python -m automations.captainship_drafts.review_gate"
              " --check --building\n")
        self.assertIsNone(A.build_started(ps))

    def test_etime_shapes(self):
        self.assertEqual(A._etime_seconds("05:10"), 310)
        self.assertEqual(A._etime_seconds("01:12:30"), 4350)
        self.assertEqual(A._etime_seconds("2-01:00:00"), 176400)


if __name__ == "__main__":
    unittest.main()
