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

import ast
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()
SHIPPED = {l.strip() for l in (HERE / "agent_files.txt").read_text().splitlines()
           if l.strip() and not l.startswith("#")}


def _reaches_the_machine(module: str, names) -> bool:
    """Is `from <module> import <names>` satisfiable from the shipped files?

    A NAME THAT IS A REAL MODULE ON DISK MUST ITSELF SHIP. Falling back to
    "the package's __init__.py ships, so the import is fine" is what let
    run.py's missing closeout.py through: automations/icd_alerts/__init__.py
    is in the manifest, so every `from automations.icd_alerts import ...`
    looked satisfied no matter which sibling was left out.

    The __init__.py fallback is still right for a name that is NOT a module --
    a class or function the package re-exports -- which is why it stays, but
    only for that case.
    """
    path = module.replace(".", "/")
    if "%s.py" % path in SHIPPED:            # a module file
        return True
    for n in names:
        rel = "%s/%s.py" % (path, n)
        if (HERE.parents[1] / rel).exists():
            # It IS a module. Shipping its package says nothing about it.
            if rel not in SHIPPED:
                return False
        elif "%s/__init__.py" % path not in SHIPPED:
            # Not a module, so it has to be something the package re-exports,
            # and that means the package body has to be there to re-export it.
            return False
    return bool(names)


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

    def test_every_shipped_module_only_imports_what_also_ships(self):
        """The same rule, applied to the AGENT and not just the installer.

        setup.py was the only file checked here, so a SHIPPED module importing
        an unshipped one slipped straight through -- and that is the worse
        failure of the two. run.py imports at module level, so a missing
        sibling does not degrade a feature, it stops the agent from starting
        at all, on every machine at once, at the next self-update.

        Caught exactly that on 2026-09-17: closeout.py was added and wired
        into run.py, and the manifest test passed happily because
        package.AGENT_FILES and agent_files.txt were BOTH missing it. Two
        lists agreeing with each other is not the same as either being right.

        READ WITH ast, NOT A REGEX. The first version of this test used one
        and did not catch that very bug: run.py's import is parenthesized
        across two lines, and the pattern stopped at the bracket. A test that
        cannot see the import it was written for is worse than no test.

        MODULE LEVEL ONLY. An import inside a function fails when that path
        runs, which is bad but survivable and sometimes deliberately guarded;
        one at the top of the file takes the whole agent down on import.
        """
        missing = []
        for rel in sorted(SHIPPED):
            path = HERE.parents[1] / rel
            if not path.exists():
                missing.append("%s is in agent_files.txt but is not here"
                               % rel)
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError as e:
                missing.append("%s does not parse: %s" % (rel, e))
                continue
            for node in tree.body:           # tree.body == module level
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if not node.module.startswith("automations"):
                    continue
                names = [a.name for a in node.names]
                if not _reaches_the_machine(node.module, names):
                    missing.append("%s imports %s (%s)"
                                   % (rel, node.module, ", ".join(names)))
        self.assertEqual(
            sorted(set(missing)), [],
            "a shipped agent file imports, at module level, something "
            "install.sh never downloads -- that raises on every ICD machine "
            "and nowhere here")

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
