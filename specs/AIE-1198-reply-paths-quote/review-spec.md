# Spec Review: AIE-1198 — Quote the tool's path; check reply paths against the trace

## What & why

The agent tells users it saved facts at paths that do not exist (it rebuilds
`project/metrics/dau.md` from its own arguments instead of quoting
`project/p-checkout/metrics/dau.md`). One general prompt sentence fixes the
mechanism, and a new harness check measures it on every reply without
touching pass counts.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `overview.BODY` | flattened | 2nd sentence: "When you tell the user where something is stored, quote the full `path` a tool returned for it; never rebuild one from its scope, area, and name." |
| US2 | a trial with transcript + trace | graded or re-reported | `grade.json.unmatched_reply_paths` lists scope-rooted reply tokens matching no path/prefix in tool results up to that turn, kind `entity_omitted` or `unmatched`; report shows counts apart from pass counts |
| US2.9 | before/after copies of 4 historical runs | re-reported | pass/judge/third-person fields identical; flag counts and FP review recorded |
| US3 | 4 held-outs (user save, project save unasked, org recall, no-path guard) | committed before the prompt edit | correct/wrong drivers with exact fail sets |
| US5 | human live gate | main baseline for held-outs; branch full corpus N=6 | floors in spec 5.3 |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Sentence in overview ("Memory") | curated_content; write_mechanics | Failure happens on any save or recall |
| Harness-wide check, separate signal | assertion kind; judge rule | ADR 0031 reasoning: no opt-in, no pass-count churn |
| Known = `path`/`prefix` in results, incl. failed calls, not arguments | arguments | Arguments are exactly what the agent rebuilds from |
| Two-segment prose skipped unless known area/entity | flag all | Avoids `user/session` prose FPs, keeps `user/preferences` shorthand |
| Tool output unchanged | shorter paths | Storage/API change for an eval symptom |

## Files/modules to be touched

- `src/wenchang/prompts/overview.py`, `.claude/agents/wenchang-eval.md`
- `evals/graders.py`, `evals/report.py`, 4 new `evals/scenarios/*.yaml`
- `tests/test_evals_graders.py`, `test_evals_report.py`, `test_evals_end_to_end.py`, `test_evals_scenario.py`, `test_prompts_overview.py`
- `docs/adr/0033-reply-path-check.md`, `ARCHITECTURE.md`

## Open questions / assumptions

- Scope/area shorthand (`user/preferences/editor`) counts as a misreport, per the issue's trial 1 example.
- Proposals before a write are flagged and classified in the review.

## Risks

- High historical flag rate (roughly a third of trials) — expected; it is the signal.
- Agent-file conflict with PR #41 on rebase.
