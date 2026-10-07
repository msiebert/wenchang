"""Tests for the filing section prose.

Covers AIE-1049, US1 through US4.
"""

import re

import pytest

from wenchang.prompts import PromptSlots, build_memory_prompt, filing

pytestmark = pytest.mark.unit


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_filing_heading() -> None:
    """AIE-1049, US1.1: filing.HEADING is "Filing"."""
    assert filing.HEADING == "Filing"


def test_filing_body_non_empty() -> None:
    """AIE-1049, US1.1: filing.BODY is non-empty."""
    assert filing.BODY.strip() != ""


def test_filing_body_length() -> None:
    """AIE-1049, US1.2: filing.BODY is at most 2000 characters."""
    assert len(filing.BODY) <= 2000


def test_filing_section_in_assembled_prompt() -> None:
    """AIE-1049, US1.3: the assembled prompt contains the filing section."""
    assert filing.BODY.strip() != ""
    slots = PromptSlots(scope_guidance="Scopes text.", seed_areas="Seed text.")
    assert "## Filing\n\n" + filing.BODY.strip() in build_memory_prompt(slots)


@pytest.mark.parametrize(
    "phrase",
    [
        pytest.param("in the file that is about its subject", id="US2.1-file-about-subject"),
        pytest.param(
            "not whichever file happens to be open", id="US2.1-not-whichever-file-is-open"
        ),
        pytest.param("starting shape", id="US2.2-starting-shape"),
        pytest.param(
            "create files and areas as subjects need them", id="US2.2-create-files-and-areas"
        ),
        pytest.param("Before creating a file", id="US3.1-before-creating"),
        pytest.param("descriptions and aliases", id="US3.2-descriptions-and-aliases"),
        pytest.param("the index's descriptions and aliases", id="US3.2-index-descriptions"),
        pytest.param(
            "If one exists, append to it or edit it instead of creating a duplicate",
            id="US3.3-append-or-edit-not-duplicate",
        ),
        pytest.param("ambiguous", id="US3.4-ambiguous"),
        pytest.param("one or two", id="US3.4-one-or-two"),
        pytest.param("`read_file`", id="US3.4-read-file"),
        pytest.param("never the whole store", id="US3.4-never-the-whole-store"),
        pytest.param("If none matches", id="US3.5-if-none-matches"),
        pytest.param("listed under `capped`", id="US3.5-listed-under-capped"),
        pytest.param("`list_prefix(scope, area)`", id="US3.5-list-prefix-scope-area"),
        pytest.param("for that area only", id="US3.5-for-that-area-only"),
        pytest.param("check it the same way", id="US3.5-check-it-the-same-way"),
        pytest.param("any new names the subject will be looked up by", id="US4.1-new-lookup-names"),
        pytest.param("nicknames", id="US4.1-nicknames"),
        pytest.param("acronyms", id="US4.1-acronyms"),
        pytest.param("phrasings", id="US4.1-phrasings"),
        pytest.param("`aliases`", id="US4.2-aliases"),
        pytest.param(
            "On the same write that records a fact, pass in `aliases`", id="US4.2-same-write"
        ),
        pytest.param("entire search surface", id="US4.3-entire-search-surface"),
        pytest.param("there is no content search", id="US4.3-no-content-search"),
        pytest.param("next match more likely", id="US4.3-next-match-more-likely"),
        pytest.param(
            "pass a new `description` if the fact changes what it should say",
            id="US4.4-new-description",
        ),
    ],
)
def test_filing_body_contains_phrase(phrase: str) -> None:
    """AIE-1049, US2.1-US4.4; AIE-1165: filing.BODY contains each required phrase."""
    assert phrase in _normalized(filing.BODY)


@pytest.mark.parametrize(
    "phrase",
    [
        pytest.param("slug", id="US2.3-slug"),
        pytest.param("lowercase", id="US2.3-lowercase"),
        pytest.param("`list_prefix(scope)`", id="US3.6-list-prefix-scope"),
        pytest.param("`append_line`", id="US4.2-no-append-line"),
        pytest.param("`replace_fact`", id="US4.2-no-replace-fact"),
        pytest.param("`write_file`", id="US4.2-no-write-file"),
    ],
)
def test_filing_body_omits_phrase(phrase: str) -> None:
    """AIE-1049, US2.3/US3.6/US4.2: filing.BODY omits the forbidden phrases."""
    assert phrase.lower() not in _normalized(filing.BODY).lower()
