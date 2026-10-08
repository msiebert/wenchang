# Tasks: Host-mounting smoke test (MCP server adapter)

**Linear issue**: AIE-1060 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task: write failing tests, run them and confirm the failure reason,
implement, re-run, `make check` green, commit `AIE-1060: <what>`.

## T1: `tool_descriptions`

- Covers US1.1 to US1.7.
- Tests: append to `tests/test_tools_descriptions.py`. No existing test
  changes.
- Implementation: `src/wenchang/tools.py`.

## T2: The `mcp` optional dependency and the import guard

- Covers US2.1 to US2.3.
- Depends on T1 only for ordering.
- Config: `uv add --optional mcp "mcp>=2.2,<3"` and
  `uv add --dev "mcp>=2.2,<3"`, then commit `uv.lock`.
- Tests: `tests/test_mcp_packaging.py`.
- Implementation: a `src/wenchang/mcp.py` skeleton holding the guarded
  import, `__all__`, and `PROMPT_RESOURCE_URI`.

## T3: `build_server` registration and startup checks

- Covers US3.1 to US3.13.
- Depends on T1 and T2.
- Tests: `tests/test_mcp_server.py`, the registration and schema section,
  driven by `mcp.client.Client`.
- Implementation: `src/wenchang/mcp.py`.

## T4: Prompt delivery

- Covers US4.1 to US4.6.
- Depends on T3.
- Tests: `tests/test_mcp_server.py`, the prompt section.
- Implementation: `src/wenchang/mcp.py`.

## T5: Per-call binding, forwarding, and rendering

- Covers US5.1 to US5.11.
- Depends on T3.
- Tests: `tests/test_mcp_server.py`, the call section. It uses a meta-keyed
  `credentials_from_context`, a two-user resolver, a counting resolver, and
  a raising transport client.
- Implementation: `src/wenchang/mcp.py`.

## T6: Stdio

- Covers US6.1.
- Depends on T5.
- Tests: `tests/test_mcp_stdio.py`, plus the `tests/mcp_stdio_server.py`
  helper script.
- Implementation: none expected.

## T7: Docs

- Covers US7.1 to US7.5.
- Files: ADR 0027, notes in ADRs 0022 and 0026, ARCHITECTURE.md, README,
  the glossary, and `review-pr.md`.
