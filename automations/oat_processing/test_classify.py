"""Fast, browser-free checks on the OAT decision tree. Run:

    python -m automations.oat_processing.test_classify

Exercises each branch of classify() against the scenarios Carlos described.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

from .classify import Applicant, Action, classify

TODAY = dt.date(2026, 7, 26)


def _check(label, applicant, expected):
    got = classify(applicant, TODAY).action
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got.value}"
          f"{'' if ok else f'  (expected {expected.value})'}")
    return ok


def main() -> int:
    cases = [
        # 1. no phone -> parked
        ("no phone", Applicant(first_name="Donald", last_name="Sowells",
                               email="x@indeed", job_board="Indeed"),
         Action.FLAG_NO_PHONE),
        # 2. future interview -> remove
        ("future interview", Applicant(first_name="A", phone="555",
                                       has_interview=True,
                                       interview_date=dt.date(2026, 7, 27)),
         Action.REMOVE_FUTURE_INTERVIEW),
        # 3. sent to call list today -> remove duplicate
        ("sent today", Applicant(first_name="B", phone="555",
                                 sent_to_call_list_today=True),
         Action.REMOVE_DUPLICATE),
        # 4a. past interview > 1wk, not overridable -> re-text then remove
        ("past interview 28d", Applicant(first_name="C", phone="555",
                                         position="AT&T Wireless Associate",
                                         has_interview=True, override_offered=False,
                                         interview_date=dt.date(2026, 6, 28)),
         Action.RETEXT_THEN_REMOVE),
        # 4b. past interview <= 1wk -> remove without texting
        ("past interview 3d", Applicant(first_name="D", phone="555",
                                        has_interview=True, override_offered=False,
                                        interview_date=dt.date(2026, 7, 23)),
         Action.REMOVE_DUPLICATE),
        # 5. overridable dup, not sent today -> override + send
        ("override offered", Applicant(first_name="E", phone="555",
                                       override_offered=True),
         Action.OVERRIDE_SEND_AI),
        # 6. fresh -> send
        ("fresh applicant", Applicant(first_name="F", phone="555"),
         Action.SEND_AI),
    ]
    print("OAT classify() checks:")
    passed = sum(_check(*c) for c in cases)
    print(f"{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
