"""RingCentral wrap-up auto-read — CLI entry for the Hub.

Marks unread SMS as read once a conversation has reached a known wrap-up
message, unless the customer replied after the wrap-up. Prints a plain
text log to stdout (the Hub captures it) and ends with the canonical
'=== done ===' success marker the dashboard scans for.

Usage:
  python -m automations.rc_autoread.run            # mark for real
  python -m automations.rc_autoread.run --dry-run  # show what it WOULD mark

Cross-platform: no file paths, no interactive prompts — stdout only.
"""
from __future__ import annotations

import argparse
import sys
import time

import requests

# --- RingCentral credentials (personal extension; committed as-is per owner) ---
CLIENT_ID = "7pKHk3Kr9uXefA76340gKo"
CLIENT_SECRET = "4VeICLfeiUceyIQeyndbUSYBLDDt1pxYpewlfCGLAj2w"
JWT_TOKEN = "eyJraWQiOiI4NzYyZjU5OGQwNTk0NGRiODZiZjVjYTk3ODA0NzYwOCIsInR5cCI6IkpXVCIsImFsZyI6IlJTMjU2In0.eyJhdWQiOiJodHRwczovL3BsYXRmb3JtLnJpbmdjZW50cmFsLmNvbS9yZXN0YXBpL29hdXRoL3Rva2VuIiwic3ViIjoiNjI2NzI0OTEwMTYiLCJpc3MiOiJodHRwczovL3BsYXRmb3JtLnJpbmdjZW50cmFsLmNvbSIsImV4cCI6MzkzMDI1MzA2NywiaWF0IjoxNzgyNzY5NDIwLCJqdGkiOiJLaXRCR1NyYVNwQzRFZ3pPUkFSdjFRIn0.eHw-Ws56nKIaITK8Ir9ciy1nXImrTOXqRwCRbB06lMiTpaJ1UyBM50lmAHl4jjKGPrENRz6p6InkB8Uz2r94-GZn-DAxMTr-pVEqXDaOj7lXExNJcw_Q5uJdfbFfrOI0MzSwuuEJJqJAXjNG9qeZw0hluXUqL0wlsNlE_JLGMRpSk0FxI4vun8qCCL7oCmuXZO9OzP9j0c3ikDnJ4T2vFQUC5YLx-CUZ01ITUbtq8lw9FUrY1JEK6ZooOVMlLQwjMJL08Ks2_wjl-Er0w7_NqZbkqbvkWHNc7bOlgj7fMV9b3wNJasdaWy78wdUtMnzSwCefgDl1o2_9WGY5Pb_1KA"
EXTENSION_ID = "62883924016"
MY_NUMBER = "+12148456450"
BASE_URL = "https://platform.ringcentral.com"

WRAP_UP_PHRASES = [
    # Universal / multi-template
    "AT&T D2D Tower Line",
    "Thanks for setting up service with me",
    "SaraPlus",
    "rewardcenter.att.com",
    "DO NOT CALL CORPORATE",
    # Self Install (older)
    "Please message in this group chat if you have any questions",
    "internet must be activated after 2:00PM",
    "bgw320-installation",
    # Self Install (newer)
    "Please first use this group chat if you have any questions or need assistance",
    "Your self-install kit is scheduled to arrive",
    # Tech Install
    "Please reach out here in this group chat",
    "Your installation date and time is in the screenshot",
    "tech will call/message 30 minutes prior to arrival",
    # Cell Phones (older)
    "Please reach out here in this group message",
    "rewardcenteroffers.com",
    "nextqr.com/tradein",
    "activate your phones after you receive them",
    # Cell Phones (newer)
    "Please use this group message if you have any questions or need assistance",
    "SOMEONE MUST BE HOME TO SIGN FOR THE DELIVERY",
    # DirecTV (older)
    "DirecTV Wrap Up",
    "registered your DirecTV",
    "begin streaming as soon as you desire",
    "Gemini when it arrives",
    "stream on your Samsung or Vizio",
    # DirecTV (newer)
    "Your DirecTV billing begins once you first start streaming",
    # Installation reminders
    "just a reminder that today is your fiber installation",
    "just a reminder that tomorrow is your fiber installation",
    "fiber installation",
    "today's installation",
    # Follow-up / check-in template ("Hello [name] this is Kim from AT&T ...
    # writing to follow up and make sure you have everything you need ...").
    # Rep-name-independent middle of the template so it matches every variant.
    # Same protection applies: if the customer replied after it, stays unread.
    "writing to follow up and make sure you have everything you need",
    # More rep follow-up / check-in templates (rep-outbound only — a customer
    # never types these). Each is ignorable unless the customer replies, which
    # the customer-reply-after skip already handles.
    "install coming up let me know if you need anything",
    "just wanted to check up on you and ask",
    "just reminding you about your install",
    "this is your personal rep",
    "how did the installation go",
    "how was the installation",
    "how did the setup go",
    "how did installation go",   # variant without "the"
    "how did the install go",    # "install" vs "installation"
    "just wanted to check in with you to see how everything went",
    # Rep "your install didn't complete, reschedule" notice — invariant core
    # catches both "schedule a new installation date" and "reschedule" variants.
    "installation was never completed just letting you know you can",
    # Rep sign-offs. Broader than the check-ins (they ride on the end of
    # substantive messages), so kept to distinctive phrasings a customer
    # wouldn't use.
    "reach out with any",
    "any questions or concerns please reach out",
    "feel free to reach out",
    # Rep install reminders + post-install check-ins (rep-outbound only — a
    # customer never types these; if the customer replied after, stays unread).
    "wanted to remind you that your install",
    "reminding you that your installation",
    "reminder today is installation day",
    "how was your installation",
    "went well with your install",
    "went smoothly with your installation",
    "just checking in to see if everything went well",
    # More rep check-ins / reminders / sign-offs (rep-outbound only).
    "reaching out to check on you and your internet installation",  # "AT&T CHECK UP" blast
    "how's the installation going",
    "this is your rep, just checking",
    "your equipment gets delivered today",
    "hope the install is going good",
    "do not hesitate to reach out to this group chat",
    # Spanish rep reminders
    "recordarte que la instalación es hoy",
    "la visita del técnico está programada",
]


def get_access_token(logfn=print):
    logfn("Connecting to RingCentral...")
    resp = requests.post(
        f"{BASE_URL}/restapi/oauth/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": JWT_TOKEN},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_all_unread_sms(token):
    headers = {"Authorization": f"Bearer {token}"}
    all_records = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/restapi/v1.0/account/~/extension/{EXTENSION_ID}/message-store",
            headers=headers,
            params={"messageType": "SMS", "readStatus": "Unread", "perPage": 100, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        all_records.extend(data.get("records", []))
        nav = data.get("navigation", {})
        if not nav.get("nextPage"):
            break
        page += 1
    return all_records


def get_all_conversation_messages(token, conversation_id):
    headers = {"Authorization": f"Bearer {token}"}
    all_records = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/restapi/v1.0/account/~/extension/{EXTENSION_ID}/message-store",
            headers=headers,
            params={"messageType": "SMS", "conversationId": conversation_id, "perPage": 100, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        all_records.extend(data.get("records", []))
        nav = data.get("navigation", {})
        if not nav.get("nextPage"):
            break
        page += 1
    return all_records


def mark_read(token, msg_id, logfn=print):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for attempt in range(5):
        resp = requests.put(
            f"{BASE_URL}/restapi/v1.0/account/~/extension/{EXTENSION_ID}/message-store/{msg_id}",
            headers=headers,
            json={"readStatus": "Read"},
            timeout=15,
        )
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 10))
            logfn(f"Rate limited, waiting {wait} seconds...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        time.sleep(0.3)
        return
    logfn(f"Failed to mark {msg_id} after retries, skipping.")


def run_autoread(dry_run: bool = False, logfn=print) -> dict:
    """Scan the extension and mark wrapped-up conversations read.
    Returns a summary dict. When dry_run, reports what it WOULD mark
    without changing anything."""
    logfn("Script starting..." + (" (DRY RUN — nothing will be marked)" if dry_run else ""))
    token = get_access_token(logfn)
    logfn("Authenticated!")
    messages = get_all_unread_sms(token)
    logfn(f"Total unread SMS found (all pages): {len(messages)}")

    phrases_lower = [p.lower() for p in WRAP_UP_PHRASES]
    matched_conversations = set()
    marked = 0
    skipped = 0

    for msg in messages:
        body = (msg.get("subject", "") or "").strip()
        body_lower = body.lower()
        has_attachments = len(msg.get("attachments", [])) > 0
        phrase_match = any(phrase in body_lower for phrase in phrases_lower)
        image_only = has_attachments and body == "" and msg.get("from", {}).get("phoneNumber") != MY_NUMBER

        if not phrase_match and not image_only:
            continue

        conv_id = msg.get("conversationId")
        rep_number = msg.get("from", {}).get("phoneNumber")
        wrapup_time = msg.get("creationTime", "")

        if conv_id and conv_id not in matched_conversations:
            all_msgs = get_all_conversation_messages(token, conv_id)

            # Anchor the wrap-up on the whole conversation, not just the single
            # unread message that triggered us. This catches trailing rep
            # artifacts — e.g. the order-screen photo a rep sends AFTER the
            # wrap-up text — that arrive once the wrap-up text was already marked
            # read on a previous run. That photo is then the only unread message
            # left, sits at the END of the thread, and would otherwise be
            # rejected by the image-position rule below and never cleared.
            phrase_msgs = [
                m for m in all_msgs
                if any(p in (m.get("subject", "") or "").lower() for p in phrases_lower)
            ]
            if phrase_msgs:
                # Earliest wrap-up phrase message is the true wrap-up point.
                anchor = min(phrase_msgs, key=lambda m: m.get("creationTime", ""))
                rep_number = anchor.get("from", {}).get("phoneNumber")
                wrapup_time = anchor.get("creationTime", "")
            elif image_only:
                # No wrap-up text anywhere in the thread — only accept an image
                # as the wrap-up if it LEADS the thread (an image-led wrap-up).
                all_msgs_sorted = sorted(all_msgs, key=lambda m: m.get("creationTime", ""))
                msg_position = next(
                    (i for i, m in enumerate(all_msgs_sorted) if m.get("id") == msg.get("id")), None
                )
                if msg_position is None or msg_position > 1:
                    continue
            else:
                continue

            matched_conversations.add(conv_id)

            # Any message after the wrap-up from a number OTHER than the rep who
            # sent the wrap-up (or our own line) means the customer engaged, so
            # keep the thread unread. The rep's own trailing order-screen photo
            # is sent from the wrap-up number, so it does NOT count as a reply —
            # and the anchor logic above still gets it marked. A photo (or text)
            # from a customer's number DOES keep the thread unread.
            customer_replied = any(
                m.get("from", {}).get("phoneNumber") not in (rep_number, MY_NUMBER)
                and m.get("creationTime", "") > wrapup_time
                for m in all_msgs
            )
            if customer_replied:
                logfn(f"Skipping conversation {conv_id} - customer replied after wrap-up")
                skipped += 1
            else:
                for m in all_msgs:
                    if m.get("readStatus") == "Unread":
                        if dry_run:
                            logfn(f"WOULD mark as read: {m['id']}")
                        else:
                            mark_read(token, m["id"], logfn)
                            logfn(f"Marked as read: {m['id']}")
                        marked += 1

    verb = "would be marked" if dry_run else "marked"
    logfn(f"Done. {marked} message(s) {verb} as read, "
          f"{skipped} conversation(s) skipped due to customer reply.")
    return {"marked": marked, "skipped": skipped, "unread_scanned": len(messages)}


def main() -> int:
    ap = argparse.ArgumentParser(description="RingCentral wrap-up auto-read")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what it would mark without changing anything")
    args = ap.parse_args()

    run_autoread(dry_run=args.dry_run)
    # Canonical Hub success marker (dashboard scans the whole log for this).
    print("=== done (dry-run) ===" if args.dry_run else "=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
