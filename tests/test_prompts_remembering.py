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
        "said",
        "directly",
        "tool result",
        "session data",
        "behavior",
        "pattern across several observations",
    ],
)
def test_body_defines_learned_labels(phrase: str) -> None:
    """AIE-1050, US2.3: BODY defines stated, observed, and inferred by evidence source."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize("phrase", ["curated", "seeded", "never write a new"])
def test_body_reserves_system_label(phrase: str) -> None:
    """AIE-1050, US2.4: BODY marks [system] as curated and never agent-written."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize("phrase", ["keep", "new or rewritten"])
def test_body_preserves_labels_on_merge(phrase: str) -> None:
    """AIE-1050, US2.5: BODY keeps existing labels on merge; only new lines get one."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "calibrated",
        "evidence",
        '"investigated X once," not "is deeply focused on X."',
    ],
)
def test_body_calibrates_phrasing(phrase: str) -> None:
    """AIE-1050, US3: BODY asks for phrasing calibrated to evidence."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "would remembering this change a future session?",
        "better, different, or faster",
        "regardless of",
        "true",
        "write time",
        "observe",
        "workflows",
        "findings",
        "transient",
        "one-off number",
        "definition or pattern",
    ],
)
def test_body_states_save_criterion(phrase: str) -> None:
    """AIE-1050, US4: BODY states the forward-looking save criterion."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        "end date",
        "in the fact line",
        "in prose",
        "prefers JSON output, but only until the v3 migration completes on October 30.",
        "not a metadata field",
        "per-fact timestamp",
        "user's own framing",
        "never guess",
        "still applies",
        "maintenance pass",
        "lapsed",
    ],
)
def test_body_describes_in_line_expiry(phrase: str) -> None:
    """AIE-1050, US5.1-5.5: BODY describes in-line expiry written in prose."""
    assert phrase in _flat(remembering.BODY)


@pytest.mark.parametrize("pattern", NEGATIVE_PATTERNS, ids=NEGATIVE_IDS)
def test_body_has_no_machine_dates_or_metadata(pattern: re.Pattern[str]) -> None:
    """AIE-1050, US5.6: raw BODY has no ISO date, clock time, year, or metadata key."""
    assert pattern.search(remembering.BODY) is None


@pytest.mark.parametrize("pattern", NEGATIVE_PATTERNS, ids=NEGATIVE_IDS)
def test_negative_patterns_match_known_bad_sample(pattern: re.Pattern[str]) -> None:
    """AIE-1050, US5.6: each negative pattern matches a known-bad sample."""
    assert pattern.search(KNOWN_BAD_SAMPLE) is not None


def test_body_has_at_most_one_example_fact_line() -> None:
    """AIE-1050, US5.7: raw BODY contains at most one example fact line."""
    assert len(FACT_LINE.findall(remembering.BODY)) <= 1


def test_fact_line_pattern_counts_multiple_lines() -> None:
    """AIE-1050, US5.7: the fact-line pattern counts each example line in a sample."""
    sample = "`- [stated] prefers JSON`\n`- [observed] runs reports weekly`\n- `[inferred]`: def\n"
    assert len(FACT_LINE.findall(sample)) == 2


@pytest.mark.parametrize(
    "phrase",
    [
        "as facts arise",
        "mid-conversation",
        "before you ask a follow-up",
        "conversation may end",
        "refusals in the next section",
        "override",
    ],
)
def test_body_describes_write_timing(phrase: str) -> None:
    """AIE-1050, US6: BODY says to write as facts arise and defers to refusals."""
    assert phrase in _flat(remembering.BODY)
