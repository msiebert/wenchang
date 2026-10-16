# Plan: File a role the user states inside a question

**Linear issue**: AIE-1182 | **Spec**: [spec.md](spec.md)

Consistent with Notion §8.1; no ADR per ADR 0025 §4.

## Public interface

No interface change. `wenchang.prompts.remembering.HEADING` and `BODY` keep
their names and types; `build_memory_prompt` and section order are unchanged.
No ARCHITECTURE.md change.

## A. Prompt text (`src/wenchang/prompts/remembering.py`, implementer)

Replace the final paragraph of `BODY`:

```diff
 Write facts as they arise, before you ask a follow-up question, because the conversation may end
-first.
+first. When the user mentions their own role, team, or responsibilities in passing, such as inside
+a question, save it before or alongside your answer.
 """
```

Line widths 97, 98, 52. BODY goes from 1293 to about 1440 characters
(budget 2500).

Wording choices:

- A standalone imperative naming the trigger ("mentions ... in passing, such
  as inside a question") rather than an extension of "facts", because the
  failure is not noticing that a fact arose.
- "their own role, team, or responsibilities" limits it to the user's work
  context: not project facts (which still need the ask) and not other
  personal details such as age or school.
- No scope is named; the adopter's "otherwise use user" routes it.
- Placed in the write-timing paragraph; the save-criterion paragraph is the
  fallback under spec 4.6.

## B. Tests (`tests/test_prompts_remembering.py`, test-writer)

Pin only load-bearing terms (ADR 0025 §8). Docstrings cite `AIE-1182, USx.y`.

- B1 (US1.1): parametrized phrases in `_flat(remembering.BODY)`:
  "When the user mentions their own role, team, or responsibilities",
  "in passing", "inside a question", "before or alongside your answer".
- B2 (US1.2): split raw `remembering.BODY` on `"\n\n"`; the one paragraph
  containing "Write facts as they arise" also contains (after `_flat`)
  "in passing" at a later index than "Write facts as they arise".
- B3 (US1.3): `build_memory_prompt(REFERENCE_SLOTS)` (from
  `evals.reference_adopter`); the text between `## Deciding what to
  remember` and the next `\n## ` contains, after `_flat`, "their own role,
  team, or responsibilities in passing".

US1.4 and US2.2 are covered by existing invariants and remembering tests;
no new test. Confirm B1-B3 fail against `main` because the phrase is absent.

## C. Scenario comment (`evals/scenarios/remembering-stated-role.yaml`, implementer)

Header only; turns and assertions unchanged:

```diff
 # Prompt: "`[stated]`: the user told you directly." and "Write facts as they
 # arise, before you ask a follow-up question, because the conversation may end
-# first." and "otherwise use user."
+# first." and "When the user mentions their own role, team, or
+# responsibilities in passing, such as inside a question, save it before or
+# alongside your answer." and "otherwise use user."
```

## D. Agent file (implementer)

After A, run `uv run python -m evals render-agent` from the worktree to
regenerate `.claude/agents/wenchang-eval.md`, then record its sha256 for
review-pr.md.

## E. Docs (doc-updater)

`specs/AIE-1182-file-role-stated/review-pr.md` from the template. Live-eval
section PENDING, with commit hash, agent sha256, the launch command:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
```

the shard and merge invocations per `.claude/commands/run-evals.md`, the US4
floors table, and per-trial result slots for `privacy-minor`,
`remembering-no-metric-value`, and `remembering-stated-role`.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1182 check` green. The PR
stays gated on the human live run (US4).
