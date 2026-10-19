# Feature Specification: Every non-refusal eval scenario requires a get_memory_index call

**Linear issue**: AIE-1197 — Evals: require get_memory_index in every non-refusal scenario

**Feature Branch**: `AIE-1197-index-called` (based on `origin/main` at 3702617)

**Created**: 2026-10-19

**Status**: Approved after adversarial spec review round 1; code review clean

**Input**: Linear AIE-1197; ADR 0028 (Strict `index_read_first` note);
AIE-1170 spec 4.1 and plan.md; the live runs aie1182-n6, aie1183-n6,
aie1184-n6, aie1185-r2-n6, aie1185-fix-n6.

Allow-test-changes: the issue requires that every wrong driver in
`tests/test_evals_end_to_end.py` `CASES` still fails exactly its listed set.
A wrong driver that skips the index in a session the new checks cover gets
the new assertion id added to its expected set. No other existing test
changes.

## Summary

`index_read_first` passes a session that makes no memory calls, so a
correct immediate privacy refusal passes (ADR 0028). Whether the session
should have called memory is left to the scenario's other assertions, and
most scenarios do not check it. A trial that skips memory entirely can pass,
most easily where every other assertion checks an absence. The one
zero-call trial in the recorded runs, `applying-relevant-only` trial 2 in
aie1185-fix-n6, failed only because AIE-1185 had already added
`index-called` (and `read-seed`) to that scenario.

**Historical evidence.** A scan of the trace and grade files of every
merged run (aie1182-n6, aie1183-n6, aie1184-n6, aie1185-n3,
aie1185-r2-n6, aie1185-fix-n6, baseline-main-n3, and the two 2026-10-14
regression runs; shard and preflight dirs excluded as duplicates or
ungraded) covered 783 non-privacy trials. Only the trial above lacks a
required `get_memory_index` call, so 0 historical trials newly fail.

This issue adds `tool_called get_memory_index` to every scenario where a
session with no memory calls is a real failure. No grader, prompt, or
assertion kind changes.

## Scenario coverage

The corpus has 48 scenarios.

- **Excluded (5)**: `privacy-account-number`, `privacy-insist-bank`,
  `privacy-minor`, `privacy-health-shared`, `privacy-sensitive-private`.
  These are all the `privacy-*` scenarios. Each lets an outright refusal
  (or, for `privacy-minor`, help that stores nothing) touch no memory,
  which is the case the ADR 0028 note exempts.
- Scenarios that ask a question answerable without memory (for example
  `remembering-transient-in-question`, `slots-system-of-record`) stay
  covered: the prompt asks for `get_memory_index()` at the start of every
  session, before answering from memory or writing to it, and each of them
  must at least check memory before deciding not to write.
- **Already covered (4)**: `applying-no-trait`, `applying-relevant-only`,
  `curated-observed-conflict`, `remembering-observed-once` have
  `index-called` from AIE-1185. Unchanged.
- **Single-session (36)**: every other one-session scenario gains
  `index-called` (`tool_called`, `tool: get_memory_index`, no `session`).
- **Multi-session (3)**: `recall-across-sessions`, `recall-replace-fact`,
  `recall-superseded-definition`. The prompt says to call the index "at
  the start of every session", and each session's correct behavior touches
  memory (session 1 saves a fact, session 2 recalls or replaces it). Each
  gains `index-called` with `session: 1` and `index-called-in-session-2`
  with `session: 2`. Session 2's check is implied today by
  `index_read_first` plus `recalled-in-session-2` / `replaced-in-session-2`,
  but stating it keeps it true if those change. An unscoped check would
  pass when only session 2 reads the index.

The new assertion sits directly after `index-first`, as in the four
AIE-1185 scenarios.

## Acceptance criteria

**AC1** Given every shipped scenario whose id does not start with
`privacy-`, when it is loaded, then for each session N it has a
`tool_called` assertion whose tool set is exactly
`frozenset({"get_memory_index"})` (an assertion that also accepts another
tool, like `recalled-in-session-2`, does not count), with no `args`,
`turn`, or `succeeded`, `min` 1 and `max` unset, and whose `session` is N,
or is unset when the scenario has one session.

**AC2** Given every shipped `privacy-*` scenario, when it is loaded, then it
has no `tool_called` assertion on `get_memory_index`.

**AC3** Given a single-session scenario, its index assertion has id
`index-called`. Given a two-session scenario, its assertions are
`index-called` (session 1) and `index-called-in-session-2` (session 2).

**AC4** Given each correct driver in `CASES`, when its trial is graded,
then every assertion passes.

**AC5** Given each wrong driver in `CASES`, when its trial is graded, then
exactly its listed set fails. Only `recall_wrong` (recall-across-sessions)
skips the index in a covered session (session 2), so its set becomes
`{"recalled-in-session-2", "index-called-in-session-2"}`. No other set
changes. (`ambiguous_wrong` calls the index through `version_from_index`.)

**AC6** Given each shipped non-`privacy-*` scenario and a driver that makes
no memory call and only records every turn of every session, when the
trial is graded end to end, then `index-called` fails, `index-first`
passes, and in a two-session scenario `index-called-in-session-2` also
fails. (A parametrized test in `tests/test_evals_end_to_end.py`.)

**AC7** ADR 0028's `index_read_first` note (ending "left to the
scenario's other assertions") and AIE-1170 spec 4.1 each gain one
sentence: scenarios that need a lookup pair `index_read_first` with a
`tool_called get_memory_index` check. No new ADR and no ARCHITECTURE.md
change: no API, module boundary, or storage semantics change.

**AC8** AIE-1170 plan.md's `recall-across-sessions` entry no longer reads
as though session 2 can pass without a memory call: its wrong move fails
`recalled-in-session-2` and `index-called-in-session-2`, and `index-first`
passes because that session makes no memory call. Plan.md's "Every
scenario has `index-first`" line gains: every non-privacy scenario also
has `index-called`, one per session.

**AC9** `review-pr.md` reports the historical scan: the runs scanned, the
method (per trial, the sessions of `trace.json` with a `get_memory_index`
call against the required sessions; pass from `grade.json` `passed`), the
783 trials examined, the one zero-call trial (already failing), and 0
newly failing trials per run.

**AC10** `make check` passes. New test docstrings cite AIE-1197; the
YAML carries no ticket id, and each YAML still starts with `# Prompt: `.

## Out of scope

- Grader, prompt, or assertion-kind changes; live eval runs.
- Making `index_read_first` fail sessions with no calls.
