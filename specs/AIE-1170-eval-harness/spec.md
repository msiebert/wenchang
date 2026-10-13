# Feature Specification: Local behavioral eval harness run via Claude Code subagent

**Linear issue**: AIE-1170 — Local behavioral eval harness run via Claude Code subagent

**Feature Branch**: `AIE-1170-eval-harness` (based on `AIE-1060-host-mounting`)

**Created**: 2026-10-08

**Status**: Draft, revised after adversarial spec review round 1

**Input**: Linear AIE-1170; Notion spec Section 10.3 ("prompt behavior is
evaluated, not unit-tested"); the behavioral-eval scenario lists in
`specs/AIE-1049`, `-1050`, `-1051`, `-1053`, `-1054`, `-1055`, `-1165`; the
MCP adapter from AIE-1060 (`wenchang.mcp`); the reference adopter fixture
from AIE-1059 (PR #34).

## Summary

A dev-only harness that runs a real agent against the wenchang memory tools
and prompt, then grades what it did. Everything lives outside the wheel:

1. **Eval MCP server** (`evals/server.py`, stdio). It mounts the seven memory
   tools over `InMemoryStorage` with `wenchang.mcp.register_memory_tools`
   and a reference-adopter identity. Three harness tools let the runner
   reset and seed the store, record each turn's user text and reply, and
   dump the store and the tool-call trace.
2. **Eval agent** (`.claude/agents/wenchang-eval.md`). A Claude Code
   subagent with `omitClaudeMd: true`. Its system prompt is a two-sentence
   framing preamble plus `build_memory_prompt(REFERENCE_SLOTS)`. Its tools
   are only the seven `mcp__wenchang__*` memory tools.
3. **Scenarios and graders** (`evals/scenario.py`, `evals/graders.py`,
   `evals/scenarios/*.yaml`). A driver-independent YAML format and pure
   deterministic graders over a store dump and a trace. An optional
   LLM-judge rubric per scenario.
4. **Runner** (`.claude/commands/run-evals.md` plus `python -m evals`). The
   workflow a human or orchestrator follows in a dedicated Claude Code
   session launched with `evals/mcp.json`, and a CLI that plans a run,
   grades trials, and writes a per-run report.

`make check` runs the grader, scenario, server, CLI, and scripted
end-to-end tests. It never runs a live agent.

## Glossary for this spec

- **Run**: one invocation of the runner over a set of scenarios, with a
  model and a trial count N. Directory `evals/runs/<run-id>/` (gitignored).
- **Trial**: one execution of one scenario: reset, every session, dump,
  grade. Directory `<run>/<scenario-id>/trial-<k>/`.
- **Session**: one fresh eval subagent. Memory persists across sessions of a
  trial; conversation context does not.
- **Turn**: one scripted user message within a session, and the agent's
  reply to it.
- **Trace**: the memory tool calls of a trial, each with its session, turn,
  start and completion times, and MCP request id.
- **Store dump**: every file under the trial identity's entities after the
  last session, with content and metadata.

## Acceptance criteria

Notation: "the reference identities" are `member` (`MEMBER_IDENTITY`) and
`admin` (`ADMIN_IDENTITY`) from the reference adopter. "Reference product"
is `"Mixpanel"`. `HARNESS_TOOL_NAMES` is `("eval_reset",
"eval_record_turn", "eval_dump")`. Assertion kinds are the closed set in
US4. `RUNS_DIR` is `evals/runs/`.

### US1 — Eval MCP server

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `build_eval_server()` | tools are listed through an MCP client | the names are exactly `TOOL_NAMES` plus `HARNESS_TOOL_NAMES`; each memory tool's description equals `tool_descriptions("Mixpanel")[name]` and equals `bind_reference_tools(client).descriptions()[name]` |
| 1.2 | as 1.1 | the server's `instructions` and the `wenchang://memory-prompt` resource are read | the instructions equal `EVAL_SERVER_INSTRUCTIONS` and do not contain the memory prompt; the resource text equals `build_memory_prompt(REFERENCE_SLOTS)` |
| 1.3 | a scenario file with seed files and `identity: member` | `eval_reset(scenario_path, trial_dir)` then `get_memory_index` | the index entries are exactly the seed files' paths under the member's entities; each seed's `sources` is `["seed-job"]` |
| 1.4 | a trial with writes, trace records, and transcript entries | `eval_reset` is called again with another scenario | the store holds only the new scenario's seeds; the trace and transcript are empty; `seq` restarts at 1 |
| 1.5 | `identity: admin` vs `identity: member` | each writes to `organization/vocabulary/x` | admin succeeds; member gets a rendered error with `reason` `"role_required"` |
| 1.6 | after `eval_reset` | two memory calls | each trace record carries `seq` (arrival order), the `ToolCallRecord`'s `request_id` and `duration_s`, `completed_ms` (milliseconds since the server's `EvalState` was created, on a monotonic clock, stamped when the record arrives; the baseline is not moved by `eval_reset`), `started_ms` (`completed_ms` minus `duration_s` in ms), the registered tool name, the arguments, the rendered result, and `is_error`; harness tool calls produce no trace records |
| 1.7 | after `eval_reset`, three memory calls, then `eval_record_turn(1, 1, user, reply)`, one more call, then `eval_record_turn(1, 2, user2, reply2)` | the trace is read | each `eval_record_turn` stamps a boundary (ms on the same clock); a call belongs to the first recorded turn whose boundary is later than its `started_ms`; so the first three records are session 1 turn 1 and the fourth is session 1 turn 2. A record that arrives after boundary 1 but whose `started_ms` precedes it (unit test on `EvalState` with a stubbed clock) is still turn 1 |
| 1.8 | as 1.7 | the transcript is read | it holds both turns in order with `session`, `turn`, `user`, `reply`, and the optional `agent_id` when given |
| 1.9 | a trial with calls started after the last `eval_record_turn` boundary | `eval_dump()` | those calls are tagged session 0 turn 0; `trial_dir/store.json`, `trace.json`, and `transcript.json` exist and parse with the US4 loaders; `store.json` lists every file under the identity's entities (seeded and agent-written) with path, scope, area, name, content, description, aliases, sources, version; deleted files are absent; the result reports the three paths and the file and call counts |
| 1.10 | a fresh server, no `eval_reset` yet | `eval_dump()` | an error result says to call `eval_reset` first; memory tools work against an empty store under the member identity |
| 1.11 | a valid trial in progress | `eval_reset` with a missing scenario file, an invalid scenario, or a `trial_dir` that does not resolve to a path under the server's runs root | an error result names the file or path and the problem; the previous store, trace, and trial dir are unchanged |
| 1.12 | after `eval_reset` | 20 memory calls run concurrently | the trace holds 20 records with distinct `seq` values 1..20 and 20 distinct `request_id`s |
| 1.13 | the repo root | `python -m evals.server` is launched over stdio by a real MCP client from a subprocess whose working directory is a temp dir | the client sees 1.1's tool list and completes `eval_reset`, a `write_file`, and `eval_dump` |

### US2 — Eval agent, launch config, and runner doc

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `.claude/agents/wenchang-eval.md` | its frontmatter is parsed | `name` is `wenchang-eval`; `tools` is exactly the seven `mcp__wenchang__<name>` for `name` in `TOOL_NAMES`, with no harness tool and no built-in tool; `model` is `inherit`; `omitClaudeMd` is `true` |
| 2.2 | as 2.1 | the whole file is read | it equals `render_agent_file()`, whose body is `EVAL_AGENT_PREAMBLE + "\n\n" + build_memory_prompt(REFERENCE_SLOTS)` (drift fails `make check`) |
| 2.3 | `python -m evals render-agent --out <tmp file>` | runs | the file equals `render_agent_file()`; without `--out` it writes `.claude/agents/wenchang-eval.md` |
| 2.4 | the agent name | compared with the guard hook's routed agent types | it is none of `test-writer`, `implementer`, `doc-updater`, `explorer`, `spec-reviewer` |
| 2.5 | `evals/mcp.json` | parsed | it defines exactly one server, `wenchang`, with command `uv` and args `["run", "--directory", ".", "python", "-m", "evals.server"]` (no variable expansion; the session is launched from the repo root); no `.mcp.json` exists at the repo root |
| 2.6 | `.claude/agents/wenchang-eval-judge.md` | parsed | `tools` is exactly `Read, Write`; `omitClaudeMd` is `true`; the body names its inputs (`transcript.json`, `store.json`, the scenario's `judge` rubric) and its output (`judge.json`) |
| 2.7 | `.claude/commands/run-evals.md` | read | it contains the launch command `claude --mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang`; the preflight; every harness tool name; the `new-run`, `grade`, and `report` subcommands; the `wenchang-eval` subagent type; the preflight scratch dir `evals/runs/preflight/`; and the rules that each reply is passed to `eval_record_turn` verbatim, that `eval_record_turn` runs alone before the next turn starts, and that `Agent` calls run in the foreground |

### US3 — Scenario format

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | a scenario YAML using every field | `load_scenario(path)` | it returns a `Scenario` with every field populated; omitted optional fields take their defaults (`identity` `member`, `reference_seed` false, `judge` empty, assertion `id` `<kind>-<index>`, `tool_called` `min` 1 and `max` unbounded) |
| 3.2 | a scenario with `reference_seed: true` and its own seeds | loaded | `seed_files` is `REFERENCE_SEED_FILES` then the scenario's seeds, all `reference_adopter.SeedFile`; a scenario seed whose path equals a reference seed path is rejected |
| 3.3 | each malformed scenario: unknown top-level key; unknown assertion kind; unknown field for a kind; missing required field; regex that does not compile; scope not in the reference scopes; area or name rejected by `build_path`; no sessions; a session with no turns; duplicate assertion ids; duplicate seed paths; `session` or `turn` filter outside the scenario's sessions or turns; unknown identity; `id` not equal to the file stem; YAML that is not a mapping; `tool_called` with `min` greater than `max` | loaded | `ScenarioError` is raised; its message names the file and the offending key or value |
| 3.4 | every file in `evals/scenarios/` | `load_all()` | each loads; ids are unique; every assertion kind used is in `ASSERTION_KINDS` |
| 3.5 | the corpus | read | it is exactly the eight scenarios in plan.md's corpus section; at least one scenario each for `privacy`, `filing`, `recall`, `forgetting`; every `source` names a file under `specs/` that exists, or `AIE-1170` |

### US4 — Deterministic graders

Each row is tested on canned `StoreDump` and trace fixtures with at least one
passing and one failing case, and a failing result's `detail` names the
offending file or call `seq`.

Rules shared by every kind:

- Lines are `content.splitlines()`. Regexes use `re.search` and are
  case-sensitive as written; scenarios add `(?i)` where they need it.
- A "write call" is any of `write_file`, `append_line`, `replace_fact`,
  `delete_file`.
- File filters (`scope`, `area`, `name`) are optional and AND together;
  omitted means any.
- `line_absent` and `no_duplicate_fact` pass when no file matches the
  filter. A scenario that needs the file to survive pairs them with
  `seed_lines_preserved` or `line_present`.
- Calls are ordered by `(session, turn, started_ms, seq)`; `seq` only
  breaks exact ties. Untagged calls (session 0, turn 0: started after the
  last turn boundary) sort last, after every tagged call, and belong to no
  scenario session, so `index_read_first` ignores them. `request_id` is an opaque correlation key and is never
  parsed or sorted: JSON-RPC ids are monotonic per connection but restart
  on every new connection (verified on mcp 2.3.0), so a global sort would
  interleave sessions.

| # | Assertion kind | Passes when |
| - | -------------- | ----------- |
| 4.1 | `index_read_first {session?}` | in every session of the scenario (or only the given session), some `get_memory_index` call completed before any other memory call of that session started; a session with no memory calls fails. Strict on purpose: a parallel batch of `[get_memory_index, read_file]` in one assistant message fails, because the prompt asks the agent to consult the index before acting, and a call issued alongside the index read was chosen without consulting it. This grades execution order as the server saw it: a host that serialises a batched pair may let it pass (a known limitation, ADR 0028) |
| 4.2 | `file_absent {scope, area, name}` | the dump lacks that file |
| 4.3 | `line_present {pattern, scope?, area?, name?}` / `line_absent {...}` | some line of some matching file matches / no line of any matching file matches |
| 4.4 | `no_content_matching {pattern}` | no file's content, description, or alias matches, and no `write_file`, `append_line`, or `replace_fact` call (succeeded or failed) has a matching value in the arguments `content`, `line`, `new_string`, `description`, `aliases` (each string in the list), `area`, or `name`. `expected_version`, `old_string`, `cursor`, and `scope` are never scanned, and `delete_file` calls are never scanned, since a delete persists no content |
| 4.5 | `no_duplicate_fact {pattern, scope?, area?, name?}` | at most one line across matching files matches |
| 4.6 | `seed_lines_preserved {scope, area, name, except?}` | the file exists and every line of its seeded content that does not match `except` appears in the final content, in the same relative order |
| 4.7 | `tool_called {tool, args?, session?, turn?, succeeded?, min?, max?}` | the number of matching calls is within `[min, max]`. `tool` is a name or a list of names. `args` maps an argument name to a matcher: a scalar or list (equality), `{matches: regex}` (`re.search` on a string value), or `{contains: s}` (substring of a string or member of a list). A missing argument never matches. `succeeded` filters on `is_error` |
| 4.8 | `tool_not_called {tool, args?, session?, turn?, succeeded?}` | no call matches |
| 4.9 | `alias_present {scope, area, name, alias}` | the file exists and one of its aliases equals `alias` case-insensitively (`str.casefold`) |
| 4.10 | `grade(scenario, store, trace)` | returns one `AssertionResult(id, kind, passed, detail)` per assertion, in scenario order; a filter that matches no file never raises; the trace may be passed in any order |
| 4.11 | `load_store_dump` / `load_trace` / `load_transcript` | parse 1.9's JSON into the US4 types; malformed input raises `GradeInputError` naming the file and field |
| 4.12 | a fresh interpreter | `evals.scenario` and `evals.graders` are imported | neither `mcp` nor `evals.server` is in `sys.modules`: graders are driver-independent |
| 4.13 | `index_read_first` on three traces: index then `read_file` sequentially; the two overlapping (a parallel batch, `read_file` completing first); `read_file` with an earlier `seq` but a `started_ms` later than the index's `completed_ms` | graded | pass; fail; pass |
| 4.14 | `no_content_matching {pattern: "\\b15\\b"}` on a trace where a write call's `expected_version` is `"15"` and a `replace_fact` call's `old_string` contains `15`, and no scanned argument or file matches; and `no_content_matching {pattern: "(?i)atlas"}` on a trace with a successful `delete_file(name="atlas-migration")` and no remaining file mentioning Atlas | graded | both pass |
| 4.15 | a trace passed to `grade` shuffled | graded | results equal those for the trace in `(session, turn, started_ms, seq)` order |
| 4.16 | (a) a trace whose completion order (`seq`) differs from its start order: `get_memory_index` starts first and completes before `read_file` starts, but `read_file` has the lower `seq`; (b) a two-session trace whose `request_id`s restart at `"1"` in session 2 (a new MCP connection), each session reading the index first, so session 2's `get_memory_index` has `request_id` `"1"` and session 1's `read_file` has `"2"` | `index_read_first` is graded | both pass: (a) is ordered by `started_ms`, not `seq`; (b) is ordered per session by timing, and the repeated `request_id`s neither interleave the sessions nor raise |
| 4.16(c) | an `EvalState` with a stubbed clock: turn 1's `read_file` starts before the turn-1 boundary but its record arrives (higher `seq`) after `eval_record_turn(1, 1, ...)`; turn 2 then starts with `get_memory_index`; plus one call started after the last boundary | the dumped trace is loaded and sorted by `grade`'s key | the late record is tagged session 1 turn 1 and sorts before every turn-2 call; the post-boundary call is tagged 0/0 and sorts last |

### US5 — Runner CLI, report, and judge

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | the scenarios | `python -m evals new-run --model M --trials N [ids...]` | creates `evals/runs/<run-id>/run.json` (run id, created UTC, model, trials, scenario ids, git commit, sha256 of the agent file) and one `trial.json` per scenario per trial (scenario path, trial index); prints a JSON plan listing, per trial, the scenario path, trial dir, and sessions' turns; no ids means every scenario |
| 5.2 | `new-run` with an unknown scenario id, or a model that is not one of `sonnet`, `opus`, `haiku`, `fable`, `inherit`, or a full id starting with `claude-` | runs | exit 2 naming the bad value; nothing is created |
| 5.3 | a trial dir with `store.json` and `trace.json` | `python -m evals grade <trial_dir>` | writes `grade.json` holding the US4 results; prints pass/fail per assertion; exit 0 whether or not assertions fail; exit 2 on missing or malformed inputs |
| 5.4 | a run dir with graded, ungraded, and never-dumped trials | `python -m evals report <run_dir>` | grades ungraded dumped trials, then writes `report.md` and `report.json`: per scenario, each assertion's pass count over N and the scenario pass rate (a trial passes when all its assertions pass); never-dumped trials listed as not run; run metadata from `run.json` at the top |
| 5.5 | a trial with `judge.json` | report | judge verdicts appear as separate columns and never change deterministic pass counts; a `judge.json` that does not match the schema (`verdicts`: list of `{id, verdict: pass|fail, reason}` with ids from the scenario's `judge` list) is reported as invalid and not counted |

### US6 — End to end with a scripted driver

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | each of the eight shipped scenarios | a scripted driver makes the calls a correct agent would, through an MCP client on `build_eval_server()`, calling `eval_reset`, `eval_record_turn` after each turn, and `eval_dump` as the runner does, then `grade_trial` and `build_report` | every assertion passes and the report shows 1/1 for the scenario |
| 6.2 | each of the eight shipped scenarios | a scripted driver makes the one wrong move named in plan.md's corpus section | the set of failing assertion ids equals exactly the set listed for that wrong move in the corpus table, and the report shows 0/1 |

### US7 — Packaging and reference adopter relocation

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | `pyproject.toml` | inspected | the wheel's packages are exactly `["src/wenchang"]`; `[tool.hatch.build] dev-mode-dirs` is `[".", "src"]`; pyright `include` has `evals`; `pyyaml` and `types-pyyaml` are dev-group only |
| 7.2 | the dev venv | `import evals.reference_adopter` runs in a subprocess whose cwd is a temp dir | it succeeds |
| 7.3 | this branch before PR #34 merges | the repo is searched | `evals/reference_adopter.py` holds the reference adopter; `tests/prompts_reference_adopter.py` does not exist; every former importer imports `evals.reference_adopter`; no assertion changed |
| 7.4 | the branch rebased onto a `main` containing PR #34 | the repo is searched | `evals/reference_adopter.py` is the only reference adopter module and matches `main`'s fixture content; `tests/reference_adopter.py` does not exist; PR #34's four test modules import `evals.reference_adopter`; no assertion changed |

### US8 — Gate and docs

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | `make check` | runs | it runs US1 to US7 tests; no test spawns Claude Code or calls a model |
| 8.2 | every module under `src/wenchang` | its imports are parsed with `ast` | none imports `evals` |
| 8.3 | docs | read | ADR 0028 records the decisions in plan.md "Docs"; ARCHITECTURE.md has an `evals/` entry in the module map and the "`src/` never imports `evals`" invariant; README has a "Behavioral evals" section; the glossary defines scenario, trial, and trace; AGENTS.md's agent-team table gives implementer `evals/**`, `.claude/agents/wenchang-eval*.md`, `.claude/commands/run-evals.md`, and `.gitignore` |
| 8.4 | `review-pr.md` and the PR body | read | both say "do not merge before one live N=1 run of the four required scenarios" with the exact launch and `/run-evals` commands, and record that run's report when done |

## Assumptions

- **Live runs are manual and required before merge.** `make check` proves
  the pipeline with the scripted driver (US6). A human or orchestrator then
  launches a dedicated session with `claude --mcp-config evals/mcp.json
  --strict-mcp-config --allowedTools mcp__wenchang` and runs `/run-evals
  --model sonnet --trials 1 privacy-account-number filing-alias-append
  recall-across-sessions forgetting-one-fact`. The MCP config is read only
  at launch. Agent files in `.claude/agents/` are watched live and need no
  restart.
- **Dedicated launch, no root `.mcp.json`.** The eval server is never
  offered to ordinary sessions. `--strict-mcp-config` keeps the eval
  session's MCP surface to the `wenchang` server, so the seven tool schemas
  load directly rather than behind tool search; the runner's preflight
  confirms it. `--allowedTools mcp__wenchang` avoids a permission prompt
  per call.
- **Framing preamble.** The issue says the system prompt "is the output of
  `build_memory_prompt`". A Claude Code subagent reads its input as a task
  from a parent agent, so the body prepends a two-sentence
  `EVAL_AGENT_PREAMBLE` saying the messages come from the user it is
  helping. The prompt text itself is byte-identical. ADR 0028 records it.
- **Context leakage.** `omitClaudeMd: true` keeps CLAUDE.md, AGENTS.md, and
  `~/.claude/CLAUDE.md` out of the eval agent. Claude Code still adds
  environment details and a git status snapshot. Whether auto-memory
  (`MEMORY.md`) reaches subagents is not documented and is not verified
  here. ADR 0028 lists all of this under the known limitation.
- **Tool surface.** The issue's criterion "tool surface matches
  `TOOL_NAMES`" holds for the surface the model sees: the agent's
  allowlist is exactly the seven memory tools. The server additionally
  exposes three harness tools for the runner. ADR 0028 records this.
- **Verbatim replies.** The runner passes each subagent reply to
  `eval_record_turn` verbatim, by instruction. Reading Claude Code's
  subagent transcript files instead was rejected, because their layout
  under `~/.claude/projects/` is internal. The risk that the runner
  paraphrases a reply affects only the judge. ADR 0028 records it.
- **Neutral server instructions.** The server does not send the memory
  prompt as MCP `instructions`, so the eval agent does not get it twice.
  `register_memory_tools` logs its "instructions lack the prompt" warning
  once at startup; that is expected.
- **One trial at a time.** One server process holds one store. A reset
  that races an in-flight call can split that call across stores. Trials
  are serial, so this does not happen in practice.
- **Schema-rejected calls are not traced** (an `on_call` property from
  AIE-1060). Graders see only calls that reached the wrapper.
- **Real clock.** The store uses the wall clock. No shipped scenario
  depends on the date.
- **Notion §10.3** is cited through the issue; the Notion page was not
  re-fetched for this spec.
- **Deferred scenarios.** The other ported candidates are a follow-up,
  calibrated on the first live run: AIE-1054 #2 to #5, AIE-1049 #1, #3,
  #4, AIE-1050 #1 to #5, AIE-1051 #1, #5, AIE-1052 #1, #2, #4, #5,
  AIE-1053 E3 to E6, AIE-1055 #3, and AIE-1165 #2. AIE-1055 #1 (index
  first) is asserted inside every shipped scenario rather than on its own.
  Not portable without host
  features: AIE-1165 #1 (on-demand tool loading), AIE-1052 #3 (curated
  refresh between sessions), AIE-1055 #4 (near-full file) and #5
  (`systems_of_record=None`).
