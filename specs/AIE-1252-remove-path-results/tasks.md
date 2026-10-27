# Tasks: AIE-1252

Each group is test-first: test-writer writes failing tests (`tests/**` only), then implementer makes them pass (`src/**`, `evals/**`, `.claude/agents/wenchang-eval*.md`). Spec refs are `spec.md` user stories. Run `make check` at the end of each group that leaves the tree green; T1 and T2 may share a commit if the intermediate tree would be red.

## T1 - Render results without `path` (US1, US5)

- [ ] T1a test-writer: update `tests/test_tools_render.py` to the shapes in plan.md; add a recursive absence walk for `path` and `prefix`; capped rows exactly `{scope, area, omitted}`; malformed-path (`None` triple) and non-str-path (triple omitted) cases; `next_cursor` unchanged.
- [ ] T1b test-writer: update `tests/test_tools_end_to_end.py`, `tests/test_mcp_server.py` (text and structured content have no `path`/`prefix`), `tests/test_evals_server.py`, `tests/test_reference_adopter_end_to_end.py`. Do not touch `test_core_*.py`.
- [ ] T1c implementer: in `src/wenchang/tools.py` stop emitting `path` in `_file_fields` and `prefix` in `_capped_fields`; update the `get_memory_index` docstring.

## T2 - Errors without `path` (US2)

- [ ] T2a test-writer: error render tests (keys per kind, `scope/area/name`, no `path`), message-format tests for every error kind and reason including the unparseable-path fallback, `.path` attribute still set, `render_error` never raises.
- [ ] T2b implementer: `src/wenchang/errors.py` `_location` helper and new message text; `src/wenchang/tools.py` drop `path` from `_ERROR_FIELDS` and derive `scope`/`area`/`name` in `_wenchang_error_fields`.

## T3 - Prompt and eval agent file (US3)

- [ ] T3a test-writer: update `tests/test_prompts_overview.py` (new sentence, no backtick in it, no word `path`, no scenario facts) and the rendered-agent-file pin in `tests/test_evals_agent.py`.
- [ ] T3b implementer: edit `overview.BODY`; run `uv run python -m evals render-agent` to regenerate `.claude/agents/wenchang-eval.md`. Needs the implementer's `.claude/agents/wenchang-eval*.md` scope (see risk in review-spec).

## T4 - Eval reply-path check and scenarios (US4)

- [ ] T4a test-writer: delete the reply-path tests in `tests/test_evals_graders.py` and `tests/test_evals_report.py`; add report tests (no reply-path fields; old `grade.json` with `unmatched_reply_paths` loads and refreshes cleanly); add drivers with exact fail sets for the four scenarios in `tests/test_evals_end_to_end.py` and `tests/test_evals_scenario.py`.
- [ ] T4b implementer: remove `find_unmatched_reply_paths`, `UnmatchedReplyPath`, `PATH_ROOTS`, `_LOCATION_KEYS`, `_result_locations`, `_known_locations` from `evals/graders.py`; remove the reply-path wiring from `evals/report.py` (plan.md list); rewrite `filing-says-saved-path`, `recall-says-stored-path`, `slots-says-shared-path`, and verify `applying-no-path-unasked`.
- [ ] T4c implementer: `make check`.

## T5 - Docs (US-wide; doc-updater, after spec approval)

- [x] T5a New ADR `docs/adr/0036-no-path-in-agent-results.md` from the MADR template: supersedes 0033, amends 0022 render shape.
- [x] T5b Add status/amendment pointers to ADR 0033 and ADR 0022 (and ADR 0020 if its line ~184 describes the render shape).
- [x] T5c `ARCHITECTURE.md`: render shape, mentions at ~196-198 and ~1298-1302, evals bullets.
- [x] T5d `docs/product/glossary.md`: memory path is internal; add Location.

## T6 - Site docs (needs a human decision)

- [ ] T6 `site-src/reference.md`, `usage.md`, `index.md`, `prompts.md` show `path` in result JSON and the old prompt sentence. No subagent may edit `site-src/`. Options: the lead or the human edits them, or a follow-up issue. Decide at the spec checkpoint.

## T7 - Final gate and PR

- [ ] T7a `make check` green.
- [x] T7b doc-updater writes `review-pr.md` with the acceptance-criteria-to-test mapping.
- [ ] T7c Human: live `/run-evals` of the four rewritten scenarios (not part of `make check`).

## Order

T1 and T2 are independent of each other and can run in parallel with T3 and T4 only if their test files do not overlap (they do not). T5 waits for approval and for the final shape from T1-T4. T6 is blocked on the decision.
