"""Are the Lucy Chrome extensions actually installed, and from the repo?

Megan, 2026-11-19: "the extensions aren't working on her machine" — which
blocked showing the ICD Onboarding Board end to end, because two of its steps
ARE the extensions (step 2 sends the background checks off ApplicantStream,
step 6 is the office's onboarding board instead of a spreadsheet).

Nothing was broken. Chrome's own records had the whole answer:

    /Users/megan/Desktop/lucy-office-admin-1.1.3   disabled, manifest unreadable
    /Users/megan/Desktop/apex-new-starts           disabled, manifest unreadable

Both had been loaded from COPIES on the Desktop rather than from the repo
folder the READMEs name, and the copies were later deleted — so Chrome kept
two dead cards and the buttons stopped appearing. The office-admin copy was
also stale (1.1.3 against 1.1.5 in the repo), which is the exact failure the
apex README warns about: a hand-copied folder does not get fixes by `git pull`.

That is invisible from the outside and the symptom is just "the button is
gone", so this reads it off disk instead of guessing:

    python -m automations.shared.extension_doctor
    python -m automations.shared.extension_doctor --all   # every profile, not
                                                          # just the ones with
                                                          # a Lucy extension

Read-only. It opens Chrome's profile files and prints; it never writes, and it
cannot install anything — Load unpacked is a file picker only a person can
drive. What it tells you is which profile to do that in, and which folder to
pick.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# The extensions that live in this repo, by their folder under extension/.
OURS = {
    "office-admin": "Lucy BG✔️ Send  (step 2 — background checks)",
    "apex-new-starts": "Lucy Onboarding  (step 6 — onboarding board / Apex)",
}

# Chrome keeps extension records in Preferences on Linux and in Secure
# Preferences on macOS and Windows. Which one is not worth guessing: read both.
PREF_FILES = ("Preferences", "Secure Preferences")

# Chrome writes disable_reasons as a list of these (older builds, one bitmask).
# Only the ones that explain a dead card are spelled out; the rest print raw.
REASONS = {
    1: "someone switched it off",
    2: "it asked for new permissions and is waiting to be allowed",
    4: "Chrome could not load the folder (moved, renamed or deleted)",
    8: "this Chrome cannot run it",
    256: "the install is corrupted",
    8192: "blocked by a Chrome policy",
}


def chrome_dirs() -> list[pathlib.Path]:
    """Every Chrome user-data directory this OS might have."""
    home = pathlib.Path.home()
    if sys.platform == "darwin":
        roots = [home / "Library/Application Support/Google/Chrome"]
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData/Local")
        roots = [pathlib.Path(local) / "Google/Chrome/User Data"]
    else:
        roots = [home / ".config/google-chrome"]
    return [r for r in roots if r.is_dir()]


def profile_label(root: pathlib.Path) -> dict[str, str]:
    """Profile folder -> the name and account Chrome shows in the picker."""
    out: dict[str, str] = {}
    try:
        cache = json.loads((root / "Local State").read_text(encoding="utf-8"))
    except Exception:
        return out
    info = cache.get("profile", {}).get("info_cache", {})
    for folder, meta in info.items():
        who = meta.get("user_name") or ""
        name = meta.get("name") or folder
        out[folder] = "%s (%s)" % (name, who) if who else name
    return out


def which_extension(path: str, name: str) -> str | None:
    """Is this record one of ours? Returns the extension/ folder name."""
    for folder in OURS:
        # The installed name is the surest signal when Chrome can still read
        # the manifest. When it cannot (a deleted folder) the name is gone and
        # the path is all that is left — Megan's dead cards looked only like
        # "apex-new-starts" and "lucy-office-admin-1.1.3".
        if folder in (path or "").replace("\\", "/").lower():
            return folder
        if folder == "office-admin" and "office-admin" in (path or "").lower():
            return folder
    label = (name or "").lower()
    if "bg" in label and "send" in label:
        return "office-admin"
    if "onboarding" in label or "new starts" in label:
        return "apex-new-starts"
    return None


def from_a_checkout(path: str, folder: str) -> bool:
    """True when the path lands in <some checkout>/extension/<folder>.

    Deliberately not "equals this checkout": the team clones to
    ~/recruiting-report, Megan's copy is ~/1st Claude Folder, and a worktree is
    a checkout too. Any of those gets fixes by `git pull`; a copy on the
    Desktop does not, which is the whole distinction that matters.

    Links are followed before judging, because the Desktop shortcuts Megan asked
    for on 2026-11-19 ARE Desktop paths — they just point back into the repo, so
    they stay current. A copy and a link look identical in Chrome's record; only
    where they land tells them apart.
    """
    raw = (path or "").replace("\\", "/")
    for candidate in (os.path.realpath(raw) if raw else "", raw):
        parts = pathlib.PurePath(candidate).parts
        if len(parts) >= 2 and parts[-2] == "extension" and parts[-1] == folder:
            return True
    return False


def read_manifest(path: str) -> dict:
    """The extension's own manifest, off disk. {} when the folder is really gone."""
    if not path:
        return {}
    try:
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def records(root: pathlib.Path, prof: pathlib.Path):
    """Every Lucy extension record in one profile."""
    found = []
    devmode = None
    for fname in PREF_FILES:
        f = prof / fname
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ext = data.get("extensions", {})
        dm = ext.get("ui", {}).get("developer_mode")
        if dm is not None:
            devmode = dm
        for eid, rec in (ext.get("settings") or {}).items():
            if not isinstance(rec, dict):
                continue
            manifest = rec.get("manifest") or {}
            path = rec.get("path") or ""
            # A packed install's path is relative to <profile>/Extensions.
            full = (path if os.path.isabs(path)
                    else str(prof / "Extensions" / path)) if path else ""
            disk = read_manifest(full)
            folder = which_extension(
                path, manifest.get("name") or disk.get("name", ""))
            if folder:
                found.append({
                    "id": eid,
                    "folder": folder,
                    "path": path,
                    # `path` is what Chrome recorded and what a person needs to
                    # see; `full` is that resolved to somewhere readable, which
                    # for a packed install is under <profile>/Extensions.
                    "full": full,
                    "version": manifest.get("version") or disk.get("version"),
                    # Chrome does NOT cache a manifest in prefs for a freshly
                    # loaded unpacked extension, so "did Chrome cache one" says
                    # nothing about health — it called Megan's good installs
                    # broken on 2026-11-19. Only the folder on disk knows.
                    "readable": bool(disk),
                    "unpacked": rec.get("location") == 4,
                    "reasons": rec.get("disable_reasons"),
                })
    return found, devmode


def reasons_text(raw) -> str:
    if not raw:
        return ""
    codes = raw if isinstance(raw, list) else [
        b for b in REASONS if isinstance(raw, int) and raw & b]
    return "; ".join(REASONS.get(c, "reason code %s" % c) for c in codes)


def main_checkout() -> pathlib.Path:
    """The checkout a person would Load unpacked from.

    Not simply this file's parents[2]: run from a git worktree (which is where
    an agent session usually lives) that is a throwaway folder, and telling
    Megan to point Chrome at it would break her extensions again the moment the
    worktree is cleaned up. `--git-common-dir` points at the real repo's .git
    whatever worktree we are in, so its parent is the lasting checkout.
    """
    here = pathlib.Path(__file__).resolve().parents[2]
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            root = pathlib.Path(out.stdout.strip()).parent
            if (root / "extension").is_dir():
                return root
    except Exception:
        pass
    return here


def in_use_profile(root: pathlib.Path, names: dict[str, str]):
    """The profile Chrome used last — the one the person is actually sitting in.

    Worth singling out: "Lucy BG Send is installed" was true of Raf's profile on
    this very Mac while Megan's own profile had nothing, and a summary that only
    says "installed somewhere" reads as a green light when it is not one.
    """
    try:
        cache = json.loads((root / "Local State").read_text(encoding="utf-8"))
    except Exception:
        return None
    folder = cache.get("profile", {}).get("last_used")
    if not folder:
        return None
    return folder, names.get(folder, folder)


def pick_this(folder: str) -> str:
    """What to tell a person to pick in Load unpacked.

    The repo folder is always the right answer, but Megan keeps shortcuts to it
    on her Desktop (2026-11-19) and that is what she will actually click, so name
    it when it is really a link to this checkout rather than a copy.
    """
    repo = main_checkout() / "extension" / folder
    desk = pathlib.Path.home() / "Desktop"
    if desk.is_dir():
        for entry in sorted(desk.iterdir()):
            try:
                if entry.is_symlink() and entry.resolve() == repo.resolve():
                    return "%s   (your Desktop shortcut to %s)" % (entry, repo)
            except OSError:
                continue
    return str(repo)


def repo_version(folder: str) -> str | None:
    here = main_checkout() / "extension" / folder
    try:
        return json.loads(
            (here / "manifest.json").read_text(encoding="utf-8")).get("version")
    except Exception:
        return None


# Chrome adds these to a packed extension's manifest when it installs it, and
# re-encodes the PNGs. Neither is drift -- comparing them raw reports every
# packed copy as different and the real signal gets lost in the noise.
CHROME_ADDS = {"key", "update_url"}
NOT_CODE = (".png", ".jpg", ".jpeg", ".webp", ".ico", ".md")


def _code_files(folder_path: pathlib.Path) -> list[pathlib.Path]:
    """The files that actually RUN, relative to the extension folder."""
    out = []
    for f in sorted(folder_path.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(folder_path)
        if rel.parts and rel.parts[0] == "_metadata":
            continue  # Chrome's own signing records; not ours.
        if f.name == "manifest.json" or not f.name.endswith(NOT_CODE):
            out.append(rel)
    return out


def drift_against_repo(installed: str, folder: str):
    """Which of the repo's files this installed copy does NOT match.

    THE POINT. A frozen copy at the same version number as the repo is the
    worst case, because every version check calls it current. On 2026-11-20
    Raf's packed office-admin said 1.1.5 and the repo said 1.1.5, while his
    content.js was missing the one-click-one-send guard added for the double
    send he himself hit on 11/11. A version string cannot see that. Bytes can.

    Returns (differing, missing) as sorted name lists, or None when either side
    cannot be read -- "unknown", which is not the same as "fine".
    """
    if not installed:
        # pathlib.Path("") is ".", the CWD, which is a real directory -- so
        # without this an install Chrome recorded no path for came back as
        # "every file missing" instead of "unknown".
        return None
    repo = main_checkout() / "extension" / folder
    try:
        here = pathlib.Path(installed)
        if not (repo.is_dir() and here.is_dir()):
            return None
    except OSError:
        return None
    differing, missing = [], []
    for rel in _code_files(repo):
        mine, theirs = repo / rel, here / rel
        if not theirs.is_file():
            missing.append(str(rel))
            continue
        try:
            if rel.name == "manifest.json":
                a = json.loads(mine.read_text(encoding="utf-8"))
                b = json.loads(theirs.read_text(encoding="utf-8"))
                b = {k: v for k, v in b.items() if k not in CHROME_ADDS}
                if a != b:
                    differing.append(str(rel))
            elif mine.read_bytes() != theirs.read_bytes():
                differing.append(str(rel))
        except (OSError, ValueError):
            return None
    return sorted(differing), sorted(missing)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Check the Lucy Chrome extensions on this computer.")
    ap.add_argument("--all", action="store_true",
                    help="show every Chrome profile, not only the ones with a "
                         "Lucy extension")
    args = ap.parse_args(argv)

    roots = chrome_dirs()
    if not roots:
        print("No Chrome found on this computer.")
        return 1

    problems = 0
    anywhere = 0
    # folder -> [(profile folder, label)] where it is installed AND working.
    ok_in: dict[str, list[tuple[str, str]]] = {f: [] for f in OURS}
    inuse = None

    for root in roots:
        names = profile_label(root)
        if inuse is None:
            inuse = in_use_profile(root, names)
        profiles = [p for p in root.iterdir() if p.is_dir()
                    and any((p / f).is_file() for f in PREF_FILES)]
        for prof in sorted(profiles):
            found, devmode = records(root, prof)
            if not found and not args.all:
                continue
            label = names.get(prof.name, prof.name)
            print("=" * 72)
            print("%s  —  %s" % (prof.name, label))
            print("   Developer mode: %s" % ("ON" if devmode else "OFF"))
            if not found:
                print("   No Lucy extension installed here.")
                continue
            for r in found:
                anywhere += 1
                print("   %s" % OURS[r["folder"]])
                print("      folder it was loaded from: %s" % (r["path"] or "?"))
                if r["version"]:
                    want = repo_version(r["folder"])
                    stale = want and want != r["version"]
                    print("      version: %s%s" % (
                        r["version"],
                        "   <-- repo has %s, this copy is behind" % want
                        if stale else ""))
                    if stale:
                        problems += 1
                why = reasons_text(r["reasons"])
                if not r["readable"]:
                    problems += 1
                    print("      BROKEN: Chrome cannot read this folder's "
                          "manifest — the folder is gone.")
                if why:
                    problems += 1
                    print("      TURNED OFF: %s" % why)
                # A copy is a copy whether Chrome unpacked it or packed it.
                # The packed case used to print a parenthetical and still count
                # as OK, so a run with nothing BUT a frozen copy exited 0 and
                # said "installed and on" -- see the note on drift_against_repo.
                own_copy = not from_a_checkout(r["path"], r["folder"])
                if own_copy and r["readable"]:
                    problems += 1
                    kind = ("this is a copy on disk, not the repo folder"
                            if r["unpacked"] else
                            "Chrome is running its own packed copy, not the "
                            "repo folder")
                    print("      FROZEN COPY: %s, so `git pull` will never "
                          "reach it." % kind)
                    moved = drift_against_repo(r["full"], r["folder"])
                    if moved is None:
                        print("      Could not compare it against the repo "
                              "folder, so assume it is behind.")
                    else:
                        differing, gone = moved
                        behind = differing + gone
                        if behind:
                            print("      It is ALREADY running different code "
                                  "— %d file(s) do not match the repo:" % len(behind))
                            for name in behind[:8]:
                                print("        %s%s" % (
                                    name, "  (missing entirely)"
                                    if name in gone else ""))
                            if len(behind) > 8:
                                print("        ... and %d more"
                                      % (len(behind) - 8))
                        else:
                            print("      Its files match the repo today, but "
                                  "the next fix will not reach it.")
                    print("      Fix: remove this card, then Load unpacked "
                          "and pick:")
                    print("      %s" % pick_this(r["folder"]))
                if r["readable"] and not why and not own_copy:
                    print("      OK — installed and on, from the repo folder.")
                    ok_in[r["folder"]].append((prof.name, label))

    print("=" * 72)
    here = inuse[1] if inuse else "the profile you use"
    print("The Chrome profile you are using: %s" % here)
    print()

    missing = 0
    for folder, title in OURS.items():
        where = ok_in[folder]
        mine = inuse and any(p == inuse[0] for p, _ in where)
        if mine:
            print("  WORKING   %s" % title)
            continue
        missing += 1
        if where:
            # The trap this whole script exists for: green in some other
            # profile on the same Mac, nothing in the one you are looking at.
            print("  MISSING   %s" % title)
            print("            (it works in %s — a different profile, "
                  "not yours)" % ", ".join(lbl for _, lbl in where))
        else:
            print("  MISSING   %s" % title)
        print("            Load unpacked in %s, and pick:" % here)
        print("            %s" % pick_this(folder))

    print()
    if missing:
        print("Chrome → chrome://extensions → Developer mode on "
              "→ Load unpacked → pick the folder above.")
        if problems:
            print("Also %d broken/stale install(s) listed above — "
                  "remove those cards first." % problems)
        return 1
    if problems:
        print("%d thing(s) to fix above." % problems)
        return 1
    print("Both extensions are installed and on in the profile you use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
