"""Documented analytical reference cases (see documentation/verification_report.md)."""
import pytest

from core.verification import run_reference_cases

CASES = run_reference_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_reference_case(case):
    assert case.passed, f"{case.id} {case.title}: expected {case.expected}, got {case.actual} (dev {case.deviation:.3e})"
