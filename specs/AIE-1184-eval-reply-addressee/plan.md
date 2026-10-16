# Implementation Plan: Flag eval replies addressed to someone other than the user

**Linear issue**: AIE-1184 | **Spec**: [spec.md](spec.md) | **Branch**: `AIE-1184-eval-reply-addressee`

Edits happen directly in the worktree. Test/implementation separation holds
by discipline: tests are written first and confirmed failing, then the
implementation. Widening the guard hook's rule 4 is a separate human
follow-up, already listed in AGENTS.md.

## 1. Approach and rejected alternatives

The chosen approach is a harness-wide deterministic reply check, plus a
conditional preamble change. The judge is unchanged. See spec "Deviation
from the issue" and ADR 0031.

**Rejected: a new scenario assertion kind** (for example
`reply_addresses_user`):

- `grade(scenario, store, trace)` excludes the transcript (ADR 0028 §3).
- It would count toward deterministic pass/fail. At baseline, 16 of 138
  passing trials would have failed.
- It is opt-in per scenario, so it would touch all 23 YAMLs and the
  scripted fail sets, which AIE-1183 and AIE-1185 edit in parallel.

**Rejected: a judge rubric line or judge rule:**

- It is LLM-graded and runs only with `--judge`.
- It breaks comparability with the baseline judge counts.
- The deterministic check already finds all 3 judge-failing trials, plus
  13 more.

**Rejected preamble wording "nobody else reads it":** it is false. The
runner, the later-turn replay, and the judge all read the reply.

## 2. Public interface

### 2.1 `evals/graders.py` (appended after `grade`)

New names go into `__all__` in sorted position. Ruff RUF022 requires a
sorted `__all__`.

```python
THIRD_PERSON_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bthe user(?:'s|’s)?+(?![\w'’])(?![-\s]+scopes?\b)|\bthe caller\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ThirdPersonReply:
    """A reply that refers to the user in the third person."""

    session: int
    turn: int
    phrase: str


def find_third_person_replies(
    scenario: Scenario, transcript: Sequence[TranscriptTurn]
) -> tuple[ThirdPersonReply, ...]:
    """At most one flag per reply, in transcript order."""
```

Private helpers:

- R1 strips, in this order: fenced blocks
  (`^[ \t]*```.*?(?:^[ \t]*```[^\n]*$|\Z)`, using MULTILINE and DOTALL),
  then `>` lines (`^[ \t]*>.*$`, MULTILINE), then the one-line quoted
  spans `"[^"\n]*"|“[^”\n]*”|`[^`\n]*``.
- The next word is `\s+[\w'’]+`, matched at the end of the match.
- `_normalize(text)` is `" ".join(text.lower().replace("’", "'").split())`.
- The R3 context is the normalized space-join of three parts:
  - `user` for transcript turns with the same session and turn <= this
    turn;
  - for each seed file, its content, description, and aliases.
- The R3 test is
  `re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", context)`.

### 2.2 `evals/report.py`

- **`grade_trial(trial_dir)`.** Results and `passed` are computed as
  today. Then `_reply_check(trial_dir, scenario)` returns one of:
  - `{"third_person_replies": [...]}` when `transcript.json` loads;
  - `{"transcript_error": str(exc)}` when it raises `GradeInputError`;
  - `{}` when it is absent.

  The result is merged into the graded dict and written.
- **`build_report`.** Per trial:
  - If `_grade_is_current` (store and trace only, unchanged), it loads
    `grade.json`. If `transcript.json` exists and either the grade lacks
    both keys or `transcript.json` is newer than `grade.json`, it
    recomputes only `_reply_check`, drops the stale
    `third_person_replies` and `transcript_error`, merges the fresh
    result, and rewrites `grade.json` with `results` and `passed` kept.
  - Otherwise, if dumped, it calls `grade_trial`.
- **`_load_grade`.** `third_person_replies`, when present, must be a list
  of `{session: int, turn: int, phrase: str}`, and `transcript_error`,
  when present, must be a str. Otherwise it raises `GradeInputError`
  naming `grade.json`.
- **New keys in each scenario entry.** Existing keys keep their exact
  shapes.
  - `third_person_trials: [{"trial", "replies"}]`
  - `addressee_unchecked_trials: [int]`
  - `judge_third_person_fails: [{"id", "fails"}]`, which has the same ids
    and order as `judge`, so only judged items appear.
- **New top-level key.** `third_person: {"flagged_trials",
  "checked_trials"}`.
- **`_markdown`:**
  - After the summary table: `Trials with a third-person reply: {f} of
    {c} checked.`
  - In each scenario section, after the assertion table, only when
    non-empty: `Third-person replies: trial 1 (session 1 turn 1: "the
    user said"); trial 3 (...)`. Several replies in one trial are
    comma-separated inside its parentheses. Also, when non-empty:
    `Addressee not checked: 3`.
  - The judge table becomes `| Judge item | Passes | Fails with a
    third-person reply |`.

### 2.3 `evals/__main__.py`

After the PASS/FAIL lines, `_grade` prints:

- `THIRD-PERSON session {s} turn {t}: {phrase}` for each flagged reply;
- `TRANSCRIPT ERROR: {message}` when grading recorded one.

Exit codes are unchanged.

## 3. Exact text changes

### `evals/agent.py` `EVAL_AGENT_PREAMBLE`

Before:

> You are an assistant helping a Mixpanel user. Each message you receive is that user's own turn; reply to them directly. Earlier turns of this conversation may be included above the newest one.

After:

> You are an assistant helping a Mixpanel user. Each message you receive is that user's own turn. Your reply goes to that user word for word, so in your reply address them as "you" and never call them "the user". Earlier turns of this conversation may be included above the newest one.

Then:

- Run `uv run python -m evals render-agent`.
- Record the new sha256 in `review-pr.md`.
- Leave the judge agent file unchanged. It is static, with no renderer.

### `.claude/commands/run-evals.md`, section 4

Append:

> The report also counts trials whose reply referred to the user in the third person ("the user said"). These counts are a separate signal and never change a pass count. A judge fail in such a trial is co-occurrence, not proof the addressee caused it.

### Docs

- **ADR 0031** (new): rules R1 to R4, rejected alternatives, the contract
  extension, the baseline calibration, the gate, and the outcome (pending).
- **ADR 0028**: a Consequences pointer to ADR 0031.
- **ARCHITECTURE.md**: the `evals.graders` and `evals.report` bullets.
- **`review-pr.md`**: the live-eval section is PENDING.

## 4. Files touched

`evals/graders.py`, `evals/report.py`, `evals/__main__.py`, `evals/agent.py`,
`.claude/agents/wenchang-eval.md`, `.claude/commands/run-evals.md`,
`tests/test_evals_graders.py`, `tests/test_evals_report.py`,
`tests/test_evals_agent.py`, `tests/test_evals_end_to_end.py`,
`docs/adr/0031-reply-addressee-check.md`,
`docs/adr/0028-behavioral-eval-harness.md`, `ARCHITECTURE.md`, and
`specs/AIE-1184-eval-reply-addressee/review-pr.md`.

## 5. Risks

- **Recall.** The pattern misses phrasings like "they asked me to". The
  count is a lower bound, measured the same way on both sides of the gate.
- **Precision on future scenarios.** Analytics talk ("where the user drops
  off") may add noise. The check never fails a trial.
- **Confounds.**
  - Sibling prompt changes: measure first and merge first (spec US3
    order).
  - The 5bd1355 `model=` rule postdates the baseline.
- **Small sample.** The gate is a practical bar, not a significance test.
- **Merge conflicts.** In `graders.py`, only in `__all__` and the imports.
