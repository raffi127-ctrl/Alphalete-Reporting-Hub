"""Google Business Profile API — read the FULL review list and POST replies.

This is the seam that turns the drafted-reply workflow (review_replies.py) from
"draft + approve in Slack" into "actually publish the reply on Google". Two
things live only here:

  * list_reviews(location)  -> every review for a location (paginated; the
    Places API only returns a 5-review sample, this returns all of them).
  * reply_to_review(review_name, comment) -> publishes/updates the public
    business reply (accounts.locations.reviews.updateReply).

Reviews + replies are on the legacy Google My Business API v4
(mybusiness.googleapis.com/v4). Account + location discovery is on the newer
split APIs (mybusinessaccountmanagement / mybusinessbusinessinformation). All
three are behind the SAME OAuth scope (business.manage) and the SAME access
allowlist you request once from Google.

────────────────────────────────────────────────────────────────────────────
ONE-TIME SETUP (only Megan / the account owner can do these — see gbp_setup()):
  1. In Google Cloud, enable: "Google My Business API",
     "My Business Account Management API", "My Business Business Information API".
  2. Request review-API access via Google's Business Profile API access form
     (manual approval, can take days–weeks). Until granted, list_reviews /
     reply_to_review return HTTP 403.
  3. Authorize this token AS the Google account that manages the Alphalete
     listing:   python -m automations.brand_audit.gbp_api --authorize
────────────────────────────────────────────────────────────────────────────

Everything here is INERT until (a) a token exists AND (b) the caller opts out
of dry-run. No import side effects, no network at import time.
"""
from __future__ import annotations

import json
from pathlib import Path

# Same scope Google uses for all Business Profile management (reviews included).
GBP_SCOPES = ["https://www.googleapis.com/auth/business.manage"]

# Reuse the existing OAuth *client* (the Desktop app credential) — only the
# scope + signed-in account differ from the Gmail/Sheets tokens.
_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"

# Token lives with the other brand-audit state (gitignored, per-machine).
_BA_CONFIG = Path.home() / ".config" / "brand-audit"
GBP_TOKEN_PATH = _BA_CONFIG / "gbp-token.json"

# API bases.
_MYBUSINESS_V4 = "https://mybusiness.googleapis.com/v4"
_ACCOUNTS_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
_INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"

_TIMEOUT = 30


# ── auth ────────────────────────────────────────────────────────────────────
def authorize() -> None:
    """One-time interactive OAuth. Opens a browser — sign in as the Google
    account that MANAGES the Alphalete Google Business Profile and approve."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            f"OAuth client not found at {OAUTH_CLIENT_PATH}. Ask Megan for "
            "oauth-client.json (same file the Gmail/Sheets tokens use).")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), GBP_SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Google Business Profile.\n"
            "➡  Sign in as the account that MANAGES the Alphalete listing\n"
            "   (the one you use on business.google.com) and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{url}"),
        success_message="Done — close this tab and return to the terminal.",
    )
    granted = set(creds.scopes or [])
    if not granted.issuperset(GBP_SCOPES):
        raise RuntimeError(
            f"Authorization came back without business.manage (got "
            f"{granted or 'none'}). Re-run and approve the Business "
            "Profile permission.")
    GBP_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GBP_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✓ Saved Business Profile token to {GBP_TOKEN_PATH}")
    print("  Scopes:", ", ".join(sorted(granted)))


def has_token() -> bool:
    return GBP_TOKEN_PATH.exists()


def _session():
    """An authed requests session, refreshing the token if needed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request, AuthorizedSession

    if not GBP_TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Business Profile token at {GBP_TOKEN_PATH}. Run the one-time "
            "authorization:  python -m automations.brand_audit.gbp_api --authorize")
    creds = Credentials.from_authorized_user_file(str(GBP_TOKEN_PATH), GBP_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GBP_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Business Profile token is invalid and can't be refreshed. "
                "Re-run:  python -m automations.brand_audit.gbp_api --authorize")
    # Attribute calls to the project that holds the API allowlist, even though
    # the OAuth client lives in a different (shared) project.
    try:
        from automations.brand_audit.config import GBP_QUOTA_PROJECT
        if GBP_QUOTA_PROJECT:
            creds = creds.with_quota_project(str(GBP_QUOTA_PROJECT))
    except Exception:
        pass
    return AuthorizedSession(creds)


class GBPAccessError(RuntimeError):
    """Raised when the API responds 403 — almost always the review-API
    allowlist hasn't been granted yet. Callers treat this as 'not ready'."""


def _get(sess, url: str, params: dict | None = None) -> dict:
    r = sess.get(url, params=params or {}, timeout=_TIMEOUT)
    if r.status_code == 403:
        raise GBPAccessError(
            f"403 from {url} — Business Profile review API access not granted "
            "yet (or this account can't manage the listing). See gbp_setup().")
    r.raise_for_status()
    return r.json() or {}


# ── discovery ────────────────────────────────────────────────────────────────
def list_accounts(sess=None) -> list[dict]:
    """Business Profile accounts this token can manage. Each has a
    name like 'accounts/123456789'."""
    sess = sess or _session()
    out, token = [], None
    while True:
        params = {"pageSize": 20}
        if token:
            params["pageToken"] = token
        data = _get(sess, f"{_ACCOUNTS_API}/accounts", params)
        out.extend(data.get("accounts") or [])
        token = data.get("nextPageToken")
        if not token:
            return out


def list_locations(account_name: str, sess=None) -> list[dict]:
    """Locations under an account. name like 'locations/987654321';
    the v4 reviews path needs '<account_name>/<location_name>'."""
    sess = sess or _session()
    out, token = [], None
    read_mask = "name,title,storefrontAddress,metadata"
    while True:
        params = {"pageSize": 100, "readMask": read_mask}
        if token:
            params["pageToken"] = token
        data = _get(sess, f"{_INFO_API}/{account_name}/locations", params)
        out.extend(data.get("locations") or [])
        token = data.get("nextPageToken")
        if not token:
            return out


# ── reviews ──────────────────────────────────────────────────────────────────
# Google returns star ratings as words on v4; map to ints for our star logic.
_STAR_WORD = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def _normalize_review(rv: dict) -> dict:
    """v4 review -> the shape review_replies.py already speaks
    (rating/text/author/when/publish_time/name/has_reply)."""
    star = _STAR_WORD.get(rv.get("starRating", ""), None)
    reviewer = rv.get("reviewer") or {}
    reply = rv.get("reviewReply") or {}
    return {
        "name": rv.get("name", ""),            # accounts/.../reviews/{id} — reply target
        "review_id": rv.get("reviewId", ""),
        "rating": star,
        "text": (rv.get("comment") or ""),
        "author": reviewer.get("displayName", ""),
        "publish_time": rv.get("createTime", ""),
        "update_time": rv.get("updateTime", ""),
        "when": "",                            # v4 has no relative string; leave blank
        "has_reply": bool(reply.get("comment")),
        "existing_reply": reply.get("comment", ""),
    }


def list_reviews(location_path: str, sess=None, *, limit: int | None = None) -> list[dict]:
    """Every review for a location, newest first. `location_path` is the full v4
    resource: 'accounts/{acct}/locations/{loc}'. Paginates fully (unlike the
    Places API 5-review cap). Returns the normalized shape."""
    sess = sess or _session()
    out, token = [], None
    while True:
        params = {"pageSize": 50, "orderBy": "updateTime desc"}
        if token:
            params["pageToken"] = token
        data = _get(sess, f"{_MYBUSINESS_V4}/{location_path}/reviews", params)
        for rv in data.get("reviews") or []:
            out.append(_normalize_review(rv))
            if limit and len(out) >= limit:
                return out
        token = data.get("nextPageToken")
        if not token:
            return out


def reply_to_review(review_name: str, comment: str, sess=None) -> dict:
    """Publish (or update) the public business reply to a review.

    `review_name` is the full v4 resource from list_reviews()[i]['name']:
      accounts/{acct}/locations/{loc}/reviews/{reviewId}
    PUT updateReply is idempotent — re-replying overwrites the prior reply."""
    if not review_name:
        raise ValueError("reply_to_review needs the full review resource name")
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("refusing to post an empty reply")
    sess = sess or _session()
    r = sess.put(
        f"{_MYBUSINESS_V4}/{review_name}/reply",
        json={"comment": comment},
        timeout=_TIMEOUT,
    )
    if r.status_code == 403:
        raise GBPAccessError(
            "403 posting reply — review API access not granted yet.")
    r.raise_for_status()
    return r.json() or {}


def gbp_setup() -> str:
    """Human-readable setup checklist (also printed by --setup)."""
    return (
        "Google Business Profile API — one-time setup\n"
        "──────────────────────────────────────────────\n"
        "1. Google Cloud Console → APIs & Services → Enable:\n"
        "     • Google My Business API\n"
        "     • My Business Account Management API\n"
        "     • My Business Business Information API\n"
        "2. Request review-API access (manual Google approval, days–weeks):\n"
        "     https://developers.google.com/my-business/content/prereqs\n"
        "     → 'Request access' / Business Profile API access form.\n"
        "3. Authorize the token AS the account that manages the listing:\n"
        "     python -m automations.brand_audit.gbp_api --authorize\n"
        "4. Confirm it worked:\n"
        "     python -m automations.brand_audit.gbp_api --locations\n"
        "Until step 2 is granted, calls return HTTP 403 (GBPAccessError) and\n"
        "the workflow stays in draft-only mode automatically.")


def main(argv=None) -> int:
    import argparse
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.gbp_api")
    p.add_argument("--authorize", action="store_true",
                   help="run the one-time interactive OAuth")
    p.add_argument("--setup", action="store_true", help="print the setup checklist")
    p.add_argument("--locations", action="store_true",
                   help="list manageable accounts + locations (verifies access)")
    args = p.parse_args(argv)

    if args.setup:
        print(gbp_setup())
        return 0
    if args.authorize:
        authorize()
        return 0
    if args.locations:
        sess = _session()
        for acct in list_accounts(sess):
            print(f"\n{acct.get('name')}  {acct.get('accountName','')}")
            for loc in list_locations(acct["name"], sess):
                # v4 reviews path = '<account>/<location>'
                full = f"{acct['name']}/{loc['name']}"
                print(f"   {full}  —  {loc.get('title','')}")
        return 0
    print(gbp_setup())
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
