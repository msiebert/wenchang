"""Tests for prompt section modules, SECTION_ORDER, and build_memory_prompt.

Covers AIE-1055, US2.1 through US2.4, US3.1 through US3.11, and US6.1
through US6.4 (the reference adopter fixture).
"""

import dataclasses
import importlib
import re
from collections.abc import Callable
from types import ModuleType
from typing import cast

import pytest

import wenchang.prompts
from prompts_reference_adopter import (
    REFERENCE_SCOPE_GUIDANCE,
    REFERENCE_SCOPE_PRIORITY,
    REFERENCE_SEED_AREAS,
    REFERENCE_SLOTS,
    REFERENCE_SYSTEMS_OF_RECORD,
)
from wenchang.core import MemoryStore
from wenchang.prompts import (
    SECTION_ORDER,
    PromptSlots,
    assemble,
    build_memory_prompt,
    overview,
    systems_of_record,
)
from wenchang.storage.memory import InMemoryStorage

pytestmark = pytest.mark.unit

EXPECTED_SECTION_ORDER = (
    "overview",
    "scope_guidance",
    "seed_areas",
    "systems_of_record",
    "applying_memory",
    "remembering",
    "privacy",
    "filing",
    "write_mechanics",
    "curated_content",
    "forgetting",
)
SLOT_IDS = ("scope_guidance", "seed_areas")
GENERIC_IDS = tuple(i for i in EXPECTED_SECTION_ORDER if i not in SLOT_IDS)
BODY_IDS = tuple(i for i in GENERIC_IDS if i != "systems_of_record")

SLOTS = PromptSlots(
    scope_guidance="Scope guidance line one.\nLine two.",
    seed_areas="- user: notes\n- team: plans",
    systems_of_record="- The catalog holds events.",
)


def _module(section_id: str) -> ModuleType:
    return importlib.import_module(f"wenchang.prompts.{section_id}")


def _heading(section_id: str) -> str:
    if section_id == "scope_guidance":
        return assemble.SCOPE_GUIDANCE_HEADING
    if section_id == "seed_areas":
        return assemble.SEED_AREAS_HEADING
    return cast(str, _module(section_id).HEADING)


def _sections(prompt: str) -> dict[str, str]:
    """Parse a prompt into {heading: body}; bodies must not contain a `## ` line."""
    assert prompt.startswith("## ")
    assert prompt.endswith("\n")
    parts = prompt[len("## ") : -1].split("\n\n## ")
    sections: dict[str, str] = {}
    for part in parts:
        heading, sep, body = part.partition("\n\n")
        assert sep == "\n\n", part
        assert heading not in sections, heading
        sections[heading] = body
    return sections


def _heading_lines(prompt: str) -> list[str]:
    return [line[len("## ") :] for line in prompt.split("\n") if line.startswith("## ")]


def _sentences(text: str) -> list[str]:
    collapsed = re.sub(r"\s+", " ", text)
    return [s for s in re.split(r"(?<=[.!?])\s+", collapsed.strip()) if s]


def _set_all_bodies(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Give every generic BODY a padded non-empty value; return the expected stripped bodies."""
    bodies: dict[str, str] = {}
    for section_id in BODY_IDS:
        monkeypatch.setattr(_module(section_id), "BODY", f"  Body of {section_id}.\n\n")
        bodies[section_id] = f"Body of {section_id}."
    return bodies


# --- US2: section modules and SECTION_ORDER ---------------------------------


def test_public_all() -> None:
    """AIE-1055, US2.1: __all__ lists exactly the three public names, each resolvable."""
    assert wenchang.prompts.__all__ == ["SECTION_ORDER", "PromptSlots", "build_memory_prompt"]
    for name in wenchang.prompts.__all__:
        assert hasattr(wenchang.prompts, name), name
    assert wenchang.prompts.PromptSlots is PromptSlots
    assert wenchang.prompts.build_memory_prompt is build_memory_prompt


def test_section_order() -> None:
    """AIE-1055, US2.2: SECTION_ORDER is exactly the eleven ids in order."""
    assert SECTION_ORDER == EXPECTED_SECTION_ORDER
    assert type(SECTION_ORDER) is tuple
    assert assemble.SECTION_ORDER is SECTION_ORDER


@pytest.mark.parametrize("section_id", GENERIC_IDS)
def test_section_module_shape(section_id: str) -> None:
    """AIE-1055, US2.3: each generic section module has a non-empty str HEADING;
    systems_of_record has PRINCIPLE and no BODY, every other has BODY."""
    module = _module(section_id)

    heading = cast(object, getattr(module, "HEADING", None))
    assert type(heading) is str
    assert heading.strip() != ""
    if section_id == "systems_of_record":
        assert type(cast(object, getattr(module, "PRINCIPLE", None))) is str
        assert not hasattr(module, "BODY")
    else:
        assert type(cast(object, getattr(module, "BODY", None))) is str


def test_headings_distinct_and_owned_values_pinned() -> None:
    """AIE-1055, US2.4: all eleven headings are non-empty and distinct; the four
    owned by this issue have their exact values."""
    headings = [_heading(section_id) for section_id in EXPECTED_SECTION_ORDER]

    assert len(headings) == 11
    assert all(h.strip() for h in headings)
    assert len(set(headings)) == 11
    assert overview.HEADING == "Memory"
    assert assemble.SCOPE_GUIDANCE_HEADING == "Scopes"
    assert assemble.SEED_AREAS_HEADING == "Seed areas"
    assert systems_of_record.HEADING == "Systems of record"


# --- US3: build_memory_prompt -----------------------------------------------


def test_build_returns_exact_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """AIE-1055, US3.1: valid slots produce an exact str."""
    for section_id in BODY_IDS:
        monkeypatch.setattr(_module(section_id), "BODY", "")
    monkeypatch.setattr(overview, "BODY", "Overview text.")
    monkeypatch.setattr(systems_of_record, "PRINCIPLE", "\nPrinciple text.\n")
    slots = PromptSlots(scope_guidance="Guide.", seed_areas="Seeds.", systems_of_record="SoR.")

    out = build_memory_prompt(slots)

    assert type(out) is str
    assert out == (
        "## Memory\n\nOverview text.\n\n"
        "## Scopes\n\nGuide.\n\n"
        "## Seed areas\n\nSeeds.\n\n"
        "## Systems of record\n\nPrinciple text.\n\nSoR.\n"
    )


def test_build_is_deterministic() -> None:
    """AIE-1055, US3.2: the same slots give identical output on repeated calls."""
    assert build_memory_prompt(SLOTS) == build_memory_prompt(SLOTS)


class _SpoofedSlots:
    """Claims to be PromptSlots via __class__ without being one."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleVariableOverride, reportIncompatibleMethodOverride]
        return PromptSlots


@pytest.mark.parametrize(
    ("value", "type_name"),
    [(None, "NoneType"), ({"scope_guidance": "a"}, "dict"), (_SpoofedSlots(), "_SpoofedSlots")],
    ids=["none", "dict", "spoofed-class"],
)
def test_build_rejects_non_prompt_slots(value: object, type_name: str) -> None:
    """AIE-1055, US3.3: a non-PromptSlots argument raises TypeError naming its real type."""
    with pytest.raises(TypeError, match=rf"^slots must be PromptSlots, not {type_name}$"):
        build_memory_prompt(cast(PromptSlots, value))


def test_build_slots_is_positional_only() -> None:
    """AIE-1055, US3.4: passing slots by keyword raises TypeError."""
    build = cast(Callable[..., object], build_memory_prompt)

    with pytest.raises(TypeError):
        build(slots=SLOTS)


def test_build_full_output_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """AIE-1055, US3.5: with every body non-empty, output is each `## heading` plus
    stripped body in SECTION_ORDER, joined by blank lines, ending in one newline."""
    bodies = _set_all_bodies(monkeypatch)
    sor = cast(str, SLOTS.systems_of_record)
    bodies["scope_guidance"] = SLOTS.scope_guidance
    bodies["seed_areas"] = SLOTS.seed_areas
    bodies["systems_of_record"] = systems_of_record.PRINCIPLE.strip() + "\n\n" + sor
    headings = [_heading(section_id) for section_id in EXPECTED_SECTION_ORDER]

    out = build_memory_prompt(SLOTS)

    expected = (
        "\n\n".join(
            f"## {_heading(section_id)}\n\n{bodies[section_id]}"
            for section_id in EXPECTED_SECTION_ORDER
        )
        + "\n"
    )
    assert out == expected
    assert _heading_lines(out) == headings


@pytest.mark.parametrize("blank", ["", "   \n\t "], ids=["empty", "whitespace"])
@pytest.mark.parametrize("section_id", BODY_IDS)
def test_build_omits_blank_section(
    monkeypatch: pytest.MonkeyPatch, section_id: str, blank: str
) -> None:
    """AIE-1055, US3.6: a section whose BODY is empty or whitespace-only is omitted
    without leaving extra blank lines."""
    _set_all_bodies(monkeypatch)
    monkeypatch.setattr(_module(section_id), "BODY", blank)
    omitted = _heading(section_id)

    out = build_memory_prompt(SLOTS)

    assert omitted not in _heading_lines(out)
    assert f"## {omitted}" not in out
    assert "\n\n\n" not in out
    assert out.endswith("\n")
    assert not out.endswith("\n\n")
    assert _heading_lines(out) == [_heading(i) for i in EXPECTED_SECTION_ORDER if i != section_id]


def test_build_slot_text_under_headings() -> None:
    """AIE-1055, US3.7: scope_guidance appears verbatim directly under `## Scopes`
    and seed_areas directly under `## Seed areas`."""
    out = build_memory_prompt(SLOTS)

    assert f"## Scopes\n\n{SLOTS.scope_guidance}\n\n## Seed areas\n\n" in out
    assert f"## Seed areas\n\n{SLOTS.seed_areas}\n\n## " in out
    sections = _sections(out)
    assert sections["Scopes"] == SLOTS.scope_guidance
    assert sections["Seed areas"] == SLOTS.seed_areas


def test_build_systems_of_record_body() -> None:
    """AIE-1055, US3.8: the SoR body is PRINCIPLE.strip(), a blank line, then the slot."""
    slots = dataclasses.replace(SLOTS, systems_of_record="X")

    out = build_memory_prompt(slots)

    assert _sections(out)["Systems of record"] == systems_of_record.PRINCIPLE.strip() + "\n\nX"


def test_build_omits_systems_of_record_when_none() -> None:
    """AIE-1055, US3.9: with systems_of_record None, neither the SoR heading nor any
    sentence of PRINCIPLE appears."""
    slots = PromptSlots(scope_guidance="Guide.", seed_areas="Seeds.", systems_of_record=None)
    sentences = _sentences(systems_of_record.PRINCIPLE)

    out = build_memory_prompt(slots)

    assert sentences
    assert systems_of_record.HEADING not in _heading_lines(out)
    collapsed = re.sub(r"\s+", " ", out)
    for sentence in sentences:
        assert sentence not in collapsed, sentence


@pytest.mark.parametrize("sor", ["SoR.", None], ids=["with-sor", "without-sor"])
def test_build_starts_with_memory_and_ends_with_one_newline(sor: str | None) -> None:
    """AIE-1055, US3.10: output starts with `## Memory`, has no H1, and ends with
    exactly one newline."""
    slots = PromptSlots(scope_guidance="Guide.", seed_areas="Seeds.", systems_of_record=sor)

    out = build_memory_prompt(slots)

    assert out.startswith("## Memory\n\n")
    assert out.endswith("\n")
    assert not out.endswith("\n\n")
    assert not any(line.startswith("# ") for line in out.split("\n"))


def test_build_reads_bodies_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """AIE-1055, US3.11: changing section bodies at runtime changes the output."""
    before = build_memory_prompt(SLOTS)
    monkeypatch.setattr(overview, "BODY", "Replacement overview.")
    forgetting = _module("forgetting")
    monkeypatch.setattr(forgetting, "BODY", "Forget carefully.")
    monkeypatch.setattr(systems_of_record, "PRINCIPLE", "Replacement principle.")

    after = build_memory_prompt(SLOTS)

    assert after != before
    sections = _sections(after)
    assert sections["Memory"] == "Replacement overview."
    assert sections[cast(str, forgetting.HEADING)] == "Forget carefully."
    assert sections["Systems of record"] == (
        "Replacement principle.\n\n" + cast(str, SLOTS.systems_of_record)
    )


# --- US6: reference adopter fixture -----------------------------------------


def test_reference_slots_build_and_appear_under_headings() -> None:
    """AIE-1055, US6.1: REFERENCE_SLOTS builds and each slot appears verbatim
    directly under its heading."""
    for blob in (REFERENCE_SCOPE_GUIDANCE, REFERENCE_SEED_AREAS, REFERENCE_SYSTEMS_OF_RECORD):
        assert blob == blob.strip()
    assert REFERENCE_SLOTS.scope_guidance == REFERENCE_SCOPE_GUIDANCE
    assert REFERENCE_SLOTS.seed_areas == REFERENCE_SEED_AREAS
    assert REFERENCE_SLOTS.systems_of_record == REFERENCE_SYSTEMS_OF_RECORD

    out = build_memory_prompt(REFERENCE_SLOTS)

    sections = _sections(out)
    assert sections["Scopes"] == REFERENCE_SCOPE_GUIDANCE
    assert sections["Seed areas"] == REFERENCE_SEED_AREAS
    assert sections["Systems of record"] == (
        systems_of_record.PRINCIPLE.strip() + "\n\n" + REFERENCE_SYSTEMS_OF_RECORD
    )


def test_reference_scope_guidance_rules() -> None:
    """AIE-1055, US6.2: the reference scope guidance states the hierarchy, the scope
    test, ask-before-shared-write, contradiction, and containment rules."""
    text = re.sub(r"\s+", " ", REFERENCE_SCOPE_GUIDANCE)

    assert (
        "There are three scopes: user, project, and organization. An organization contains "
        "projects, and a user can belong to several organizations." in text
    )
    assert "Scope test: scope a fact by who it is true for, not who said it." in text
    assert (
        "Before saving a new fact to a shared scope (project or organization), ask the user "
        "first and say which scope you intend to use." in text
    )
    assert (
        "If a new fact contradicts one already stored in a shared scope, do not overwrite it "
        "silently" in text
    )
    assert "Never write a fact about one project there." in text


def test_reference_seed_areas_content() -> None:
    """AIE-1055, US6.2: the reference seed areas list each scope's areas, mark the
    system area read-only, and present the list as extensible."""
    lines = REFERENCE_SEED_AREAS.split("\n")
    text = re.sub(r"\s+", " ", REFERENCE_SEED_AREAS)

    assert "- user: identity, preferences, workflows, people" in lines
    assert "- project: taxonomy, metrics, entities, conventions, glossary" in lines
    assert "- organization: business-context, vocabulary" in lines
    assert "Every scope also has a `system/` area." in text
    assert "is read-only." in text
    assert "not a fixed list" in text


def test_reference_systems_of_record_content() -> None:
    """AIE-1055, US6.2: the reference systems of record name the event catalog,
    dashboards, and cohorts."""
    assert "event catalog" in REFERENCE_SYSTEMS_OF_RECORD
    assert "Dashboards" in REFERENCE_SYSTEMS_OF_RECORD
    assert "cohorts" in REFERENCE_SYSTEMS_OF_RECORD


def test_reference_slots_without_systems_of_record() -> None:
    """AIE-1055, US6.3: REFERENCE_SLOTS with systems_of_record None omits the SoR section."""
    slots = dataclasses.replace(REFERENCE_SLOTS, systems_of_record=None)

    out = build_memory_prompt(slots)

    sections = _sections(out)
    assert "Systems of record" not in sections
    assert sections["Scopes"] == REFERENCE_SCOPE_GUIDANCE
    assert REFERENCE_SYSTEMS_OF_RECORD not in out


def test_reference_scope_priority_configures_memory_store() -> None:
    """AIE-1055, US6.4: REFERENCE_SCOPE_PRIORITY is accepted by MemoryStore and
    exposed unchanged by its scope_priority property."""
    assert REFERENCE_SCOPE_PRIORITY == ("user", "project", "organization")

    store = MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY)

    assert store.scope_priority == REFERENCE_SCOPE_PRIORITY
