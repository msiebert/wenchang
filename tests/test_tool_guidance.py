"""Unit tests for the tool-description guidance preambles (AIE-1382)."""

import re
from dataclasses import replace

import pytest

from evals.reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import PromptSlots
from wenchang.prompts import tool_guidance as tg
from wenchang.tools import TOOL_NAMES

pytestmark = pytest.mark.unit

SLOTS_A = PromptSlots(
    purpose="Acme Notes keeps a shared notebook for support teams.",
    scope_guidance="Team scope is shared; personal scope is private.",
    seed_areas="team: faq, runbooks. personal: preferences.",
)
SLOTS_B = PromptSlots(
    purpose="Orbit Garden remembers each gardener's plants and watering habits.",
    scope_guidance="Everything is private to the gardener.",
    seed_areas="user: plants, schedule.",
)
WRITE_TOOLS = ("write_file", "append_line", "replace_fact")
CONSTANTS = {
    "GET_MEMORY_INDEX_CALL_FIRST": tg.GET_MEMORY_INDEX_CALL_FIRST,
    "GET_MEMORY_INDEX_GENERIC": tg.GET_MEMORY_INDEX_GENERIC,
    "WRITE_PREAMBLE": tg.WRITE_PREAMBLE,
}


def _flat(text: str) -> str:
    """Whitespace-normalized text, so phrase checks survive hard wrapping."""
    return " ".join(text.split())


def test_preamble_tools_are_the_four_guided_tools() -> None:
    """PREAMBLE_TOOLS names the index tool and the three write tools (AIE-1382, AC1)."""
    assert tg.PREAMBLE_TOOLS == ("get_memory_index", "write_file", "append_line", "replace_fact")


@pytest.mark.parametrize("slots", [None, REFERENCE_SLOTS], ids=["no-slots", "slots"])
def test_tool_preambles_keys_and_read_only(slots: PromptSlots | None) -> None:
    """tool_preambles has exactly the PREAMBLE_TOOLS keys and rejects assignment
    (AIE-1382, AC1).
    """
    preambles = tg.tool_preambles(slots)

    assert set(preambles) == set(tg.PREAMBLE_TOOLS)
    with pytest.raises(TypeError):
        preambles["read_file"] = "x"  # pyright: ignore[reportIndexIssue]


def test_index_preamble_with_slots_is_purpose_then_call_first() -> None:
    """The index preamble is the purpose, a space, then the call-first sentence
    (AIE-1382, AC1, AC8).
    """
    preamble = tg.tool_preambles(SLOTS_A)["get_memory_index"]

    assert preamble == f"{SLOTS_A.purpose} {tg.GET_MEMORY_INDEX_CALL_FIRST}"


def test_call_first_sentence_says_to_call_first_and_points_at_rules() -> None:
    """The call-first sentence names calling first, before answering or writing,
    and the rules in the result (AIE-1382, AC1).
    """
    text = _flat(tg.GET_MEMORY_INDEX_CALL_FIRST).lower()

    assert "first" in text
    assert "before" in text
    assert "writing" in text
    assert "scopes" in text
    assert "confidence" in text
    assert "never to store" in text or "never store" in text


def test_index_preamble_without_slots_is_generic() -> None:
    """slots=None gives the generic sentence with no purpose (AIE-1382, AC8)."""
    preamble = tg.tool_preambles(None)["get_memory_index"]

    assert preamble == tg.GET_MEMORY_INDEX_GENERIC
    preamble = _flat(preamble)
    assert not preamble.startswith("When that applies")
    assert "first" in preamble.lower()
    assert "scopes" in preamble.lower()
    assert SLOTS_A.purpose not in preamble
    assert REFERENCE_SLOTS.purpose not in preamble


def test_index_preamble_follows_the_slots_given() -> None:
    """Different slots give different index preambles, each with its own purpose
    (AIE-1382, AC8).
    """
    a = tg.tool_preambles(SLOTS_A)["get_memory_index"]
    b = tg.tool_preambles(SLOTS_B)["get_memory_index"]

    assert a != b
    assert SLOTS_A.purpose in a
    assert SLOTS_B.purpose in b
    assert SLOTS_B.purpose not in a
    assert SLOTS_A.purpose not in b


def test_write_preamble_is_shared_by_the_write_tools() -> None:
    """write_file, append_line, and replace_fact carry WRITE_PREAMBLE regardless
    of the slots (AIE-1382, AC1, AC8).
    """
    for slots in (None, SLOTS_A, SLOTS_B, REFERENCE_SLOTS):
        preambles = tg.tool_preambles(slots)
        for name in WRITE_TOOLS:
            assert preambles[name] == tg.WRITE_PREAMBLE


def test_write_preamble_is_short() -> None:
    """WRITE_PREAMBLE stays near its budget so the descriptions fit (AIE-1382, AC3)."""
    assert 250 <= len(tg.WRITE_PREAMBLE) <= 600


def test_write_preamble_names_the_scope_rules_source() -> None:
    """The write preamble sends scope choice to the get_memory_index result
    (AIE-1382, AC1).
    """
    text = _flat(tg.WRITE_PREAMBLE).lower()

    assert "get_memory_index" in text
    assert "scope" in text


def test_write_preamble_gives_the_confidence_labels() -> None:
    """The write preamble spells the three labels in backticks and forbids new
    [system] lines (AIE-1382, AC1).
    """
    text = _flat(tg.WRITE_PREAMBLE)

    for label in ("`[stated]`", "`[observed]`", "`[inferred]`"):
        assert label in text
    assert "[system]" in text
    assert "never" in text.lower()


def test_write_preamble_says_to_save_as_facts_arise() -> None:
    """The write preamble says to save each fact as it arises, never to offer
    to save it later (AIE-1382, AC1).
    """
    text = _flat(tg.WRITE_PREAMBLE).lower()

    assert "save" in text
    assert "later" in text
    assert "offer" in text


def test_write_preamble_lists_what_never_to_store() -> None:
    """The write preamble forbids financial account numbers, health diagnoses,
    and minor indicators (AIE-1382, AC1).
    """
    text = _flat(tg.WRITE_PREAMBLE).lower()

    assert "financial account numbers" in text
    assert "health diagnoses" in text
    assert "minor" in text


def test_write_preamble_holds_no_adopter_text() -> None:
    """The write preamble carries none of the reference adopter's slot text
    (AIE-1382, AC8).
    """
    assert REFERENCE_SLOTS.scope_guidance not in tg.WRITE_PREAMBLE
    assert REFERENCE_SLOTS.seed_areas not in tg.WRITE_PREAMBLE
    assert REFERENCE_SLOTS.purpose not in tg.WRITE_PREAMBLE
    assert "Mixpanel" not in tg.WRITE_PREAMBLE
    for text in tg.tool_preambles(None).values():
        assert "Mixpanel" not in text


def test_preambles_ignore_scope_guidance_seed_areas_and_systems_of_record() -> None:
    """Only the purpose varies the preambles; the other slots do not
    (AIE-1382, AC8).
    """
    changed = replace(
        REFERENCE_SLOTS,
        scope_guidance="Entirely different scope text.",
        seed_areas="other: areas.",
        systems_of_record=None,
    )

    assert tg.tool_preambles(changed) == tg.tool_preambles(REFERENCE_SLOTS)


@pytest.mark.parametrize("name", list(CONSTANTS))
def test_constant_is_ascii_with_short_lines(name: str) -> None:
    """Each guidance constant is ASCII with every line at most 100 characters
    (AIE-1382, AC3).
    """
    text = CONSTANTS[name]

    assert text.isascii()
    for line in text.split("\n"):
        assert len(line) <= 100, line


@pytest.mark.parametrize("name", list(CONSTANTS))
def test_constant_has_no_linear_ids(name: str) -> None:
    """No guidance constant contains a Linear issue ID (AIE-1382, AC3)."""
    assert re.search(r"AIE-\d+", CONSTANTS[name]) is None


@pytest.mark.parametrize("name", list(CONSTANTS))
def test_constant_snake_case_names_are_real_tools(name: str) -> None:
    """Backticked snake_case names in a guidance constant are real tool names
    (AIE-1382, AC3).
    """
    for match in re.finditer(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", CONSTANTS[name]):
        assert match.group(1) in TOOL_NAMES, match.group(0)
    for match in re.finditer(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", CONSTANTS[name]):
        assert match.group(1) in TOOL_NAMES, match.group(0)
