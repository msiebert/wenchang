# Tasks: AIE-1382 tool-description guidance

Tests first; implementation never edits `tests/`. Run `make check` at the end.
Site edits (`site-src/`) go to a general-purpose agent, not doc-updater.

- [ ] T1 — Descriptions: guidance module, `mcp_tool_descriptions`,
  registration, length check.
  - test-writer: `tests/test_tool_guidance.py` and updates and additions in
    `tests/test_mcp_server.py` (updates covered by `Allow-test-changes`).
  - implementer: `src/wenchang/prompts/tool_guidance.py`;
    `mcp_tool_descriptions` and `MAX_TOOL_DESCRIPTION_CHARS` in
    `src/wenchang/mcp.py`; `slots` keyword on `register_memory_tools`;
    `build_server` passes slots; pre-registration length check.
  - Given a server built with slots, When `tools/list`, Then the index
    description has purpose + call-first + "result includes" rules, and each
    write tool has the scope pointer, the three labels, never-write-`[system]`,
    save-as-they-arise, and the refusal sentence (AC1).
  - Given the same server, When descriptions are read, Then preamble, blank
    line, existing text verbatim for the four tools; the other three equal
    `tool_descriptions(product)` (AC1, AC2).
  - Given normal slots, Then every description is at most 2000, and under 1600
    with `REFERENCE_SLOTS` (AC3).
  - Given an over-long purpose, When `build_server` or `register_memory_tools`,
    Then `ValueError` naming tool, length, limit; nothing registered (AC4).
  - Given two different `PromptSlots` and `slots=None`, Then purpose text
    follows the slots and the generic sentence has none (AC8).
  - Given the change, Then `tool_descriptions` and `MemoryTools.descriptions()`
    are unchanged and `instructions` and the resource are byte-identical (AC7,
    AC9).
- [ ] T2 — Index result: second content block.
  - test-writer: tests in `tests/test_mcp_server.py` (update `_text` use for the
    index).
  - implementer: `get_memory_index` wrapper in `src/wenchang/mcp.py`.
  - Given a successful `get_memory_index`, When read, Then two `TextContent`
    blocks (JSON payload, then `memory_instructions(slots)`), `structured_content`
    and the `on_call` payload unchanged (AC5).
  - Given a failing index call or any other tool, Then one block (AC6).
- [ ] T3 — Stdio end to end.
  - test-writer: extend `tests/test_mcp_stdio.py`.
  - Given the stdio server, When the client lists tools and calls
    `get_memory_index`, Then listed descriptions carry the guidance and the
    result's second block is the prompt (AC10).
- [ ] T4 — Docs (after implementation; AC12).
  - doc-updater: ADR `docs/adr/0048-guidance-in-tool-descriptions-and-index-result.md`.
    Context: client gap and research (instructions dropped, truncation limits,
    deferred tool loading, Desktop reads `content` only). Decision: the two
    channels above. Alternatives rejected: copying `scope_guidance` into
    descriptions (over 2048 with the reference text), failing at startup on long
    scope text, a new short-scope slot, a separate `get_instructions` tool, an
    opt-in flag, relying on resources or prompts. Consequences: duplication for
    clients that also inject instructions (same text, so repetitive not
    contradictory); about 2.8k extra tokens per index call.
  - doc-updater: `ARCHITECTURE.md` MCP adapter section (descriptions, index
    result block, length check, `tool_guidance` module).
  - doc-updater: `docs/product/glossary.md` check (no new term expected);
    draft `review-pr.md`.
  - general-purpose agent: `README.md` MCP section; `site-src/` pages
    (`integrate-new-server.md`, `prompts.md`, `reference.md`), including advice
    to pick a descriptive connector display name; `CHANGELOG.md` `[Unreleased]`;
    then `uv run scripts/build_site.py`.
- [ ] T5 — `make check` green (AC11).
- [ ] T6 — After merge: a live `/run-evals` pass to measure call-first and
  label compliance on a client that drops instructions (follow-up, not a gate).
