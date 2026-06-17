"""Starter reply drafts for below-5★ reviews.

These are first-draft replies meant for human approval (the hybrid model:
negatives never auto-send). They personalize on the reviewer's first name and
star level and keep a warm, non-defensive, take-it-offline tone — the response
pattern that actually helps a rating recover. Phase 3 can swap this for an
LLM-written draft; the call site stays the same.
"""
from __future__ import annotations


def _first_name(author: str) -> str:
    author = (author or "").strip()
    return author.split()[0] if author else ""


def draft_reply(review: dict, company_name: str) -> str:
    stars = review.get("rating")
    name = _first_name(review.get("author", ""))
    hi = f"Hi {name}," if name else "Hi there,"

    if isinstance(stars, (int, float)) and stars <= 2:
        return (
            f"{hi} thank you for the honest feedback — we're sorry your "
            f"experience with {company_name} fell short, and that's on us to "
            f"make right. We'd like to understand what happened and fix it. "
            f"Please reach us directly so we can help."
        )
    # 3-4 stars: appreciative + invite specifics
    return (
        f"{hi} thank you for taking the time to review {company_name}. We're "
        f"glad you chose us and we're always working to earn that last star — "
        f"if there's something specific we could have done better, we'd genuinely "
        f"like to hear it."
    )
