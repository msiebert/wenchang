# Spec Review: AIE-1384 — Test alternative names for get_memory_index

## What & why

Clients that drop MCP `instructions` only see the memory rules if the model
calls `get_memory_index` first. The name may undersell it. This adds eval
"arms" (an index tool name, and the agent prompt on or off), a `compare`
command, and a pre-registered five-name experiment. Rename only if a name
clearly beats the baseline. No change to `src/`.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | No `arm.json` | Server, agent file, `new-run` | Identical to today; committed agent file unchanged; default arm recorded |
| 2 | `set-arm --index-tool load_memory --no-agent-prompt` | Runs | `arm.json` written; agent file tools line swaps the name; body is the preamble only |
| 3 | Arm with prompt on, tool X | Agent rendered | Preamble + memory prompt, `get_memory_index` replaced by X |
| 4 | Invalid name; bad `arm.json` | `set-arm`; `load_arm` | Exit 2, nothing written; `ArmError` |
| 5 | Arm X | Server lists tools | X replaces the index tool; descriptions differ only by the name |
| 6 | Arm X | X called | Prompt block uses X; `structured_content` unchanged |
| 7 | Arm X | X called | Trace says `get_memory_index`; graders need no change |
| 8 | Any arm | Server built | Instructions stay neutral |
| 9 | An arm | `new-run`, `merge-runs` | `run.json` and report show the arm; mixed arms exit 2; old runs read as default |
| 10 | Run dirs | `compare` | Markdown table: call-first, label, pass rates, deltas vs baseline; exit 2 on differing scenarios |
| 11 | `run-evals.md` | Runner follows it | Preflight uses the arm's tool; arm procedure documented |
| 12 | Five live arms | Results in | `eval-report.md` plus an ADR with the decision |
| 13 | Change | `make check` | Passes |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Gitignored `evals/arm.json` written by `set-arm`, read by server and agent renderer | Env var in `mcp.json`; a public rename parameter on `register_memory_tools` | Env expansion is client-side and does not regenerate the agent allowlist; no public API change for an experiment |
| Rename eval-side by substituting `get_memory_index` | Hand-written description per candidate | Only the name varies; wording is not confounded |
| Bare agent body for experiment arms | Keep the memory prompt in the agent body | The prompt already says to call the index first, so names would barely matter |
| Trace keeps the canonical name | Per-arm scenario and grader changes | No scenario or grader edits |
| Rename deferred to a follow-up if a name wins | Rename in this PR | Keeps this PR to eval tooling |

Pre-registered: all arms prompt off, Sonnet 5.5 (`--model sonnet`), 3 trials, 10 panel scenarios.
Rename only if call-first is up 15+ points and label and pass rates are each
down 5 or fewer. Highest call-first wins ties.

## Files/modules to be touched

- `evals/arm.py`, `evals/compare.py` (new); `evals/agent.py`, `evals/server.py`, `evals/__main__.py`, `evals/report.py`
- `.claude/agents/wenchang-eval.md`, `.claude/commands/run-evals.md`, `.gitignore`
- `tests/` (new files only); ADR and evals docs; later `eval-report.md`

## Open questions / assumptions

- Is 3 trials x 10 scenarios x 5 arms (150 trials) the right budget, or more trials on fewer scenarios?
- Is the 15-point / 5-point rule right?
- If a name wins: rename in this PR or a follow-up issue? Recommended: follow-up.
- Run the optional reference arm (default name, prompt in agent)?
- Assumes live runs happen in a separate session; each arm needs a fresh one.

## Risks

- Noise: 30 trials per arm cannot detect small effects; the rule acts only on large ones.
- `set-arm` rewrites the committed agent file. Forgetting `set-arm --reset` leaves a dirty tree; `new-run` warns on a non-default arm and `run-evals.md` says to reset.
- Substitution also renames prose mentions. Accepted, since only the name should vary.
