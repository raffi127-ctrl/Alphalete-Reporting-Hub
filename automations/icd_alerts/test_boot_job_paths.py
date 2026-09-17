"""The boot job must name the INSTALLED agent, not the copy that wrote it.

install.sh downloads the agent into a mktemp directory and runs setup.py from
there, under whatever system Python the Mac has. Every path in the boot job
was derived from __file__, so during an install they all described the
TEMPORARY copy:

    root   = /var/folders/.../T/tmp.XXXX        deleted minutes later
    python = tmp.XXXX/../venv/bin/python        never existed
             -> fell back to sys.executable     = system python3.9, no patchright

The job was then loaded and ran every two minutes against a directory that no
longer existed: Khalil 131 times on 2026-09-16, Aya 7 times on 2026-09-17.
Both looked installed, both relayed their enrolment, and neither could sweep
until a person ran a repair command afterwards.

Megan, 2026-09-17: "this shouldn't be another step moving forward. we need the
install to just work."
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import boot_schedule as B


def _fake_install(root: pathlib.Path) -> pathlib.Path:
    """A ~/.lucy-reports-shaped tree: app and venv as SIBLINGS."""
    app = root / "app"
    (app / "automations" / "icd_alerts").mkdir(parents=True)
    (app / "automations" / "icd_alerts" / "run.py").write_text("")
    venv = root / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")
    return app


class TheInstalledTreeWinsTest(unittest.TestCase):
    def test_app_root_prefers_the_install_over_this_file(self):
        """The case that broke: setup.py is running from a temp copy, and the
        real install already exists beside it."""
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            app = _fake_install(base)
            with mock.patch.object(B, "INSTALLED_ROOT", app):
                self.assertEqual(B.app_root(), app)

    def test_the_interpreter_is_the_installed_venv_not_sys_executable(self):
        """sys.executable during an install is the Mac's system Python, which
        has no patchright -- so every sweep died on ModuleNotFoundError."""
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            app = _fake_install(base)
            with mock.patch.object(B, "INSTALLED_ROOT", app):
                got = B.venv_python(B.app_root())
            self.assertEqual(got, base / "venv" / "bin" / "python")
            self.assertTrue(got.exists())

    def test_the_plist_names_the_installed_venv_and_app(self):
        """Asserted against the resolved paths, NOT against the string
        '/var/folders' -- the fixture itself lives there, so that check passes
        or fails for the wrong reason."""
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            app = _fake_install(base)
            with mock.patch.object(B, "INSTALLED_ROOT", app):
                text = B.plist_text(seconds=120)
            want_py = base / "venv" / "bin" / "python"
            self.assertIn("<string>%s</string>" % want_py, text)
            self.assertIn("<key>WorkingDirectory</key><string>%s</string>" % app,
                          text)
            # THE ACTUAL REGRESSION: the interpreter must not be whatever
            # Python is running the installer.
            self.assertNotIn("<string>%s</string>" % sys.executable, text)

    def test_a_checkout_with_no_install_still_resolves(self):
        """The only case that is not an install: somebody running from a
        clone. It must keep working, or this fix breaks development."""
        missing = pathlib.Path("/nonexistent-install-root-for-test")
        with mock.patch.object(B, "INSTALLED_ROOT", missing):
            got = B.app_root()
        self.assertIsNotNone(got)
        self.assertTrue(B._is_app(got))


if __name__ == "__main__":
    unittest.main()
