# Implementation Plan: AIE-1199 Third-person reply check skips data uses in SQL turns

**Spec**: [spec.md](spec.md)

## Public interface

No new public names. These keep their signatures, in `evals/graders.py`:

```python
THIRD_PERSON_PATTERN: Final[re.Pattern[str]]  # unchanged


def find_third_person_replies(
    scenario: Scenario, transcript: Sequence[TranscriptTurn]
) -> tuple[ThirdPersonReply, ...]: ...
```

`evals/report.py`: `build_report(run_dir)` keeps its signature. Its private
`_refresh_reply_check` changes (US3). `grade.json` keeps its shape.

## Rules

### SQL statement (private `_has_sql(text) -> bool`)

Case-insensitive, on raw text (fences, backticks, and quotes not stripped).
Split the text into statements at blank lines (`\n[ \t]*\n`) and at `;`.
True when any one statement holds either:

1. `\bselect\b` ... `\bfrom\s+[a-z_][\w.]*` and, after that `from`, one of:
   - `\bjoin\s+[a-z_][\w.]*(?:\s+(?:as\s+)?[a-z_]\w*)?\s+on\b`
   - `\bwhere\s+[a-z_][\w.]*\s*(?:=|<>|!=|<=|>=|<|>)`
   - `\bgroup\s+by\b` or `\border\s+by\b`
2. `\binsert\s+into\s+[a-z_]`, `\bupdate\s+[a-z_][\w.]*\s+set\s+[a-z_][\w.]*\s*=`,
   `\bdelete\s+from\s+[a-z_][\w.]*\s+where\b`, or `\bcreate\s+table\b`.

Newlines inside a statement are allowed, so multi-line SQL counts.

A turn is an SQL turn when `_has_sql` holds for its raw reply or for the
raw `user` text of any turn of the same session with `turn <=` this turn.

### Data-verb exemption

In an SQL turn, a match is skipped when all hold:

- it is non-possessive (no `'s`);
- the unquoted reply text before it (`reply[:match.start()]`, trailing
  whitespace trimmed) does not end with an addressee word from spec US2.3;
- the next word (the same word `_NEXT_WORD` already finds) is a data verb
  from spec US1.6, whole word, case-insensitive;
- the word after it, skipping at most one adverb from spec US2.4, is not a
  speech verb from spec US2.4.

The match is `the user` or `the caller`; only `the user` is exempt (US2.10).
The echo rule is unchanged and still applies. Reported phrases are
unchanged. At most one flag per reply: the first match that is neither
exempt nor an echo (US2.5).

### Product and data vocabulary (US1.7 to US1.9, any turn)

`THIRD_PERSON_PATTERN` stops matching a non-possessive `the user` directly
followed by `(?:[ \t ]+|[ \t ]*[-–—][ \t ]*)` and
then a data noun or an interface action verb from spec US1.7 / US1.8, at a
word boundary. Possessives keep today's rule (only "scope" excluded), and
"the caller" is unchanged. The existing "scope" rule and its separator are
unchanged.

### Re-report (US3)

`_refresh_reply_check(trial_dir, scenario, graded)`:
- transcript missing: unchanged (drop the check if present).
- transcript present: compute `_reply_check(...)`; if the recorded
  `third_person_replies` / `transcript_error` fields equal the fresh ones,
  return without writing; otherwise replace them and write `grade.json`.

## Files

- `evals/graders.py`: `_has_sql`, verb sets, the exemption in
  `find_third_person_replies`.
- `evals/report.py`: `_refresh_reply_check`.
- `tests/test_evals_graders.py`, `tests/test_evals_report.py`: new tests;
  one docstring reworded.
- `docs/adr/0031-reply-addressee-check.md`: amendment.
- `specs/AIE-1199-third-person-data-rows/review-pr.md`.

## Re-report procedure (US3.3 to US3.5)

1. Before: the original `report.json` of each run (both have a
   `third_person` total: 8/138 and 2/30). Hash every file of both original
   run dirs.
2. `cp -Rp` both runs into the session scratchpad (`runs-after/`).
3. 1184 copy: `uv run --directory <AIE-1199 worktree> python -m evals report <copy>`.
4. 1185 copy: in a scratch worktree at `origin/AIE-1185-deferred-eval-scenarios`,
   apply the AIE-1199 `evals/` diff (3-way), then run the report from there.
5. Same as step 4 for the AIE-1182 and AIE-1183 runs, each on a scratch
   worktree of its own branch.
6. Compare `third_person`, per-scenario flags, `trials_run`,
   `passed_trials`, `assertions`, `judge`; re-hash the originals.
