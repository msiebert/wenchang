# Implementation Plan: AIE-1208 dontAsk eval sessions and transcript-recorded replies

**Spec**: [spec.md](spec.md)

## Public interface

Edit ownership: the guard hook resolves paths against the main repo
(`CLAUDE_PROJECT_DIR`), so worktree edits are outside its scope; roles follow
the AGENTS.md table. test-writer: `tests/**`. implementer: `evals/**` and
`.claude/commands/run-evals.md`. doc-updater: AGENTS.md (no owner in the table;
one-line command change), README.md, ARCHITECTURE.md, `docs/adr/*`, `specs/*`.

### New `evals/subagent_transcript.py` (implementer)

```python
class SubagentTranscriptError(Exception): ...

def default_projects_root() -> Path:
    # Path(CLAUDE_CONFIG_DIR) / "projects" if set and non-empty,
    # else Path.home() / ".claude" / "projects"

def find_subagent_transcript(projects_root: Path, agent_id: str) -> Path:
    # agent_id must match ^[A-Za-z0-9_-]+$; exactly one match of
    # */*/subagents/agent-<agent_id>.jsonl, else SubagentTranscriptError
    # (message names agent_id and the root)

def reply_from_transcript(path: Path) -> str:
    # text blocks of every type "assistant" entry in file order, deduped by
    # uuid, stripped, empties dropped, joined with "\n\n";
    # SubagentTranscriptError on a malformed JSON line or no text

def read_subagent_reply(projects_root: Path, agent_id: str) -> str:
    # find + reply
```

### `evals/graders.py`

`TranscriptTurn` gains `agent_result: str | None = None` (last field).
`transcript_to_json` emits `"agent_result"` only when not None.
`load_transcript` accepts an optional str `agent_result`; a non-str non-null
value raises in the existing error style.

### `evals/server.py`

- `EvalState.__init__(self, runs_root=RUNS_DIR, clock=time.monotonic,
  transcripts_root: Path | None = None, transcript_retry_s: float = 2.0)`.
- `record_turn` stamps the boundary first, normalizes `agent_id` to its first
  whitespace token, and checks the reconstruction's last text block
  (whitespace-normalized) is a substring of the normalized passed reply; else
  it re-reads until `transcript_retry_s`, then raises.
- `reply_from_transcript` skips `isApiErrorMessage: true` and
  `message.model == "<synthetic>"` entries and ignores `thinking` blocks. The
  not-found error names the root and `--transcripts-root`. `evals/mcp.json` is
  unchanged.
- `record_turn` with `transcripts_root` set: `agent_id` None raises
  `SubagentTranscriptError`; otherwise `reply = read_subagent_reply(...)` and
  `agent_result` is the passed reply. Errors raise before anything is recorded.
  Without `transcripts_root`: unchanged, `agent_result` None.
- Tool `eval_record_turn` returns `_error(str(exc))` on
  `SubagentTranscriptError`; its description says the reply is read from the
  subagent transcript by `agent_id`.
- `main()` gains `--transcripts-root` (default `default_projects_root()`) and
  builds `EvalState(runs_root=..., transcripts_root=...)`.

### `.claude/commands/run-evals.md` (implementer)

- Step 0 commands: the pinned commands in spec.md; each on one line.
- "What each part does": entries for `--permission-mode dontAsk` and
  `Edit(evals/runs/**)`.
- Preflight: D3 prompt, steps, and pass checks (a) to (d), failure text.
- Step 3.2 "Record the turn": pass `reply=<the Agent result text>` and
  `agent_id=<the agentId the Agent result reports>`; the server replaces the
  reply with the subagent's full text from its transcript; `agent_id` is
  required.
- D5 rules: Bash limits, stop on a denied call, `judge.json` existence check.

## Tests (test-writer, tests first)

- `tests/test_evals_agent.py`: update `LAUNCH`; add `SHARD_LAUNCH`; AC3-AC7,
  AC10, AC17 on normalized text (AC7 slices between the "What each part does"
  heading and "## 1. Preflight").
- New `tests/test_evals_subagent_transcript.py`: AC11-AC13 with a `tmp_path`
  JSONL fixture.
- Server and graders tests: AC14, AC14b, AC15, AC16; scripted drivers keep building
  `EvalState` without a transcripts root.
- Docstrings cite `AIE-1208, ACn`. AC8 and AC9 have no unit test by design.

## Docs (doc-updater)

AGENTS.md and README.md commands; ADR 0028 (decisions 6 and 7, the note); ADR
0031 amendment; ADR 0032 pointer; new ADR 0035 from the MADR template;
ARCHITECTURE.md link (and the new module if the evals bullets list modules);
`review-pr.md`.

## Gate

`make -C /Users/marksiebert/p/github/wenchang-AIE-1208 check` green. The
orchestrator runs the live preflight probe through the harness and, after
merge, a clean N=6 baseline.
