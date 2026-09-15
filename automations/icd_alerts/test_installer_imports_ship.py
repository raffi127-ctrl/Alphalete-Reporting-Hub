"""Everything the installer imports must actually reach an ICD's machine.

install.sh fetches the files in agent_files.txt, plus dist/setup.py and
offices_public.json. Nothing else exists over there.

So an import that works perfectly on our laptops can raise on every ICD's Mac.
It did: the fix that was supposed to ask Carlos for his SaraPlus login
imported automations.icd_signup.schema, which is not shipped -- so the import
raised before the question could be asked, and the login was skipped a second
time (2026-09-15). The office saw no error that meant anything.

The module this catches is always one WE have, which is why eyes do not catch
it.
"""
from __future__ import annotations

import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()
SHIPPED = {l.strip() for l in (HERE / "agent_files.txt").read_text().splitlines()
           if l.strip() and not l.startswith("#")}


def _reaches_the_machine(module: str, names) -> bool:
    """Is `from <module> import <names>` satisfiable from the shipped files?"""
    path = module.replace(".", "/")
    if "%s.py" % path in SHIPPED:            # a module file
        return True
    if "%s/__init__.py" % path in SHIPPED:   # a package: each name must ship
        return all("%s/%s.py" % (path, n) in SHIPPED
                   or "%s/__init__.py" % path in SHIPPED for n in names)
    return False


class TheInstallerOnlyImportsWhatItShips(unittest.TestCase):

    def test_every_automations_import_is_shipped(self):
        missing = []
        for module, raw in re.findall(
                r"from\s+(automations[\w.]*)\s+import\s+([^\n(]+)", SETUP):
            names = [n.strip().split(" as ")[0].strip()
                     for n in raw.split(",") if n.strip()]
            if not _reaches_the_machine(module, names):
                missing.append("%s (%s)" % (module, ", ".join(names)))
        self.assertEqual(
            sorted(set(missing)), [],
            "setup.py imports modules that install.sh never downloads, so "
            "these raise on every ICD machine and nowhere else")

    def test_the_campaign_check_uses_a_shipped_module(self):
        # The specific one that bit. config.py is in agent_files.txt.
        self.assertIn("automations/icd_alerts/config.py", SHIPPED)
        # The IMPORT, not the word -- the comment explaining this bug names
        # the module, and asserting on the text made the test fail on its own
        # documentation.
        self.assertNotIn("from automations.icd_signup", SETUP,
                         "the installer reaches for a module that only "
                         "exists on our side")


if __name__ == "__main__":
    unittest.main()
