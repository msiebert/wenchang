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
    "private scope", and "the `system/` area"; the scope slots map that
    vocabulary onto the adopter's deployment. Slots state only deployment
    facts; the generic sections already say that areas are extensible, what
    the `system/` area means, and that systems of record are never copied.

    - ``purpose``: one or two sentences naming the product and when to use
      memory.
    - ``scope_guidance``: which scopes exist, which are shared and which are
      private, who may write to each, and any ask-before-write,
      contradiction, containment, or scope-test rules, with examples.
    - ``seed_areas``: starting area names per scope, as lowercase ASCII
      slugs, and which scopes have a ``system/`` area.
    - ``systems_of_record``: optional; which systems hold canonical
      information and how to refer to their objects. None omits the whole
      systems-of-record section.

    Scope priority is not a slot; it is ``MemoryStore(scope_priority=...)``.
    Values are stored stripped as exact ``str``.
    """

    purpose: str
    scope_guidance: str
    seed_areas: str
    systems_of_record: str | None = None

    def __post_init__(self) -> None:
        for field in ("purpose", "scope_guidance", "seed_areas"):
            v = cast(object, getattr(self, field))
            if not issubclass(type(v), str):
                raise TypeError(f"{field} must be str, not {_type_name(type(v))}")
        sor = cast(object, self.systems_of_record)
        if sor is not None and not issubclass(type(sor), str):
            raise TypeError(f"systems_of_record must be str or None, not {_type_name(type(sor))}")

        for field in ("purpose", "scope_guidance", "seed_areas", "systems_of_record"):
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
