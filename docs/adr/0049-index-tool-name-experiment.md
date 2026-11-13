# 0049. Experiment design for the index tool name

Date: 2026-11-13

## Status

Proposed. Builds on [ADR 0028](0028-behavioral-eval-harness.md) (the eval
harness) and [ADR 0048](0048-guidance-in-tool-descriptions-and-index-result.md)
(rules delivered in the `get_memory_index` result). The decision is pending the
live runs.

## Context

AIE-1384. Since ADR 0048, the memory rules reach clients that drop MCP
`instructions` only if the model calls `get_memory_index` first. The name may
undersell the tool. The issue asks whether another name raises call-first
compliance, and to rename only if a name clearly beats the baseline.

The eval harness does not yet model such a client. The eval server already
sends neutral instructions, but the subject agent's body carries the full
memory prompt, so the subject is told to call the index regardless of its name.

## Decision

Add eval "arms" and pre-register the experiment. No change to `src/` or the
public API.

- **Arms.** An arm is an index tool name plus an `agent_prompt` on/off switch.
  It lives in the gitignored `evals/arm.json`, written only by
  `python -m evals set-arm` and read by the eval server and the agent
  renderer. No file means the default arm (`get_memory_index`, prompt on), and
  every output is unchanged. Names are validated in `evals/arm.py`.
- **Name substitution is eval-side.** The eval server replaces
  `get_memory_index` with the arm's name in tool descriptions and in the
  prompt block of the index result. Nothing else differs, so only the name
  varies.
- **Bare agent body.** With `agent_prompt` off, the agent body is the eval
  preamble only, which models a client that drops instructions.
- **Trace keeps the canonical name.** The server records `get_memory_index`
  in the trace for any arm, so scenarios and graders need no changes.
- **Recording and comparison.** `new-run` records the arm in `run.json`,
  `report.md` shows it, and `merge-runs` refuses runs with different arms.
  `compare` builds one markdown table (call-first rate, label rate, pass
  rates, deltas against a baseline).
- **Pre-registered design.**
  - Arms: `get_memory_index` (baseline), `load_memory`,
    `get_memory_rules_and_index`, `start_memory_session`,
    `get_memory_entrypoint`. All with `agent_prompt` off.
  - Model: Sonnet 5.5 (`--model sonnet`), 3 trials per scenario.
  - Panel (10 scenarios): `remembering-stated-name`,
    `remembering-observed-once`, `remembering-stated-role`,
    `remembering-fact-about-user`, `remembering-preference-mid-task`,
    `recall-across-sessions`, `filing-new-acronym`, `privacy-account-number`,
    `forgetting-one-fact`, `curated-correction`.
  - Each arm runs in its own freshly launched session, because Claude Code
    loads the MCP server and agent file at session start.
- **Decision rule.** Rename only if a candidate's call-first rate is at least
  15 points above the baseline AND its label rate and overall pass rate are
  each no more than 5 points below the baseline. If several qualify, the
  highest call-first rate wins. Otherwise keep `get_memory_index`.

Rejected alternatives:

- **Rename in `src/` and compare by git history.** Ships a breaking change
  before there is evidence, and needs a release per candidate.
- **Keep the agent prompt on.** The subject is told to call the index, so name
  would not matter and the result would not model the affected clients.
- **Edit scenarios or graders per arm.** The trace keeps the canonical name
  instead, so the same assertions grade every arm.
- **Env vars or CLI flags instead of `arm.json`.** The agent file and MCP
  server load at session start, so the arm has to be on disk for both to
  read; one file keeps them in step.
- **No pre-registered rule.** A rule fixed before the runs avoids picking a
  winner from noise.

## Decision outcome (Result)

Pending. This section will be filled in after the live runs: the `compare`
table (saved as `specs/AIE-1384-memory-tool-name-eval/eval-report.md`) and
whether the rule says to keep or rename.

## Consequences

- The harness can compare any set of index names on a bare-agent setup, and
  normal eval runs are unchanged.
- 30 trials per arm cannot detect small effects. The rule acts only on large
  ones, so a null result means "no clear winner", not "no difference".
- The eval server renames the registered tool through the `MCPServer`
  private managers, as `register_memory_tools` already does under the `mcp<3`
  pin.
- Substitution also renames mentions in prose. Accepted, since only the name
  should vary.
- If a name wins, the rename is a follow-up with its own ADR and a CHANGELOG
  breaking-change entry.
