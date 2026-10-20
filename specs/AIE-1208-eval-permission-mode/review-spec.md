# Spec Review: AIE-1208 — Run eval sessions outside auto mode; record the full reply

## What & why

Auto mode injects `SubagentHandback` into eval subagents, so about 7% of
recorded replies (68 of 1,428) were third-person summaries. `--permission-mode
dontAsk` (plus one `Edit` rule so `judge.json` still writes) removes it, but
then the Agent tool returns only the subagent's last text block, losing text
before its last tool call. The server therefore records the reply from the
subagent's own transcript, and a hardened preflight exercises that route live.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1-3 | run-evals.md, AGENTS.md, README.md, ADR 0028 | scanned | launch commands carry `--permission-mode dontAsk` and `"Edit(evals/runs/**)"` |
| 4-7 | run-evals.md preflight | read | new prompt (index call first, marker last); pass needs all 7 tools, no other, error-free `get_memory_index`, marker as last line of the recorded reply |
| 8-9 | docs, worktree | reviewed, `make check` | ADR 0035 and dated pointers; check passes (no unit test) |
| 10 | run-evals.md | read | stop on a denied call; stop if `judge.json` is missing |
| 11-13 | transcript fixture | parsed | texts joined by blank line, uuid deduped; lookup errors on 0/2 matches or bad id; config dir honoured |
| 14-16 | `EvalState` | record a turn | with transcripts root: reply from transcript, `agent_result` kept, errors record nothing; without: unchanged |
| 17 | run-evals.md | read | step 3.2 requires `agent_id`; preflight records the turn and reads `transcript.json` |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| `dontAsk` on every launch command | none | Probed: only the 7 memory tools |
| Add `Edit(evals/runs/**)` | `acceptEdits`; broad `Edit` | `dontAsk` denies the judge's Write; only `Edit(path)` gates writes |
| Record reply from the subagent transcript (D6) | preamble asking for one final message | Preamble changes the measured prompt and fails silently; transcript matches what a host shows |
| Preflight and D5 stop on silent denials | continue silently | `dontAsk` denies without a prompt |
| New ADR 0035; pointers in 0028/0031/0032 | rewrite old ADRs | History stays; 0034 reserved by PR #41 |

## Files/modules to be touched

- `evals/subagent_transcript.py` (new), `evals/graders.py`, `evals/server.py`
- `.claude/commands/run-evals.md`, `tests/test_evals_agent.py`, new and existing evals tests
- `AGENTS.md`, `README.md`, `ARCHITECTURE.md` (one link)
- `docs/adr/0028-*.md`, `0031-*.md`, `0032-*.md`, new `docs/adr/0035-eval-sessions-dontask.md`

## Open questions / assumptions

- Decision note: D2 goes beyond the issue's literal fix; it keeps `--judge`
  writing `judge.json`.
- Decision note: D6 reverses ADR 0028 decision 7 (no reading Claude Code's
  transcript layout); accepted because the alternative fails silently.

## Risks

- D6 depends on Claude Code's internal transcript layout; mitigated by loud
  failures, a fixture test, and the live preflight.
- Recorded replies now include pre-tool-call text, so reply-text checks,
  third-person counts, judge grades, `unmatched_reply_paths`, and the turn
  replay shift; the post-merge baseline resets them.
- A transcript flush race is guarded by a substring check and a short retry
  (`transcript_retry_s`).
- Preflight check (b) is self-reported; a mechanical check from the
  transcript's tool list is a possible follow-up. A custom `CLAUDE_CONFIG_DIR`
  may not reach the server; `--transcripts-root` is the lever.
- `dontAsk` could deny something else the runner needs; mitigated by D5, the
  preflight stop, and the clean baseline.
