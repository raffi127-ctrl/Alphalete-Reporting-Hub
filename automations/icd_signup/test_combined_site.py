"""The combined site must not break the tools that are still deployed alone.

Megan 2026-09-13: "I really don't want to keep creating all these apps. Can we
combine them?" The combining is cheap -- st.navigation takes a path, so each
tool stays where it is. The DANGER is the shared file it introduces.

Seven tools are also deployed as their own Community Cloud apps, with owners
holding links to them. Cloud resolves dependencies from a file next to the
entry script or from the repo root, and which wins is not worth betting seven
working tools on. A root requirements.txt that is missing one app's dependency
would take that app out on its next rebuild -- silently, and nowhere near the
change that caused it.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("document_builder", "pay_structure", "office_onboarding",
        "tracker_onboarding", "metric_request", "metric_edit",
        "disposition_signup", "icd_signup")


def _names(path: pathlib.Path):
    out = set()
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.add(re.split(r"[><=]", line)[0].strip().lower())
    return out


class RootRequirementsCoverEveryApp(unittest.TestCase):

    def test_no_app_loses_a_dependency_to_the_root_file(self):
        root = _names(ROOT / "requirements.txt")
        for app in APPS:
            p = ROOT / app / "requirements.txt"
            if not p.exists():
                continue
            missing = _names(p) - root
            self.assertEqual(
                missing, set(),
                "%s needs %s, and the repo-root requirements.txt does not "
                "list it. If Cloud resolves from root on a rebuild, that app "
                "loses it." % (app, sorted(missing)))


class EveryListedToolExists(unittest.TestCase):

    def _tools(self):
        src = (ROOT / "streamlit_app.py").read_text()
        block = src[src.index("TOOLS = ["):src.index("]", src.index("TOOLS = ["))]
        return re.findall(r'\("([^"]+)",\s*"([^"]+)"', block)

    def test_each_tool_points_at_a_real_script(self):
        for path, _url in self._tools():
            self.assertTrue((ROOT / path).is_file(),
                            "streamlit_app.py lists %s, which does not exist" % path)

    def test_tool_urls_are_unique(self):
        # Streamlit derives a page url from its FILENAME, and every tool here
        # is called app.py -- so without an explicit url_path the second tool
        # added collides with the first and one of them becomes unreachable.
        urls = [u for _p, u in self._tools()]
        self.assertEqual(len(urls), len(set(urls)), "two tools share a url")

    def test_an_unlisted_tool_is_still_registered(self):
        """Unlisted means NOT OFFERED, never NOT REACHABLE.

        Daily Dispositions is being retired, so it is off the front page -- but
        its ?confirm=<key> deep link is how a sign-up already in flight gets
        approved. Dropping the page instead of unlisting it would break that
        at the moment Megan next tried to approve somebody, with nothing to
        connect the failure to this change.
        """
        src = (ROOT / "streamlit_app.py").read_text()
        block = src[src.index("TOOLS = ["):src.index("]\n\n\ndef home")]
        self.assertIn("daily-dispositions", block)
        # and it must still be handed to st.navigation, not filtered out
        nav = src[src.index("pages = ["):]
        self.assertIn("for p, u, t, i, _who, _listed in TOOLS", nav)
        self.assertNotIn("if _listed", nav)

    def test_the_entry_script_sets_no_page_config(self):
        # Each tool calls its own as its first Streamlit command; a second call
        # in the same run raises and takes the whole site down.
        src = (ROOT / "streamlit_app.py").read_text()
        self.assertNotIn("set_page_config(", src)


if __name__ == "__main__":
    unittest.main()
