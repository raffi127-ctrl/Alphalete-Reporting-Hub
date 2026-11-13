"""Lucy ECO runs in the background. This is the list of every place it does not.

Megan, 2026-11-13: "let's make it so everything runs in the background,
including all future things that we launch on Lucy Eco. Our goal should be
that they almost don't even know that Lucy is running on their machine."

THE RULE. Anything that runs on an office's computer by itself -- a read, a
push, a post, a send -- opens NOTHING the owner can see: a hidden browser, no
dialog, no window brought forward. A window is allowed only when a PERSON has
to do something in it (type a code, pick from a list, approve a password
box), and then only while that person is at the screen.

HOW IT IS KEPT. `scan()` reads every file that ships to offices
(agent_files.txt) and finds the ways code puts something on a screen. Each
one found has to be listed in ALLOWED below with WHY -- so a new report that
opens a window fails `test_visible_windows` until somebody has decided, in
writing, that a person really is needed there. Nothing here is imported by
the agent's sweeps; it is the list and the scanner, nothing else.

WHY (one of):
  person   a person must act in it -- sign-in, set-up, a question
  hidden   a real window is required, and it is opened behind everything
           and kept from taking focus
  ours     never runs on an office's computer (a mapping / hub-side tool
           that ships only because its file does)
  owed     opens by itself, in view, today. KNOWN AND TO BE MOVED to
           `hidden`. Nothing new may be added under this word.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
FILES_LIST = Path(__file__).with_name("agent_files.txt")

PERSON, HIDDEN, OURS, OWED = "person", "hidden", "ours", "owed"
WHYS = (PERSON, HIDDEN, OURS, OWED)

# file -> (why, the sentence somebody reads before adding the next one)
ALLOWED: Dict[str, Tuple[str, str]] = {
    # --- a person has to act ------------------------------------------------
    "automations/icd_alerts/dialogs.py":
        (PERSON, "the question boxes every set-up step asks through"),
    "automations/icd_alerts/apex_signin.py":
        (PERSON, "the owner signs in to Apex once"),
    "automations/icd_alerts/box_signin.py":
        (PERSON, "the owner signs in to My Service Cloud (authenticator code)"),
    "automations/icd_alerts/ov_signin.py":
        (PERSON, "the owner signs in to OwnerVille by hand when the saved "
                 "sign-in stopped working"),
    "automations/icd_alerts/code_forward.py":
        (PERSON, "set-up: opens the owner's Gmail forwarding page"),
    "automations/icd_alerts/gmail_filters.py":
        (PERSON, "set-up: opens the owner's Gmail filter page"),
    "automations/icd_alerts/boot_schedule.py":
        (PERSON, "install: the Mac's own password box, to start after a restart"),
    "automations/icd_alerts/stay_awake.py":
        (PERSON, "install: the Mac's own password box, to never sleep"),
    "automations/icd_alerts/sara_read.py":
        (PERSON, "the SaraPlus read is hidden on every scheduled run; its "
                 "window (and red banner) exist only for a sign-in a person "
                 "started"),
    "automations/icd_alerts/run.py":
        (PERSON, "the sign-in commands a person runs from the set-up link"),
    # --- a real window, kept out of the way ---------------------------------
    "automations/icd_alerts/resume_push.py":
        (HIDDEN, "real Chrome for Indeed, opened in the background, minimized, "
                 "and stopped from taking focus (_FocusGuard)"),
    # --- never on an office's computer --------------------------------------
    "automations/icd_alerts/sterling_send.py":
        (OURS, "try_here is the mapping run on OUR computer; the office send "
               "and its sign-in test are hidden"),
    "automations/icd_alerts/optix_read.py":
        (OURS, "switched off at offices -- the Lucy Optix extension in the "
               "owner's own Chrome is the reader (2026-11-07)"),
    "automations/headshots/ov_upload.py":
        (OURS, "--headed is a flag for running it by hand on the hub; the "
               "office job drives an already-open hidden page"),
    "automations/oat_processing/resume_download.py":
        (HIDDEN, "osascript reads a FILE (no window, nothing on screen)"),
    "automations/oat_processing/run.py":
        (HIDDEN, "osascript reads a screenshot FILE (no window, nothing on screen)"),
    # --- opens by itself, in view. TO BE MOVED. -----------------------------
    "automations/icd_alerts/ov_read.py":
        (OWED, "when the OwnerVille session lapses, Lucy signs in again in a "
               "visible window (the security check never clears hidden)"),
    "automations/brand_audit/zoho_draft.py":
        (OWED, "LucyECO Social drives Zoho in a visible window (hidden trips "
               "Zoho's bot check). NOT RELEASED to any office yet (Megan, "
               "2026-11-13) -- it goes to the background BEFORE the first "
               "office is enrolled, not after"),
}


def shipped() -> List[str]:
    out = []
    for line in FILES_LIST.read_text().splitlines():
        line = line.strip()
        if line.endswith(".py") and not line.startswith("#") \
                and "/test_" not in line:
            out.append(line)
    return out


def _marks(src: str) -> Set[str]:
    """The ways this file can put something on a screen."""
    found: Set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"could not be read"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "headless" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is False:
                    found.add("headless=False")
                if kw.arg == "interactive" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is True:
                    found.add("interactive=True")
            try:
                name = ast.unparse(n.func)
            except Exception:  # noqa: BLE001
                name = ""
            if name.startswith("webbrowser.open"):
                found.add("webbrowser.open")
            if n.args and isinstance(n.args[0], ast.List) and n.args[0].elts \
                    and isinstance(n.args[0].elts[0], ast.Constant) \
                    and n.args[0].elts[0].value in ("open", "osascript"):
                found.add("runs " + str(n.args[0].elts[0].value))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            pos = a.args[len(a.args) - len(a.defaults):]
            for arg, d in list(zip(pos, a.defaults)) + \
                    [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults) if d]:
                if arg.arg == "headless" and isinstance(d, ast.Constant) \
                        and d.value is False:
                    found.add("headless defaults to False")
    # The red "do not log in" bar is only ever attached to a window in view.
    if re.search(r"browser_banner\.attach\(", src):
        found.add("visible-window banner")
    if re.search(r"headless\s*=\s*\(?\s*not\s", src):
        found.add("headless=not ...")
    return found


def scan() -> Dict[str, Set[str]]:
    """{shipped file: the ways it can open something in view} -- only files
    that have at least one."""
    out: Dict[str, Set[str]] = {}
    for rel in shipped():
        p = ROOT / rel
        if not p.is_file():
            continue
        marks = _marks(p.read_text())
        if marks:
            out[rel] = marks
    return out


def owed() -> List[str]:
    return sorted(f for f, (why, _) in ALLOWED.items() if why == OWED)


if __name__ == "__main__":
    for f, marks in sorted(scan().items()):
        why, note = ALLOWED.get(f, ("NOT LISTED", ""))
        print("%-8s %s  [%s]\n         %s" % (why, f, ", ".join(sorted(marks)), note))
