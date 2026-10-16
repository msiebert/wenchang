# Implementation Plan: Corrections use replace_fact (AIE-1183)

**Spec**: `specs/AIE-1183-corrections-use-replace-fact/spec.md`

No public interface changes: no signatures, modules, docstrings, or
storage behavior. The changes are prompt text, one scenario, its scripted
drivers, and the rendered eval agent file.

## 1. `src/wenchang/prompts/write_mechanics.py`

Two sentences go in after the "mechanically impossible" sentence. Every
existing sentence stays word for word; only the line wrapping after the
insertion changes. I checked the new `BODY` against every existing
write-mechanics and invariants test: 1005 characters, longest line 99.
Replace `BODY` with exactly:

```
Match the write to the change. Use `append_line` to add one fact to an existing file and
`replace_fact` to change one fact, quoting the existing line as `old_string` so surrounding lines
stay intact; this makes it mechanically impossible to disturb lines you were not editing. To change
or correct a fact stored in a file you can write, use `replace_fact` even when you have read the
whole file; never rewrite the file with `write_file` to change a fact. The `new_string` of a
changed fact states only the current fact, with no "previously" or "instead of" clause, and leaves
no note of the old value. Use `write_file` only for creating a file, restructuring many lines,
dropping a name from `aliases`, or rewriting the `description` with no fact to write. To drop one
fact line, call `replace_fact` with an empty `new_string` and the whole line as `old_string`,
including the line break after it (or before it, if none follows), so no blank line remains. Use
`delete_file` only when the whole file goes.
```

The first sentence says "change or correct" because session 2's user states
an update ("I now send ... instead"), not a mistake. With "correct" alone an
agent could decide the history ban did not apply.

Why each sentence is there:

- **"you can write"** keeps the sentence out of curated content. A
  `system/` correction is still a new line in a writable area
  (curated_content.py).
- **"even when you have read the whole file ... never rewrite"** targets
  the read-then-overwrite path seen in the live runs.
- **"states only the current fact ... no note of the old value"** targets
  the "(previously sent to the growth team)" line. "of a changed fact"
  covers an update the user states, not only a mistake.

Rejected alternatives:

- Rewording "Use `write_file` only for creating a file, ...". The
  `write-new-subject` scenario and the AIE-1051 tests cite it verbatim.
- A `write_file` docstring sentence. ADR 0025 decision 6 gives tool choice
  to the prompt.
- An alias/description sentence. It would route agents back to
  `write_file`, restate filing.py, and nothing would test it.
- A "pass an updated description on the same call" clause (reviewer
  suggestion). filing.py owns that rule, and the AIE-1051 US3.2 test bans
  "same call" and "same write" in this body.

## 2. `evals/scenarios/recall-replace-fact.yaml`

Replace the header comment with:

```
# Prompt: "Use `append_line` to add one fact to an existing file and
# `replace_fact` to change one fact", "To change or correct a fact stored in a
# file you can write, use `replace_fact` even when you have read the whole
# file; never rewrite the file with `write_file` to change a fact", "The
# `new_string` of a changed fact states only the current fact, with no
# "previously" or "instead of" clause, and leaves no note of the old value",
# and "Writes to user need no ask."
```

Then append this assertion:

```yaml
  - kind: line_absent
    id: old-recipient-gone
    pattern: "(?i)growth"
    scope: user
```

## 3. `tests/test_evals_end_to_end.py`

Edits to the existing table:

- The `CASES` fail set for `recall-replace-fact` becomes
  `{"replaced-in-session-2", "one-recipient-line", "old-recipient-gone"}`.

New scripted drivers:

- **`replace_overwrite_wrong(d)`**, which reproduces the live failure.
  - Session 1 is the same as in `replace_correct`.
  - Session 2: `d.index()`, then read `user/workflows/weekly-report` for its
    version.
  - It then calls `write_file` with:
    - `content="- [stated] Sends the weekly report to the retention team (previously sent to the growth team).\n"`
    - `description="Weekly report routine"`
    - `aliases=[]`
    - `expected_version` set to that version
  - It ends with `d.turn(2, 1)`.
- **`replace_with_stale_metadata(d)`**:
  - Session 1: `d.index()`, then `write_file` the `GROWTH` line with
    `description="Weekly report to the growth team"`,
    `aliases=["growth report"]`, and `expected_version=None`, then
    `d.turn(1, 1)`.
  - Session 2: `d.index()`, `d.replace(... GROWTH, RETENTION)`, then
    `d.turn(2, 1)`.

New tests, each citing AIE-1183 in its docstring:

- `test_recall_replace_fact_flags_a_previously_clause`: fails exactly
  `{"replaced-in-session-2", "old-recipient-gone"}`, and the report shows
  0/1.
- `test_recall_replace_fact_ignores_stale_metadata`: passes every
  assertion, and the report shows 1/1. It also asserts the growth alias and
  description survive session 2.

`tests/test_evals_scenario.py` gains
`test_recall_replace_fact_header_cites_the_correction_sentences` (US2.6).

## 4. `tests/test_prompts_write_mechanics.py`

Add tests only; existing ones stay as they are. Each docstring cites
AIE-1183, and each test pins only load-bearing terms:

- `_only_sentence_containing("even when you have read the whole file")`
  contains `replace_fact`, `write_file`, "change or correct", "you can
  write", and "never rewrite the file".
- `_only_sentence_containing("states only the current fact")` contains
  `new_string`, "of a changed fact", `"previously"`, and "no note of the
  old value".

## 5. `.claude/agents/wenchang-eval.md`

Run `uv run python -m evals render-agent` after §1. The file embeds the
framing preamble and the rendered memory prompt; tool descriptions are not
in it. `tests/test_evals_agent.py` requires it to equal
`render_agent_file()`.

## 6. `review-pr.md`

Draft it from `docs/templates/review-pr-template.md`. It must include:

- The AC-to-test table.
- The baseline table from the spec.
- The new agent sha256 (`shasum -a 256 .claude/agents/wenchang-eval.md`)
  and the commit the live runs must report.
- The live section marked PENDING, with the exact commands below and the
  miss policy.

There is no ADR or ARCHITECTURE.md change.

## Live runs (human merge checkpoint)

From the worktree root, run the targeted N=6 set in one session:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
/run-evals --model sonnet --trials 6 --judge recall-replace-fact write-correct-seeded-fact write-new-subject forgetting-one-fact forgetting-whole-file forgetting-two-files forgetting-only-fact curated-correction curated-shared-conflict
```

Then run the full corpus at N=3 in 3 headless shards, and merge them:

```
CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard 1/3" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
# repeat with --shard 2/3 and --shard 3/3, then:
uv run python -m evals merge-runs evals/runs/<name> <shard run dirs...>
```

## Risks

- `.claude/agents/wenchang-eval.md` is generated, and AIE-1182 and
  AIE-1184 also change its inputs, so it will conflict on merge. Resolve
  it by re-rendering on the merged tree.
- AIE-1185 also edits `CASES`. The conflict is only textual.
