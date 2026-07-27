"""Fast, browser-free checks on the OAT decision tree. Run:

    python -m automations.oat_processing.test_classify

Exercises each branch of classify() against the states Carlos showed in the Loom.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

from .classify import Applicant, Action, classify

TODAY = dt.date(2026, 7, 27)


def _check(label, applicant, expected):
    got = classify(applicant, TODAY).action
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got.value}"
          f"{'' if ok else f'  (expected {expected.value})'}")
    return ok


def main() -> int:
    cases = [
        ("no phone", Applicant(first_name="Donald", last_name="Sowells",
                               email="x@indeed", job_board="Indeed"),
         Action.FLAG_NO_PHONE),
        ("future interview", Applicant(first_name="A", phone="555",
                                       interview_future=True),
         Action.REMOVE_FUTURE_INTERVIEW),
        ("sent to call list today", Applicant(first_name="B", phone="555",
                                              sent_to_call_list_today=True),
         Action.REMOVE_DUPLICATE),
        ("blocked, last contact 28d ago", Applicant(
            first_name="C", phone="555", position="AT&T Wireless Associate",
            correspondence_blocked=True, last_correspondence=dt.date(2026, 6, 28)),
         Action.RETEXT_THEN_REMOVE),
        ("blocked, last contact 3d ago", Applicant(
            first_name="D", phone="555", correspondence_blocked=True,
            last_correspondence=dt.date(2026, 7, 25)),
         Action.REMOVE_DUPLICATE),
        ("past no-show, undated", Applicant(
            first_name="E", phone="555", interview_past_noshow=True),
         Action.REMOVE_DUPLICATE),
        ("overwrite offered", Applicant(first_name="F", phone="555",
                                        override_button=True),
         Action.OVERRIDE_SEND_AI),
        ("fresh applicant", Applicant(first_name="G", phone="555"),
         Action.SEND_AI),
    ]
    print("OAT classify() checks:")
    passed = sum(_check(*c) for c in cases)
    print(f"{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
