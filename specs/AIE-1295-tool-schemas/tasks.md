# Tasks: AIE-1295 Export tool input/output schemas

Build order: rebase onto a main containing PRs #53, #54, #56 first.

- [ ] T001 (implementer, before T002) Add `jsonschema>=4.20` and `types-jsonschema>=4.20` to the `dev` group in `pyproject.toml`; `uv lock`; `uv sync`.
- [ ] T002 (test-writer) `tests/snapshots/tool_schemas.json` by hand from plan.md "Exact schemas" (per-tool `input`/`output` plus one `error`; no descriptions); `tests/test_schemas.py` for US1, US2.1, US3, US4 (including the `FileQuotaExceededError` fixture from PR #54); `tests/test_schemas_mcp.py` for US2.2. Confirm they fail with `ModuleNotFoundError: wenchang.schemas`.
- [ ] T003 (implementer) `src/wenchang/schemas.py` per plan.md until T002's tests pass; `make check` green.
- [ ] T004 (doc-updater) ADR 0042 (including the adopter-subclass stance and follow-ups: pydantic generator, MCP `outputSchema`), ARCHITECTURE.md (`schemas` module entry, pointer from `tools`), README adopter snippet, `review-pr.md`.
- [ ] T005 (general-purpose; the role agents' scopes exclude `site-src/`) Docs-site section on `wenchang.schemas` per plan.md "Docs site"; regenerate with `uv run scripts/build_site.py`; commit `site-src/` and the regenerated `site/` together.
- [ ] T006 (lead) `make check`; commit with `AIE-1295`.
