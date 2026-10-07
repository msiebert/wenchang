"""Tests for the write mechanics section prose.

Covers AIE-1051, US1.1 through US5.3.
"""

import re

import pytest

from prompts_reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import build_memory_prompt, write_mechanics

pytestmark = pytest.mark.unit


def _body() -> str:
    return re.sub(r"\s+", " ", write_mechanics.BODY)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _only_sentence_containing(anchor: str) -> str:
    matches = [s for s in _sentences(_body()) if anchor in s]
    assert len(matches) == 1, f"expected exactly one sentence containing {anchor!r}: {matches}"
    return matches[0]


def test_body_is_non_empty() -> None:
    """AIE-1051, US1.1: write_mechanics.BODY is not empty."""
    assert write_mechanics.BODY.strip() != ""


def test_heading_is_choosing_a_write_tool() -> None:
    """AIE-1051, US1.2: the heading is "Choosing a write tool"."""
    assert write_mechanics.HEADING == "Choosing a write tool"


def test_assembled_prompt_contains_section() -> None:
    """AIE-1051, US1.3: build_memory_prompt renders the heading followed by the body."""
    expected = "## Choosing a write tool\n\n" + write_mechanics.BODY.strip()
    assert expected in build_memory_prompt(REFERENCE_SLOTS)


@pytest.mark.parametrize("phrase", ["Match the write to the change"])
def test_us2_1_match_write_to_change(phrase: str) -> None:
    """AIE-1051, US2.1: body says to match the write to the change."""
    assert phrase in _body()


@pytest.mark.parametrize("phrase", ["`append_line`", "add one fact", "existing file"])
def test_us2_2_append_line_adds_one_fact(phrase: str) -> None:
    """AIE-1051, US2.2: body assigns adding one fact to an existing file to append_line."""
    assert phrase in _body()


def test_us2_2_add_one_fact_sentence_names_append_line() -> None:
    """AIE-1051, US2.2: the sentence about adding one fact names append_line."""
    assert "`append_line`" in _only_sentence_containing("add one fact")


@pytest.mark.parametrize(
    "phrase",
    [
        "`replace_fact`",
        "change one fact",
        "quote the existing line",
        "surrounding lines stay intact",
    ],
)
def test_us2_3_replace_fact_changes_one_fact(phrase: str) -> None:
    """AIE-1051, US2.3: body assigns changing one fact to replace_fact, quoting the line."""
    assert phrase in _body()


def test_us2_3_change_one_fact_sentence_names_replace_fact() -> None:
    """AIE-1051, US2.3: the sentence about changing one fact names replace_fact."""
    assert "`replace_fact`" in _only_sentence_containing("change one fact")


@pytest.mark.parametrize("phrase", ["`write_file`", "new file", "restructuring many lines"])
def test_us2_4_write_file_for_new_or_restructure(phrase: str) -> None:
    """AIE-1051, US2.4: body reserves write_file for new files or restructuring many lines."""
    assert phrase in _body()


def test_us2_4_restructuring_sentence_names_write_file() -> None:
    """AIE-1051, US2.4: the sentence about restructuring many lines names write_file."""
    assert "`write_file`" in _only_sentence_containing("restructuring many lines")


@pytest.mark.parametrize(
    "phrase", ["mechanically impossible to disturb lines you were not editing"]
)
def test_us2_5_mechanically_impossible(phrase: str) -> None:
    """AIE-1051, US2.5: body states untouched lines cannot be disturbed."""
    assert phrase in _body()


@pytest.mark.parametrize("phrase", ["`aliases`", "`description`"])
def test_us3_1_names_metadata_parameters(phrase: str) -> None:
    """AIE-1051, US3.1: body names the aliases and description parameters."""
    assert phrase in _body()


@pytest.mark.parametrize("anchor", ["pass that name in `aliases`", "pass the new `description`"])
def test_us3_2_metadata_on_same_call(anchor: str) -> None:
    """AIE-1051, US3.2: the aliases and description sentences each say "same call"."""
    assert "same call" in _only_sentence_containing(anchor)


@pytest.mark.parametrize(
    "phrase",
    ["Removing an alias", "rewriting the description wholesale with no fact to write"],
)
def test_us3_3_removal_phrases_present(phrase: str) -> None:
    """AIE-1051, US3.3: body covers removing an alias and wholesale description rewrites."""
    assert phrase in _body()


def test_us3_3_removing_alias_sentence_names_write_file() -> None:
    """AIE-1051, US3.3: the sentence about removing an alias names write_file."""
    assert "`write_file`" in _only_sentence_containing("Removing an alias")


@pytest.mark.parametrize("tool", ["`append_line`", "`replace_fact`", "`write_file`"])
def test_us3_4_alias_sentence_names_all_write_tools(tool: str) -> None:
    """AIE-1051, US3.4: the sentence passing a new name in aliases names each write tool."""
    assert tool in _only_sentence_containing("pass that name in `aliases`")


@pytest.mark.parametrize("phrase", ["drop one fact line", "`old_string`", "empty `new_string`"])
def test_us4_1_drop_fact_via_empty_new_string(phrase: str) -> None:
    """AIE-1051, US4.1: body drops one fact line via old_string and an empty new_string."""
    assert phrase in _body()


def test_us4_1_drop_sentence_names_replace_fact() -> None:
    """AIE-1051, US4.1: the sentence about dropping one fact line names replace_fact."""
    assert "`replace_fact`" in _only_sentence_containing("drop one fact line")


@pytest.mark.parametrize("phrase", ["line break that follows it", "the line break before it"])
def test_us4_2_drop_includes_line_break(phrase: str) -> None:
    """AIE-1051, US4.2: body says which line break to include when dropping a line."""
    assert phrase in _body()


def test_us4_3_no_blank_line_left() -> None:
    """AIE-1051, US4.3: body says no blank line is left behind."""
    assert "no blank line" in _body()


def test_us4_4_delete_file_for_whole_file() -> None:
    """AIE-1051, US4.4: the delete_file sentence reserves it for removing the whole file."""
    assert "only when the whole file goes" in _only_sentence_containing("`delete_file`")


@pytest.mark.parametrize(
    "term",
    [
        "conflict",
        "expected_version",
        "version",
        "unique",
        "byte",
        "ceiling",
        "retry",
        "read-only",
        "slug",
    ],
)
def test_us5_1_no_docstring_mechanics(term: str) -> None:
    """AIE-1051, US5.1: body omits per-call mechanics owned by tool docstrings."""
    assert term not in _body().lower()


@pytest.mark.parametrize("label", ["[stated]", "[observed]", "[inferred]", "[system]"])
def test_us5_2_no_label_syntax(label: str) -> None:
    """AIE-1051, US5.2: body omits fact label syntax."""
    assert label not in _body()


def test_us5_3_body_under_length_budget() -> None:
    """AIE-1051, US5.3: body is under 2500 characters."""
    assert len(write_mechanics.BODY) < 2500
