"""Never post the same (or nearly the same) photo twice; one message = one post.

    python -m unittest automations.brand_audit.test_photo_dupes

Slack, downloads and the photo screen are fakes: nothing is sent or posted.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from automations.brand_audit import photo_edit, social_inbox as S


def _photo(seed: int, bright: float = 1.0, size=(640, 480)) -> bytes:
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (12, 16, 3), dtype=np.uint8)
    im = Image.fromarray(small).resize(size, Image.BILINEAR)
    arr = np.clip(np.asarray(im, dtype=np.float32) * bright, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=90)
    return buf.getvalue()


class Fingerprint(unittest.TestCase):
    def test_same_shot_resent_matches_different_shot_does_not(self):
        a = photo_edit.dhash(_photo(1))
        resaved = photo_edit.dhash(_photo(1, bright=1.08, size=(1200, 900)))
        other = photo_edit.dhash(_photo(2))
        self.assertLessEqual(photo_edit.hash_distance(a, resaved), S.SAME_PHOTO_BITS)
        self.assertGreater(photo_edit.hash_distance(a, other), S.SAME_PHOTO_BITS)

    def test_twin_of_skips_itself(self):
        h = photo_edit.dhash(_photo(1))
        seen = [{"ts": "1.0", "h": f"{h:016x}"}]
        self.assertIsNone(S.twin_of(seen, h, "1.0"))
        self.assertEqual(S.twin_of(seen, h, "2.0")["ts"], "1.0")


class FakeSlack:
    def __init__(self, msgs, reactions=None):
        self.msgs, self.posts, self.reactions = msgs, [], reactions or {}

    def conversations_history(self, **kw):
        return {"messages": self.msgs}

    def conversations_replies(self, channel, ts, **kw):
        msgs = [{"ts": ts, "reactions": self.reactions.get(ts, [])}]
        msgs += [{"ts": p["ts"], "reactions": self.reactions.get(p["ts"], [])}
                 for p in self.posts if p.get("thread_ts") == ts]
        return {"messages": msgs}

    def chat_postMessage(self, **kw):
        kw["ts"] = f"9.{len(self.posts)}"
        self.posts.append(kw)
        return {"ts": kw["ts"]}

    def chat_getPermalink(self, channel, message_ts):
        return {"permalink": f"https://slack.test/{message_ts}"}


def _msg(ts, n=1, form=True):
    from automations.online_presence import post_form
    return {"ts": ts, "user": post_form.JIRAIYA if form else "U1",
            "text": "📸 *New post from <@U1>*\n*Who:* Sarah\n*What:* first sale" if form else "",
            "files": [{"mimetype": "image/jpeg", "url_private": f"u{ts}-{i}"} for i in range(n)]}


class Inbox(unittest.TestCase):
    """Runs process_inbox up to the duplicate gate; the photo screen 'stops'
    every photo that passes the gate, so nothing past it runs."""

    def _run(self, cl, photos, state=None, dry=False):
        from automations.online_presence.offices import Presence
        tmp = Path(tempfile.mkdtemp())
        P = Presence(key="t", business_name="T Co", slack_channel="C1", approvers=["U9"])
        state_file = tmp / "social_inbox.json"
        if state:
            S._save_state(state, state_file)
        with mock.patch.object(Presence, "path", lambda self, n: tmp / n), \
                mock.patch.object(S, "_client", return_value=cl), \
                mock.patch.object(S, "_download", side_effect=lambda u: photos[u]), \
                mock.patch.object(photo_edit, "quality_report", return_value={}), \
                mock.patch.object(photo_edit, "process_bytes", side_effect=lambda b, **k: b), \
                mock.patch.object(photo_edit, "is_too_blurry", return_value=False), \
                mock.patch.object(S, "screen_photo", return_value=["(test stop)"]):
            acts = S.process_inbox(dry_run=dry, profile=P)
        return acts, S._load_state(state_file)

    def test_same_photo_twice_is_held_with_a_link_to_the_first(self):
        cl = FakeSlack([_msg("200.0"), _msg("100.0")])          # newest first, like Slack
        photos = {"u200.0-0": _photo(1, bright=1.05), "u100.0-0": _photo(1)}
        state = {"100.0": {}}
        acts, st = self._run(cl, photos)
        held = [a for a in acts if a["action"] == "duplicate_held"]
        self.assertEqual(len(held), 1)                            # only ONE of the pair
        hold = next(p for p in cl.posts if ":repeat:" in p["text"])
        self.assertIn("https://slack.test/", hold["text"])
        self.assertEqual(len(st[S._HASHES]), 2)

    def test_different_photos_both_go_through(self):
        cl = FakeSlack([_msg("200.0"), _msg("100.0")])
        photos = {"u200.0-0": _photo(2), "u100.0-0": _photo(1)}
        acts, _ = self._run(cl, photos)
        self.assertFalse([a for a in acts if a["action"] == "duplicate_held"])

    def test_already_posted_photo_resent_later_is_caught(self):
        tmp = Path(tempfile.mkdtemp()) / "old.jpg"
        tmp.write_bytes(_photo(3))
        cl = FakeSlack([_msg("300.0")])
        state = {"100.0": {"posted": True, "photo_path": str(tmp)}}   # before the guard
        acts, _ = self._run(cl, {"u300.0-0": _photo(3)}, state)
        self.assertEqual([a["matches"] for a in acts if a["action"] == "duplicate_held"],
                         [["100.0"]])

    def test_approver_check_lets_it_through_x_skips_it(self):
        h = f"{photo_edit.dhash(_photo(1)):016x}"
        base = {"_photo_hashes": [{"ts": "100.0", "h": h}, {"ts": "200.0", "h": h}],
                "200.0": {"dup_ts": "9.0"}}
        ok = FakeSlack([_msg("200.0")], {"9.0": [{"name": "white_check_mark", "users": ["U9"]}]})
        ok.posts.append({"ts": "9.0", "thread_ts": "200.0", "text": "hold"})
        acts, st = self._run(ok, {"u200.0-0": _photo(1)}, dict(base))
        self.assertTrue(st["200.0"]["dup_ok"])
        self.assertFalse([a for a in acts if a["action"] == "duplicate_held"])

        no = FakeSlack([_msg("200.0")], {"9.0": [{"name": "x", "users": ["U9"]}]})
        no.posts.append({"ts": "9.0", "thread_ts": "200.0", "text": "hold"})
        acts, st = self._run(no, {"u200.0-0": _photo(1)}, dict(base))
        self.assertEqual(acts[-1]["action"], "duplicate_dropped")
        self.assertTrue(st["200.0"]["posted"])

    def test_two_photos_in_one_message_both_edited_and_checked(self):
        cl = FakeSlack([_msg("100.0", n=2)])
        photos = {"u100.0-0": _photo(1), "u100.0-1": _photo(2)}
        with mock.patch.object(photo_edit, "process_bytes",
                               side_effect=lambda b, **k: b) as edit:
            acts, st = self._run(cl, photos)
        keys = sorted(x["ts"] for x in st[S._HASHES])
        self.assertEqual(keys, ["100.0", "100.0#1"])            # both fingerprinted
        self.assertFalse([a for a in acts if a["action"] == "duplicate_held"])
        self.assertFalse([p for p in cl.posts if "in one message" in p["text"]])

    def test_same_shot_twice_inside_one_post_is_held(self):
        cl = FakeSlack([_msg("100.0", n=2)])
        photos = {"u100.0-0": _photo(1), "u100.0-1": _photo(1, bright=1.05)}
        acts, _ = self._run(cl, photos)
        self.assertEqual([a["matches"] for a in acts if a["action"] == "duplicate_held"],
                         [["100.0"]])
        self.assertIn("photo 2 looks like photo 1 in this same post",
                      next(p["text"] for p in cl.posts if ":repeat:" in p["text"]))

    def test_more_than_ten_photos_told_once(self):
        cl = FakeSlack([_msg("100.0", n=12)])
        photos = {f"u100.0-{i}": _photo(10 + i) for i in range(12)}
        acts, st = self._run(cl, photos)
        self.assertEqual(len([p for p in cl.posts if "up to 10 photos" in p["text"]]), 1)
        self.assertEqual(len(st[S._HASHES]), 10)


    def test_photo_dropped_straight_in_gets_pointed_at_the_button_once(self):
        import time
        ts = f"{time.time() + 60:.6f}"
        cl = FakeSlack([_msg(ts, form=False)])
        from automations.due_diligence import watch
        with mock.patch.object(watch, "_client", side_effect=Exception("no jiraiya here")):
            acts, st = self._run(cl, {f"u{ts}-0": _photo(1)})
        self.assertEqual([a["action"] for a in acts], ["use_the_button"])
        self.assertIn("New post", cl.posts[0]["text"])
        self.assertEqual(cl.posts[0]["thread_ts"], ts)
        acts, _ = self._run(cl, {f"u{ts}-0": _photo(1)}, st)
        self.assertEqual(acts, [])                                 # never twice
        self.assertEqual(len(cl.posts), 1)

    def test_old_drops_are_left_alone_and_in_flight_ones_finish(self):
        cl = FakeSlack([_msg("200.0", form=False), _msg("100.0", form=False)])
        acts, _ = self._run(cl, {"u100.0-0": _photo(1)}, {"100.0": {}})
        self.assertNotIn("use_the_button", [a["action"] for a in acts])
        self.assertEqual({a["ts"] for a in acts}, {"100.0"})        # 100 carries on; 200 untouched
        self.assertEqual(cl.posts and [p for p in cl.posts if "New post" in p["text"]], [])

    def test_dry_run_sends_nothing(self):
        cl = FakeSlack([_msg("200.0", n=2), _msg("100.0")])
        photos = {"u200.0-0": _photo(1), "u200.0-1": _photo(1), "u100.0-0": _photo(1)}
        acts, _ = self._run(cl, photos, dry=True)
        self.assertIn("duplicate_held", [a["action"] for a in acts])
        self.assertEqual(cl.posts, [])


class Album(unittest.TestCase):
    def test_relay_zip_unpacks_in_order_on_the_office_computer(self):
        from automations.icd_alerts import social_post
        from automations.online_presence import relay
        tmp = Path(tempfile.mkdtemp())
        srcs = []
        for i in range(3):
            p = tmp / f"src{i}.jpg"
            p.write_bytes(_photo(i))
            srcs.append(p)
        out = Path(tempfile.mkdtemp())
        got = social_post._unpack_album(relay.album_bytes(srcs), out)
        self.assertEqual([Path(g).read_bytes() for g in got], [p.read_bytes() for p in srcs])

    def test_album_job_hands_every_photo_to_zoho(self):
        import base64
        from automations.icd_alerts import social_post
        from automations.online_presence import relay
        tmp = Path(tempfile.mkdtemp())
        srcs = [tmp / "a.jpg", tmp / "b.jpg"]
        for i, p in enumerate(srcs):
            p.write_bytes(_photo(i))
        sent = {}
        with mock.patch.object(relay, "enqueue", side_effect=lambda o, k, pl, live: sent.update(pl) or "J1"):
            relay.enqueue_post("t", "cap", srcs, ["instagram"], live=False)
        self.assertEqual(sent["media"], "album")
        seen = {}
        from automations.brand_audit import zoho_draft
        def fake_post(caption, image, *a, **k):
            seen["n"] = len(image)
            return {"ok": True, "channels": ["instagram"]}
        with mock.patch.object(social_post, "_busy", return_value=False), \
                mock.patch.object(zoho_draft, "post_now", side_effect=fake_post):
            res = social_post.post(sent, live=True, log=lambda *a: None)
        self.assertEqual((res["status"], seen["n"]), ("posted", 2))


if __name__ == "__main__":
    unittest.main()
