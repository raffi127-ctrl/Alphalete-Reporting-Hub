"""Where the NDS Sales Board fill keeps its OWN SaraPlus login and browser.

ITS OWN FILE, ITS OWN KEY, ITS OWN PROFILE -- never another report's:

  * NOT saraplus-creds.json        (alphaletemarketing -- the Alphalete Sales
                                    Board sweep, alphalete_sales_board.config)
  * NOT saraplus-creds-b2b.json    (Carlos's B2B dealer -- rc_contact_sync)
  * NOT saraplus-creds-nds.json    (the alphaletegp dealer's ORDER HISTORY pull
                                    -- nds_metrics; a different reader, and as
                                    of 2026-10-23 its own notes say the crew's
                                    current orders may still land elsewhere)

One file per account AND per reader, so a rotation on one can never hand
another report the wrong dealer -- and so the fill reads exactly the login
Carlos typed for it. The board is filled under Megan's SaraPlus-is-the-truth
rule (a matched rep is SET, up or down), which is why reading the wrong
dealer is not a harmless empty day: it would blank real sales.

  python -m automations.vantura_nds_sara.set_credentials --push "Lucy 2"

writes CREDS_PATH here (mode 600, password never echoed) and hands it to
Lucy 2 through mini_control's redacted transit (push_cred_file /
set_cred_file, key CRED_KEY -- whitelisted in mini_control._CRED_FILES).
Lucy 2 accepts that key only once it runs this code.

Everything is evaluated at call time (not import time) on purpose: tests
point HOME at a scratch directory, and mini_control's whitelist resolves its
paths the same way.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

# mini_control._CRED_FILES key (push_cred_file / set_cred_file). The file is
# CRED_KEY + ".json" under ~/.config/recruiting-report, same as every other
# per-account SaraPlus login in that whitelist.
CRED_KEY = "saraplus-nds-creds"
PROFILE_NAME = "saraplus-nds-profile"
# Environment override, for a one-off run on a box without the file.
ENV_EMAIL = "SARAPLUS_NDS_EMAIL"
ENV_PASSWORD = "SARAPLUS_NDS_PASSWORD"
SET_CREDENTIALS_CMD = ('python -m automations.vantura_nds_sara.set_credentials '
                       '--push "Lucy 2"')


def config_dir() -> Path:
    return Path.home() / ".config" / "recruiting-report"


# VERIFIED FALLBACK (2026-10-23): the NDS dealer login nds_metrics already keeps
# on Lucy 2 (alphaletegp). Probed the same day: the B2B dealer login shows NO
# reps selling on 10/22, the alphaletegp login accepts the password and is the
# account the crew sells under since 10/19. Used only when CRED_KEY's own file
# is absent, so a login Carlos types for this fill still wins.
FALLBACK_CRED_FILE = "saraplus-creds-nds.json"
# nds_metrics' Chrome profile for that login -- SaraPlus trusted that browser
# on 2026-10-22 (emailed passcode answered once). A fresh profile would be
# asked for a code again, so ours is SEEDED from it the first time.
def seed_profile_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "automations" / "uploaded" / ".saraplus_nds_profile"


def creds_path() -> Path:
    own = config_dir() / (CRED_KEY + ".json")
    if own.exists():
        return own
    fb = config_dir() / FALLBACK_CRED_FILE
    return fb if fb.exists() else own


def profile_dir() -> Path:
    """The persistent Chrome profile the direct read signs in with. Persistent
    so SaraPlus's "trust this browser" passcode is a once-per-machine event,
    not a once-per-run one (shared.saraplus.open_context). Under ~/.config,
    outside the repo: a code update never deletes it, and chrome_guard only
    ever signals the real Google Chrome binary, never patchright's bundled
    Chromium, so it is not at risk there either."""
    return config_dir() / PROFILE_NAME


def ensure_profile_seeded(log=print) -> Path:
    """Our profile dir, copied from nds_metrics' trusted one on first use so
    SaraPlus does not demand the emailed passcode for a never-seen browser."""
    import shutil
    ours = profile_dir()
    seed = seed_profile_dir()
    if not (ours / "Default").exists() and (seed / "Default").exists():
        try:
            if ours.exists():
                shutil.rmtree(ours)
            shutil.copytree(seed, ours, ignore=shutil.ignore_patterns("Singleton*", "*.lock", "lockfile"))
            log("profile seeded from %s (trusted browser)" % seed)
        except Exception as ex:  # noqa: BLE001 -- fall back to a fresh profile
            log("profile seed skipped (%s)" % type(ex).__name__)
    return ours


def creds_status(path: Optional[Path] = None,
                 env: Optional[Mapping[str, str]] = None
                 ) -> Tuple[Optional[Dict[str, str]], str, bool]:
    """({'email', 'password'} or None, one line saying where it came from or
    what is missing, whether the file exists).

    The line NEVER carries the password -- it is printed by --preflight and
    --probe and lands in logs. The environment pair wins over the file, like
    alphalete_sales_board.config.creds; a file that exists but cannot be read
    is reported as such (exists=True) so the caller can fail loudly instead
    of holding forever on a typo.
    """
    path = path or creds_path()
    env = os.environ if env is None else env
    e, p = (env.get(ENV_EMAIL) or "").strip(), env.get(ENV_PASSWORD) or ""
    if e and p:
        return ({"email": e, "password": p},
                "login from the environment (%s / %s) for %s" % (ENV_EMAIL, ENV_PASSWORD, e),
                path.exists())
    if not path.exists():
        return (None,
                "no creds file at %s (and no %s / %s in the environment) -- "
                "on the laptop: %s" % (path, ENV_EMAIL, ENV_PASSWORD, SET_CREDENTIALS_CMD),
                False)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:  # noqa: BLE001 -- any unreadable file is the same answer
        return (None,
                "%s is not readable JSON (%s) -- rewrite it: %s"
                % (path, type(ex).__name__, SET_CREDENTIALS_CMD),
                True)
    if not isinstance(data, dict):
        return None, "%s is not a JSON object -- rewrite it: %s" % (path, SET_CREDENTIALS_CMD), True
    missing = [k for k in ("email", "password") if not str(data.get(k) or "").strip()]
    if missing:
        return (None,
                "%s is missing %s -- rewrite it: %s" % (path, ", ".join(missing), SET_CREDENTIALS_CMD),
                True)
    email = str(data["email"]).strip()
    return ({"email": email, "password": str(data["password"])},
            "creds file %s for %s" % (path, email),
            True)


def creds() -> Dict[str, str]:
    """{'email', 'password'}, or a RuntimeError that names the fix."""
    cr, why, _exists = creds_status()
    if cr is None:
        raise RuntimeError("no NDS SaraPlus login: " + why)
    return cr
