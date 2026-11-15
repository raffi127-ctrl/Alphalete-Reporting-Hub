"""Hand a secret to ONE office computer through the shared jobs sheet without
the sheet ever holding it readable (Megan 2026-11-15: Facebook replies from
the office's own computer).

    office:  priv, pub = keypair()            # pub rides a job answer
    sender:  box = seal(secret, office_pub)    # box rides the next job
    office:  secret = unseal(box, priv)

Diffie-Hellman over the RFC 3526 2048-bit group (group 14, a safe prime),
SHA-256 to derive keys, a SHA-256 keystream to encrypt, HMAC-SHA256 to prove
nothing was changed. Standard library only: an office computer has nothing
else. The sheet sees two public numbers and scrambled bytes; only the office
computer that made `priv` can open the box, and `priv` never leaves it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Tuple

_P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A0879"
    "8E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B"
    "0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA4836"
    "1C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804"
    "F1746C08CA18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6"
    "955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)
_G = 2


def keypair() -> Tuple[str, str]:
    """(private, public) as hex strings. Keep private on this computer."""
    priv = secrets.randbits(256) | (1 << 255)
    return format(priv, "x"), format(pow(_G, priv, _P), "x")


def _check_pub(pub: int) -> int:
    if not (2 <= pub <= _P - 2):
        raise ValueError("bad public number")
    return pub


def _keys(shared: int, a_pub: int, b_pub: int) -> Tuple[bytes, bytes]:
    base = hashlib.sha256(shared.to_bytes(256, "big") + a_pub.to_bytes(256, "big")
                          + b_pub.to_bytes(256, "big")).digest()
    return (hmac.new(base, b"lucy-sealed-enc", hashlib.sha256).digest(),
            hmac.new(base, b"lucy-sealed-mac", hashlib.sha256).digest())


def _stream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 32):
        block = hashlib.sha256(key + nonce + (i // 32).to_bytes(8, "big")).digest()
        out += bytes(a ^ b for a, b in zip(data[i:i + 32], block))
    return bytes(out)


def seal(secret: str, office_pub_hex: str) -> str:
    """A box only the holder of the matching private number can open."""
    b_pub = _check_pub(int(office_pub_hex, 16))
    e_priv = secrets.randbits(256) | (1 << 255)
    e_pub = pow(_G, e_priv, _P)
    enc, mac = _keys(pow(b_pub, e_priv, _P), e_pub, b_pub)
    nonce = secrets.token_bytes(16)
    ct = _stream(enc, nonce, secret.encode("utf-8"))
    tag = hmac.new(mac, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(json.dumps({
        "e": format(e_pub, "x"), "n": nonce.hex(), "c": ct.hex(), "t": tag.hex()}).encode()).decode()


def unseal(box: str, priv_hex: str) -> str:
    d = json.loads(base64.b64decode(box))
    e_pub = _check_pub(int(d["e"], 16))
    priv = int(priv_hex, 16)
    b_pub = pow(_G, priv, _P)
    enc, mac = _keys(pow(e_pub, priv, _P), e_pub, b_pub)
    nonce, ct = bytes.fromhex(d["n"]), bytes.fromhex(d["c"])
    if not hmac.compare_digest(hmac.new(mac, nonce + ct, hashlib.sha256).digest(), bytes.fromhex(d["t"])):
        raise ValueError("box was changed or is not for this computer")
    return _stream(enc, nonce, ct).decode("utf-8")
