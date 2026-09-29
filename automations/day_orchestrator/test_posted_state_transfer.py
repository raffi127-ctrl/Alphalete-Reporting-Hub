"""push_posted_state / set_posted_state: the single-owner 'already posted'
memory travels with the office metrics (Lucy 1 -> Lucy 4, 2026-09-29)."""
import base64, io, os, pathlib, tarfile, tempfile, time, unittest
from unittest import mock

from automations.day_orchestrator import mini_control as MC


def _root():
    r = pathlib.Path(tempfile.mkdtemp())
    for d in MC.POSTED_STATE_DIRS:
        (r / "output" / d).mkdir(parents=True)
    return r


class RoundTrip(unittest.TestCase):
    def test_push_then_set_installs_the_same_files(self):
        src, dst = _root(), _root()
        (src / "output/canceled_orders/_posted/aya.json").write_text('{"a": "1"}')
        (src / "output/disconnects/_posted/aya.json").write_text('{"d": "2"}')
        sent = []
        with mock.patch.object(MC, "REPO_ROOT", src), \
                mock.patch.object(MC, "_this_box", return_value="Lucy 1"), \
                mock.patch.object(MC, "_machine_profile", return_value="Lucy 1"), \
                mock.patch.object(MC, "enqueue", side_effect=lambda a, p, **k: sent.append((a, p, k))):
            ok, msg = MC._action_push_posted_state("Lucy 4")
        self.assertTrue(ok, msg)
        self.assertEqual(sent[0][0], "set_posted_state")
        self.assertEqual(sent[0][2]["machine"], "Lucy 4")
        with mock.patch.object(MC, "REPO_ROOT", dst):
            ok, msg = MC._action_set_posted_state(sent[0][1])
        self.assertTrue(ok, msg)
        self.assertEqual((dst / "output/canceled_orders/_posted/aya.json").read_text(), '{"a": "1"}')
        self.assertEqual((dst / "output/disconnects/_posted/aya.json").read_text(), '{"d": "2"}')

    def test_a_newer_local_file_is_kept(self):
        src, dst = _root(), _root()
        f = src / "output/canceled_orders/_posted/aya.json"
        f.write_text("old")
        os.utime(f, (time.time() - 3600, time.time() - 3600))
        (dst / "output/canceled_orders/_posted/aya.json").write_text("newer")
        sent = []
        with mock.patch.object(MC, "REPO_ROOT", src), mock.patch.object(MC, "_this_box", return_value="Lucy 1"), \
                mock.patch.object(MC, "_machine_profile", return_value="Lucy 1"), \
                mock.patch.object(MC, "enqueue", side_effect=lambda a, p, **k: sent.append(p)):
            MC._action_push_posted_state("Lucy 4")
        with mock.patch.object(MC, "REPO_ROOT", dst):
            ok, msg = MC._action_set_posted_state(sent[0])
        self.assertIn("kept 1", msg)
        self.assertEqual((dst / "output/canceled_orders/_posted/aya.json").read_text(), "newer")

    def test_anything_outside_the_two_folders_is_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            data = b"x"
            info = tarfile.TarInfo("../../.config/evil.json"); info.size = 1
            t.addfile(info, io.BytesIO(data))
        dst = _root()
        with mock.patch.object(MC, "REPO_ROOT", dst):
            ok, msg = MC._action_set_posted_state(base64.b64encode(buf.getvalue()).decode())
        self.assertFalse(ok)
        self.assertIn("refused", msg)

    def test_never_to_itself(self):
        with mock.patch.object(MC, "_this_box", return_value="Lucy 4"):
            self.assertFalse(MC._action_push_posted_state("Lucy 4")[0])


if __name__ == "__main__":
    unittest.main()
