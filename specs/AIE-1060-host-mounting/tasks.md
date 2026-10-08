# Tasks: Host-mounting smoke test (MCP server adapter)

**Linear issue**: AIE-1060 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task follows the same loop:

1. Write the failing tests.
2. Run them and confirm they fail for the right reason.
3. Implement.
4. Re-run the tests.
5. Get `make check` green.
6. Commit as `AIE-1060: <what>`.

## T1: `tool_descriptions`

- **Covers:** US1.1 to US1.7.
- **Tests:** appended to `tests/test_tools_descriptions.py`; no existing
  test changes.
- **Implementation:** `src/wenchang/tools.py`.

## T2: Thread-safe `InMemoryStorage`

- **Covers:** US6.1 to US6.3.
- **Tests:** `tests/test_storage_memory_threads.py`.
- **Implementation:** `src/wenchang/storage/memory.py`.

## T3: `mcp` optional dependency and import guard

- **Covers:** US2.1 to US2.3.
- **Config:** `uv add --optional mcp "mcp>=2.2,<3"` and
  `uv add --dev "mcp>=2.2,<3"`, then commit `uv.lock`.
- **Tests:** `tests/test_mcp_packaging.py`.
- **Implementation:** a `src/wenchang/mcp.py` skeleton with the guarded
  import, `__all__`, and `PROMPT_RESOURCE_URI`.

## T4: Registration, validation, and startup checks

- **Covers:** US3.1 to US3.17.
- **Depends on:** T1 and T3.
- **Tests:** `tests/test_mcp_server.py`, registration, schema, and
  validation section.
- **Implementation:** `register_memory_tools`, `build_server`, and
  `_validate` in `src/wenchang/mcp.py`.

## T5: Prompt delivery

- **Covers:** US4.1 to US4.6.
- **Depends on:** T4.
- **Tests:** `tests/test_mcp_server.py`, prompt section.

## T6: Per-call binding, forwarding, rendering, and MCP-surface behavior

- **Covers:** US5.1 to US5.15.
- **Depends on:** T4.
- **Tests:** `tests/test_mcp_server.py`, calls section.

## T7: Concurrency through MCP

- **Covers:** US6.4 and US6.5.
- **Depends on:** T2 and T6.
- **Tests:** `tests/test_mcp_server.py`, concurrency section.

## T8: `on_call` observer

- **Covers:** US7.1 to US7.6.
- **Depends on:** T6.
- **Tests:** `tests/test_mcp_server.py`, observer section.

## T9: Stdio

- **Covers:** US8.1.
- **Depends on:** T6.
- **Tests:** `tests/test_mcp_stdio.py` and `tests/mcp_stdio_server.py`.

## T10: Docs

- **Covers:** US9.1 to US9.7.
- **Deliverables:**
  - ADR 0027.
  - Notes in ADRs 0003, 0022, and 0026.
  - Updates to ARCHITECTURE.md, the README, and the glossary.
  - review-pr.md.
