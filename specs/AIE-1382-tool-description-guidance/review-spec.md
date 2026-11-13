# Spec Review: AIE-1382 — Core memory guidance in tool descriptions and the index result

## What & why

Claude Desktop and claude.ai drop the MCP `instructions` field, so their models
never see wenchang's memory rules. This puts the essentials where those clients
do look: a short behavioral preamble on the index and write tool descriptions,
and the full memory prompt as a second block in the `get_memory_index` result.
Always on; `instructions` and the resource stay exactly as they are.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | Server with slots | `tools/list` | Index description: purpose + call-first + "result includes" rules. Write tools: scope pointer, three labels, no new `[system]`, save now, refusals. Other three tools unchanged |
| 2 | Same | Read descriptions | Preamble, blank line, existing text verbatim |
| 3 | Normal slots | Build | Each description at most 2000 chars; under 1600 with reference slots |
| 4 | Over-long purpose | Start server | `ValueError` (tool, length, limit); nothing registered |
| 5 | Successful index call | Read result | Second text block equals the prompt; `structured_content` and `on_call` payload unchanged |
| 6 | Error result or other tool | Read result | One block |
| 7 | Server | Read `instructions` / resource | Byte-identical to before |
| 8 | Two different slots; `slots=None` | Build descriptions | Purpose follows slots; generic sentence when none; nothing hardcoded |
| 9 | Non-MCP API | Call `tool_descriptions`, `MemoryTools.descriptions()` | Unchanged |
| 10 | Stdio server | List tools, call index | Guidance in descriptions; prompt in second block |
| 11-12 | Change | `make check`; docs | Pass; ADR 0048, ARCHITECTURE, README, site, CHANGELOG updated |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Full prompt in the index result's `content` | Separate `get_instructions` tool; relying on resources/prompts | Results have no practical cap; Desktop reads `content`; no extra tool or client support needed |
| Short fixed preambles; purpose first on the index tool | Copy `scope_guidance` into descriptions; new short-scope slot; fail on long scope text | Scope text pushes past 2048 with the reference text; purpose is what tool search matches; no new slot |
| Shared ~430-char write preamble, wording aligned to remembering/privacy | Per-tool bespoke text | One place to keep consistent with the prompt |
| `ValueError` at startup above 2000 chars | Silent client truncation | Fails loudly, margin under 2048 |
| Guidance in `prompts/tool_guidance.py`; composition in `wenchang.mcp` | Edit `tool_descriptions` | Non-MCP integrators own their system prompt; core unchanged |
| Always on | Opt-in flag | Clients that drop instructions are the common case; text is non-contradictory |

## Files/modules to be touched

- `src/wenchang/prompts/tool_guidance.py` (new)
- `src/wenchang/mcp.py` (`mcp_tool_descriptions`, `MAX_TOOL_DESCRIPTION_CHARS`, `slots`, index block, length check)
- `tests/test_tool_guidance.py` (new); `tests/test_mcp_server.py`, `tests/test_mcp_stdio.py` (updated per `Allow-test-changes`)
- Docs: ADR 0048, `ARCHITECTURE.md`, `README.md`, `site-src/` pages, `CHANGELOG.md`

## Open questions / assumptions

- Whether models actually obey call-first is unmeasured; suggest a live `/run-evals` pass after merge.
- Claude Desktop deferred tool loading and the Claude Code limits (2 KB instructions, 2048 descriptions) are reported, not verified.
- Assumes `prompt` and `slots` passed to `register_memory_tools` correspond; not checked.
- Existing test `test_description_first_lines_name_the_product` and the `__all__` pin must change (listed in `Allow-test-changes`).

## Risks

- Duplication for clients that also inject `instructions`: same text, so repetitive, not contradictory.
- Token cost: about 2.8k extra tokens per index call.
- A very long `purpose` now fails startup for existing adopters (only if it pushes the index description past 2000).
