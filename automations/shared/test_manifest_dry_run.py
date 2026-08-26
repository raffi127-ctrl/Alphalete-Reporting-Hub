"""A dry run may write its manifest. It may not speak in the channel.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_manifest_dry_run

WHY (Megan 2026-08-26). write_manifest had no `dry_run` parameter at all, and on
a clean run it calls section_drop_alert.resolved() — which posts "RESOLVED, it
just ran clean" into the report's open incident thread and closes the ticket.
So a REHEARSAL reached into #claudecorrections and edited a live incident.

That is the worst shape a side effect can take: the whole point of --dry-run is
that you can run it against production to see what WOULD happen, and everyone
here uses it that way (the project rule is literally "always --dry-run while
testing"). A flag people trust to be inert must actually be inert.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class ManifestDryRunTest(unittest.TestCase):

    def setUp(self):
        from automations.shared import run_manifest as rm
        from automations.shared import section_drop_alert as sda
        self.rm, self.sda = rm, sda
        self.calls = []
        for name in ("resolved", "alert"):
            real = getattr(sda, name)
            self.addCleanup(setattr, sda, name, real)
            setattr(sda, name, self._spy(name))
        # keep manifests out of the real output dir
        tmp = Path(tempfile.mkdtemp())
        if hasattr(rm, "MANIFEST_DIR"):
            real_dir = rm.MANIFEST_DIR
            rm.MANIFEST_DIR = tmp
            self.addCleanup(setattr, rm, "MANIFEST_DIR", real_dir)

    def _spy(self, name):
        def fn(*a, **k):
            self.calls.append((name, k.get("dry_run")))
            return True
        return fn

    def test_a_clean_dry_run_does_not_speak_for_real(self):
        self.rm.write_manifest("test_report_dry", failed=[], ok=True,
                               dry_run=True)
        resolved = [c for c in self.calls if c[0] == "resolved"]
        self.assertTrue(resolved, "the resolver should still be consulted")
        self.assertTrue(all(d is True for _, d in resolved),
                        "a dry run must pass dry_run through, got %r" % resolved)

    def test_a_failing_dry_run_does_not_page_anyone(self):
        self.rm.write_manifest("test_report_dry", failed=["a"], ok=False,
                               dry_run=True)
        alerts = [c for c in self.calls if c[0] == "alert"]
        self.assertTrue(alerts)
        self.assertTrue(all(d is True for _, d in alerts),
                        "a dry run must not post a real drop alert, got %r"
                        % alerts)

    def test_a_real_run_still_speaks(self):
        """The guard must not silence the live path it exists to protect."""
        self.rm.write_manifest("test_report_dry", failed=[], ok=True)
        resolved = [c for c in self.calls if c[0] == "resolved"]
        self.assertTrue(resolved)
        self.assertTrue(all(not d for _, d in resolved),
                        "a live run must still close its incident, got %r"
                        % resolved)


if __name__ == "__main__":
    unittest.main()
