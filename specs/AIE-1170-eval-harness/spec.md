# Feature Specification: Local behavioral eval harness run via Claude Code subagent

**Linear issue**: AIE-1170 — Local behavioral eval harness run via Claude Code subagent

**Feature Branch**: `AIE-1170-eval-harness` (based on `AIE-1060-host-mounting`)

**Created**: 2026-10-08

**Status**: Draft

**Input**: Linear AIE-1170; Notion spec Section 10.3 ("prompt behavior is
evaluated, not unit-tested"); the behavioral-eval scenario lists in
`specs/AIE-1049`, `-1050`, `-1051`, `-1052`, `-1053`, `-1054`, `-1055`,
`-1165`; the MCP adapter from AIE-1060 (`wenchang.mcp`); the reference
adopter fixture from AIE-1059 (PR #34).

## Summary

A dev-only harness that runs a real agent against the wenchang memory tools
and prompt, then grades what it did. Four parts, all outside the wheel:

1. **Eval MCP server** (`evals/server.py`, stdio): the seven memory tools
   over `InMemoryStorage`, mounted with `wenchang.mcp.register_memory_tools`
   and a sandbox identity from the reference adopter, plus four harness
   tools the runner uses to reset and seed the store, tag turns, record
   replies, and dump state and the tool-call trace.
2. **Eval agent** (`.claude/agents/wenchang-eval.md`): a Claude Code
   subagent whose system prompt is a fixed two-sentence framing plus
   `build_memory_prompt(REFERENCE_SLOTS)`, and whose tools are only the
   seven `mcp__wenchang__*` memory tools.
3. **Scenarios and graders** (`evals/scenario.py`, `evals/graders.py`,
   `evals/scenarios/*.yaml`): a driver-independent YAML format and pure
   deterministic graders over a store dump and a trace. An optional
   LLM-judge rubric per scenario.
4. **Runner** (`.claude/commands/run-evals.md` plus `python -m evals`): the
   workflow the orchestrator follows, and a CLI that plans a run, grades
   trials, and writes a per-run report.

Only the grader, scenario-loader, server, CLI, and scripted end-to-end
tests run under `make check`. Live agent runs never do.

## Glossary for this spec

- **Run**: one invocation of the runner over a set of scenarios, with a
  model and a trial count N. Directory `evals/runs/<run-id>/` (gitignored).
- **Trial**: one execution of one scenario: reset, every session, dump,
  grade. Directory `<run>/<scenario-id>/trial-<k>/`.
- **Session**: one fresh eval subagent. Memory persists across sessions of a
  trial; conversation context does not.
- **Turn**: one scripted user message within a session.
- **Trace**: the ordered memory tool calls of a trial, each tagged with its
  session and turn.
- **Store dump**: every file under the trial identity's entities after the
  last session, with content and metadata.

## Acceptance criteria

Notation: "the reference identities" are `member` (`MEMBER_IDENTITY`) and
`admin` (`ADMIN_IDENTITY`) from the reference adopter. "Reference product"
is `"Mixpanel"`. `HARNESS_TOOL_NAMES` is `("eval_reset", "eval_begin_turn",
"eval_record_turn", "eval_dump")`. Assertion kinds are the closed set in
US4.

### US1 — Eval MCP server

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `build_eval_server()` | tools are listed through an MCP client | the names are exactly `TOOL_NAMES` plus `HARNESS_TOOL_NAMES`; each memory tool's description equals `tool_descriptions("Mixpanel")[name]` and equals `bind_reference_tools(client).descriptions()[name]` |
| 1.2 | as 1.1 | the server's `instructions` and the `wenchang://memory-prompt` resource are read | the instructions equal `EVAL_SERVER_INSTRUCTIONS` and do not contain the memory prompt; the resource text equals `build_memory_prompt(REFERENCE_SLOTS)` |
| 1.3 | a scenario file with seed files and `identity: member` | `eval_reset(scenario_path, trial_dir)` then `get_memory_index` | the index entries are exactly the seed files' paths under the member's entities; each seed's `sources` is `["seed-job"]` |
| 1.4 | a trial with writes and trace records | `eval_reset` is called again with another scenario | the store holds only the new scenario's seeds; the trace and transcript are empty; the trace `seq` restarts at 1 |
| 1.5 | `identity: admin` vs `identity: member` | each writes to `organization/vocabulary/x` | admin succeeds; member gets a rendered error with `reason` `"role_required"` |
| 1.6 | after `eval_reset` | `eval_begin_turn(session=1, turn=2)`, then two memory calls | both trace records carry `session` 1, `turn` 2, consecutive `seq` (arrival order), the `ToolCallRecord`'s `request_id` and `duration_s`, the registered tool name, the arguments, the rendered result, and `is_error`; harness tool calls produce no trace records |
| 1.7 | after `eval_reset` and before any `eval_begin_turn` | a memory call | its record carries `session` 0 and `turn` 0 |
| 1.8 | after `eval_reset` | `eval_record_turn(session, turn, user, reply)` twice | the transcript holds both entries in order |
| 1.9 | a trial after some calls | `eval_dump()` | `trial_dir/store.json`, `trace.json`, and `transcript.json` exist and parse with the US4 loaders; `store.json` lists every file under the identity's entities (seeded and agent-written) with path, scope, area, name, content, description, aliases, sources, version; deleted files are absent; the result reports the three paths and the file and call counts |
| 1.10 | a fresh server, no `eval_reset` yet | `eval_dump()` | an error result says to call `eval_reset` first; memory tools work against an empty store under the member identity |
| 1.11 | a valid trial in progress | `eval_reset` with a missing or invalid scenario | an error result names the file and the problem; the previous store, trace, and trial dir are unchanged |
| 1.12 | after `eval_reset` | 20 memory calls run concurrently | the trace holds 20 records with distinct `seq` values 1..20 and 20 distinct `request_id`s, each the id of the MCP request that produced it |
| 1.13 | the repo root | `python -m evals.server` is launched over stdio by a real MCP client (subprocess, any working directory) | the client sees 1.1's tool list and completes `eval_reset`, a `write_file`, and `eval_dump` |

### US2 — Eval agent definition and server registration

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `.claude/agents/wenchang-eval.md` | its frontmatter is parsed | `name` is `wenchang-eval`; `tools` is exactly the seven `mcp__wenchang__<name>` for `name` in `TOOL_NAMES`, with no harness tool and no built-in tool; `model` is `inherit` |
| 2.2 | as 2.1 | its body is read | it equals `render_agent_body()`, which is `EVAL_AGENT_PREAMBLE + "\n\n" + build_memory_prompt(REFERENCE_SLOTS)` |
| 2.3 | the checked-in agent file | `python -m evals render-agent --check` runs | exit 0 when the file equals `render_agent_file()`; exit 1 with a message naming the file after any byte of it changes |
| 2.4 | the agent name | compared with the guard hook's routed agent types | it is none of `test-writer`, `implementer`, `doc-updater`, `explorer`, `spec-reviewer` |
| 2.5 | `.mcp.json` at the repo root | parsed | it defines exactly one server, `wenchang`, a stdio command running `uv run --directory <repo> python -m evals.server` with `${CLAUDE_PROJECT_DIR}` as the directory |

### US3 — Scenario format

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | a scenario YAML using every field | `load_scenario(path)` | it returns a `Scenario` with every field populated; omitted optional fields take their defaults (`identity` `member`, `reference_seed` false, `judge` empty, assertion `id` `<kind>-<index>`) |
| 3.2 | a scenario with `reference_seed: true` and its own seeds | loaded | `seed_files` is `REFERENCE_SEED_FILES` then the scenario's seeds; a scenario seed whose path equals a reference seed path is rejected |
| 3.3 | each malformed scenario: unknown top-level key; unknown assertion kind; unknown field for a kind; missing required field; regex that does not compile; scope not in the reference scopes; area or name rejected by `build_path`; no sessions; a session with no turns; duplicate assertion ids; duplicate seed paths; `session` or `turn` filter outside the scenario's sessions or turns; unknown identity; `id` not equal to the file stem; YAML that is not a mapping | loaded | `ScenarioError` is raised; its message names the file and the offending key or value |
| 3.4 | every file in `evals/scenarios/` | loaded | each loads; ids are unique |
| 3.5 | the corpus | categories are read | at least one scenario each for `privacy`, `filing`, `recall`, `forgetting`; every scenario's `source` names a file under `specs/` that exists (or `AIE-1170` for scenarios the issue itself specifies) |

### US4 — Deterministic graders

Each row is tested on canned `StoreDump` and trace fixtures with at least one
passing and one failing case, and a failing result's `detail` names the
offending file or call `seq`.

**Call order.** `on_call` records arrive in completion order, so `seq` is
only an arrival tag. Order-sensitive checks (4.1's "first call", 4.10) use
issue order: ascending integer `request_id` when every record's
`request_id` in the trace is a decimal integer (MCP clients, Claude Code
included, number requests monotonically per connection), else `seq`. 4.16
pins this.

Lines are `content.splitlines()`. Regexes use `re.search`. A "write call" is
any of `write_file`, `append_line`, `replace_fact`, `delete_file`. File
filters (`scope`, `area`, `name`) are optional and AND together; omitted
means any.

| # | Assertion kind | Passes when |
| - | -------------- | ----------- |
| 4.1 | `index_read_first {session?}` | in every session that has turns (or only the given session), the first memory call is `get_memory_index`; a session with no memory calls fails |
| 4.2 | `file_exists {scope, area, name}` / `file_absent {...}` | the dump has / lacks that file |
| 4.3 | `line_present {pattern, scope?, area?, name?}` / `line_absent {...}` | some line of some matching file matches / no line of any matching file matches |
| 4.4 | `no_content_matching {pattern}` | no file's content, description, or alias matches, and no write call (succeeded or failed) has a string argument, or a string inside a list argument, that matches |
| 4.5 | `no_duplicate_fact {pattern, scope?, area?, name?}` | at most one line across matching files matches |
| 4.6 | `seed_lines_preserved {scope, area, name, except?}` | the file exists and every line of its seeded content that does not match `except` appears in the final content, in the same relative order |
| 4.7 | `file_unchanged {scope, area, name}` | the file exists and its content, description, and aliases equal the seed's |
| 4.8 | `tool_called {tool, args?, session?, turn?, succeeded?, min?, max?}` | the number of matching calls is within `[min, max]` (`min` defaults to 1, `max` to unbounded). `tool` is a name or a list of names. `args` maps an argument name to a matcher: a scalar or list (equality), `{matches: regex}` (`re.search` on a string value), or `{contains: s}` (substring of a string or member of a list). A missing argument never matches. `succeeded` filters on `is_error` |
| 4.9 | `tool_not_called {tool, args?, session?, turn?, succeeded?}` | no call matches |
| 4.10 | `called_before {first, then, session?}` | `first` and `then` are call matchers as in 4.8 (without counts); either no call matches `then`, or a call matching `first` precedes the earliest call matching `then` |
| 4.11 | `max_tool_calls {max, tool?, session?, turn?}` | the number of matching calls is at most `max` |
| 4.12 | `alias_present {scope, area, name, alias}` / `alias_absent {...}` | the file exists and has / the file is absent or lacks the alias |
| 4.13 | `grade(scenario, store, trace)` | returns one `AssertionResult(id, kind, passed, detail)` per assertion, in scenario order; a filter that matches no file never raises |
| 4.14 | `load_store_dump` / `load_trace` / `load_transcript` | parse 1.9's JSON into the US4 types; malformed input raises `GradeInputError` naming the file and field |
| 4.15 | a fresh interpreter | `evals.scenario` and `evals.graders` are imported | neither `mcp` nor `evals.server` is in `sys.modules`: graders are driver-independent |
| 4.16 | a trace whose completion order differs from its issue order (`read_file` with `request_id` "7", `seq` 1; `get_memory_index` with `request_id` "6", `seq` 2); and the same trace with a non-integer `request_id` | `index_read_first` and `called_before {first: get_memory_index, then: read_file}` are graded | the first trace is ordered by `request_id`, so both pass; the second falls back to `seq`, so both fail |

### US5 — Runner CLI, report, and judge

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 5.1 | the scenarios | `python -m evals new-run --model M --trials N [ids...]` | creates `evals/runs/<run-id>/run.json` (run id, created UTC, model, trials, scenario ids, git commit, sha256 of the agent file) and one `trial.json` per scenario per trial (scenario path, trial index); prints a JSON plan listing, per trial, the scenario path, trial dir, and sessions' turns; unknown ids exit 2 naming them; no ids means every scenario |
| 5.2 | a trial dir with `store.json` and `trace.json` | `python -m evals grade <trial_dir>` | writes `grade.json` holding the US4 results; prints pass/fail per assertion; exit 0 whether or not assertions fail; exit 2 on missing or malformed inputs |
| 5.3 | a run dir with graded, ungraded, and never-dumped trials | `python -m evals report <run_dir>` | grades ungraded dumped trials, then writes `report.md` and `report.json`: per scenario, each assertion's pass count over N, the scenario pass rate (a trial passes when all its assertions pass), never-dumped trials listed as not run; run metadata from `run.json` at the top |
| 5.4 | a trial with `judge.json` | report | judge verdicts appear as separate columns; they never change deterministic pass counts; `judge.json` that does not match the schema (list of `{id, verdict: pass|fail, reason}` with ids from the scenario's `judge` list) is reported as invalid, not counted |
| 5.5 | `.claude/commands/run-evals.md` | read | it names every harness tool, every CLI subcommand, the `wenchang-eval` subagent type, and the one-time setup (approve the `wenchang` server, restart) |
| 5.6 | `.claude/agents/wenchang-eval-judge.md` | parsed | `tools` is exactly `Read, Write`; the body states the judge's inputs (`transcript.json`, `store.json`, the scenario's `judge` rubric) and output (`judge.json`) |

### US6 — End to end with a scripted driver

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 6.1 | each of the four required scenarios (one privacy, one filing, one recall across sessions, one forgetting) | a scripted driver makes the calls a correct agent would, through an MCP client on `build_eval_server()`, using the harness tools as the runner does, then `eval_dump`, `grade`, `report` | every assertion passes and the report shows 1/1 for the scenario |
| 6.2 | the same scenarios | a scripted driver makes one wrong call each (writes the account number; appends a duplicate instead of filing to the aliased file; a second session that never reads memory; a softened past-tense line instead of removal) | the targeted assertion fails and the report shows 0/1 |

### US7 — Reference adopter relocation (applies after PR #34 merges)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 7.1 | the branch rebased onto a `main` that contains PR #34 | the repo is searched | `evals/reference_adopter.py` is the only reference adopter module; `tests/reference_adopter.py` and `tests/prompts_reference_adopter.py` do not exist; every importer uses `evals.reference_adopter`; no assertion in those tests changed |
| 7.2 | `pyproject.toml` | inspected | the wheel's packages are exactly `["src/wenchang"]`; the editable install adds the repo root (`dev-mode-dirs`), so `import evals` works from any working directory in the dev venv; pyright `include` has `evals`; `pyyaml` and `types-pyyaml` are dev-group only |

### US8 — Gate and docs

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 8.1 | `make check` | runs | it runs US1 to US7 tests; no test spawns Claude Code or calls a model |
| 8.2 | every module under `src/wenchang` | its imports are parsed with `ast` | none imports `evals` |
| 8.3 | docs | read | ADR 0028 records the `evals/` boundary, the dev-only `mcp`/`pyyaml` dependencies, the driver-agnostic scenario and grader design, the eval server's neutral instructions, and the known Claude Code harness limitation; ARCHITECTURE.md has an `evals/` entry in the module map and the boundary rule; README has a "Behavioral evals" section; the glossary defines scenario, trial, and trace |

## Assumptions

- **Live runs are manual.** The agent file and `.mcp.json` load only at
  Claude Code session start, and the server needs one-time approval, so the
  live end-to-end run is done by a human or orchestrator in a fresh session.
  `make check` proves the pipeline with the scripted driver (US6). The PR
  reports one live run of the four required scenarios if one was done.
- **Framing preamble.** The issue says the system prompt "is the output of
  `build_memory_prompt`". A Claude Code subagent otherwise reads its input
  as a task from a parent agent, so the body prepends a two-sentence
  `EVAL_AGENT_PREAMBLE` saying the messages come from the user it is
  helping. The prompt text itself is byte-identical.
- **Neutral server instructions.** The server does not send the memory
  prompt as MCP `instructions`, so the orchestrator's own session is not
  told to act as a memory agent, and the eval agent does not get the prompt
  twice. `register_memory_tools` logs its "instructions lack the prompt"
  warning once at startup; that is expected.
- **One trial at a time.** One server process holds one store, so trials
  run serially.
- **Schema-rejected calls are not traced** (an `on_call` property from
  AIE-1060). Graders see only calls that reached the wrapper.
- **Real clock.** The store uses the wall clock; scenarios that depend on a
  date use dates far from today.
- **Notion §10.3** is cited through the issue; the Notion page was not
  re-fetched for this spec.
- **Scenario scope.** Scenarios needing host features the harness lacks are
  not ported: on-demand tool loading (AIE-1165 #1), a curated refresh
  between sessions (AIE-1052 #3), `systems_of_record=None` slots
  (AIE-1055 #5), and a near-size-limit file (AIE-1055 #4).
