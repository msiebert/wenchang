"""Assembly of the memory system prompt from section modules and adopter slots."""

from collections.abc import Callable, Mapping
from typing import Final, cast

from wenchang.prompts import (
    applying_memory,
    curated_content,
    filing,
    forgetting,
    overview,
    privacy,
    remembering,
    systems_of_record,
    write_mechanics,
)
from wenchang.prompts.slots import PromptSlots

SECTION_ORDER: Final[tuple[str, ...]] = (
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
SCOPE_GUIDANCE_HEADING: Final[str] = "Scopes"
SEED_AREAS_HEADING: Final[str] = "Seed areas"


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


def _overview(slots: PromptSlots) -> tuple[str, str]:
    parts = [slots.purpose, overview.BODY.strip()]
    return overview.HEADING, "\n\n".join(p for p in parts if p)


def _systems_of_record(slots: PromptSlots) -> tuple[str, str]:
    if slots.systems_of_record is None:
        return systems_of_record.HEADING, ""
    body = systems_of_record.PRINCIPLE.strip() + "\n\n" + slots.systems_of_record
    return systems_of_record.HEADING, body


# Generic sections read HEADING and BODY at call time so module edits take effect.
_SECTIONS: Final[Mapping[str, Callable[[PromptSlots], tuple[str, str]]]] = {
    "overview": _overview,
    "scope_guidance": lambda s: (SCOPE_GUIDANCE_HEADING, s.scope_guidance),
    "seed_areas": lambda s: (SEED_AREAS_HEADING, s.seed_areas),
    "systems_of_record": _systems_of_record,
    "applying_memory": lambda _: (applying_memory.HEADING, applying_memory.BODY),
    "remembering": lambda _: (remembering.HEADING, remembering.BODY),
    "privacy": lambda _: (privacy.HEADING, privacy.BODY),
    "filing": lambda _: (filing.HEADING, filing.BODY),
    "write_mechanics": lambda _: (write_mechanics.HEADING, write_mechanics.BODY),
    "curated_content": lambda _: (curated_content.HEADING, curated_content.BODY),
    "forgetting": lambda _: (forgetting.HEADING, forgetting.BODY),
}

if tuple(_SECTIONS) != SECTION_ORDER:
    raise RuntimeError("_SECTIONS keys must match SECTION_ORDER")


def build_memory_prompt(slots: PromptSlots, /) -> str:
    """Return the memory system prompt: one `## heading` section per non-empty body."""
    slots_type = type(cast(object, slots))
    if not issubclass(slots_type, PromptSlots):
        raise TypeError(f"slots must be PromptSlots, not {_type_name(slots_type)}")
    parts: list[str] = []
    for section_id in SECTION_ORDER:
        heading, body = _SECTIONS[section_id](slots)
        body = body.strip()
        if body:
            parts.append(f"## {heading}\n\n{body}")
    return "\n\n".join(parts) + "\n"
