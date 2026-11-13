# Implementation Plan: Core memory guidance in tool descriptions and the index result (AIE-1382)

Linear: AIE-1382. Spec: `spec.md`. Detailed enough to write tests without
reading `src/`.

## Public interface

### `wenchang.prompts.tool_guidance` (new, `src/wenchang/prompts/tool_guidance.py`)

Not re-exported from `wenchang.prompts` (import the module directly:
`from wenchang.prompts import tool_guidance`). `wenchang.prompts.__all__` is
unchanged.

```python
GET_MEMORY_INDEX_CALL_FIRST: Final[str]  # fixed sentence after the purpose
GET_MEMORY_INDEX_GENERIC: Final[str]  # used when slots is None; no purpose
WRITE_PREAMBLE: Final[str]  # shared by write_file, append_line, replace_fact (~430 chars)

PREAMBLE_TOOLS: Final[tuple[str, ...]] = (
    "get_memory_index",
    "write_file",
    "append_line",
    "replace_fact",
)


def tool_preambles(slots: PromptSlots | None) -> Mapping[str, str]:
    """Preamble text by tool name, for the tools in PREAMBLE_TOOLS only. Read-only."""
```

Contents:

- `get_memory_index` preamble with slots: `slots.purpose` (already stripped by
  `PromptSlots`), a space, then `GET_MEMORY_INDEX_CALL_FIRST`: "When that
  applies, call this first in the conversation, before answering from memory or
  writing to it. Its result includes your memory rules (scopes, confidence
  labels, what never to store); follow them."
- `get_memory_index` preamble with `slots=None`: `GET_MEMORY_INDEX_GENERIC`, a
  similar sentence that does not begin "When that applies" and contains no
  purpose (for example "Call this first in the conversation, before answering
  from memory or writing to it. Its result includes ...").
- `WRITE_PREAMBLE` covers, in about 430 characters: choose the scope by the
  Scopes rules in the `get_memory_index` result; give every fact line a label
  `[stated]` (the user told you), `[observed]` (seen in a tool result or
  behavior), or `[inferred]` (concluded from a pattern), and never write a new
  `[system]` line; save each fact as it arises, before replying, and never offer
  to save it later; one sentence: never store financial account numbers, health
  diagnoses, or anything indicating the user is a minor, even if asked. It uses
  the same backtick-quoted label forms as `remembering.py`.
- The function reads no `scope_guidance`, `seed_areas`, or
  `systems_of_record`.

### `wenchang.mcp` (changed)

```python
MAX_TOOL_DESCRIPTION_CHARS: Final[int] = 2000


def mcp_tool_descriptions(
    slots: PromptSlots | None = None, product: str | None = None
) -> Mapping[str, str]:
    """Descriptions as served over MCP: preamble + blank line + tool_descriptions(product)[name]."""
```

- Keys are exactly `TOOL_NAMES`, in `TOOL_NAMES` order; the mapping is
  read-only (assignment raises `TypeError`).
- For a name in `PREAMBLE_TOOLS`: `f"{preamble}\n\n{tool_descriptions(product)[name]}"`.
  For the others: `tool_descriptions(product)[name]` unchanged.
- `product` is validated as `tool_descriptions` validates it (same errors).
- Does not enforce the length limit; the length check is in registration.

`__all__` becomes (sorted as today):

```python
[
    "MAX_TOOL_DESCRIPTION_CHARS",
    "PROMPT_RESOURCE_URI",
    "ToolCallRecord",
    "build_server",
    "mcp_tool_descriptions",
    "memory_instructions",
    "register_memory_tools",
]
```

`register_memory_tools` gains a keyword-only parameter, placed after `product`:

```python
def register_memory_tools(
    server: MCPServer,
    *,
    prompt: str,
    client,
    resolver,
    policy,
    credentials_from_context,
    source: str,
    product: str | None = None,
    slots: PromptSlots | None = None,
    tool_prefix: str | None = None,
    on_call: ToolCallObserver | None = None,
) -> None: ...
```

Behavior:

- Served descriptions are `mcp_tool_descriptions(slots, product)`.
- Before registering anything (same point as the other argument checks, so no
  tool and no resource exists after the failure): any description longer than
  `MAX_TOOL_DESCRIPTION_CHARS` raises `ValueError`. The message names the tool
  (the unprefixed `TOOL_NAMES` name), the length, and the limit, for example
  `tool description for get_memory_index is 2143 characters; the limit is 2000
  (shorten PromptSlots.purpose)`. Tests match on the tool name, the number, and
  `2000`, not on the full sentence.
- `build_server(..., slots=slots, ...)` passes `slots` through; its signature is
  unchanged (it already takes `slots`).
- `get_memory_index` MCP wrapper, on success only: `CallToolResult.content` is
  `[TextContent(type="text", text=json.dumps(payload)), TextContent(type="text", text=prompt)]`.
  `structured_content` is still `payload`, `is_error` is `False`, and the
  `on_call` observer receives the same payload as before. Error results and
  every other tool: one block, as before.
- `instructions` and the resource are untouched.

### Unchanged

`wenchang.tools.tool_descriptions(product)`, `MemoryTools.descriptions()`,
`MemoryTools`, `MemoryIndex`, `exported_tool_schemas` and its descriptions
(`tests/test_schemas.py` stays as is), `memory_instructions(slots)`,
`PromptSlots`.

## Length budget

Preamble plus existing description must stay under 2000 characters. The write
tools' preamble is fixed (~430), so their length does not depend on adopter
text. The index description grows with `purpose`; with `REFERENCE_SLOTS` every
description is under 1600 (the test pins this as the headroom check).

## Placement rationale

Guidance text is prompt content, so it lives in `wenchang.prompts` next to the
sections it must agree with. `wenchang.mcp` only composes it with the tool
mechanics text and enforces the transport's length limit. No dependency from
`wenchang.tools` on the new module.

## Tests

- `tests/test_tool_guidance.py` (unit): `tool_preambles` content, `slots=None`
  vs slots, two different slots, no reference-adopter text hardcoded (AC1, AC8).
- `tests/test_mcp_server.py`: updated tests per `Allow-test-changes`; new tests
  for AC2 to AC7, AC9.
- `tests/test_mcp_stdio.py`: extended for AC10.
- Tests that call `get_memory_index` and use `_text` must read the first block
  (the helper changes for the index; other tools keep the one-block assertion).

## Constraints surfaced from the code

- `test_module_exports_and_keyword_only_parameters` pins `__all__` exactly; it
  changes with the new names. `register_memory_tools` parameters after `server`
  stay keyword-only.
- `test_description_first_lines_name_the_product` asserts "Mixpanel" in each
  description's first line. A preamble-first description has the preamble on
  line one, so the assertion applies to the mechanics text after the preamble.
- `register_memory_tools` already warns when `server.instructions` does not
  include `prompt`; that stays.
