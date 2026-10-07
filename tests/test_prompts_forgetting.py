"""Tests for the forgetting section prose.

Covers AIE-1053, US1-US6.
"""

import re

import pytest

from wenchang.prompts import PromptSlots, build_memory_prompt, forgetting

pytestmark = pytest.mark.unit


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_forgetting_body_is_non_empty() -> None:
    """AIE-1053, US1.1: forgetting.BODY is non-empty."""
    assert forgetting.BODY.strip() != ""


def test_forgetting_heading() -> None:
    """AIE-1053, US1.2: forgetting.HEADING is "Forgetting"."""
    assert forgetting.HEADING == "Forgetting"


def test_build_memory_prompt_ends_with_forgetting_section() -> None:
    """AIE-1053, US1.3: the rendered prompt ends with the forgetting section."""
    slots = PromptSlots(scope_guidance="Scope guidance.", seed_areas="Seed areas.")
    body = forgetting.BODY.strip()
    assert body != ""
    assert build_memory_prompt(slots).endswith("## Forgetting\n\n" + body + "\n")


@pytest.mark.parametrize(
    "phrase",
    [
        pytest.param("two moves", id="US2.1-two-moves"),
        pytest.param("`replace_fact`", id="US2.2-replace-fact"),
        pytest.param("fact line", id="US2.2-fact-line"),
        pytest.param("`delete_file`", id="US2.3-delete-file"),
        pytest.param("whole file", id="US2.3-whole-file"),
        pytest.param(
            "write-tool section says how to take the line break",
            id="US2.5-write-tool-section-line-break",
        ),
        pytest.param("the file's only fact", id="US2.6-files-only-fact"),
        pytest.param("Removal is total", id="US3.1-removal-is-total"),
        pytest.param("solely", id="US3.3-solely"),
        pytest.param("`[inferred]`", id="US3.4-inferred"),
        pytest.param("description or alias", id="US3.5-description-or-alias"),
        pytest.param(
            "exists only because of the removed fact",
            id="US3.5-exists-only-because",
        ),
        pytest.param("ambiguous", id="US4.1-ambiguous"),
        pytest.param("end date", id="US5.1-end-date"),
        pytest.param("candidate", id="US5.1-candidate"),
        pytest.param("not automatically", id="US5.2-not-automatically"),
        pytest.param("maintenance", id="US5.3-maintenance"),
        pytest.param("`system/`", id="US6.1-system"),
        pytest.param("curated-content section", id="US6.1-curated-content-section"),
        pytest.param("Never drop or delete", id="US6.2-never-drop-or-delete"),
    ],
)
def test_forgetting_body_contains_phrase(phrase: str) -> None:
    """AIE-1053, US2-US6: forgetting.BODY contains each required phrase."""
    assert phrase in _flat(forgetting.BODY)


def test_forgetting_body_says_ask() -> None:
    """AIE-1053, US4.1: forgetting.BODY tells the agent to ask when ambiguous."""
    assert re.search(r"\bask\b", _flat(forgetting.BODY))


def test_forgetting_body_omits_write_tools() -> None:
    """AIE-1053, US2.4: forgetting.BODY does not name write_file or append_line."""
    flat = _flat(forgetting.BODY)
    assert flat.strip() != ""
    assert "`write_file`" not in flat
    assert "`append_line`" not in flat


def test_forgetting_body_has_no_used_to_tombstones() -> None:
    """AIE-1053, US3.2: forgetting.BODY contains no "used to"-style phrasing."""
    flat = _flat(forgetting.BODY).lower()
    assert flat.strip() != ""
    for phrase in ("used to", "used-to", "formerly", "previously believed"):
        assert phrase not in flat
