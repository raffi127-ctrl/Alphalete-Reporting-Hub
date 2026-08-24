"""Thin client for the Blue Ink eSignature API v2.

Deliberately plain `requests` rather than the official blueink-client-python
SDK: Lucy 2 runs python 3.9 and every report here has to run on macOS AND
Windows, so one less pinned dependency is one less thing to break on a runner.

Docs: https://developer.blueink.com/api/  (base https://api.blueink.com/api/v2,
auth header `Authorization: Token <private key>`).
"""
from __future__ import annotations

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


def _request(method: str, path: str, **kw):
    url = f"{config.API_BASE}{path}"
    resp = requests.request(method, url, headers=_headers(), timeout=TIMEOUT, **kw)
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


def bundle_status(bundle_id: str) -> str:
    """Human-readable status for one bundle ('sent', 'complete', ...)."""
    data = _request("GET", f"/bundles/{bundle_id}/") or {}
    raw = str(data.get("status", ""))
    return BUNDLE_STATUS.get(raw, raw or "unknown")
