"""Tests for the remembering section prose.

Covers AIE-1050, US1 through US6.
"""

import re

import pytest

from wenchang.file_format import ConfidenceLabel
from wenchang.prompts import remembering

pytestmark = pytest.mark.unit

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CLOCK_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
FOUR_DIGIT_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
METADATA_KEY = re.compile(r"\b(?:expires?|expiry|until|date|timestamp)\s*:", re.IGNORECASE)

NEGATIVE_PATTERNS = [ISO_DATE, CLOCK_TIME, FOUR_DIGIT_YEAR, METADATA_KEY]
NEGATIVE_IDS = ["iso_date", "clock_time", "four_digit_year", "metadata_key"]

KNOWN_BAD_SAMPLE = "- [stated] prefers JSON (expires: 2026-10-30 09:00)"

FACT_LINE = re.compile(r"- \[(?:stated|observed|inferred|system)\] ")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_body_is_non_empty() -> None:
    """AIE-1050, US1.1: remembering.BODY is non-empty."""
    assert remembering.BODY.strip() != ""


def test_heading_is_unchanged() -> None:
    """AIE-1050, US1.2: remembering.HEADING is "Deciding what to remember"."""
    assert remembering.HEADING == "Deciding what to remember"


def test_body_is_under_length_budget() -> None:
    """AIE-1050, US1.3: remembering.BODY is shorter than 2500 characters."""
    assert len(remembering.BODY) < 2500


def test_body_label_set_matches_confidence_label_enum() -> None:
    """AIE-1050, US2.1: bracketed labels in BODY are exactly the ConfidenceLabel values."""
    found = set(re.findall(r"\[([a-z]+)\]", remembering.BODY))
    assert found == {label.value for label in ConfidenceLabel}


@pytest.mark.parametrize("phrase", ["`[stated]`", "`[observed]`", "`[inferred]`", "`[system]`"])
def test_body_names_each_label(phrase: str) -> None:
    """AIE-1050, US2.2: BODY names each confidence label in code formatting."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "confidence label for how you know it",
        "told you",
        "directly",
        "tool result",
        "session data",
        "behavior",
        "pattern across several observations",
    ],
)
def test_body_defines_learned_labels(phrase: str) -> None:
    """AIE-1050, US2.3; AIE-1165: BODY defines stated, observed, and inferred by source."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize("phrase", ["curated", "marks curated content", "never write a new"])
def test_body_reserves_system_label(phrase: str) -> None:
    """AIE-1050, US2.4; AIE-1165: BODY marks [system] as curated and never agent-written."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase", ["unchanged lines keep their labels", "only new or changed lines get a fresh one"]
)
def test_body_preserves_labels_on_merge(phrase: str) -> None:
    """AIE-1050, US2.5; AIE-1165: BODY keeps existing labels on merge; only new lines get one."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "no stronger than the evidence",
        "evidence",
        '"investigated X once," not "is deeply focused on X."',
    ],
)
def test_body_calibrates_phrasing(phrase: str) -> None:
    """AIE-1050, US3; AIE-1165: BODY asks for phrasing calibrated to evidence."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "Save a fact only if it would let a future session answer",
        "better, differently, or faster",
        "otherwise leave it out, even if true",
        "what you observe",
        "workflows",
        "findings",
        "not only what the user tells you",
        "transient",
        "one-off number",
        "definition or pattern",
        "behind it, if you know it",
    ],
)
def test_body_states_save_criterion(phrase: str) -> None:
    """AIE-1050, US4; AIE-1165: BODY states the forward-looking save criterion."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "end date",
        "into the fact line",
        "as prose",
        "prefers JSON output, but only until the v3 migration completes on October 30.",
        (
            "Never put an end date in metadata, add a per-fact timestamp, or guess an end"
            " date the user did not state."
        ),
        "user's own framing",
        "end date explicit",
    ],
)
def test_body_describes_in_line_expiry(phrase: str) -> None:
    """AIE-1050, US5.1-5.5; AIE-1165: BODY describes in-line expiry written in prose."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize("pattern", NEGATIVE_PATTERNS, ids=NEGATIVE_IDS)
def test_body_has_no_machine_dates_or_metadata(pattern: re.Pattern[str]) -> None:
    """AIE-1050, US5.6: raw BODY has no ISO date, clock time, year, or metadata key."""
    assert pattern.search(remembering.BODY) is None


@pytest.mark.parametrize("pattern", NEGATIVE_PATTERNS, ids=NEGATIVE_IDS)
def test_negative_patterns_match_known_bad_sample(pattern: re.Pattern[str]) -> None:
    """AIE-1050, US5.6: each negative pattern matches a known-bad sample."""
    assert pattern.search(KNOWN_BAD_SAMPLE) is not None


@pytest.mark.parametrize(
    ("sample", "pattern"),
    [
        ("(as of 2026-10-30)", ISO_DATE),
        ("[2026-10-30]", ISO_DATE),
        ("logged 09:15", CLOCK_TIME),
        ("since 2025", FOUR_DIGIT_YEAR),
        ("expiry: soon", METADATA_KEY),
    ],
    ids=["iso_date_as_of", "iso_date_bracketed", "clock_time", "four_digit_year", "metadata_key"],
)
def test_negative_pattern_matches_realistic_sample(sample: str, pattern: re.Pattern[str]) -> None:
    """AIE-1050, US5.6: each negative pattern trips on a realistic standalone sample."""
    assert pattern.search(sample) is not None


def test_body_has_at_most_one_example_fact_line() -> None:
    """AIE-1050, US5.7: raw BODY contains at most one example fact line."""
    assert len(FACT_LINE.findall(remembering.BODY)) <= 1


def test_fact_line_pattern_counts_multiple_lines() -> None:
    """AIE-1050, US5.7: the fact-line pattern counts each example line in a sample."""
    # The backticked definition-style bullet must not be counted.
    sample = "`- [stated] prefers JSON`\n`- [observed] runs reports weekly`\n- `[inferred]`: def\n"
    assert len(FACT_LINE.findall(sample)) == 2


@pytest.mark.parametrize(
    "phrase",
    [
        "Write facts as they arise",
        "before you ask a follow-up",
        "conversation may end",
    ],
)
def test_body_describes_write_timing(phrase: str) -> None:
    """AIE-1050, US6; AIE-1165: BODY says to write facts as they arise."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize("phrase", ["override", "refusals"])
def test_body_leaves_privacy_override_to_privacy_section(phrase: str) -> None:
    """AIE-1050, US6; AIE-1165: BODY leaves the refusal override to the privacy section."""
    assert remembering.BODY.strip() != ""
    assert phrase not in _flat(remembering.BODY)
