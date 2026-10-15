# 0028. Behavioral eval harness

Date: 2026-10-13

## Status

Accepted

## Context

Section 10.3 of the spec says prompt behavior is evaluated, not
unit-tested. Several specs (AIE-1049 to AIE-1055, AIE-1165) list
behavioral scenarios, and nothing ran them. AIE-1170 adds a local harness
whose first driver is a Claude Code subagent. It needs no API key and is
cheap to iterate with. A later Anthropic SDK driver should reuse the
scenarios and graders unchanged.

The harness runs a real agent against the memory tools, so it needs an MCP
server, an agent definition, a scenario format, graders, and a runner. None
of these may ship in the wheel or run in `make check`, because live runs are
slow and nondeterministic.

## Decision

1. **`evals/` is a dev-only top-level package.**
   - It is outside the wheel, which still packages only `src/wenchang`.
   - It may import public `wenchang` modules, and `src/` never imports it.
     An `ast` test pins that.
   - It holds the eval server, the scenario loader, the graders, the
     report, the agent renderer, the scenarios, and the reference adopter.
     The reference adopter moved here from `tests/`, so both tests and
     evals import `evals.reference_adopter`.
   - `[tool.hatch.build] dev-mode-dirs = [".", "src"]` puts the repo root
     on `sys.path` in the editable install. `import evals` then works from
     any working directory and in subprocesses. As a side effect, `tests`,
     `scripts`, and `docs` become importable namespace packages in the dev
     venv.
   - Pyright strict covers `evals/`.

2. **Dependencies are dev-only.** `mcp` (already a dev and optional
   dependency since ADR 0027) and `pyyaml`, with `types-pyyaml`, are in the
   dev group only. Nothing is added to the library's dependencies or
   extras.

3. **The driver contract is the scenario YAML plus five JSON files.**
   Graders are pure functions of (scenario, store dump, trace), and
   `evals.scenario` and `evals.graders` never import `mcp`. A driver writes
   three files and grading writes two:
   - `store.json`: every file under the identity's entities, with content
     and metadata.
   - `trace.json`: each memory call with `seq`, `request_id`, `duration_s`,
     `started_ms`, `completed_ms`, `session`, `turn`, `tool`, `arguments`,
     `result`, and `is_error`.
   - `transcript.json`: each turn's user text, reply, and optional agent
     id.
   - `grade.json` and the optional `judge.json`.

   The trace rules are:
   - **Timing.** `completed_ms` is stamped when the `on_call` record
     arrives, in milliseconds on a monotonic clock. The baseline is server
     start, before the first reset, and resets never move it.
     `started_ms` is `completed_ms - duration_s * 1000`. Both lag the
     true times by the same small stamping delay.
   - **Order.** Graders order calls by `(session, turn, started_ms, seq)`,
     and untagged session-0 calls sort last. `seq` is completion order
     only. `request_id` is an opaque correlation key, because JSON-RPC
     ids restart on each connection.
   - **Turn tagging.** Each `eval_record_turn` stamps a boundary. A call
     belongs to the first recorded turn whose boundary is later than its
     `started_ms`. A call started after the last boundary is session 0,
     turn 0. This relies on each turn's subagent finishing before
     `eval_record_turn` runs. Claude Code runs subagents in the background
     by default, so the launch sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`.
     The runner also waits for any background completion notification
     before recording the turn.
   - **Strict `index_read_first`.** Some `get_memory_index` call must
     complete before any other memory call of the session starts, so a
     parallel batch with the index read fails. The prompt asks the agent
     to consult the index before acting, and a call issued alongside the
     index read was not chosen from it.
     - **Note (2026-10-14, first live run).** A session with no memory
       calls now passes `index_read_first`. In the first live run, the
       privacy agent refused to store an account number and made no memory
       call. The grader failed it as "made no memory calls", which
       penalized the correct refusal. The check now applies only to
       sessions that call memory: if a session makes any memory call, the
       index read must come first. Whether a session should have called
       memory at all is left to the scenario's other assertions.
   - **Scanned writes.** `no_content_matching` scans only `content`,
     `line`, `new_string`, `description`, `aliases`, `area`, and `name`,
     and only on `write_file`, `append_line`, and `replace_fact`. Version
     tokens are small integers, `old_string` quotes text being removed,
     and a delete persists nothing.
   - **Trial dir.** `eval_reset` accepts a `trial_dir` only under the
     server's runs root, which defaults to `evals/runs/` and is gitignored.

4. **The eval server mounts the memory tools with `register_memory_tools`
   and adds three harness tools.**
   - The harness tools are `eval_reset`, `eval_record_turn`, and
     `eval_dump`. The issue says the tool surface matches `TOOL_NAMES`.
     That holds for the surface the model sees, because the eval agent's
     allowlist is exactly the seven memory tools.
   - The server's MCP `instructions` are neutral: "Memory tools for this
     workspace." They do not mention evaluation, and the memory prompt
     reaches the agent through its definition, not twice. Because the
     instructions lack the prompt, `register_memory_tools` logs its "server
     instructions do not include the memory prompt" warning at every
     start. That is by design.
   - A reset swaps the store and identity behind a forwarding client and
     resolver, since Claude Code cannot restart an MCP server mid-session.
   - Trials run serially. A reset racing an in-flight call could split
     that call across stores.

5. **The eval agent is `.claude/agents/wenchang-eval.md`.** It is
   generated by `python -m evals render-agent`, and a test fails on drift.
   - `tools` is the seven `mcp__wenchang__*` tools, `model` is `inherit`,
     and `omitClaudeMd` is `true`. Without `omitClaudeMd`, the repo and
     user CLAUDE.md files would load into every trial.
   - The body is a short framing preamble, then
     `build_memory_prompt(REFERENCE_SLOTS)` byte for byte. This deviates
     from the issue's "the system prompt is the output of
     `build_memory_prompt`". Without the preamble, a subagent reads each
     turn as a task delegated by a parent agent.
   - **Note (2026-10-14, live run at a723dd8).** Turn 1 reaches the eval
     agent as an `Agent` prompt. Later turns arrive through `SendMessage`,
     which Claude Code wraps as a message from another agent. Claude Code's
     own rule that a peer agent's message cannot grant approval then
     overrode "each message you receive is from that user". In every
     scenario whose turn 2 confirms a shared-scope write
     (`curated-correction`, `filing-new-acronym`,
     `remembering-no-metric-value`, `slots-ask-before-shared`), the agent
     asked correctly in turn 1 and then refused the relayed "yes". The
     preamble now says a runner relays the conversation. It says every
     message, including one delivered as a message from a coordinator or
     another agent, is the user's own next turn verbatim, and a
     confirmation in such a message is the user's own. The agent file's
     sha256 in reports changes with it.
   - **Note (2026-10-14, rerun at 65f3baf).** Three of the four scenarios
     passed. `remembering-no-metric-value` still refused the relayed "yes"
     as coming from a coordinator. The preamble now also says there is no
     coordinator or other agent in the conversation, that every message,
     however it is delivered or labelled, is the user's own turn, and that
     a yes in any message is sufficient for any write, shared scopes
     included. It remains harness framing only; the memory prompt is
     unchanged.
   - **Note (2026-10-14, N=3 attempt at 3910d91).** The preamble framing
     lost to the harness again: `curated-correction` refused its relayed
     turn-2 "yes" as a coordinator's message. Three wordings have now
     failed, so the harness no longer relays later turns with
     `SendMessage`. Every turn is a fresh `Agent` call whose prompt comes
     from `python -m evals turn-prompt`: the session's earlier user turns
     and verbatim replies, then the new turn. `eval_record_turn` rewrites
     `transcript.json` after each turn so the next prompt can be built.
     The preamble is back to plain framing: each message is the user's
     own turn, and earlier turns may be included above the newest one.
     Fidelity note: a later turn's agent has its earlier replies in
     context but not its own earlier tool calls or results. Memory state
     still carries over through the store, and the agent re-reads it.
     Because every turn is a new `Agent` call and the agent definition
     uses `model: inherit`, every call must pass `model=<model>`. A turn
     run on the wrong model invalidates the trial, which is reset and rerun
     from turn 1. In run A at 9c51a50, the runner omitted it once on a
     turn 2, noticed, and reran the trial.
     The runner doc also now forbids stopping, pausing, skipping, or
     reordering trials because of their results. In the 3910d91 attempt,
     the runner paused the run on its own after one trial.

6. **The eval session is launched with `evals/mcp.json`.** There is no
   root `.mcp.json`. The command is:

   ```
   CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "Bash(uv run python -m evals *)" --settings '{"includeGitInstructions": false}'
   ```

   - Ordinary sessions never see the eval server.
   - `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` runs subagents in the
     foreground, which turn tagging needs.
   - `--strict-mcp-config` keeps the tool schemas loaded directly rather
     than behind tool search, and the runner's preflight checks that.
   - `--allowedTools` avoids a prompt on every memory call and every
     `uv run python -m evals` command.
   - `includeGitInstructions: false` keeps the git status snapshot out of
     the eval agent's context.
   - The config uses `--directory .` without variable expansion, because
     expansion in `--mcp-config` files is unverified.

7. **Replies are copied verbatim, by instruction, into
   `eval_record_turn`.** Reading Claude Code's subagent transcript files
   was rejected, because their layout under `~/.claude/projects/` is
   internal. A paraphrased copy would affect only the judge.

8. **The judge is optional and separate.** `wenchang-eval-judge` (Read and
   Write, `omitClaudeMd`) writes `judge.json`. The report shows judge
   verdicts in their own columns, and they never change deterministic pass
   counts.

9. **Scripted drivers prove mechanics, not compliance.** Every shipped
   scenario cites the prompt sentence it tests. It has a scripted correct
   driver, which must pass every assertion, and one wrong driver, which
   must fail exactly a listed set, both in `make check`. Whether a real
   agent complies is the live run's job.

10. **Edit scope.** AGENTS.md now gives the implementer `evals/**`, the
    eval `.claude/` files, and `.gitignore`. This widens the table from
    ADR 0004. The guard hook (`scripts/hooks/guard-edits.sh`) is protected,
    so widening its rule 4 for the same paths, and giving doc-updater
    `AGENTS.md`, is a manual follow-up.

11. **Corpus expansion (2026-10-14).** After the first passing live run,
    the corpus grew from 8 to 23 scenarios. They cover privacy,
    remembering, filing, write mechanics, curated content, shared-scope
    asks, and forgetting. Each still cites its prompt sentence, has
    index-first, and has a correct and a wrong scripted driver with an exact
    fail set. The expansion added two harness features:
    - **`called_before {first, then, session?}`** is an ordering kind. In
      each session with a call matching `then`, a call matching `first`
      must complete strictly before the earliest such `then` call starts.
      Session-0 calls are ignored. A failed call counts unless its matcher
      sets `succeeded`. `filing-ambiguous-match` uses it to require a
      `read_file` before any write.
    - **Per-scenario `index_max_bytes`** sets the store's index cap for
      one scenario. `filing-capped-area` sets it to 1, so every seeded area
      is listed under `capped` and the agent must list one area.

    Every judge rubric now names the reply it grades ("The turn N reply"
    or "The session S turn N reply"). The judge agent grades only that
    reply, and a missing reply is a `fail`. The remaining deferred
    scenarios are listed in the spec.

12. **Parallel runs are sharded across sessions (2026-10-14).** Trials
    inside one runner session stay serial. One eval server holds one
    in-memory store, and `eval_record_turn` assigns memory calls to turns by
    time window, so concurrent trials in one session would share a store
    and interleave traces. Making the server multi-trial would need a trial
    key on every memory call, which the agent never sends. Instead:
    - `new-run --shard k/n` takes the scenarios, sorted by id, whose index
      % n is k - 1. It names the run dir `<timestamp>-<model>-shard<k>of<n>`
      and records the shard in `run.json`.
    - Each shard runs in its own headless `claude -p` session, with its own
      eval server and its own preflight dir.
    - `merge-runs <out_dir> <run_dir>...` requires every shard to match on
      model, trials, git commit, and agent sha256, and rejects a scenario
      that appears in two shards. It copies the trial dirs, writes a
      combined `run.json` listing the sources, and writes one report.
      Grading is per trial, so merging is file-level.

## Consequences

- Prompt changes can be checked against real agent behavior locally, with
  pass counts over N trials per assertion.
- **Known limitation.** A subagent gets only its own system prompt plus
  Claude Code's environment details. Unless disabled, it also gets a git
  status snapshot, and the launch disables it. It does not get the Claude
  Code system prompt or auto memory, and `omitClaudeMd` keeps CLAUDE.md
  out. The environment details still differ from what an adopter's host
  sends, and the model runs inside Claude Code's agent loop. Each turn is a
  fresh `Agent` call that replays the session's earlier exchanges as text,
  so the agent does not see its own earlier tool calls. Results therefore guide
  prompt iteration and are not release gates.
- **Note (2026-10-14, N=3 runs).** The eval agent is a Claude Code
  subagent, whose output is framed as a report to a parent agent. In 3 of
  138 trials across two N=3 runs, its turn 1 reply read as a third-person
  report ("I asked the user whether...") instead of addressing the user.
  The judge failed those replies even though every deterministic assertion
  passed. Judge items on reply wording carry this noise. No change is
  made.
- Strict `index_read_first` grades execution order as the server saw it.
  A host that serializes a batched pair may let it pass.
- Calls that MCP rejects during argument validation never reach `on_call`,
  so graders do not see them.
- An SDK driver needs only to produce `store.json`, `trace.json`, and
  `transcript.json`. Everything else is reused.
- Live runs are manual. A pull request that changes the harness or the
  prompt should report one live run.
