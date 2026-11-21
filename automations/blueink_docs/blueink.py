"""Thin client for the Blue Ink eSignature API v2.

Deliberately plain `requests` rather than the official blueink-client-python
SDK: Lucy 2 runs python 3.9 and every report here has to run on macOS AND
Windows, so one less pinned dependency is one less thing to break on a runner.

Docs: https://developer.blueink.com/api/  (base https://api.blueink.com/api/v2,
auth header `Authorization: Token <private key>`).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from automations.blueink_docs import config

TIMEOUT = 60

# Bundle status codes, per the API spec's enum.
BUNDLE_STATUS = {
    "ne": "new", "dr": "draft", "pr": "processing", "pe": "pending",
    "se": "sent", "st": "started", "de": "declined", "ca": "cancelled",
    "ex": "expired", "fa": "failed", "co": "complete",
}
# Packet (per-signer) status codes.
PACKET_STATUS = {
    "ne": "new", "re": "ready", "pe": "pending", "se": "sent",
    "st": "started", "co": "complete", "ca": "cancelled", "ex": "expired",
    "fa": "failed", "de": "declined", "ra": "reassigned",
}


class BlueInkError(RuntimeError):
    pass


@dataclass
class SentBundle:
    bundle_id: str
    status: str          # human-readable, e.g. "sent"
    label: str


def _headers() -> dict:
    return {"Authorization": f"Token {config.api_key()}",
            "Content-Type": "application/json"}


# A read timeout on one bundle used to kill a whole run: the new-starts button
# fetches ~20 packets in a row, and Blue Ink drops one often enough that the
# build failed three times running with nothing to show for it (2026-09-10).
# A timeout is not an answer, so ask again rather than treating it as one.
RETRIES = 3
RETRY_WAIT = 3          # seconds, doubled each time


def _request(method: str, path: str, **kw):
    url = f"{config.API_BASE}{path}"
    wait = RETRY_WAIT
    for attempt in range(RETRIES):
        try:
            resp = requests.request(method, url, headers=_headers(),
                                    timeout=TIMEOUT, **kw)
            break
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as err:
            if attempt == RETRIES - 1:
                raise BlueInkError(
                    f"{method} {path}: Blue Ink did not answer after "
                    f"{RETRIES} tries ({err.__class__.__name__}).") from None
            time.sleep(wait)
            wait *= 2
    if resp.status_code == 401:
        raise BlueInkError(
            "Blue Ink rejected the API key (401). Check blueink-creds.json "
            "holds the PRIVATE key from the alphaletemarketing@gmail.com "
            "account, not a public/publishable one.")
    if resp.status_code == 429:
        raise BlueInkError("Blue Ink rate limit hit (429) -- back off and rerun.")
    if not resp.ok:
        raise BlueInkError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def _results(payload):
    """The list endpoints return either a bare array or a paginated object."""
    if isinstance(payload, dict):
        return payload.get("results") or payload.get("data") or []
    return payload or []


def list_envelope_templates() -> list:
    """Every enabled envelope template on the account, newest first."""
    return _results(_request("GET", "/envelope-templates/",
                             params={"page": 1, "per_page": 50}))


def send_from_template(name: str, email: str, phone: str = "",
                       template_id_: Optional[str] = None,
                       label: Optional[str] = None,
                       is_test: bool = False) -> SentBundle:
    """Create -- and thereby SEND -- one bundle to one signer.

    Creating a bundle launches it immediately; there is no separate send step
    and no undo, which is why every caller is gated behind --send.
    """
    packet = {"key": config.SIGNER_KEY, "name": name, "email": email,
              "deliver_via": "email"}
    if phone:
        packet["phone"] = phone
    body = {
        "label": label or f"{config.BUNDLE_LABEL} - {name}",
        "email_subject": config.EMAIL_SUBJECT,
        "email_message": config.EMAIL_MESSAGE,
        "is_test": is_test,
        "packets": [packet],
        "envelope_template": {"template_id": template_id_ or config.template_id()},
    }
    data = _request("POST", "/bundles/create_from_envelope_template/", json=body) or {}
    raw = str(data.get("status", ""))
    return SentBundle(bundle_id=str(data.get("id", "")),
                      status=BUNDLE_STATUS.get(raw, raw or "unknown"),
                      label=str(data.get("label", "")))


# THE REMIND CALL LIVES ON THE PACKET, NOT THE BUNDLE (probed 2026-11-20).
#   OPTIONS /bundles/<id>/remind/            -> 404, no such route
#   OPTIONS /packets/<key>/remind/           -> 200, allow='PUT, OPTIONS'
# Confirmed meaningful by checking OPTIONS against routes that do exist
# (/bundles/ answers 200 with an Allow header), so the 404 is an absence and
# not an unsupported method.
#
# THIS IS WHY THE CHASES ARE SAFE. Our client could only ever CREATE a bundle,
# and creating one launches it -- so "they have not signed yet" would have
# meant sending a second contract packet, the exact thing the double-send
# guard exists to stop. A remind re-sends the invitation for the packet that
# is already out: same bundle, same link, nothing duplicated.
PACKET_REMIND = "/packets/%s/remind/"


def remind_packet(packet_key: str) -> None:
    """Re-send one signer's invitation. No new bundle, no second contract."""
    if not str(packet_key or "").strip():
        raise BlueInkError("remind_packet needs a packet key")
    _request("PUT", PACKET_REMIND % packet_key)


def packets_of(bundle_id: str) -> list:
    """The signer packets on a bundle, each with its own status and key.

    `?include=packets` is REFUSED -- the API answers 400 and names what it
    will take ("events, files, data") -- but the bundle detail carries the
    packets anyway, so ask for the bundle plainly.
    """
    data = _request("GET", f"/bundles/{bundle_id}/") or {}
    return list(data.get("packets") or [])


def unsigned_packets(bundle_id: str) -> list:
    """Only the packets still owed a signature.

    A reminder to somebody who has already signed is the one thing a chase
    must never do, so the filter is on what the packet SAYS it is rather than
    on the bundle's overall state: a bundle reads "started" the moment one of
    several signers is done.
    """
    done = ("complete", "cancelled", "expired", "failed", "declined")
    out = []
    for p in packets_of(bundle_id):
        said = PACKET_STATUS.get(str(p.get("status", "")), str(p.get("status", "")))
        if said not in done:
            out.append(p)
    return out


def bundle_status(bundle_id: str) -> str:
    """Human-readable status for one bundle ('sent', 'complete', ...)."""
    data = _request("GET", f"/bundles/{bundle_id}/") or {}
    raw = str(data.get("status", ""))
    return BUNDLE_STATUS.get(raw, raw or "unknown")
