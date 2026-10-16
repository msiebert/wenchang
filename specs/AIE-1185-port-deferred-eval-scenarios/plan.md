# Implementation Plan: Port the deferred eval scenarios

**Linear issue**: AIE-1185 | **Spec**: [spec.md](spec.md)

## Branch and merge ordering

- **Order.** AIE-1184 merges first, and AIE-1185 merges after it.
- **What AIE-1184 brings.**
  - A non-failing check that flags third-person replies.
  - `transcript.json` loading in `grade_trial`.
  - Changes to `_grade_is_current` and `_load_grade`.
  - It keeps `grade(scenario, store, trace)` unchanged.
- **What AIE-1185 owns.** The `grade()` contract change: the optional
  transcript argument that the reply kinds need.
- **Rebase.**
  - Branch `AIE-1185-deferred-eval-scenarios` starts from `main` at
    abe49c9, in the worktree `/Users/marksiebert/p/github/wenchang-AIE-1185`.
  - When the coordinator says AIE-1184 has committed, the branch is rebased
    with `git -C /Users/marksiebert/p/github/wenchang-AIE-1185 rebase
    AIE-1184-eval-reply-addressee`, or onto `main` if AIE-1184 has merged.
- **Before the rebase**, this branch may commit only:
  - spec artifacts;
  - the ten scenario YAMLs;
  - `evals/scenario.py`;
  - tests that do not depend on `grade_trial` or on the new `grade`
    parameter.

  No `evals/graders.py` or `evals/report.py` code is committed before the
  rebase.
- **After the rebase**:
  - `grade_trial` passes AIE-1184's already-loaded transcript to `grade`. It
    does not add a second loader.
  - `transcript.json` joins the freshness mtime set in `_grade_is_current`,
    unless AIE-1184 already added it.
- **Other siblings.**
  - AIE-1182 edits `prompts/remembering.py`.
  - AIE-1183 edits `prompts/write_mechanics.py` and
    `recall-replace-fact.yaml`.
  - This branch touches no prompt module, no `evals/agent.py`, and no judge
    agent.
  - In `evals/scenario.py` and `evals/graders.py`, the new kinds are
    appended after `CalledBefore`, or after any kind AIE-1184 adds, and
    nothing is reordered.
- **Citation drift.** If AIE-1182 rewords a `remembering.py` sentence that
  `remembering-observed-once` cites, the US3.2 citation test fails at
  rebase. The scenario is then re-cited, falling back to the Applying
  memory sentence if needed.

## Public interface changes

### `evals/scenario.py`

```python
CATEGORIES  # gains "applying"


@dataclass(frozen=True)
class ReplyMatching:
    id: str
    pattern: str
    session: int | None = None
    turn: int | None = None


@dataclass(frozen=True)
class ReplyNotMatching:
    id: str
    pattern: str
    session: int | None = None
    turn: int | None = None


@dataclass(frozen=True)
class ContextRecord:
    system: str  # e.g. "event catalog"; rendered as "[From the product's <system>]"
    content: str


type Assertion = ... | CalledBefore | ReplyMatching | ReplyNotMatching
ASSERTION_KINDS  # gains "reply_matching", "reply_not_matching": thirteen kinds


@dataclass(frozen=True)
class Scenario:
    ...  # existing fields unchanged
    index_max_bytes: int | None = None
    context_records: tuple[ContextRecord, ...] = ()
```

- `_KIND_KEYS` gains `"reply_matching": (frozenset({"pattern", "session",
  "turn"}), frozenset({"pattern"}))`, and the same entry for
  `"reply_not_matching"`.
- `session` and `turn` are validated against the scenario's sessions and
  turns by the existing `session_turn` helper.
- `_TOP_KEYS` gains `context_records`. The loader rejects any of the
  following, with a message that names the file and `context_records[i]`:
  - a value that is not a non-empty list;
  - an item that is not a mapping;
  - a key other than `system` and `content`, or a missing key;
  - a value that is not a string, or is blank.

### YAML shapes

```yaml
context_records:              # optional; default none
  - system: event catalog
    content: "Purchase Completed: fires when the payment is authorized."
assertions:
  - kind: reply_not_matching
    id: no-chart-mention
    pattern: "(?i)\\bcharts?\\b|dark[- ]background"
    session: 1                # optional; omitted = any
    turn: 1                   # optional; omitted = any
  - kind: reply_matching      # same keys
    id: example
    pattern: "\\?"
```

### `evals/graders.py` (after the rebase)

```python
def grade(
    scenario: Scenario,
    store: StoreDump,
    trace: Sequence[TraceCall],
    transcript: Sequence[TranscriptTurn] = (),
) -> tuple[AssertionResult, ...]
```

- The parameter is last and has a default, so every existing caller,
  AIE-1184's included, still works.
- `_check` receives the transcript and gains two entries:
  - `ReplyMatching` maps to `_reply_matching(a, transcript)`.
  - `ReplyNotMatching` maps to `_reply_not_matching(a, transcript)`.
- Both helpers select turns where `(a.session is None or t.session ==
  a.session) and (a.turn is None or t.turn == a.turn)`. Selected turns are
  sorted by `(session, turn)`.
- With no turn selected, the detail is `"no reply recorded for session S
  turn T"`, with `any` for an unset filter.
- `_reply_matching` fails when no selected reply has `re.search(pattern,
  reply)`. The detail lists the `(session, turn)` pairs it checked.
- `_reply_not_matching` fails on the first selected turn whose reply
  matches. The detail is `"session S turn T reply matches: <up to 80 chars
  around the match>"`.
- The module docstring says graders are pure functions of the scenario, the
  store dump, the trace, and the transcript (US4.3).
- `evals.graders` still imports neither `mcp` nor `evals.server`.

### `evals/report.py`

- **Rebased onto AIE-1184 at 6e1d259**, which added `_reply_check`,
  `_refresh_reply_check`, and `transcript_error`, and records an unreadable
  transcript (bad UTF-8, deep nesting) instead of raising. `grade_trial`
  uses that same read once for both the reply kinds and the reply check.
- **Deleted transcript.** For a reply-kind scenario, `_grade_is_current`
  is also False when `transcript.json` is gone but `grade.json` still holds
  a reply-check key, so the trial is fully regraded. The regrade writes no
  check key, so it does not repeat.
- **`grade_trial`**:
  - It loads `transcript.json` once and shares the result with `grade` and
    `_reply_check`. `_reply_check` takes the loaded transcript or the load
    error instead of reading the file again.
  - When the file is absent, the transcript is `()`.
  - A malformed transcript is recorded as `transcript_error` and graded as
    `()`, so the reply kinds fail with "no reply recorded" and nothing
    raises.
- **`uses_reply_kinds(scenario) -> bool`**: true when any assertion is a
  `ReplyMatching` or `ReplyNotMatching`.
- **`_grade_is_current(trial_dir, scenario)`**:
  - When `uses_reply_kinds(scenario)`, `transcript.json` joins the mtime
    set, so a newer transcript triggers a full `grade_trial`.
  - Otherwise, AIE-1184's `_refresh_reply_check` path is unchanged.
- **`turn_prompt`**: no AIE-1184 dependency, but it is held with the report
  changes and committed after the rebase. When `scenario.context_records`
  is non-empty, turn 1 renders as:

  ```
  [From the product's event catalog]
  Purchase Completed: fires when the payment is authorized.

  [Newest message]
  <turn 1 text>
  ```

  - For a later turn, the context blocks and one blank line come first,
    then the existing replay, unchanged.
  - Records are separated by one blank line, and content has trailing
    newlines stripped.
  - Without context records, the output is byte-identical to today's.

### `.claude/commands/run-evals.md`

The turn step gains two sentences:

- The `turn-prompt` output, including any `[From the product's ...]`
  blocks, is the whole `Agent` prompt and is passed unchanged.
- The `user` argument of `eval_record_turn` is the scenario's turn text as
  listed in the plan, never the rendered prompt.

No agent file is regenerated.

## Judge

The judge does not change. It already reads `transcript.json`, grades the
named reply, and fails a missing reply. Every new rubric follows US9.6.

## Scenario corpus additions (10)

Each scenario is specified in full in spec.md, "Scenarios". Each file is
`evals/scenarios/<id>.yaml`, and its header comment is `# Prompt:` followed
by the cited sentences, as in the existing files.

| id | source | uses |
| -- | ------ | ---- |
| `filing-second-customer` | `specs/AIE-1049-filing-dedup/spec.md` | |
| `remembering-observed-once` | `specs/AIE-1050-remembering/spec.md` | `context_records` |
| `curated-observed-conflict` | `specs/AIE-1052-curated-applying/spec.md` | `context_records` |
| `applying-relevant-only` | `specs/AIE-1052-curated-applying/spec.md` | `reply_not_matching` |
| `applying-no-trait` | `specs/AIE-1052-curated-applying/spec.md` | `reply_not_matching` |
| `forgetting-ambiguous-that` | `specs/AIE-1053-forgetting/spec.md` | |
| `forgetting-lapsed-expiry` | `specs/AIE-1053-forgetting/spec.md` | |
| `forgetting-system-fact` | `specs/AIE-1053-forgetting/spec.md` | |
| `forgetting-nickname-alias` | `specs/AIE-1053-forgetting/spec.md` | |
| `slots-system-of-record` | `specs/AIE-1055-prompt-slots/spec.md` | `context_records` |

The header of `curated-shared-conflict.yaml` says "the system-of-record
variant is deferred". It is changed to name `slots-system-of-record`.

## Tests

Every new test docstring names "AIE-1185, USx.y".

### Before the rebase

`tests/test_evals_scenario.py`:

- Parse and reject cases for both reply kinds (US1.1) and for
  `context_records` (US2.1).
- The closed-set test gains exactly two kinds.
- The corpus test is updated to 33 ids.
- A `CITATIONS: dict[str, tuple[str, ...]]` table for the ten new ids
  checks that each sentence, with whitespace collapsed, appears in the
  collapsed `build_memory_prompt(REFERENCE_SLOTS)` (US3.2).
- The US3.4 rubric check covers the new scenarios.

### After the rebase

- **`tests/test_evals_graders.py`**:
  - Canned `TranscriptTurn` tuples for US1.2 to US1.4. Each kind gets a
    pass case, a fail case, a missing-reply case, and a filter case.
  - A `grade` call without a transcript.
  - The US1.8 canned replies, graded against the `no-trait-reply` pattern
    loaded from `applying-no-trait.yaml`.
- **`tests/test_evals_report.py`**:
  - `grade_trial` with and without `transcript.json` (US1.5).
  - Regrading when `transcript.json` is newer (US1.6).
  - `turn_prompt` for turns 1 and 2, with one record and with two, plus the
    byte-identical case without records (US2.2, US2.3).
- **`tests/test_evals_end_to_end.py`**:
  - `Driver.turn(session, turn, reply="scripted")`.
  - Twenty new driver functions and ten new `CASES` rows, with the fail
    sets from spec.md.
  - Drivers that write existing files take `expected_version` from the
    index or from `read_file`, as the existing drivers do.
  - The `forgetting-nickname-alias` correct driver uses one `write_file`
    with the remaining line and `aliases=["monday-review"]`.
- **`tests/test_evals_agent.py`**: the two US2.4 sentences in
  `run-evals.md`.

### Offline regression check (US5.7, not in `make check`)

1. Copy `/Users/marksiebert/p/github/wenchang-AIE-1170/evals/runs/20261014-225317-sonnet`
   and `.../20261014-231845-sonnet-merged` under
   `<worktree>/evals/runs/regression-*`.
2. In each copied `trial.json`, rewrite `scenario_path` to the same file
   under `<worktree>/evals/scenarios/`.
3. Delete each copied `grade.json`.
4. Run `uv run python -m evals report <copy>`.
5. Compare each scenario's per-assertion pass counts with the original
   `report.json`. All 23 must be identical.

The orchestrator runs this itself after the rebase. It is a Bash and
file-copy step under `evals/runs/`, which is gitignored.

## Docs

- **ADR 0032**, "Transcript-graded assertions and context records". It
  amends ADR 0028:
  - §3: graders are pure functions of (scenario, store dump, trace,
    transcript), and `transcript.json` is a grading input.
  - §7: a paraphrased reply now affects `reply_matching` and
    `reply_not_matching`, not only the judge. US5.6 spot-checks this.
  - It also records `context_records`, its rendering, and why it stands in
    for lookup tools the eval agent lacks; the closed set at thirteen
    kinds; the corpus at 33; and the merge order after AIE-1184.
- **ADR 0028**: dated (2026-10-16) in-place pointers, "Amended by ADR 0032",
  under §3 and §7. No other change.
- **ARCHITECTURE.md**: the `evals/` entry gets thirteen assertion kinds,
  `transcript.json` as a grading input, and `context_records` (US4.4).
- **AIE-1170 `spec.md`**: its "Deferred scenarios" bullet points to this
  spec.
- **`review-pr.md`**: the live-run gate (US5):
  - the 2/3 floor;
  - the miss classification;
  - the third-person judge-noise label;
  - the read counts for the two applying scenarios;
  - the verbatim spot-check;
  - the offline regression result;
  - these commands:

  ```
  # one headless session per shard, k = 1 and 2
  CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 --judge --shard k/2 <the ten ids>" --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
  uv run python -m evals merge-runs evals/runs/<name> <shard run dirs>
  ```

## Design decisions

| Decision | Rejected | Why |
| -------- | -------- | --- |
| Deterministic `reply_not_matching`, with a `reply_matching` counterpart | judge-only scenarios | Judge verdicts never reach the deterministic count, so a wrong scripted driver could not fail. Narrow regexes catch the named mistake, and the judge covers the meaning |
| No `applies-sql-style` assertion | `reply_matching` on lowercase SQL | Brittle (review blocker 4) |
| An assertive second-person `no-trait-reply` pattern with negation guards | a bare "work late" pattern | A reply may mention the late night to say it is not a habit, and that is allowed |
| `grade` takes the transcript as an optional fourth parameter, and AIE-1185 owns that change after AIE-1184 merges | AIE-1184 changes `grade`; a separate `grade_replies` | Keeps one result list per trial and one transcript loader, and leaves existing callers unchanged |
| `context_records` rendered by `turn-prompt` | a memory seed; the user quoting the catalog; a per-scenario agent file; the name `systems_of_record` | A seed contradicts "never copy their contents into memory". A quote makes the user surface the discrepancy. The agent file is fixed per run, and its sha256 is recorded. The name `systems_of_record` collides with the prompt slot |
| Observations arrive as context records in `remembering-observed-once` and `curated-observed-conflict` | the user describing them | An observation the user states becomes a statement. A record is session data, which matches `[observed]` |
| `forgetting-lapsed-expiry` gives context in the turn and uses a cutover subject | a date-only lapse; reusing "v3 migration" | The prompt says a lapsed fact is "not to be removed automatically". A distinct subject keeps it apart from `remembering-expiry` |
| A new category, `applying` | the `curated` category | These scenarios test the Applying memory section |
| ADR 0032, with pointers in 0028 | rewriting 0028 | It amends two decisions of an accepted ADR |
