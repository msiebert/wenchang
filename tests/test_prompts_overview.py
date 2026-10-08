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


def test_overview_body_is_three_to_six_sentences() -> None:
    """AIE-1055, US4.1; AIE-1165: overview.BODY is non-empty and has 3-6 sentences."""
    assert overview.BODY.strip() != ""
    assert 3 <= len(_sentences(overview.BODY)) <= 6


@pytest.mark.parametrize(
    "phrase",
    [
        "`get_memory_index()`",
        "scope",
        "area",
        "name",
        "split",
        "before you answer from memory or write to it",
        "narrower files",
    ],
)
def test_overview_body_contains_phrase(phrase: str) -> None:
    """AIE-1055, US4.1; AIE-1165: overview.BODY contains each required phrase."""
    assert phrase in re.sub(r"\s+", " ", overview.BODY)


@pytest.mark.parametrize("phrase", ["slug", "full address"])
def test_overview_body_omits_tool_mechanics(phrase: str) -> None:
    """AIE-1165: overview.BODY leaves the slug rule and addressing to get_memory_index."""
    assert overview.BODY.strip() != ""
    assert phrase not in re.sub(r"\s+", " ", overview.BODY)
