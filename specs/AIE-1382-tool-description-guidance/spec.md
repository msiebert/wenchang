Linear: AIE-1382

Allow-test-changes: update (not weaken or remove) existing tests to the new MCP contract: `tests/test_mcp_server.py::test_descriptions_equal_tool_descriptions` (served descriptions now equal `mcp_tool_descriptions(slots, product)`, and read_file/list_prefix/delete_file still equal `tool_descriptions(product)`); `tests/test_mcp_server.py::test_description_first_lines_name_the_product` (the first line is now the preamble; the assertion moves to the first line of the mechanics text after the preamble); `tests/test_mcp_server.py::test_module_exports_and_keyword_only_parameters` (the `__all__` list gains the new public names); and the `_text` helper and any test that asserts a successful `get_memory_index` result has exactly one content block (now two; error results keep one); `tests/test_prompts_invariants.py` `NON_SECTION_MODULES` (gains `"tool_guidance"`, a prompts-layer module that is not a prompt section; its text invariants move to `tests/test_tool_guidance.py`); `tests/test_mcp_observer_shared.py::test_mcp_all_is_unchanged` (asserts the new seven-name `__all__`); `tests/test_mcp_server.py::test_register_on_adopter_server` (compares against `mcp_tool_descriptions(None, product)`); and `tests/test_evals_server.py::test_tool_surface_is_memory_tools_plus_harness` (compares served descriptions against `mcp_tool_descriptions`). Each is updated to the new contract and not weakened. No test is deleted or skipped.

# Feature Specification: Core memory guidance in MCP tool descriptions and the index result

**Linear issue**: AIE-1382 — Put core memory guidance in MCP tool descriptions for clients that drop instructions

**Feature Branch**: `AIE-1382-tool-description-guidance`

**Created**: 2026-11-12

**Status**: Draft

**Input**: Claude Desktop and claude.ai drop the MCP `instructions` field
(anthropics/claude-code#43749, anthropics/claude-ai-mcp#93). Claude Code
reportedly truncates instructions at about 2 KB (unverified) and tool
descriptions at 2048 characters (anthropics/claude-code#41593). claude.ai "Auto"
tool mode defers connector tools until the model searches, so descriptions may
not be in context up front. Tool results have no practical cap, but Desktop
reads only a result's `content`, not `structuredContent`. wenchang's memory
prompt (`build_memory_prompt(slots)`, about 11.2k characters, 11 sections) is
today served only as `instructions` and the `wenchang://memory-prompt`
resource, so those clients never see it.

## Summary

- The `get_memory_index` MCP result carries the full memory prompt as a second
  text content block (success only).
- MCP tool descriptions gain a short behavioral preamble ahead of the existing
  mechanics text:
  - `get_memory_index`: the adopter's `slots.purpose`, then a call-first
    sentence that points at the rules in the result.
  - `write_file`, `append_line`, `replace_fact`: one shared preamble (scope
    pointer, confidence labels, save-as-it-arises, the never-store refusals).
  - `read_file`, `list_prefix`, `delete_file`: unchanged.
- Guidance text lives in a new prompts-layer module
  `src/wenchang/prompts/tool_guidance.py`. `wenchang.mcp` gains
  `mcp_tool_descriptions(slots, product)` and `MAX_TOOL_DESCRIPTION_CHARS`.
  `register_memory_tools` gains `slots`. A served description over 2000
  characters raises `ValueError` before anything is registered.
- Unchanged: the `instructions` field and the resource (byte for byte),
  `tool_descriptions(product)`, `MemoryTools.descriptions()`, `MemoryTools`,
  `MemoryIndex`, and the non-MCP API. Always on; no flag; no new `PromptSlots`
  field.

Out of scope: measuring whether models obey call-first (a live `/run-evals` pass
after merge), changing the memory prompt text, truncating or summarizing
`scope_guidance`, and any client-specific behavior.

## User scenarios

1. **Desktop user with a connector that drops instructions.** The model sees the
   write tools' descriptions (labels, save-now, refusals) and the index tool's
   description (purpose, call first). After calling the index, the full rules
   are in the result's `content`.
2. **Adopter integrating a server.** Passes `slots` as before; descriptions
   derive from them with no extra configuration. A very long `purpose` fails at
   startup with a clear message instead of being silently truncated by a client.
3. **Non-MCP integrator.** Still uses `tool_descriptions(product)` and owns the
   system prompt; nothing changes.

## Acceptance criteria

Tests are unit tests unless noted and cite `AIE-1382`.

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | A server built with slots (and optional product) | `tools/list` | `get_memory_index` contains `slots.purpose`, the call-first sentence, and the "result includes" rules sentence; each of `write_file`, `append_line`, `replace_fact` contains the scope pointer (to the Scopes rules in the index result), `[stated]`, `[observed]`, `[inferred]`, "never write a new `[system]` line", save-as-they-arise / never offer to save later, and the financial-account / health-diagnosis / minor refusal; `read_file`, `list_prefix`, `delete_file` equal `tool_descriptions(product)` |
| 2 | The same server | `tools/list` | In each changed description the preamble comes first, then a blank line, then the existing `tool_descriptions(product)[name]` text verbatim |
| 3 | Any slots with a normal-length purpose | Descriptions are built | Every served description is at most `MAX_TOOL_DESCRIPTION_CHARS` (2000); with `evals/reference_adopter.py` `REFERENCE_SLOTS` each is under 1600 |
| 4 | A `purpose` long enough that a description exceeds 2000 | `build_server` or `register_memory_tools` | `ValueError` naming the tool, its length, and the limit; nothing registered (no tools, no resource) |
| 5 | A successful `get_memory_index` call | The result is read | `content` has two `TextContent` blocks: the JSON payload, then the prompt, equal to `memory_instructions(slots)`; `structured_content` and the `on_call` payload are unchanged |
| 6 | A `get_memory_index` call that fails, and any other tool call | The result is read | `content` has exactly one block, as before |
| 7 | A server built with slots | `server.instructions` and the `wenchang://memory-prompt` resource are read | Both equal `memory_instructions(slots)` byte for byte; existing tests for them pass unchanged |
| 8 | Two different `PromptSlots` | Descriptions are built for each | The `get_memory_index` description differs and shows each purpose; no reference-adopter text appears except via `REFERENCE_SLOTS`; with `slots=None` the index description uses the generic sentence and contains no purpose |
| 9 | `tool_descriptions(product)` and `MemoryTools.descriptions()` | Called | Return exactly what they returned before the change |
| 10 | The stdio server (`tests/test_mcp_stdio.py`) | The client lists tools and calls `get_memory_index` | Listed descriptions carry the guidance (AC1) and the index result has the prompt as its second block |
| 11 | The change | `make check` | Passes |
| 12 | The docs | ADR 0048, ARCHITECTURE.md MCP adapter section, README MCP section, site pages, CHANGELOG | Updated and consistent with the above (see `tasks.md` T4) |

## Functional requirements

- **FR-001**: `wenchang.mcp.mcp_tool_descriptions(slots: PromptSlots | None = None,
  product: str | None = None) -> Mapping[str, str]` MUST return a read-only
  mapping in `TOOL_NAMES` order: preamble, blank line, `tool_descriptions(product)[name]`
  for the four tools with a preamble; `tool_descriptions(product)[name]` for the rest.
- **FR-002**: The shared write-tool preamble MUST NOT contradict
  `src/wenchang/prompts/remembering.py` or `privacy.py`, and MUST NOT contain
  scope guidance text; description length MUST NOT depend on `scope_guidance`.
- **FR-003**: `register_memory_tools` and `build_server` MUST validate lengths
  before registering any tool or resource.
- **FR-004**: The second content block MUST be the same `prompt` string
  `register_memory_tools` already receives.

## Assumptions

- The `prompt` passed to `register_memory_tools` equals
  `memory_instructions(slots)` for the `slots` passed alongside it. If an
  adopter passes unrelated values, the descriptions follow `slots` and the
  index block follows `prompt`; this is not checked.
- Models that see both `instructions` and the new text get the same rules twice;
  repetition, not contradiction.
- `MAX_TOOL_DESCRIPTION_CHARS = 2000` leaves margin under the 2048-character
  truncation reported for Claude Code.

## Resolved at design review

- Always on, no opt-in flag: accepted.
- Scope guidance reaches the model via the index result, not descriptions:
  accepted.
- Fail at startup on an over-long description: accepted.
