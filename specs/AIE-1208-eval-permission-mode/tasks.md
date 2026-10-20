# Tasks: AIE-1208

Order matters: tests first. Roles follow the AGENTS.md table; the guard hook
resolves against the main repo, so worktree edits are outside its scope.

## T1 — Tests (test-writer)

Spec AC1-AC7, AC10-AC17 (including AC14b, the flush-race and filtering cases). Update `LAUNCH`, add `SHARD_LAUNCH`, add runner-doc
tests, transcript module tests, and server/graders tests. They fail until T2
and T3 land.

## T2 — Evals code and run-evals.md (implementer)

Add `evals/subagent_transcript.py`; extend `TranscriptTurn` and
`load_transcript`; add `transcripts_root` to `EvalState`, the tool error, and
`--transcripts-root`; update `.claude/commands/run-evals.md` (commands,
"What each part does", preflight, step 3.2, D5 rules).

## T3 — Docs and ADR (doc-updater)

Spec AC3, AC8. AGENTS.md, README.md, ADR 0028 (decisions 6 and 7, the note),
0031, 0032, new ADR 0035, ARCHITECTURE.md link.

## T4 — Live probe (orchestrator)

Run the preflight through the harness under `dontAsk`; confirm the recorded
reply and marker line.

## T5 — review-pr.md (doc-updater)

From `docs/templates/review-pr-template.md`.

## T6 — Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1208 check` (AC9).
