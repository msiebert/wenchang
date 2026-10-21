# Implementation Plan: AIE-1198 Reply paths quote the tool's path, checked against the trace

**Spec**: [spec.md](spec.md)

## Public interface

### `evals/graders.py` (new names, added to `__all__`)

```python
PATH_ROOTS: Final[frozenset[str]]
# REFERENCE_SCOPES | {"org", "system"}; the scenario's grant keys are added per call.


@dataclass(frozen=True)
class UnmatchedReplyPath:
    """A scope-rooted path in a reply that no tool result named up to that turn."""

    session: int
    turn: int
    token: str  # normalized: root onward, "/"-joined, no leading or trailing "/"
    kind: str  # "entity_omitted" or "unmatched"


def find_unmatched_reply_paths(
    scenario: Scenario,
    trace: Sequence[TraceCall],
    transcript: Sequence[TranscriptTurn],
) -> tuple[UnmatchedReplyPath, ...]: ...
```

Rules are spec US2.1-2.5. Notes for the implementer:

- Token regex on the raw reply: `[A-Za-z0-9_.~/-]*/[A-Za-z0-9_.~/-]*`, then
  `rstrip(".,;:!?")`. URL skip (spec 2.2):
  `re.search(r"[A-Za-z][A-Za-z0-9+.-]*:$", reply[:start])`, or the run starts
  with `//`, or a segment before the first root contains `.`.
- Normalize: split on `/`, drop empty segments, cut before the first root,
  join with `/`.
- Two-segment rule, known areas, and known entity ids: spec 2.2.
- Echo: the normalized token is in the set of normalized tokens extracted
  (same extraction, no echo rule) from the session's user texts up to and
  including this turn.
- Known locations: walk each eligible `result` recursively (dict values and
  list items), depth limit 32, collecting `str` values whose key is `path` or
  `prefix`. Strip one leading and trailing `/`. Add every proper directory
  prefix (segment-wise).
- Call eligibility is by session/turn tags only; trace order is irrelevant.
- `entity_omitted`: for some known location K (directories included) with at
  least 3 segments, K with its second segment removed equals a candidate or
  ends with `/` + candidate.
- Per reply: distinct tokens only, first-appearance order; replies in the
  transcript's given order.

### `evals/report.py`

No new public names. Private changes:

- `_REPLY_CHECK_KEYS` becomes `("third_person_replies",
  "unmatched_reply_paths", "transcript_error")`.
- `_reply_check(trial_dir, scenario, trace, transcript, error)` takes the
  trace too and returns both lists (or only `transcript_error`, or `{}`).
  `grade_trial` passes the loaded trace; `_refresh_reply_check` loads
  `trace.json` with `load_trace`, and when it is missing or raises
  (`GradeInputError`, `ValueError`, `RecursionError`) passes `None`, so
  `unmatched_reply_paths` is omitted (spec 2.7).
- `_load_grade` validates `unmatched_reply_paths` (list of objects with
  `session`/`turn` int and `token`/`kind` str), raising `GradeInputError`
  like the third-person list.
- `build_report` adds `reply_path_trials`, `reply_path_unchecked_trials` per
  scenario and `reply_paths` at run level (spec US2.8). `_markdown` gains
  the total line and per-scenario "Unmatched reply paths:" line.

`grade.json` shape: adds `unmatched_reply_paths`. `report.json` adds the
fields in US2.8. Nothing else changes.

### `src/wenchang/prompts/overview.py`

`BODY` gains the Goal 1 sentence as its second sentence; lines wrapped at
100 columns. `HEADING` unchanged.

## Tests (test-writer, `tests/` only)

- `tests/test_evals_graders.py`: unit tests for US2.1-2.5 with hand-built
  `TraceCall`/`TranscriptTurn` values. At least: exact match; missing `.md`;
  backticks, parens, bold; leading `/`; trailing punctuation; directory
  reference; `system/` suffix match; `entity_omitted`
  (`project/metrics/dau.md`); `unmatched` (wrong name); a path only known from
  a later turn is flagged; a path from an earlier session counts; untagged
  call counts; failed-call result path counts; arguments do not count;
  nested `entries[].path` and `capped[].prefix`; scheme URL and `//` run
  skipped; `www.x.com/user/y` skipped; `Saved to: user/u-ada/...` (colon then
  space) still checked; single-segment `user/` skipped; all-root
  `user/project` skipped; two-segment prose `user/session` skipped while
  `user/preferences` (known area) is flagged `entity_omitted`; depth beyond 32
  ignored; echo of user text
  skipped; a grant-key scope root from the scenario identity; duplicate token
  in one reply reported once; result order.
- `tests/test_evals_report.py`: US2.6-2.8 (grade.json field, transcript
  error, no transcript, refresh adds the field to an old grade.json and does
  not touch `results`/`passed` or the file when unchanged, refresh with a
  missing or malformed `trace.json` omits the field and does not raise,
  `_load_grade`
  rejects a malformed list, report fields and markdown lines, merge).
- `tests/test_prompts_overview.py`: US1.1, 1.2 (no backtick except `path`;
  no scenario area/file names), 1.4.
- `tests/test_evals_end_to_end.py` and `tests/test_evals_scenario.py`: US3
  drivers, exact fail sets, corpus set, US3.5.
- `tests/test_evals_agent.py` already pins the rendered agent file (US1.5).

Docstrings cite `AIE-1198, USx.y`.

## Held-out scenarios (implementer writes yaml under `evals/scenarios/`)

Spec US3.1-3.4, verbatim turns, ids, patterns. `# Prompt:` headers cite
existing sentences only (for example the overview's addressing sentence,
the Scopes ask rule, and the Applying-memory guidance).

## Docs (doc-updater)

- ADR `docs/adr/0033-reply-path-check.md`: context, decision (spec US2),
  rejected alternatives (spec Goal), consequences with the US2.9 numbers and
  false-positive review, limits.
- ARCHITECTURE.md `evals/` bullets: graders gain the reply-path check;
  report records it apart from pass counts.
- `specs/AIE-1198-reply-paths-quote/review-pr.md` with the US5 live gate.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1198 check` green.
