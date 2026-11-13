"""Guidance prepended to the descriptions of the tools an agent calls first or writes with."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from wenchang.prompts.slots import PromptSlots

GET_MEMORY_INDEX_CALL_FIRST: Final[str] = """\
When that applies, call this first in the conversation, before answering from memory or writing to
it. Its result includes your memory rules (scopes, confidence labels, what never to store); follow
them."""
GET_MEMORY_INDEX_GENERIC: Final[str] = """\
Call this first in a conversation that uses this memory, before answering from memory or writing to
it. Its result includes your memory rules (scopes, confidence labels, what never to store); follow
them."""
WRITE_PREAMBLE: Final[str] = """\
Choose the scope by the Scopes rules in the get_memory_index result. Give every fact line a
confidence label: `[stated]` (the user told you), `[observed]` (seen in a tool result or behavior),
or `[inferred]` (concluded from a pattern); never write a new `[system]` line. Save each fact as it
arises, before replying; never offer to save it later. Never store financial account numbers, health
diagnoses, or anything indicating the user is a minor, even if asked."""

PREAMBLE_TOOLS: Final[tuple[str, ...]] = (
    "get_memory_index",
    "write_file",
    "append_line",
    "replace_fact",
)


def tool_preambles(slots: PromptSlots | None) -> Mapping[str, str]:
    """Preamble text by tool name, for the tools in PREAMBLE_TOOLS only. Read-only."""
    index = (
        GET_MEMORY_INDEX_GENERIC
        if slots is None
        else f"{slots.purpose} {GET_MEMORY_INDEX_CALL_FIRST}"
    )
    return MappingProxyType(
        {name: index if name == "get_memory_index" else WRITE_PREAMBLE for name in PREAMBLE_TOOLS}
    )
