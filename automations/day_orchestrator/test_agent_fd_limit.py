"""Every installed LaunchAgent gets a real file-descriptor ceiling.

A launchd job inherits macOS's default soft limit of 256 open files. None of the
committed plists set one, and on 2026-09-18 that showed up on Lucy 2 as
`OSError: [Errno 24] Too many open files` — three times, on an otherwise healthy
box, once for another person's command — while the session holder's Chrome sat at
211 descriptors of its 256.

install_agent injects the ceiling as it writes the plist, so a new agent cannot
be added without one. Pinned here: it is injected, it is idempotent, it does not
disturb the rest of the plist, and a plist that declares its OWN limit is left
alone.
"""
import pathlib
import plistlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automations.day_orchestrator import install_agent as ia  # noqa: E402

_failed = 0


def check(label, got, want):
    global _failed
    if got == want:
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


BASE = {
    "Label": "com.alphalete.example",
    "ProgramArguments": ["/bin/bash", "/repo/deploy/example.sh"],
    "StartCalendarInterval": {"Hour": 4, "Minute": 0},
    "StandardOutPath": "/repo/output/logs/example.out.log",
}


def _xml(d):
    return plistlib.dumps(d).decode()


print("a plist with no limit gets one:")
out = plistlib.loads(ia._with_fd_limit(_xml(BASE), "com.alphalete.example").encode())
check("NumberOfFiles set", out["SoftResourceLimits"]["NumberOfFiles"], ia.FD_SOFT_LIMIT)
check("comfortably above the macOS default of 256",
      ia.FD_SOFT_LIMIT > 256, True)
# kern.maxfilesperproc is 10240 on this hardware — a ceiling ABOVE it would be
# rejected by launchd, which would break every agent rather than fix one.
check("and below a Mac's per-process maximum", ia.FD_SOFT_LIMIT <= 10240, True)

print("the rest of the plist is untouched:")
for k in ("Label", "ProgramArguments", "StartCalendarInterval", "StandardOutPath"):
    check("%s preserved" % k, out[k], BASE[k])

print("idempotent — installing twice does not change it:")
again = plistlib.loads(
    ia._with_fd_limit(_xml(out), "com.alphalete.example").encode())
check("still the same", again["SoftResourceLimits"]["NumberOfFiles"], ia.FD_SOFT_LIMIT)

print("a job that asked for its own ceiling keeps it:")
own = dict(BASE, SoftResourceLimits={"NumberOfFiles": 512})
kept = plistlib.loads(ia._with_fd_limit(_xml(own), "x").encode())
check("own limit respected", kept["SoftResourceLimits"]["NumberOfFiles"], 512)

print("other SoftResourceLimits keys survive:")
mixed = dict(BASE, SoftResourceLimits={"NumberOfProcesses": 64})
got = plistlib.loads(ia._with_fd_limit(_xml(mixed), "x").encode())
check("NumberOfProcesses kept", got["SoftResourceLimits"]["NumberOfProcesses"], 64)
check("NumberOfFiles added", got["SoftResourceLimits"]["NumberOfFiles"], ia.FD_SOFT_LIMIT)

print("an unparseable plist is returned untouched, for plutil to report:")
check("garbage passes through", ia._with_fd_limit("not a plist", "x"), "not a plist")

print("FAILED" if _failed else "ALL PASSED")
raise SystemExit(1 if _failed else 0)
