"""Get the bot's two Slack keys onto Lucy 3 through the `lucy` queue, locked.

Megan 2026-11-21: "you should be able to reach Lucy 3 always" -- and the queue
(a Google Sheet) does reach it from anywhere. But a key typed into a Sheet
cell is a key anyone with the Sheet can read. So:

  ON LUCY 3   --make-lock   makes a lock only Lucy 3 can open (its private
                            half never leaves ~/.config/recruiting-report/,
                            mode 600) and prints the public half -- 44
                            characters, safe to show anyone.
  LAPTOP      --send <public half>
                            seals both keys with that lock and queues
                            `--receive <sealed>` for Lucy 3. The Sheet only
                            ever holds the sealed text.
  ON LUCY 3   --receive <sealed>
                            opens it, writes the two key files (mode 600),
                            throws the lock away, restarts the bot. Prints
                            "keys in place" and never a key.

X25519 + HKDF-SHA256 + AES-GCM (the `cryptography` package; installed into
the venv on first use if missing).

    lucy rerun lucy_transcriber_keydrop --make-lock --machine "Lucy 3"
    python -m automations.lucy_transcriber.key_drop --send <public half>
"""
from __future__ import annotations  # Lucy runs Python 3.9

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from automations.lucy_transcriber import config as C

LOCK = C.CFG / "transcriber-lock.key"
INFO = b"lucy-pitch-auditor key drop v1"
REPO = Path(__file__).resolve().parents[2]


def _crypto():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "cryptography"],
                       check=True, capture_output=True)
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import (X25519PrivateKey,
                                                                  X25519PublicKey)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return hashes, serialization, X25519PrivateKey, X25519PublicKey, AESGCM, HKDF


def _raw(pub) -> bytes:
    _, serialization, *_ = _crypto()
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _key(shared: bytes) -> bytes:
    hashes, _, _, _, _, HKDF = _crypto()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(shared)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_lock() -> str:
    _, serialization, X25519PrivateKey, *_ = _crypto()
    priv = X25519PrivateKey.generate()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv.private_bytes(serialization.Encoding.Raw,
                                   serialization.PrivateFormat.Raw,
                                   serialization.NoEncryption()))
    return _b64(_raw(priv.public_key()))


def seal(public_half: str, payload: dict) -> str:
    _, _, X25519PrivateKey, X25519PublicKey, AESGCM, _ = _crypto()
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(_unb64(public_half)))
    nonce = os.urandom(12)
    ct = AESGCM(_key(shared)).encrypt(nonce, json.dumps(payload).encode(), INFO)
    return _b64(_raw(eph.public_key()) + nonce + ct)


def open_sealed(sealed: str) -> dict:
    _, _, X25519PrivateKey, X25519PublicKey, AESGCM, _ = _crypto()
    raw = _unb64(sealed)
    priv = X25519PrivateKey.from_private_bytes(LOCK.read_bytes())
    shared = priv.exchange(X25519PublicKey.from_public_bytes(raw[:32]))
    return json.loads(AESGCM(_key(shared)).decrypt(raw[32:44], raw[44:], INFO))


def _write(path: Path, tok: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")


def receive(sealed: str) -> int:
    if not LOCK.exists():
        print("no lock on this machine -- run --make-lock here first")
        return 1
    keys = open_sealed(sealed)
    if not (keys.get("bot", "").startswith("xoxb-") and keys.get("app", "").startswith("xapp-")):
        print("opened, but the keys inside look wrong -- nothing written")
        return 1
    _write(C.BOT_TOKEN_FILE, keys["bot"])
    _write(C.APP_TOKEN_FILE, keys["app"])
    LOCK.unlink()
    subprocess.run(["launchctl", "kickstart", "-k",
                    "gui/{}/com.alphalete.lucy-transcriber".format(os.getuid())],
                   capture_output=True)
    print("keys in place; lock thrown away; bot restarted")
    return 0


def send(public_half: str, machine: str = "Lucy 3") -> int:
    bot = C.token(C.BOT_TOKEN_FILE, "LUCY_TRANSCRIBER_BOT_TOKEN")
    app = C.token(C.APP_TOKEN_FILE, "LUCY_TRANSCRIBER_APP_TOKEN")
    if not (bot.startswith("xoxb-") and app.startswith("xapp-")):
        print("no keys saved on this laptop -- run set_tokens --dialog first")
        return 1
    sealed = seal(public_half, {"bot": bot, "app": app})
    r = subprocess.run(
        [sys.executable, "-m", "automations.day_orchestrator.mini_control", "--by", "Megan",
         "--machine", machine, "--enqueue", "rerun", "lucy_transcriber_keydrop",
         "--receive", sealed], cwd=str(REPO), capture_output=True, text=True)
    print((r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "queued")
    return r.returncode


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--make-lock", action="store_true")
    g.add_argument("--send", metavar="PUBLIC_HALF")
    g.add_argument("--receive", metavar="SEALED")
    a = ap.parse_args(argv)
    if a.make_lock:
        print("lock public half: " + make_lock())
        return 0
    if a.send:
        return send(a.send)
    return receive(a.receive)


if __name__ == "__main__":
    raise SystemExit(main())
