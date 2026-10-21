"""Which Slack token an ECO office's rooms are posted with.

Every office posts with the machine's default 'Lucy' token (AO workspace) --
except an office whose channel lives in ANOTHER workspace. Trang (FRESH
SUCCESS, 2026-10-21) is the first on Lucy ECO: her metrics and trackers already
post through the `alphalete_metrics` bot installed there, keyed by
office_metrics.offices.CROSS_WS_TOKEN_FILES (office key -> token file under
~/.config/recruiting-report/). This gives the ECO poster, the knocks board, the
call-outs and the approval check the same routing, per office, so an OPS post
in the same loop never picks up the wrong token.

The ECO office key and the metrics office key are the same word for every
office so far; ECO_KEY_ALIASES covers one that is not.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# ECO office key -> metrics office key, only where they differ.
ECO_KEY_ALIASES: dict = {}

LUCY_REPORTING = "U0BCG8F9B5Z"      # the AO workspace user every post is from

_ids: dict = {}


def _registry() -> dict:
    try:
        from automations.office_metrics import offices as om
        return dict(getattr(om, "CROSS_WS_TOKEN_FILES", {}) or {})
    except Exception:  # noqa: BLE001
        return {}


def token_file(office_key: str) -> Optional[Path]:
    """The token file this office posts with, or None = the default token."""
    key = (office_key or "").strip().lower()
    key = ECO_KEY_ALIASES.get(key, key)
    fname = _registry().get(key)
    return (Path.home() / ".config" / "recruiting-report" / fname) if fname else None


def token_for(office_key: str) -> Optional[str]:
    """The office's own token, None for the default, and a RuntimeError when
    the office is mapped to a file this machine does not have -- posting with
    the default would land in the wrong workspace, so that is never silent."""
    p = token_file(office_key)
    if p is None:
        return None
    if not p.exists():
        raise RuntimeError(
            "%s posts to another Slack workspace and needs its bot token at %s, "
            "which is not on this machine (lucy set_office_slack_token %s <xoxb-...>)"
            % (office_key, p, office_key))
    return p.read_text(encoding="utf-8-sig").strip()


def client_for(office_key: Optional[str]):
    """A posting client for this office's rooms. None/unknown = the default."""
    from automations.shared import slack_metrics_post as smp
    tok = token_for(office_key) if office_key else None
    return smp._client(token=tok) if tok else smp._client()


def lucy_id_for(office_key: Optional[str]) -> str:
    """The user id a room must contain for Lucy to post there: Lucy Reporting
    in AO, the office's bot in its own workspace (asked once per token)."""
    p = token_file(office_key) if office_key else None
    if p is None:
        return LUCY_REPORTING
    key = str(p)
    if key not in _ids:
        try:
            _ids[key] = (client_for(office_key).auth_test() or {}).get("user_id") or ""
        except Exception:  # noqa: BLE001
            _ids[key] = ""
    return _ids[key] or LUCY_REPORTING


def is_cross_workspace(office_key: Optional[str]) -> bool:
    return bool(office_key) and token_file(office_key) is not None


def post_kwargs(office_key: Optional[str]) -> dict:
    """{'office': key} only for a cross-workspace office, {} otherwise -- so
    every existing posting call (and every test that fakes it) keeps its old
    shape for the offices that never needed this."""
    return {"office": office_key} if is_cross_workspace(office_key) else {}
