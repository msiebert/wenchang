# Spec Review: AIE-1252 - Remove `path` from agent-facing tool results

## What & why

Tool results and errors currently carry `path` next to `scope`, `area`, and `name`, but no tool takes a path. We remove `path` (and the capped-row `prefix`) from everything the agent sees, reword error messages to name the location as `scope X, area Y, name Z`, and change the prompt and evals to match. Core types keep `.path`; only the agent-facing layer changes.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | A file from read/write/append/replace | rendered | no `path`; has scope, area, name, content, version, metadata |
| 2 | A list page | rendered | entries without `path`/`content`; `next_cursor` unchanged and opaque |
| 3 | An index with capped rows | rendered | entries without `path`; rows are exactly `{scope, area, omitted}` |
| 4 | Any error kind | rendered | no `path`; has scope/area/name when parseable; repair fields kept |
| 5 | Any error | message read | says `scope X, area Y, name Z`; no slash path, `.md`, or entity ID |
| 6 | MCP call | succeeds | text and structured payloads have no `path`/`prefix` at any depth |
| 7 | Overview prompt | read | "name its scope, area, and name"; no `path`; eval agent file regenerated |
| 8 | Eval harness | graded/reported | reply-path check, report fields, and tests gone; old `grade.json` still loads |
| 9 | The 4 path scenarios | driven | rewritten to scope/area/name; an entity ID in the reply fails |
| 10 | Core values and errors | read in-process | `.path` / `.prefix` unchanged; `test_core_*` untouched |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Remove `path` from the render layer only | Remove from core types too | In-process hosts and core tests use `.path`; the issue targets agent tokens |
| Agent names scope/area/name; no `entity` field | Add `entity`; keep `path` | Decided by you; the entity is implicit in the grant |
| Errors keep `.path` attribute, stop rendering it; message uses `scope X, area Y, name Z` | Keep path in errors; slash-joined `scope/area/name` in messages | Consistent with results; slash form looks like a path and invites quoting |
| Retire the reply-path check entirely | Keep a check for the new wording | Nothing structural left to verify against the trace; judge items cover the wording |
| Scenarios guard against entity IDs in replies (`u-ada`, `o-acme`, `p-checkout`) | Regex requiring a specific area/name | Area/name are chosen by the agent; the leak to prevent is the entity segment |

## Files/modules to be touched

- `src/wenchang/tools.py`, `src/wenchang/errors.py`, `src/wenchang/prompts/overview.py`
- `.claude/agents/wenchang-eval.md` (regenerated), `evals/graders.py`, `evals/report.py`, four scenario YAMLs
- Tests: render, end-to-end, MCP, evals server, reference adopter, prompts, evals graders/report/scenario/end-to-end
- Later: new ADR 0036 (supersedes 0033, amends 0022), ARCHITECTURE.md, glossary

## Open questions / assumptions

1. `site-src/` (reference.md, usage.md, index.md, prompts.md) shows `path` in result JSON and the old prompt sentence. No subagent can edit it. Who updates it: you or the lead, in this PR, or a follow-up issue? `README.md` needs nothing.
2. Is a reply like `user/preferences/csv-format` (slash-joined, no entity) acceptable? The plan allows it and only fails on the entity ID.
3. The reply-path tests (~600 lines across graders and report tests) are deleted because the feature they test is removed per the issue. Confirm this counts as "the issue requires it".
4. ADR number assumed 0036 (latest is 0035).
5. Old `grade.json` with `unmatched_reply_paths` is ignored, not migrated.

## Risks

- Hosts that parse `path` out of rendered JSON break; recorded as intended in the ADR.
- The guard hook does not yet cover the implementer's `evals/` and `.claude/agents/wenchang-eval*.md` scope (AGENTS.md), so T3b/T4b may be blocked or need a manual hook change.
- Evals are not part of `make check`; the rewritten scenarios are only driver-tested until you run `/run-evals`.
- Error message rewording is exact-string pinned in many tests; one missed formatting change fails several.
