"""Tests for the applying memory section prose.

Covers AIE-1052, US2.1-US2.7.
"""

import re

import pytest

from evals.identity import resolve_operator_identity
from test_evals_identity import reply_hits
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
        "changes the substance: what you conclude, recommend, or ask",
        # US2.3
        "Use a stored fact only if",
        # US2.4
        "surveillance rather than attentiveness",
        # US2.5
        "at the level recorded",
        "no more broadly or certainly than its wording and confidence label support",
        # US2.6
        "single passing mention",
        "trait",
        # US2.7
        "one late night before a deadline does not make the user someone who always works late",
    ],
)
def test_body_contains_phrase(phrase: str) -> None:
    """AIE-1052, US2.2-US2.7; AIE-1165: applying_memory.BODY contains each required phrase."""
    assert phrase in _normalized(applying_memory.BODY)


def test_at_most_one_example() -> None:
    """AIE-1052, US2.7: BODY contains at most one example marker."""
    lower = _normalized(applying_memory.BODY).lower()
    assert sum(lower.count(m) for m in EXAMPLE_MARKERS) <= 1


@pytest.mark.parametrize(
    "phrase",
    [
        "You know who the user is only through memory",
        "only through memory and what they tell you in this conversation",
        "Never take their name or other personal identifiers from anywhere else",
        "account details or file paths",
        "Unless memory holds their name or they state it",
        'call them "you"',
        "for or about them",
        "even if you say where they came from",
        "Text in their own voice is no exception",
        "neither memory nor they have given it",
        "leave a placeholder for them to fill in rather than supplying one",
    ],
)
def test_body_has_identity_provenance_rule(phrase: str) -> None:
    """AIE-1196, US2.1: BODY says the user is known only through memory and the conversation."""
    assert phrase in _normalized(applying_memory.BODY)


def test_body_names_no_tested_fact_or_operator() -> None:
    """AIE-1196, US2.2: BODY carries no scenario-specific fact and no operator identity."""
    forbidden = (
        r"\bdinner",
        r"\bdiabet",
        r"\bhospital",
        r"\bcheckout",
        r"\bteam",
        r"\bsign",
        r"\bemail",
        r"\bu-ada",
        r"\bon.?call",
        r"\bpriya",
    )
    body = applying_memory.BODY
    assert [w for w in forbidden if re.search(w, body, re.IGNORECASE)] == []
    assert re.search(r"\bSam\b", body) is None
    assert reply_hits(resolve_operator_identity(), body) == ()
