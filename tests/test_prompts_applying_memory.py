"""Tests for the applying memory section prose.

Covers AIE-1052, US2.1-US2.7.
"""

import re

import pytest

from wenchang.prompts import applying_memory

pytestmark = pytest.mark.unit

EXAMPLE_MARKERS = ("for example", "for instance", "e.g.")


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_heading_and_body() -> None:
    """AIE-1052, US2.1: HEADING is "Applying memory" and BODY is non-empty."""
    assert applying_memory.HEADING == "Applying memory"
    assert applying_memory.BODY.strip() != ""


@pytest.mark.parametrize(
    "phrase",
    [
        # US2.2
        "changes the substance",
        "what you conclude",
        "what you recommend",
        "what you ask",
        # US2.3
        "just as good without it",
        "leave it out",
        # US2.4
        "surveillance rather than attentiveness",
        # US2.5
        "level it was recorded",
        # US2.6
        "single passing mention",
        "trait",
        # US2.7
        "only if it changes what you suggest",
    ],
)
def test_body_contains_phrase(phrase: str) -> None:
    """AIE-1052, US2.2-US2.7: applying_memory.BODY contains each required phrase."""
    assert phrase in _normalized(applying_memory.BODY)


def test_at_most_one_example() -> None:
    """AIE-1052, US2.7: BODY contains at most one example marker."""
    lower = _normalized(applying_memory.BODY).lower()
    assert sum(lower.count(m) for m in EXAMPLE_MARKERS) <= 1
