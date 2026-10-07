"""Tests for the privacy section prose.

Covers AIE-1054, US1 through US5.
"""

import re

import pytest

from wenchang.prompts import privacy
from wenchang.tools import TOOL_NAMES

pytestmark = pytest.mark.unit


def _collapsed() -> str:
    return re.sub(r"\s+", " ", privacy.BODY)


def test_privacy_body_is_non_empty() -> None:
    """AIE-1054, US1.1: privacy.BODY is non-empty."""
    assert privacy.BODY.strip() != ""


def test_privacy_heading() -> None:
    """AIE-1054, US1.2: privacy.HEADING is "What never to store"."""
    assert privacy.HEADING == "What never to store"


def test_privacy_body_format() -> None:
    """AIE-1054, US1.3: BODY is ASCII, lines <= 100 chars, under 2500 chars."""
    assert privacy.BODY.strip() != ""
    assert privacy.BODY.isascii()
    assert all(len(line) <= 100 for line in privacy.BODY.splitlines())
    assert len(privacy.BODY) <= 2500


@pytest.mark.parametrize(
    "phrase",
    [
        pytest.param("veto before", id="US2.1-veto-before"),
        pytest.param("worth remembering", id="US2.1-worth-remembering"),
        pytest.param("financial account numbers", id="US3.1-financial"),
        pytest.param("health diagnoses", id="US3.1-health"),
        pytest.param("indicating the user is a minor", id="US3.1-minor"),
        pytest.param("no matter how directly", id="US3.2-no-matter-how-directly"),
        pytest.param("no scope", id="US3.3-no-scope"),
        pytest.param("even when the user asks", id="US3.3-even-when-asked"),
        pytest.param("Continue the task", id="US3.4-continue-task"),
        pytest.param("will not be kept", id="US3.4-will-not-be-kept"),
        pytest.param("shared scope", id="US4.1-shared-scope"),
        pytest.param("private scope", id="US4.1-private-scope"),
        pytest.param("disclosure to a team", id="US4.2-disclosure"),
        pytest.param("note to self", id="US4.2-note-to-self"),
        pytest.param("version history", id="US4.2-version-history"),
        pytest.param(
            "unsure whether a sensitive detail is safe", id="US4.3-unsure-sensitive-detail"
        ),
        pytest.param("non-sensitive part", id="US4.3-non-sensitive-part"),
        pytest.param("judgment", id="US5.1-judgment"),
        pytest.param("No tool filter", id="US5.1-no-tool-filter"),
    ],
)
def test_privacy_body_contains_phrase(phrase: str) -> None:
    """AIE-1054, US2.1-US5.1: privacy.BODY contains each required phrase."""
    assert phrase in _collapsed()


def test_privacy_body_names_no_tools() -> None:
    """AIE-1054, US5.2: BODY names no tool and contains no backticks."""
    assert privacy.BODY.strip() != ""
    assert TOOL_NAMES
    for name in TOOL_NAMES:
        assert re.search(rf"\b{re.escape(name)}\b", privacy.BODY) is None, name
    assert "`" not in privacy.BODY


@pytest.mark.parametrize("term", ["team scope", "personal scope", "public scope", "user scope"])
def test_privacy_body_avoids_noncanonical_scope_terms(term: str) -> None:
    """AIE-1054, US5.3: BODY uses no non-canonical scope term."""
    assert privacy.BODY.strip() != ""
    assert term not in _collapsed().lower()
