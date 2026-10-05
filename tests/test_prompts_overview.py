"""Tests for the overview section prose.

Covers AIE-1055, US4.1.
"""

import re

import pytest

from wenchang.prompts import overview

pytestmark = pytest.mark.unit


def _sentences(text: str) -> list[str]:
    collapsed = re.sub(r"\s+", " ", text)
    return [s for s in re.split(r"(?<=[.!?])\s+", collapsed.strip()) if s]


def test_overview_body_is_four_to_six_sentences() -> None:
    """AIE-1055, US4.1: overview.BODY is non-empty and has 4-6 sentences."""
    assert overview.BODY.strip() != ""
    assert 4 <= len(_sentences(overview.BODY)) <= 6


@pytest.mark.parametrize(
    "phrase",
    ["`get_memory_index()`", "scope", "area", "name", "lowercase ASCII slug", "split"],
)
def test_overview_body_contains_phrase(phrase: str) -> None:
    """AIE-1055, US4.1: overview.BODY contains each required phrase."""
    assert phrase in re.sub(r"\s+", " ", overview.BODY)
