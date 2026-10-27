"""Tests for the overview section prose.

Covers AIE-1055, US4.1.
"""

import re

import pytest

from evals.reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import build_memory_prompt, overview

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


def test_overview_body_opens_without_restating_purpose() -> None:
    """AIE-1164: overview.BODY opens by defining memory and does not repeat the purpose
    slot's "You have persistent memory" opening."""
    body = re.sub(r"\s+", " ", overview.BODY).strip()

    assert body.startswith(
        "Memory is short markdown files that outlast this conversation, each addressed by "
        "a scope, an area in that scope, and a name."
    )
    assert "You have persistent memory" not in body


NAME_SENTENCE = "When you tell the user where something is stored, name its scope, area, and name."


def test_overview_body_second_sentence_names_scope_area_and_name() -> None:
    """AIE-1252, US3.1: the second sentence of overview.BODY tells the agent to name
    a stored thing's scope, area, and name, and the body never mentions a path."""
    body = re.sub(r"\s+", " ", overview.BODY)

    assert _sentences(overview.BODY)[1] == NAME_SENTENCE
    assert NAME_SENTENCE in body
    assert "`path`" not in body
    assert re.search(r"\bpaths?\b", body, re.IGNORECASE) is None


def test_name_sentence_names_no_example_values() -> None:
    """AIE-1252, US3.2: the sentence has no backtick span and names no area or
    fixture value from any scenario."""
    sentence = next((s for s in _sentences(overview.BODY) if "where something" in s), "")

    assert sentence != ""
    assert re.findall(r"`([^`]*)`", sentence) == []
    for word in (
        "metrics",
        "dau",
        "preferences",
        "workflows",
        "vocabulary",
        "glossary",
        "conventions",
    ):
        assert word not in sentence.lower()


def test_memory_section_of_reference_prompt_carries_name_sentence() -> None:
    """AIE-1198, US1.4; AIE-1252: the "## Memory" section of the built prompt has the sentence."""
    prompt = build_memory_prompt(REFERENCE_SLOTS)

    start = prompt.index("## Memory")
    end = prompt.find("\n## ", start + 1)
    section = re.sub(r"\s+", " ", prompt[start : end if end != -1 else len(prompt)])

    assert NAME_SENTENCE in section
