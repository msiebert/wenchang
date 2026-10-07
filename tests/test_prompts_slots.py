"""PromptSlots validation tests (AIE-1055, US1)."""

import dataclasses
import re
from typing import cast

import pytest

from wenchang.prompts.slots import PromptSlots

pytestmark = pytest.mark.unit

FIELDS = ("scope_guidance", "seed_areas", "systems_of_record")
REQUIRED_FIELDS = ("scope_guidance", "seed_areas")

VALID: dict[str, object] = {
    "scope_guidance": "Org scope is shared; user scope is private.",
    "seed_areas": "org: product, customers; system/: policies",
    "systems_of_record": "Jira holds tickets.",
}


class _SpoofsStr:
    """Claims to be a str via __class__ but is not one."""

    @property
    def __class__(self) -> type:  # pyright: ignore[reportIncompatibleMethodOverride]
        return str


class _LyingStr(str):
    """A str subclass whose __str__ and strip return unrelated text."""

    def __str__(self) -> str:
        return "lie from __str__"

    def strip(self, chars: str | None = None) -> str:
        return "lie from strip"


def _make(
    scope_guidance: object,
    seed_areas: object,
    systems_of_record: object = None,
) -> PromptSlots:
    return PromptSlots(
        scope_guidance=cast(str, scope_guidance),
        seed_areas=cast(str, seed_areas),
        systems_of_record=cast(str | None, systems_of_record),
    )


def _make_with(**overrides: object) -> PromptSlots:
    values = {**VALID, **overrides}
    return _make(values["scope_guidance"], values["seed_areas"], values["systems_of_record"])


def test_three_non_blank_strings_construct_stripped() -> None:
    """Three non-blank str values construct, each stored .strip()ped (AIE-1055, US1.1)."""
    slots = PromptSlots(
        scope_guidance="  shared org, private user \n",
        seed_areas="\tproduct, customers  ",
        systems_of_record=" Jira holds tickets.\n\n",
    )
    assert slots.scope_guidance == "shared org, private user"
    assert slots.seed_areas == "product, customers"
    assert slots.systems_of_record == "Jira holds tickets."


def test_systems_of_record_omitted_is_none() -> None:
    """Omitting systems_of_record leaves the field None (AIE-1055, US1.2)."""
    slots = PromptSlots(scope_guidance="a", seed_areas="b")
    assert slots.systems_of_record is None


def test_systems_of_record_none_is_none() -> None:
    """Passing systems_of_record=None leaves the field None (AIE-1055, US1.2)."""
    slots = PromptSlots(scope_guidance="a", seed_areas="b", systems_of_record=None)
    assert slots.systems_of_record is None


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
@pytest.mark.parametrize(
    ("bad", "type_name"),
    [
        (None, "NoneType"),
        (b"bytes", "bytes"),
        (42, "int"),
        pytest.param(_SpoofsStr(), "_SpoofsStr", id="spoofs"),
    ],
)
def test_required_field_wrong_type_raises_type_error(
    field: str, bad: object, type_name: str
) -> None:
    """A required field whose real type is not str raises TypeError (AIE-1055, US1.3)."""
    with pytest.raises(TypeError, match=f"^{re.escape(f'{field} must be str, not {type_name}')}$"):
        _make_with(**{field: bad})


@pytest.mark.parametrize(
    ("bad", "type_name"),
    [
        (b"bytes", "bytes"),
        (42, "int"),
        pytest.param(_SpoofsStr(), "_SpoofsStr", id="spoofs"),
    ],
)
def test_systems_of_record_wrong_type_raises_type_error(bad: object, type_name: str) -> None:
    """systems_of_record neither str nor None raises TypeError (AIE-1055, US1.4)."""
    expected = f"systems_of_record must be str or None, not {type_name}"
    with pytest.raises(TypeError, match=f"^{re.escape(expected)}$"):
        _make_with(systems_of_record=bad)


@pytest.mark.parametrize("field", FIELDS)
def test_str_subclass_normalized_to_exact_str(field: str) -> None:
    """A lying str subclass is stored as exact str via str.__str__ then str.strip
    (AIE-1055, US1.5).
    """
    slots = _make_with(**{field: _LyingStr("  real text \n")})
    stored = getattr(slots, field)
    assert type(stored) is str
    assert stored == "real text"


@pytest.mark.parametrize("field", FIELDS)
def test_surrounding_whitespace_is_stripped(field: str) -> None:
    """'  text\\n' is stored as 'text' (AIE-1055, US1.6)."""
    slots = _make_with(**{field: "  text\n"})
    assert getattr(slots, field) == "text"


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_blank_field_raises_value_error(field: str, blank: str) -> None:
    """Empty or whitespace-only text raises ValueError (AIE-1055, US1.7)."""
    expected = f"{field} must not be empty or whitespace-only"
    with pytest.raises(ValueError, match=f"^{re.escape(expected)}$"):
        _make_with(**{field: blank})


@pytest.mark.parametrize("field", FIELDS)
def test_lone_surrogate_raises_value_error_from_unicode_error(field: str) -> None:
    """A lone surrogate raises ValueError caused by UnicodeEncodeError (AIE-1055, US1.8)."""
    expected = f"{field} must be encodable as UTF-8"
    with pytest.raises(ValueError, match=f"^{re.escape(expected)}$") as exc_info:
        _make_with(**{field: "a\ud800b"})
    assert isinstance(exc_info.value.__cause__, UnicodeEncodeError)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"scope_guidance": "   ", "seed_areas": 42}, "seed_areas must be str, not int"),
        (
            {"scope_guidance": "", "systems_of_record": b"x"},
            "systems_of_record must be str or None, not bytes",
        ),
        (
            {"seed_areas": "a\ud800b", "systems_of_record": 7},
            "systems_of_record must be str or None, not int",
        ),
    ],
)
def test_type_checks_run_before_value_checks(overrides: dict[str, object], expected: str) -> None:
    """A later wrong type wins over an earlier bad value (AIE-1055, US1.9)."""
    with pytest.raises(TypeError, match=f"^{re.escape(expected)}$"):
        _make_with(**overrides)


@pytest.mark.parametrize(
    ("overrides", "error", "expected"),
    [
        (
            {"scope_guidance": 1, "seed_areas": None},
            TypeError,
            "scope_guidance must be str, not int",
        ),
        (
            {"seed_areas": b"x", "systems_of_record": 3},
            TypeError,
            "seed_areas must be str, not bytes",
        ),
        (
            {"scope_guidance": None, "systems_of_record": 3},
            TypeError,
            "scope_guidance must be str, not NoneType",
        ),
        (
            {"scope_guidance": " ", "seed_areas": ""},
            ValueError,
            "scope_guidance must not be empty or whitespace-only",
        ),
        (
            {"seed_areas": "\n", "systems_of_record": "\t"},
            ValueError,
            "seed_areas must not be empty or whitespace-only",
        ),
        (
            {"scope_guidance": "a\ud800b", "seed_areas": "b\udfffc"},
            ValueError,
            "scope_guidance must be encodable as UTF-8",
        ),
        (
            {"seed_areas": "a\ud800b", "systems_of_record": ""},
            ValueError,
            "seed_areas must be encodable as UTF-8",
        ),
    ],
)
def test_first_bad_field_in_order_is_reported(
    overrides: dict[str, object], error: type[Exception], expected: str
) -> None:
    """With two bad fields of the same kind, the first in field order is named
    (AIE-1055, US1.10).
    """
    with pytest.raises(error, match=f"^{re.escape(expected)}$"):
        _make_with(**overrides)


@pytest.mark.parametrize("field", FIELDS)
def test_assignment_raises_frozen_instance_error(field: str) -> None:
    """Assigning to any field raises FrozenInstanceError (AIE-1055, US1.11)."""
    slots = _make_with()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(slots, field, "changed")


def test_equal_post_strip_text_is_equal_with_equal_hashes() -> None:
    """Slots built from equal post-strip text are equal and hash equal (AIE-1055, US1.12)."""
    a = PromptSlots(scope_guidance="  guide ", seed_areas="areas\n", systems_of_record="sor")
    b = PromptSlots(scope_guidance="guide", seed_areas="\tareas", systems_of_record=" sor ")
    assert a == b
    assert hash(a) == hash(b)


def test_equal_text_without_systems_of_record_is_equal_with_equal_hashes() -> None:
    """Slots with equal text and no systems_of_record are equal and hash equal
    (AIE-1055, US1.12).
    """
    a = PromptSlots(scope_guidance="guide", seed_areas="areas")
    b = PromptSlots(scope_guidance=" guide", seed_areas="areas ", systems_of_record=None)
    assert a == b
    assert hash(a) == hash(b)


@pytest.mark.parametrize("term", ["shared", "private", "system/"])
def test_docstring_states_vocabulary_contract(term: str) -> None:
    """The class docstring names the generic scope vocabulary (AIE-1055, US1.13)."""
    assert PromptSlots.__doc__ is not None
    assert term in PromptSlots.__doc__


def test_docstring_says_slots_state_only_deployment_facts() -> None:
    """The class docstring says slots carry only deployment facts (AIE-1055, US1.13;
    AIE-1165, US3.5).
    """
    assert PromptSlots.__doc__ is not None
    assert "Slots state only deployment facts" in re.sub(r"\s+", " ", PromptSlots.__doc__)
