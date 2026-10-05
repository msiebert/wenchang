"""Tests for the generic systems-of-record principle.

Covers AIE-1055, US4.2.
"""

import pytest

from wenchang.prompts import systems_of_record

pytestmark = pytest.mark.unit


def test_principle_is_non_empty() -> None:
    """AIE-1055, US4.2: systems_of_record.PRINCIPLE is non-empty."""
    assert systems_of_record.PRINCIPLE.strip() != ""


@pytest.mark.parametrize(
    "word", ["canonical", "interpretation", "correction", "discrepancy", "copy"]
)
def test_principle_contains_word(word: str) -> None:
    """AIE-1055, US4.2: PRINCIPLE contains each required word."""
    assert word in systems_of_record.PRINCIPLE
