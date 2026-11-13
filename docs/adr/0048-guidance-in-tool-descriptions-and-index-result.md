# 0048. Guidance in MCP tool descriptions and the index result

Date: 2026-11-12

## Status

Accepted. Extends [ADR 0027](0027-mcp-host-adapter.md) (the MCP host adapter
serves the memory prompt as `instructions` and a resource) and builds on
[ADR 0025](0025-prompt-layer-sections-and-slots.md) (the prompt layer). This is
a workaround for a client gap, not a change to what the memory prompt says.

## Context

AIE-1382. wenchang's memory prompt (`build_memory_prompt(slots)`, about 11.2k
characters) reaches an agent today only through the MCP `instructions` field
and the `wenchang://memory-prompt` resource. Several clients do not deliver
either to the model:

- Claude Desktop and claude.ai drop the `instructions` field
  (anthropics/claude-code#43749, closed as a duplicate of #23808;
  anthropics/claude-ai-mcp#93 is open). Resources and MCP prompts are
  user-initiated in those clients, so the model does not read them on its own.
- Claude Code reportedly truncates `instructions` at about 2 KB (unverified; a
  sunpeak.ai post, Sep 2026) and truncates tool descriptions at 2048 characters
  (anthropics/claude-code#41593).
- claude.ai's Auto tool mode defers connector tools until the model searches
  for them, so descriptions may not be in context up front.
- Claude Desktop reads only a tool result's `content`, not `structuredContent`.
- Tool results have no practical size cap.

A model on those clients sees the tools but none of the rules: which scope to
write to, confidence labels, what never to store.

## Decision

Deliver the core rules through the two channels those clients do read: tool
descriptions and a tool result. It is always on, with no flag.

- **Index result carries the prompt.** A successful `get_memory_index` MCP
  result appends the full memory prompt (the `prompt` already passed to
  `register_memory_tools`) as a second `TextContent` block after the JSON
  payload. `structured_content` and the `on_call` payload are unchanged. Error
  results and every other tool keep one block.
- **Behavioral preambles in descriptions.** A new prompts-layer module,
  `wenchang.prompts.tool_guidance`, holds the preamble text and
  `tool_preambles(slots)`. `wenchang.mcp.mcp_tool_descriptions(slots, product)`
  composes `preamble + blank line + tool_descriptions(product)[name]` for four
  tools:
  - `get_memory_index`: `slots.purpose`, then a call-first sentence pointing at
    the rules in the result (a generic sentence when `slots` is `None`).
  - `write_file`, `append_line`, `replace_fact`: one shared `WRITE_PREAMBLE`:
    choose the scope by the Scopes rules in the index result, give each fact a
    `[stated]`, `[observed]`, or `[inferred]` label, never write a new
    `[system]` line, save facts as they arise and never offer to save later,
    and refuse financial account numbers, health diagnoses, and anything
    indicating a minor.
  - `read_file`, `list_prefix`, `delete_file` are unchanged.
- **Length limit enforced at registration.**
  `MAX_TOOL_DESCRIPTION_CHARS = 2000`, below the 2048 truncation reported for
  Claude Code. `register_memory_tools` (and so `build_server`) raises
  `ValueError` naming the tool, its length, and the limit before registering any
  tool or resource. `register_memory_tools` gains a keyword-only
  `slots: PromptSlots | None = None`; `build_server` passes its `slots`
  through.
- **Unchanged.** The `instructions` field and the `wenchang://memory-prompt`
  resource stay byte for byte. `tools.tool_descriptions(product)`,
  `MemoryTools.descriptions()`, `MemoryTools`, `MemoryIndex`, and the non-MCP
  API do not change; the preamble exists only in the MCP adapter's served text.
  The write preamble holds no adopter text, so write-tool description length
  does not depend on `scope_guidance`.

Rejected alternatives:

- **Copy `scope_guidance` into the write-tool descriptions.** The reference
  adopter's scope text pushes the write tools past 2048 characters, and the
  length would then depend on adopter text. The preamble points at the Scopes
  rules in the index result instead.
- **Fail at startup when scope text is long, or truncate or summarize it.**
  Only meaningful if scope text were in descriptions; it is not. Truncation
  would silently change adopter rules.
- **A new short-scope `PromptSlots` field.** Adds a required adopter concept and
  a second place to state scopes that can drift from `scope_guidance`.
- **A separate `get_instructions` tool.** A new tool the model must be told
  about, which is the same call-first problem the index description already
  solves, plus a larger tool surface.
- **An opt-in flag.** The affected clients cannot be detected by the server, and
  the cost of the default is small (below), so a flag would mostly stay off
  where it is needed.
- **Relying on MCP resources or prompts.** Those clients expose them to the
  user, not the model.

## Consequences

- A model on a client that drops `instructions` sees the labels, save-now rule,
  and refusals in the write tools' descriptions and the full rules in the index
  result, using only `content`.
- Clients that also inject `instructions` show the rules twice. The text is the
  same prompt, so the repetition is redundant, not contradictory.
- Each `get_memory_index` call returns about 2.8k more tokens (the prompt).
- A `purpose` long enough to push the index description past 2000 characters
  fails startup with a clear message instead of being silently truncated by a
  client. With the reference slots every description is under 1600.
- `register_memory_tools` assumes `prompt` is `memory_instructions(slots)` for
  the `slots` passed with it; a mismatch is not checked.
- The preamble tracks `remembering.py` and `privacy.py` by test, not by
  construction; a wording change there needs a matching change in
  `tool_guidance`.
- Whether models actually call the index first and follow the labels on these
  clients is unmeasured. A live `/run-evals` pass after merge is the follow-up.
- If clients start delivering `instructions` reliably, the preambles and the
  second block can be removed without touching the prompt layer's sections.
