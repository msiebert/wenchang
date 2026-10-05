"""Adopter-supplied text slots for the memory system prompt."""

from dataclasses import dataclass
from typing import cast


def _type_name(t: type) -> str:
    # A metaclass may make __name__ raise or return a str subclass.
    try:
        return str.__str__(t.__name__)
    except Exception:
        return "<unnamed>"


@dataclass(frozen=True)
class PromptSlots:
    """Adopter-specific text inserted into the generic memory prompt.

    The generic sections refer to scope shape only as "shared scope",
    "private scope", and "the `system/` area"; these slots map that vocabulary
    onto the adopter's deployment.

    - ``scope_guidance``: which of the adopter's scopes are shared and which
      are private, plus any ask-before-write, contradiction, or containment
      rules, with examples.
    - ``seed_areas``: starting areas per scope as lowercase ASCII slugs,
      marking the curated ``system/`` areas (read-only to the agent) apart
      from agent-writable ones, presented as an extensible list.
    - ``systems_of_record``: optional; None omits the whole
      systems-of-record section.

    Scope priority is not a slot; it is ``MemoryStore(scope_priority=...)``.
    Values are stored stripped as exact ``str``.
    """

    scope_guidance: str
    seed_areas: str
    systems_of_record: str | None = None

    def __post_init__(self) -> None:
        for field in ("scope_guidance", "seed_areas"):
            v = cast(object, getattr(self, field))
            if not issubclass(type(v), str):
                raise TypeError(f"{field} must be str, not {_type_name(type(v))}")
        sor = cast(object, self.systems_of_record)
        if sor is not None and not issubclass(type(sor), str):
            raise TypeError(f"systems_of_record must be str or None, not {_type_name(type(sor))}")

        for field in ("scope_guidance", "seed_areas", "systems_of_record"):
            v = cast(str | None, getattr(self, field))
            if v is None:
                continue
            # str.__str__ and str.strip bypass overrides on str subclasses.
            value = str.strip(str.__str__(v))
            if not value:
                raise ValueError(f"{field} must not be empty or whitespace-only")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError(f"{field} must be encodable as UTF-8") from exc
            object.__setattr__(self, field, value)
