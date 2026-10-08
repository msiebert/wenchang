"""Tests for the curated content section prose.

Covers AIE-1052, US1.1-US1.10.
"""

import re

import pytest

from wenchang.prompts import curated_content

pytestmark = pytest.mark.unit

WRITE_TOOLS = ("write_file", "append_line", "replace_fact", "delete_file")

# Only a mutation verb before `system/` is detected. Verbs match as stems, so words like
# "recorded" or "address" also trip it. A negated sentence such as "Never write to the
# `system/` area." also trips it, so the body phrases the prohibition without a mutation
# verb before `system/`.
WRITE_INTO_SYSTEM = re.compile(
    r"\b(write|append|add|save|record|put|store|edit|update|change|replace|fix|modify"
    r"|overwrite|delete|drop|remove|rewrite|insert|correct|amend)\w*\b[^.]*`?system/",
    re.IGNORECASE,
)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _sentences(text: str) -> list[str]:
    collapsed = _normalized(text)
    return [s for s in re.split(r"(?<=[.!?])\s+", collapsed.strip()) if s]


def _write_into_system(sentence: str) -> bool:
    if "system/" not in sentence:
        return False
    if any(tool in sentence for tool in WRITE_TOOLS):
        return True
    return WRITE_INTO_SYSTEM.search(sentence) is not None


def test_heading_and_body() -> None:
    """AIE-1052, US1.1: HEADING is "Curated content" and BODY is non-empty."""
    assert curated_content.HEADING == "Curated content"
    assert curated_content.BODY.strip() != ""


@pytest.mark.parametrize(
    "phrase",
    [
        # US1.2
        "`system/`",
        "curated",
        "read-only",
        "never attempt",
        "a person maintains and replaces wholesale",
        # US1.4
        "only when the user explicitly says it is wrong",
        "observed or inferred",
        "never because of something you observed or inferred",
        # US1.5
        "new fact line",
        "with its own label",
        "topical file",
        "writable area",
        # US1.6
        "in a shared scope",
        "Scopes section",
        "asking first",
        # US1.7
        "tell the user where you saved it",
        # US1.8
        "answer from the correction",
        "When a correction and a curated fact conflict, answer from the correction",
        "survives refreshes",
    ],
)
def test_body_contains_phrase(phrase: str) -> None:
    """AIE-1052, US1.2-US1.8; AIE-1165: curated_content.BODY contains each required phrase."""
    assert phrase in _normalized(curated_content.BODY)


def test_body_leaves_label_set_to_remembering() -> None:
    """AIE-1052, US1.3; AIE-1165: BODY leaves the `[system]` label to the remembering section."""
    assert curated_content.BODY.strip() != ""
    assert "`[system]`" not in curated_content.BODY


def test_body_does_not_redefine_labels() -> None:
    """AIE-1052, US1.3: BODY does not restate the non-system confidence labels."""
    for label in ("[stated]", "[observed]", "[inferred]"):
        assert label not in curated_content.BODY


def test_no_sentence_directs_a_write_into_system() -> None:
    """AIE-1052, US1.9: no sentence of BODY directs a write into the `system/` area."""
    sentences = _sentences(curated_content.BODY)
    assert len(sentences) > 1
    offending = [s for s in sentences if _write_into_system(s)]
    assert offending == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Use `append_line` to add it to the `system/` area.",
        "Record the correction in the `system/` area.",
        "Update the `system/` area with the correction.",
        "Replace the curated fact in `system/` with the user's version.",
        "Correct the curated fact in the `system/` area.",
    ],
)
def test_write_into_system_checker_rejects_known_bad(sentence: str) -> None:
    """AIE-1052, US1.10: the US1.9 checker flags each known-bad sentence."""
    assert _write_into_system(sentence)
