"""The Mac and Windows installers have to stay twins.

WINDOWS IS THE PLATFORM NOBODY TESTS. Both pilot offices were Macs, and every
fix since has been written and watched on a Mac. That makes drift between
install.sh and install.ps1 a bug with a very long fuse: it lands on the first
PC office, weeks later, as "it just doesn't work" from somebody who cannot
tell us why.

These are shape checks, not behaviour -- PowerShell cannot be executed here.
They catch the failure that actually happens: one installer learning a step
the other never does.
"""
from __future__ import annotations

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SH = (HERE / "install.sh").read_text()
PS = (HERE / "install.ps1").read_text()
USH = (HERE / "update.sh").read_text()
UPS = (HERE / "update.ps1").read_text()
XSH = (HERE / "uninstall.sh").read_text()
XPS = (HERE / "uninstall.ps1").read_text()


class InstallersDoTheSameThings(unittest.TestCase):

    STEPS = (
        ("agent_files.txt", "fetches the file list rather than baking it in"),
        ("dist/setup.py", "runs the same setup"),
        ("offices_public.json", "reads the public office record"),
        ("install.json", "writes the same install record"),
        ('urlencode({"office"', "falls back to the relay for a signed-up office"),
    )

    def test_both_installers_do_every_step(self):
        for needle, why in self.STEPS:
            self.assertIn(needle, SH, "install.sh no longer %s" % why)
            self.assertIn(needle, PS, "install.ps1 %s -- it does not %s"
                                      % ("is missing a step", why))

    def test_both_carry_the_office_key(self):
        # The key is the identity. An installer that lost it would enrol a
        # machine as nobody.
        self.assertIn("KEY", SH)
        self.assertIn("LUCY_KEY", PS)

    def test_windows_asks_for_python_the_reliable_way(self):
        # A bare `python` on Windows is very often the Microsoft Store stub,
        # which prints an advert and exits -- indistinguishable from a broken
        # install unless `py` is tried first.
        self.assertLess(PS.index("'py'"), PS.index("'python'"),
                        "install.ps1 must try the py launcher before python")


class UpdatersDoTheSameThings(unittest.TestCase):

    def test_both_fetch_the_list_instead_of_baking_it(self):
        for text, name in ((USH, "update.sh"), (UPS, "update.ps1")):
            self.assertIn("agent_files.txt", text,
                          "%s bakes in its own file list, which is how an "
                          "update becomes a successful-looking no-op" % name)

    def test_both_write_to_a_temp_file_first(self):
        self.assertIn(".new", USH)
        self.assertIn(".new", UPS)

    def test_both_prove_the_agent_still_imports(self):
        for text, name in ((USH, "update.sh"), (UPS, "update.ps1")):
            self.assertIn("import automations.icd_alerts.run", text,
                          "%s does not check the agent still starts" % name)


class UninstallersDoTheSameThings(unittest.TestCase):
    """There has to be a way OFF, and it has to be the same way on both.

    Revoking an office used to switch its key off on our side while its
    computer kept waking up, opening a browser and talking to a relay that
    refused it -- forever, on a machine we do not own.
    """

    # (file, how it stops the schedule, how it deletes)
    PAIRS = ((XSH, "uninstall.sh", "launchctl unload", "rm -rf"),
             (XPS, "uninstall.ps1", "schtasks /Delete", "Remove-Item -Recurse"))

    def test_both_stop_the_schedule_before_deleting_the_program(self):
        # Deleting the program out from under a running tick leaves a
        # half-finished browser and a job that keeps retrying it.
        for text, name, stop, delete in self.PAIRS:
            self.assertIn(stop, text, "%s never stops the schedule" % name)
            self.assertIn(delete, text, "%s never deletes anything" % name)
            self.assertLess(text.index(stop), text.index(delete),
                            "%s deletes the program before stopping it" % name)

    def test_both_ask_before_deleting_anything(self):
        for text, name in ((XSH, "uninstall.sh"), (XPS, "uninstall.ps1")):
            self.assertIn("REMOVE", text,
                          "%s deletes a login without asking" % name)

    def test_the_prompt_reads_from_the_terminal_not_stdin(self):
        """`curl ... | bash` makes stdin the PIPE.

        A plain `read` then gets EOF immediately, takes it as "no", and prints
        "Nothing was changed" before the person has typed anything -- leaving
        them believing it was removed when nothing was (Megan, 2026-09-13).
        """
        self.assertIn("read -r answer < /dev/tty", XSH,
                      "uninstall.sh asks a question it cannot hear the answer to")

    def test_both_remove_the_saved_logins(self):
        # They live ONLY on that machine. Leaving them on a computer that is
        # finished with the program is the worst of both.
        for text, name in ((XSH, "uninstall.sh"), (XPS, "uninstall.ps1")):
            self.assertIn("lucy-reports", text, name)


if __name__ == "__main__":
    unittest.main()
