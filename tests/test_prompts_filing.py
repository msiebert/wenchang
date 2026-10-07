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
        pytest.param("file that is about", id="US2.1-file-that-is-about"),
        pytest.param("not in whichever file", id="US2.1-not-in-whichever-file"),
        pytest.param("starting shape", id="US2.2-starting-shape"),
        pytest.param("new files and areas", id="US2.2-new-files-and-areas"),
        pytest.param("Before you create a new file", id="US3.1-before-you-create"),
        pytest.param("descriptions and aliases", id="US3.2-descriptions-and-aliases"),
        pytest.param("the index you loaded", id="US3.2-the-index-you-loaded"),
        pytest.param("`get_memory_index()`", id="US3.2-get-memory-index"),
        pytest.param("append to it or edit it", id="US3.3-append-or-edit"),
        pytest.param("creating a duplicate", id="US3.3-creating-a-duplicate"),
        pytest.param("ambiguous", id="US3.4-ambiguous"),
        pytest.param("one or two", id="US3.4-one-or-two"),
        pytest.param("`read_file`", id="US3.4-read-file"),
        pytest.param("never the whole store", id="US3.4-never-the-whole-store"),
        pytest.param("If nothing there matches", id="US3.5-if-nothing-there-matches"),
        pytest.param("listed under `capped` in the index", id="US3.5-listed-under-capped"),
        pytest.param("`list_prefix(scope, area)`", id="US3.5-list-prefix-scope-area"),
        pytest.param("that one area only", id="US3.5-that-one-area-only"),
        pytest.param("check its entries the same way", id="US3.5-check-its-entries"),
        pytest.param("only when you create a file", id="US3.7-only-when-you-create"),
        pytest.param("does not trigger it", id="US3.7-does-not-trigger-it"),
        pytest.param("Every write should carry any new names", id="US4.1-every-write-should-carry"),
        pytest.param("nicknames", id="US4.1-nicknames"),
        pytest.param("acronyms", id="US4.1-acronyms"),
        pytest.param("phrasings", id="US4.1-phrasings"),
        pytest.param("`aliases`", id="US4.2-aliases"),
        pytest.param("`aliases` on the same write that records the fact", id="US4.2-same-write"),
        pytest.param("entire search surface", id="US4.3-entire-search-surface"),
    ],
)
def test_filing_body_contains_phrase(phrase: str) -> None:
    """AIE-1049, US2.1-US4.3: filing.BODY contains each required phrase."""
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
