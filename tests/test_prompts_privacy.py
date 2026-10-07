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
        pytest.param(
            "The refusals below override the previous section", id="US2.1-refusals-override"
        ),
        pytest.param("however useful a fact seems", id="US2.1-however-useful"),
        pytest.param("Refuse outright to store", id="US3.2-refuse-outright"),
        pytest.param("financial account numbers", id="US3.1-financial"),
        pytest.param("health diagnoses", id="US3.1-health"),
        pytest.param("indicating the user is a minor", id="US3.1-minor"),
        pytest.param("even if the user states it directly", id="US3.2-even-if-stated-directly"),
        pytest.param("not in any file or scope, private included", id="US3.3-no-file-or-scope"),
        pytest.param("asks you to remember it", id="US3.3-even-when-asked"),
        pytest.param("Continue the task", id="US3.4-continue-task"),
        pytest.param("will not be kept", id="US3.4-will-not-be-kept"),
        pytest.param("shared scope", id="US4.1-shared-scope"),
        pytest.param("private scope", id="US4.1-private-scope"),
        pytest.param(
            "disclosure to a team rather than a note to self", id="US4.2-disclosure-not-note"
        ),
        pytest.param("version history", id="US4.2-version-history"),
        pytest.param("unsure whether such a detail is safe", id="US4.3-unsure-detail"),
        pytest.param("non-sensitive part", id="US4.3-non-sensitive-part"),
        pytest.param("No tool filter", id="US5.1-no-tool-filter"),
        pytest.param("successful write does not mean it was safe", id="US5.1-success-not-safe"),
    ],
)
def test_privacy_body_contains_phrase(phrase: str) -> None:
    """AIE-1054, US2.1-US5.1; AIE-1165: privacy.BODY contains each required phrase."""
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
